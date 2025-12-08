#!/usr/bin/env python3
"""
Deep investigation: How does the dashboard get Lates data?

Navigate to a specific store (Chingford) and capture ALL API calls
to find where Lates/LatePicksRate comes from.
"""

import asyncio
import json
import csv
from playwright.async_api import async_playwright

# Find Chingford
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Chingford' in row.get('store_name', ''):
            store = row
            break

MERCHANT_ID = store['merchant_id']
MARKETPLACE_ID = store['marketplace_id']
STORE_NAME = store['store_name']

print(f"Investigating: {STORE_NAME}")
print(f"Merchant ID: {MERCHANT_ID}")
print(f"Marketplace ID: {MARKETPLACE_ID}")

# Track all APIs
all_apis = []
lates_related = []

async def capture_response(response):
    url = response.url
    
    # Skip static assets
    if any(ext in url for ext in ['.js', '.css', '.png', '.jpg', '.gif', '.woff', '.ico']):
        return
    if any(skip in url for skip in ['google', 'amazon-adsystem', 'cloudfront', 'unagi']):
        return
    
    try:
        if response.status == 200:
            content_type = response.headers.get('content-type', '')
            if 'json' in content_type:
                body = await response.json()
                
                api_info = {
                    'url': url,
                    'body': body
                }
                all_apis.append(api_info)
                
                # Check for Lates-related data
                body_str = json.dumps(body).lower()
                if any(term in body_str for term in ['late', 'latepicks', 'delay', 'ontime']):
                    print(f"\n🎯 LATES-RELATED API: {url[:80]}...")
                    lates_related.append(api_info)
                    
                    # Print relevant fields
                    if isinstance(body, dict):
                        for key, value in body.items():
                            if 'late' in key.lower():
                                print(f"   {key}: {value}")
                    elif isinstance(body, list) and len(body) > 0:
                        first = body[0]
                        if isinstance(first, dict):
                            metrics = first.get('metrics', first)
                            if isinstance(metrics, dict):
                                for key, value in metrics.items():
                                    if 'late' in key.lower():
                                        print(f"   {key}: {value}")
                                        
    except Exception as e:
        pass

async def main():
    print("\n" + "=" * 60)
    print("INVESTIGATING LATES DATA SOURCE")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        
        # Load auth
        with open('state.json', 'r') as f:
            storage_state = json.load(f)
        context = await browser.new_context(storage_state=storage_state)
        
        page = await context.new_page()
        page.on("response", capture_response)
        
        # Navigate directly to THIS store's dashboard
        dash_url = f"https://sellercentral.amazon.co.uk/snowdash?ref_=mp_home_logo_xx&cor=mmp_EU&mons_sel_dir_mcid={MERCHANT_ID}&mons_sel_mkid={MARKETPLACE_ID}"
        
        print(f"\n🌐 Navigating to {STORE_NAME}'s dashboard...")
        print(f"URL: {dash_url[:80]}...")
        
        await page.goto(dash_url, wait_until="networkidle", timeout=60000)
        print("✓ Page loaded")
        
        # Wait for dashboard data
        await page.wait_for_timeout(5000)
        
        # Click refresh to trigger fresh data
        try:
            refresh_btn = page.locator("button:has-text('Refresh')")
            if await refresh_btn.count() > 0:
                print("\n🔄 Clicking Refresh...")
                await refresh_btn.first.click()
                await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Refresh click failed: {e}")
        
        # Check the Lates value in the DOM
        print("\n📊 Checking DOM for Lates value...")
        try:
            header_second_row = page.locator("kat-table-head kat-table-row").nth(1)
            lates_cell = header_second_row.locator("kat-table-cell").nth(10)
            lates_text = await lates_cell.text_content()
            print(f"   Lates from DOM: '{lates_text}'")
        except Exception as e:
            print(f"   Could not get Lates from DOM: {e}")
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        print(f"\nTotal APIs captured: {len(all_apis)}")
        print(f"Lates-related APIs: {len(lates_related)}")
        
        if lates_related:
            print("\n📋 Lates-related API details:")
            for api in lates_related:
                print(f"\n  URL: {api['url'][:100]}...")
                body = api['body']
                if isinstance(body, list) and len(body) > 0:
                    print(f"  Type: Array with {len(body)} items")
                    for item in body[:3]:
                        if isinstance(item, dict):
                            name = item.get('merchantName', item.get('shopperName', 'Unknown'))
                            metrics = item.get('metrics', {})
                            late_rate = metrics.get('LatePicksRate', 'N/A')
                            print(f"    - {name}: LatePicksRate={late_rate}")
                elif isinstance(body, dict):
                    for key in sorted(body.keys()):
                        if 'late' in key.lower():
                            print(f"    {key}: {body[key]}")
        
        # Save all API responses for analysis
        with open('output/chingford_apis.json', 'w') as f:
            json.dump(all_apis, f, indent=2, default=str)
        print(f"\n💾 Saved all API responses to output/chingford_apis.json")
        
        # Keep browser open briefly
        print("\n🔍 Keeping browser open for 10 seconds for manual inspection...")
        await page.wait_for_timeout(10000)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
