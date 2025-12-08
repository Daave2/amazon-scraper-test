#!/usr/bin/env python3
"""Test the new fetch_store_metrics_with_lates_browser function"""

import asyncio
import csv
import json
from playwright.async_api import async_playwright
from api_scraper import fetch_store_metrics_with_lates_browser

# Find Chingford
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if 'Chingford' in row.get('store_name', ''):
            store = row
            break

print(f"Testing: {store['store_name']}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Load auth
        with open('state.json', 'r') as f:
            storage_state = json.load(f)
        context = await browser.new_context(storage_state=storage_state)
        
        page = await context.new_page()
        
        print("\nFetching with Lates...")
        success, data = await fetch_store_metrics_with_lates_browser(page, store)
        
        if success:
            print("\n✅ SUCCESS!")
            print("\nData:")
            for key, value in data.items():
                if key != '_api_data':
                    print(f"  {key}: {value}")
            
            print(f"\n🎯 Lates: {data['lates']}")
        else:
            print(f"\n❌ FAILED: {data}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
