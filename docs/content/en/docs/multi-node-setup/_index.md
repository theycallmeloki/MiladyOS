---
title: "Multi-Node Cluster Setup"
linkTitle: "Multi-Node Setup"
weight: 35
description: >
  Deploy MiladyOS across multiple nodes with Talos Linux and Jenkins-driven automation
---

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    DISTRIBUTED CONSCIOUSNESS DEPLOYMENT                     │
│                                                                             │
│    ┌─────────┐      ┌─────────┐      ┌─────────┐      ┌─────────┐         │
│    │ Control │      │  GPU    │      │  GPU    │      │ Storage │         │
│    │  Plane  │◄────►│ Node 1  │◄────►│ Node 2  │◄────►│  Node   │         │
│    │         │      │ (vLLM)  │      │ (Train) │      │(Longhorn)│        │
│    └─────────┘      └─────────┘      └─────────┘      └─────────┘         │
│         │                │                │                │               │
│         └────────────────┴────────────────┴────────────────┘               │
│                              Nebula Mesh                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Overview

This guide covers deploying MiladyOS across multiple physical or virtual machines using:

- **Talos Linux** - Immutable, API-driven Kubernetes OS
- **Jenkins** - Orchestrate cluster lifecycle via pipelines
- **Nebula** - Overlay network connecting all nodes
- **Longhorn** - Distributed storage across nodes
- **ArgoCD** - GitOps deployment of workloads

---

## Architecture

### Node Roles

| Role | Purpose | Recommended Specs |
|------|---------|-------------------|
| **Control Plane** | K8s API, etcd, scheduler | 4 CPU, 8GB RAM, 100GB SSD |
| **GPU Worker** | LLM inference, training | 8+ CPU, 32GB+ RAM, GPU (16GB+ VRAM) |
| **Storage Worker** | Longhorn replicas | 4 CPU, 16GB RAM, 500GB+ NVMe |
| **General Worker** | Jenkins, monitoring, services | 4 CPU, 16GB RAM, 200GB SSD |

### Network Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Network Layout                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Public Internet                                                           │
│        │                                                                    │
│        ▼                                                                    │
│   ┌─────────────┐                                                          │
│   │  Lighthouse │  Nebula VPN Entry Point                                  │
│   │ 192.168.5.1 │  (Can be cloud VM or on-prem)                           │
│   └──────┬──────┘                                                          │
│          │                                                                  │
│   ┌──────┴──────────────────────────────────────────────────────────┐      │
│   │                    Nebula Overlay (192.168.5.0/24)               │      │
│   │                                                                  │      │
│   │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐    │      │
│   │  │  talos-   │  │  talos-   │  │  talos-   │  │  talos-   │    │      │
│   │  │  cp-001   │  │  gpu-001  │  │  gpu-002  │  │  store-01 │    │      │
│   │  │  .5.10    │  │  .5.20    │  │  .5.21    │  │  .5.30    │    │      │
│   │  │           │  │           │  │           │  │           │    │      │
│   │  │ [Control] │  │[RTX 4090] │  │[RTX 3090] │  │ [NVMe x4] │    │      │
│   │  └───────────┘  └───────────┘  └───────────┘  └───────────┘    │      │
│   │                                                                  │      │
│   └──────────────────────────────────────────────────────────────────┘      │
│                                                                             │
│   K8s Service Network: 10.96.0.0/12                                        │
│   K8s Pod Network: 10.244.0.0/16                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### On Your MiladyOS Control Machine

MiladyOS includes `talosctl` pre-installed:

```bash
# Verify talosctl is available
docker exec miladyos talosctl version --client

# Or if running locally
talosctl version --client
```

### Hardware Preparation

1. **Boot media** - USB drives with Talos ISO or PXE boot setup
2. **Network** - All nodes on same L2 network (or Nebula overlay)
3. **IPMI/BMC** - Recommended for remote management
4. **GPU nodes** - NVIDIA drivers will be installed via GPU Operator

---

## Step 1: Generate Talos Configuration

### Create Cluster Secrets

```bash
# Generate secrets (do this once, save securely!)
talosctl gen secrets -o secrets.yaml

# Generate configs for your cluster
talosctl gen config miladyos-cluster https://<control-plane-ip>:6443 \
  --with-secrets secrets.yaml \
  --output-dir _out

# This creates:
# _out/controlplane.yaml  - Control plane node config
# _out/worker.yaml        - Worker node config
# _out/talosconfig        - Client config
```

### Customize Node Configurations

**Control Plane** (`controlplane.yaml`):
```yaml
machine:
  type: controlplane
  certSANs:
    - 192.168.5.10
    - talos-cp-001
  network:
    hostname: talos-cp-001
    interfaces:
      - interface: eth0
        dhcp: false
        addresses:
          - 192.168.5.10/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.5.1
  install:
    disk: /dev/sda
    image: ghcr.io/siderolabs/installer:v1.6.0
    bootloader: true
    wipe: true

cluster:
  network:
    cni:
      name: flannel
  proxy:
    disabled: false
  controllerManager: {}
  scheduler: {}
```

**GPU Worker** (`worker-gpu.yaml`):
```yaml
machine:
  type: worker
  network:
    hostname: talos-gpu-001
    interfaces:
      - interface: eth0
        dhcp: false
        addresses:
          - 192.168.5.20/24
        routes:
          - network: 0.0.0.0/0
            gateway: 192.168.5.1
  install:
    disk: /dev/nvme0n1
    image: ghcr.io/siderolabs/installer:v1.6.0
    extensions:
      - image: ghcr.io/siderolabs/nvidia-container-toolkit:v1.14.3-v1.6.0
    bootloader: true
    wipe: true
  kernel:
    modules:
      - name: nvidia
      - name: nvidia_uvm
      - name: nvidia_drm
      - name: nvidia_modeset
  sysctls:
    net.core.rmem_max: "2500000"
    vm.nr_hugepages: "1024"
  nodeLabels:
    node.kubernetes.io/gpu: "true"
    nvidia.com/gpu.present: "true"
```

---

## Step 2: Bootstrap the Cluster via Jenkins

Create a Jenkins pipeline to automate cluster operations.

### Pipeline: Cluster Bootstrap

```groovy
// templates/talos-cluster-bootstrap.Jenkinsfile
// Description: Bootstrap a new Talos Kubernetes cluster

pipeline {
    agent any

    parameters {
        string(name: 'CONTROL_PLANE_IP', defaultValue: '192.168.5.10', description: 'Control plane IP')
        string(name: 'CLUSTER_NAME', defaultValue: 'miladyos-cluster', description: 'Cluster name')
        booleanParam(name: 'WIPE_EXISTING', defaultValue: false, description: 'Wipe existing cluster')
    }

    environment {
        TALOSCONFIG = "${WORKSPACE}/_out/talosconfig"
    }

    stages {
        stage('Validate Configs') {
            steps {
                sh '''
                    talosctl validate -m metal -c _out/controlplane.yaml
                    talosctl validate -m metal -c _out/worker.yaml
                '''
            }
        }

        stage('Apply Control Plane Config') {
            steps {
                sh '''
                    talosctl apply-config --insecure \
                        --nodes ${CONTROL_PLANE_IP} \
                        --file _out/controlplane.yaml
                '''
            }
        }

        stage('Bootstrap Cluster') {
            steps {
                sh '''
                    # Wait for node to be ready
                    sleep 60

                    # Bootstrap etcd on first control plane
                    talosctl bootstrap \
                        --nodes ${CONTROL_PLANE_IP} \
                        --talosconfig ${TALOSCONFIG}
                '''
            }
        }

        stage('Wait for Kubernetes') {
            steps {
                sh '''
                    # Wait for Kubernetes API
                    talosctl --nodes ${CONTROL_PLANE_IP} \
                        --talosconfig ${TALOSCONFIG} \
                        health --wait-timeout 10m
                '''
            }
        }

        stage('Get Kubeconfig') {
            steps {
                sh '''
                    talosctl kubeconfig \
                        --nodes ${CONTROL_PLANE_IP} \
                        --talosconfig ${TALOSCONFIG} \
                        -f kubeconfig

                    export KUBECONFIG=${WORKSPACE}/kubeconfig
                    kubectl get nodes
                '''
            }
        }
    }

    post {
        success {
            archiveArtifacts artifacts: 'kubeconfig,_out/talosconfig', fingerprint: true
            echo 'Cluster bootstrapped successfully!'
        }
    }
}
```

### Pipeline: Add Worker Node

```groovy
// templates/talos-add-worker.Jenkinsfile
// Description: Add a worker node to existing Talos cluster

pipeline {
    agent any

    parameters {
        string(name: 'WORKER_IP', description: 'Worker node IP address')
        string(name: 'WORKER_TYPE', defaultValue: 'worker', description: 'worker or worker-gpu')
        string(name: 'HOSTNAME', description: 'Node hostname (e.g., talos-gpu-001)')
    }

    environment {
        TALOSCONFIG = "${WORKSPACE}/_out/talosconfig"
    }

    stages {
        stage('Generate Worker Config') {
            steps {
                sh '''
                    # Patch worker config with specific hostname and IP
                    talosctl machineconfig patch _out/${WORKER_TYPE}.yaml \
                        --patch '[{"op": "replace", "path": "/machine/network/hostname", "value": "'${HOSTNAME}'"}]' \
                        --output _out/${HOSTNAME}.yaml
                '''
            }
        }

        stage('Apply Config to Worker') {
            steps {
                sh '''
                    talosctl apply-config --insecure \
                        --nodes ${WORKER_IP} \
                        --file _out/${HOSTNAME}.yaml
                '''
            }
        }

        stage('Wait for Node Join') {
            steps {
                sh '''
                    sleep 120

                    # Verify node joined cluster
                    export KUBECONFIG=${WORKSPACE}/kubeconfig
                    kubectl get nodes
                    kubectl wait --for=condition=Ready node/${HOSTNAME} --timeout=300s
                '''
            }
        }

        stage('Label GPU Node') {
            when {
                expression { params.WORKER_TYPE == 'worker-gpu' }
            }
            steps {
                sh '''
                    export KUBECONFIG=${WORKSPACE}/kubeconfig
                    kubectl label node ${HOSTNAME} nvidia.com/gpu.present=true --overwrite
                    kubectl label node ${HOSTNAME} node.kubernetes.io/gpu=true --overwrite
                '''
            }
        }
    }

    post {
        success {
            echo "Worker ${HOSTNAME} added successfully!"
        }
    }
}
```

### Pipeline: Cluster Upgrade

```groovy
// templates/talos-cluster-upgrade.Jenkinsfile
// Description: Rolling upgrade of Talos cluster

pipeline {
    agent any

    parameters {
        string(name: 'TALOS_VERSION', defaultValue: 'v1.6.0', description: 'Target Talos version')
        string(name: 'NODES', description: 'Comma-separated list of node IPs to upgrade')
    }

    environment {
        TALOSCONFIG = "${WORKSPACE}/_out/talosconfig"
    }

    stages {
        stage('Pre-flight Checks') {
            steps {
                sh '''
                    # Check cluster health before upgrade
                    talosctl --talosconfig ${TALOSCONFIG} health

                    export KUBECONFIG=${WORKSPACE}/kubeconfig
                    kubectl get nodes
                '''
            }
        }

        stage('Upgrade Nodes') {
            steps {
                script {
                    def nodes = params.NODES.split(',')
                    for (node in nodes) {
                        sh """
                            echo "Upgrading node: ${node}"

                            # Cordon node
                            export KUBECONFIG=${WORKSPACE}/kubeconfig
                            kubectl cordon ${node} || true

                            # Drain workloads
                            kubectl drain ${node} --ignore-daemonsets --delete-emptydir-data --force || true

                            # Upgrade Talos
                            talosctl upgrade \
                                --nodes ${node} \
                                --image ghcr.io/siderolabs/installer:${TALOS_VERSION} \
                                --talosconfig ${TALOSCONFIG}

                            # Wait for node to come back
                            sleep 120

                            # Uncordon node
                            kubectl uncordon ${node}

                            # Wait for node ready
                            kubectl wait --for=condition=Ready node/${node} --timeout=300s

                            echo "Node ${node} upgraded successfully"
                        """
                    }
                }
            }
        }

        stage('Verify Cluster') {
            steps {
                sh '''
                    talosctl --talosconfig ${TALOSCONFIG} health

                    export KUBECONFIG=${WORKSPACE}/kubeconfig
                    kubectl get nodes -o wide
                '''
            }
        }
    }
}
```

---

## Step 3: Deploy MiladyOS Stack

Once the cluster is running, deploy the MiladyOS components.

### Bootstrap Script

```bash
#!/bin/bash
# deploy-miladyos-stack.sh - Deploy full MiladyOS stack to cluster

set -e

export KUBECONFIG=${KUBECONFIG:-./kubeconfig}

echo "=== Deploying MiladyOS Stack ==="

# Step 1: Install Longhorn for distributed storage
echo "[1/4] Installing Longhorn..."
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --values deploy/longhorn-values.yaml \
  --wait

# Step 2: Install ArgoCD for GitOps
echo "[2/4] Installing ArgoCD..."
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --values deploy/argocd-values.yaml \
  --wait

# Step 3: Install NVIDIA GPU Operator (for GPU nodes)
echo "[3/4] Installing NVIDIA GPU Operator..."
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator \
  --create-namespace \
  --set driver.enabled=false \
  --wait

# Step 4: Deploy App of Apps
echo "[4/4] Deploying MiladyOS applications..."
kubectl apply -f deploy/argocd-apps/app-of-apps.yaml

echo "=== Deployment Complete ==="
echo "ArgoCD UI: kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "ArgoCD Password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
```

### Jenkins Pipeline: Full Stack Deploy

```groovy
// templates/miladyos-stack-deploy.Jenkinsfile
// Description: Deploy complete MiladyOS stack to Talos cluster

pipeline {
    agent any

    environment {
        KUBECONFIG = "${WORKSPACE}/kubeconfig"
    }

    stages {
        stage('Verify Cluster') {
            steps {
                sh '''
                    kubectl cluster-info
                    kubectl get nodes
                '''
            }
        }

        stage('Deploy Longhorn') {
            steps {
                sh '''
                    helm repo add longhorn https://charts.longhorn.io
                    helm repo update
                    helm upgrade --install longhorn longhorn/longhorn \
                        --namespace longhorn-system \
                        --create-namespace \
                        --values deploy/longhorn-values.yaml \
                        --wait --timeout 10m
                '''
            }
        }

        stage('Deploy ArgoCD') {
            steps {
                sh '''
                    helm repo add argo https://argoproj.github.io/argo-helm
                    helm upgrade --install argocd argo/argo-cd \
                        --namespace argocd \
                        --create-namespace \
                        --values deploy/argocd-values.yaml \
                        --wait --timeout 10m
                '''
            }
        }

        stage('Deploy GPU Operator') {
            steps {
                sh '''
                    helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
                    helm upgrade --install gpu-operator nvidia/gpu-operator \
                        --namespace gpu-operator \
                        --create-namespace \
                        --set driver.enabled=false \
                        --wait --timeout 10m
                '''
            }
        }

        stage('Deploy MiladyOS Apps') {
            steps {
                sh '''
                    kubectl apply -f deploy/argocd-apps/app-of-apps.yaml

                    # Wait for apps to sync
                    sleep 60
                    kubectl -n argocd get applications
                '''
            }
        }

        stage('Verify Deployment') {
            steps {
                sh '''
                    echo "=== Cluster Status ==="
                    kubectl get nodes -o wide

                    echo "=== GPU Status ==="
                    kubectl get pods -n gpu-operator

                    echo "=== Storage Status ==="
                    kubectl -n longhorn-system get pods

                    echo "=== ArgoCD Apps ==="
                    kubectl -n argocd get applications

                    echo "=== All Pods ==="
                    kubectl get pods -A | grep -v "Running\|Completed" || echo "All pods healthy!"
                '''
            }
        }
    }

    post {
        success {
            echo '''
                ╔═══════════════════════════════════════════════════════════════╗
                ║            MiladyOS Stack Deployed Successfully!              ║
                ╠═══════════════════════════════════════════════════════════════╣
                ║                                                               ║
                ║  Access Points:                                               ║
                ║  • ArgoCD:   kubectl port-forward svc/argocd-server 8080:443  ║
                ║  • Grafana:  kubectl port-forward svc/grafana 3000:3000       ║
                ║  • Jenkins:  Already running in MiladyOS container            ║
                ║                                                               ║
                ║  We are all Milady. Always have been.                         ║
                ║                                                               ║
                ╚═══════════════════════════════════════════════════════════════╝
            '''
        }
    }
}
```

---

## Step 4: Configure Nebula Mesh

Connect all nodes via Nebula overlay network for secure communication.

### Generate Nebula Certificates

```bash
# On lighthouse node (or your workstation)
nebula-cert ca -name "MiladyOS Network"

# Generate cert for each node
nebula-cert sign -name "talos-cp-001" -ip "192.168.5.10/24"
nebula-cert sign -name "talos-gpu-001" -ip "192.168.5.20/24" -groups "gpu"
nebula-cert sign -name "talos-gpu-002" -ip "192.168.5.21/24" -groups "gpu"
nebula-cert sign -name "talos-store-01" -ip "192.168.5.30/24" -groups "storage"
```

### Deploy Nebula as DaemonSet

```yaml
# deploy/nebula/nebula-daemonset.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: nebula
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: nebula
  template:
    metadata:
      labels:
        app: nebula
    spec:
      hostNetwork: true
      containers:
      - name: nebula
        image: nebulaoss/nebula:latest
        securityContext:
          capabilities:
            add: ["NET_ADMIN"]
        volumeMounts:
        - name: config
          mountPath: /etc/nebula
          readOnly: true
        - name: tun
          mountPath: /dev/net/tun
      volumes:
      - name: config
        secret:
          secretName: nebula-config
      - name: tun
        hostPath:
          path: /dev/net/tun
```

---

## Step 5: Node-Specific Workload Scheduling

### Label Nodes by Capability

```bash
# GPU nodes
kubectl label node talos-gpu-001 nvidia.com/gpu.present=true
kubectl label node talos-gpu-001 node.kubernetes.io/instance-type=gpu-large
kubectl label node talos-gpu-001 miladyos.net/role=inference

kubectl label node talos-gpu-002 nvidia.com/gpu.present=true
kubectl label node talos-gpu-002 miladyos.net/role=training

# Storage nodes
kubectl label node talos-store-01 longhorn.io/node=true
kubectl label node talos-store-01 miladyos.net/role=storage
```

### Schedule LLMs to GPU Nodes

Update your deployment to target specific nodes:

```yaml
# deploy/mistral-7b/mistral-7b-deployment.yaml
spec:
  template:
    spec:
      nodeSelector:
        nvidia.com/gpu.present: "true"
        miladyos.net/role: inference
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
```

---

## Monitoring Multi-Node Cluster

### Check Node Status

```bash
# Via talosctl
talosctl --nodes 192.168.5.10,192.168.5.20,192.168.5.21 health

# Via kubectl
kubectl get nodes -o wide
kubectl top nodes
```

### Check GPU Allocation

```bash
kubectl describe nodes | grep -A5 "Allocated resources"
kubectl get pods -o wide | grep -i gpu
```

### ArgoCD Application Status

```bash
kubectl -n argocd get applications
argocd app list  # If argocd CLI is installed
```

---

## Troubleshooting

### Node Won't Join Cluster

```bash
# Check Talos logs
talosctl --nodes <node-ip> logs controller-runtime

# Check kubelet status
talosctl --nodes <node-ip> service kubelet status

# Reset and retry
talosctl reset --nodes <node-ip> --graceful=false
```

### GPU Not Detected

```bash
# Check GPU Operator pods
kubectl -n gpu-operator get pods

# Check if driver is loaded
kubectl -n gpu-operator logs -l app=nvidia-driver-daemonset

# Verify on node
talosctl --nodes <gpu-node-ip> dmesg | grep -i nvidia
```

### Storage Issues

```bash
# Check Longhorn status
kubectl -n longhorn-system get pods
kubectl -n longhorn-system get nodes.longhorn.io

# Check volume health
kubectl get pv
kubectl get pvc -A
```

### Network Connectivity

```bash
# Check Nebula status
kubectl -n kube-system logs -l app=nebula

# Test cross-node connectivity
kubectl run test --image=busybox --rm -it -- ping 192.168.5.20
```

---

## Quick Reference: Common Operations

| Task | Command |
|------|---------|
| **Add worker node** | `talosctl apply-config --insecure --nodes <ip> --file worker.yaml` |
| **Upgrade node** | `talosctl upgrade --nodes <ip> --image ghcr.io/siderolabs/installer:v1.6.x` |
| **Reset node** | `talosctl reset --nodes <ip> --graceful=false` |
| **Get node logs** | `talosctl --nodes <ip> logs controller-runtime` |
| **Check services** | `talosctl --nodes <ip> services` |
| **Dashboard** | `talosctl --nodes <ip> dashboard` |
| **Cluster health** | `talosctl health --nodes <control-plane-ip>` |
| **Get kubeconfig** | `talosctl kubeconfig --nodes <control-plane-ip>` |

---

## Next Steps

- [Configuration Reference](/docs/configuration/) - All environment variables and config options
- [Infrastructure](/docs/infrastructure/) - Detailed Longhorn and ArgoCD setup
- [Operations](/docs/operations/) - Day-2 operations and maintenance
- [Security](/docs/security/) - Lock down your multi-node deployment

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   "When there's a task that can be done manually in 10 minutes,            │
│    but you find a way to automate it in 100 days..."                       │
│                                                                             │
│   I'm gonna do what's called a milady move <3                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
