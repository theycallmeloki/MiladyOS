---
title: "Configuration Reference"
linkTitle: "Configuration"
weight: 3
description: >
  Complete reference for all MiladyOS configuration options, environment variables, CLI flags, and config files.
---

This reference documents all configurable parameters in MiladyOS. Understanding these options allows you to customize deployments for your specific hardware, network, and operational requirements.

## Quick Reference

| Category | Primary Config | Key Variables |
|----------|---------------|---------------|
| [Core Runtime](#core-runtime) | Environment | `KUBERNETES_MODE`, `REDIS_HOST`, `REDIS_PORT` |
| [MCP Server](#mcp-server-cli) | CLI flags | `--transport`, `--port`, `--all-tools` |
| [Environment](#environment) | startup.sh | `MILADY_ADMIN_ID`, `MILADY_ADMIN_PASSWORD` |
| [GPU Support](#gpu-configuration) | Environment | `GPU_TYPE`, `CUDA_VISIBLE_DEVICES` |
| [Networking](#networking) | `config.yaml` | Nebula VPN, Headscale/Tailscale |
| [LLM Serving](#llm-configuration) | ConfigMap | LiteLLM proxy, vLLM settings |
| [AlphaEvolve](#alphaevolve-configuration) | `evolve_default.yaml` | Evolution parameters, LLM models |
| [Monitoring](#monitoring-configuration) | ConfigMap | Gatus, Prometheus exporters |
| [Authentication](#authentication) | Environment | NFT auth service settings |

---

## Core Runtime

These environment variables control the core MiladyOS runtime behavior.

### Runtime Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `KUBERNETES_MODE` | `false` | Set to `true` when running inside Kubernetes. Adjusts service discovery and Redis host defaults. |
| `DISABLE_DOCKER` | `false` | Set to `true` to skip Docker daemon initialization. Useful in K8s environments. |
| `USE_KUBECTL` | Auto-detected | Automatically set when kubectl is available. Forces Kubernetes-based container operations. |

### Redis/Cache Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` (standalone) / `redka` (K8s) | Hostname of the Redis-compatible cache server. |
| `REDIS_PORT` | `6379` | Port for Redis connections. |

### Storage Paths

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPLATES_DIR` | `templates` | Directory containing Woodpecker pipeline templates (`.yml` files). |
| `METADATA_DIR` | `metadata` | Directory for storing pipeline metadata and execution history. |
| `SQLITE_DB_PATH` | `/data/redka/data.db` | Path to SQLite database for metadata storage. |

---

## MCP Server CLI

The MiladyOS MCP (Model Context Protocol) server provides tool interfaces for AI agents.

### Command: `miladyos mcp`

```bash
miladyos mcp [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--all-tools` | `false` | Load all available tools instead of the default minimal set. |
| `--templates-dir` | `templates` | Directory containing pipeline templates. |
| `--metadata-dir` | `metadata` | Directory to store metadata files. |
| `--redis-host` | `localhost` | Redis server hostname. |
| `--redis-port` | `6379` | Redis server port. |
| `--transport` | `stdio` | Transport protocol: `stdio` or `sse`. |
| `--host` | `0.0.0.0` | Bind address (only with `sse` transport). |
| `--port` | `6000` | Server port (only with `sse` transport). |
| `--base-path` | `""` | Base URL path for SSE transport. |
| `--sqlite-db-path` | `/data/redka/data.db` | Path to SQLite database file. |

**Example - Start MCP server with SSE transport:**
```bash
miladyos mcp --transport sse --host 0.0.0.0 --port 6000 --all-tools
```

### Command: `miladyos deploy`

Deploy a pipeline template as a woodpecker pipeline repo.

```bash
miladyos deploy TEMPLATE_NAME [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--job-name` | Template name | Optional pipeline repo name. |


### Command: `miladyos run`

Run a pipeline template on the local woodpecker agent.

```bash
miladyos run TEMPLATE_NAME [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--job-name` | Template name | Optional pipeline repo name. |

| `--no-stream` | `false` | Don't stream console output (return immediately). |

### Command: `miladyos list-templates`

List all available pipeline templates.

```bash
miladyos list-templates
```

### Command: `miladyos list-runs`

List pipeline execution history.

```bash
miladyos list-runs [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--template` | None | Filter by template name. |
| `--limit` | `10` | Maximum number of runs to show. |
| `--status` | None | Filter by status: `running`, `complete`, or `failed`. |

---

## Runtime Credentials

The container admin credential is `milady` / `milady` by default, overridable via the environment.

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `MILADY_ADMIN_ID` | `milady` | Admin username. |
| `MILADY_ADMIN_PASSWORD` | `milady` | Admin password. |
| `API_TOKEN` | None | Optional API token for programmatic access. |

### Pipeline Runtime

Pipelines run on the local Woodpecker agent (docker backend). Runtime
configuration lives in `startup.sh` (secrets persisted to
`/var/lib/woodpecker/.secrets`); the admin credential defaults are
`MILADY_ADMIN_ID` / `MILADY_ADMIN_PASSWORD` (defaults `milady`/`milady`).

```text
Woodpecker server  :8000 (UI) / :9000 (gRPC)   — woodpecker.db (sqlite3)
Woodpecker agent   docker backend, health :3001
Forgejo            :3000 (repo + auth backing the pipelines)
API token          WOODPECKER_TOKEN in .secrets (token dance at boot)
```

### Global Environment Variables

These can be set in `casc.yaml` under `globalNodeProperties.envVars`:

| Variable | Description |
|----------|-------------|
| `SLACK_API_KEY` | Slack integration for build notifications. |
| `GITHUB_TOKEN` | GitHub API token for repository access. |
| `CONTAINER_REGISTRY` | Default container registry URL. |
| `DOCKERHUB_USERNAME` | DockerHub credentials for image pulls/pushes. |
| `DOCKERHUB_PASSWORD` | DockerHub password. |
| `PUSHBULLET_API_KEY` | Pushbullet notifications. |

### Java Options

| Variable | Default | Description |
|----------|---------|-------------|
| `JAVA_OPTS` | | JVM options (legacy, unused). |
| `WOODPECKER_CUSTOM_CSS_FILE` | `/etc/woodpecker/custom.css` | UI branding stylesheet. |

---

## GPU Configuration

MiladyOS supports both NVIDIA and AMD GPUs for AI workloads.

### GPU Detection

| Variable | Default | Description |
|----------|---------|-------------|
| `GPU_TYPE` | Auto-detected | Force GPU type: `nvidia` or `amd`. Auto-detected via `nvidia-smi` or `rocm-smi`. |

### NVIDIA Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CUDA_HOME` | `/usr/local/cuda-11.8` | CUDA toolkit installation path. |
| `CUDA_ARCHS` | `86;80;75;61` | Target GPU architectures (SM versions). |
| `CUDACXX` | `${CUDA_HOME}/bin/nvcc` | CUDA compiler path. |
| `NVCC_FLAGS` | `-allow-unsupported-compiler` | Additional NVCC compiler flags. |
| `NVIDIA_VISIBLE_DEVICES` | `all` | GPUs visible to containers. |
| `CUDA_VISIBLE_DEVICES` | All available | Specific GPU indices (e.g., `0,1`). |

**Supported CUDA Architectures:**
- `61` - Pascal (P40, GTX 1080)
- `75` - Turing (RTX 2080, T4)
- `80` - Ampere (A100)
- `86` - Ampere (RTX 3090, A40)

### AMD Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `HSA_OVERRIDE_GFX_VERSION` | `10.3.0` | Override GFX version for ROCm compatibility. |
| `PATH` | Includes `/opt/rocm/bin` | ROCm binaries path. |

**Supported ROCm Architectures:**
- `gfx900` - Vega 10
- `gfx906` - Vega 20 (MI50)
- `gfx908` - CDNA (MI100)
- `gfx1030` - RDNA 2

---

## Networking

### Nebula VPN Configuration

Nebula provides the overlay network for decentralized node discovery.

**Config file:** `/etc/nebula/config.yaml`

```yaml
pki:
  ca: /etc/nebula/ca.crt           # Certificate authority
  cert: /etc/nebula/miladyos.crt   # Node certificate
  key: /etc/nebula/miladyos.key    # Node private key

static_host_map:
  "192.168.5.1": ["<lighthouse-public-ip>:4242"]  # Lighthouse mapping

lighthouse:
  am_lighthouse: false    # Set true for lighthouse nodes
  interval: 60           # Lighthouse query interval (seconds)
  hosts:
    - "192.168.5.1"      # Lighthouse Nebula IP

listen:
  host: 0.0.0.0
  port: 4242             # UDP port for Nebula traffic

punchy:
  punch: true            # Enable NAT hole punching

tun:
  disabled: false
  dev: nebula1           # TUN device name
  drop_local_broadcast: false
  drop_multicast: false
  tx_queue: 500
  mtu: 1300              # MTU for Nebula interface

logging:
  level: info            # debug, info, warn, error
  format: text           # text or json

firewall:
  outbound:
    - port: any
      proto: any
      host: any
  inbound:
    - port: any
      proto: any
      host: any
```

### Headscale Configuration

Headscale provides WireGuard-based VPN as a Tailscale control server.

**Config file:** `/etc/headscale/config.yaml`

```yaml
server_url: https://headscale.example.com
listen_addr: 0.0.0.0:8080
grpc_listen_addr: 0.0.0.0:50443

db_type: sqlite3
db_path: /var/lib/headscale/db.sqlite

dns_config:
  magic_dns: true
  base_domain: headscale.internal
  nameservers:
    - 1.1.1.1
    - 8.8.8.8
```

### IP Range Discovery

| Variable | Default | Description |
|----------|---------|-------------|
| `IP_RANGE` | `192\.168\.` | Regex pattern for host IP discovery. Used by startup scripts to find the host's local IP. |

---

## LLM Configuration

### LiteLLM Proxy

The LiteLLM proxy routes requests to multiple LLM backends.

**Environment Variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_CONFIG_PATH` | `/etc/litellm/config.yaml` | Path to LiteLLM configuration. |
| `PORT` | `4000` | LiteLLM proxy port. |
| `LITELLM_LOAD_MODEL_CONFIG_AT_START` | `True` | Load model config on startup. |
| `STORE_MODEL_IN_DB` | `True` | Persist model config to database. |

**ConfigMap (`litellm-config.yaml`):**

```yaml
model_list:
  - model_name: "deepseek-r1:1.5b"
    litellm_params:
      model: "ollama/deepseek-r1:1.5b"
      api_base: "http://miladyos.default.svc.cluster.local:11434/v1"
      api_key: "not-needed"
    model_info:
      description: "DeepSeek-R1 1.5B - Lightweight reasoning model"

  - model_name: "Qwen/QwQ-32B-AWQ"
    litellm_params:
      model: "openai/Qwen/QwQ-32B-AWQ"
      api_base: "http://qwq-32b-svc.default.svc.cluster.local:8000/v1"
      api_key: "sk-fake"
    model_info:
      description: "QwQ 32B - High-performance language model"

litellm_settings:
  drop_params: true      # Drop unsupported parameters
  verbose: true          # Verbose logging
  telemetry: false       # Disable telemetry

router_settings:
  num_retries: 3         # Retry failed requests
  timeout: 600           # Request timeout (seconds)
  default_model: "Qwen/QwQ-32B-AWQ"
```

### vLLM Settings

vLLM serves individual models with these common options:

| Parameter | Example | Description |
|-----------|---------|-------------|
| `--model` | `Qwen/QwQ-32B-AWQ` | HuggingFace model ID. |
| `--max-model-len` | `8192` | Maximum context length. |
| `--gpu-memory-utilization` | `0.85` | GPU memory fraction to use. |
| `--max-num-batched-tokens` | `1024` | Max tokens per batch. |
| `--enable-chunked-prefill` | - | Enable chunked prefill for lower latency. |
| `--dtype` | `auto` | Model precision (`auto`, `float16`, `bfloat16`). |

**Environment for vLLM:**

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_LOGGING_LEVEL` | `DEBUG` | Logging verbosity. |
| `HF_HOME` | `/root/.cache/huggingface` | HuggingFace cache directory. |
| `HUGGING_FACE_HUB_TOKEN` | None | Token for gated model access. |

### Ollama Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `0.0.0.0` | Bind address for Ollama server. |

Ollama runs on port `11434` by default.

---

## AlphaEvolve Configuration

AlphaEvolve evolutionary optimization is configured via `configs/evolve_default.yaml`.

### LLM Settings

```yaml
llm:
  # Primary model for high-quality mutations
  primary:
    model: "ollama/deepseek-r1:14b"
    api_base: "http://localhost:11434/v1"
    temperature: 0.8
    max_tokens: 4096

  # Secondary model for rapid iteration
  secondary:
    model: "ollama/qwen2.5-coder:7b"
    api_base: "http://localhost:11434/v1"
    temperature: 0.9
    max_tokens: 2048

  # LiteLLM proxy (recommended)
  proxy:
    enabled: true
    api_base: "http://localhost:4000/v1"
```

### Evolution Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `population_size` | 20 | Total candidates per generation |
| `num_islands` | 4 | Isolated populations (prevents premature convergence) |
| `migration_interval` | 5 | Generations between island migrations |
| `migration_size` | 2 | Candidates migrated per interval |
| `tournament_size` | 3 | Selection tournament size |
| `elite_ratio` | 0.2 | Fraction of population preserved each generation |
| `mutation_rate` | 0.4 | Probability of LLM mutation vs crossover |
| `crossover_rate` | 0.6 | Probability of parent crossover |
| `max_generations` | 100 | Maximum evolution iterations |
| `stagnation_limit` | 15 | Generations without improvement before stopping |
| `target_fitness` | 0.95 | Early termination fitness threshold |
| `seed` | 42 | Random seed for reproducibility |

```yaml
evolution:
  population_size: 20
  num_islands: 4
  migration_interval: 5
  migration_size: 2
  tournament_size: 3
  elite_ratio: 0.2
  mutation_rate: 0.4
  crossover_rate: 0.6
  max_generations: 100
  stagnation_limit: 15
  target_fitness: 0.95
  seed: 42
```

### MAP-Elites Quality-Diversity

```yaml
map_elites:
  enabled: true
  grid_resolution: 20
  feature_dimensions:
    - name: "execution_speed"
      min: 0.0
      max: 1.0
    - name: "reliability"
      min: 0.0
      max: 1.0
    - name: "resource_efficiency"
      min: 0.0
      max: 1.0
```

### Evaluator Cascade

```yaml
evaluator:
  cascade:
    - name: "syntax"
      timeout: 5        # seconds
      weight: 0.1
    - name: "dry_run"
      timeout: 30
      weight: 0.2
    - name: "execution"
      timeout: 300
      weight: 0.7

  # Enable live execution on the local agent (expensive)
  live_execution: false

  metrics:
    - "duration_seconds"
    - "success_rate"
    - "resource_usage"
    - "error_count"
    - "warning_count"
```

### Woodpecker Runner

The evolution machinery runs candidates on the local Woodpecker agent
(`milady/evolve` repo) via `WoodpeckerClient.run_content`; execution is
enabled with `evaluator.live_execution: true`.
```

### Storage

```yaml
storage:
  redis:
    url: "${REDIS_URL:-redis://localhost:6379}"
    prefix: "miladyos:evolve:"
    ttl: 86400  # 24 hours

  backup_dir: "evolved_templates"
  keep_generations: 10
```

### Evolution Goals

Five pre-configured optimization goals:

| Goal | Primary Metrics | Description |
|------|-----------------|-------------|
| `speed` | duration_seconds, parallelism_score | Optimize execution time |
| `reliability` | success_rate, error_handling_score | Improve success rate |
| `resources` | resource_efficiency, cleanup_score | Optimize resource usage |
| `security` | security_score, secrets_handling | Enhance security practices |
| `observability` | logging_score, notification_score | Improve monitoring |

---

## Monitoring Configuration

### Gatus Health Checks

**ConfigMap (`gatus-configmap.yaml`):**

```yaml
web:
  port: 8080

metrics: true              # Enable Prometheus metrics

storage:
  path: /data/gatus.db
  type: sqlite

endpoints:
  - name: Grafana
    group: Monitoring
    url: https://grafana.miladyos.net
    interval: 1m           # Check interval
    conditions:
      - "[STATUS] == 200"
      - "[RESPONSE_TIME] < 2000"
    alerts:
      - type: pagerduty
        enabled: false
        send-on-resolved: true
```

### Filebrowser Instances

| Instance | Port | Root Path | Description |
|----------|------|-----------|-------------|
| Metrics Browser | `7331` | `/metrics` | Browse collected metrics data. |
| Models Browser | `1337` | `/models` | Browse downloaded AI models. |

### Wiz Exporter (IoT Monitoring)

| Variable | Default | Description |
|----------|---------|-------------|
| `HASS_URL` | `http://localhost:8123` | Home Assistant URL. |
| `HASS_TOKEN` | None | Home Assistant API token. |
| `EXPORTER_PORT` | `9678` | Prometheus exporter port. |
| `POLL_INTERVAL` | `60` | Polling interval (seconds). |
| `LOG_LEVEL` | `1` | Logging verbosity. |
| `ENTITY_PATTERNS` | `wiz,socket,plug` | Entity name patterns to monitor. |
| `POWER_PATTERNS` | `power,energy,consumption` | Power metric patterns. |

---

## Authentication

### NFT Authentication Service

MiladyOS supports NFT-based authentication via the High Integrity Milady contract.

| Variable | Default | Description |
|----------|---------|-------------|
| `ETHEREUM_RPC_URL` | `https://ethereum-rpc.publicnode.com` | Ethereum RPC endpoint. |
| `REDIS_HOST` | `localhost` | Redis host for session storage. |
| `REDIS_PORT` | `6379` | Redis port. |
| `SECRET_KEY` | `your-secret-key-here` | Secret for admin endpoints. **Change in production!** |
| `SERVICE_PORT` | `8080` | NFT auth service port. |

**Contract Address:** `0xf01B34d9418874258B35b0507AB53ED971CBB8D3` (High Integrity Milady)

---

## Display Control

The Display Control system manages remote displays via WebSocket.

### Display Client

| Variable | Default | Description |
|----------|---------|-------------|
| `DISPLAY_ID` | `:0` | X11 display identifier. |
| `DEFAULT_URL` | `https://grafana.miladyos.net` | Initial URL to load. |
| `CONTROL_API` | `http://control-api:8000` | Control API endpoint. |
| `BALENA_DEVICE_UUID` | `unknown` | Device UUID (Balena deployments). |
| `BALENA_DEVICE_NAME` | `device-{display}` | Device name. |
| `DETECTED_RESOLUTION` | Auto-detected | Display resolution. |

### Screenshot Client CLI

```bash
python screenshot_client.py [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--api` | `http://localhost:8000` | API base URL. |
| `--display` | `device-0-display` | Display name. |
| `--quality` | `80` | JPEG quality (1-100). |
| `--full` | `false` | Capture full page. |
| `--output` | Auto-generated | Output file path. |

---

## Kubernetes Resources

### Resource Requests/Limits

Typical resource specifications for GPU workloads:

```yaml
resources:
  requests:
    cpu: "4"
    memory: "8Gi"
    nvidia.com/gpu: "1"
  limits:
    cpu: "8"
    memory: "16Gi"
    nvidia.com/gpu: "1"
```

### Storage Classes

| Storage Class | Description |
|--------------|-------------|
| `longhorn` | Default persistent storage with 3-way replication. |

### ArgoCD Settings

```yaml
server:
  replicas: 2
  resources:
    requests: {cpu: 200m, memory: 512Mi}
    limits: {cpu: 1000m, memory: 2Gi}

controller:
  replicas: 2
  resources:
    requests: {cpu: 500m, memory: 1Gi}
    limits: {cpu: 2000m, memory: 4Gi}
```

---

## Service Ports Reference

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| Woodpecker | 8000 | HTTP | CI/CD web interface |
| MCP Server | 6000 | HTTP/SSE | Model Context Protocol |
| Ollama | 11434 | HTTP | Local LLM inference |
| LiteLLM Proxy | 4000 | HTTP | LLM routing proxy |
| Redka/Redis | 6379 | TCP | Cache/KV store |
| Nebula | 4242 | UDP | VPN overlay |
| Headscale | 8080/50443 | HTTP/gRPC | VPN control |
| Gatus | 8080 | HTTP | Health monitoring |
| TempleOS (loader) | stdio | pipes | Divine computing (templeos-loader) |
| Filebrowser (metrics) | 7331 | HTTP | Metrics file browser |
| Filebrowser (models) | 1337 | HTTP | Models file browser |
| Docs Server | 8081 | HTTP | Documentation |
| NFT Auth | 8080 | HTTP | Authentication service |
| Display Control API | 8000 | HTTP/WS | Display management |

---

## Configuration Files Summary

| File | Location | Purpose |
|------|----------|---------|
| `startup.sh` | `/startup.sh` | Boot: forge/woodpecker/token-dance orchestration |
| `config.yaml` | `/etc/nebula/config.yaml` | Nebula VPN configuration |
| `config.yaml` | `/etc/headscale/config.yaml` | Headscale VPN configuration |
| `Caddyfile` | `/etc/caddy/Caddyfile` | Caddy reverse proxy |
| `config.yaml` | `/etc/litellm/config.yaml` | LiteLLM proxy models |
| `config.yaml` | Gatus ConfigMap | Health check endpoints |

---

## Next Steps

- [Getting Started](/docs/getting-started/) - Install and run MiladyOS
- [Architecture](/docs/architecture/) - Understand system components
- [Operations](/docs/operations/) - Day-2 operational procedures
