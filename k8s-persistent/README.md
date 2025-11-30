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

# View pod logs
kubectl logs -n cx-drs -l app=cx-drs-tool -f

# Check deployment status
kubectl get deployment -n cx-drs
```

## 📅 Scheduled Jobs

The pod runs two scheduled jobs internally. **Schedules are configurable via ConfigMap** (no image rebuild required).

| Job | Default Schedule | Command | ConfigMap Key |
|-----|------------------|---------|---------------|
| **S3 Sync** | 12:30 AM UTC daily | `python3 drs-tool.py s3-sync` | `S3_SYNC_SCHEDULE` |
| **Migration** | 1:30 AM UTC daily | `python3 drs-tool.py all` | `MIGRATION_SCHEDULE` |

### View Current Schedule

```bash
# View schedule from ConfigMap
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.S3_SYNC_SCHEDULE}'
kubectl get configmap cx-drs-config -n cx-drs -o jsonpath='{.data.MIGRATION_SCHEDULE}'

# View schedule from running pod logs
kubectl logs -n cx-drs -l app=cx-drs-tool | grep "Cron schedule configured"
```

## 🔍 Debugging & Monitoring

### View Live Logs

```bash
# View pod startup logs
kubectl logs -n cx-drs -l app=cx-drs-tool -f

# View cron job logs
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n cx-drs $POD_NAME -- tail -f /app/logs/cron.log
```

### Access Pod Shell

```bash
# Get shell access to the pod
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it -n cx-drs $POD_NAME -- /bin/bash

# Once inside the pod:
cd /app
ls -la logs/
cat logs/cron.log
```

### Manual Execution

```bash
# Trigger migration manually (without waiting for schedule)
POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py all

# Trigger S3 sync manually
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py s3-sync

# Run specific service migration
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py alerts
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

