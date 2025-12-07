#!/usr/bin/env python3
"""
Amazon Seller Central API Discovery Tool

This script navigates to the INF page and captures all network requests,
documenting background APIs that could be used for enhanced data extraction.

Uses auth.py for proper authentication flow.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright

# Add parent directory to path to import local modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import check_if_login_needed, perform_login_and_otp
from utils import setup_logging, _save_screenshot

# Setup logging
app_logger = setup_logging()

# Load config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    app_logger.critical("config.json not found - run from project root directory")
    sys.exit(1)

DEBUG_MODE = config.get('debug', False)
LOGIN_URL = config['login_url']
PAGE_TIMEOUT = config.get('page_timeout_ms', 30000)
STORAGE_STATE = 'state.json'

# Output file for discovered APIs
OUTPUT_FILE = "output/discovered_apis.json"

# Store captured requests
captured_requests = []
captured_responses = {}


async def capture_request(request):
    """Capture outgoing requests"""
    url = request.url
    
    # Filter to capture API calls (skip static assets)
    if any(x in url for x in ['.js', '.css', '.png', '.jpg', '.gif', '.ico', '.woff', 'analytics', 'tracking', 'metrics']):
        return
    
    # Focus on data endpoints
    if '/api/' in url or 'inventoryinsights' in url or '/snow' in url or '/inventory' in url or '/fba' in url:
        req_data = {
            "timestamp": datetime.now().isoformat(),
            "method": request.method,
            "url": url,
            "headers": dict(request.headers),
            "post_data": request.post_data if request.method == "POST" else None,
            "resource_type": request.resource_type
        }
        captured_requests.append(req_data)
        print(f"📡 [{request.method}] {url[:100]}...")


async def capture_response(response):
    """Capture API responses"""
    url = response.url
    
    # Focus on JSON responses from data endpoints
    if any(x in url for x in ['/api/', '/snow', '/inventory', '/fba', 'inventoryinsights']):
        if 'json' in response.headers.get('content-type', ''):
            try:
                body = await response.json()
                captured_responses[url] = {
                    "status": response.status,
                    "headers": dict(response.headers),
                    "body_sample": body if isinstance(body, dict) else {"data": str(body)[:500]},
                    "body_size": len(str(body))
                }
                print(f"✅ Response captured from {url[:80]}... ({len(str(body))} bytes)")
            except:
                pass


async def discover_apis():
    """Main discovery function"""
    print("=" * 60)
    print("🔍 Amazon Seller Central API Discovery Tool")
    print("=" * 60)
    
    async with async_playwright() as p:
        # Launch browser with visible UI for debugging
        browser = await p.chromium.launch(headless=not DEBUG_MODE)
        
        # Try to load existing session
        context = None
        
        if os.path.exists(STORAGE_STATE):
            app_logger.info(f"Loading session from {STORAGE_STATE}")
            try:
                context = await browser.new_context(storage_state=STORAGE_STATE)
            except Exception as e:
                app_logger.warning(f"Failed to load state: {e}")
                context = await browser.new_context()
        else:
            context = await browser.new_context()
        
        page = await context.new_page()
        
        # Check if login is needed using auth.py method
        test_url = "https://sellercentral.amazon.co.uk/home"
        login_needed = await check_if_login_needed(page, test_url, PAGE_TIMEOUT, DEBUG_MODE, app_logger)
        
        if login_needed:
            app_logger.info("Login required. Performing login with OTP...")
            # Create a save_screenshot helper for login
            async def save_screenshot_helper(pg, name):
                await _save_screenshot(pg, name, "output", None, app_logger)
            
            login_success = await perform_login_and_otp(
                page, LOGIN_URL, config, PAGE_TIMEOUT, DEBUG_MODE, app_logger, save_screenshot_helper
            )
            
            if not login_success:
                app_logger.error("Login failed! Cannot continue with API discovery.")
                await browser.close()
                return
            
            # Save the new session state
            await context.storage_state(path=STORAGE_STATE)
            app_logger.info(f"Login successful! Session saved to {STORAGE_STATE}")
        else:
            app_logger.info("Session is valid, no login needed.")
        
        # Set up request/response interception
        page.on("request", capture_request)
        page.on("response", capture_response)
        
        # Navigate to INF page
        inf_url = "https://sellercentral.amazon.co.uk/snow-inventory/inventoryinsights/"
        app_logger.info(f"Navigating to: {inf_url}")
        
        try:
            await page.goto(inf_url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
        except Exception as e:
            app_logger.warning(f"Navigation warning: {e}")
        
        print("\n📊 Exploring INF page features...")
        
        # Wait for initial data load
        await asyncio.sleep(3)
        
        # 1. Try to interact with date picker
        print("\n🗓️ Looking for date picker...")
        try:
            date_button = page.locator('[data-testid="date-range-picker"], .date-picker, [class*="datepicker"]').first
            if await date_button.is_visible():
                await date_button.click()
                await asyncio.sleep(2)
                print("   Date picker opened!")
        except:
            print("   No date picker found")
        
        # 2. Try to click on filters
        print("\n🔍 Looking for filters...")
        try:
            filter_buttons = await page.locator('button:has-text("Filter"), [class*="filter"]').all()
            for btn in filter_buttons[:2]:
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1)
        except:
            pass
        
        # 3. Try different sorting
        print("\n📊 Testing table sorting...")
        try:
            headers = await page.locator('th a, th button, .sortable').all()
            for header in headers[:5]:
                try:
                    if await header.is_visible():
                        await header.click()
                        await asyncio.sleep(1.5)
                        print(f"   Sorted by: {await header.inner_text()}")
                except:
                    pass
        except:
            pass
        
        # 4. Try pagination
        print("\n📄 Testing pagination...")
        try:
            next_buttons = await page.locator('[aria-label="Next"], button:has-text("Next"), .pagination-next').all()
            for btn in next_buttons[:1]:
                if await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    await asyncio.sleep(2)
                    print("   Navigated to next page!")
        except:
            pass
        
        # 5. Click into a product row
        print("\n📦 Exploring product details...")
        try:
            rows = await page.locator('table tbody tr').all()
            if rows:
                await rows[0].click()
                await asyncio.sleep(2)
                print("   Clicked on product row!")
        except:
            pass
        
        # 6. Look for export buttons
        print("\n📥 Looking for export options...")
        try:
            export_btns = await page.locator('button:has-text("Export"), button:has-text("Download"), [class*="export"]').all()
            for btn in export_btns:
                if await btn.is_visible():
                    text = await btn.inner_text()
                    print(f"   Found export option: {text}")
        except:
            pass
        
        # 7. Check for product drill-down
        print("\n🔗 Looking for product detail links...")
        try:
            product_links = await page.locator('td a[href*="product"], td a[href*="sku"]').all()
            if product_links:
                print(f"   Found {len(product_links)} product links!")
                # Click first one
                await product_links[0].click()
                await asyncio.sleep(3)
        except:
            pass
        
        await asyncio.sleep(3)  # Final wait for any pending requests
        
        print("\n" + "=" * 60)
        print("📋 API DISCOVERY RESULTS")
        print("=" * 60)
        
        # Save results
        results = {
            "discovery_timestamp": datetime.now().isoformat(),
            "page_url": page.url,
            "requests_captured": len(captured_requests),
            "responses_captured": len(captured_responses),
            "requests": captured_requests,
            "responses": captured_responses
        }
        
        os.makedirs("output", exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n✅ Found {len(captured_requests)} API requests")
        print(f"✅ Captured {len(captured_responses)} JSON responses")
        print(f"💾 Saved to: {OUTPUT_FILE}")
        
        # Print summary of unique endpoints
        print("\n📡 UNIQUE ENDPOINTS:")
        seen_paths = set()
        for req in captured_requests:
            # Extract path without query params
            url = req["url"]
            path = url.split("?")[0]
            if path not in seen_paths:
                seen_paths.add(path)
                print(f"   [{req['method']}] {path}")
        
        # Print response samples
        if captured_responses:
            print("\n📦 RESPONSE SAMPLES:")
            for url, data in list(captured_responses.items())[:5]:
                print(f"\n   {url[:80]}...")
                print(f"   Status: {data['status']}, Size: {data['body_size']} bytes")
                if isinstance(data.get('body_sample'), dict):
                    keys = list(data['body_sample'].keys())[:10]
                    print(f"   Fields: {keys}")
        
        print("\n🏁 Discovery complete! Check output/discovered_apis.json for full details.")
        print("\n💡 Press Enter in this terminal to close the browser...")
        
        # Keep browser open for manual inspection
        await asyncio.sleep(300)  # 5 minutes to explore manually
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(discover_apis())
