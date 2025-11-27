# Quick Start - Persistent Pod Deployment

## 🚀 5-Minute Setup

### Step 1: Build & Push Image

```bash
# From repository root
docker build -f k8s-persistent/Dockerfile -t ramthulsi12/cx-drs-tool:persistent .
docker push ramthulsi12/cx-drs-tool:persistent
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
kubectl get pods -n cx-drs

# View logs
kubectl logs -n cx-drs -l app=cx-drs-tool -f
```

## 📊 Common Commands

```bash
# Get pod name
export POD_NAME=$(kubectl get pods -n cx-drs -l app=cx-drs-tool -o jsonpath='{.items[0].metadata.name}')

# View cron logs
kubectl exec -n cx-drs $POD_NAME -- tail -f /app/logs/cron.log

# Manual migration
kubectl exec -n cx-drs $POD_NAME -- python3 /app/drs-tool.py all

# Access shell
kubectl exec -it -n cx-drs $POD_NAME -- /bin/bash
```

## ⏰ Schedule (Configurable!)

- **S3 Sync**: 12:30 AM UTC daily (default)
- **Migration**: 1:30 AM UTC daily (default)

**Change schedule without rebuilding image:**
```bash
# Edit configmap.yaml and change S3_SYNC_SCHEDULE or MIGRATION_SCHEDULE
kubectl apply -f configmap.yaml
kubectl rollout restart deployment cx-drs-tool -n cx-drs
```

## 🎯 Key Benefits

✅ Pod always running - easy debugging  
✅ Persistent logs - no data loss  
✅ Manual execution - test anytime  
✅ Shell access - full control  

---

For detailed documentation, see [README.md](README.md)

