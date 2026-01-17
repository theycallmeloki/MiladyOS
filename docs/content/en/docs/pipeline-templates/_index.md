---
title: "Pipeline Templates"
linkTitle: "Pipeline Templates"
weight: 45
description: >
  Jenkins pipeline templates for common CI/CD workflows
---

## Overview

MiladyOS provides pre-built Jenkins pipeline templates for common deployment and infrastructure tasks. These templates can be used as-is, customized, or evolved using AlphaEvolve.

Templates are stored in the `templates/` directory as `.Jenkinsfile` files.

---

## Template Inventory

| Template | Purpose | EVOLVE-BLOCK |
|----------|---------|--------------|
| `example-build` | Basic Node.js build pipeline | Yes |
| `docker-deploy` | Docker image build and deployment | Yes |
| `talos-cluster-bootstrap` | Bootstrap Talos Kubernetes cluster | No |
| `talos-add-worker` | Add worker nodes to Talos cluster | No |
| `miladyos-stack-deploy` | Deploy full MiladyOS stack | No |

---

## example-build

A basic build pipeline for JavaScript/Node.js projects. Includes EVOLVE-BLOCK markers for optimization.

### Features
- Node.js 18 environment
- npm install, build, and test stages
- Artifact archiving
- Workspace cleanup

### Template

```groovy
// Jenkinsfile for example-build
// Description: Example build pipeline that can be evolved for better performance
pipeline {
    agent any

    environment {
        NODE_VERSION = '18'
        BUILD_ENV = 'production'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        // EVOLVE-BLOCK-START: {"type": "build", "language": "javascript", "goals": ["speed", "reliability"]}
        stage('Install Dependencies') {
            steps {
                sh 'npm install'
            }
        }

        stage('Build') {
            steps {
                sh 'npm run build'
            }
        }

        stage('Test') {
            steps {
                sh 'npm test'
            }
        }
        // EVOLVE-BLOCK-END

        stage('Archive') {
            steps {
                archiveArtifacts artifacts: 'dist/**/*', fingerprint: true
            }
        }
    }

    post {
        success {
            echo 'Build completed successfully!'
        }
        failure {
            echo 'Build failed'
        }
        always {
            cleanWs()
        }
    }
}
```

### Evolution

Evolve this template for speed:
```bash
python alpha_evolve.py evolve --template example-build --goal speed
```

Potential optimizations:
- Parallel npm install and build
- npm ci instead of npm install
- Shallow git clones
- Dependency caching

---

## docker-deploy

Build and deploy Docker images to a registry.

### Features
- Docker image building
- Image testing
- Registry push
- Kubernetes deployment

### Template

```groovy
// Jenkinsfile for docker-deploy
// Description: Docker image build and deployment pipeline
pipeline {
    agent any

    environment {
        DOCKER_REGISTRY = credentials('docker-registry')
        IMAGE_NAME = 'myapp'
        IMAGE_TAG = "${BUILD_NUMBER}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        // EVOLVE-BLOCK-START: {"type": "build", "language": "docker", "goals": ["speed", "resources"]}
        stage('Build Image') {
            steps {
                sh 'docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .'
            }
        }

        stage('Test Image') {
            steps {
                sh 'docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} npm test'
            }
        }
        // EVOLVE-BLOCK-END

        stage('Push to Registry') {
            steps {
                sh '''
                    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
                    docker push ${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
                '''
            }
        }

        stage('Deploy') {
            steps {
                sh 'kubectl set image deployment/myapp myapp=${DOCKER_REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}'
            }
        }
    }

    post {
        always {
            sh 'docker system prune -f'
            cleanWs()
        }
    }
}
```

### Evolution

Evolve for resource efficiency:
```bash
python alpha_evolve.py evolve --template docker-deploy --goal resources
```

Potential optimizations:
- Multi-stage Docker builds
- BuildKit caching
- Layer optimization
- Image size reduction

---

## talos-cluster-bootstrap

Bootstrap a Talos Linux Kubernetes cluster from scratch.

### Features
- Generate cluster configuration
- Validate connectivity
- Apply machine configs
- Bootstrap control plane
- Deploy CNI (Cilium)
- Wait for node readiness

### Stages

1. **Generate Configs** - Create talosctl machine configurations
2. **Validate Endpoints** - Verify connectivity to all nodes
3. **Apply Machine Configs** - Push configs to nodes
4. **Bootstrap Control Plane** - Initialize etcd and API server
5. **Deploy CNI** - Install Cilium networking
6. **Wait for Ready** - Verify all nodes join successfully

### Usage

```bash
# Deploy via MCP
miladyos deploy --template talos-cluster-bootstrap

# Run with parameters
miladyos run --job-name talos-bootstrap --parameters '{
  "CONTROL_PLANE_IPS": "192.168.1.10,192.168.1.11,192.168.1.12",
  "WORKER_IPS": "192.168.1.20,192.168.1.21"
}'
```

---

## talos-add-worker

Add worker nodes to an existing Talos cluster.

### Features
- Generate worker config from existing cluster
- Apply to new worker nodes
- Wait for node registration

### Stages

1. **Generate Worker Config** - Create worker machine config
2. **Validate Worker Endpoints** - Check connectivity
3. **Apply Worker Configs** - Push config to new nodes
4. **Wait for Registration** - Verify nodes join cluster

### Usage

```bash
miladyos run --job-name talos-add-worker --parameters '{
  "WORKER_IPS": "192.168.1.22,192.168.1.23",
  "CLUSTER_ENDPOINT": "https://192.168.1.10:6443"
}'
```

---

## miladyos-stack-deploy

Deploy the complete MiladyOS stack to Kubernetes.

### Features
- Pre-flight checks
- Core infrastructure (ArgoCD, Longhorn)
- Monitoring stack (Prometheus, Grafana)
- LLM services (Ollama, vLLM, LiteLLM)
- MiladyOS services (MCP, NFT-Auth)
- Post-deploy verification

### Stages

1. **Pre-flight Checks** - Verify cluster readiness
2. **Deploy Infrastructure** - ArgoCD, storage, networking
3. **Deploy Monitoring** - Prometheus, Grafana, exporters
4. **Deploy LLM Services** - AI model serving infrastructure
5. **Deploy MiladyOS** - Core MiladyOS components
6. **Verify Deployment** - Health checks and smoke tests

### Usage

```bash
# Full stack deployment
miladyos deploy --template miladyos-stack-deploy
miladyos run --job-name miladyos-stack

# With custom options
miladyos run --job-name miladyos-stack --parameters '{
  "ENABLE_GPU": "true",
  "GPU_COUNT": "2",
  "STORAGE_CLASS": "longhorn"
}'
```

---

## Creating Custom Templates

### Basic Structure

```groovy
// Jenkinsfile for my-custom-template
// Description: What this pipeline does
pipeline {
    agent any

    environment {
        // Define environment variables
    }

    stages {
        stage('Stage Name') {
            steps {
                // Commands
            }
        }
    }

    post {
        success {
            echo 'Success!'
        }
        failure {
            echo 'Failed!'
        }
        always {
            cleanWs()
        }
    }
}
```

### Adding EVOLVE-BLOCK Markers

Mark sections for evolution with JSON metadata:

```groovy
// EVOLVE-BLOCK-START: {"type": "build", "language": "python", "goals": ["speed", "reliability"]}
stage('Build') {
    steps {
        sh 'pip install -r requirements.txt'
        sh 'python setup.py build'
    }
}

stage('Test') {
    steps {
        sh 'pytest tests/'
    }
}
// EVOLVE-BLOCK-END
```

### Block Metadata Fields

| Field | Values | Description |
|-------|--------|-------------|
| `type` | build, test, deploy, lint, security | Stage category |
| `language` | javascript, python, go, docker, etc. | Primary toolchain |
| `goals` | speed, reliability, resources, security | Optimization priorities |
| `complexity` | low, medium, high | Complexity hint for LLM |
| `constraints` | `{"no_parallel": true}` | Optional restrictions |

---

## Template Management

### List Templates

```bash
# Via CLI
miladyos list-templates

# Via MCP
# Use the list_templates tool
```

### View Template

```bash
# Via CLI
miladyos view-template --template example-build

# Via MCP
# Use the view_template tool with template_name parameter
```

### Create Template

```bash
# Via MCP - auto-generate from description
# Use create_template tool:
{
  "template_name": "my-python-app",
  "description": "Build and test a Python application with pytest"
}
```

### Edit Template

```bash
# Via MCP - use edit_template tool
{
  "template_name": "example-build",
  "line_edits": [
    {"line": 20, "content": "        sh 'npm ci --prefer-offline'"}
  ]
}
```

### Deploy to Jenkins

```bash
miladyos deploy --template example-build --job-name my-project-build
```

### Run Pipeline

```bash
miladyos run --job-name my-project-build
```

---

## Best Practices

### 1. Use Post Actions

Always include post actions for cleanup:

```groovy
post {
    always {
        cleanWs()
    }
    success {
        // Notify success
    }
    failure {
        // Alert on failure
    }
}
```

### 2. Use Credentials Binding

Never hardcode secrets:

```groovy
environment {
    DOCKER_CREDS = credentials('docker-registry')
    API_KEY = credentials('api-key')
}
```

### 3. Add Timeouts

Prevent hanging builds:

```groovy
options {
    timeout(time: 30, unit: 'MINUTES')
}
```

### 4. Enable Retry for Flaky Operations

```groovy
stage('Deploy') {
    steps {
        retry(3) {
            sh 'kubectl apply -f deployment.yaml'
        }
    }
}
```

### 5. Use Parallel Stages

Speed up independent stages:

```groovy
stage('Tests') {
    parallel {
        stage('Unit Tests') {
            steps { sh 'npm run test:unit' }
        }
        stage('Integration Tests') {
            steps { sh 'npm run test:integration' }
        }
    }
}
```

---

## Evolving Templates

Use AlphaEvolve to automatically optimize templates:

```bash
# Evolve for speed
python alpha_evolve.py evolve --template example-build --goal speed

# Evolve for reliability
python alpha_evolve.py evolve --template docker-deploy --goal reliability

# Check evolved versions
ls evolved_templates/
```

The evolution system will:
1. Parse EVOLVE-BLOCK sections
2. Generate mutations using LLMs
3. Evaluate fitness (syntax, static analysis, execution)
4. Select best candidates
5. Save optimized templates to `evolved_templates/`

See [AlphaEvolve](/docs/alpha-evolve/) for detailed documentation.
