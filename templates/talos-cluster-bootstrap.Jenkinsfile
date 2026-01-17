// Description: Bootstrap a new Talos Kubernetes cluster for MiladyOS
// Usage: Configure control plane IP and run to create a new cluster

pipeline {
    agent any

    parameters {
        string(name: 'CONTROL_PLANE_IP', defaultValue: '192.168.5.10', description: 'Control plane node IP')
        string(name: 'CLUSTER_NAME', defaultValue: 'miladyos-cluster', description: 'Cluster name')
        string(name: 'CLUSTER_ENDPOINT', defaultValue: 'https://192.168.5.10:6443', description: 'Kubernetes API endpoint')
        string(name: 'TALOS_VERSION', defaultValue: 'v1.6.0', description: 'Talos version')
        booleanParam(name: 'GENERATE_NEW_SECRETS', defaultValue: false, description: 'Generate new cluster secrets')
    }

    environment {
        TALOSCONFIG = "${WORKSPACE}/_out/talosconfig"
        KUBECONFIG = "${WORKSPACE}/kubeconfig"
    }

    stages {
        stage('Prepare Workspace') {
            steps {
                sh '''
                    mkdir -p _out
                    echo "Talos version: $(talosctl version --client)"
                '''
            }
        }

        stage('Generate Secrets') {
            when {
                expression { params.GENERATE_NEW_SECRETS }
            }
            steps {
                sh '''
                    talosctl gen secrets -o _out/secrets.yaml
                    echo "New secrets generated - save _out/secrets.yaml securely!"
                '''
            }
        }

        stage('Generate Configs') {
            steps {
                sh '''
                    # Generate cluster configs
                    if [ -f "_out/secrets.yaml" ]; then
                        talosctl gen config ${CLUSTER_NAME} ${CLUSTER_ENDPOINT} \
                            --with-secrets _out/secrets.yaml \
                            --output-dir _out \
                            --force
                    else
                        talosctl gen config ${CLUSTER_NAME} ${CLUSTER_ENDPOINT} \
                            --output-dir _out \
                            --force
                    fi

                    ls -la _out/
                '''
            }
        }

        stage('Validate Configs') {
            steps {
                sh '''
                    talosctl validate -m metal -c _out/controlplane.yaml
                    talosctl validate -m metal -c _out/worker.yaml
                    echo "Configs validated successfully"
                '''
            }
        }

        stage('Apply Control Plane Config') {
            steps {
                sh '''
                    echo "Applying config to control plane at ${CONTROL_PLANE_IP}..."
                    talosctl apply-config --insecure \
                        --nodes ${CONTROL_PLANE_IP} \
                        --file _out/controlplane.yaml

                    echo "Config applied, waiting for node to process..."
                    sleep 30
                '''
            }
        }

        stage('Bootstrap Cluster') {
            steps {
                sh '''
                    echo "Bootstrapping etcd on control plane..."

                    # Wait for Talos to be ready
                    for i in $(seq 1 30); do
                        if talosctl --nodes ${CONTROL_PLANE_IP} --talosconfig ${TALOSCONFIG} version >/dev/null 2>&1; then
                            echo "Talos API is ready"
                            break
                        fi
                        echo "Waiting for Talos API... ($i/30)"
                        sleep 10
                    done

                    # Bootstrap the cluster
                    talosctl bootstrap \
                        --nodes ${CONTROL_PLANE_IP} \
                        --talosconfig ${TALOSCONFIG}

                    echo "Bootstrap initiated"
                '''
            }
        }

        stage('Wait for Kubernetes') {
            steps {
                sh '''
                    echo "Waiting for Kubernetes to be ready..."

                    talosctl --nodes ${CONTROL_PLANE_IP} \
                        --talosconfig ${TALOSCONFIG} \
                        health --wait-timeout 10m

                    echo "Cluster is healthy!"
                '''
            }
        }

        stage('Get Kubeconfig') {
            steps {
                sh '''
                    talosctl kubeconfig \
                        --nodes ${CONTROL_PLANE_IP} \
                        --talosconfig ${TALOSCONFIG} \
                        --force \
                        ${KUBECONFIG}

                    echo "=== Cluster Status ==="
                    kubectl --kubeconfig ${KUBECONFIG} get nodes
                    kubectl --kubeconfig ${KUBECONFIG} cluster-info
                '''
            }
        }

        stage('Archive Configs') {
            steps {
                archiveArtifacts artifacts: '_out/talosconfig,kubeconfig', fingerprint: true

                sh '''
                    echo ""
                    echo "=========================================="
                    echo "  CLUSTER BOOTSTRAP COMPLETE"
                    echo "=========================================="
                    echo ""
                    echo "Cluster: ${CLUSTER_NAME}"
                    echo "Endpoint: ${CLUSTER_ENDPOINT}"
                    echo ""
                    echo "Archived artifacts:"
                    echo "  - talosconfig: Talos client configuration"
                    echo "  - kubeconfig: Kubernetes client configuration"
                    echo ""
                    echo "Next steps:"
                    echo "  1. Add worker nodes using talos-add-worker pipeline"
                    echo "  2. Deploy MiladyOS stack using miladyos-stack-deploy pipeline"
                    echo ""
                '''
            }
        }
    }

    post {
        success {
            echo 'Cluster bootstrapped successfully!'
        }
        failure {
            echo 'Cluster bootstrap failed. Check logs for details.'
        }
        always {
            cleanWs(cleanWhenSuccess: false)
        }
    }
}
