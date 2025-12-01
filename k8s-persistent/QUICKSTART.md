# Quick Start - Persistent Pod Deployment

## 🚀 5-Minute Setup

### Step 1: Build & Push Image

```bash
# From repository root
docker build -f k8s-persistent/Dockerfile -t your-docker-hub-login/cx-drs-tool:persistent .
docker push your-docker-hub-login/cx-drs-tool:persistent
```

### Step 2: Configure Secrets

Edit `secrets.yaml` and add your API keys:
```yaml
CX_API_KEY_TEAMA: "your-actual-team-a-api-key"
CX_API_KEY_TEAMB: "your-actual-team-b-api-key"
```

### Step 3: Deploy

```bash
cd k8s-persistent
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml
kubectl apply -f deployment.yaml
```

### Step 4: Verify

```bash
# Check pod is running
kubectl get pods -n cx-drs-new

# View all logs (migration output goes to stdout) ⭐
kubectl logs -n cx-drs-new -l app=cx-drs-tool -f
```

## 📊 Common Commands

```bash
# Get pod name
export POD_NAME=$(kubectl get pods -n cx-drs-new -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')

# View all logs (includes tables and JSON summaries) ⭐
kubectl logs -n cx-drs-new $POD_NAME -f

# View last 200 lines
kubectl logs -n cx-drs-new $POD_NAME --tail=200

# Manual migration
kubectl exec -n cx-drs-new $POD_NAME -- python3 /app/drs-tool.py all

# Manual dry-run (redirect output to the main process stdout)

kubectl exec -n cx-drs-new $POD_NAME -- sh -c 'cd /app && python3 -u /app/drs-tool.py all --dry-run 2>&1 | tee /proc/1/fd/1'
kubectl logs -n cx-drs-new $POD_NAME --tail=300

# Access shell
kubectl exec -it -n cx-drs-new $POD_NAME -- /bin/bash
```

## 📊 Coralogix Integration

Logs are automatically sent to Coralogix via otel collector:
- ✅ All logs go to stdout/stderr
- ✅ JSON logs include `log_type` field
- ✅ Search in Coralogix: `log_type:"migration_summary"`

## ⏰ Schedule (Configurable!)

- **S3 Sync**: 01:30 UTC daily (default)
- **Migration**: 00:30 UTC daily (default)
- **Cleanup**: 14:00 UTC daily (deletes files older than 7 days)

**Change schedule without rebuilding image:**
```bash
# Edit configmap.yaml and change S3_SYNC_SCHEDULE, MIGRATION_SCHEDULE, or CLEANUP_SCHEDULE
kubectl apply -f configmap.yaml
kubectl rollout restart deployment cx-drs-tool -n cx-drs-new
```

## 🎯 Key Benefits

✅ Pod always running - easy debugging  
✅ Persistent logs - no data loss  
✅ Manual execution - test anytime  
✅ Shell access - full control  

---

For detailed documentation, see [README.md](README.md)

