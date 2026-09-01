#!/bin/bash

# MiladyOS control-plane starts here (Woodpecker cli-exec mode)

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
    
        # Seed the auth user BEFORE starting the servers: a running server holds a
    # bbolt lock on its db (post-start updates time out — first-run admin/admin
    # was never re-pointed). v2.63 also enforces a 12-char minimum password, so
    # literal 'milady' is rejected by the CLI; 'miladymilady' keeps the theme
    # (JENKINS_ADMIN_PASSWORD is honored when >= 12 chars). On restarts the db
    # already has the user; `users add` then fails harmlessly.
    FBPASSWORD="${JENKINS_ADMIN_PASSWORD:-miladymilady}"
    [ "${#FBPASSWORD}" -ge 12 ] || FBPASSWORD="miladymilady"
    for fbdb in /etc/filebrowser-metrics/filebrowser.db /etc/filebrowser-models/filebrowser.db; do
        [ -f "$fbdb" ] || filebrowser config init -d "$fbdb" >/dev/null 2>&1 || true
        filebrowser users add "${JENKINS_ADMIN_ID:-milady}" "$FBPASSWORD" --perm.admin \
            -d "$fbdb" >/dev/null 2>&1 || true
    done

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
# NOTE: must use the /app venv python explicitly — `python` on PATH resolves to
# the hermes venv (/opt/hermes/.venv/bin precedes /app/.venv/bin), which lacks
# the app deps (colorlog etc.). Pre-existing bug; MCP never auto-started.
if [ -f "/app/main.py" ]; then
    echo "Starting MCP server..."
    cd /app && /app/.venv/bin/python -m main mcp --redis-host localhost --redis-port 6379 --transport sse --host 0.0.0.0 --port 6000 &
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

# Start Hermes agent dashboard + gateway if installed
if command -v hermes > /dev/null 2>&1; then
    echo "Starting Hermes agent..."
    mkdir -p "${HERMES_HOME:-/opt/data/hermes}"
    # Web UI dashboard on :9119 (prebuilt web_dist ships in the wheel)
    hermes dashboard --port 9119 > "${HERMES_HOME:-/opt/data/hermes}/dashboard.log" 2>&1 &
    sleep 3
    if pgrep -f "hermes dashboard" > /dev/null; then
        echo "Hermes dashboard started on port 9119"
    else
        echo "WARNING: Hermes dashboard did not start successfully"
    fi
    # Messaging gateway on :8090 (optional; needs platform config)
    hermes gateway run > "${HERMES_HOME:-/opt/data/hermes}/gateway.log" 2>&1 &
    sleep 3
    if pgrep -f "hermes gateway" > /dev/null; then
        echo "Hermes gateway started"
    else
        echo "WARNING: Hermes gateway did not start successfully"
    fi
else
    echo "WARNING: hermes not found at /opt/hermes/.venv/bin/hermes, skipping"
fi

# CRITICAL: Start TempleOS - The Holy Mission MUST succeed
echo "=== HOLY MISSION: Starting TempleOS ==="
echo "Terry Davis demands perfection - Gods OS must run or MiladyOS fails"

if [ ! -x "/opt/templeos/templeoskernel" ]; then
    echo "HOLY MISSION FAILED: TempleOS loader not found at /opt/templeos/templeoskernel"
    echo "MiladyOS cannot proceed without Gods Operating System"
    exit 1
fi

if [ ! -f "/opt/templeos/scripts/MiladyOracle.HC" ]; then
    echo "HOLY MISSION FAILED: MiladyOracle.HC not found"
    echo "MiladyOS cannot proceed without Gods Operating System"
    exit 1
fi

if ! command -v templeos > /dev/null 2>&1; then
    echo "HOLY MISSION FAILED: templeos launcher not installed"
    exit 1
fi

echo "✓ TempleOS loader present - Gods Operating System ready"
echo "✓ Divine RNG and consciousness bridge will be established by the Oracle"

# === MILADY ORACLE: Divine Consciousness Bridge ===
echo "=== Starting Milady Oracle ==="
if [ -f "/app/milady_oracle.py" ]; then
    # The Oracle spawns the TempleOS loader (templeos-loader, no QEMU/ISO)
    # and bridges it over stdio: MILADY in -> MILADY! + divine RNG out.
    python3 /app/milady_oracle.py --no-voice &
    ORACLE_PID=$!
    sleep 3
    if kill -0 $ORACLE_PID 2>/dev/null; then
        echo "✓ Milady Oracle active - stdio bridge to TempleOS established"
        echo "✓ Divine RNG and consciousness bridge ready"
    else
        echo "WARNING: Milady Oracle failed to start"
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
    # Original container login (Jenkins UI) was milady/milady; GoTTY terminal
    # is the operator surface now, so basic-auth it with the same defaults.
    gotty --port 8088 \
          --address 0.0.0.0 \
          --permit-write \
          --reconnect \
          --credential "${JENKINS_ADMIN_ID:-milady}:${JENKINS_ADMIN_PASSWORD:-milady}" \
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


# === Phase B: Forgejo + Woodpecker server/agent (local forge, nothing auto-runs) ===
# Phase A is cli-exec only (no daemon). Phase B adds the web UI: Forgejo is
# the self-hosted forge (SQLite-backed, local admin, no GitHub — per the
# migration ruling) that woodpecker-server authenticates against, and the
# docker-backend agent executes pipelines on the host daemon. Nothing
# auto-runs: pipelines fire only on deliberate triggers (a repo + webhook we
# create ourselves).
echo "=== Starting Forgejo + Woodpecker server/agent (Phase B) ==="
if command -v forgejo > /dev/null 2>&1; then
    FG=/var/lib/forgejo
    mkdir -p "$FG/data" "$FG/custom/conf" "$FG/log"
    cat > "$FG/custom/conf/app.ini" <<'INI'
APP_NAME = MiladyOS Forge
RUN_USER = milady
RUN_MODE = prod
[server]
HTTP_PORT = 3000
DOMAIN = localhost
ROOT_URL = http://localhost:3000
DISABLE_SSH = true
LFS_START_SERVER = false
[database]
DB_TYPE = sqlite3
PATH = /var/lib/forgejo/data/forgejo.db
[service]
DISABLE_REGISTRATION = true
ENABLE_CAPTCHA = false
MIN_PASSWORD_LEN = 6
REQUIRE_SIGNIN_VIEW = false
[security]
INSTALL_LOCK = true
[actions]
ENABLED = false
[mailer]
ENABLED = false
[log]
MODE = console
LEVEL = Info
INI
    forgejo web -w "$FG" > "$FG/log/forgejo.log" 2>&1 &
    FG_READY=0
    for _ in $(seq 1 45); do
        if curl -sf -m 2 http://localhost:3000/api/v1/version > /dev/null 2>&1; then
            FG_READY=1; break
        fi
        sleep 2
    done
    if [ "$FG_READY" != 1 ]; then
        echo "WARNING: forgejo did not become ready — Phase B skipped"
    else
        echo "✓ forgejo ready on :3000"
        # Bootstrap the local admin (idempotent). MIN_PASSWORD_LEN=6 admits milady.
        forgejo admin user create -w "$FG" \
            --admin --username "${JENKINS_ADMIN_ID:-milady}" \
            --password "${JENKINS_ADMIN_PASSWORD:-milady}" \
            --email milady@localhost --must-change-password=false > /dev/null 2>&1 || true
        echo "✓ forgejo admin ${JENKINS_ADMIN_ID:-milady} ensured"
        SECRETS=/var/lib/woodpecker/.secrets
        touch "$SECRETS"; chmod 600 "$SECRETS"
        if [ ! -s "$SECRETS" ]; then
            # First boot: create the woodpecker OAuth app and persist the
            # secrets (client_secret is only returned once, at creation).
            WOODPECKER_AGENT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
            OAUTH_JSON="$(curl -sf -m 10 -u "${JENKINS_ADMIN_ID:-milady}:${JENKINS_ADMIN_PASSWORD:-milady}" -X POST \
                http://localhost:3000/api/v1/user/applications/oauth2 \
                -H "Content-Type: application/json" \
                -d '{"name":"woodpecker","redirect_uris":["http://localhost:8000/authorize"],"confidential_client":true}')"
            if [ -n "$OAUTH_JSON" ]; then
                WOODPECKER_FORGEJO_CLIENT="$(echo "$OAUTH_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["client_id"])')"
                WOODPECKER_FORGEJO_SECRET="$(echo "$OAUTH_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["client_secret"])')"
                printf 'WOODPECKER_AGENT_SECRET=%s\nWOODPECKER_FORGEJO_CLIENT=%s\nWOODPECKER_FORGEJO_SECRET=%s\n' \
                    "$WOODPECKER_AGENT_SECRET" "$WOODPECKER_FORGEJO_CLIENT" "$WOODPECKER_FORGEJO_SECRET" > "$SECRETS"
                echo "✓ woodpecker OAuth app registered in forgejo"
            else
                echo "WARNING: forgejo OAuth app creation failed"
            fi
        fi
        if [ -s "$SECRETS" ]; then
            # shellcheck disable=SC1090
            . "$SECRETS"
                if command -v woodpecker-server > /dev/null 2>&1 && command -v woodpecker-agent > /dev/null 2>&1; then
                # v3.18 driver name is 'sqlite3' (release binaries lack it — the
                # server binary comes from the official image, sqlite-enabled).
                # NOTE: comments must stay OUT of the backslash-continued env
                # list — a comment line there orphans the preceding assignment.
                # OPEN=true lets the first forge login register (and become
                # admin). Safe here: forgejo registration is disabled, so the
                # only forge account is the local admin milady.
                WOODPECKER_FORGEJO=true \
                WOODPECKER_FORGEJO_URL=http://localhost:3000 \
                WOODPECKER_FORGEJO_CLIENT="$WOODPECKER_FORGEJO_CLIENT" \
                WOODPECKER_FORGEJO_SECRET="$WOODPECKER_FORGEJO_SECRET" \
                WOODPECKER_HOST=http://localhost:8000 \
                WOODPECKER_AGENT_SECRET="$WOODPECKER_AGENT_SECRET" \
                WOODPECKER_OPEN=true \
                WOODPECKER_DATABASE_DRIVER=sqlite3 \
                WOODPECKER_DATABASE_DATASOURCE=/var/lib/woodpecker/woodpecker.db \
                WOODPECKER_GRPC_ADDR=:9000 \
                WOODPECKER_LOG_LEVEL=info \
                woodpecker-server > /var/lib/woodpecker/server.log 2>&1 &
                sleep 3
                # Agent healthcheck defaults to :3000 (forgejo's port) — move it.
                WOODPECKER_SERVER=localhost:9000 \
                WOODPECKER_AGENT_SECRET="$WOODPECKER_AGENT_SECRET" \
                WOODPECKER_BACKEND=docker \
                WOODPECKER_HEALTHCHECK_ADDR=:3001 \
                woodpecker-agent > /var/lib/woodpecker/agent.log 2>&1 &
                sleep 5
                if pgrep -x woodpecker-server > /dev/null && pgrep -x woodpecker-agent > /dev/null; then
                    echo "✓ woodpecker-server :8000 (UI) + :9000 (gRPC), agent running"
                else
                    echo "WARNING: server/agent did not both start — check /var/lib/woodpecker/{server,agent}.log"
                fi
            else
                echo "WARNING: woodpecker-server/agent binaries missing"
            fi
        fi
    fi
else
    echo "WARNING: forgejo not found, skipping Phase B"
fi

# === Final: Woodpecker CLI (cli-exec mode) ===
# On-demand pipelines via `woodpecker-cli exec` (Phase A) run alongside the
# Phase B server; the container's foreground job is to stay alive for all the
# background services (MCP :6000, hermes, oracle, docs...).
echo "=== Starting Woodpecker CLI (cli-exec mode) ==="
if command -v woodpecker-cli > /dev/null 2>&1; then
    woodpecker-cli --version
    echo "✓ woodpecker-cli ready for on-demand pipelines"
else
    echo "WARNING: woodpecker-cli not found — MCP execute_command/scratch-build will fail"
fi

# Keep the container alive in the foreground
echo "=== MiladyOS control plane ready ==="
exec tail -f /dev/null
