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

echo "📅 Cron schedule configured from environment variables:"
echo "  - S3 Sync:   Daily at ${S3_SYNC_SCHEDULE} UTC"
echo "  - Migration: Daily at ${MIGRATION_SCHEDULE} UTC"
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

# Convert HH:MM to cron format (MM HH * * *)
S3_HOUR=$(echo $S3_SYNC_SCHEDULE | cut -d: -f1)
S3_MINUTE=$(echo $S3_SYNC_SCHEDULE | cut -d: -f2)
MIGRATION_HOUR=$(echo $MIGRATION_SCHEDULE | cut -d: -f1)
MIGRATION_MINUTE=$(echo $MIGRATION_SCHEDULE | cut -d: -f2)

# Remove leading zeros for cron (08 -> 8)
S3_HOUR=$((10#$S3_HOUR))
S3_MINUTE=$((10#$S3_MINUTE))
MIGRATION_HOUR=$((10#$MIGRATION_HOUR))
MIGRATION_MINUTE=$((10#$MIGRATION_MINUTE))

echo "🔄 Setting up cron jobs..."
echo "📝 Logs will be written to: /app/logs/cron.log"
echo ""

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

# Create log file
touch /app/logs/cron.log
touch /app/logs/drs-s3.log

# Create crontab file for supercronic
cat > /app/crontab << EOF
# Coralogix DRS Tool Scheduled Jobs
# Logs are written to /app/logs/

# S3 Sync - Daily at ${S3_SYNC_SCHEDULE} UTC
${S3_MINUTE} ${S3_HOUR} * * * /usr/local/bin/aws s3 sync /app ${S3_BUCKET_NAME} --exclude ".*" --exclude "*/.*" >> /app/logs/drs-s3.log 2>&1

# Migration - Daily at ${MIGRATION_SCHEDULE} UTC
${MIGRATION_MINUTE} ${MIGRATION_HOUR} * * * cd /app && /usr/local/bin/python3 /app/drs-tool.py all >> /app/logs/cron.log 2>&1

EOF

# Display crontab
echo "✅ Crontab configured:"
cat /app/crontab
echo ""

echo "✅ DRS Tool is running in persistent mode"
echo "⏰ Supercronic will execute jobs at scheduled times"
echo ""
echo "To view logs, run:"
echo "  kubectl logs -n cx-drs <pod-name> -f"
echo "  kubectl exec -n cx-drs <pod-name> -- tail -f /app/logs/cron.log"
echo ""
echo "To view crontab:"
echo "  kubectl exec -n cx-drs <pod-name> -- cat /app/crontab"
echo ""
echo "To manually trigger a migration:"
echo "  kubectl exec -n cx-drs <pod-name> -- python3 /app/drs-tool.py all"
echo ""
echo "=========================================="

# Start supercronic in foreground (works perfectly with non-root users)
exec supercronic /app/crontab