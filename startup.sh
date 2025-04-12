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
    # Check if we are explicitly in Kubernetes mode or if Docker is disabled
    if [ "${KUBERNETES_MODE}" = "true" ] || [ "${DISABLE_DOCKER}" = "true" ]; then
        echo "Running in Kubernetes mode or Docker is disabled by configuration."
        echo "Checking for kubectl..."
        if kubectl_ready; then
            echo "kubectl is available. Will use Kubernetes for container operations."
            export USE_KUBECTL=true
            return 0
        else
            echo "WARNING: kubectl not available in Kubernetes mode."
            # Continue anyway, as other services may still work
            return 0
        fi
    fi
    
    # Check if we are in a Kubernetes environment
    if [ -n "${KUBERNETES_SERVICE_HOST}" ]; then
        echo "Detected Kubernetes environment. Checking for kubectl..."
        if kubectl_ready; then
            echo "kubectl is available. Will use Kubernetes for container operations."
            export USE_KUBECTL=true
            return 0
        fi
    fi
    
    # If Docker is explicitly disabled, don't try to start it
    if [ "${DISABLE_DOCKER}" = "true" ]; then
        echo "Docker is disabled by configuration."
        return 0
    fi
    
    # Check if Docker socket exists and is not a directory
    if [ -S "/var/run/docker.sock" ]; then
        echo "Docker socket exists, checking if Docker is already running..."
        if docker_ready; then
            echo "Docker is already running and accessible"
            return 0
        fi
    elif [ -d "/var/run/docker.sock" ]; then
        echo "Error: /var/run/docker.sock is a directory, cannot use Docker socket"
        # Clean up the directory to prepare for Docker daemon
        rm -rf /var/run/docker.sock
    fi
    
    # Try to start Docker daemon
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

# Set default IP range if not provided
IP_RANGE=${IP_RANGE:-"192\.168\."}

# Get the host's IP address
HOST_IP=$(get_host_ip)

if [ -z "$HOST_IP" ]; then
    echo "Could not determine the host's IP address in the specified range ($IP_RANGE)."
    echo "Using localhost as fallback."
    HOST_IP="127.0.0.1"
fi

# Discover Kubernetes server using Avahi if available
if command -v avahi-browse > /dev/null 2>&1; then
    echo "Discovering Kubernetes server..."
    SERVER_IP=$(discover_k8s_server)
    if [ -n "$SERVER_IP" ]; then
        echo "Found Kubernetes server at $SERVER_IP"
    else
        echo "No Kubernetes server discovered via Avahi"
    fi
else
    echo "Avahi not installed, skipping Kubernetes server discovery"
fi

# Function to start a service if available
start_service() {
    local name="$1"
    local command="$2"
    local required="$3"
    
    if command -v $(echo "$command" | awk '{print $1}') > /dev/null 2>&1; then
        echo "Starting $name..."
        eval "$command" &
        
        # Wait for service to start
        sleep 5
        
        # Check if service started successfully
        if pgrep -x "$(echo "$command" | awk '{print $1}')" > /dev/null || pgrep -f "$command" > /dev/null; then
            echo "$name started successfully"
            return 0
        else
            echo "WARNING: $name did not start successfully"
            if [ "$required" = "true" ]; then
                echo "ERROR: Required service $name failed to start"
                return 1
            fi
            return 0
        fi
    else
        echo "WARNING: $name command not found, skipping"
        if [ "$required" = "true" ]; then
            echo "ERROR: Required service $name not available"
            return 1
        fi
        return 0
    fi
}

# Start Caddy if available
start_service "Caddy" "caddy run --config /etc/caddy/Caddyfile" "false" || true

# Start Ollama if available
if command -v ollama > /dev/null 2>&1; then
    echo "Starting Ollama..."
    OLLAMA_HOST=0.0.0.0 ollama serve &
    sleep 5
    
    # Check if ollama is running
    if pgrep -x "ollama" > /dev/null; then
        echo "Ollama started successfully"
    else
        echo "WARNING: Ollama did not start successfully, continuing anyway"
    fi
else
    echo "Ollama not available, skipping"
fi

# Start Filebrowser instances if available
if command -v filebrowser > /dev/null 2>&1; then
    echo "Starting Filebrowser instances..."
    
    # Create parent directories if they don't exist
    mkdir -p /etc/filebrowser-metrics
    mkdir -p /etc/filebrowser-models
    
    # Start filebrowser instances
    filebrowser -a 0.0.0.0 -r /metrics -d /etc/filebrowser-metrics/filebrowser.db -p 7331 &
    filebrowser -a 0.0.0.0 -r /models -d /etc/filebrowser-models/filebrowser.db -p 1337 &
    
    sleep 5
    echo "Filebrowser instances started"
else
    echo "Filebrowser not available, skipping"
fi

# Create directory for Redka database and start if available
if command -v redka > /dev/null 2>&1; then
    echo "Starting Redka server..."
    mkdir -p /data/redka
    redka -h 0.0.0.0 -p 6379 /data/redka/data.db &
    sleep 5
    
    # Check if redka is running
    if pgrep -x "redka" > /dev/null; then
        echo "Redka server started successfully"
    else
        echo "WARNING: Redka server did not start successfully"
    fi
else
    echo "Redka not available, switching to default Redis if available"
    if command -v redis-server > /dev/null 2>&1; then
        echo "Starting Redis server..."
        redis-server --bind 0.0.0.0 &
        sleep 2
    else
        echo "WARNING: Neither Redka nor Redis is available"
    fi
fi

# Start the NVIDIA monitoring script if it exists
if [ -x "/nvidia.sh" ]; then
    echo "Starting NVIDIA monitoring..."
    /nvidia.sh &
    sleep 2
else
    echo "NVIDIA monitoring script not found or not executable, skipping"
fi

# Start MCP server if main.py exists
if [ -f "/app/main.py" ]; then
    echo "Starting MCP server..."
    cd /app && python -m main mcp --redis-host localhost --redis-port 6379 --transport sse --host 0.0.0.0 --port 6000 &
    sleep 2
    
    # Check if python process is running
    if pgrep -f "python -m main mcp" > /dev/null; then
        echo "MiladyOS MCP server started on port 6000"
    else
        echo "WARNING: MCP server did not start successfully"
    fi
else
    echo "WARNING: main.py not found at /app/main.py, MCP server will not be available"
fi

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
