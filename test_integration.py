#!/usr/bin/env python3
"""Quick test of the integrated API-first scraper with 3 stores."""

import asyncio
import json
import csv
from playwright.async_api import async_playwright
from workers import api_worker_task
from asyncio import Queue

# Load stores
with open('urls.csv', 'r') as f:
    reader = csv.DictReader(f)
    stores = list(reader)[:5]  # Test with 5 stores

print(f"Testing integrated API-first scraper with {len(stores)} stores...")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Load auth
        with open('state.json', 'r') as f:
            storage_state = json.load(f)
        
        # Queues
        job_queue = Queue()
        submission_queue = Queue()
        
        # Add stores to job queue
        for store in stores:
            await job_queue.put(store)
        
        # Tracking
        active_workers = {'value': 0}
        concurrency_limit = {'value': 10}
        concurrency_condition = asyncio.Condition()
        
        def get_date_range():
            return None  # Use defaults
        
        # Simple logger
        import logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        logger = logging.getLogger()
        
        print("\nStarting API worker...")
        start_time = asyncio.get_event_loop().time()
        
        # Run single worker
        await api_worker_task(
            worker_id=1,
            browser=browser,
            storage_template=storage_state,
            job_queue=job_queue,
            submission_queue=submission_queue,
            page_timeout=60000,
            action_timeout=10000,
            active_workers_ref=active_workers,
            concurrency_limit_ref=concurrency_limit,
            concurrency_condition=concurrency_condition,
            get_date_range_func=get_date_range,
            app_logger=logger
        )
        
        elapsed = asyncio.get_event_loop().time() - start_time
        
        print(f"\n" + "=" * 60)
        print(f"RESULTS")
        print("=" * 60)
        print(f"Time: {elapsed:.2f}s for {len(stores)} stores ({elapsed/len(stores):.2f}s per store)")
        print(f"Submissions queued: {submission_queue.qsize()}")
        
        # Show results
        print("\nData collected:")
        while not submission_queue.empty():
            data = await submission_queue.get()
            store = data.get('store', 'Unknown')
            orders = data.get('orders', 'N/A')
            lates = data.get('lates', 'N/A')
            inf = data.get('inf', 'N/A')
            print(f"  {store}: Orders={orders}, Lates={lates}, INF={inf}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
