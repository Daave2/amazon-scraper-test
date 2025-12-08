import json
import os
from datetime import datetime, timedelta
import csv
import glob

from confirmed_hours import (
    parse_confirmed_hours_csv, 
    get_confirmed_hours_for_day, 
    get_confirmed_hours_wtd,
    get_forecast_hours_for_day,
    get_forecast_hours_wtd,
    find_headcount_csv
)

class ReportGenerator:
    def __init__(self, managers_file='managers.json', output_dir='output', headcount_csv=None):
        self.managers_file = managers_file
        self.output_dir = output_dir
        self.load_managers()
        self.load_confirmed_hours(headcount_csv)
        
    def load_managers(self):
        try:
            with open(self.managers_file, 'r') as f:
                data = json.load(f)
                self.store_map = data.get('stores', {})
                self.settings = data.get('settings', {'hourly_rate': 11.00, 'avg_item_value': 3.50})
        except FileNotFoundError:
            print(f"Warning: {self.managers_file} not found. Grouping will be limited.")
            self.store_map = {}
            self.settings = {'hourly_rate': 11.00, 'avg_item_value': 3.50}
    
    def load_confirmed_hours(self, headcount_csv=None):
        """Load confirmed hours from CSV file."""
        self.confirmed_hours = {}
        
        # Find the CSV if not specified
        if headcount_csv is None:
            headcount_csv = find_headcount_csv('.')
        
        if headcount_csv:
            self.confirmed_hours = parse_confirmed_hours_csv(headcount_csv)
            print(f"Loaded confirmed hours for {len(self.confirmed_hours)} stores")
        else:
            print("Warning: No headcount CSV found. Confirmed hours will not be available.")

    def process_data(self, store_data_list, report_date=None):
        """Aggregate and enrich data for the report."""
        regions = {'North': {}, 'South': {}, 'Unknown': {}}
        
        # Determine the report date (yesterday by default)
        if report_date is None:
            report_date = datetime.now() - timedelta(days=1)
        elif isinstance(report_date, str):
            report_date = datetime.strptime(report_date, '%Y-%m-%d')
        
        # Get day of week for confirmed hours lookup (0=Monday, 6=Sunday)
        day_of_week = report_date.weekday()
        
        for entry in store_data_list:
            store_name = entry.get('store', 'Unknown').replace('Morrisons - ', '')
            meta = self.store_map.get(store_name, {'region': 'Unknown', 'manager': 'Unassigned'})
            region = meta.get('region', 'Unknown')
            manager = meta.get('manager', 'Unassigned')
            
            if region not in regions:
                regions[region] = {}
            if manager not in regions[region]:
                regions[region][manager] = []

            # Extract basic metrics
            def parse_metric(val):
                if isinstance(val, str):
                    clean = val.replace('%', '').strip()
                    if clean == '' or clean == 'N/A': return 0.0
                    return float(clean)
                return float(val or 0)

            inf_y = parse_metric(entry.get('inf', 0))
            inf_wtd = parse_metric(entry.get('inf_WTD', 0) if entry.get('has_wtd') else entry.get('inf', 0))
            
            lates_y = parse_metric(entry.get('lates', 0))
            lates_wtd = parse_metric(entry.get('lates_WTD', 0) if entry.get('has_wtd') else entry.get('lates', 0))
            
            uph_y = parse_metric(entry.get('uph', 0))
            uph_wtd = parse_metric(entry.get('uph_WTD', 0) if entry.get('has_wtd') else entry.get('uph', 0))
            
            # Calculate Available vs Confirmed Hours, Available vs Requested, and financials
            metrics = self._calculate_avc(entry, store_name, day_of_week)
            
            row = {
                'store': store_name,
                'rate_my_exp': 0.0, # Placeholder - removed from report for now
                'inf_y': inf_y,
                'inf_wtd': inf_wtd,
                'lates_y': lates_y,
                'lates_wtd': lates_wtd,
                'uph_y': uph_y,
                'uph_wtd': uph_wtd,
                'avc_y': metrics['avc_y'],
                'avc_wtd': metrics['avc_wtd'],
                'avr_wtd': metrics['avr_wtd'],
                'forecast_wtd': metrics['forecast_wtd'],  # Total Requested Hours
                'wasted_payroll': metrics['wasted_payroll'],
                'missed_sales': metrics['missed_sales'],
            }
            regions[region][manager].append(row)
            
        return regions
    
    def _calculate_avc(self, entry, store_name, day_of_week):
        """Calculate Available vs Confirmed Hours, Available vs Requested, and financial metrics.
        
        Formulas:
        - Available vs Confirmed = (Available Hours / Confirmed Hours) × 100
        - Available vs Requested = (Available Hours / Forecasted Hours) × 100
        - Hours Lost = max(0, Confirmed Hours - Available Hours)
        - Wasted Payroll = Hours Lost × £11/hour
        - Missed Sales = Hours Lost × £152/hour (avg sales per productive hour)
        """
        # Constants
        HOURLY_RATE = 11.0  # £11 per hour
        SALES_PER_HOUR = 152.0  # £152 average sales per productive hour
        
        avc_y = None
        avc_wtd = None
        avr_wtd = None
        hours_lost_wtd = 0.0
        wasted_payroll = 0.0
        missed_sales = 0.0
        forecast_wtd = None
        
        # Get available hours from API data
        api_data = entry.get('_api_data', {})
        available_hours_y = api_data.get('time_available_hours', 0.0)
        
        # Fallback: parse from formatted time_available string (e.g., "3:45")
        if not available_hours_y:
            time_str = entry.get('time_available', '0:00')
            try:
                parts = time_str.split(':')
                if len(parts) == 2:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    available_hours_y = hours + (minutes / 60.0)
            except (ValueError, IndexError):
                available_hours_y = 0.0
        
        # Get WTD available hours
        available_hours_wtd = api_data.get('time_available_hours_wtd', 0.0)
        if not available_hours_wtd:
            time_str_wtd = entry.get('time_available_WTD', entry.get('time_available', '0:00'))
            try:
                parts = time_str_wtd.split(':')
                if len(parts) == 2:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    available_hours_wtd = hours + (minutes / 60.0)
            except (ValueError, IndexError):
                available_hours_wtd = 0.0
        
        # Get confirmed hours from CSV
        confirmed_y = get_confirmed_hours_for_day(self.confirmed_hours, store_name, day_of_week)
        confirmed_wtd = get_confirmed_hours_wtd(self.confirmed_hours, store_name, day_of_week)
        
        # Get forecasted (requested) hours from CSV  
        forecast_wtd = get_forecast_hours_wtd(self.confirmed_hours, store_name, day_of_week)
        
        # Calculate Available vs Confirmed percentages
        if confirmed_y and confirmed_y > 0 and available_hours_y > 0:
            avc_y = round((available_hours_y / confirmed_y) * 100, 1)
        
        if confirmed_wtd and confirmed_wtd > 0 and available_hours_wtd > 0:
            avc_wtd = round((available_hours_wtd / confirmed_wtd) * 100, 1)
        
        # Calculate Available vs Requested (Forecasted) percentage
        if forecast_wtd and forecast_wtd > 0 and available_hours_wtd > 0:
            avr_wtd = round((available_hours_wtd / forecast_wtd) * 100, 1)
        
        # Calculate financial metrics (based on confirmed vs available)
        if confirmed_wtd and confirmed_wtd > 0 and available_hours_wtd > 0:
            hours_lost_wtd = max(0, confirmed_wtd - available_hours_wtd)
            if hours_lost_wtd > 0:
                wasted_payroll = round(hours_lost_wtd * HOURLY_RATE, 0)  # £11 per hour
                missed_sales = round(hours_lost_wtd * SALES_PER_HOUR, 0)  # £152 per hour
        
        return {
            'avc_y': avc_y,
            'avc_wtd': avc_wtd,
            'avr_wtd': avr_wtd,
            'forecast_wtd': forecast_wtd,  # Total requested hours
            'hours_lost_wtd': hours_lost_wtd,
            'wasted_payroll': wasted_payroll,
            'missed_sales': missed_sales,
        }

    def generate_html(self, regions_data):
        """Generate HTML report string matching the screenshot."""
        date_str = datetime.now().strftime("%d/%m/%Y")
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #ffffff; padding: 20px; }}
                .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
                .title {{ font-size: 24px; font-weight: 500; }}
                .date {{ font-size: 18px; font-weight: bold; }}
                
                table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 30px; }}
                th {{ background-color: #f2f2f2; border: 1px solid #ccc; padding: 1px; text-align: center; font-weight: normal; vertical-align: middle; height: 50px; }}
                td {{ border: 1px solid #ccc; padding: 4px; text-align: center; }}
                
                .manager-col {{ text-align: left; font-weight: bold; background-color: #fff; width: 120px; }}
                .store-col {{ text-align: left; width: 120px; }}
                
                /* Conditional Formatting Colors */
                .bg-green {{ background-color: #88dba3; }} /* Light Green */
                .bg-red {{ background-color: #eba5a5; }}   /* Light Red */
                .bg-amber {{ background-color: #fcbc7e; }} /* Amber/Orange */
                
                /* Column Widths */
                .col-metric {{ width: 60px; }}
                .col-financial {{ width: 80px; }}
                
                .section-header {{ text-align: left; background-color: #ddd; font-weight: bold; padding: 5px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div class="title">Amazon Daily Update</div>
                <div class="date">{date_str}</div>
            </div>
        """

        # Order of regions to display
        region_order = ['North', 'South', 'Unknown']
        
        for region_name in region_order:
            managers_data = regions_data.get(region_name, {})
            if not managers_data:
                continue
                
            html += self._generate_region_table(region_name, managers_data)

        html += "</body></html>"
        return html

    def _generate_region_table(self, region_name, managers_data):
        html = f"""
        <h3>{region_name}</h3>
        <table>
            <thead>
                <tr style="background-color: #f2f2f2;">
                    <th colspan="2" style="text-align: left; padding-left: 10px; font-weight: bold;">{datetime.now().strftime("%A %d %B")}</th>
                    <th class="col-metric">Rate My<br>Experience<br>Week 5</th>
                    <th class="col-metric">Items Not Found<br>Yesterday</th>
                    <th class="col-metric">Items Not Found<br>Week to date</th>
                    <th class="col-metric">Late Picks<br>Yesterday</th>
                    <th class="col-metric">Late Picks<br>Week to date</th>
                    <th class="col-metric">Units Picked Per<br>Hour Yesterday</th>
                    <th class="col-metric">Units Picked Per<br>Hour Week to date</th>
                    <th class="col-metric">Available Vs<br>Confirmed Hours<br>Yesterday</th>
                    <th class="col-metric">Available Vs<br>Confirmed Hours<br>WTD</th>
                    <th class="col-metric">Available Vs<br>Requested Hours<br>WTD</th>
                    <th class="col-financial">Wasted Payroll<br>WTD</th>
                    <th class="col-financial">Missed Sales<br>Opportunity WTD</th>
                </tr>
            </thead>
            <tbody>
        """
        
        # Sort managers alphabetically
        sorted_managers = sorted(managers_data.keys())
        
        for manager in sorted_managers:
            stores = managers_data[manager]
            # Merge cell for manager name (rowspan)
            rowspan = len(stores)
            
            for i, row in enumerate(stores):
                html += "<tr>"
                # Manager Column (only first row)
                if i == 0:
                    html += f"<td class='manager-col' rowspan='{rowspan}'>{manager}</td>"
                
                html += f"<td class='store-col'>{row['store']}</td>"
                
                # Metrics with conditional formatting
                # Note: Thresholds are illustrative. Adjust as needed.
                # Lower is better: INF, Lates
                # Higher is better: Rate My Exp, UPH, AVC
                
                html += f"<td class='{self._color_high(row['rate_my_exp'], 70, 50)}'>-</td>" # Placeholder
                html += f"<td class='{self._color_low(row['inf_y'], 1.5, 3.0)}'>{row['inf_y']}%</td>"
                html += f"<td class='{self._color_low(row['inf_wtd'], 1.5, 3.0)}'>{row['inf_wtd']}%</td>"
                html += f"<td class='{self._color_low(row['lates_y'], 0.5, 2.0)}'>{row['lates_y']}%</td>"
                html += f"<td class='{self._color_low(row['lates_wtd'], 0.5, 2.0)}'>{row['lates_wtd']}%</td>"
                html += f"<td class='{self._color_high(row['uph_y'], 90, 80)}'>{row['uph_y']}</td>"
                html += f"<td class='{self._color_high(row['uph_wtd'], 90, 80)}'>{row['uph_wtd']}</td>"
                
                # Available vs Confirmed Hours - display value or "-" if not calculable
                avc_y_display = f"{row['avc_y']}%" if row['avc_y'] is not None else "-"
                avc_wtd_display = f"{row['avc_wtd']}%" if row['avc_wtd'] is not None else "-"
                avc_y_class = self._color_high(row['avc_y'] or 0, 95, 85) if row['avc_y'] else ''
                avc_wtd_class = self._color_high(row['avc_wtd'] or 0, 95, 85) if row['avc_wtd'] else ''
                
                # Available vs Requested (Forecasted) Hours - WTD only
                avr_wtd_display = f"{row['avr_wtd']}%" if row['avr_wtd'] is not None else "-"
                avr_wtd_class = self._color_high(row['avr_wtd'] or 0, 95, 85) if row['avr_wtd'] else ''
                
                html += f"<td class='{avc_y_class}'>{avc_y_display}</td>"
                html += f"<td class='{avc_wtd_class}'>{avc_wtd_display}</td>"
                html += f"<td class='{avr_wtd_class}'>{avr_wtd_display}</td>"
                
                # Financial metrics - display with £ formatting or "-" if zero/not calculable
                wasted = row.get('wasted_payroll', 0)
                missed = row.get('missed_sales', 0)
                wasted_display = f"£{int(wasted):,}" if wasted and wasted > 0 else "-"
                missed_display = f"£{int(missed):,}" if missed and missed > 0 else "-"
                
                html += f"<td>{wasted_display}</td>"  # Wasted Payroll WTD
                html += f"<td>{missed_display}</td>"  # Missed Sales Opportunity WTD
                
                html += "</tr>"
        
        html += "</tbody></table>"
        return html

    def _color_low(self, value, good_thresh, bad_thresh):
        """Lower is better (Green < good < Amber < bad < Red)"""
        # Logic: If < good (Green), If > bad (Red), else Amber
        # Adjust logic to match user expectations. 
        # Typically: < target = Green, > target = Red? 
        # User screenshot: 9.8% Lates is Red. 0.0% is Green. 
        # 3.7% INF is Red. 1.8% INF is Green.
        if value <= good_thresh: return 'bg-green'
        if value >= bad_thresh: return 'bg-red'
        return 'bg-amber'

    def _color_high(self, value, good_thresh, bad_thresh):
        """Higher is better"""
        if value >= good_thresh: return 'bg-green'
        if value <= bad_thresh: return 'bg-red'
        return 'bg-amber'
    
    def calculate_summary(self, regions_data):
        """Calculate network-wide summary statistics."""
        all_stores = []
        for region, managers in regions_data.items():
            for manager, stores in managers.items():
                all_stores.extend(stores)
        
        if not all_stores:
            return {}
        
        # Calculate averages
        inf_values = [s['inf_wtd'] for s in all_stores if s.get('inf_wtd') is not None]
        lates_values = [s['lates_wtd'] for s in all_stores if s.get('lates_wtd') is not None]
        uph_values = [s['uph_wtd'] for s in all_stores if s.get('uph_wtd') is not None and s['uph_wtd'] > 0]
        wasted = [s.get('wasted_payroll', 0) or 0 for s in all_stores]
        missed = [s.get('missed_sales', 0) or 0 for s in all_stores]
        
        return {
            'stores_count': len(all_stores),
            'avg_inf': round(sum(inf_values) / len(inf_values), 2) if inf_values else None,
            'avg_lates': round(sum(lates_values) / len(lates_values), 2) if lates_values else None,
            'avg_uph': round(sum(uph_values) / len(uph_values), 1) if uph_values else None,
            'total_wasted_payroll': sum(wasted),
            'total_missed_sales': sum(missed),
        }
    
    def push_to_dashboard(self, regions_data, dashboard_url=None, report_date=None):
        """Push report data to a GitHub Gist with historical date-keyed storage."""
        import requests
        import json
        
        RETENTION_DAYS = 14  # Keep 14 days of history
        
        # Load config for Gist settings
        gist_id = None
        gist_token = None
        
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
            gist_id = config.get('dashboard_gist_id')
            gist_token = config.get('gist_token')
        except:
            pass
        
        if not gist_id:
            print("Dashboard Gist ID not configured - skipping dashboard push")
            return False
        
        if not gist_token:
            print("Gist token not configured - skipping dashboard push")
            return False
        
        try:
            summary = self.calculate_summary(regions_data)
            date_key = report_date or datetime.now().strftime('%Y-%m-%d')
            
            # Fetch existing Gist data to merge with
            gist_url = f"https://api.github.com/gists/{gist_id}"
            headers = {
                'Authorization': f'token {gist_token}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            existing_data = {
                'metadata': {'available_dates': [], 'retention_days': RETENTION_DAYS},
                'performance': {},
                'inf_items': {}
            }
            
            # Try to fetch existing data
            try:
                get_response = requests.get(gist_url, headers=headers, timeout=15)
                if get_response.status_code == 200:
                    gist_content = get_response.json()
                    if 'dashboard_data.json' in gist_content.get('files', {}):
                        file_content = gist_content['files']['dashboard_data.json'].get('content', '{}')
                        existing_data = json.loads(file_content)
            except:
                pass  # Start fresh if fetch fails
            
            # Ensure structure exists
            if 'metadata' not in existing_data:
                existing_data['metadata'] = {'available_dates': [], 'retention_days': RETENTION_DAYS}
            if 'performance' not in existing_data:
                existing_data['performance'] = {}
            if 'inf_items' not in existing_data:
                existing_data['inf_items'] = {}
            
            # Add today's data
            existing_data['performance'][date_key] = {
                'regions': regions_data,
                'summary': summary,
                'stores_count': summary.get('stores_count', 0)
            }
            
            # Update metadata
            existing_data['metadata']['last_updated'] = datetime.now().isoformat()
            
            # Get all available dates and sort
            all_dates = sorted(existing_data['performance'].keys(), reverse=True)
            
            # Prune old dates (keep only RETENTION_DAYS)
            if len(all_dates) > RETENTION_DAYS:
                dates_to_remove = all_dates[RETENTION_DAYS:]
                for old_date in dates_to_remove:
                    existing_data['performance'].pop(old_date, None)
                    existing_data['inf_items'].pop(old_date, None)
                all_dates = all_dates[:RETENTION_DAYS]
            
            existing_data['metadata']['available_dates'] = all_dates
            
            # Update the Gist
            response = requests.patch(
                gist_url,
                json={
                    'files': {
                        'dashboard_data.json': {
                            'content': json.dumps(existing_data, indent=2)
                        }
                    }
                },
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"✅ Dashboard Gist updated ({len(all_dates)} days of history)")
                return True
            else:
                print(f"⚠️ Dashboard Gist update failed: HTTP {response.status_code}")
                if response.status_code == 404:
                    print("   Hint: Check that dashboard_gist_id is correct")
                elif response.status_code == 401:
                    print("   Hint: Check that gist_token has 'gist' scope")
            
            return False
            
        except Exception as e:
            print(f"⚠️ Dashboard push error: {e}")
            return False

    def save_report(self, report_data, push_dashboard=True, dashboard_url=None):
        html = self.generate_html(report_data)
        filename = f"{self.output_dir}/daily_update_{datetime.now().strftime('%Y%m%d')}.html"
        with open(filename, 'w') as f:
            f.write(html)
        print(f"Report saved to {filename}")
        
        # Push to dashboard if configured
        if push_dashboard:
            self.push_to_dashboard(report_data, dashboard_url)
        
        return filename

if __name__ == "__main__":
    # Test run
    gen = ReportGenerator()
    dummy_data = [{'store': 'Morrisons - Jarrow', 'inf': '1.6%', 'lates': '0.0%', 'uph': '90', 'inf_WTD': '1.5%', 'lates_WTD': '0.1%', 'uph_WTD': '92', 'has_wtd': True},
                  {'store': 'Morrisons - Taunton', 'inf': '2.0%', 'lates': '5.0%', 'uph': '85', 'inf_WTD': '2.1%', 'lates_WTD': '4.0%', 'uph_WTD': '86', 'has_wtd': True}]
    processed = gen.process_data(dummy_data)
    gen.save_report(processed)
