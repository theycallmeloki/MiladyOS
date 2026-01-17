---
title: "Infrastructure & Deployment"
linkTitle: "Infrastructure"
weight: 40
description: >
  Kubernetes deployment, monitoring, and infrastructure management
---

## Overview

MiladyOS runs on enterprise-grade Kubernetes infrastructure with GitOps deployment, distributed storage, and comprehensive monitoring.

## Prerequisites

- Kubernetes cluster (Talos, k3s, etc.)
- `kubectl` configured with cluster access
- `helm` CLI installed

## Bootstrap Order

Components must be installed in this specific order:

1. **Longhorn** (Storage provider)
2. **ArgoCD** (GitOps operator)
3. **Monitoring Stack** (via ArgoCD app)

## Step 1: Install Longhorn Storage

```bash
# Add Longhorn Helm repository
helm repo add longhorn https://charts.longhorn.io
helm repo update

# Install Longhorn with custom values
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --values deploy/longhorn-values.yaml

# Wait for Longhorn to be ready
kubectl -n longhorn-system wait --for=condition=ready pod \
  -l app=longhorn-manager --timeout=600s
```

## Step 2: Install ArgoCD

```bash
# Add ArgoCD Helm repository
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Install ArgoCD with custom values
helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --values deploy/argocd-values.yaml

# Wait for ArgoCD to be ready
kubectl -n argocd wait --for=condition=ready pod \
  -l app.kubernetes.io/name=argocd-server --timeout=600s

# Get ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

## Step 3: Deploy Applications

Deploy the App of Apps pattern:

```bash
kubectl apply -f deploy/argocd-apps/app-of-apps.yaml
```

This automatically deploys all applications defined in `deploy/argocd-apps/apps/`.

## Monitoring Stack

### Components
- **Prometheus** - Metrics collection and alerting
- **Grafana** - Visualization and dashboards
- **Alertmanager** - Alert routing and notification

### Access Grafana
- URL: `http://monitoring.miladyos.net` (with ingress)
- Anonymous admin access enabled by default

### Specialized Monitoring
- **SNMP Monitoring** - Network device monitoring
- **UPS Monitoring** - Power management
- **Tuya Monitoring** - Smart device integration
- **Wiz Monitoring** - Lighting system monitoring

## Service Deployments

### LLM Services
- **Mistral-7B** - General purpose language model
- **QWQ-32B-AWQ** - Quantized large model
- **Deep-Coder-14B-AWQ** - Code generation model

### Infrastructure Services
- **NFT-Auth** - Blockchain-based authentication
- **LiteLLM-Proxy** - Model API gateway
- **Gatus** - Service health monitoring
- **Gotty-Dev** - Web-based terminal access

## Storage Configuration

### Longhorn Settings
- **3-way replication** for high availability
- **200% over-provisioning** for flexibility
- **Default storage class** for automatic provisioning
- **Worker node targeting** with `longhorn.io/node=true` label

## Ingress & Networking

### Cloudflare Integration
```bash
kubectl apply -f deploy/cloudflare-ingress.yaml
```

### SSL Certificates
- Automatic certificate provisioning via cert-manager
- Cloudflare DNS challenge support

## Troubleshooting

### Check Longhorn Status
```bash
kubectl -n longhorn-system get pods
kubectl -n longhorn-system get nodes.longhorn.io
```

### Check ArgoCD Applications
```bash
kubectl -n argocd get applications
```

### View ArgoCD Logs
```bash
kubectl -n argocd logs -l app.kubernetes.io/name=argocd-server
kubectl -n argocd logs -l app.kubernetes.io/name=argocd-application-controller
```