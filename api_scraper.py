# =======================================================================================
#                    API SCRAPER MODULE - Direct API-First Performance Data Collection
# =======================================================================================
# This module provides API-first data collection for the performance dashboard,
# eliminating the need for browser rendering for most data points.
# =======================================================================================

import asyncio
import aiohttp
import ssl
import certifi
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode
from typing import Dict, List, Optional, Tuple
from pytz import timezone

from utils import setup_logging, LOCAL_TIMEZONE

app_logger = setup_logging()

# API Configuration
SUMMATION_METRICS_URL = "https://sellercentral.amazon.co.uk/snowdash/api/summationMetrics"
DETAILED_METRICS_URL = "https://sellercentral.amazon.co.uk/snowdash/api/metrics"

# Default headers for API requests
DEFAULT_HEADERS = {
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'content-type': 'application/json',
    'x-requested-with': 'XMLHttpRequest',
    'referer': 'https://sellercentral.amazon.co.uk/snowdash',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


def load_cookies_from_state(state_file: str = 'state.json') -> Dict[str, str]:
    """Load authentication cookies from Playwright state file."""
    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
        
        cookies = {}
        for cookie in state.get('cookies', []):
            domain = cookie.get('domain', '')
            if 'amazon.co.uk' in domain or 'amazon.com' in domain:
                cookies[cookie['name']] = cookie['value']
        
        app_logger.debug(f"Loaded {len(cookies)} cookies from {state_file}")
        return cookies
    except FileNotFoundError:
        app_logger.error(f"State file not found: {state_file}")
        return {}
    except json.JSONDecodeError:
        app_logger.error(f"Invalid JSON in state file: {state_file}")
        return {}


def build_metrics_url(merchant_id: str, start_date: datetime = None, end_date: datetime = None, base_url: str = None) -> str:
    """Build the summationMetrics API URL with query parameters.
    
    Args:
        merchant_id: The full merchant ID (e.g., amzn1.merchant.d.xxx)
        start_date: Start of date range (defaults to yesterday)
        end_date: End of date range (defaults to now)
        base_url: Optional base URL (defaults to SUMMATION_METRICS_URL)
    
    Returns:
        Full API URL with query parameters
    """
    if not start_date:
        # Default to today at midnight (not yesterday)
        now = datetime.now(LOCAL_TIMEZONE)
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if not end_date:
        end_date = datetime.now(LOCAL_TIMEZONE)
    
    if not base_url:
        base_url = SUMMATION_METRICS_URL
    
    # API uses 0-indexed months
    params = {
        'merchantIds[]': merchant_id,
        'startRange[year]': start_date.year,
        'startRange[month]': start_date.month - 1,  # 0-indexed
        'startRange[day]': start_date.day,
        'startRange[hour]': 0,
        'endRange[year]': end_date.year,
        'endRange[month]': end_date.month - 1,  # 0-indexed
        'endRange[day]': end_date.day,
        'endRange[hour]': end_date.hour,
    }
    
    return f"{base_url}?{urlencode(params)}"


async def fetch_lates_from_detailed_metrics(
    session: aiohttp.ClientSession,
    store_name: str,
    merchant_id: str,
    start_date: datetime = None,
    end_date: datetime = None
) -> float:
    """Fetch LatePicksRate from the detailed /metrics endpoint.
    
    The /metrics endpoint returns per-shopper data including LatePicksRate.
    We need to find the MASTER record for this store to get the store-level rate.
    
    Args:
        session: aiohttp session with cookies
        store_name: Store name to match
        merchant_id: Merchant ID to query
        start_date: Start of date range
        end_date: End of date range
    
    Returns:
        LatePicksRate as a float (percentage), or 0.0 if not found
        
    Note:
        The /metrics endpoint returns data for the current SESSION context only,
        not for the merchantId parameter. This means we can only get accurate
        LatePicksRate when the session context matches the requested store.
        For fully accurate Lates data, browser-based scraping is still required.
    """
    api_url = build_metrics_url(merchant_id, start_date, end_date, base_url=DETAILED_METRICS_URL)
    
    try:
        async with session.get(api_url, headers=DEFAULT_HEADERS, timeout=15) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                if isinstance(data, list):
                    # Find MASTER record for this store (contains aggregated metrics)
                    for item in data:
                        if item.get('type') == 'MASTER' and store_name in item.get('merchantName', ''):
                            metrics = item.get('metrics', {})
                            return metrics.get('LatePicksRate', 0.0)
                    
                    # Fallback: calculate weighted average from all shoppers
                    total_orders = 0
                    weighted_lates = 0.0
                    for item in data:
                        if store_name in item.get('merchantName', ''):
                            metrics = item.get('metrics', {})
                            orders = metrics.get('OrdersShopped_V2', 0) or metrics.get('OrdersShopped', 0)
                            late_rate = metrics.get('LatePicksRate', 0.0)
                            if orders > 0:
                                total_orders += orders
                                weighted_lates += late_rate * orders
                    
                    if total_orders > 0:
                        return weighted_lates / total_orders
                
                return 0.0
            else:
                return 0.0
    except Exception as e:
        app_logger.debug(f"[{store_name}] Failed to fetch LatePicksRate: {e}")
        return 0.0


async def fetch_store_metrics(
    session: aiohttp.ClientSession,
    store_info: Dict[str, str],
    start_date: datetime = None,
    end_date: datetime = None,
    retry_count: int = 3,
    include_lates: bool = False  # Disabled by default - /metrics endpoint requires browser session context
) -> Tuple[bool, Dict]:
    """Fetch metrics for a single store via direct API call.
    
    Args:
        session: aiohttp session with cookies
        store_info: Store info dict with merchant_id, store_name, etc.
        start_date: Start of date range
        end_date: End of date range
        retry_count: Number of retries on failure
        include_lates: If True, attempt to fetch LatePicksRate (unreliable without browser context)
    
    Returns:
        Tuple of (success: bool, data: dict)
        On success, data contains the parsed form data
        On failure, data contains error info
    """
    store_name = store_info.get('store_name', 'Unknown')
    merchant_id = store_info.get('merchant_id', '')
    
    if not merchant_id:
        return False, {'error': 'Missing merchant_id', 'store': store_name}
    
    api_url = build_metrics_url(merchant_id, start_date, end_date)
    
    for attempt in range(retry_count):
        try:
            async with session.get(api_url, headers=DEFAULT_HEADERS, timeout=15) as resp:
                status = resp.status
                
                if status == 200:
                    api_data = await resp.json()
                    
                    # Parse API response into form data format (matching current scraper output)
                    milliseconds_from_api = float(api_data.get('TimeAvailable_V2', 0.0))
                    total_seconds = int(milliseconds_from_api / 1000)
                    total_minutes, _ = divmod(abs(total_seconds), 60)
                    total_hours, remaining_minutes = divmod(total_minutes, 60)
                    formatted_time_available = f"{total_hours}:{remaining_minutes:02d}"
                    
                    # Fetch LatePicksRate from detailed metrics if requested
                    lates_rate = 0.0
                    if include_lates:
                        lates_rate = await fetch_lates_from_detailed_metrics(
                            session, store_name, merchant_id, start_date, end_date
                        )
                    
                    form_data = {
                        'store': store_name,
                        'orders': str(int(api_data.get('OrdersShopped_V2', 0))),
                        'units': str(int(api_data.get('RequestedQuantity_V2', 0))),
                        'fulfilled': str(int(api_data.get('PickedUnits_V2', 0))),
                        'uph': f"{api_data.get('AverageUPH_V2', 0.0):.0f}",
                        'inf': f"{api_data.get('ItemNotFoundRate_V2', 0.0):.1f} %",
                        'found': f"{api_data.get('ItemFoundRate_V2', 0.0):.1f} %",
                        'cancelled': str(int(api_data.get('ShortedUnits_V2', 0))),
                        'lates': f"{lates_rate:.1f} %",  # Now calculated from detailed metrics API
                        'time_available': formatted_time_available,
                        # Additional fields from API (for future use)
                        '_api_data': {
                            'time_available_ms': milliseconds_from_api,  # Raw ms for calculations
                            'time_available_hours': milliseconds_from_api / 3600000.0,  # Hours
                            'acceptance_rate': api_data.get('AcceptanceRate_V2', 0),
                            'rejection_rate': api_data.get('RejectionRate_V2', 0),
                            'replacement_rate': api_data.get('ReplacementRate_V2', 0),
                            'availability_percent': api_data.get('AvailabilityPercent_V2', 0),
                            'utilized_percent': api_data.get('UtilizedPercent_V2', 0),
                            'abandonment_rate': api_data.get('AbandonmentRate_V2', 0),
                            'avg_order_time_sec': api_data.get('AverageOrderTime_V2', 0),
                            'pick_time_sec': api_data.get('PickTimeInSec_V2', 0),
                            'late_picks_rate': lates_rate,
                        }
                    }
                    
                    app_logger.debug(f"[{store_name}] API fetch successful: {form_data['orders']} orders, UPH: {form_data['uph']}, Lates: {lates_rate:.1f}%")
                    return True, form_data
                
                elif status == 403:
                    # Session expired
                    error_text = await resp.text()
                    app_logger.warning(f"[{store_name}] Session expired (403): {error_text[:100]}")
                    return False, {'error': 'session_expired', 'store': store_name, 'status': 403}
                
                else:
                    error_text = await resp.text()
                    app_logger.warning(f"[{store_name}] API error {status}: {error_text[:100]}")
                    if attempt < retry_count - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    return False, {'error': f'HTTP {status}', 'store': store_name, 'status': status}
        
        except asyncio.TimeoutError:
            app_logger.warning(f"[{store_name}] API timeout (attempt {attempt + 1}/{retry_count})")
            if attempt < retry_count - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            return False, {'error': 'timeout', 'store': store_name}
        
        except Exception as e:
            app_logger.error(f"[{store_name}] API error: {e}")
            if attempt < retry_count - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            return False, {'error': str(e), 'store': store_name}
    
    return False, {'error': 'max_retries_exceeded', 'store': store_name}


async def fetch_all_stores_api(
    stores: List[Dict[str, str]],
    cookies: Dict[str, str],
    start_date: datetime = None,
    end_date: datetime = None,
    max_concurrency: int = 100
) -> Tuple[List[Dict], List[Dict]]:
    """Fetch metrics for all stores using direct API calls.
    
    Args:
        stores: List of store info dicts
        cookies: Authentication cookies
        start_date: Start of date range
        end_date: End of date range
        max_concurrency: Maximum concurrent API requests
    
    Returns:
        Tuple of (successful_results: list, failed_stores: list)
    """
    if not cookies:
        app_logger.error("No cookies available for API calls")
        return [], [{'error': 'no_cookies'}]
    
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context, limit=max_concurrency)
    
    successful = []
    failed = []
    
    semaphore = asyncio.Semaphore(max_concurrency)
    
    async def fetch_with_semaphore(store):
        async with semaphore:
            return await fetch_store_metrics(session, store, start_date, end_date)
    
    async with aiohttp.ClientSession(connector=connector, cookies=cookies) as session:
        tasks = [fetch_with_semaphore(store) for store in stores]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for store, result in zip(stores, results):
            if isinstance(result, Exception):
                failed.append({'store': store.get('store_name', 'Unknown'), 'error': str(result)})
            elif result[0]:  # Success
                successful.append(result[1])
            else:  # Failure
                failed.append(result[1])
    
    app_logger.info(f"API fetch complete: {len(successful)} successful, {len(failed)} failed")
    return successful, failed


class APIScraperWorker:
    """Worker class for API-first scraping with session management."""
    
    def __init__(self, state_file: str = 'state.json'):
        self.state_file = state_file
        self.cookies = {}
        self.session: Optional[aiohttp.ClientSession] = None
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
    
    async def initialize(self):
        """Load cookies and create session."""
        self.cookies = load_cookies_from_state(self.state_file)
        if not self.cookies:
            raise RuntimeError("No cookies available - login required")
        
        connector = aiohttp.TCPConnector(ssl=self.ssl_context, limit=200)
        self.session = aiohttp.ClientSession(connector=connector, cookies=self.cookies)
        app_logger.info(f"API worker initialized with {len(self.cookies)} cookies")
    
    async def close(self):
        """Close the session."""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def fetch_store(self, store_info: Dict, start_date: datetime = None, end_date: datetime = None) -> Tuple[bool, Dict]:
        """Fetch metrics for a single store."""
        if not self.session:
            await self.initialize()
        return await fetch_store_metrics(self.session, store_info, start_date, end_date)
    
    def is_session_valid(self, result: Tuple[bool, Dict]) -> bool:
        """Check if the result indicates a valid session."""
        if result[0]:
            return True
        return result[1].get('error') != 'session_expired'
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


async def fetch_store_metrics_with_lates_browser(
    page,
    store_info: Dict[str, str],
    start_date: datetime = None,
    end_date: datetime = None
) -> Tuple[bool, Dict]:
    """Fetch store metrics WITH accurate Lates by using browser to set context.
    
    This function:
    1. Navigates to the store's dashboard (sets session context)
    2. Fetches summationMetrics API for main data
    3. Fetches /metrics API for LatePicksRate (now available due to context)
    4. Combines both into the final result
    
    Args:
        page: Playwright page object
        store_info: Store info dict
        start_date: Start of date range
        end_date: End of date range
    
    Returns:
        Tuple of (success: bool, data: dict)
    """
    store_name = store_info.get('store_name', 'Unknown')
    merchant_id = store_info.get('merchant_id', '')
    marketplace_id = store_info.get('marketplace_id', '')
    new_id = store_info.get('new_id', '')  # Short format for /metrics API
    
    try:
        # Navigate to store dashboard to set context
        dash_url = f"https://sellercentral.amazon.co.uk/snowdash?ref_=mp_home_logo_xx&cor=mmp_EU&mons_sel_dir_mcid={merchant_id}&mons_sel_mkid={marketplace_id}"
        await page.goto(dash_url, wait_until="domcontentloaded", timeout=30000)
        
        # Get cookies after navigation
        context = page.context
        cookies_list = await context.cookies()
        cookies = {c['name']: c['value'] for c in cookies_list if 'amazon' in c.get('domain', '')}
        
        # Build date range params - default to today only
        if not start_date:
            now = datetime.now(LOCAL_TIMEZONE)
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if not end_date:
            end_date = datetime.now(LOCAL_TIMEZONE)
        
        params = {
            'merchantIds[]': new_id if new_id else merchant_id,
            'startRange[year]': start_date.year,
            'startRange[month]': start_date.month - 1,
            'startRange[day]': start_date.day,
            'startRange[hour]': 0,
            'endRange[year]': end_date.year,
            'endRange[month]': end_date.month - 1,
            'endRange[day]': end_date.day,
            'endRange[hour]': end_date.hour,
        }
        
        # Create aiohttp session with updated cookies
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        
        async with aiohttp.ClientSession(connector=connector, cookies=cookies) as session:
            # Fetch summation metrics (main data)
            summation_url = f"{SUMMATION_METRICS_URL}?{urlencode(params)}"
            async with session.get(summation_url, headers=DEFAULT_HEADERS, timeout=15) as resp:
                if resp.status != 200:
                    return False, {'error': f'Summation API error: {resp.status}', 'store': store_name}
                api_data = await resp.json()
            
            # Fetch detailed metrics (for LatePicksRate)
            detailed_url = f"{DETAILED_METRICS_URL}?{urlencode(params)}"
            async with session.get(detailed_url, headers=DEFAULT_HEADERS, timeout=15) as resp:
                lates_rate = 0.0
                if resp.status == 200:
                    detailed_data = await resp.json()
                    if isinstance(detailed_data, list):
                        # Calculate weighted average LatePicksRate
                        total_orders = 0
                        weighted_lates = 0.0
                        for item in detailed_data:
                            metrics = item.get('metrics', {})
                            orders = metrics.get('OrdersShopped_V2', 0) or metrics.get('OrdersShopped', 0)
                            late_rate = metrics.get('LatePicksRate', 0.0)
                            if orders > 0:
                                total_orders += orders
                                weighted_lates += late_rate * orders
                        if total_orders > 0:
                            lates_rate = weighted_lates / total_orders
        
        # Build form data
        milliseconds = float(api_data.get('TimeAvailable_V2', 0.0))
        total_seconds = int(milliseconds / 1000)
        total_minutes, _ = divmod(abs(total_seconds), 60)
        total_hours, remaining_minutes = divmod(total_minutes, 60)
        formatted_time = f"{total_hours}:{remaining_minutes:02d}"
        
        form_data = {
            'store': store_name,
            'orders': str(int(api_data.get('OrdersShopped_V2', 0))),
            'units': str(int(api_data.get('RequestedQuantity_V2', 0))),
            'fulfilled': str(int(api_data.get('PickedUnits_V2', 0))),
            'uph': f"{api_data.get('AverageUPH_V2', 0.0):.0f}",
            'inf': f"{api_data.get('ItemNotFoundRate_V2', 0.0):.1f} %",
            'found': f"{api_data.get('ItemFoundRate_V2', 0.0):.1f} %",
            'cancelled': str(int(api_data.get('ShortedUnits_V2', 0))),
            'lates': f"{lates_rate:.1f} %",  # NOW ACCURATE!
            'time_available': formatted_time,
            '_api_data': {
                'late_picks_rate': lates_rate,
                'acceptance_rate': api_data.get('AcceptanceRate_V2', 0),
                'rejection_rate': api_data.get('RejectionRate_V2', 0),
            }
        }
        
        app_logger.debug(f"[{store_name}] API+Browser fetch: Orders={form_data['orders']}, Lates={lates_rate:.1f}%")
        return True, form_data
        
    except Exception as e:
        app_logger.error(f"[{store_name}] Error in fetch_with_lates: {e}")
        return False, {'error': str(e), 'store': store_name}


# Convenience function for quick testing
async def test_api_fetch(store_info: Dict[str, str], state_file: str = 'state.json') -> Dict:
    """Quick test function to fetch metrics for a single store."""
    async with APIScraperWorker(state_file) as worker:
        success, data = await worker.fetch_store(store_info)
        if success:
            return data
        else:
            raise RuntimeError(f"Failed to fetch: {data}")


if __name__ == "__main__":
    # Quick test
    import csv
    
    with open('urls.csv', 'r') as f:
        reader = csv.DictReader(f)
        stores = list(reader)
    
    print(f"Testing with {len(stores)} stores...")
    
    async def main():
        cookies = load_cookies_from_state()
        if not cookies:
            print("No cookies - please run the browser scraper first to login")
            return
        
        successful, failed = await fetch_all_stores_api(stores[:10], cookies)
        
        print(f"\nResults: {len(successful)} successful, {len(failed)} failed")
        
        if successful:
            print("\nSample data:")
            sample = successful[0]
            for key, value in sample.items():
                if key != '_api_data':
                    print(f"  {key}: {value}")
    
    asyncio.run(main())
