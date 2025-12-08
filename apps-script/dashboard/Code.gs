/**
 * Amazon Performance Dashboard - Google Apps Script
 * 
 * HISTORICAL DATA VERSION
 * Supports date picker to view past reports (up to 14 days).
 * Data is stored in a GitHub Gist with date-keyed structure.
 */

// ============================================================
// CONFIGURATION - Update this with your Gist raw URL
// ============================================================
const GIST_RAW_URL = 'https://gist.githubusercontent.com/Daave2/267134a093e5906af4aeaf1c6eb50ea1/raw/dashboard_data.json';

/**
 * Serve the dashboard HTML page
 */
function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('Amazon Performance Dashboard')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * Fetch the full dashboard data including all available dates
 */
function getDashboardData() {
  try {
    const response = UrlFetchApp.fetch(GIST_RAW_URL + '?t=' + new Date().getTime(), {
      muteHttpExceptions: true,
      headers: { 'Cache-Control': 'no-cache' }
    });
    
    if (response.getResponseCode() === 200) {
      const data = JSON.parse(response.getContentText());
      return { ok: true, data: data };
    } else {
      return { ok: false, message: 'Failed to fetch: HTTP ' + response.getResponseCode() };
    }
  } catch (error) {
    return { ok: false, message: 'Error: ' + error.message };
  }
}

/**
 * Get available dates for the date picker
 */
function getAvailableDates() {
  const result = getDashboardData();
  if (!result.ok) return result;
  
  // Handle new format (has metadata.available_dates)
  if (result.data.metadata && result.data.metadata.available_dates) {
    return { ok: true, dates: result.data.metadata.available_dates };
  }
  
  // Handle old format (single date at root)
  if (result.data.report_date) {
    return { ok: true, dates: [result.data.report_date] };
  }
  
  return { ok: true, dates: [] };
}

/**
 * Get report data for a specific date
 */
function getReportForDate(dateKey) {
  const result = getDashboardData();
  if (!result.ok) return result;
  
  // Handle new format (data in performance.{date})
  if (result.data.performance && result.data.performance[dateKey]) {
    const performance = result.data.performance[dateKey];
    return {
      ok: true,
      report_date: dateKey,
      timestamp: result.data.metadata?.last_updated,
      regions: performance.regions || {},
      summary: performance.summary || {},
      stores_count: performance.stores_count || 0,
      available_dates: result.data.metadata?.available_dates || [dateKey]
    };
  }
  
  // Handle old format (data at root level)
  if (result.data.regions && result.data.report_date === dateKey) {
    return {
      ok: true,
      report_date: result.data.report_date,
      timestamp: result.data.timestamp,
      regions: result.data.regions,
      summary: result.data.summary || {},
      stores_count: result.data.stores_count || 0,
      available_dates: [result.data.report_date]
    };
  }
  
  return { ok: false, message: 'No data for date: ' + dateKey };
}

/**
 * Get the latest report (most recent date)
 */
function getLatestReportData() {
  const result = getDashboardData();
  if (!result.ok) return result;
  
  // Handle new format (has metadata.available_dates)
  if (result.data.metadata && result.data.metadata.available_dates && result.data.metadata.available_dates.length > 0) {
    const latestDate = result.data.metadata.available_dates[0];
    return getReportForDate(latestDate);
  }
  
  // Handle old format (single report at root)
  if (result.data.regions) {
    return {
      ok: true,
      report_date: result.data.report_date || new Date().toISOString().split('T')[0],
      timestamp: result.data.timestamp,
      regions: result.data.regions,
      summary: result.data.summary || {},
      stores_count: result.data.stores_count || 0,
      available_dates: result.data.report_date ? [result.data.report_date] : []
    };
  }
  
  return { ok: false, message: 'No report data available. Run the scraper with --generate-report.' };
}

/**
 * Get INF items data for a specific date
 */
function getINFItemsForDate(dateKey) {
  const result = getDashboardData();
  if (!result.ok) return result;
  
  const infData = result.data.inf_items?.[dateKey];
  if (!infData) {
    return { ok: false, message: 'No INF data for date: ' + dateKey };
  }
  
  return {
    ok: true,
    report_date: dateKey,
    stores: infData.stores || {},
    store_count: infData.store_count || 0
  };
}

/**
 * Get available dates that have INF data
 */
function getINFDates() {
  const result = getDashboardData();
  if (!result.ok) return result;
  
  const infDates = Object.keys(result.data.inf_items || {}).sort().reverse();
  return { ok: true, dates: infDates };
}
