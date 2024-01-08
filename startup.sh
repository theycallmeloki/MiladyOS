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

# Function to check if Docker is ready
docker_ready() {
    docker info > /dev/null 2>&1
}

# Function to run Docker daemon
run_docker() {
    dockerd \
        --host=unix:///var/run/docker.sock \
        --host=tcp://0.0.0.0:2375 \
        > /var/log/dockerd.log 2>&1 < /dev/null &

    # Wait for Docker to be ready
    until docker_ready; do
        sleep 1
    done
}


# Start Docker daemon
echo "Starting Docker..."
run_docker


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


# Get the host's IP address
HOST_IP=$(get_host_ip)

if [ -z "$HOST_IP" ]; then
    echo "Could not determine the host's IP address in the specified range ($IP_RANGE). Exiting."
    exit 1
fi

# Discover Kubernetes server using Avahi
echo "Discovering Kubernetes server..."
SERVER_IP=$(discover_k8s_server)

# Switch to root user for k3s commands
gosu root

# Determine if this node will be a server or an agent
if [ -n "$SERVER_IP" ] && [ "$SERVER_IP" != "$HOST_IP" ]; then
    echo "Kubernetes server found at $SERVER_IP. Attempting to join as an agent..."
    # Start k3s as agent
    /usr/local/bin/k3s agent --server https://${SERVER_IP}:6443 --docker --token milady &
else
    echo "No Kubernetes server found or self is server. Bootstrapping a new cluster as server..."
    # Start k3s server
    /usr/local/bin/k3s server --node-name grill --docker --debug --bind-address ${HOST_IP} --node-ip ${HOST_IP} --flannel-backend none --disable-network-policy --cluster-init  --snapshotter zfs --https-listen-port 6443 --token milady &
fi

sleep 120

# Check if k3s is running
if ! pgrep -x "k3s" > /dev/null; then
    echo "k3s did not start successfully. Exiting."
    exit 1
fi


# Switch back to the jenkins user
gosu jenkins

# Sleep to allow k3s to initialize
sleep 10

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
