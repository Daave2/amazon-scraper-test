#!/bin/bash
# Populate historical dashboard data for the last 7 days
# Uses conservative settings for background running
# Uses date-aware headcount CSV selection

cd "$(dirname "$0")"

echo "=== Populating Dashboard History ===" | tee -a populate_history.log
echo "Started: $(date)" | tee -a populate_history.log

# Conservative settings: limit to 30 stores per run
LIMIT=30

# Run for each of the last 6 days (excluding today - we already have it)
for DAYS_AGO in 1 2 3 4 5 6; do
    DATE=$(date -v-${DAYS_AGO}d '+%m/%d/%Y')
    DATE_DISPLAY=$(date -v-${DAYS_AGO}d '+%Y-%m-%d')
    
    echo "" | tee -a populate_history.log
    echo "--- Processing $DATE_DISPLAY ($DAYS_AGO days ago) ---" | tee -a populate_history.log
    echo "Started: $(date '+%H:%M:%S')" | tee -a populate_history.log
    echo "Will use headcount CSV for week containing $DATE_DISPLAY" | tee -a populate_history.log
    
    .venv/bin/python scraper.py \
        --start-date "$DATE" \
        --end-date "$DATE" \
        --generate-report \
        --limit $LIMIT 2>&1 | tail -10 | tee -a populate_history.log
    
    echo "Completed: $(date '+%H:%M:%S')" | tee -a populate_history.log
    
    # Wait 30 seconds between runs to avoid rate limiting
    if [ $DAYS_AGO -lt 6 ]; then
        echo "Waiting 30s before next run..." | tee -a populate_history.log
        sleep 30
    fi
done

echo "" | tee -a populate_history.log
echo "=== All Done! ===" | tee -a populate_history.log
echo "Finished: $(date)" | tee -a populate_history.log
echo "Check your dashboard - should have 7 days of history!"
