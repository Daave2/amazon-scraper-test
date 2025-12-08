#!/usr/bin/env python3
"""
Test Direct API Calls to Amazon Seller Central Performance Dashboard

This script tests if we can call the summationMetrics API directly
without using a browser, using cookies from state.json.

Based on API Discovery Results:
- Endpoint: https://sellercentral.amazon.co.uk/snowdash/api/summationMetrics
- Method: GET
- Auth: Session cookies
- Headers: x-requested-with: XMLHttpRequest, content-type: application/json
"""

import asyncio
import aiohttp
import json
import csv
import ssl
import certifi
from datetime import datetime, timedelta
from urllib.parse import urlencode

# Load config and auth state
with open('config.json', 'r') as f:
    config = json.load(f)

with open('state.json', 'r') as f:
    state = json.load(f)

# Extract cookies from state.json - include all amazon cookies
cookies = {}
for cookie in state.get('cookies', []):
    domain = cookie.get('domain', '')
    if 'amazon.co.uk' in domain or 'amazon.com' in domain:
        cookies[cookie['name']] = cookie['value']

print(f"Loaded {len(cookies)} cookies for sellercentral.amazon.co.uk")

# Load test stores from urls.csv
stores = []
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        stores.append(row)
        if len(stores) >= 5:  # Test with first 5 stores
            break

print(f"Testing with {len(stores)} stores")

# API URL Template
# From discovery: https://sellercentral.amazon.co.uk/snowdash/api/summationMetrics?merchantIds[]=AHX1VDQB3N63T&startRange[year]=2025&startRange[month]=11&...
BASE_URL = "https://sellercentral.amazon.co.uk/snowdash/api/summationMetrics"

def build_api_url(merchant_id: str, start_date: datetime = None, end_date: datetime = None) -> str:
    """Build the summationMetrics API URL with query parameters"""
    
    if not start_date:
        start_date = datetime.now() - timedelta(days=1)  # Yesterday
    if not end_date:
        end_date = datetime.now()
    
    # Build query params matching what we observed
    params = {
        'merchantIds[]': merchant_id,
        'startRange[year]': start_date.year,
        'startRange[month]': start_date.month - 1,  # 0-indexed in API
        'startRange[day]': start_date.day,
        'startRange[hour]': 0,
        'endRange[year]': end_date.year,
        'endRange[month]': end_date.month - 1,  # 0-indexed in API
        'endRange[day]': end_date.day,
        'endRange[hour]': end_date.hour,
    }
    
    return f"{BASE_URL}?{urlencode(params)}"

async def test_direct_api_call(session: aiohttp.ClientSession, store: dict) -> dict:
    """Test calling the API directly for a single store"""
    
    store_name = store.get('store_name', 'Unknown')
    merchant_id = store.get('merchant_id', '')
    
    # The merchant ID in URL params seems to be a different format
    # From discovery, it uses 'AHX1VDQB3N63T' format, not the full amzn1.merchant.d.xxx
    # We may need to extract or convert this
    
    # Try with the full merchant ID first
    api_url = build_api_url(merchant_id)
    
    headers = {
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'content-type': 'application/json',
        'x-requested-with': 'XMLHttpRequest',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'referer': 'https://sellercentral.amazon.co.uk/snowdash',
    }
    
    print(f"\n🔄 Testing {store_name}...")
    print(f"   URL: {api_url[:100]}...")
    
    try:
        async with session.get(api_url, headers=headers, timeout=15) as resp:
            status = resp.status
            print(f"   Status: {status}")
            
            if status == 200:
                data = await resp.json()
                
                # Check if we got real data
                orders = data.get('OrdersShopped_V2', 0)
                uph = data.get('AverageUPH_V2', 0)
                inf = data.get('ItemNotFoundRate_V2', 0)
                
                print(f"   ✅ SUCCESS! Orders: {orders}, UPH: {uph:.0f}, INF: {inf:.1f}%")
                
                # Print all available fields
                print(f"   Available fields ({len(data)} total):")
                for key in sorted(data.keys()):
                    print(f"      - {key}: {data[key]}")
                
                return {'success': True, 'store': store_name, 'data': data}
            else:
                text = await resp.text()
                print(f"   ❌ Failed: {text[:200]}")
                return {'success': False, 'store': store_name, 'status': status, 'error': text[:200]}
                
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {'success': False, 'store': store_name, 'error': str(e)}

async def main():
    print("=" * 60)
    print("DIRECT API TEST - Performance Dashboard")
    print("=" * 60)
    
    # Create SSL context
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    # Create cookie jar and add our cookies
    jar = aiohttp.CookieJar()
    
    async with aiohttp.ClientSession(connector=connector, cookies=cookies) as session:
        results = []
        for store in stores:
            result = await test_direct_api_call(session, store)
            results.append(result)
            await asyncio.sleep(0.5)  # Polite delay
        
        # Summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        
        success_count = sum(1 for r in results if r.get('success'))
        print(f"\nSuccess: {success_count}/{len(results)}")
        
        if success_count == 0:
            print("\n⚠️ All direct API calls failed.")
            print("This may mean:")
            print("  1. We need to visit the dashboard first to get additional tokens")
            print("  2. The merchant ID format needs conversion")
            print("  3. Additional headers or cookies are required")
            print("\nThe hybrid approach (browser + API intercept) may still be best.")
        else:
            print("\n✅ Direct API calls work!")
            print("We can potentially eliminate browser dependency entirely.")

if __name__ == "__main__":
    asyncio.run(main())
