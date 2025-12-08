# =======================================================================================
#                    WORKERS MODULE - Worker Tasks & Concurrent Processing
# =======================================================================================

import asyncio
import aiohttp
import ssl
import certifi
import re
import psutil
from asyncio import Queue
from playwright.async_api import BrowserContext, Browser, Page, TimeoutError, expect
from typing import Dict
from datetime import datetime

# Import API-first scraper for optimized data collection
from api_scraper import fetch_store_metrics_with_lates_browser


async def auto_concurrency_manager(concurrency_limit_ref: dict, last_change_ref: dict,
                                   auto_enabled: bool, auto_min: int, auto_max: int,
                                   cpu_upper: float, cpu_lower: float, mem_upper: float,
                                   check_interval: int, cooldown: int,
                                   failure_lock, failure_timestamps: list,
                                   concurrency_condition, app_logger):
    """Manages automatic concurrency scaling based on system resources and failure rate."""
    if not auto_enabled:
        return
    app_logger.info(f"Auto-concurrency enabled with range {auto_min}-{auto_max}")
    
    while True:
        now = asyncio.get_event_loop().time()
        
        # 1. Check Failure Rate (Error-Aware Scaling)
        async with failure_lock:
            while failure_timestamps and now - failure_timestamps[0] > 60:
                failure_timestamps.pop(0)
            recent_failure_count = len(failure_timestamps)
        
        estimated_throughput = concurrency_limit_ref['value'] * 30 
        failure_rate = recent_failure_count / max(estimated_throughput, 1)
        
        if failure_rate > 0.05: # >5% failure rate
            if now - last_change_ref['value'] >= cooldown:
                concurrency_limit_ref['value'] = max(auto_min, int(concurrency_limit_ref['value'] * 0.5))
                last_change_ref['value'] = now
                app_logger.warning(f"Auto-concurrency: THROTTLING DOWN to {concurrency_limit_ref['value']} due to high failure rate ({failure_rate:.1%})")
                async with concurrency_condition:
                    concurrency_condition.notify_all()
                await asyncio.sleep(cooldown * 2)
                continue

        # 2. Standard Resource Scaling
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        
        if now - last_change_ref['value'] >= cooldown:
            if (cpu > cpu_upper or mem > mem_upper) and concurrency_limit_ref['value'] > auto_min:
                concurrency_limit_ref['value'] -= 1
                last_change_ref['value'] = now
                app_logger.info(f"Auto-concurrency: decreased to {concurrency_limit_ref['value']} (CPU {cpu:.1f}%, MEM {mem:.1f}%)")
            elif cpu < cpu_lower and mem < mem_upper and concurrency_limit_ref['value'] < auto_max:
                concurrency_limit_ref['value'] += 1
                last_change_ref['value'] = now
                app_logger.info(f"Auto-concurrency: increased to {concurrency_limit_ref['value']} (CPU {cpu:.1f}%, MEM {mem:.1f}%)")
            
            if concurrency_limit_ref['value'] > auto_max:
                concurrency_limit_ref['value'] = auto_max
            if concurrency_limit_ref['value'] < auto_min:
                concurrency_limit_ref['value'] = auto_min
            async with concurrency_condition:
                concurrency_condition.notify_all()
        await asyncio.sleep(check_interval)


async def data_processor_worker(queue: Queue, worker_id: int, 
                              log_submission_func, progress_lock,
                              progress: dict, metrics_lock, metrics: dict,
                              run_failures: list, local_timezone,
                              debug_mode: bool, app_logger):
    """Worker that processes collected data for internal reporting (Dashboard/Chat) without external submission."""
    log_prefix = f"[Data-Processor-{worker_id}]"
    app_logger.info(f"{log_prefix} Starting up...")
    
    while True:
        form_data = None
        try:
            form_data = await queue.get()
            store_name = form_data.get('store', 'Unknown')
            
            # Log submission internally (Critical for Dashboard & Chat)
            # This appends to submitted_store_data_list strings which generates the report
            await log_submission_func(form_data)
            
            # Update Progress
            with progress_lock:
                progress["current"] += 1
                progress["lastUpdate"] = datetime.now(local_timezone).strftime("%H:%M:%S")
            
            # Update Metrics
            async with metrics_lock:
                # We don't have a submission time anymore, so just mark it as processed
                metrics["submission_times"].append((store_name, 0.0))
                
            # Log success
            # app_logger.info(f"{log_prefix} Processed {store_name}") # Optional: reduce noise by commenting out
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            failed_store = form_data.get('store', 'Unknown') if form_data else "Unknown"
            app_logger.error(f"{log_prefix} Unhandled exception for {failed_store}: {e}", exc_info=debug_mode)
            run_failures.append(f"{failed_store} (Processing Exception)")
        finally:
            if form_data:
                queue.task_done()
    
    app_logger.info(f"{log_prefix} Shut down.")


async def process_single_store(context: BrowserContext, store_info: Dict[str,str], queue: Queue,
                               worker_retry_count: int, resource_blocklist: list,
                               apply_date_range_func, wait_timeout: int, action_timeout: int,
                               metrics_lock, metrics: dict, run_failures: list,
                               failure_lock, failure_timestamps: list,
                               debug_mode: bool, app_logger):
    """Process a single store: navigate, scrape metrics, queue for form submission."""
    start_ts = asyncio.get_event_loop().time()
    merchant_id = store_info['merchant_id']
    store_name  = store_info['store_name']
    
    for attempt in range(worker_retry_count):
        page = None
        try:
            marketplace_id = store_info['marketplace_id']
            if not marketplace_id:
                app_logger.error(f"Skipping {store_name}: marketplace_id is missing.")
                run_failures.append(f"{store_name} (Missing MKID)")
                return

            page = await context.new_page()
            
            # Block resources on this page
            async def block_resources(route):
                if (any(domain in route.request.url for domain in resource_blocklist) or
                        route.request.resource_type in ("image", "stylesheet", "font", "media")):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", block_resources)

            dash_url = f"https://sellercentral.amazon.co.uk/snowdash?ref_=mp_home_logo_xx&cor=mmp_EU&mons_sel_dir_mcid={merchant_id}&mons_sel_mkid={marketplace_id}"
            await page.goto(dash_url, timeout=30000, wait_until="domcontentloaded")
            
            refresh_button_selector = "#content > div > div.mainAppContainerExternal > div.css-6pahkd.action-bar-container > div > div.filterbar-right-slot > kat-button:nth-child(2) > button"
            METRICS_TIMEOUT = 45_000
            
            # Wait for dashboard to be ready
            refresh_button = page.locator(refresh_button_selector)
            await expect(refresh_button).to_be_visible(timeout=wait_timeout)
            app_logger.info(f"[{store_name}] Dashboard loaded, refresh button visible")
            
            # Apply date/time range filter if configured
            date_range_applied = await apply_date_range_func(page, store_name)
            if not date_range_applied:
                app_logger.warning(f"[{store_name}] Proceeding without date range filter")
            
            # Wait for metrics response after clicking refresh
            async with page.expect_response(lambda r: "summationMetrics" in r.url and r.status == 200, timeout=METRICS_TIMEOUT) as resp_info:
                await refresh_button.click()
            
            response = await resp_info.value
            api_data = await response.json()

            formatted_lates = "0 %"
            try:
                header_second_row = page.locator("kat-table-head kat-table-row").nth(1)
                lates_cell = header_second_row.locator("kat-table-cell").nth(10)
                await expect(lates_cell).to_be_visible(timeout=10000)
                cell_text = (await lates_cell.text_content() or "").strip()
                app_logger.info(f"[{store_name}] Raw 'Lates' text scraped: '{cell_text}'")

                if re.fullmatch(r"\d+(\.\d+)?\s*%", cell_text):
                    formatted_lates = cell_text
                    app_logger.info(f"[{store_name}] Successfully parsed 'Lates' as: {formatted_lates}")
                elif cell_text:
                    app_logger.warning(f"[{store_name}] Scraped 'Lates' value '{cell_text}' but it didn't match format, defaulting to 0 %.")
                else:
                    app_logger.warning(f"[{store_name}] 'Lates' cell was visible but empty, defaulting to 0 %.")

            except TimeoutError:
                app_logger.warning(f"[{store_name}] Timed out waiting for the 'Lates' cell to become visible, defaulting to 0 %.")
            except Exception as e:
                app_logger.error(f"[{store_name}] An unexpected error occurred while scraping 'Lates': {e}", exc_info=debug_mode)

            milliseconds_from_api = float(api_data.get('TimeAvailable_V2', 0.0))
            total_seconds = int(milliseconds_from_api / 1000)
            total_minutes, _ = divmod(abs(total_seconds), 60)
            total_hours, remaining_minutes = divmod(total_minutes, 60)
            formatted_time_available = f"{total_hours}:{remaining_minutes:02d}"

            form_data = {
                'store': store_name, 'orders': str(api_data.get('OrdersShopped_V2', 0)),
                'units': str(api_data.get('RequestedQuantity_V2', 0)), 'fulfilled': str(api_data.get('PickedUnits_V2', 0)),
                'uph': f"{api_data.get('AverageUPH_V2', 0.0):.0f}", 'inf': f"{api_data.get('ItemNotFoundRate_V2', 0.0):.1f} %",
                'found': f"{api_data.get('ItemFoundRate_V2', 0.0):.1f} %", 'cancelled': str(api_data.get('ShortedUnits_V2', 0)),
                'lates': formatted_lates, 'time_available': formatted_time_available
            }
            await queue.put(form_data)
            
            duration = asyncio.get_event_loop().time() - start_ts
            async with metrics_lock:
                metrics["collection_times"].append((store_name, duration))
                metrics["total_orders"] += int(api_data.get('OrdersShopped_V2', 0))
                metrics["total_units"] += int(api_data.get('RequestedQuantity_V2', 0))
            
            app_logger.info(f"[{store_name}] Data collection complete ({duration:.2f}s).")
            return # Success, exit loop

        except Exception as e:
            app_logger.warning(f"[{store_name}] Failed attempt {attempt + 1}: {e}")
            if attempt < worker_retry_count - 1:
                async with metrics_lock:
                    metrics["retries"] += 1
                    metrics["retry_stores"].add(store_name)
                sleep_time = 2 ** attempt
                app_logger.info(f"[{store_name}] Retrying in {sleep_time}s...")
                await asyncio.sleep(sleep_time)
            else:
                run_failures.append(f"{store_name} (Fail)")
                async with failure_lock:
                    failure_timestamps.append(asyncio.get_event_loop().time())
        finally:
            if page: await page.close()


async def worker_task(worker_id: int, browser: Browser, storage_template: Dict, job_queue: Queue, 
                     submission_queue: Queue, page_timeout: int, action_timeout: int,
                     process_store_func, active_workers_ref: dict, concurrency_limit_ref: dict,
                     concurrency_condition, app_logger):
    """Main worker task that processes stores from the job queue."""
    app_logger.info(f"[Worker-{worker_id}] Starting up.")
    context = None
    try:
        context = await browser.new_context(storage_state=storage_template)
        context.set_default_navigation_timeout(page_timeout)
        context.set_default_timeout(action_timeout)
        
        while True:
            try:
                store_item = job_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            # Enforce Concurrency Limit
            async with concurrency_condition:
                while active_workers_ref['value'] >= concurrency_limit_ref['value']:
                    await concurrency_condition.wait()
                active_workers_ref['value'] += 1

            try:
                await process_store_func(context, store_item, submission_queue)
            finally:
                async with concurrency_condition:
                    active_workers_ref['value'] -= 1
                    concurrency_condition.notify_all()
                job_queue.task_done()
            
    except Exception as e:
        app_logger.error(f"[Worker-{worker_id}] Crashed: {e}")
    finally:
        if context: await context.close()
        app_logger.info(f"[Worker-{worker_id}] Shutting down.")


async def api_worker_task(worker_id: int, browser, storage_template: Dict, job_queue: Queue,
                          submission_queue: Queue, page_timeout: int, action_timeout: int,
                          active_workers_ref: dict, concurrency_limit_ref: dict,
                          concurrency_condition, get_date_range_func, app_logger):
    """API-first worker task that uses direct API calls with browser context switching.
    
    This worker:
    1. Creates a browser context for session management
    2. For each store, navigates to set context then calls APIs directly
    3. Gets all metrics including accurate Lates via API
    4. Is significantly faster than full browser scraping
    
    Args:
        worker_id: Worker identifier
        browser: Playwright browser instance
        storage_template: Auth state template
        job_queue: Queue of stores to process
        submission_queue: Queue for form submission
        page_timeout: Page navigation timeout
        action_timeout: Action timeout
        active_workers_ref: Dict tracking active workers
        concurrency_limit_ref: Dict tracking concurrency limit
        concurrency_condition: Asyncio Condition for concurrency control
        get_date_range_func: Function to get date range config
        app_logger: Logger instance
    """
    log_prefix = f"[API-Worker-{worker_id}]"
    app_logger.info(f"{log_prefix} Starting up (API-first mode).")
    context = None
    page = None
    
    try:
        context = await browser.new_context(storage_state=storage_template)
        context.set_default_navigation_timeout(page_timeout)
        context.set_default_timeout(action_timeout)
        page = await context.new_page()
        
        # Get date range configuration
        date_range = get_date_range_func()
        start_date = None
        end_date = None
        
        if date_range:
            from datetime import datetime, timedelta
            from pytz import timezone
            tz = timezone('Europe/London')
            now = datetime.now(tz)
            
            mode = date_range.get('mode', 'today')
            
            if mode == 'yesterday':
                # Yesterday: midnight to 11:59 PM
                yesterday = now - timedelta(days=1)
                start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=0)
            elif mode == 'today':
                # Today: midnight to now
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
            elif mode == 'last_7_days':
                start_date = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
            elif mode == 'last_30_days':
                start_date = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now
                # Calculate Week to Date (Sunday to Today)
                wtd_start_date = (now - timedelta(days=(now.weekday() + 1) % 7)).replace(hour=0, minute=0, second=0, microsecond=0) # Last Sunday
                wtd_end_date = now
            elif mode == 'custom' and date_range.get('start_date'):
                # Parse custom dates from config
                try:
                    start_str = date_range.get('start_date', '')
                    end_str = date_range.get('end_date', '')
                    if start_str:
                        start_date = datetime.strptime(start_str, '%m/%d/%Y').replace(tzinfo=tz, hour=0, minute=0)
                    if end_str:
                        end_date = datetime.strptime(end_str, '%m/%d/%Y').replace(tzinfo=tz, hour=23, minute=59)
                except:
                    pass  # Use defaults if parsing fails
        
        # Check if we should fetch WTD as well
        # We assume if mode='yesterday' we want WTD too for the report
        fetch_wtd = (date_range and date_range.get('mode') == 'yesterday')
        wtd_start = None
        wtd_end = None
        
        if fetch_wtd:
            # WTD is Monday to the report date (inclusive)
            # Week starts on MONDAY
            from datetime import timedelta
            if start_date:
                # weekday(): Mon=0, Tue=1, ..., Sun=6
                # If start_date is Sunday (weekday=6), we want the PREVIOUS Monday (6 days back)
                # If start_date is Monday (weekday=0), we want THAT Monday (0 days back)
                days_since_monday = start_date.weekday()  # Mon=0, Sun=6
                wtd_start = (start_date - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0)
                wtd_end = end_date  # End of yesterday
                app_logger.info(f"{log_prefix} fetching WTD from {wtd_start.strftime('%Y-%m-%d')} to {wtd_end.strftime('%Y-%m-%d')}")
        
        while True:
            try:
                store_item = job_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            
            store_name = store_item.get('store_name', 'Unknown')
            
            # Enforce Concurrency Limit
            async with concurrency_condition:
                while active_workers_ref['value'] >= concurrency_limit_ref['value']:
                    await concurrency_condition.wait()
                active_workers_ref['value'] += 1

            try:
                # Use API-first approach with browser context switching
                # Fetch primary date range (Yesterday/Custom)
                success, form_data = await fetch_store_metrics_with_lates_browser(
                    page, store_item, start_date, end_date
                )
                
                # Fetch WTD if reliable and separate
                if success and fetch_wtd and wtd_start:
                    # Reuse connection/context - no need to navigate again as context is set!
                    # We need a way to call API without navigation. 
                    # fetch_store_metrics_with_lates_browser does nav first.
                    # Ideally we refactor api_scraper to separate nav from fetch.
                    # For now, we'll just call it again - it's fast enough.
                    success_wtd, wtd_data = await fetch_store_metrics_with_lates_browser(
                        page, store_item, wtd_start, wtd_end
                    )
                    
                    if success_wtd:
                        # Merge WTD data into form_data with _WTD suffix
                        for k, v in wtd_data.items():
                            if k not in ['store', 'date_range']: # Skip meta that duplicates
                                form_data[f"{k}_WTD"] = v
                        form_data['has_wtd'] = True
                
                if success:
                    # Submit to form queue
                    await submission_queue.put(form_data)
                    app_logger.info(f"{log_prefix} [{store_name}] API fetch complete: Orders={form_data['orders']}, Lates={form_data['lates']}")
                else:
                    error = form_data.get('error', 'Unknown error')
                    app_logger.warning(f"{log_prefix} [{store_name}] API fetch failed: {error}")
                    
            except Exception as e:
                app_logger.error(f"{log_prefix} [{store_name}] Error: {e}")
            finally:
                async with concurrency_condition:
                    active_workers_ref['value'] -= 1
                    concurrency_condition.notify_all()
                job_queue.task_done()
            
    except Exception as e:
        app_logger.error(f"{log_prefix} Crashed: {e}")
    finally:
        if page: await page.close()
        if context: await context.close()
        app_logger.info(f"{log_prefix} Shutting down.")

