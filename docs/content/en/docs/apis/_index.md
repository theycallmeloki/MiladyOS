---
title: "APIs & Development"
linkTitle: "APIs"
weight: 70
description: >
  Complete API documentation, MCP tools reference, and integration guides
---

## API Overview

MiladyOS provides multiple API interfaces:

| Interface | Purpose | Transport |
|-----------|---------|-----------|
| **MCP Server** | AI agent tool calling | stdio / SSE |
| **REST API** | Display control, LLM proxy | HTTP |
| **WebSocket** | Real-time updates | WS |
| **gRPC** | High-performance inference | gRPC |

---

## Model Context Protocol (MCP)

The MCP server is the primary interface for AI agents (Claude, etc.) to interact with MiladyOS.

### Starting the MCP Server

```bash
# stdio transport (for Claude Desktop)
miladyos mcp

# SSE transport (for web clients)
miladyos mcp --transport sse --host 0.0.0.0 --port 6000

# With all tools enabled
miladyos mcp --all-tools
```

### Claude Desktop Configuration

Add to your Claude Desktop config (`~/.config/claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "miladyos": {
      "command": "python",
      "args": ["-m", "miladyos_mcp"],
      "cwd": "/path/to/MiladyOS"
    }
  }
}
```

---

## MCP Tools Reference

MiladyOS exposes **7 MCP tools**:

### Pipeline Tools

#### hello_world

Test connectivity to MiladyOS.

```json
// Request
{}

// Response
{
  "success": true,
  "message": "milady!",
  "status": "success"
}
```

---

#### execute_command

Execute arbitrary CLI commands (with session tracking).

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | Command to execute |
| `working_directory` | string | No | Working directory (default: /workspace) |
| `session_id` | string | No | Session ID for tracking |

```json
// Request
{
  "command": "ls -la /workspace",
  "working_directory": "/workspace"
}

// Response
{
  "success": true,
  "command": "ls -la /workspace",
  "output": "total 48\ndrwxr-xr-x ...",
  "exit_code": 0,
  "session_id": "sess-abc123"
}
```

---

#### create_pipeline

Create a pipeline repo from `.woodpecker.yml` content.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo_name` | string | Yes | Name of the pipeline repo to create |
| `pipeline_content` | string | Yes | Full `.woodpecker.yml` pipeline content |


```json
// Request
{
  "job_name": "youtube-dl",
  "pipeline_content": "when:\n  event: manual\nsteps:\n  hi:\n    image: alpine:3.20\n    commands:\n      - echo hi"
}

// Response
{
  "success": true,
  "message": "Job youtube-dl created successfully"
}
```

---

#### evolve_template

Start evolutionary optimization of a Woodpecker CI pipeline.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `template_name` | string | Yes | - | Template to evolve |
| `goal` | string | Yes | - | Optimization goal |
| `max_generations` | integer | No | 50 | Max evolution generations |
| `population_size` | integer | No | 20 | Population size |
| `run_async` | boolean | No | true | Run in background |

**Available Goals:**
- `speed` - Optimize execution time
- `reliability` - Improve success rate
- `resources` - Optimize resource usage
- `security` - Enhance security practices
- `observability` - Improve logging/metrics

```json
// Request
{
  "template_name": "example-build",
  "goal": "speed",
  "max_generations": 100
}

// Response
{
  "success": true,
  "evolution_id": "evo-abc123",
  "template_name": "example-build",
  "goal": "speed",
  "status": "started",
  "message": "Evolution started in background. Use evolution_status to check progress."
}
```

---

#### evolution_status

Check status of running/completed evolution.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `evolution_id` | string | Yes | Evolution to check |

```json
// Response (running)
{
  "success": true,
  "evolution_id": "evo-abc123",
  "status": "running",
  "template_name": "example-build",
  "goal": "speed",
  "generation": 15,
  "best_fitness": 0.72
}

// Response (completed)
{
  "success": true,
  "evolution_id": "evo-abc123",
  "status": "completed",
  "generations": 47,
  "best_fitness": 0.8234,
  "output_path": "evolved_templates/example-build_evolved_speed_20240115.yml"
}
```

---

#### list_evolution_goals

List all available optimization goals with descriptions.

```json
// Response
{
  "success": true,
  "goals": [
    {
      "name": "speed",
      "description": "Optimize for faster execution time",
      "fitness_weights": {
        "duration_seconds": -1.0,
        "success_rate": 0.3,
        "parallelism_score": 0.5
      },
      "optimization_hints": [
        "Add parallel execution where stages are independent",
        "Use shallow git clones (depth: 1)",
        "Implement caching for dependencies"
      ]
    }
  ],
  "count": 5
}
```

---

#### list_evolved_templates

List all evolved template versions.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `template_name` | string | No | Filter by original template |

```json
// Response
{
  "success": true,
  "templates": [
    {
      "filename": "example-build_evolved_speed_20240115_143022.yml",
      "original_template": "example-build",
      "path": "evolved_templates/...",
      "metadata": {
        "evolution_id": "evo-abc123",
        "goal": "speed",
        "generations": "47",
        "fitness": "0.8234"
      }
    }
  ],
  "count": 3
}
```

---

## REST APIs

### Display Control API

**Base URL**: `http://display-api:8000`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/displays` | GET | List all displays |
| `/api/v1/displays/{id}/configure` | POST | Configure display |
| `/api/v1/displays/{id}/status` | GET | Get display status |
| `/api/v1/displays/{id}/screenshot` | POST | Capture screenshot |

```bash
# List displays
curl -X GET "http://display-api:8000/api/v1/displays" \
  -H "Authorization: Bearer <token>"

# Take screenshot
curl -X POST "http://display-api:8000/api/v1/displays/main/screenshot" \
  -H "Authorization: Bearer <token>"
```

### LiteLLM Proxy

**Base URL**: `http://litellm-proxy:4000`

Unified OpenAI-compatible API for all models.

```python
import openai

client = openai.OpenAI(
    base_url="http://litellm-proxy:4000/v1",
    api_key="your-api-key"
)

# Chat completion
response = client.chat.completions.create(
    model="mistral-7b",  # or "qwq-32b-awq", "deep-coder-14b-awq"
    messages=[{"role": "user", "content": "Hello MiladyOS!"}]
)

# Streaming
stream = client.chat.completions.create(
    model="mistral-7b",
    messages=[{"role": "user", "content": "Explain Kubernetes"}],
    stream=True
)

for chunk in stream:
    print(chunk.choices[0].delta.content, end="")
```

**Available Models:**

| Model | Endpoint | Use Case |
|-------|----------|----------|
| `mistral-7b` | Mistral-7B-Instruct | General chat |
| `qwq-32b-awq` | QwQ-32B quantized | Reasoning |
| `deep-coder-14b-awq` | DeepSeek Coder | Code generation |

---

## WebSocket APIs

### Real-time Updates

Connect to `ws://miladyos-api:8000/ws` for live updates.

```javascript
const ws = new WebSocket('ws://miladyos-api:8000/ws');

ws.onopen = () => {
  // Subscribe to channels
  ws.send(JSON.stringify({
    type: 'subscribe',
    channels: ['training_progress', 'pipeline_status', 'system_metrics']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.channel) {
    case 'training_progress':
      console.log(`Training: ${data.progress}%`);
      break;
    case 'pipeline_status':
      console.log(`Pipeline ${data.job}: ${data.status}`);
      break;
    case 'system_metrics':
      console.log(`CPU: ${data.cpu}%, Memory: ${data.memory}%`);
      break;
  }
};
```

---

## Authentication

### API Key

```http
Authorization: Bearer sk-miladyos-1234567890abcdef
```

### Service Account Token (Kubernetes)

```bash
kubectl -n miladyos get secret miladyos-api-token \
  -o jsonpath='{.data.token}' | base64 -d
```

### NFT-Based Authentication

```python
from web3 import Web3

# Connect to NFT auth service
auth_response = requests.post(
    "http://nft-auth:8080/authenticate",
    json={
        "wallet_address": "0x1234...",
        "signature": signed_message,
        "contract": "0xf01B34d9418874258B35b0507AB53ED971CBB8D3"  # High Integrity Milady
    }
)

token = auth_response.json()["token"]
```

---

## Error Handling

### Standard Error Response

```json
{
  "success": false,
  "error": "Invalid template name",
  "status": "error",
  "tool": "view_template",
  "additional_info": {
    "template_name": "nonexistent",
    "available_templates": ["example-build", "docker-deploy"]
  }
}
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Invalid request parameters |
| 401 | Authentication required |
| 403 | Access denied (NFT auth failed) |
| 404 | Resource not found |
| 429 | Rate limited |
| 500 | Internal server error |

---

## Rate Limiting

| Resource | Limit |
|----------|-------|
| API Requests | 1000/hour per key |
| Model Inference | 100/minute per model |
| WebSocket Connections | 10 concurrent |
| Evolution Jobs | 5 concurrent |

Response headers:
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1640995200
```

---

## Development Setup

### Local Development

```bash
# Clone
git clone https://github.com/theycallmeloki/MiladyOS.git
cd MiladyOS

# Install with uv
uv sync

# Or pip
pip install -e .

# Configure
cp .env.example .env
# Edit .env with your settings

# Run MCP server
miladyos mcp --all-tools
```

### Docker Development

```bash
# Build
docker build -t miladyos:dev .

# Run with development settings
docker run -it --rm \
  -v $(pwd):/app \
  -p 6000:6000 \
  -e REDIS_HOST=host.docker.internal \
  miladyos:dev mcp --transport sse
```

### Testing Tools

```bash
# Test MCP server with mcp-cli
npx @anthropics/mcp-cli stdio python -m miladyos_mcp

# List available tools
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python -m miladyos_mcp
```
