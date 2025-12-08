import json
import os
from datetime import datetime
import csv

class ReportGenerator:
    def __init__(self, managers_file='managers.json', output_dir='output'):
        self.managers_file = managers_file
        self.output_dir = output_dir
        self.load_managers()
        
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

    def process_data(self, store_data_list):
        """Aggregate and enrich data for the report."""
        regions = {'North': {}, 'South': {}, 'Unknown': {}}
        
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
            
            row = {
                'store': store_name,
                'rate_my_exp': 0.0, # Placeholder
                'inf_y': inf_y,
                'inf_wtd': inf_wtd,
                'lates_y': lates_y,
                'lates_wtd': lates_wtd,
                'uph_y': uph_y,
                'uph_wtd': uph_wtd,
                'avc_y': 0.0, # Placeholder
                'avc_wtd': 0.0, # Placeholder
                'avr_wtd': 0.0, # Placeholder (Available vs Requested)
                'wasted_payroll': 0, # Placeholder
                'missed_sales': 0, # Placeholder
            }
            regions[region][manager].append(row)
            
        return regions

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
                
                html += f"<td class='{self._color_high(row['avc_y'], 95, 90)}'>-</td>"
                html += f"<td class='{self._color_high(row['avc_wtd'], 95, 90)}'>-</td>"
                html += f"<td class='{self._color_high(row['avr_wtd'], 95, 90)}'>-</td>"
                
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
