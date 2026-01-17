---
title: "AlphaEvolve"
linkTitle: "AlphaEvolve"
weight: 25
description: >
  Self-improving pipeline evolution using LLM-powered genetic algorithms
---

{{% pageinfo %}}
AlphaEvolve enables MiladyOS to autonomously optimize Jenkins pipelines through evolutionary algorithms powered by local LLMs. The system can improve execution speed, reliability, resource usage, security, and observability without human intervention.
{{% /pageinfo %}}

## Overview

MiladyOS AlphaEvolve is inspired by [Google DeepMind's AlphaEvolve](https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) but runs entirely on your local infrastructure using open-source LLMs.

```
                    ┌─────────────────────────────────────────────────────┐
                    │              MiladyOS AlphaEvolve                   │
                    ├─────────────────────────────────────────────────────┤
                    │  ┌──────────────┐   ┌──────────────┐   ┌─────────┐ │
                    │  │ LLM Ensemble │   │ Evaluator    │   │ Jenkins │ │
                    │  │ (Ollama/vLLM)│   │ Cascade      │   │ Test    │ │
                    │  └──────┬───────┘   └──────┬───────┘   └────┬────┘ │
                    │         │                  │                 │      │
                    │         ▼                  ▼                 ▼      │
                    │  ┌─────────────────────────────────────────────────┐│
                    │  │              Evolution Engine                   ││
                    │  │  ┌─────────┐  ┌─────────┐  ┌─────────────────┐ ││
                    │  │  │ Islands │  │ MAP-    │  │ Selection &     │ ││
                    │  │  │ (4)     │  │ Elites  │  │ Mutation        │ ││
                    │  │  └─────────┘  └─────────┘  └─────────────────┘ ││
                    │  └─────────────────────────────────────────────────┘│
                    │                        │                            │
                    │                        ▼                            │
                    │  ┌─────────────────────────────────────────────────┐│
                    │  │              Program Database (Redis)           ││
                    │  └─────────────────────────────────────────────────┘│
                    └─────────────────────────────────────────────────────┘
```

### Key Features

- **LLM-Powered Mutations**: Uses local models (DeepSeek, Qwen, Mistral) for intelligent code modifications
- **Quality-Diversity Search**: MAP-Elites algorithm maintains diverse high-quality solutions
- **Island-Based Evolution**: Multiple populations prevent premature convergence
- **Cascade Evaluation**: Fast syntax checks → static analysis → dry runs → live execution
- **Meta-Evolution**: The system can optimize its own evolution parameters
- **MCP Integration**: Trigger evolutions via Claude or any MCP client

---

## Quick Start

### Evolve a Pipeline via CLI

```bash
# Evolve for speed optimization
python alpha_evolve.py evolve --template example-build --goal speed

# Evolve for reliability with custom generations
python alpha_evolve.py evolve --template docker-deploy --goal reliability --generations 100

# List available goals
python alpha_evolve.py goals

# List evolved templates
python alpha_evolve.py templates
```

### Evolve via MCP Tool

Using Claude Desktop or any MCP client:

```
Use the evolve_template tool to optimize the example-build pipeline for speed
```

The MCP server exposes these evolution tools:
- `evolve_template` - Start evolutionary optimization
- `evolution_status` - Check progress of running evolutions
- `list_evolution_goals` - Show available optimization goals
- `list_evolved_templates` - List all evolved versions

---

## Evolution Goals

AlphaEvolve supports 5 optimization goals, each with specific fitness weights and LLM hints:

### Speed

Optimize for faster execution time.

| Metric | Weight | Description |
|--------|--------|-------------|
| `duration_seconds` | -1.0 | Lower is better |
| `success_rate` | 0.3 | Must still work |
| `parallelism_score` | 0.5 | Parallel stages help |

**Optimization Hints:**
- Add parallel execution where stages are independent
- Use shallow git clones (`depth: 1`)
- Implement caching for dependencies (npm, pip)
- Use faster alternatives (pnpm over npm, uv over pip)
- Use incremental builds where possible

### Reliability

Improve success rate and error handling.

| Metric | Weight | Description |
|--------|--------|-------------|
| `success_rate` | 1.0 | Primary metric |
| `error_handling_score` | 0.5 | Try-catch coverage |
| `retry_coverage` | 0.3 | Retry on flaky ops |
| `timeout_coverage` | 0.2 | Prevent hangs |

**Optimization Hints:**
- Add retry logic for flaky operations (network, docker)
- Implement comprehensive try-catch blocks
- Add timeouts to prevent hanging builds
- Validate inputs before processing
- Add health checks before deployments

### Resources

Optimize CPU, memory, and disk usage.

| Metric | Weight | Description |
|--------|--------|-------------|
| `resource_efficiency` | 1.0 | Primary metric |
| `cleanup_score` | 0.4 | Workspace cleanup |
| `constraint_score` | 0.3 | Resource limits |

**Optimization Hints:**
- Add resource limits (memory, CPU) to containers
- Implement cleanup steps (docker prune, cleanWs)
- Use smaller base images
- Use multi-stage builds to reduce final image size

### Security

Enhance security practices.

| Metric | Weight | Description |
|--------|--------|-------------|
| `security_score` | 1.0 | Primary metric |
| `secrets_handling` | 0.5 | Credentials usage |
| `vulnerability_scan` | 0.3 | Security scanning |

**Optimization Hints:**
- Never hardcode secrets, use credentials binding
- Add vulnerability scanning (trivy, snyk)
- Use specific image tags, not `:latest`
- Add SBOM generation

### Observability

Improve logging, metrics, and tracing.

| Metric | Weight | Description |
|--------|--------|-------------|
| `logging_score` | 0.4 | Structured logging |
| `metrics_score` | 0.3 | Build metrics |
| `notification_score` | 0.3 | Failure alerts |

**Optimization Hints:**
- Add structured logging with context
- Emit build metrics (duration, size, test count)
- Implement notifications for failures
- Include performance timing for stages

---

## EVOLVE-BLOCK Markers

Mark sections of your Jenkinsfile for evolution using special comments:

```groovy
pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        // EVOLVE-BLOCK-START: {"type": "build", "language": "javascript", "goals": ["speed", "reliability"]}
        stage('Build') {
            steps {
                sh 'npm install'
                sh 'npm run build'
            }
        }

        stage('Test') {
            steps {
                sh 'npm test'
            }
        }
        // EVOLVE-BLOCK-END

        stage('Deploy') {
            steps {
                // Not evolved - critical deployment logic
                sh 'kubectl apply -f deploy/'
            }
        }
    }
}
```

### Block Metadata

The JSON metadata after `EVOLVE-BLOCK-START:` provides context to the LLM:

| Field | Description |
|-------|-------------|
| `type` | Block type: `build`, `test`, `deploy`, `lint`, `security` |
| `language` | Primary language: `javascript`, `python`, `go`, `docker` |
| `goals` | Optimization priorities: `["speed", "reliability"]` |
| `complexity` | Hint: `low`, `medium`, `high` |
| `constraints` | Optional restrictions (e.g., `{"no_parallel": true}`) |

---

## Architecture

### Evolution Engine

The engine combines several algorithms for effective optimization:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Evolution Loop                                   │
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐ │
│  │ Initialize   │────▶│ Evaluate     │────▶│ Select & Reproduce       │ │
│  │ Population   │     │ Fitness      │     │ (Tournament + Crossover) │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────┘ │
│         │                    │                         │                 │
│         │                    │                         │                 │
│         ▼                    ▼                         ▼                 │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐ │
│  │ Island 1     │     │ MAP-Elites   │     │ LLM Mutation             │ │
│  │ Island 2     │     │ Archive      │     │ (DeepSeek/Qwen)          │ │
│  │ Island 3     │     │ (Quality-    │     │                          │ │
│  │ Island 4     │     │  Diversity)  │     │ Error Feedback Loop      │ │
│  └──────────────┘     └──────────────┘     └──────────────────────────┘ │
│         │                    │                         │                 │
│         └────────────────────┴─────────────────────────┘                 │
│                              │                                           │
│                              ▼                                           │
│                    ┌──────────────────┐                                  │
│                    │ Migration        │                                  │
│                    │ (Every N gens)   │                                  │
│                    └──────────────────┘                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Island-Based Evolution

Multiple isolated populations evolve in parallel, preventing premature convergence:

- **Default**: 4 islands with 5 candidates each (20 total population)
- **Migration**: Every 5 generations, top candidates migrate between islands
- **Diversity**: Each island uses slightly different LLM temperatures

### MAP-Elites Quality-Diversity

Instead of just finding the single best solution, MAP-Elites maintains an archive of diverse high-quality solutions across multiple dimensions:

| Dimension | Range | Description |
|-----------|-------|-------------|
| Execution Speed | 0.0 - 1.0 | How fast the pipeline runs |
| Reliability | 0.0 - 1.0 | Error handling coverage |
| Resource Efficiency | 0.0 - 1.0 | Resource constraints/cleanup |

This means you get multiple evolved variants optimized for different trade-offs.

### Cascade Evaluation

Candidates are evaluated through increasingly expensive stages:

```
Stage 1: Syntax Validation (< 1 sec)
    │
    ├── Pass ──▶ Stage 2: Static Analysis (< 5 sec)
    │               │
    │               ├── Pass ──▶ Stage 3: Dry Run (< 30 sec)
    │               │               │
    │               │               ├── Pass ──▶ Stage 4: Live Execution
    │               │               │               │
    │               │               │               └── Final Fitness Score
    │               │               │
    │               │               └── Fail ──▶ Fitness = 0.2
    │               │
    │               └── Fail ──▶ Fitness = 0.1
    │
    └── Fail ──▶ Fitness = -1.0 (Invalid)
```

---

## Configuration

Configure evolution via `configs/evolve_default.yaml`:

```yaml
# LLM Configuration
llm:
  primary:
    model: "ollama/deepseek-r1:14b"
    api_base: "http://localhost:11434/v1"
    temperature: 0.8
    max_tokens: 4096
  secondary:
    model: "ollama/qwen2.5-coder:7b"
    api_base: "http://localhost:11434/v1"
    temperature: 0.9
  proxy:
    enabled: true
    api_base: "http://localhost:4000/v1"

# Evolution Parameters
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

# MAP-Elites Settings
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

# Evaluator Configuration
evaluator:
  cascade:
    - name: "syntax"
      timeout: 5
      weight: 0.1
    - name: "dry_run"
      timeout: 30
      weight: 0.2
    - name: "execution"
      timeout: 300
      weight: 0.7

# Storage
storage:
  redis:
    url: "${REDIS_URL:-redis://localhost:6379}"
    prefix: "miladyos:evolve:"
    ttl: 86400
  backup_dir: "evolved_templates"
  keep_generations: 10
```

---

## Meta-Evolution

AlphaEvolve can optimize its own evolution parameters through meta-evolution:

```bash
# Run meta-evolution to find optimal parameters
python meta_evolve.py meta-evolve --template example-build --goal reliability --meta-generations 5
```

This runs multiple evolution attempts with different configurations and learns which parameters work best for your template type.

### Evolution Chain

Set up continuous improvement with evolution chains:

```python
from meta_evolve import EvolutionChainManager

# Create a chain that rotates through goals
manager = EvolutionChainManager(redis_client)
chain = await manager.create_chain(
    template_name="example-build",
    goals=["reliability", "speed", "resources"],
    interval_hours=24
)

# Run next evolution in chain
result = await manager.run_chain_evolution(chain.chain_id)
```

### Auto-Inject EVOLVE-BLOCK

Automatically analyze templates and inject evolution markers:

```bash
# Analyze template for evolution opportunities
python meta_evolve.py analyze --template docker-deploy

# Output:
# Found 3 evolution opportunities:
#   Type: build, Language: docker, Complexity: medium
#   Type: test, Language: docker, Complexity: low
#   Type: deploy, Language: kubernetes, Complexity: high

# Inject EVOLVE-BLOCK markers
python meta_evolve.py inject-blocks --template docker-deploy
```

---

## MCP Tool Reference

### evolve_template

Start evolutionary optimization of a Jenkins pipeline.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `template_name` | string | Yes | - | Template name (without .Jenkinsfile) |
| `goal` | string | Yes | - | Evolution goal |
| `max_generations` | int | No | 50 | Maximum generations |
| `population_size` | int | No | 20 | Population size |
| `run_async` | bool | No | true | Run in background |

**Example:**
```json
{
  "template_name": "example-build",
  "goal": "speed",
  "max_generations": 100,
  "run_async": true
}
```

**Response:**
```json
{
  "success": true,
  "evolution_id": "abc123...",
  "template_name": "example-build",
  "goal": "speed",
  "status": "started",
  "message": "Evolution started in background. Use evolution_status to check progress."
}
```

### evolution_status

Check status of a running or completed evolution.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `evolution_id` | string | Yes | Evolution ID to check |

**Response:**
```json
{
  "success": true,
  "evolution_id": "abc123...",
  "status": "running",
  "template_name": "example-build",
  "goal": "speed",
  "generation": 15,
  "best_fitness": 0.72
}
```

### list_evolution_goals

List all available evolution optimization goals.

**Response:**
```json
{
  "success": true,
  "goals": [
    {
      "name": "speed",
      "description": "Optimize for faster execution time",
      "fitness_weights": {"duration_seconds": -1.0, "success_rate": 0.3},
      "optimization_hints": ["Add parallel execution...", "Use shallow clones..."]
    }
  ],
  "count": 5
}
```

### list_evolved_templates

List all evolved template versions.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `template_name` | string | No | Filter by original template name |

**Response:**
```json
{
  "success": true,
  "templates": [
    {
      "filename": "example-build_evolved_speed_20240115_143022.Jenkinsfile",
      "original_template": "example-build",
      "path": "evolved_templates/example-build_evolved_speed_20240115_143022.Jenkinsfile",
      "metadata": {
        "evolution_id": "abc123...",
        "goal": "speed",
        "fitness": "0.8234"
      }
    }
  ],
  "count": 3
}
```

---

## Output Files

Evolved templates are saved to `evolved_templates/` with metadata headers:

```groovy
// Evolved by MiladyOS AlphaEvolve
// Evolution ID: abc123-def456-...
// Goal: speed
// Generations: 47
// Fitness: 0.8234
// Timestamp: 20240115_143022

pipeline {
    agent any

    stages {
        // Optimized stages...
    }
}
```

---

## Best Practices

### 1. Start with Reliability

Before optimizing for speed, ensure your pipeline is reliable:
```bash
python alpha_evolve.py evolve --template my-pipeline --goal reliability
```

### 2. Use EVOLVE-BLOCK Strategically

Don't mark critical deployment logic for evolution. Focus on:
- Build stages (parallelization, caching)
- Test stages (parallel test suites)
- Lint/security stages (optional optimization)

### 3. Review Evolved Code

Always review evolved templates before deploying to production:
```bash
diff templates/my-pipeline.Jenkinsfile evolved_templates/my-pipeline_evolved_speed_*.Jenkinsfile
```

### 4. Chain Goals

Run evolution chains to optimize multiple objectives:
```bash
# First optimize reliability
python alpha_evolve.py evolve -t my-pipeline -g reliability

# Then optimize the reliable version for speed
python alpha_evolve.py evolve -t my-pipeline_evolved_reliability_* -g speed
```

### 5. Monitor Evolution

Check Redis for evolution state:
```bash
redis-cli KEYS "miladyos:evolve:*"
redis-cli HGETALL "miladyos:evolve:running:YOUR_EVOLUTION_ID"
```

---

## Troubleshooting

### Evolution Stalls

**Symptom:** No fitness improvement for many generations

**Solutions:**
1. Increase mutation rate: `mutation_rate: 0.6`
2. Increase population diversity: `num_islands: 6`
3. Reduce stagnation limit to terminate earlier: `stagnation_limit: 10`

### LLM Generation Errors

**Symptom:** Invalid Groovy syntax in generated code

**Solutions:**
1. Lower temperature: `temperature: 0.6`
2. Use a more capable model: `deepseek-r1:32b`
3. Enable fallback mutations: The system has rule-based fallbacks

### Fitness Always Zero

**Symptom:** All candidates have fitness = 0 or negative

**Solutions:**
1. Check syntax of original template
2. Ensure EVOLVE-BLOCK markers are correctly placed
3. Review evaluator logs for specific errors

### Out of Memory

**Symptom:** Evolution crashes with OOM

**Solutions:**
1. Reduce population size: `population_size: 10`
2. Use smaller LLM model: `qwen2.5-coder:7b`
3. Disable live execution evaluation: `live_execution: false`

---

## Future Improvements

- [ ] Support for multi-file pipeline evolution (shared libraries)
- [ ] Integration with test result parsing for fitness
- [ ] GPU-accelerated parallel evaluation
- [ ] Web UI for evolution monitoring
- [ ] Pre-trained evolution strategies per language/framework
