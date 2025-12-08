#!/usr/bin/env python3
"""
Quick test to debug API endpoint patterns
"""
import asyncio
import sys
import logging

# Set up logging to see DEBUG messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s'
)

# Import and run INF analysis on just one store
from inf_scraper import run_inf_analysis

async def main():
    # Use a store that definitely has INF items (from earlier logs)
    target_stores = [
        {
            'store_name': 'Morrisons - Anniesland',
            'store_number': '179',
            'merchant_id': 'amzn1.merchant.d.H2F77QCIJPDU6IYTICWEOZGMYI',
            'marketplace_id': 'AM7DNVYQULIQ5',
        }
    ]
    
    # Configure for yesterday's data
    config_override = {
        'use_date_range': True,
        'date_range_mode': 'yesterday'
    }
    
    print("Testing API capture with Anniesland using YESTERDAY's data...")
    await run_inf_analysis(target_stores=target_stores, config_override=config_override)

if __name__ == "__main__":
    asyncio.run(main())
