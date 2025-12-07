#!/usr/bin/env python3
"""
API-First INF Extraction Test - Response Interception Approach

This script intercepts the actual API responses made by the INF page
to show exactly what data is available vs what we currently scrape.
"""

import asyncio
import json
import os
import sys
import re
from datetime import datetime, timezone as dt_timezone
from urllib.parse import unquote
from playwright.async_api import async_playwright

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import check_if_login_needed, perform_login_and_otp
from utils import setup_logging, _save_screenshot

# Setup
app_logger = setup_logging()

try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print("❌ config.json not found - run from project root")
    sys.exit(1)

DEBUG_MODE = config.get('debug', False)
LOGIN_URL = config['login_url']
PAGE_TIMEOUT = config.get('page_timeout_ms', 30000)
STORAGE_STATE = 'state.json'

# Captured API responses
captured_responses = {}


async def run_api_test():
    """Main test function"""
    print("=" * 70)
    print("🧪 API-FIRST INF EXTRACTION TEST")
    print("    (Response Interception Approach)")
    print("=" * 70)
    
    # Test with one store from urls.csv
    import csv
    with open('urls.csv', 'r') as f:
        reader = csv.DictReader(f)
        stores = list(reader)
    
    # Pick first store for testing
    test_store = stores[0]
    store_name = test_store['store_name']
    store_number = test_store['store_number']
    merchant_id_long = test_store['merchant_id']
    merchant_id = test_store['new_id']
    
    print(f"\n📍 TEST STORE: {store_name} (#{store_number})")
    print(f"   Merchant ID: {merchant_id}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        
        # Load session if exists
        context = None
        if os.path.exists(STORAGE_STATE):
            app_logger.info(f"Loading session from {STORAGE_STATE}")
            try:
                context = await browser.new_context(storage_state=STORAGE_STATE)
            except:
                context = await browser.new_context()
        else:
            context = await browser.new_context()
        
        page = await context.new_page()
        
        # Set up response interception BEFORE navigation
        async def capture_response(response):
            url = response.url
            # Capture INF-related API responses
            if any(x in url for x in ['/inf/', '/item/data']):
                try:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        body = await response.json()
                        # Extract endpoint name from URL
                        if '/inf/GetAllByAsin' in url:
                            captured_responses['GetAllByAsin'] = body
                            print(f"✅ Captured GetAllByAsin response")
                        elif '/inf/GetFulfillmentMetrics' in url:
                            if 'GetFulfillmentMetrics' not in captured_responses:
                                captured_responses['GetFulfillmentMetrics'] = body
                                print(f"✅ Captured GetFulfillmentMetrics response")
                        elif '/item/data' in url:
                            captured_responses['ItemData'] = body
                            print(f"✅ Captured item/data response")
                except Exception as e:
                    pass
        
        page.on("response", capture_response)
        
        # Navigate to INF page for the specific store
        inf_url = (
            f"https://sellercentral.amazon.co.uk/snow-inventory/inventoryinsights/"
            f"?ref_=mp_home_logo_xx&cor=mmp_EU"
            f"&mons_sel_dir_mcid={merchant_id_long}"
            f"&mons_sel_mkid={test_store['marketplace_id']}"
        )
        
        print(f"\n🌐 Navigating to INF page for {store_name}...")
        
        try:
            await page.goto(inf_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        except Exception as e:
            app_logger.warning(f"Navigation error: {e}")
        
        # Check if we landed on login page
        await asyncio.sleep(2)
        current_url = page.url
        if "signin" in current_url.lower() or "/ap/" in current_url:
            print("\n🔐 Login required, performing login...")
            async def save_ss(pg, name):
                await _save_screenshot(pg, name, "output", None, app_logger)
            
            success = await perform_login_and_otp(page, LOGIN_URL, config, PAGE_TIMEOUT, DEBUG_MODE, app_logger, save_ss)
            if not success:
                print("❌ Login failed!")
                await browser.close()
                return
            await context.storage_state(path=STORAGE_STATE)
            print("✅ Login successful!")
            
            # Now navigate to INF page after login
            print(f"\n🌐 Re-navigating to INF page...")
            await page.goto(inf_url, timeout=PAGE_TIMEOUT, wait_until="networkidle")
        
        # Wait for page to fully load and all API calls to complete
        print("\n⏳ Waiting for API responses...")
        await asyncio.sleep(8)
        
        # Check what we captured
        print("\n" + "=" * 70)
        print("📊 CAPTURED API RESPONSES")
        print("=" * 70)
        
        # Variables for data
        skus = []
        asins = []
        
        # ============================================
        # Analyze GetAllByAsin
        # ============================================
        if 'GetAllByAsin' in captured_responses:
            print("\n📊 GetAllByAsin API:")
            data = captured_responses['GetAllByAsin']
            
            # Handle different response structures
            items = data.get('infMetrics') or data.get('infDataList') or []
            if items:
                print(f"   ✅ Got {len(items)} INF items!")
                
                if items:
                    print(f"\n   📋 Fields available: {list(items[0].keys())}")
                    
                    print("\n   📦 SAMPLE DATA (first 5 items):")
                    print("   " + "-" * 60)
                    
                    for i, item in enumerate(items[:5]):
                        print(f"\n   Item {i+1}:")
                        for key, value in item.items():
                            print(f"      {key}: {value}")
                        skus.append(item.get('merchantSku'))
                        asins.append(item.get('asin'))
                    
                    # Show comparison
                    print("\n   📊 COMPARISON - Current vs API:")
                    print("   " + "-" * 60)
                    current_fields = ['merchantSku', 'infCount', 'name', 'imageUrl']
                    new_fields = []
                    for key in items[0].keys():
                        if key in current_fields:
                            print(f"      ✅ {key} (already extracted)")
                        else:
                            new_fields.append(key)
                            print(f"      🆕 {key} (NEW!)")
                    
                    print(f"\n   💡 NEW fields we could extract: {len(new_fields)}")
                    for field in new_fields:
                        sample = items[0].get(field)
                        print(f"      • {field}: {sample}")
            else:
                print(f"   ⚠️ Unexpected response structure: {list(data.keys())}")
        else:
            print("\n⚠️ GetAllByAsin not captured - checking page state...")
        
        # ============================================
        # Analyze GetFulfillmentMetrics
        # ============================================
        if 'GetFulfillmentMetrics' in captured_responses:
            print("\n\n📈 GetFulfillmentMetrics API:")
            data = captured_responses['GetFulfillmentMetrics']
            
            if 'fulfillmentMetrics' in data:
                metrics = data['fulfillmentMetrics']
                print(f"   ✅ Got metrics for {len(metrics)} ASINs!")
                print("\n   Sample (first 5):")
                for m in metrics[:5]:
                    print(f"      ASIN {m.get('asin')}: {m.get('unitsShipped')} units shipped")
        
        # ============================================
        # Analyze ItemData
        # ============================================
        if 'ItemData' in captured_responses:
            print("\n\n📦 Item/Data API:")
            data = captured_responses['ItemData']
            
            if 'data' in data:
                products = data['data']
                if isinstance(products, str):
                    import ast
                    products = ast.literal_eval(products)
                
                print(f"   ✅ Got details for {len(products)} products!")
                
                if products:
                    print(f"\n   📋 Fields available: {list(products[0].keys())}")
                    print("\n   Sample (first 3):")
                    for i, p in enumerate(products[:3]):
                        print(f"\n   Product {i+1}:")
                        print(f"      name: {p.get('name', '')[:50]}...")
                        print(f"      category: {p.get('category')}")
                        print(f"      asin: {p.get('asin')}")
                        if 'productUrl' in p:
                            print(f"      productUrl: {p.get('productUrl')[:50]}...")
        
        # ============================================
        # FINAL SUMMARY
        # ============================================
        print("\n" + "=" * 70)
        print("📋 FINAL VERDICT")
        print("=" * 70)
        
        apis_captured = len(captured_responses)
        print(f"\n   APIs captured: {apis_captured}")
        
        if apis_captured > 0:
            print("\n   ✅ API-FIRST APPROACH IS VIABLE!")
            print("\n   🎯 NEW DATA AVAILABLE:")
            print("      From GetAllByAsin:")
            print("        • asin - Amazon product ID")
            print("        • ordersImpacted - Customer impact count")
            print("        • shortCount - Items not fulfilled")
            print("        • successfulReplacementPercent - Substitution rate")
            print("        • pickingWindow - Time slot (e.g., '8am-10am')")
            print("        • dayOfWeek - Day pattern (e.g., 'Sunday')")
            print("        • unitsShipped - Total shipped units")
            
            print("\n      From item/data:")
            print("        • category - Product category")
            print("        • productUrl - Amazon listing URL")
            print("        • thumbnailUrl - Small image")
            
            print("\n   🚀 WHAT WE CAN DO WITH THIS:")
            print("      1. Picking Window Analysis - Peak INF times")
            print("      2. Day-of-Week Patterns - Weekly trends")
            print("      3. Customer Impact Ranking - Prioritize by impact")
            print("      4. Replacement Success - Track substitutions")
            print("      5. Category Breakdown - INF by category")
            print("      6. Fill Rate - Shipped vs INF ratio")
        else:
            print("\n   ⚠️ No APIs captured - may need to interact with page more")
        
        print("\n" + "=" * 70)
        print("Press Ctrl+C to exit...")
        
        # Keep browser open for inspection
        try:
            await asyncio.sleep(30)
        except:
            pass
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run_api_test())
