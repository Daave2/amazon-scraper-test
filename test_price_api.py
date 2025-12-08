#!/usr/bin/env python3
"""
Test script to investigate Morrisons Price Integrity API response structure
"""
import requests
import json
from stock_enrichment import fetch_bearer_token_from_gist

# Test with a known SKU from recent data
TEST_SKU = "110974949"  # Highland Spring water from Woking
TEST_LOCATION = "099"  # Woking store number

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

API_KEY = config['morrisons_api_key']
BEARER_TOKEN_URL = config.get('morrisons_bearer_token_url')

# Fetch bearer token
print(f"Fetching bearer token from: {BEARER_TOKEN_URL}")
bearer_token = fetch_bearer_token_from_gist(BEARER_TOKEN_URL)
print(f"Token fetched: {bearer_token[:20]}..." if bearer_token else "Failed to fetch token")
print()

# Test Price Integrity API
pi_url = f"https://api.morrisons.com/priceintegrity/v1/locations/{TEST_LOCATION}/items/{TEST_SKU}?apikey={API_KEY}"

headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Price Test)",
}
if bearer_token:
    headers["Authorization"] = f"Bearer {bearer_token}"

print(f"Testing Price Integrity API:")
print(f"URL: {pi_url}")
print(f"Headers: {json.dumps({k: v[:20]+'...' if k == 'Authorization' else v for k, v in headers.items()}, indent=2)}")
print()

response = requests.get(pi_url, headers=headers, timeout=15)
print(f"Status: {response.status_code}")
print()

if response.status_code == 200:
    data = response.json()
    print("Full API Response:")
    print(json.dumps(data, indent=2))
    print()
    
    # Check for price fields
    print("="*60)
    print("PRICE FIELD ANALYSIS:")
    print("="*60)
    
    if 'prices' in data:
        print(f"✓ 'prices' field exists: {data['prices']}")
        if isinstance(data['prices'], list) and len(data['prices']) > 0:
            print(f"  First price entry: {json.dumps(data['prices'][0], indent=4)}")
    else:
        print("✗ 'prices' field NOT found in response")
    
    # Check all top-level keys that might contain price info
    print("\nAll top-level keys:")
    for key in data.keys():
        print(f"  - {key}: {type(data[key]).__name__}")
        if 'price' in key.lower():
            print(f"    → Contains 'price' in name! Value: {data[key]}")
    
    # Deep search for any price-related fields
    print("\nSearching entire response for 'price' keywords...")
    def find_price_fields(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if 'price' in k.lower():
                    print(f"  Found at {path}.{k}: {v}")
                find_price_fields(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                find_price_fields(item, f"{path}[{i}]")
    
    find_price_fields(data)
    
else:
    print(f"Error: {response.text}")
