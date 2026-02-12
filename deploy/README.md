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
3. **MetalLB + NGINX Ingress** (LAN-accessible ingress)
4. **App of Apps** (deploys everything else via ArgoCD)
5. **Monitoring Stack** (via ArgoCD app)

## Step 1: Install Longhorn Storage

Longhorn provides distributed storage for all persistent volumes in the cluster.

```bash
# Create namespace with privileged PSA (required for Longhorn's hostPath and privileged containers)
kubectl create namespace longhorn-system
kubectl label namespace longhorn-system \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged

# Add Longhorn Helm repository
helm repo add longhorn https://charts.longhorn.io
helm repo update

# Install Longhorn with custom values
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system \
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

## Step 3: Install MetalLB + NGINX Ingress Controller

For bare-metal/homelab clusters, MetalLB provides LoadBalancer IPs on your LAN and NGINX Ingress Controller routes traffic to services.

### 3a: Install MetalLB

MetalLB assigns real LAN IPs to LoadBalancer services using ARP advertisement.

```bash
# Add MetalLB Helm repository
helm repo add metallb https://metallb.github.io/metallb
helm repo update

# Create namespace with privileged PSA (MetalLB speaker needs host networking)
kubectl create namespace metallb-system
kubectl label namespace metallb-system \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged

# Install MetalLB
helm install metallb metallb/metallb \
  --namespace metallb-system

# Wait for MetalLB to be ready
kubectl -n metallb-system wait --for=condition=ready pod -l app.kubernetes.io/name=metallb --timeout=300s
```

After MetalLB is running, configure an IP address pool and L2 advertisement.
Pick a range on your LAN subnet that is **outside your DHCP range** and not used by any other hosts:

```bash
kubectl apply -f - <<EOF
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: lan-pool
  namespace: metallb-system
spec:
  addresses:
    - 192.168.1.200-192.168.1.210  # Adjust to a free range on your LAN
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: lan-l2
  namespace: metallb-system
spec:
  ipAddressPools:
    - lan-pool
EOF
```

### 3b: Install NGINX Ingress Controller

```bash
# Add ingress-nginx Helm repository
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

# Install NGINX Ingress Controller
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace

# Wait for the controller to be ready
kubectl -n ingress-nginx wait --for=condition=ready pod -l app.kubernetes.io/component=controller --timeout=300s

# Verify it got an external IP from MetalLB
kubectl -n ingress-nginx get svc ingress-nginx-controller
```

The ingress controller should receive an EXTERNAL-IP from your MetalLB pool (e.g. `192.168.1.200`).
You can then access any Ingress resource from your LAN by pointing DNS or `/etc/hosts` entries to that IP.

## Step 4: Port Forwarding / DMZ

For internet-accessible ingress with Let's Encrypt TLS, forward ports 80 and 443 from your ISP-facing router through to the MetalLB NGINX Ingress IP (e.g. `192.168.1.200`).

If you have a double-NAT setup (two routers):
- **Router 1** (ISP-facing): DMZ to Router 2's WAN IP
- **Router 2** (LAN-facing): DMZ to `192.168.1.200` (or port forward 80+443)

cert-manager is deployed as part of the App of Apps and automatically provisions Let's Encrypt certificates using HTTP-01 challenges through the NGINX ingress.

## Step 5: Deploy App of Apps

Deploy the main application that manages all other apps:

```bash
kubectl apply -f deploy/argocd-apps/app-of-apps.yaml
```

This will automatically deploy all applications defined in `deploy/argocd-apps/apps/`.

## Step 6: Post-Deploy PSA Labeling

Several namespaces created by the App of Apps require privileged Pod Security Admission labels.
Without these, daemonsets and privileged pods will fail to schedule.

```bash
# Monitoring namespace (required for node-exporter hostPath and privileged containers)
kubectl label namespace monitoring \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged
```

Any namespace that runs pods with hostPath volumes, host networking, or privileged containers
will need these labels. Common examples: monitoring, GPU operators, storage drivers.

## Monitoring Stack

The monitoring stack (Prometheus, Grafana, Alertmanager) is deployed automatically via ArgoCD using the values in `deploy/monitoring/kube-prometheus-stack-values.yaml`.

### Access Grafana

Grafana is available via ingress at `grafana.transparentlyrotatableproxy.me`.
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
- Schedules on all worker nodes automatically (control-plane nodes excluded via taints)

### `monitoring/kube-prometheus-stack-values.yaml`
- Enables Grafana with anonymous admin access
- Configures 365-day retention for Prometheus (150Gi storage)
- Uses Longhorn for persistent storage
- Auto-discovers all ServiceMonitors in the cluster
- Disables etcd/controller-manager/scheduler/kube-proxy metrics (Talos-specific)

## Talos Prerequisites

Talos worker nodes must have the following system extensions installed for Longhorn storage:
- `iscsi-tools` — required for Longhorn volume attachment
- `util-linux-tools` — required for block device operations

These can be added via the Talos machine config or Image Factory schematic.

## Troubleshooting

### Pod Security Admission (PSA)

If daemonset pods show 0/N ready or pods fail with `violates PodSecurity "baseline:latest"`,
the namespace needs privileged PSA labels:
```bash
kubectl label namespace <namespace> \
  pod-security.kubernetes.io/enforce=privileged \
  pod-security.kubernetes.io/audit=privileged \
  pod-security.kubernetes.io/warn=privileged
```

### MetalLB Speakers Not Joining

MetalLB speakers use memberlist (port 7946) for leader election. If speakers show
`connection refused` errors on startup, restart the daemonset — this is a race condition
during initial deployment:
```bash
kubectl -n metallb-system rollout restart daemonset metallb-speaker
```

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

## TLS Certificates

cert-manager is deployed via ArgoCD and uses Let's Encrypt HTTP-01 challenges.

- **Staging issuer** (`letsencrypt-staging`): Active by default. Issues fake certs for testing — browsers will show warnings but the ACME flow is validated.
- **Production issuer** (`letsencrypt-prod`): Uncomment in `deploy/cert-manager/cluster-issuer.yaml` and update ingress annotations once staging is confirmed working.

All ingress resources use the `cert-manager.io/cluster-issuer` annotation to auto-provision TLS certificates.

### Domains

All domains have `@` and `*` A records pointing to the static ISP IP:
- basedjourney.com
- generalpurposetransformer.com
- matrixmilady.com
- milady.api
- miladyos.com
- miladyos.net
- radbrocorp.com
- theycallmeloki.site
- tiniercorp.com
- transparentlyrotatableproxy.me

Service subdomains use `transparentlyrotatableproxy.me`:
- `argocd.transparentlyrotatableproxy.me` — ArgoCD
- `grafana.transparentlyrotatableproxy.me` — Grafana
- `ha.transparentlyrotatableproxy.me` — Home Assistant
- `litellm.transparentlyrotatableproxy.me` — LiteLLM Proxy
- `pachd.transparentlyrotatableproxy.me` — Pachyderm

## Next Steps

After bootstrap:
1. Verify staging certs are issued: `kubectl get certificates -A`
2. Switch to production Let's Encrypt once confirmed
3. Customize application configurations in their respective folders
4. Add more applications by creating new files in `deploy/argocd-apps/apps/`