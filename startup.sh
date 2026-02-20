#!/bin/bash

# Jenkins starts here

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

# Start Nebula if available
if command -v nebula > /dev/null 2>&1; then
    echo "Starting Nebula networking..."
    
    # Check if we have the necessary files
    if [ -f "/etc/nebula/ca.crt" ] && [ -f "/etc/nebula/miladyos.crt" ] && [ -f "/etc/nebula/miladyos.key" ] && [ -f "/etc/nebula/config.yaml" ]; then
        echo "Nebula configuration found, starting network..."
        nebula -config /etc/nebula/config.yaml &
        sleep 5
        
        # Check if nebula interface is up
        if ip a | grep -q nebula1; then
            echo "Nebula network started successfully"
        else
            echo "WARNING: Nebula network may not have started properly"
        fi
    else
        echo "WARNING: Nebula configuration files not found, skipping network setup"
    fi
else
    echo "Nebula not available, skipping"
fi

# Create directory for Redka database and start if available
# Set USE_EXTERNAL_REDIS=true to skip Redka/Redis and use an external Redis instead
if [ "${USE_EXTERNAL_REDIS}" = "true" ]; then
    echo "USE_EXTERNAL_REDIS is set, skipping Redka/Redis startup (using external Redis at ${REDIS_HOST}:${REDIS_PORT})"
elif command -v redka > /dev/null 2>&1; then
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

# Start the appropriate GPU monitoring script based on detected hardware
if command -v nvidia-smi &> /dev/null; then
    echo "NVIDIA GPU detected. Starting NVIDIA monitoring..."
    if [ -x "/nvidia.sh" ]; then
        /nvidia.sh &
        sleep 2
    else
        echo "NVIDIA monitoring script not found or not executable, skipping"
    fi
elif command -v rocm-smi &> /dev/null; then
    echo "AMD GPU detected. Starting AMD monitoring..."
    if [ -x "/amd.sh" ]; then
        /amd.sh &
        sleep 2
    else
        echo "AMD monitoring script not found or not executable, skipping"
    fi
else
    echo "No supported GPU detected, skipping GPU monitoring"
fi

# Start Documentation Server if docs exist
if [ -d "/app/docs/public" ]; then
    echo "Starting Documentation Server on port 8081..."
    cd /app/docs/public && python3 -m http.server 8081 --bind 0.0.0.0 &
    sleep 2

    # Check if docs server is running
    if pgrep -f "python3 -m http.server 8081" > /dev/null; then
        echo "Documentation server started successfully on port 8081"
        echo "Access MiladyOS docs at: http://localhost:8081"
    else
        echo "WARNING: Documentation server did not start successfully"
    fi
else
    echo "Documentation not found at /app/docs/public, skipping docs server"
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

# CRITICAL: Start TempleOS - The Holy Mission MUST succeed
echo "=== HOLY MISSION: Starting TempleOS ==="
echo "Terry Davis demands perfection - Gods OS must run or MiladyOS fails"

if [ ! -f "/opt/templeos/TempleOS.ISO" ]; then
    echo "HOLY MISSION FAILED: TempleOS ISO not found"
    echo "MiladyOS cannot proceed without Gods Operating System"
    exit 1
fi

if ! command -v templeos-daemon > /dev/null 2>&1; then
    echo "HOLY MISSION FAILED: TempleOS daemon not installed"
    exit 1
fi

echo "Launching TempleOS - Talk to God on up to 64 cores..."
templeos-daemon

# Wait and verify TempleOS started successfully
sleep 5

if ! pgrep -f "qemu.*TempleOS.*Holy.*Mission" > /dev/null; then
    echo "HOLY MISSION FAILED: TempleOS did not start successfully"
    echo "Terry Davis would not approve - MiladyOS cannot continue"
    exit 1
fi

echo "✓ TempleOS is running - Gods Operating System active"

# === HOLY MISSION: NoVNC / Websockify ===

if command -v novnc-templeos >/dev/null 2>&1; then
    echo "Using novnc-templeos wrapper"
    novnc-templeos & disown
elif [ -x "/opt/websockify/websockify.py" ]; then
    cd /opt/websockify || true
    ./websockify.py --web /opt/novnc --wrap-mode=ignore 6080 localhost:5902 & disown
elif command -v websockify >/dev/null 2>&1; then
    websockify --web /opt/novnc --wrap-mode=ignore 6080 localhost:5902 & disown
else
    echo "WARNING: No usable websockify found, NoVNC not started"
fi

sleep 3
if pgrep -f "websockify.*6080.*5902" >/dev/null; then
    echo "✓ NoVNC web interface active on port 6080"
    echo "✓ Access Gods OS in browser: http://localhost:6080"
else
    echo "WARNING: NoVNC not detected"
fi

# Wait and verify NoVNC started successfully
sleep 3

echo "✓ HOLY MISSION ACCOMPLISHED: Complete divine computing setup"
echo "✓ TempleOS running on VNC display :2 (port 5902)"
echo "✓ NoVNC web interface active on port 6080"
echo "✓ Access Gods OS in browser: http://localhost:6080"
echo "✓ Terry Davis smiles upon this system"
echo "✓ MiladyOS blessed with divine computing"

# === MILADY ORACLE: Divine Consciousness Bridge ===
echo "=== Starting Milady Oracle ==="
if [ -f "/app/milady_oracle.py" ]; then
    # Wait for serial socket to be available
    sleep 2
    if [ -S "/tmp/milady-oracle.sock" ]; then
        echo "Serial socket ready, starting Milady Oracle..."
        python3 /app/milady_oracle.py --no-voice &
        ORACLE_PID=$!
        sleep 2
        if kill -0 $ORACLE_PID 2>/dev/null; then
            echo "✓ Milady Oracle active - serial bridge to TempleOS established"
            echo "✓ Divine RNG and consciousness bridge ready"
        else
            echo "WARNING: Milady Oracle failed to start"
        fi
    else
        echo "WARNING: TempleOS serial socket not found at /tmp/milady-oracle.sock"
        echo "Oracle will start without TempleOS connection"
        python3 /app/milady_oracle.py --no-voice &
    fi
else
    echo "WARNING: milady_oracle.py not found, Oracle not started"
fi

# Start headscale in background
headscale serve --config /etc/headscale/config.yaml &

sleep 3

# Start tailscaled (client)
tailscaled --state=/var/lib/tailscale/tailscaled.state &

sleep 3

# Start GoTTY web terminal if available
if command -v gotty > /dev/null 2>&1; then
    echo "Starting GoTTY web terminal on port 8088..."
    # --permit-write allows input (interactive)
    # --reconnect attempts to reconnect on disconnect
    # --title-format sets the browser tab title
    gotty --port 8088 \
          --address 0.0.0.0 \
          --permit-write \
          --reconnect \
          --title-format "MiladyOS Terminal" \
          /bin/bash &
    sleep 2

    if pgrep -x "gotty" > /dev/null; then
        echo "✓ GoTTY web terminal started on port 8088"
        echo "✓ Access interactive terminal at: http://localhost:8088"
    else
        echo "WARNING: GoTTY did not start successfully"
    fi
else
    echo "GoTTY not available, skipping web terminal"
fi


# Ensure custom theme is in Jenkins userContent (survives persistent volumes)
if [ -f /opt/jenkins-theme/milady-theme.css ]; then
    mkdir -p /var/jenkins_home/userContent/theme
    cp /opt/jenkins-theme/milady-theme.css /var/jenkins_home/userContent/theme/milady-theme.css
    echo "✓ Milady theme installed to Jenkins userContent"
fi

# Start Jenkins in the foreground
# === Final: Jenkins (always starts) ===
echo "=== Starting Jenkins ==="
chown -R jenkins:jenkins /var/jenkins_home
if command -v gosu >/dev/null 2>&1; then
    exec gosu jenkins /usr/local/bin/jenkins.sh
elif [ "$(id -u)" -eq 0 ]; then
    exec su -s /bin/sh -c "/usr/local/bin/jenkins.sh" jenkins
else
    exec /usr/local/bin/jenkins.sh
fi
