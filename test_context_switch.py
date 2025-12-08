#!/usr/bin/env python3
"""
Test: Can we call the metrics API after setting the store context via navigation?

This script will:
1. Navigate to Chingford's dashboard (sets session context)
2. Extract the updated cookies
3. Call the API directly with those cookies
"""

import asyncio
import json
import csv
import aiohttp
import ssl
import certifi
from datetime import datetime
from urllib.parse import urlencode
from playwright.async_api import async_playwright

# Find Chingford
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Chingford' in row.get('store_name', ''):
            store = row
            break

print(f"Store: {store['store_name']}")
print(f"new_id: {store['new_id']}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Load existing auth
        with open('state.json', 'r') as f:
            storage_state = json.load(f)
        context = await browser.new_context(storage_state=storage_state)
        
        page = await context.new_page()
        
        # Navigate to Chingford's dashboard
        dash_url = f"https://sellercentral.amazon.co.uk/snowdash?ref_=mp_home_logo_xx&cor=mmp_EU&mons_sel_dir_mcid={store['merchant_id']}&mons_sel_mkid={store['marketplace_id']}"
        
        print(f"\n1. Navigating to Chingford dashboard...")
        await page.goto(dash_url, wait_until="networkidle", timeout=60000)
        print("   Done")
        
        # Get the updated cookies
        print("\n2. Extracting cookies after navigation...")
        cookies_list = await context.cookies()
        
        # Convert to dict for aiohttp
        cookies = {}
        for cookie in cookies_list:
            domain = cookie.get('domain', '')
            if 'amazon.co.uk' in domain or 'amazon.com' in domain:
                cookies[cookie['name']] = cookie['value']
        
        print(f"   Got {len(cookies)} cookies")
        
        # Now try calling the metrics API directly
        print("\n3. Calling /metrics API directly with these cookies...")
        
        now = datetime.now()
        params = {
            'merchantIds[]': store['new_id'],
            'startRange[year]': now.year,
            'startRange[month]': now.month - 1,
            'startRange[day]': now.day,
            'startRange[hour]': 0,
            'endRange[year]': now.year,
            'endRange[month]': now.month - 1,
            'endRange[day]': now.day,
            'endRange[hour]': now.hour,
        }
        
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
            'referer': 'https://sellercentral.amazon.co.uk/snowdash',
        }
        
        url = f"https://sellercentral.amazon.co.uk/snowdash/api/metrics?{urlencode(params)}"
        
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        conn = aiohttp.TCPConnector(ssl=ssl_ctx)
        
        async with aiohttp.ClientSession(connector=conn, cookies=cookies) as session:
            async with session.get(url, headers=headers, timeout=30) as resp:
                print(f"   Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        # Check what store data we got
                        first_store = data[0].get('merchantName', 'Unknown') if data else 'Empty'
                        print(f"   First item store: {first_store}")
                        
                        # Calculate Lates
                        total_orders = 0
                        weighted_lates = 0.0
                        for item in data:
                            metrics = item.get('metrics', {})
                            orders = metrics.get('OrdersShopped_V2', 0) or metrics.get('OrdersShopped', 0)
                            late_rate = metrics.get('LatePicksRate', 0.0)
                            if orders > 0:
                                total_orders += orders
                                weighted_lates += late_rate * orders
                        
                        if total_orders > 0:
                            avg_lates = weighted_lates / total_orders
                            print(f"\n✅ RESULT:")
                            print(f"   Total orders: {total_orders}")
                            print(f"   Weighted LatePicksRate: {avg_lates:.2f}%")
                        else:
                            print("   No orders found")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
