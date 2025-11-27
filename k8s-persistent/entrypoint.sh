#!/bin/bash
set -e

echo "=========================================="
echo "Coralogix DRS Tool - Persistent Mode"
echo "=========================================="
echo "Starting at: $(date)"
echo ""

# Read cron schedules from environment variables with defaults
S3_SYNC_SCHEDULE="${S3_SYNC_SCHEDULE:-00:30}"
MIGRATION_SCHEDULE="${MIGRATION_SCHEDULE:-01:30}"
CHECK_INTERVAL="${CHECK_INTERVAL:-30}"

echo "📅 Cron schedule configured from environment variables:"
echo "  - S3 Sync:   Daily at ${S3_SYNC_SCHEDULE} UTC"
echo "  - Migration: Daily at ${MIGRATION_SCHEDULE} UTC"
echo "  - Check Interval: Every ${CHECK_INTERVAL} seconds"
echo ""

# Validate time format (HH:MM)
validate_time() {
    local time=$1
    if [[ ! $time =~ ^[0-2][0-9]:[0-5][0-9]$ ]]; then
        echo "ERROR: Invalid time format '$time'. Expected HH:MM (e.g., 01:30)"
        exit 1
    fi
}

validate_time "$S3_SYNC_SCHEDULE"
validate_time "$MIGRATION_SCHEDULE"

echo "🔄 Starting continuous monitoring mode..."
echo "📝 Logs will be written to: /app/logs/cron.log"
echo ""

# Create log file
touch /app/logs/cron.log

# Function to run scheduled tasks
run_scheduled_tasks() {
    # Track last run dates to avoid duplicate runs
    LAST_S3_RUN=""
    LAST_MIGRATION_RUN=""

    while true; do
        CURRENT_TIME=$(date +"%H:%M")
        CURRENT_DATE=$(date +"%Y-%m-%d")
        CURRENT_DATETIME="${CURRENT_DATE} ${CURRENT_TIME}"

        # Check if it's S3 sync time
        if [ "$CURRENT_TIME" = "$S3_SYNC_SCHEDULE" ]; then
            # Only run if we haven't run today
            if [ "$LAST_S3_RUN" != "$CURRENT_DATE" ]; then
                echo "[$CURRENT_DATETIME] Starting S3 sync job..." | tee -a /app/logs/cron.log
                cd /app && /usr/local/bin/python3 /app/drs-tool.py s3-sync >> /app/logs/cron.log 2>&1
                echo "[$CURRENT_DATETIME] S3 sync job completed" | tee -a /app/logs/cron.log
                LAST_S3_RUN="$CURRENT_DATE"
                # Sleep for 2 minutes to avoid checking again immediately
                sleep 120
            fi
        fi

        # Check if it's Migration time
        if [ "$CURRENT_TIME" = "$MIGRATION_SCHEDULE" ]; then
            # Only run if we haven't run today
            if [ "$LAST_MIGRATION_RUN" != "$CURRENT_DATE" ]; then
                echo "[$CURRENT_DATETIME] Starting migration job..." | tee -a /app/logs/cron.log
                cd /app && /usr/local/bin/python3 /app/drs-tool.py all >> /app/logs/cron.log 2>&1
                echo "[$CURRENT_DATETIME] Migration job completed" | tee -a /app/logs/cron.log
                LAST_MIGRATION_RUN="$CURRENT_DATE"
                # Sleep for 2 minutes to avoid checking again immediately
                sleep 120
            fi
        fi

        # Check at configured interval
        sleep "$CHECK_INTERVAL"
    done
}

# Print initial status
echo "✅ DRS Tool is running in persistent mode"
echo "⏰ Waiting for scheduled times..."
echo ""
echo "To view logs, run:"
echo "  kubectl logs -n cx-drs <pod-name> -f"
echo "  kubectl exec -n cx-drs <pod-name> -- tail -f /app/logs/cron.log"
echo ""
echo "To manually trigger a migration:"
echo "  kubectl exec -n cx-drs <pod-name> -- python3 /app/drs-tool.py all"
echo ""
echo "=========================================="

# Run the scheduler
run_scheduled_tasks

