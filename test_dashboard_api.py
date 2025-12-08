#!/usr/bin/env python3
"""
API Discovery Script for Amazon Seller Central Performance Dashboard

This script helps discover API endpoints used by the Performance Dashboard
to determine if we can switch to an API-first approach like we did for INF.

Run this with: python test_dashboard_api.py

It will:
1. Load auth cookies from state.json
2. Navigate to the dashboard and intercept ALL API calls
3. Log the endpoints, payloads, and responses
4. Help identify if we can call these APIs directly
"""

import asyncio
import json
import re
from datetime import datetime
from playwright.async_api import async_playwright

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

# Test store - use first store from urls.csv
import csv
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    first_store = next(reader)
    
MERCHANT_ID = first_store.get('merchant_id', '')
MARKETPLACE_ID = first_store.get('marketplace_id', '')
STORE_NAME = first_store.get('store_name', 'Test Store')

print(f"Testing with store: {STORE_NAME}")
print(f"Merchant ID: {MERCHANT_ID}")
print(f"Marketplace ID: {MARKETPLACE_ID}")
print("-" * 60)

# Storage for captured API calls
captured_apis = []

async def capture_response(response):
    """Capture all API responses for analysis"""
    url = response.url
    
    # Filter for API-like URLs (skip static assets)
    if any(ext in url for ext in ['.js', '.css', '.png', '.jpg', '.gif', '.svg', '.woff', '.ico']):
        return
    if 'google' in url or 'amazon-adsystem' in url or 'cloudfront' in url:
        return
        
    try:
        status = response.status
        content_type = response.headers.get('content-type', '')
        
        # Only capture JSON responses
        if 'json' in content_type and status == 200:
            try:
                body = await response.json()
                
                # Summarize the response
                if isinstance(body, dict):
                    keys = list(body.keys())[:10]  # First 10 keys
                    sample = {k: body.get(k) for k in keys}
                elif isinstance(body, list):
                    sample = f"[Array with {len(body)} items]"
                else:
                    sample = str(body)[:200]
                
                api_info = {
                    'url': url,
                    'status': status,
                    'keys': keys if isinstance(body, dict) else None,
                    'sample': sample,
                    'full_body': body
                }
                captured_apis.append(api_info)
                
                # Print interesting APIs immediately
                if any(kw in url for kw in ['summation', 'metric', 'dashboard', 'performance', 'snow']):
                    print(f"\n🎯 INTERESTING API: {url}")
                    print(f"   Status: {status}")
                    print(f"   Keys: {keys if isinstance(body, dict) else 'N/A'}")
                    
            except Exception as e:
                pass  # Not JSON or can't parse
                
    except Exception as e:
        pass

async def capture_request(request):
    """Capture request details for APIs we might want to call directly"""
    url = request.url
    
    if any(kw in url for kw in ['summation', 'metric', 'dashboard', 'performance']):
        print(f"\n📤 REQUEST: {request.method} {url}")
        print(f"   Headers: {dict(request.headers)}")
        if request.post_data:
            print(f"   Body: {request.post_data[:500]}")

async def main():
    print("Starting API discovery...")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # Visible for debugging
        
        # Load auth state
        try:
            with open('state.json', 'r') as f:
                storage_state = json.load(f)
            context = await browser.new_context(storage_state=storage_state)
            print("✓ Loaded auth state from state.json")
        except FileNotFoundError:
            print("⚠ No state.json found - you may need to login first")
            context = await browser.new_context()
        
        page = await context.new_page()
        
        # Set up listeners BEFORE navigation
        page.on("response", capture_response)
        page.on("request", capture_request)
        
        # Navigate to performance dashboard
        dash_url = f"https://sellercentral.amazon.co.uk/snowdash?ref_=mp_home_logo_xx&cor=mmp_EU&mons_sel_dir_mcid={MERCHANT_ID}&mons_sel_mkid={MARKETPLACE_ID}"
        
        print(f"\n🌐 Navigating to: {dash_url}")
        await page.goto(dash_url, wait_until="networkidle", timeout=60000)
        
        print("\n⏳ Waiting for dashboard to load (15s)...")
        await page.wait_for_timeout(15000)
        
        # Try clicking refresh button to trigger API calls
        try:
            refresh_btn = page.locator("button:has-text('Refresh')")
            if await refresh_btn.count() > 0:
                print("\n🔄 Clicking Refresh button...")
                await refresh_btn.first.click()
                await page.wait_for_timeout(5000)
        except Exception as e:
            print(f"Could not click refresh: {e}")
        
        # Print summary
        print("\n" + "=" * 60)
        print("API DISCOVERY SUMMARY")
        print("=" * 60)
        
        print(f"\nTotal APIs captured: {len(captured_apis)}")
        
        # Group by URL pattern
        metrics_apis = [a for a in captured_apis if 'metric' in a['url'].lower() or 'summation' in a['url'].lower()]
        snow_apis = [a for a in captured_apis if 'snow' in a['url'].lower()]
        other_apis = [a for a in captured_apis if a not in metrics_apis and a not in snow_apis]
        
        print(f"\n📊 Metrics/Summation APIs ({len(metrics_apis)}):")
        for api in metrics_apis:
            print(f"   - {api['url'][:100]}...")
            if api.get('keys'):
                print(f"     Keys: {api['keys']}")
        
        print(f"\n❄️ Snow/Dashboard APIs ({len(snow_apis)}):")
        for api in snow_apis:
            print(f"   - {api['url'][:100]}...")
            if api.get('keys'):
                print(f"     Keys: {api['keys']}")
        
        # Save full results to file
        output_file = 'output/api_discovery_results.json'
        with open(output_file, 'w') as f:
            # Don't include full bodies for large responses
            summary = []
            for api in captured_apis:
                entry = {
                    'url': api['url'],
                    'status': api['status'],
                    'keys': api.get('keys'),
                }
                # Include full body for small responses only
                if isinstance(api.get('full_body'), dict) and len(str(api['full_body'])) < 5000:
                    entry['body'] = api['full_body']
                summary.append(entry)
            json.dump(summary, f, indent=2)
        
        print(f"\n💾 Full results saved to: {output_file}")
        
        # Keep browser open for manual inspection
        print("\n🔍 Browser will stay open for manual inspection. Press Ctrl+C to close.")
        try:
            await asyncio.sleep(300)  # Keep open for 5 minutes
        except asyncio.CancelledError:
            pass
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
