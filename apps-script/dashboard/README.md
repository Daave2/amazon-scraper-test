# Amazon Performance Dashboard

A Google Apps Script web app that displays daily performance reports in a shareable dashboard.

## Features

- 📊 **Real-time dashboard** - Auto-updates when scraper runs
- 📱 **Mobile-friendly** - Responsive design works on all devices
- 🔒 **Works with Workspace restrictions** - Uses GitHub Gist for data transfer
- 📈 **Rich metrics** - INF, Lates, UPH, Available vs Confirmed Hours, Financial metrics

## Architecture

```
Scraper runs → Updates GitHub Gist → Apps Script reads Gist → Dashboard displays
```

This approach works with Google Workspace restrictions because:
- The Gist is publicly readable
- Apps Script only needs to READ from the Gist (no external webhooks needed)
- Scraper uses your existing GIST_TOKEN to update the Gist

## Setup Instructions

### Step 1: Create a GitHub Gist for Dashboard Data

1. Go to [gist.github.com](https://gist.github.com)
2. Create a **new public gist** with:
   - **Filename:** `dashboard_data.json`
   - **Content:** `{}`
3. Click **Create public gist**
4. Copy the **Gist ID** from the URL (the long string after your username)
   - Example: `https://gist.github.com/Daave2/abc123def456` → ID is `abc123def456`
5. Copy the **Raw URL** for the file:
   - Click on `dashboard_data.json`
   - Click **Raw** button
   - Copy the URL (e.g., `https://gist.githubusercontent.com/Daave2/abc123def456/raw/dashboard_data.json`)

### Step 2: Update config.json

Add these to your `config.json`:

```json
{
  "dashboard_gist_id": "abc123def456",
  "gist_token": "ghp_your_github_token"
}
```

> **Note:** You can reuse your existing `GIST_TOKEN` if you have one configured.

### Step 3: Create the Apps Script Project

1. Go to [script.google.com](https://script.google.com)
2. Click **New Project**
3. Rename to "Amazon Performance Dashboard"

### Step 4: Add the Files

1. Replace `Code.gs` content with the file from this folder
2. **Important:** Update the `GIST_RAW_URL` constant with your raw Gist URL:
   ```javascript
   const GIST_RAW_URL = 'https://gist.githubusercontent.com/Daave2/YOUR_GIST_ID/raw/dashboard_data.json';
   ```
3. Click **+** next to Files → **HTML** → Name it `Index`
4. Replace content with `Index.html` from this folder

### Step 5: Deploy as Web App

1. Click **Deploy** → **New deployment**
2. Click gear icon → Choose **Web app**
3. Configure:
   - **Execute as:** Me
   - **Who has access:** Anyone within [your organization]
4. Click **Deploy** and **Authorize**
5. Copy the **Web app URL** - this is your dashboard link!

### Step 6: Test It

Run the scraper:
```bash
python scraper.py --date-mode yesterday --generate-report
```

You should see:
```
✅ Dashboard Gist updated successfully
```

Visit your dashboard URL to see the report!

## Sharing the Dashboard

Share the Apps Script Web App URL with your team. Anyone in your organization can view it.

## Troubleshooting

### "Dashboard data not found"
Run the scraper with `--generate-report` to populate the Gist.

### "Dashboard Gist ID not configured"
Add `dashboard_gist_id` to your `config.json`.

### "Gist token not configured"  
Add `gist_token` to your `config.json` (same token used for bearer token updates).

### HTTP 404 when updating Gist
Check that `dashboard_gist_id` matches your Gist exactly.

### HTTP 401 when updating Gist
Your `gist_token` needs the `gist` scope. Generate a new token at GitHub → Settings → Developer settings → Personal access tokens.
