---
title: "Operations & Troubleshooting"
linkTitle: "Operations"
weight: 80
description: >
  Operational procedures, monitoring, and troubleshooting guides
---

## Operational Overview

This section covers day-to-day operations, monitoring, maintenance, and troubleshooting for MiladyOS deployments.

## Cluster Management

### Health Checks
```bash
# Overall cluster status
kubectl get nodes
kubectl get pods --all-namespaces

# MiladyOS specific services
kubectl get pods -n miladyos
kubectl get services -n miladyos

# Storage status
kubectl get pv,pvc --all-namespaces
```

### Scaling Operations
```bash
# Scale AutoDidact training replicas
kubectl scale deployment autodidact-trainer --replicas=3

# Scale LLM service replicas
kubectl scale deployment mistral-7b --replicas=2

# Horizontal Pod Autoscaling
kubectl autoscale deployment miladyos-api --min=2 --max=10 --cpu-percent=70
```

## Monitoring & Alerting

### Prometheus Metrics

**System Metrics**
- `miladyos_node_status` - Node health and availability
- `miladyos_training_progress` - AutoDidact training progress
- `miladyos_api_requests_total` - API usage statistics
- `miladyos_model_inference_duration` - Model response times

**Custom Alerts**
```yaml
# Example alert rule
- alert: MiladyOSNodeDown
  expr: up{job="miladyos-node"} == 0
  for: 5m
  annotations:
    summary: "MiladyOS node {{ $labels.instance }} is down"
```

### Grafana Dashboards

**Available Dashboards**
- **MiladyOS Overview** - System health and performance
- **AutoDidact Training** - AI training metrics and progress
- **Infrastructure Monitoring** - Kubernetes and storage metrics
- **API Performance** - Request rates and response times

**Access Grafana**
```bash
# Port forward to access locally
kubectl port-forward -n monitoring svc/grafana 3000:80

# Or access via ingress
open http://monitoring.miladyos.net
```

## Backup & Recovery

### Database Backups
```bash
# MongoDB backup (if using)
kubectl exec -it mongodb-0 -- mongodump --out /backup/$(date +%Y%m%d)

# Redis backup
kubectl exec -it redis-0 -- redis-cli BGSAVE
```

### Configuration Backups
```bash
# Backup all MiladyOS configurations
kubectl get configmaps,secrets -n miladyos -o yaml > miladyos-config-backup.yaml

# Backup ArgoCD applications
kubectl get applications -n argocd -o yaml > argocd-apps-backup.yaml
```

### Disaster Recovery
1. **Data Recovery**: Restore from latest backup
2. **Configuration Restore**: Apply saved configurations
3. **Service Restart**: Restart all MiladyOS services
4. **Health Verification**: Verify all systems operational

## Performance Tuning

### Resource Optimization

**CPU Optimization**
```yaml
# Optimize for CPU-intensive workloads
resources:
  requests:
    cpu: 2000m
    memory: 4Gi
  limits:
    cpu: 4000m
    memory: 8Gi
```

**GPU Optimization**
```yaml
# Configure GPU resources
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  accelerator: nvidia-tesla-v100
```

### Storage Performance
```bash
# Monitor storage performance
kubectl top pods --containers -n miladyos

# Check Longhorn volume performance
kubectl -n longhorn-system logs -l app=longhorn-manager
```

## Log Management

### Centralized Logging
```bash
# View application logs
kubectl logs -f deployment/miladyos-api -n miladyos

# View training logs
kubectl logs -f deployment/autodidact-trainer -n miladyos

# View all MiladyOS logs
kubectl logs -f -l app.kubernetes.io/name=miladyos -n miladyos
```

### Log Aggregation
- **ELK Stack**: Elasticsearch, Logstash, Kibana
- **Loki**: Grafana Loki for log aggregation
- **Fluentd**: Log collection and forwarding

## Troubleshooting Guide

### Common Issues

**1. Training Jobs Failing**
```bash
# Check training job status
kubectl describe job autodidact-training-job

# Check resource availability
kubectl describe node <node-name>

# Check GPU availability
kubectl get nodes -l accelerator=nvidia
```

**Solution**: Ensure adequate GPU resources and check training parameters.

**2. API Service Unreachable**
```bash
# Check service status
kubectl get svc miladyos-api -n miladyos

# Check ingress configuration
kubectl get ingress -n miladyos

# Test internal connectivity
kubectl exec -it <pod-name> -- curl http://miladyos-api:8000/health
```

**Solution**: Verify ingress configuration and service endpoints.

**3. Storage Issues**
```bash
# Check PVC status
kubectl get pvc -n miladyos

# Check Longhorn volumes
kubectl -n longhorn-system get volumes

# Check storage class
kubectl get storageclass
```

**Solution**: Verify Longhorn health and storage availability.

**4. Node Discovery Problems**
```bash
# Check Redis connectivity
kubectl exec -it redis-0 -- redis-cli ping

# Check network policies
kubectl get networkpolicies -n miladyos

# Test inter-node communication
kubectl exec -it <pod1> -- ping <pod2>
```

**Solution**: Verify Redis cluster and network connectivity.

### Debug Commands

**System Diagnostics**
```bash
# Complete system overview
kubectl get all -n miladyos

# Resource usage
kubectl top nodes
kubectl top pods -n miladyos

# Events
kubectl get events -n miladyos --sort-by='.lastTimestamp'
```

**Service-Specific Debugging**
```bash
# AutoDidact debugging
kubectl logs -f deployment/autodidact-trainer -n miladyos
kubectl exec -it <autodidact-pod> -- python -c "import torch; print(torch.cuda.is_available())"

# Display control debugging
kubectl port-forward svc/display-control-api 8000:8000
curl http://localhost:8000/api/v1/displays

# Infrastructure debugging
kubectl describe nodes
kubectl get pods -o wide -n miladyos
```

## Maintenance Procedures

### Regular Maintenance

**Weekly Tasks**
- Review monitoring dashboards
- Check backup integrity
- Update documentation
- Review access logs

**Monthly Tasks**
- Security patching
- Performance review
- Capacity planning
- Backup testing

**Quarterly Tasks**
- Major version updates
- Security audit
- Disaster recovery testing
- Architecture review

### Update Procedures

**Rolling Updates**
```bash
# Update MiladyOS image
kubectl set image deployment/miladyos-api miladyos-api=miladyos:v1.1.0

# Monitor rollout
kubectl rollout status deployment/miladyos-api

# Rollback if needed
kubectl rollout undo deployment/miladyos-api
```

**Infrastructure Updates**
```bash
# Update Kubernetes cluster
kubeadm upgrade apply v1.28.0

# Update Helm charts
helm upgrade miladyos ./charts/miladyos

# Update ArgoCD applications
kubectl patch application miladyos -n argocd --type merge \
  -p '{"spec":{"source":{"targetRevision":"v1.1.0"}}}'
```