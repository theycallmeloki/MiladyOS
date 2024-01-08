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

# Switch to root user for k3sup commands
gosu root

# # Determine if this node will be a server or an agent
# if [ -n "$SERVER_IP" ] && [ "$SERVER_IP" != "$HOST_IP" ]; then
#     echo "Kubernetes server found at $SERVER_IP. Attempting to join..."
#     k3sup join --ip $SERVER_IP --user root || exit 1
# else
#     echo "No Kubernetes server found or self is server. Bootstrapping a new cluster..."
#     k3sup install --local --ip $HOST_IP --cluster --user root --k3s-extra-args '--docker' || exit 1

#     # Start k3s server
#     /usr/local/bin/k3s server --docker --debug	 &

#     sleep 120
    
#     if ! pgrep -x "k3s" > /dev/null; then
#         echo "k3s did not start successfully. Exiting."
#         exit 1
#     fi
# fi

# Switch back to the jenkins user
gosu jenkins

# Sleep to allow k3s to initialize
sleep 10

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
