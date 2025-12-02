# Coralogix DRS Tool - Persistent Pod Deployment

This deployment strategy runs a **persistent pod** that stays running continuously with internal cron scheduling. This makes debugging and log monitoring much easier compared to Kubernetes CronJobs.

## 📋 Overview

**Key Differences from k8s/ folder:**
- ✅ Pod runs **continuously** (always available for debugging)
- ✅ **Easy log access** - logs persist in the running pod
- ✅ **Manual execution** - can trigger migrations anytime via `kubectl exec`
- ✅ Internal cron scheduling within the pod
- ✅ Better for development and troubleshooting

## 🚀 Quick Start

### 1. Build Docker Image

From the repository root:

```bash
docker build -f k8s-persistent/Dockerfile -t your-docker-hub-login/cx-drs-tool:persistent .
docker push your-docker-hub-login/cx-drs-tool:persistent
```

### 2. Configure Secrets and ConfigMap

Edit the following files with your actual values:

**`secrets.yaml`** - Add your API keys:
```yaml
CX_API_KEY_TEAMA: "your-actual-team-a-api-key"
CX_API_KEY_TEAMB: "your-actual-team-b-api-key"
```

**`configmap.yaml`** - Verify your region settings (already configured for AP1)

### 3. Deploy to Kubernetes

```bash
cd k8s-persistent

# Create namespace
kubectl apply -f namespace.yaml

# Create ConfigMap and Secrets
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml

# Deploy the persistent pod
kubectl apply -f deployment.yaml
```

### 4. Verify Deployment

```bash
# Check if pod is running
kubectl get pods -n cx-drs

# View pod startup logs
kubectl logs -n cx-drs -l app=cx-drs-tool -f

# Check deployment status
kubectl get deployment -n cx-drs
```

## 📅 Scheduled Jobs

The pod runs three scheduled jobs internally. **Schedules are configurable via ConfigMap** (no image rebuild required).

| Job | Default Schedule | Command | ConfigMap Key |
|-----|------------------|---------|---------------|
| **S3 Sync** | 01:30 UTC daily | `aws s3 sync /app ${S3_BUCKET_NAME}` | `S3_SYNC_SCHEDULE` |
| **Migration** | 00:30 UTC daily | `python3 drs-tool.py all` | `MIGRATION_SCHEDULE` |
| **Cleanup** | 14:00 UTC daily | Delete files older than 7 days | `CLEANUP_SCHEDULE` |

### Cleanup Job Details

The cleanup job runs daily at 2:00 PM UTC (configurable) and deletes files older than 7 days from:
- `/app/logs` - Log files
- `/app/outputs` - Output files
- `/app/snapshots` - Snapshot files
- `/app/state` - State files
- `/app/src/scripts/dashboards` - Downloaded dashboard files
- `/app/src/scripts/folders` - Downloaded folder files

This prevents disk space issues from accumulating old files.

### View Current Schedule

```bash
# View schedule from ConfigMap
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.S3_SYNC_SCHEDULE}'
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.MIGRATION_SCHEDULE}'
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.CLEANUP_SCHEDULE}'

# View schedule from running pod logs
kubectl logs -n cx-drs -l app=cx-drs-tool | grep "Cron schedule configured"
```

## 🔍 Debugging & Monitoring

### View Live Logs

**IMPORTANT:** All logs (migration output, tables, JSON summaries) are sent to **pod stdout/stderr** for Coralogix otel collector ingestion.

```bash
# View all logs (migration + cron output) ⭐ THIS IS WHAT YOU WANT
kubectl logs -n cx-drs -l app=cx-drs-tool -f

# View logs from specific pod
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n cx-drs $POD_NAME -f

# View last 200 lines (includes full migration summary)
kubectl logs -n cx-drs $POD_NAME --tail=200
```

### View Logs in Coralogix

The migration logs are automatically ingested by the Coralogix otel collector:

- ✅ **Application Name**: `cx-drs-tool` (or as configured in your otel collector)
- ✅ **JSON Logs**: All structured logs include `log_type` field for filtering
- ✅ **Migration Summary**: Search for `log_type: "migration_summary"`
- ✅ **Service Details**: Search for `log_type: "service_detail"`

**Coralogix Query Examples:**
```
# View all migration summaries
log_type:"migration_summary"

# View specific service details
log_type:"service_detail" AND service:"parsing-rules"

# View failed migrations
log_type:"migration_summary" AND failed_services:>0
```

### View Migration Summary Tables

The migration summary includes:
- ✅ **Print statements** - Tables and summaries (visible in kubectl logs)
- ✅ **JSON logs** - Structured logs with `log_type` field (ingested by Coralogix)

```bash
# View recent logs with tables
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n cx-drs $POD_NAME --tail=200

# Filter only JSON logs (for parsing with jq)
kubectl logs -n cx-drs $POD_NAME | grep '{"log_type"' | tail -10 | jq .
```

### Access Pod Shell

```bash
# Get shell access to the pod
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it -n cx-drs $POD_NAME -- /bin/bash

# Once inside the pod:
cd /app
ls -la logs/
tail -100 logs/cron.log  # View last 100 lines of migration logs
```

### Manual Execution

```bash
# Trigger migration manually (without waiting for schedule)
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py all

# Trigger dry-run migration
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py all --dry-run

# Run specific service migration
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py parsing-rules
```

### Check Pod Status

```bash
# Get detailed pod information
kubectl describe pod -n cx-drs -l app=cx-drs-tool

# Check resource usage
kubectl top pod -n cx-drs -l app=cx-drs-tool

# View events
kubectl get events -n cx-drs --sort-by='.lastTimestamp'
```

## 📂 File Structure

```
k8s-persistent/
├── Dockerfile           # Multi-stage build with cron support
├── entrypoint.sh        # Startup script with internal scheduler
├── namespace.yaml       # Kubernetes namespace
├── secrets.yaml         # API keys (edit with your values)
├── configmap.yaml       # Configuration (URLs, settings)
├── deployment.yaml      # Persistent pod deployment
└── README.md           # This file
```

## 🔄 Updating the Deployment

### Update Configuration

```bash
# Edit ConfigMap
kubectl edit configmap cx-drs-config -n cx-drs

# Edit Secrets
kubectl edit secret cx-drs-secrets -n cx-drs

# Restart pod to apply changes
kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

### Update Docker Image

```bash
# Rebuild and push new image
docker build -f k8s-persistent/Dockerfile -t your-docker-hub-login/cx-drs-tool:persistent .
docker push your-docker-hub-login/cx-drs-tool:persistent

# Force pod to pull new image
kubectl rollout restart deployment cx-drs-tool -n cx-drs

# Watch rollout status
kubectl rollout status deployment cx-drs-tool -n cx-drs
```

## 🗑️ Cleanup

```bash
# Delete deployment (keeps namespace, configmap, secrets)
kubectl delete deployment cx-drs-tool -n cx-drs

# Delete everything
kubectl delete namespace cx-drs
```

## ⚙️ Customization

### Change Schedule Times (No Rebuild Required!)

You can change the schedule times **without rebuilding the Docker image**. Just edit the ConfigMap:

**Option 1: Edit ConfigMap file and reapply**
```bash
# Edit configmap.yaml
vim k8s-persistent/configmap.yaml

# Change the schedule values:
# S3_SYNC_SCHEDULE: "02:00"      # Change to 2:00 AM UTC
# MIGRATION_SCHEDULE: "03:30"    # Change to 3:30 AM UTC

# Apply changes
kubectl apply -f configmap.yaml

# Restart pod to pick up new schedule
kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

**Option 2: Edit ConfigMap directly in Kubernetes**
```bash
# Edit ConfigMap directly
kubectl edit configmap cx-drs-config -n cx-drs

# Change these values:
#   S3_SYNC_SCHEDULE: "02:00"      # HH:MM format (UTC)
#   MIGRATION_SCHEDULE: "03:30"    # HH:MM format (UTC)
#   CHECK_INTERVAL: "60"           # Check every 60 seconds

# Restart pod to apply changes
kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

**Option 3: Use kubectl patch**
```bash
# Change migration schedule to 2:30 AM UTC
kubectl patch configmap cx-drs-config -n cx-drs \
  --type merge \
  -p '{"data":{"MIGRATION_SCHEDULE":"02:30"}}'

# Restart pod
kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

**Schedule Format:**
- Use **HH:MM** format (24-hour)
- Times are in **UTC timezone**
- Examples: `00:30` (12:30 AM), `13:45` (1:45 PM), `23:00` (11:00 PM)

**Check Interval:**
- Default: `30` seconds
- Increase for less frequent checks (saves CPU)
- Decrease for more precise timing (uses more CPU)

### Add More Scheduled Jobs

To add more scheduled jobs, you need to edit `entrypoint.sh` and rebuild the image:

1. Edit `entrypoint.sh` and add more time checks in the `run_scheduled_tasks()` function
2. Add corresponding environment variables to `configmap.yaml`
3. Rebuild and push the Docker image

## 🆚 Comparison: Persistent vs CronJob

| Feature | Persistent Pod (this folder) | CronJob (k8s/ folder) |
|---------|------------------------------|----------------------|
| Pod Lifecycle | Always running | Created on schedule |
| Debugging | ✅ Easy - pod always available | ❌ Harder - pod disappears |
| Log Access | ✅ Persistent logs in pod | ❌ Need to catch pod before cleanup |
| Manual Execution | ✅ Simple `kubectl exec` | ⚠️ Need to create manual job |
| Resource Usage | ⚠️ Constant (even when idle) | ✅ Only when running |
| Best For | Development, debugging | Production, cost optimization |

## 🎯 Recommendations

- **Use this (persistent) for**: Development, testing, troubleshooting, when you need easy access to logs
- **Use k8s/ (CronJob) for**: Production environments where cost optimization matters

## 📞 Support

For issues or questions:
1. Check pod logs: `kubectl logs -n cx-drs -l app=cx-drs-tool`
2. Check pod status: `kubectl describe pod -n cx-drs -l app=cx-drs-tool`
3. Access pod shell: `kubectl exec -it -n cx-drs <pod-name> -- /bin/bash`

