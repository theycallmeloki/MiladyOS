---
title: "CLI Reference"
linkTitle: "CLI Reference"
weight: 15
description: >
  Complete command-line interface reference for MiladyOS
---

## Overview

MiladyOS provides a command-line interface for managing pipelines, running the MCP server, and performing evolution operations.

```bash
# Main entry point
miladyos [command] [options]

# Or run directly
python main.py [command] [options]
```

---

## Core Commands

### mcp

Start the MCP (Model Context Protocol) server for AI agent integration.

```bash
miladyos mcp [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--transport` | choice | stdio | Transport mode: `stdio` or `sse` |
| `--host` | string | 0.0.0.0 | Host to bind (SSE mode) |
| `--port` | int | 6000 | Port to listen on (SSE mode) |
| `--all-tools` | flag | false | Load all available tools |
| `--templates-dir` | path | templates | Templates directory |
| `--metadata-dir` | path | metadata | Metadata directory |
| `--redis-host` | string | localhost | Redis host |
| `--redis-port` | int | 6379 | Redis port |
| `--sqlite-db-path` | path | /data/redka/data.db | SQLite database path |

**Examples:**

```bash
# Run for Claude Desktop (stdio transport)
miladyos mcp

# Run as HTTP server (SSE transport)
miladyos mcp --transport sse --host 0.0.0.0 --port 6000

# Load all tools with custom templates directory
miladyos mcp --all-tools --templates-dir /custom/templates

# Connect to remote Redis
miladyos mcp --redis-host redis.example.com --redis-port 6379
```

---

### deploy

Deploy a pipeline template to Jenkins.

```bash
miladyos deploy [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template` | string | required | Template name to deploy |
| `--job-name` | string | template name | Jenkins job name |
| `--server` | string | default | Jenkins server configuration |
| `--templates-dir` | path | templates | Templates directory |

**Examples:**

```bash
# Deploy template with same job name
miladyos deploy --template example-build

# Deploy with custom job name
miladyos deploy --template docker-deploy --job-name production-deploy

# Deploy to specific Jenkins server
miladyos deploy --template my-pipeline --server staging-jenkins
```

---

### run

Execute a deployed pipeline and optionally stream output.

```bash
miladyos run [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--job-name` | string | required | Jenkins job to run |
| `--parameters` | JSON | {} | Build parameters as JSON |
| `--server` | string | default | Jenkins server |
| `--no-stream` | flag | false | Disable output streaming |
| `--wait` | flag | false | Wait for completion |

**Examples:**

```bash
# Run job and stream output
miladyos run --job-name example-build

# Run with parameters
miladyos run --job-name my-deploy --parameters '{"BRANCH": "main", "ENV": "staging"}'

# Run without streaming, just trigger
miladyos run --job-name background-job --no-stream

# Run and wait for completion
miladyos run --job-name ci-pipeline --wait
```

---

### list-templates

List all available pipeline templates.

```bash
miladyos list-templates [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--templates-dir` | path | templates | Templates directory |
| `--verbose` | flag | false | Show template descriptions |

**Examples:**

```bash
# List all templates
miladyos list-templates

# List with descriptions
miladyos list-templates --verbose

# List from custom directory
miladyos list-templates --templates-dir /custom/templates
```

**Output:**
```
Available Templates:
  example-build         Example build pipeline that can be evolved
  docker-deploy         Docker image build and deployment
  talos-cluster-bootstrap  Bootstrap a Talos Kubernetes cluster
  talos-add-worker      Add worker nodes to Talos cluster
  miladyos-stack-deploy Deploy the MiladyOS stack
```

---

### view-template

View a template's content with line numbers.

```bash
miladyos view-template [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template` | string | required | Template name to view |
| `--templates-dir` | path | templates | Templates directory |

**Examples:**

```bash
# View template
miladyos view-template --template example-build
```

**Output:**
```
   1 | // Jenkinsfile for example-build
   2 | // Description: Example build pipeline that can be evolved
   3 | pipeline {
   4 |     agent any
   5 |
   6 |     environment {
   7 |         NODE_VERSION = '18'
   ...
```

---

### list-runs

Show pipeline execution history.

```bash
miladyos list-runs [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template` | string | - | Filter by template name |
| `--status` | choice | - | Filter by status: running, complete, failed |
| `--limit` | int | 10 | Maximum runs to show |
| `--redis-host` | string | localhost | Redis host |
| `--redis-port` | int | 6379 | Redis port |

**Examples:**

```bash
# List recent runs
miladyos list-runs

# List runs for specific template
miladyos list-runs --template example-build

# List only failed runs
miladyos list-runs --status failed --limit 20
```

---

## AlphaEvolve Commands

The AlphaEvolve CLI provides direct access to the evolution engine.

### evolve

Start evolutionary optimization of a pipeline template.

```bash
python alpha_evolve.py evolve [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template`, `-t` | string | required | Template name or path |
| `--goal`, `-g` | choice | reliability | Evolution goal |
| `--config`, `-c` | path | configs/evolve_default.yaml | Config file |
| `--generations`, `-n` | int | 100 | Maximum generations |

**Available Goals:**
- `speed` - Optimize execution time
- `reliability` - Improve success rate
- `resources` - Optimize resource usage
- `security` - Enhance security practices
- `observability` - Improve logging/metrics

**Examples:**

```bash
# Evolve for speed
python alpha_evolve.py evolve --template example-build --goal speed

# Evolve with custom config
python alpha_evolve.py evolve -t docker-deploy -g reliability -c my-config.yaml

# Short evolution run
python alpha_evolve.py evolve -t my-pipeline -g speed --generations 20
```

**Output:**
```
[INFO] Starting evolution: abc123-def456-...
[INFO] Template: example-build, Goal: speed
[INFO] Initialized 4 islands with 20 total candidates
[INFO] Generation 1/100
[INFO] New best fitness: 0.3500
[INFO] Generation 2/100
...
[INFO] Evolution complete: 47 generations, best fitness: 0.8234

============================================================
EVOLUTION COMPLETE
============================================================
Evolution ID: abc123-def456-...
Generations: 47
Best Fitness: 0.8234
Archive Size: 15
Duration: 342.5s
Output: evolved_templates/example-build_evolved_speed_20240115_143022.Jenkinsfile
```

---

### goals

List available evolution optimization goals.

```bash
python alpha_evolve.py goals
```

**Output:**
```
Available Evolution Goals:

  speed
    Optimize for faster execution time
    Weights: {'duration_seconds': -1.0, 'success_rate': 0.3, 'parallelism_score': 0.5}

  reliability
    Improve success rate and error handling
    Weights: {'success_rate': 1.0, 'error_handling_score': 0.5, ...}

  resources
    Optimize resource usage (CPU, memory, disk)
    Weights: {'resource_efficiency': 1.0, 'cleanup_score': 0.4, ...}

  security
    Enhance security practices
    Weights: {'security_score': 1.0, 'secrets_handling': 0.5, ...}

  observability
    Improve logging, metrics, and tracing
    Weights: {'logging_score': 0.4, 'metrics_score': 0.3, ...}
```

---

### templates

List available and evolved templates.

```bash
python alpha_evolve.py templates [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--path`, `-p` | path | templates | Templates directory |

**Output:**
```
Templates in templates:

  [✓] example-build
  [✓] docker-deploy
  [ ] talos-cluster-bootstrap
  [ ] talos-add-worker
  [ ] miladyos-stack-deploy

  [✓] = Has EVOLVE-BLOCK markers
```

---

## Meta-Evolution Commands

The meta-evolution CLI enables recursive optimization.

### meta-evolve

Run meta-evolution to find optimal evolution parameters.

```bash
python meta_evolve.py meta-evolve [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template`, `-t` | string | required | Template to meta-evolve |
| `--goal`, `-g` | string | reliability | Evolution goal |
| `--meta-generations`, `-m` | int | 5 | Meta-evolution generations |

**Examples:**

```bash
# Find optimal parameters for reliability evolution
python meta_evolve.py meta-evolve --template example-build --goal reliability

# Run longer meta-evolution
python meta_evolve.py meta-evolve -t docker-deploy -g speed -m 10
```

**Output:**
```
Meta-Evolution Complete!
Best Config: {
  "population_size": 25,
  "num_islands": 6,
  "mutation_rate": 0.45,
  "elite_ratio": 0.15,
  "tournament_size": 4,
  "stagnation_limit": 12,
  "llm_temperature": 0.75
}
Best Fitness: 0.8123
```

---

### analyze

Analyze a template for evolution opportunities.

```bash
python meta_evolve.py analyze [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template`, `-t` | string | required | Template to analyze |

**Examples:**

```bash
python meta_evolve.py analyze --template docker-deploy
```

**Output:**
```
Found 3 evolution opportunities:

  Type: build
  Language: docker
  Complexity: medium
  Suggested Goals: ['speed', 'reliability']

  Type: test
  Language: docker
  Complexity: low
  Suggested Goals: ['reliability', 'speed']

  Type: deploy
  Language: kubernetes
  Complexity: high
  Suggested Goals: ['reliability', 'security']
```

---

### inject-blocks

Automatically inject EVOLVE-BLOCK markers into a template.

```bash
python meta_evolve.py inject-blocks [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--template`, `-t` | string | required | Template to modify |
| `--output`, `-o` | path | in-place | Output file path |

**Examples:**

```bash
# Inject markers in place
python meta_evolve.py inject-blocks --template my-pipeline

# Inject to new file
python meta_evolve.py inject-blocks --template my-pipeline --output my-pipeline-evolvable.Jenkinsfile
```

---

## Environment Variables

These environment variables affect CLI behavior:

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | localhost | Redis server host |
| `REDIS_PORT` | 6379 | Redis server port |
| `JENKINS_URL` | http://localhost:8080 | Jenkins server URL |
| `JENKINS_ADMIN_ID` | milady | Jenkins username |
| `JENKINS_ADMIN_PASSWORD` | milady | Jenkins password |
| `TEMPLATES_DIR` | templates | Templates directory |
| `METADATA_DIR` | metadata | Metadata directory |
| `SQLITE_DB_PATH` | /data/redka/data.db | SQLite database path |
| `KUBERNETES_MODE` | false | Enable Kubernetes mode |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Template not found |
| 4 | Jenkins connection failed |
| 5 | Evolution failed |

---

## Shell Completion

### Bash

```bash
# Add to ~/.bashrc
eval "$(_MILADYOS_COMPLETE=bash_source miladyos)"
```

### Zsh

```bash
# Add to ~/.zshrc
eval "$(_MILADYOS_COMPLETE=zsh_source miladyos)"
```

### Fish

```bash
# Add to ~/.config/fish/completions/miladyos.fish
eval (env _MILADYOS_COMPLETE=fish_source miladyos)
```
