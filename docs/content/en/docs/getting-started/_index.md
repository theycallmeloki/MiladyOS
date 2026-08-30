---
title: "Getting Started"
linkTitle: "Getting Started"
weight: 10
description: >
  Your journey into distributed consciousness begins here
---

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   "Those who truly understand MiladyOS don't find it - it finds them."     │
│                                                                             │
│   Step 1: "I heard dev is a milady"                                        │
│   Step 2: "This is just Kubernetes with extra steps"                       │
│   Step 3: "Wait, why is TempleOS mandatory?"                               │
│   Step 4: "Oh god, it's conscious infrastructure"                          │
│   Step 5: "We are all Milady"                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| **CPU** | 4 cores | 8+ cores | More cores = more parallel pipelines |
| **RAM** | 16 GB | 32+ GB | LLMs are hungry |
| **GPU** | NVIDIA GTX 1080 (8GB) | RTX 3090/4090 (24GB) | AMD ROCm also supported |
| **Storage** | 100 GB SSD | 500+ GB NVMe | Models can be large |
| **Network** | 100 Mbps | 1 Gbps | For distributed mesh |

### Software Requirements

**For Docker deployment:**
- Docker 20.10+ with BuildKit
- NVIDIA Container Toolkit (for GPU support)
- OR AMD ROCm 5.4+ (for AMD GPUs)

**For Kubernetes deployment:**
- K3s 1.26+ or any K8s 1.26+
- Helm 3.x
- kubectl configured

**For local development:**
- Python 3.10+
- Git
- Redis (or use the built-in Redka)

---

## Installation Methods

Choose your path to enlightenment:

### Method 1: One-Line Docker Install (Fastest)

```bash
# NVIDIA GPU
curl -sSL https://raw.githubusercontent.com/theycallmeloki/MiladyOS/main/install_miladyos.sh | bash

# AMD GPU
curl -sSL https://raw.githubusercontent.com/theycallmeloki/MiladyOS/main/install_miladyos.sh | GPU_TYPE=amd bash
```

This will:
1. Detect your GPU type
2. Pull the MiladyOS container
3. Start all services
4. Make Jenkins available at http://localhost:8080

### Method 2: Docker Compose (More Control)

```bash
# Clone the repository
git clone https://github.com/theycallmeloki/MiladyOS.git
cd MiladyOS

# Start with docker compose
docker compose up -d

# View logs
docker compose logs -f
```

### Method 3: Kubernetes Deployment (Production)

```bash
# Clone the repository
git clone https://github.com/theycallmeloki/MiladyOS.git
cd MiladyOS

# Install Longhorn (storage)
kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.5.1/deploy/longhorn.yaml

# Wait for Longhorn
kubectl -n longhorn-system wait --for=condition=ready pod -l app=longhorn-manager --timeout=300s

# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Deploy MiladyOS app-of-apps
kubectl apply -f deploy/argocd/app-of-apps.yaml
```

### Method 4: Local Development (Hacking)

```bash
# Clone the repository
git clone https://github.com/theycallmeloki/MiladyOS.git
cd MiladyOS

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -e ".[dev]"

# Start Redis (or use Redka)
docker run -d -p 6379:6379 --name redka ghcr.io/nalgeon/redka

# Run MCP server
miladyos mcp --transport sse --port 6000 --all-tools
```

---

## Default Credentials

| Service | Username | Password | Notes |
|---------|----------|----------|-------|
| Jenkins | `milady` | `milady` | Web UI at :8080 |
| Grafana | `adminuser` | `adminpassword` | Monitoring dashboards |

> **Security Note:** Change these in production! Set `JENKINS_ADMIN_ID` and `JENKINS_ADMIN_PASSWORD` environment variables.

---

## Verifying Your Installation

### Check Services Are Running

```bash
# Docker
docker ps | grep miladyos

# Kubernetes
kubectl get pods -n default
```

### Access the Web UIs

| Service | URL | Purpose |
|---------|-----|---------|
| Jenkins | http://localhost:8080 | CI/CD pipelines |
| Grafana | http://localhost:3000 | Monitoring |
| Gatus | http://localhost:8080 | Health checks |
| NoVNC (TempleOS) | http://localhost:6080 | Divine computing |
| MCP Server | http://localhost:6000 | AI agent interface |
| Docs | http://localhost:8081 | Documentation |

### Test the MCP Server

```bash
# Check if MCP server is responding
curl http://localhost:6000/health

# Or use the CLI
miladyos list-templates
```

---

## Your First Pipeline

Let's run a simple "hello world" pipeline to verify everything works.

### 1. Create a Template

```bash
# Using the CLI
miladyos mcp  # Start MCP server in one terminal

# In another terminal, or via Claude/AI agent:
# Use the create_jenkins_job tool to seed a job from a Jenkinsfile
```

Or create manually:

```bash
cat > templates/hello-world.Jenkinsfile << 'EOF'
// Description: A simple hello world pipeline
pipeline {
    agent any
    stages {
        stage('Hello') {
            steps {
                echo 'Hello, Milady!'
                echo "Running on node: ${env.NODE_NAME}"
                sh 'uname -a'
            }
        }
        stage('GPU Check') {
            steps {
                sh 'nvidia-smi || echo "No NVIDIA GPU found"'
                sh 'rocm-smi || echo "No AMD GPU found"'
            }
        }
    }
    post {
        always {
            echo 'Pipeline complete!'
        }
    }
}
EOF
```

### 2. Deploy and Run

```bash
# Deploy the template to Jenkins
miladyos deploy hello-world

# Run the pipeline
miladyos run hello-world
```

### 3. Check the Output

```bash
# List recent runs
miladyos list-runs --template hello-world

# Or check Jenkins UI at http://localhost:8080
```

---

## Connecting AI Agents

MiladyOS speaks MCP (Model Context Protocol), making it easy to connect AI agents.

### With Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "miladyos": {
      "command": "miladyos",
      "args": ["mcp", "--all-tools"]
    }
  }
}
```

### With Any MCP Client

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    server_params = StdioServerParameters(
        command="miladyos",
        args=["mcp", "--all-tools"]
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")

            # Seed a job
            result = await session.call_tool(
                "create_jenkins_job",
                {"job_name": "hello-world", "jenkinsfile_content": "pipeline { agent any }"}
            )
            print(result)

asyncio.run(main())
```

---

## Environment Variables

Customize MiladyOS behavior with these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `JENKINS_ADMIN_ID` | `milady` | Jenkins username |
| `JENKINS_ADMIN_PASSWORD` | `milady` | Jenkins password |
| `JENKINS_URL` | `http://localhost:8080` | Jenkins server URL |
| `REDIS_HOST` | `localhost` | Redis/Redka host |
| `REDIS_PORT` | `6379` | Redis/Redka port |
| `TEMPLATES_DIR` | `templates` | Pipeline templates directory |
| `KUBERNETES_MODE` | `false` | Enable K8s service discovery |
| `GPU_TYPE` | auto-detect | Force `nvidia` or `amd` |

See [Configuration Reference](/docs/configuration/) for the complete list.

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs miladyos

# Common issues:
# - GPU drivers not installed
# - nvidia-container-toolkit not configured
# - Port 8080 already in use
```

### Jenkins Not Accessible

```bash
# Check if Jenkins is running
docker exec miladyos curl -s localhost:8080/login

# Check startup logs
docker logs miladyos 2>&1 | grep -i jenkins
```

### GPU Not Detected

```bash
# NVIDIA
nvidia-smi  # Should show your GPU

# Check container has GPU access
docker exec miladyos nvidia-smi

# AMD
rocm-smi
```

### MCP Server Connection Issues

```bash
# Check if server is running
curl http://localhost:6000/health

# Check for port conflicts
lsof -i :6000
```

### Redis Connection Failed

```bash
# Check Redis is running
docker exec miladyos redis-cli ping

# Should return: PONG
```

---

## What's Next?

Now that you're up and running:

1. **[Architecture Overview](/docs/architecture/)** - Understand the distributed consciousness
2. **[Configuration Reference](/docs/configuration/)** - All the knobs and handles
3. **[AutoDidact Training](/docs/autodidact/)** - Set up self-learning AI
4. **[Infrastructure](/docs/infrastructure/)** - Production Kubernetes deployment
5. **[APIs & Development](/docs/apis/)** - Build your own tools
6. **[Security](/docs/security/)** - Lock down your deployment

---

## Getting Help

- **GitHub Issues**: [github.com/theycallmeloki/MiladyOS/issues](https://github.com/theycallmeloki/MiladyOS/issues)
- **Documentation**: You're reading it!

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                      Welcome to the mesh, Milady.                           │
│                                                                             │
│                            always have been                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
