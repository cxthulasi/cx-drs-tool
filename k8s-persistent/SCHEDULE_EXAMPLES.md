# Schedule Configuration Examples

This document shows how to change the cron schedule **without rebuilding the Docker image**.

## 🎯 Quick Reference

The schedule is controlled by these ConfigMap values:
- `S3_SYNC_SCHEDULE` - Time for S3 sync job (HH:MM format, UTC)
- `MIGRATION_SCHEDULE` - Time for migration job (HH:MM format, UTC)
- `CHECK_INTERVAL` - Seconds between schedule checks (default: 30)

## 📝 Common Schedule Changes

### Example 1: Change Migration to 2:00 AM UTC

**Method 1: Edit configmap.yaml**
```bash
# Edit the file
vim k8s-persistent/configmap.yaml

# Change this line:
# MIGRATION_SCHEDULE: "02:00"

# Apply and restart
kubectl apply -f configmap.yaml
kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

**Method 2: Direct kubectl edit**
```bash
kubectl edit configmap cx-drs-config -n cx-drs
# Change MIGRATION_SCHEDULE: "02:00"
# Save and exit

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

**Method 3: kubectl patch**
```bash
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"MIGRATION_SCHEDULE":"02:00"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

### Example 2: Run Both Jobs at Same Time (3:00 AM UTC)

```bash
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"S3_SYNC_SCHEDULE":"03:00","MIGRATION_SCHEDULE":"03:00"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

### Example 3: Change to Business Hours (9:00 AM and 5:00 PM UTC)

```bash
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"S3_SYNC_SCHEDULE":"09:00","MIGRATION_SCHEDULE":"17:00"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

### Example 4: Reduce Check Interval for More Precise Timing

```bash
# Check every 10 seconds instead of 30
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"CHECK_INTERVAL":"10"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

### Example 5: Increase Check Interval to Save CPU

```bash
# Check every 60 seconds (1 minute)
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"CHECK_INTERVAL":"60"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

## 🌍 Timezone Conversion Examples

All times are in **UTC**. Convert your local time to UTC:

| Your Timezone | Local Time | UTC Time | Config Value |
|---------------|------------|----------|--------------|
| EST (UTC-5) | 8:00 PM | 1:00 AM next day | `01:00` |
| PST (UTC-8) | 5:00 PM | 1:00 AM next day | `01:00` |
| IST (UTC+5:30) | 7:00 AM | 1:30 AM | `01:30` |
| JST (UTC+9) | 10:00 AM | 1:00 AM | `01:00` |
| CET (UTC+1) | 2:00 AM | 1:00 AM | `01:00` |

**Example: Run migration at 8:00 PM EST**
```bash
# 8:00 PM EST = 1:00 AM UTC next day
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"MIGRATION_SCHEDULE":"01:00"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

## ✅ Verify Schedule Changes

### Check ConfigMap Values
```bash
# View all schedule settings
kubectl get configmap cx-drs-config -n cx-drs -o yaml | grep -A 3 "SCHEDULE"

# View specific schedule
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.MIGRATION_SCHEDULE}'
echo ""
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.S3_SYNC_SCHEDULE}'
echo ""
```

### Check Pod Logs for Active Schedule
```bash
# View startup logs showing configured schedule
kubectl logs -n cx-drs -l app=cx-drs-tool | grep "Cron schedule configured" -A 3

# Expected output:
# 📅 Cron schedule configured from environment variables:
#   - S3 Sync:   Daily at 00:30 UTC
#   - Migration: Daily at 01:30 UTC
#   - Check Interval: Every 30 seconds
```

### Watch for Next Scheduled Run
```bash
# Tail the cron log to see when jobs run
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n cx-drs $POD_NAME -- tail -f /app/logs/cron.log
```

## 🔄 Rollback Schedule Changes

If you need to revert to default schedule:

```bash
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"S3_SYNC_SCHEDULE":"00:30","MIGRATION_SCHEDULE":"01:30","CHECK_INTERVAL":"30"}}'

kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

## 📋 Schedule Format Rules

- **Format**: `HH:MM` (24-hour format)
- **Hours**: `00` to `23`
- **Minutes**: `00` to `59`
- **Timezone**: Always UTC
- **Examples**:
  - `00:00` = Midnight UTC
  - `12:00` = Noon UTC
  - `23:59` = 11:59 PM UTC

## ⚠️ Important Notes

1. **Always restart the pod** after changing ConfigMap:
   ```bash
   kubectl rollout restart deployment cx-drs-tool -n cx-drs
   ```

2. **Jobs run once per day** at the specified time

3. **Check interval** determines how often the script checks the time:
   - Lower value (10s) = more precise, more CPU usage
   - Higher value (60s) = less precise, less CPU usage
   - Default (30s) = good balance

4. **Time validation**: Invalid time formats will cause pod to fail startup

5. **Timezone**: All times are UTC - convert your local time accordingly

## 🎯 Best Practices

1. **Test schedule changes** in a dev environment first
2. **Use kubectl patch** for quick one-time changes
3. **Update configmap.yaml** for permanent changes
4. **Monitor logs** after schedule changes to verify timing
5. **Consider timezone** when setting schedules for global teams

## 📞 Troubleshooting

### Pod won't start after schedule change
```bash
# Check pod logs for validation errors
kubectl logs -n cx-drs -l app=cx-drs-tool

# Common error: "Invalid time format"
# Fix: Use HH:MM format (e.g., "01:30" not "1:30")
```

### Jobs not running at expected time
```bash
# Verify ConfigMap values
kubectl get configmap cx-drs-config -n cx-drs -o yaml

# Check pod environment variables
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n cx-drs $POD_NAME -- env | grep SCHEDULE

# Verify pod was restarted after ConfigMap change
kubectl get pods -n cx-drs -o wide
```

