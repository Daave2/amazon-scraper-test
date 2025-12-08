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
            
            # Calculate Available vs Confirmed Hours and Available vs Requested
            avc_y, avc_wtd, avr_wtd = self._calculate_avc(entry, store_name, day_of_week)
            
            row = {
                'store': store_name,
                'rate_my_exp': 0.0, # Placeholder
                'inf_y': inf_y,
                'inf_wtd': inf_wtd,
                'lates_y': lates_y,
                'lates_wtd': lates_wtd,
                'uph_y': uph_y,
                'uph_wtd': uph_wtd,
                'avc_y': avc_y,
                'avc_wtd': avc_wtd,
                'avr_wtd': avr_wtd,  # Available vs Requested (Forecasted) Hours
                'wasted_payroll': 0, # Placeholder
                'missed_sales': 0, # Placeholder
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
                
                html += f"<td>-</td>" # Wasted Payroll
                html += f"<td>-</td>" # Missed Sales
                
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

    def save_report(self, report_data):
        html = self.generate_html(report_data)
        filename = f"{self.output_dir}/daily_update_{datetime.now().strftime('%Y%m%d')}.html"
        with open(filename, 'w') as f:
            f.write(html)
        print(f"Report saved to {filename}")
        return filename

if __name__ == "__main__":
    # Test run
    gen = ReportGenerator()
    dummy_data = [{'store': 'Morrisons - Jarrow', 'inf': '1.6%', 'lates': '0.0%', 'uph': '90', 'inf_WTD': '1.5%', 'lates_WTD': '0.1%', 'uph_WTD': '92', 'has_wtd': True},
                  {'store': 'Morrisons - Taunton', 'inf': '2.0%', 'lates': '5.0%', 'uph': '85', 'inf_WTD': '2.1%', 'lates_WTD': '4.0%', 'uph_WTD': '86', 'has_wtd': True}]
    processed = gen.process_data(dummy_data)
    gen.save_report(processed)
