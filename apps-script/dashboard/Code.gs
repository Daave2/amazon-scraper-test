/**
 * Amazon Performance Dashboard - Google Apps Script
 * 
 * HISTORICAL DATA VERSION
 * Supports date picker to view past reports (up to 14 days).
 * Data is stored in a GitHub Gist with date-keyed structure.
 */

// ============================================================
// CONFIGURATION - Update with your Gist raw URLs
// ============================================================
const GIST_RAW_URL = 'https://gist.githubusercontent.com/Daave2/267134a093e5906af4aeaf1c6eb50ea1/raw/dashboard_data.json';
const INF_GIST_RAW_URL = 'https://gist.githubusercontent.com/Daave2/ab05f1ce3b536b33e2ee117fb7d5f646/raw/inf_data.json';

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
    // Fetch performance data
    const perfResponse = UrlFetchApp.fetch(GIST_RAW_URL + '?t=' + new Date().getTime(), {
      muteHttpExceptions: true,
      headers: { 'Cache-Control': 'no-cache' }
    });
    
    if (perfResponse.getResponseCode() !== 200) {
      return { ok: false, message: 'Failed to fetch performance data: HTTP ' + perfResponse.getResponseCode() };
    }
    
    const perfData = JSON.parse(perfResponse.getContentText());
    
    // Fetch INF data (optional - backwards compatible)
    try {
      const infResponse = UrlFetchApp.fetch(INF_GIST_RAW_URL + '?t=' + new Date().getTime(), {
        muteHttpExceptions: true,
        headers: { 'Cache-Control': 'no-cache' }
      });
      
      if (infResponse.getResponseCode() === 200) {
        const infData = JSON.parse(infResponse.getContentText());
        // Merge INF data into performance data
        perfData.inf_items = infData.inf_items || {};
      }
    } catch (e) {
      // INF gist not available yet, use data from performance gist if exists
    }
    
    return { ok: true, data: perfData };
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
  
  // Calculate previous day
  const prevDate = new Date(dateKey);
  prevDate.setDate(prevDate.getDate() - 1);
  const prevDateKey = prevDate.toISOString().split('T')[0];
  
  // Get previous day summary for trend comparison
  let prevSummary = null;
  if (result.data.performance && result.data.performance[prevDateKey]) {
    prevSummary = result.data.performance[prevDateKey].summary || null;
  }
  
  // Handle new format (data in performance.{date})
  if (result.data.performance && result.data.performance[dateKey]) {
    const performance = result.data.performance[dateKey];
    return {
      ok: true,
      report_date: dateKey,
      timestamp: result.data.metadata?.last_updated,
      regions: performance.regions || {},
      summary: performance.summary || {},
      prev_summary: prevSummary,
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
      prev_summary: null,
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
