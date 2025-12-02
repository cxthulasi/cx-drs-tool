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
CLEANUP_SCHEDULE="${CLEANUP_SCHEDULE:-14:00}"

echo "📅 Cron schedule configured from environment variables:"
echo "  - S3 Sync:   Daily at ${S3_SYNC_SCHEDULE} UTC"
echo "  - Migration: Daily at ${MIGRATION_SCHEDULE} UTC"
echo "  - Cleanup:   Daily at ${CLEANUP_SCHEDULE} UTC"
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
validate_time "$CLEANUP_SCHEDULE"

# Convert HH:MM to cron format (MM HH * * *)
S3_HOUR=$(echo $S3_SYNC_SCHEDULE | cut -d: -f1)
S3_MINUTE=$(echo $S3_SYNC_SCHEDULE | cut -d: -f2)
MIGRATION_HOUR=$(echo $MIGRATION_SCHEDULE | cut -d: -f1)
MIGRATION_MINUTE=$(echo $MIGRATION_SCHEDULE | cut -d: -f2)
CLEANUP_HOUR=$(echo $CLEANUP_SCHEDULE | cut -d: -f1)
CLEANUP_MINUTE=$(echo $CLEANUP_SCHEDULE | cut -d: -f2)

# Remove leading zeros for cron (08 -> 8)
S3_HOUR=$((10#$S3_HOUR))
S3_MINUTE=$((10#$S3_MINUTE))
MIGRATION_HOUR=$((10#$MIGRATION_HOUR))
MIGRATION_MINUTE=$((10#$MIGRATION_MINUTE))
CLEANUP_HOUR=$((10#$CLEANUP_HOUR))
CLEANUP_MINUTE=$((10#$CLEANUP_MINUTE))

echo "🔄 Setting up cron jobs..."
echo "📝 Logs will be sent to stdout/stderr for otel collector ingestion"
echo ""

# Ensure logs directory exists (for artifact files, not cron logs)
mkdir -p /app/logs

# Configure AWS CLI if credentials are provided
if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "🔐 Configuring AWS CLI with provided credentials..."
    mkdir -p ~/.aws
    cat > ~/.aws/credentials << AWSCREDS
[default]
aws_access_key_id = ${AWS_ACCESS_KEY_ID}
aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}
AWSCREDS

    cat > ~/.aws/config << AWSCONFIG
[default]
region = ${AWS_DEFAULT_REGION:-us-east-1}
AWSCONFIG
    echo "✅ AWS CLI configured"
else
    echo "ℹ️  No AWS credentials provided - assuming IAM role is attached"
fi
echo ""

# Create crontab file for supercronic
# NOTE: Logs go to stdout/stderr so otel collector can pick them up for Coralogix
cat > /app/crontab << EOF
# Coralogix DRS Tool Scheduled Jobs
# Logs are sent to stdout/stderr for otel collector ingestion

# S3 Sync - Daily at ${S3_SYNC_SCHEDULE} UTC
${S3_MINUTE} ${S3_HOUR} * * * /usr/local/bin/aws s3 sync /app ${S3_BUCKET_NAME} --exclude ".*" --exclude "*/.*"

# Migration - Daily at ${MIGRATION_SCHEDULE} UTC
${MIGRATION_MINUTE} ${MIGRATION_HOUR} * * * cd /app && /usr/local/bin/python3 /app/drs-tool.py all

# Cleanup - Daily at ${CLEANUP_SCHEDULE} UTC (delete files older than 7 days)
${CLEANUP_MINUTE} ${CLEANUP_HOUR} * * * /bin/bash -c 'echo "Starting cleanup of files & folders older than 7 days..." && find /app/logs /app/outputs /app/snapshots /app/state /app/src/scripts/dashboards /app/src/scripts/folders -mindepth 1 -mtime +7 -exec rm -rf {} + 2>/dev/null && echo "Cleanup completed"'
EOF

# Display crontab
echo "✅ Crontab configured:"
cat /app/crontab
echo ""

echo "✅ DRS Tool is running in persistent mode"
echo "⏰ Supercronic will execute jobs at scheduled times"
echo ""
echo "📋 Logs are sent to stdout/stderr for Coralogix otel collector ingestion"
echo ""
echo "📋 To view all logs (migration + cron output):"
echo "  kubectl logs -n cx-drs <pod-name> -f"
echo ""
echo "📋 To view logs in Coralogix:"
echo "  - Logs are automatically ingested by otel collector"
echo "  - Search for application: cx-drs-tool"
echo "  - JSON logs include 'log_type' field for filtering"
echo ""
echo "📋 To view crontab:"
echo "  kubectl exec -n cx-drs <pod-name> -- cat /app/crontab"
echo ""
echo "🔧 To manually trigger a migration:"
echo "  kubectl exec -n cx-drs <pod-name> -- python3 /app/drs-tool.py all"
echo ""
echo "🔧 To manually trigger a dry-run:"
echo "  kubectl exec -n cx-drs <pod-name> -- python3 /app/drs-tool.py all --dry-run"
echo ""
echo "=========================================="

# Start supercronic in foreground (works perfectly with non-root users)
exec supercronic /app/crontab