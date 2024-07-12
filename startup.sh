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

# Start the NVIDIA monitoring script in the background
/nvidia.sh &

# Sleep to start
sleep 5

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
