#!/usr/bin/env python3
"""
Investigate the /metrics API endpoint to find Lates calculation data.

This script captures the detailed metrics API response which may contain
per-order timing information we can use to calculate "Lates %".
"""

import asyncio
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode
import aiohttp
import ssl
import certifi

# Load cookies
with open('state.json', 'r') as f:
    state = json.load(f)

cookies = {}
for cookie in state.get('cookies', []):
    domain = cookie.get('domain', '')
    if 'amazon.co.uk' in domain:
        cookies[cookie['name']] = cookie['value']

print(f"Loaded {len(cookies)} cookies")

# Test store
import csv
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    store = next(reader)

MERCHANT_ID = store['merchant_id']
STORE_NAME = store['store_name']

print(f"Testing with: {STORE_NAME}")
print(f"Merchant ID: {MERCHANT_ID}")

# API endpoints to investigate
METRICS_URL = "https://sellercentral.amazon.co.uk/snowdash/api/metrics"
SUMMATION_URL = "https://sellercentral.amazon.co.uk/snowdash/api/summationMetrics"

def build_url(base_url, merchant_id):
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    
    params = {
        'merchantIds[]': merchant_id,
        'startRange[year]': yesterday.year,
        'startRange[month]': yesterday.month - 1,
        'startRange[day]': yesterday.day,
        'startRange[hour]': 0,
        'endRange[year]': now.year,
        'endRange[month]': now.month - 1,
        'endRange[day]': now.day,
        'endRange[hour]': now.hour,
    }
    return f"{base_url}?{urlencode(params)}"

async def investigate_apis():
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    
    headers = {
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'content-type': 'application/json',
        'x-requested-with': 'XMLHttpRequest',
        'referer': 'https://sellercentral.amazon.co.uk/snowdash',
    }
    
    async with aiohttp.ClientSession(connector=connector, cookies=cookies) as session:
        # 1. Get summation metrics (we already have this)
        print("\n" + "=" * 60)
        print("1. SUMMATION METRICS")
        print("=" * 60)
        
        url = build_url(SUMMATION_URL, MERCHANT_ID)
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"Status: {resp.status}")
                print("\nAll fields (looking for Lates-related):")
                for key in sorted(data.keys()):
                    value = data[key]
                    # Highlight anything that might be Lates-related
                    if any(term in key.lower() for term in ['late', 'delay', 'time', 'available', 'unavailable', 'break']):
                        print(f"  ⭐ {key}: {value}")
                    else:
                        print(f"     {key}: {value}")
            else:
                print(f"Error: {resp.status}")
        
        # 2. Get detailed metrics (may have per-order data)
        print("\n" + "=" * 60)
        print("2. DETAILED METRICS (/metrics)")
        print("=" * 60)
        
        url = build_url(METRICS_URL, MERCHANT_ID)
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"Status: {resp.status}")
                print(f"Type: {type(data)}")
                
                if isinstance(data, list):
                    print(f"Array length: {len(data)}")
                    if data:
                        print("\nFirst item structure:")
                        first = data[0]
                        if isinstance(first, dict):
                            for key in sorted(first.keys()):
                                value = first[key]
                                if any(term in key.lower() for term in ['late', 'delay', 'time', 'deadline', 'window', 'due']):
                                    print(f"  ⭐ {key}: {value}")
                                else:
                                    print(f"     {key}: {value}")
                        
                        # Save full sample for analysis
                        with open('output/metrics_sample.json', 'w') as f:
                            json.dump(data[:10], f, indent=2)
                        print(f"\nSaved first 10 items to output/metrics_sample.json")
                        
                elif isinstance(data, dict):
                    print("Dict keys:")
                    for key in sorted(data.keys()):
                        print(f"  {key}: {type(data[key])}")
                    
                    with open('output/metrics_full.json', 'w') as f:
                        json.dump(data, f, indent=2)
                    print(f"\nSaved full response to output/metrics_full.json")
            else:
                text = await resp.text()
                print(f"Error: {resp.status}")
                print(f"Response: {text[:500]}")
        
        # 3. Look for any other APIs we might have missed
        print("\n" + "=" * 60)
        print("3. TIMING ANALYSIS")
        print("=" * 60)
        
        # Re-fetch summation to analyze
        url = build_url(SUMMATION_URL, MERCHANT_ID)
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status == 200:
                data = await resp.json()
                
                # Analyze timing fields
                time_available = data.get('TimeAvailable_V2', 0)  # milliseconds
                time_unavailable = data.get('TimeUnavailable_V2', 0)  # milliseconds
                time_break = data.get('TimeBreak_V2', 0)  # milliseconds
                orders = data.get('OrdersShopped_V2', 0)
                avg_order_time = data.get('AverageOrderTime_V2', 0)  # seconds
                pick_time = data.get('PickTimeInSec_V2', 0)  # seconds
                
                total_time = time_available + time_unavailable
                availability_pct = (time_available / total_time * 100) if total_time > 0 else 0
                
                print(f"\nTiming fields available:")
                print(f"  TimeAvailable_V2:   {time_available:,.0f} ms ({time_available/3600000:.2f} hours)")
                print(f"  TimeUnavailable_V2: {time_unavailable:,.0f} ms ({time_unavailable/3600000:.2f} hours)")
                print(f"  TimeBreak_V2:       {time_break:,.0f} ms ({time_break/3600000:.2f} hours)")
                print(f"  PickTimeInSec_V2:   {pick_time:,.0f} sec ({pick_time/3600:.2f} hours)")
                print(f"  AverageOrderTime_V2: {avg_order_time:.1f} seconds")
                print(f"  OrdersShopped_V2:   {orders}")
                
                print(f"\nCalculated:")
                print(f"  Total shopper time: {total_time/3600000:.2f} hours")
                print(f"  Availability %:     {availability_pct:.1f}%")
                
                # Hypothesis: "Lates" might be related to TimeUnavailable or a threshold calculation
                # Let's look for patterns

if __name__ == "__main__":
    asyncio.run(investigate_apis())
