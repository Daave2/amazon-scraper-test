#!/usr/bin/env python3
"""
Quick single-store test for API-first INF extraction.
Tests the new implementation end-to-end without posting to chat.
"""

import asyncio
import json
import os
import sys
from datetime import datetime

# Add parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright
from auth import check_if_login_needed, perform_login_and_otp
from utils import setup_logging, _save_screenshot
from inf_scraper import navigate_and_extract_inf, process_store_task

# Setup
app_logger = setup_logging()

try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print("❌ config.json not found")
    sys.exit(1)

DEBUG_MODE = config.get('debug', False)
LOGIN_URL = config['login_url']
PAGE_TIMEOUT = config.get('page_timeout_ms', 30000)
STORAGE_STATE = 'state.json'


async def test_single_store():
    """Test API-first extraction on a single store"""
    print("=" * 70)
    print("🧪 SINGLE STORE API-FIRST EXTRACTION TEST")
    print("=" * 70)
    
    # Load first store from urls.csv
    import csv
    with open('urls.csv', 'r') as f:
        reader = csv.DictReader(f)
        stores = list(reader)
    
    test_store = stores[0]
    store_name = test_store['store_name']
    store_number = test_store['store_number']
    merchant_id = test_store['merchant_id']
    marketplace_id = test_store['marketplace_id']
    
    print(f"\n📍 Testing: {store_name} (#{store_number})")
    print(f"   Merchant ID: {merchant_id}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Load session
        context = None
        if os.path.exists(STORAGE_STATE):
            try:
                context = await browser.new_context(storage_state=STORAGE_STATE)
                app_logger.info("Loaded existing session")
            except:
                context = await browser.new_context()
        else:
            context = await browser.new_context()
        
        page = await context.new_page()
        
        # Dictionary to capture API responses
        captured_api_data = {}
        
        # Set up response interception
        async def capture_api_response(response):
            url = response.url
            try:
                if '/inf/GetAllByAsin' in url:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        captured_api_data['GetAllByAsin'] = await response.json()
                        print(f"✅ Captured GetAllByAsin API")
                elif '/item/data' in url:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        captured_api_data['ItemData'] = await response.json()
                        print(f"✅ Captured ItemData API")
            except Exception as e:
                pass
        
        page.on("response", capture_api_response)
        
        # Navigate to INF page
        inf_url = (
            f"https://sellercentral.amazon.co.uk/snow-inventory/inventoryinsights/"
            f"?ref_=mp_home_logo_xx&cor=mmp_EU"
            f"&mons_sel_dir_mcid={merchant_id}"
            f"&mons_sel_mkid={marketplace_id}"
        )
        
        print(f"\n🌐 Navigating to INF page...")
        
        try:
            await page.goto(inf_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        except Exception as e:
            app_logger.warning(f"Navigation: {e}")
        
        # Check for login
        await asyncio.sleep(2)
        if "signin" in page.url.lower() or "/ap/" in page.url:
            print("\n🔐 Login required...")
            async def save_ss(pg, name):
                await _save_screenshot(pg, name, "output", None, app_logger)
            
            success = await perform_login_and_otp(page, LOGIN_URL, config, PAGE_TIMEOUT, DEBUG_MODE, app_logger, save_ss)
            if not success:
                print("❌ Login failed!")
                await browser.close()
                return
            await context.storage_state(path=STORAGE_STATE)
            print("✅ Login successful!")
            
            # Re-navigate
            await page.goto(inf_url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
        
        # Wait for API data
        print("\n⏳ Waiting for API responses...")
        await asyncio.sleep(5)
        
        # Call the extraction function
        print("\n📊 Extracting INF data...")
        items = await navigate_and_extract_inf(page, store_name, 10, captured_api_data)
        
        # Display results
        print("\n" + "=" * 70)
        print("📋 EXTRACTION RESULTS")
        print("=" * 70)
        
        if items:
            print(f"\n✅ Extracted {len(items)} items!")
            
            # Check if we got API data
            first_item = items[0]
            has_api_data = first_item.get('asin') or first_item.get('picking_window')
            
            if has_api_data:
                print("✅ API-FIRST extraction successful!")
            else:
                print("⚠️ HTML fallback was used (API data not available)")
            
            print(f"\n📋 Fields per item: {len(first_item)}")
            print("\n📦 First 3 items:")
            print("-" * 70)
            
            for i, item in enumerate(items[:3]):
                print(f"\n  Item {i+1}: {item.get('name', 'Unknown')[:40]}...")
                print(f"    SKU: {item.get('sku')}")
                print(f"    INF Count: {item.get('inf')}")
                print(f"    ASIN: {item.get('asin', 'N/A')}")
                print(f"    Orders Impacted: {item.get('orders_impacted', 'N/A')}")
                print(f"    Picking Window: {item.get('picking_window', 'N/A')}")
                print(f"    Day of Week: {item.get('day_of_week', 'N/A')}")
                print(f"    Replacement %: {item.get('replacement_percent', 'N/A')}")
                print(f"    Category: {item.get('category', 'N/A')}")
            
            # Check for missing data
            print("\n📊 Data Quality Check:")
            filled_fields = sum(1 for k, v in first_item.items() if v)
            total_fields = len(first_item)
            print(f"   Fields filled: {filled_fields}/{total_fields}")
            
            missing = [k for k, v in first_item.items() if not v]
            if missing:
                print(f"   ⚠️ Empty fields: {missing}")
        else:
            print("❌ No items extracted!")
        
        print("\n" + "=" * 70)
        print("✅ Test complete!")
        print("=" * 70)
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_single_store())
