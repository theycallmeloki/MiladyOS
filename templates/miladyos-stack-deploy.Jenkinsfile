// Description: Deploy the complete MiladyOS stack to a Talos Kubernetes cluster
// Usage: Run after cluster is bootstrapped with at least one control plane node

pipeline {
    agent any

    parameters {
        string(name: 'CONTROL_PLANE_IP', defaultValue: '192.168.5.10', description: 'Control plane IP')
        booleanParam(name: 'INSTALL_LONGHORN', defaultValue: true, description: 'Install Longhorn storage')
        booleanParam(name: 'INSTALL_ARGOCD', defaultValue: true, description: 'Install ArgoCD')
        booleanParam(name: 'INSTALL_GPU_OPERATOR', defaultValue: true, description: 'Install NVIDIA GPU Operator')
        booleanParam(name: 'DEPLOY_APPS', defaultValue: true, description: 'Deploy MiladyOS applications')
    }

    environment {
        KUBECONFIG = "${WORKSPACE}/kubeconfig"
        TALOSCONFIG = "${WORKSPACE}/_out/talosconfig"
    }

    stages {
        stage('Get Kubeconfig') {
            steps {
                // Try to copy from bootstrap job
                copyArtifacts(
                    projectName: 'talos-cluster-bootstrap',
                    filter: 'kubeconfig,_out/talosconfig',
                    optional: true
                )

                sh '''
                    if [ ! -f "kubeconfig" ]; then
                        echo "Fetching kubeconfig from cluster..."
                        mkdir -p _out
                        talosctl kubeconfig --nodes ${CONTROL_PLANE_IP} kubeconfig || {
                            echo "ERROR: Cannot get kubeconfig. Ensure cluster is running."
                            exit 1
                        }
                    fi

                    echo "=== Cluster Info ==="
                    kubectl cluster-info
                    kubectl get nodes
                '''
            }
        }

        stage('Add Helm Repos') {
            steps {
                sh '''
                    helm repo add longhorn https://charts.longhorn.io || true
                    helm repo add argo https://argoproj.github.io/argo-helm || true
                    helm repo add nvidia https://helm.ngc.nvidia.com/nvidia || true
                    helm repo update
                '''
            }
        }

        stage('Install Longhorn') {
            when {
                expression { params.INSTALL_LONGHORN }
            }
            steps {
                sh '''
                    echo "Installing Longhorn distributed storage..."

                    helm upgrade --install longhorn longhorn/longhorn \
                        --namespace longhorn-system \
                        --create-namespace \
                        --values deploy/longhorn-values.yaml \
                        --wait --timeout 10m

                    echo "Waiting for Longhorn to be ready..."
                    kubectl -n longhorn-system wait --for=condition=ready pod \
                        -l app=longhorn-manager --timeout=300s

                    kubectl -n longhorn-system get pods
                '''
            }
        }

        stage('Install ArgoCD') {
            when {
                expression { params.INSTALL_ARGOCD }
            }
            steps {
                sh '''
                    echo "Installing ArgoCD..."

                    helm upgrade --install argocd argo/argo-cd \
                        --namespace argocd \
                        --create-namespace \
                        --values deploy/argocd-values.yaml \
                        --wait --timeout 10m

                    echo "Waiting for ArgoCD to be ready..."
                    kubectl -n argocd wait --for=condition=ready pod \
                        -l app.kubernetes.io/name=argocd-server --timeout=300s

                    echo ""
                    echo "ArgoCD admin password:"
                    kubectl -n argocd get secret argocd-initial-admin-secret \
                        -o jsonpath="{.data.password}" | base64 -d
                    echo ""
                '''
            }
        }

        stage('Install GPU Operator') {
            when {
                expression { params.INSTALL_GPU_OPERATOR }
            }
            steps {
                sh '''
                    echo "Installing NVIDIA GPU Operator..."

                    # Check if any GPU nodes exist
                    GPU_NODES=$(kubectl get nodes -l nvidia.com/gpu.present=true -o name 2>/dev/null | wc -l)

                    if [ "$GPU_NODES" -eq 0 ]; then
                        echo "WARNING: No GPU nodes detected. Skipping GPU Operator."
                        exit 0
                    fi

                    helm upgrade --install gpu-operator nvidia/gpu-operator \
                        --namespace gpu-operator \
                        --create-namespace \
                        --set driver.enabled=false \
                        --set toolkit.enabled=true \
                        --wait --timeout 10m

                    kubectl -n gpu-operator get pods
                '''
            }
        }

        stage('Deploy MiladyOS Apps') {
            when {
                expression { params.DEPLOY_APPS }
            }
            steps {
                sh '''
                    echo "Deploying MiladyOS App-of-Apps..."

                    kubectl apply -f deploy/argocd-apps/app-of-apps.yaml

                    echo "Waiting for apps to sync..."
                    sleep 60

                    kubectl -n argocd get applications
                '''
            }
        }

        stage('Verify Deployment') {
            steps {
                sh '''
                    echo ""
                    echo "=========================================="
                    echo "  MILADYOS STACK DEPLOYMENT COMPLETE"
                    echo "=========================================="
                    echo ""

                    echo "=== Nodes ==="
                    kubectl get nodes -o wide

                    echo ""
                    echo "=== Storage (Longhorn) ==="
                    kubectl -n longhorn-system get pods 2>/dev/null || echo "Longhorn not installed"

                    echo ""
                    echo "=== GitOps (ArgoCD) ==="
                    kubectl -n argocd get pods 2>/dev/null || echo "ArgoCD not installed"

                    echo ""
                    echo "=== GPU Operator ==="
                    kubectl -n gpu-operator get pods 2>/dev/null || echo "GPU Operator not installed"

                    echo ""
                    echo "=== ArgoCD Applications ==="
                    kubectl -n argocd get applications 2>/dev/null || echo "No apps deployed yet"

                    echo ""
                    echo "=== All Pods ==="
                    kubectl get pods -A | grep -v "Running\|Completed" || echo "All pods are healthy!"
                '''
            }
        }
    }

    post {
        success {
            echo '''
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║   ███╗   ███╗██╗██╗      █████╗ ██████╗ ██╗   ██╗ ██████╗ ███████╗            ║
║   ████╗ ████║██║██║     ██╔══██╗██╔══██╗╚██╗ ██╔╝██╔═══██╗██╔════╝            ║
║   ██╔████╔██║██║██║     ███████║██║  ██║ ╚████╔╝ ██║   ██║███████╗            ║
║   ██║╚██╔╝██║██║██║     ██╔══██║██║  ██║  ╚██╔╝  ██║   ██║╚════██║            ║
║   ██║ ╚═╝ ██║██║███████╗██║  ██║██████╔╝   ██║   ╚██████╔╝███████║            ║
║   ╚═╝     ╚═╝╚═╝╚══════╝╚═╝  ╚═╝╚═════╝    ╚═╝    ╚═════╝ ╚══════╝            ║
║                                                                               ║
║                    Stack Deployed Successfully!                               ║
║                                                                               ║
║   Access Points:                                                              ║
║   • ArgoCD UI:  kubectl port-forward svc/argocd-server -n argocd 8080:443     ║
║   • Grafana:    kubectl port-forward svc/grafana -n monitoring 3000:3000      ║
║   • Longhorn:   kubectl port-forward svc/longhorn-frontend -n longhorn 8000   ║
║                                                                               ║
║                     We are all Milady. Always have been.                      ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
            '''
        }
        failure {
            echo 'Stack deployment failed. Check logs for details.'
        }
    }
}
