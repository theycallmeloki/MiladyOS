#!/bin/bash

# Function to get the host's IP address in the specified range
get_host_ip() {
    # Get all IP addresses, filter for the desired pattern
    ip -4 addr | grep -oP "${IP_RANGE}\d+" | head -n 1
}

# Function to discover Kubernetes server using Avahi
discover_k8s_server() {
    # Parse avahi-browse output to find a Kubernetes server's IP
    avahi-browse -tpr _kubernetes._tcp | grep "=;.*IPv4;.*" | awk '{print $8}' | head -n 1
}

# Function to check if Docker client works
docker_ready() {
    docker info > /dev/null 2>&1
}

# Function to check if kubectl is available
kubectl_ready() {
    kubectl version --client > /dev/null 2>&1
}

# Function to set up container build environment
setup_build_environment() {
    # Try to start Docker daemon first
    echo "Attempting to start Docker daemon..."
    
    # Try to start dockerd in the background
    dockerd \
        --host=unix:///var/run/docker.sock \
        --host=tcp://0.0.0.0:2375 \
        > /var/log/dockerd.log 2>&1 < /dev/null &
    
    # Wait for up to 10 seconds for Docker to be ready
    local max_attempts=10
    local attempts=0
    while [ $attempts -lt $max_attempts ]; do
        if docker_ready; then
            echo "Docker daemon started successfully"
            return 0
        fi
        attempts=$((attempts+1))
        sleep 1
    done
    
    # If Docker failed to start, check for kubectl
    echo "Docker daemon failed to start. Checking for kubectl..."
    if kubectl_ready; then
        echo "kubectl is available. Will use Kubernetes for container operations."
        # Set environment variable to indicate kubectl should be used
        export USE_KUBECTL=true
        return 0
    fi
    
    # Neither Docker nor kubectl is available
    echo "WARNING: Neither Docker nor kubectl is available. Container builds and deployments may fail."
    return 1
}

# Set up build environment
setup_build_environment

# Get the host's IP address
HOST_IP=$(get_host_ip)

if [ -z "$HOST_IP" ]; then
    echo "Could not determine the host's IP address in the specified range ($IP_RANGE). Exiting."
    exit 1
fi

# Discover Kubernetes server using Avahi
echo "Discovering Kubernetes server..."
SERVER_IP=$(discover_k8s_server)

# Start Caddy in the background
caddy run --config /etc/caddy/Caddyfile &

# Sleep for a few seconds to ensure Caddy starts
sleep 5

if ! pgrep -x "caddy" > /dev/null; then
    echo "Caddy did not start successfully. Exiting."
    # exit 1
fi

# Start Ollama in the background
OLLAMA_HOST=0.0.0.0 ollama serve &

# Sleep to start
sleep 5

if ! pgrep -x "ollama" > /dev/null; then
    echo "Ollama did not start successfully. Exiting."
    exit 1
fi

# Sleep to start
sleep 5

# Launch filebrowser in the background
filebrowser -a 0.0.0.0 -r /metrics -d /etc/filebrowser-metrics/filebrowser.db -p 7331 &
filebrowser -a 0.0.0.0 -r /models -d /etc/filebrowser-models/filebrowser.db -p 1337 &

# Sleep to start
sleep 15

# Create directory for Redka database
mkdir -p /data/redka

# Start Redka server in the background
redka -h 0.0.0.0 -p 6379 /data/redka/data.db &

# Sleep to start
sleep 5

# Start the NVIDIA monitoring script in the background
/nvidia.sh &

# Sleep to start
sleep 5

# Start MCP server with HTTP transport in the background
python -m main mcp --redis-host localhost --redis-port 6379 --http --port 6000 &

# Sleep to ensure MCP server starts
sleep 2
echo "MiladyOS MCP server started on port 6000"

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
