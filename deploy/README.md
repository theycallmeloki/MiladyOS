# MiladyOS Kubernetes Bootstrap Guide

This guide explains how to bootstrap a fresh MiladyOS Kubernetes cluster from scratch using the provided Helm values files.

## Prerequisites

- Kubernetes cluster running (e.g., Talos, k3s, etc.)
- `kubectl` configured with cluster access
- `helm` CLI installed

## Bootstrap Order

The components must be installed in this specific order due to dependencies:

1. **Longhorn** (Storage provider)
2. **ArgoCD** (GitOps operator)
3. **Monitoring Stack** (via ArgoCD app)

## Step 1: Install Longhorn Storage

Longhorn provides distributed storage for all persistent volumes in the cluster.

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
kubectl -n longhorn-system wait --for=condition=ready pod -l app=longhorn-manager --timeout=600s
```

## Step 2: Install ArgoCD

ArgoCD will manage all other applications via GitOps.

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
kubectl -n argocd wait --for=condition=ready pod -l app.kubernetes.io/name=argocd-server --timeout=600s

# Get ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

## Step 3: Deploy App of Apps

Deploy the main application that manages all other apps:

```bash
kubectl apply -f deploy/argocd-apps/app-of-apps.yaml
```

This will automatically deploy all applications defined in `deploy/argocd-apps/apps/`.

## Step 4: Configure Ingress (Optional)

If you have an ingress controller installed:

```bash
kubectl apply -f deploy/cloudflare-ingress.yaml
```

## Monitoring Stack

The monitoring stack (Prometheus, Grafana, Alertmanager) is deployed automatically via ArgoCD using the values in `deploy/monitoring/kube-prometheus-stack-values.yaml`.

### Access Grafana

Once deployed, Grafana can be accessed at:
- URL: `http://monitoring.miladyos.net` (if ingress is configured)
- No login required (anonymous admin access is enabled)

## Values Files Reference

### `argocd-values.yaml`
- Configures ArgoCD with high availability (2 replicas)
- Sets generous resource limits
- Uses Longhorn as default storage class
- Disables authentication features (can be enabled later)

### `longhorn-values.yaml`
- Sets 3-way replication for high availability
- Configures Longhorn as default storage class
- Allows 200% over-provisioning for flexibility
- Uses worker nodes with `longhorn.io/node=true` label

### `monitoring/kube-prometheus-stack-values.yaml`
- Enables Grafana with anonymous admin access
- Configures 30-day retention for Prometheus
- Uses Longhorn for persistent storage
- Auto-discovers all ServiceMonitors in the cluster

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

## Next Steps

After bootstrap:
1. Configure DNS to point to your ingress controller
2. Set up SSL certificates (cert-manager or Cloudflare)
3. Customize application configurations in their respective folders
4. Add more applications by creating new files in `deploy/argocd-apps/apps/`