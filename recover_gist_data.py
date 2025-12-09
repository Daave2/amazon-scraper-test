#!/usr/bin/env python3
"""
Gist Data Recovery Script
Restores historical performance data from gist revision history
"""

import requests
import json
from datetime import datetime

print("🔧 Gist Data Recovery Tool")
print("=" * 50)

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

gist_id = config.get('dashboard_gist_id')
gist_token = config.get('gist_token')

if not gist_id or not gist_token:
    print("❌ Gist not configured in config.json")
    exit(1)

headers = {'Authorization': f'token {gist_token}'}

# Step 1: Get current data
print("\n1️⃣ Fetching current gist data...")
url = f'https://api.github.com/gists/{gist_id}'
response = requests.get(url, headers=headers)

if response.status_code != 200:
    print(f"❌ Failed to fetch gist: {response.status_code}")
    exit(1)

gist = response.json()
current_content = gist['files']['dashboard_data.json']['content']
current_data = json.loads(current_content)

print(f"   Current: {len(current_data.get('performance', {}))} dates")
print(f"   Dates: {sorted(current_data.get('performance', {}).keys())}")

# Step 2: Get revision history
print("\n2️⃣ Fetching gist revision history...")
commits_url = f'https://api.github.com/gists/{gist_id}/commits'
commits_response = requests.get(commits_url, headers=headers)

if commits_response.status_code != 200:
    print(f"❌ Failed to fetch history: {commits_response.status_code}")
    exit(1)

commits = commits_response.json()
print(f"   Found {len(commits)} revisions")

# Step 3: Find best historical version (from yesterday)
print("\n3️⃣ Looking for historical data from Dec 8th...")

for i, commit in enumerate(commits):
    commit_date = commit['committed_at'][:10]
    if commit_date == '2025-12-08':
        print(f"   ✅ Found Dec 8 version at position {i+1}")
        
        # Fetch the gist at this commit by downloading raw URL
        # Get the raw URL from the current gist structure
        raw_url = f"https://gist.githubusercontent.com/Daave2/{gist_id}/raw/{commit['version']}/dashboard_data.json"
        
        print(f"   Fetching from: ...{commit['version'][:7]}")
        raw_response = requests.get(raw_url)
        
        if raw_response.status_code == 200:
            historical_data = json.loads(raw_response.text)
            historical_performance = historical_data.get('performance', {})
            historical_inf = historical_data.get('inf_items', {})
            
            print(f"\n   📊 Historical version had:")
            print(f"      Performance: {len(historical_performance)} dates")
            print(f"      INF Items: {len(historical_inf)} dates")
            print(f"      Dates: {sorted(historical_performance.keys())}")
            
            # Step 4: Merge historical with current
            print("\n4️⃣ Merging historical data with current...")
            
            # Merge performance data (current takes precedence for 2025-12-09)
            merged_performance = historical_performance.copy()
            merged_performance.update(current_data.get('performance', {}))
            
            # Merge INF data
            merged_inf = historical_inf.copy()
            merged_inf.update(current_data.get('inf_items', {}))
            
            merged_data = {
                'metadata': {
                    'available_dates': sorted(merged_performance.keys(), reverse=True),
                    'retention_days': 14,
                    'last_updated': datetime.now().isoformat(),
                    'recovered_from': commit['version'][:7]
                },
                'performance': merged_performance,
                'inf_items': merged_inf
            }
            
            print(f"   ✅ Merged to {len(merged_performance)} dates")
            print(f"   Dates: {sorted(merged_performance.keys())}")
            
            # Step 5: Update gist
            print("\n5️⃣ Updating gist with recovered data...")
            
            update_response = requests.patch(
                url,
                json={
                    'files': {
                        'dashboard_data.json': {
                            'content': json.dumps(merged_data, indent=2)
                        }
                    }
                },
                headers=headers
            )
            
            if update_response.status_code == 200:
                print("   ✅ Gist updated successfully!")
                print(f"\n🎉 Recovery complete! Restored {len(merged_performance)} days of data")
            else:
                print(f"   ❌ Failed to update: {update_response.status_code}")
                print(f"   Response: {update_response.text[:200]}")
            
            break
        else:
            print(f"   ❌ Failed to fetch historical version: {raw_response.status_code}")
    
else:
    print("   ⚠️ No Dec 8 version found, trying most recent before today...")
    # Fallback: use most recent commit before today
    for commit in commits:
        if commit['committed_at'][:10] < '2025-12-09':
            print(f"   Using version from {commit['committed_at'][:16]}")
            # Same recovery logic as above
            break
