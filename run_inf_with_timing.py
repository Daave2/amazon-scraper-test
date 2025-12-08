#!/usr/bin/env python3
"""
Simple timing wrapper for INF scraper - adds performance metrics
"""
import time
import sys
import subprocess

def main():
    print("=" * 60)
    print("INF SCRAPER WITH TIMING")
    print("=" * 60)
    
    start_time = time.time()
    
    # Run the actual scraper
    args = sys.argv[1:]  # Pass through all arguments
    cmd = [".venv/bin/python", "inf_scraper.py"] + args
    
    print(f"Running: {' '.join(cmd)}")
    print()
    
    result = subprocess.run(cmd)
    
    # Calculate timing
    total_time = time.time() - start_time
    
    print()
    print("=" * 60)
    print("PERFORMANCE SUMMARY")
    print("=" * 60)
    print(f"Total Runtime: {total_time:.2f}s ({total_time/60:.2f} minutes)")
    print("=" * 60)
    
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
