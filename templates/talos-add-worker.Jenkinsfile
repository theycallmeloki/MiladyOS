// Description: Add a worker node to an existing Talos Kubernetes cluster
// Usage: Provide worker IP, hostname, and optionally mark as GPU node

pipeline {
    agent any

    parameters {
        string(name: 'WORKER_IP', description: 'IP address of the worker node')
        string(name: 'HOSTNAME', description: 'Hostname for the worker (e.g., talos-gpu-001)')
        string(name: 'CONTROL_PLANE_IP', defaultValue: '192.168.5.10', description: 'Control plane IP for cluster access')
        choice(name: 'NODE_TYPE', choices: ['worker', 'worker-gpu', 'worker-storage'], description: 'Type of worker node')
        booleanParam(name: 'HAS_GPU', defaultValue: false, description: 'Node has NVIDIA GPU')
        booleanParam(name: 'IS_STORAGE_NODE', defaultValue: false, description: 'Use for Longhorn storage')
    }

    environment {
        TALOSCONFIG = "${WORKSPACE}/_out/talosconfig"
        KUBECONFIG = "${WORKSPACE}/kubeconfig"
    }

    stages {
        stage('Fetch Cluster Configs') {
            steps {
                // Copy from last successful bootstrap or provide manually
                copyArtifacts(
                    projectName: 'talos-cluster-bootstrap',
                    filter: '_out/talosconfig,kubeconfig,_out/worker.yaml',
                    optional: true
                )

                sh '''
                    if [ ! -f "_out/talosconfig" ]; then
                        echo "ERROR: No talosconfig found. Run talos-cluster-bootstrap first or provide configs."
                        exit 1
                    fi

                    # Get kubeconfig if not present
                    if [ ! -f "kubeconfig" ]; then
                        talosctl kubeconfig --nodes ${CONTROL_PLANE_IP} --talosconfig ${TALOSCONFIG} kubeconfig
                    fi
                '''
            }
        }

        stage('Generate Worker Config') {
            steps {
                sh '''
                    echo "Generating config for ${HOSTNAME} (${NODE_TYPE})..."

                    # Start with base worker config
                    cp _out/worker.yaml _out/${HOSTNAME}.yaml

                    # Patch with specific settings using talosctl
                    talosctl machineconfig patch _out/${HOSTNAME}.yaml \
                        --patch '[{"op": "replace", "path": "/machine/network/hostname", "value": "'${HOSTNAME}'"}]' \
                        --output _out/${HOSTNAME}.yaml

                    echo "Config generated for ${HOSTNAME}"
                '''
            }
        }

        stage('Apply Config') {
            steps {
                sh '''
                    echo "Applying Talos config to ${WORKER_IP}..."

                    talosctl apply-config --insecure \
                        --nodes ${WORKER_IP} \
                        --file _out/${HOSTNAME}.yaml

                    echo "Config applied, node will reboot and join cluster..."
                '''
            }
        }

        stage('Wait for Node') {
            steps {
                sh '''
                    echo "Waiting for node to join cluster..."

                    # Wait for node to appear in Kubernetes
                    for i in $(seq 1 60); do
                        if kubectl --kubeconfig ${KUBECONFIG} get node ${HOSTNAME} >/dev/null 2>&1; then
                            echo "Node ${HOSTNAME} has joined the cluster!"
                            break
                        fi
                        echo "Waiting for node to join... ($i/60)"
                        sleep 10
                    done

                    # Wait for node to be ready
                    kubectl --kubeconfig ${KUBECONFIG} wait --for=condition=Ready node/${HOSTNAME} --timeout=300s

                    echo "Node ${HOSTNAME} is ready!"
                '''
            }
        }

        stage('Label Node') {
            steps {
                sh '''
                    echo "Applying labels to ${HOSTNAME}..."

                    # Apply role label
                    kubectl --kubeconfig ${KUBECONFIG} label node ${HOSTNAME} \
                        miladyos.net/role=${NODE_TYPE} --overwrite

                    # GPU labels
                    if [ "${HAS_GPU}" = "true" ]; then
                        kubectl --kubeconfig ${KUBECONFIG} label node ${HOSTNAME} \
                            nvidia.com/gpu.present=true \
                            node.kubernetes.io/gpu=true \
                            --overwrite
                        echo "GPU labels applied"
                    fi

                    # Storage labels
                    if [ "${IS_STORAGE_NODE}" = "true" ]; then
                        kubectl --kubeconfig ${KUBECONFIG} label node ${HOSTNAME} \
                            longhorn.io/node=true \
                            node.kubernetes.io/storage=true \
                            --overwrite
                        echo "Storage labels applied"
                    fi
                '''
            }
        }

        stage('Verify') {
            steps {
                sh '''
                    echo "=== Node Status ==="
                    kubectl --kubeconfig ${KUBECONFIG} get node ${HOSTNAME} -o wide

                    echo ""
                    echo "=== Node Labels ==="
                    kubectl --kubeconfig ${KUBECONFIG} get node ${HOSTNAME} --show-labels

                    echo ""
                    echo "=== Cluster Nodes ==="
                    kubectl --kubeconfig ${KUBECONFIG} get nodes -o wide
                '''
            }
        }
    }

    post {
        success {
            echo """
                ====================================
                Worker node added successfully!
                ====================================
                Hostname: ${HOSTNAME}
                IP: ${WORKER_IP}
                Type: ${NODE_TYPE}
                GPU: ${HAS_GPU}
                Storage: ${IS_STORAGE_NODE}
                ====================================
            """
        }
        failure {
            echo 'Failed to add worker node. Check logs for details.'
        }
    }
}
