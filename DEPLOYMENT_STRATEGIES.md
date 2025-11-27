# Kubernetes Deployment Strategies Comparison

This repository provides **two different Kubernetes deployment strategies** for the Coralogix DRS Tool. Choose the one that best fits your needs.

## 📁 Two Deployment Options

### 1. **k8s/** - Kubernetes CronJobs (Production-Optimized)
- Pods created only when scheduled
- Automatic cleanup after completion
- Resource-efficient (no idle pods)
- Best for production environments

### 2. **k8s-persistent/** - Persistent Pod (Debug-Friendly)
- Pod runs continuously
- Easy log access and debugging
- Manual execution anytime
- Best for development/testing

---

## 🆚 Detailed Comparison

| Feature | k8s/ (CronJob) | k8s-persistent/ (Persistent) |
|---------|----------------|------------------------------|
| **Pod Lifecycle** | Created on schedule, terminated after completion | Always running |
| **Resource Usage** | ✅ Efficient - only uses resources when running | ⚠️ Constant - uses resources even when idle |
| **Debugging** | ❌ Difficult - pod disappears after job completes | ✅ Easy - pod always available |
| **Log Access** | ❌ Must catch logs before pod cleanup | ✅ Persistent - logs always accessible |
| **Manual Execution** | ⚠️ Requires creating manual Job from CronJob | ✅ Simple `kubectl exec` command |
| **Shell Access** | ❌ Only during job execution | ✅ Always available |
| **Cost** | ✅ Lower - pay only when running | ⚠️ Higher - pay for continuous running |
| **Complexity** | ⚠️ More K8s concepts (CronJob, Job, Pod) | ✅ Simple Deployment |
| **Production Ready** | ✅ Yes - standard K8s pattern | ✅ Yes - but less cost-effective |
| **Monitoring** | ⚠️ Need to monitor CronJob history | ✅ Simple pod monitoring |
| **Troubleshooting** | ❌ Hard - need to wait for next run | ✅ Easy - test immediately |

---

## 🎯 When to Use Each Strategy

### Use **k8s/** (CronJob) When:

✅ **Production environment** - cost optimization matters  
✅ **Stable workload** - migrations run reliably  
✅ **Scheduled only** - no need for manual execution  
✅ **Resource constraints** - want to minimize idle resource usage  
✅ **Standard K8s patterns** - following best practices  

**Example Use Cases:**
- Production disaster recovery automation
- Cost-sensitive environments
- Well-tested, stable migrations
- Compliance with K8s best practices

### Use **k8s-persistent/** (Persistent Pod) When:

✅ **Development/Testing** - need frequent debugging  
✅ **Troubleshooting** - investigating migration issues  
✅ **Manual execution** - need to run migrations on-demand  
✅ **Log analysis** - need persistent access to logs  
✅ **Learning/Training** - easier to understand and debug  

**Example Use Cases:**
- Initial setup and testing
- Debugging migration failures
- Customer demos and training
- Development environments
- Proof of concept deployments

---

## 📊 Resource Comparison

### k8s/ (CronJob)
```
Idle State:     0 pods running = 0 resources used
Running State:  1 pod running  = 512Mi-2Gi RAM, 500m-2000m CPU
Daily Usage:    ~2-4 hours (depending on migration duration)
```

### k8s-persistent/ (Persistent Pod)
```
Idle State:     1 pod running  = 512Mi-2Gi RAM, 250m-1000m CPU
Running State:  1 pod running  = 512Mi-2Gi RAM, 250m-1000m CPU
Daily Usage:    24 hours continuous
```

**Cost Impact:** Persistent pod uses ~6-12x more resources over 24 hours.

---

## 🚀 Quick Start Commands

### For k8s/ (CronJob)

```bash
# Build and deploy
docker build -f k8s/Dockerfile -t ramthulsi12/cx-drs-tool:latest .
docker push ramthulsi12/cx-drs-tool:latest

cd k8s
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml
kubectl apply -f drs-tool.yaml

# Monitor
kubectl get cronjobs -n cx-drs
kubectl get jobs -n cx-drs
```

### For k8s-persistent/ (Persistent Pod)

```bash
# Build and deploy
docker build -f k8s-persistent/Dockerfile -t ramthulsi12/cx-drs-tool:persistent .
docker push ramthulsi12/cx-drs-tool:persistent

cd k8s-persistent
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml
kubectl apply -f deployment.yaml

# Monitor
kubectl get pods -n cx-drs
kubectl logs -n cx-drs -l app=cx-drs-tool -f
```

---

## 🔄 Migration Between Strategies

You can easily switch between strategies:

### From CronJob to Persistent:
```bash
# Delete CronJobs
kubectl delete cronjob cx-drs-migration cx-drs-s3-sync -n cx-drs

# Deploy persistent pod
cd k8s-persistent
kubectl apply -f deployment.yaml
```

### From Persistent to CronJob:
```bash
# Delete Deployment
kubectl delete deployment cx-drs-tool -n cx-drs

# Deploy CronJobs
cd k8s
kubectl apply -f drs-tool.yaml
```

**Note:** ConfigMap, Secrets, and Namespace are compatible between both strategies.

---

## 💡 Recommendations

### For Customer Deployments:

1. **Start with k8s-persistent/** during:
   - Initial setup and configuration
   - Testing and validation
   - Training and knowledge transfer

2. **Switch to k8s/** for:
   - Production deployment
   - Long-term operation
   - Cost optimization

### Hybrid Approach:

You can also use both:
- **k8s/** for production scheduled migrations
- **k8s-persistent/** in a separate namespace for testing/debugging

```bash
# Production namespace with CronJobs
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/drs-tool.yaml

# Dev namespace with persistent pod
kubectl create namespace cx-drs-dev
kubectl apply -f k8s-persistent/deployment.yaml -n cx-drs-dev
```

---

## 📚 Documentation

- **k8s/**: See [k8s/README.md](k8s/README.md) and [k8s/QUICKSTART.md](k8s/QUICKSTART.md)
- **k8s-persistent/**: See [k8s-persistent/README.md](k8s-persistent/README.md) and [k8s-persistent/QUICKSTART.md](k8s-persistent/QUICKSTART.md)

---

## 🎓 Summary

| Scenario | Recommended Strategy |
|----------|---------------------|
| Production deployment | **k8s/** (CronJob) |
| Development/Testing | **k8s-persistent/** (Persistent) |
| Initial setup | **k8s-persistent/** (Persistent) |
| Cost optimization | **k8s/** (CronJob) |
| Debugging issues | **k8s-persistent/** (Persistent) |
| Customer demo | **k8s-persistent/** (Persistent) |
| Long-term operation | **k8s/** (CronJob) |

**Best Practice:** Start with `k8s-persistent/` for setup and testing, then switch to `k8s/` for production.

