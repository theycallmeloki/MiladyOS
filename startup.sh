#!/bin/bash

# Function to discover Kubernetes cluster using Avahi
discover_k8s_cluster() {
    # This command looks for a service named "_kubernetes._tcp"
    # You'll need to ensure your k3s clusters are advertising this service via Avahi
    avahi-browse -tpr _kubernetes._tcp | grep "=;.*IPv4;.*"
}

# Start Caddy in the background
caddy run --config /etc/caddy/Caddyfile &

# Sleep for a few seconds to ensure Caddy starts
sleep 5

# Start Ollama in the background
OLLAMA_HOST=0.0.0.0 ollama serve &

# Sleep to start
sleep 5

# Discover Kubernetes cluster
echo "Discovering Kubernetes cluster..."
CLUSTER_FOUND=$(discover_k8s_cluster)

if [ -n "$CLUSTER_FOUND" ]; then
    echo "Kubernetes cluster found. Attempting to join..."
    # Code to join the discovered Kubernetes cluster
    # This might involve running k3s agent with specific flags or config
else
    echo "No Kubernetes cluster found. Bootstrapping a new cluster..."
    # Code to start a new Kubernetes cluster
    # This typically involves starting k3s server
    k3s server &
fi

# Sleep to allow k3s to initialize
sleep 10

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
