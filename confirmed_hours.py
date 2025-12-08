"""
Confirmed Hours CSV Parser

Parses the exported Amazon Headcount sheet to extract confirmed hours per store per day.
Used for calculating "Available vs Confirmed Hours" in the daily report.
"""

import csv
import os
from typing import Dict, Optional
from datetime import datetime, timedelta

import logging
app_logger = logging.getLogger(__name__)


def parse_confirmed_hours_csv(csv_path: str) -> Dict[str, Dict]:
    """
    Parse the Amazon Headcount CSV and extract confirmed AND forecasted hours per store.
    
    Returns:
        Dict mapping store name -> {
            'store_number': str,
            'monday_confirmed': float, 'monday_forecast': float,
            'tuesday_confirmed': float, 'tuesday_forecast': float,
            ... (for all days)
            'total_confirmed': float, 'total_forecast': float
        }
    """
    if not os.path.exists(csv_path):
        app_logger.warning(f"Confirmed hours CSV not found: {csv_path}")
        return {}
    
    confirmed_data = {}
    
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        # Find "Total Hours" rows - these contain the daily totals
        for row in rows:
            if len(row) < 18:  # Need at least columns up to Sunday Confirmed
                continue
            
            # Column indices (0-based):
            # 1 = No. (store number)
            # 2 = Store name
            # 3 = Window (look for "Total Hours")
            # 4 = Mon Forecast, 5 = Mon Confirmed
            # 6 = Tue Forecast, 7 = Tue Confirmed
            # 8 = Wed Forecast, 9 = Wed Confirmed
            # 10 = Thu Forecast, 11 = Thu Confirmed
            # 12 = Fri Forecast, 13 = Fri Confirmed
            # 14 = Sat Forecast, 15 = Sat Confirmed
            # 16 = Sun Forecast, 17 = Sun Confirmed
            # 18 = Total Hours provided (confirmed)
            # 19 = Forecasted Hours
            
            window = row[3].strip() if len(row) > 3 else ""
            
            if window.lower() == "total hours":
                store_number = row[1].strip() if len(row) > 1 else ""
                store_name = row[2].strip() if len(row) > 2 else ""
                
                if not store_name:
                    continue
                
                def safe_float(val):
                    try:
                        return float(val.replace(',', '')) if val.strip() else 0.0
                    except (ValueError, AttributeError):
                        return 0.0
                
                # Extract both confirmed (odd columns) and forecast (even columns)
                hours_data = {
                    'store_number': store_number,
                    # Confirmed hours (columns 5, 7, 9, 11, 13, 15, 17)
                    'monday_confirmed': safe_float(row[5] if len(row) > 5 else '0'),
                    'tuesday_confirmed': safe_float(row[7] if len(row) > 7 else '0'),
                    'wednesday_confirmed': safe_float(row[9] if len(row) > 9 else '0'),
                    'thursday_confirmed': safe_float(row[11] if len(row) > 11 else '0'),
                    'friday_confirmed': safe_float(row[13] if len(row) > 13 else '0'),
                    'saturday_confirmed': safe_float(row[15] if len(row) > 15 else '0'),
                    'sunday_confirmed': safe_float(row[17] if len(row) > 17 else '0'),
                    'total_confirmed': safe_float(row[18] if len(row) > 18 else '0'),
                    # Forecasted hours (columns 4, 6, 8, 10, 12, 14, 16)
                    'monday_forecast': safe_float(row[4] if len(row) > 4 else '0'),
                    'tuesday_forecast': safe_float(row[6] if len(row) > 6 else '0'),
                    'wednesday_forecast': safe_float(row[8] if len(row) > 8 else '0'),
                    'thursday_forecast': safe_float(row[10] if len(row) > 10 else '0'),
                    'friday_forecast': safe_float(row[12] if len(row) > 12 else '0'),
                    'saturday_forecast': safe_float(row[14] if len(row) > 14 else '0'),
                    'sunday_forecast': safe_float(row[16] if len(row) > 16 else '0'),
                    'total_forecast': safe_float(row[19] if len(row) > 19 else '0'),
                    # Legacy field names for backward compatibility
                    'monday': safe_float(row[5] if len(row) > 5 else '0'),
                    'tuesday': safe_float(row[7] if len(row) > 7 else '0'),
                    'wednesday': safe_float(row[9] if len(row) > 9 else '0'),
                    'thursday': safe_float(row[11] if len(row) > 11 else '0'),
                    'friday': safe_float(row[13] if len(row) > 13 else '0'),
                    'saturday': safe_float(row[15] if len(row) > 15 else '0'),
                    'sunday': safe_float(row[17] if len(row) > 17 else '0'),
                    'total': safe_float(row[18] if len(row) > 18 else '0'),
                }
                
                # Normalize store name for matching (handle variations)
                normalized_name = normalize_store_name(store_name)
                confirmed_data[normalized_name] = hours_data
                
                # Also store with original name as fallback
                if store_name != normalized_name:
                    confirmed_data[store_name] = hours_data
        
        app_logger.info(f"Loaded confirmed hours for {len(confirmed_data)} stores from {csv_path}")
        return confirmed_data
        
    except Exception as e:
        app_logger.error(f"Error parsing confirmed hours CSV: {e}")
        return {}


def normalize_store_name(name: str) -> str:
    """Normalize store name for matching between CSV and scraped data."""
    # Common variations
    replacements = {
        'Belle vale': 'Belle Vale',
        'Cleveleys': 'Thornton-Cleveleys',  # CSV uses "Cleveleys", Amazon uses "Thornton-Cleveleys"
        'Leeds': 'Hunslet',  # CSV uses "Leeds", Amazon uses "Hunslet"
        'London Stratford': 'Stratford',
        'Cardiff Tyglas': 'Cardiff',
        'WGC': 'Welwyn Garden City',
        'Catcliffe': 'Sheffield',  # Map Catcliffe to Sheffield
    }
    
    cleaned = name.strip()
    return replacements.get(cleaned, cleaned)


def get_confirmed_hours_for_day(
    confirmed_data: Dict[str, Dict],
    store_name: str,
    day_of_week: int  # 0=Monday, 6=Sunday
) -> Optional[float]:
    """
    Get confirmed hours for a specific store on a specific day.
    
    Args:
        confirmed_data: Parsed confirmed hours dict
        store_name: Store name to look up
        day_of_week: 0=Monday, 1=Tuesday, ..., 6=Sunday
    
    Returns:
        Confirmed hours for that day, or None if not found
    """
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    if day_of_week < 0 or day_of_week > 6:
        return None
    
    # Try to find the store
    store_data = confirmed_data.get(store_name)
    
    if not store_data:
        # Try normalized name
        normalized = normalize_store_name(store_name)
        store_data = confirmed_data.get(normalized)
    
    if not store_data:
        return None
    
    return store_data.get(day_names[day_of_week], 0.0)


def get_confirmed_hours_wtd(
    confirmed_data: Dict[str, Dict],
    store_name: str,
    end_day_of_week: int  # 0=Monday, 6=Sunday - WTD is Monday to this day
) -> Optional[float]:
    """
    Get week-to-date confirmed hours for a store (Monday to end_day inclusive).
    
    Args:
        confirmed_data: Parsed confirmed hours dict
        store_name: Store name to look up
        end_day_of_week: 0=Monday, 6=Sunday - sum from Monday to this day
    
    Returns:
        Total confirmed hours for the week-to-date period
    """
    if end_day_of_week < 0 or end_day_of_week > 6:
        return None
    
    # Get store data
    store_data = confirmed_data.get(store_name)
    if not store_data:
        normalized = normalize_store_name(store_name)
        store_data = confirmed_data.get(normalized)
    
    if not store_data:
        return None
    
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    total = 0.0
    for i in range(end_day_of_week + 1):  # 0 to end_day inclusive
        # Use confirmed hours (with _confirmed suffix or legacy names)
        total += store_data.get(f'{day_names[i]}_confirmed', store_data.get(day_names[i], 0.0))
    
    return total


def get_forecast_hours_for_day(
    confirmed_data: Dict[str, Dict],
    store_name: str,
    day_of_week: int  # 0=Monday, 6=Sunday
) -> Optional[float]:
    """
    Get forecasted/requested hours for a specific store on a specific day.
    
    Args:
        confirmed_data: Parsed hours dict (contains both confirmed and forecast)
        store_name: Store name to look up
        day_of_week: 0=Monday, 1=Tuesday, ..., 6=Sunday
    
    Returns:
        Forecasted hours for that day, or None if not found
    """
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    if day_of_week < 0 or day_of_week > 6:
        return None
    
    # Try to find the store
    store_data = confirmed_data.get(store_name)
    
    if not store_data:
        # Try normalized name
        normalized = normalize_store_name(store_name)
        store_data = confirmed_data.get(normalized)
    
    if not store_data:
        return None
    
    return store_data.get(f'{day_names[day_of_week]}_forecast', 0.0)


def get_forecast_hours_wtd(
    confirmed_data: Dict[str, Dict],
    store_name: str,
    end_day_of_week: int  # 0=Monday, 6=Sunday - WTD is Monday to this day
) -> Optional[float]:
    """
    Get week-to-date forecasted/requested hours for a store (Monday to end_day inclusive).
    
    Args:
        confirmed_data: Parsed hours dict
        store_name: Store name to look up
        end_day_of_week: 0=Monday, 6=Sunday - sum from Monday to this day
    
    Returns:
        Total forecasted hours for the week-to-date period
    """
    if end_day_of_week < 0 or end_day_of_week > 6:
        return None
    
    # Get store data
    store_data = confirmed_data.get(store_name)
    if not store_data:
        normalized = normalize_store_name(store_name)
        store_data = confirmed_data.get(normalized)
    
    if not store_data:
        return None
    
    day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    total = 0.0
    for i in range(end_day_of_week + 1):  # 0 to end_day inclusive
        total += store_data.get(f'{day_names[i]}_forecast', 0.0)
    
    return total


def find_headcount_csv(base_dir: str) -> Optional[str]:
    """
    Find the most recent Amazon Headcount CSV in the directory.
    
    Returns:
        Path to the CSV file, or None if not found
    """
    import glob
    
    # Look for files matching the pattern
    patterns = [
        '*Amazon Headcount*.csv',
        '*headcount*.csv',
        'confirmed_hours.csv',
    ]
    
    for pattern in patterns:
        matches = glob.glob(os.path.join(base_dir, pattern))
        if matches:
            # Return the most recently modified one
            matches.sort(key=os.path.getmtime, reverse=True)
            return matches[0]
    
    return None


if __name__ == '__main__':
    # Test the parser
    import sys
    
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = find_headcount_csv('.')
    
    if csv_path:
        print(f"Parsing: {csv_path}")
        data = parse_confirmed_hours_csv(csv_path)
        
        print(f"\nFound {len(data)} stores")
        print("\nSample data (first 5 stores):")
        for i, (name, hours) in enumerate(list(data.items())[:5]):
            print(f"  {name}: Mon={hours['monday']}, Sun={hours['sunday']}, Total={hours['total']}")
    else:
        print("No headcount CSV found")
