---
title: "APIs & Development"
linkTitle: "APIs"
weight: 70
description: >
  API documentation, development setup, and integration guides
---

## API Overview

MiladyOS provides multiple API interfaces for different aspects of the system, from AI model interaction to infrastructure management.

## Model Context Protocol (MCP)

### MCP Server
- **Implementation**: `miladyos_mcp.py`
- **Purpose**: AI agent communication protocol
- **Features**: Tool definitions, function calling, state management

### MCP Tools
The MCP server provides various tools for AI agents:
- Hardware monitoring and control
- Infrastructure management
- Model deployment and scaling
- Data pipeline operations

### Usage Example
```python
import anyio
from miladyos_mcp import MCPServer

async def main():
    server = MCPServer()
    await server.start()

    # Tool execution example
    result = await server.execute_tool(
        name="hardware_status",
        parameters={"node_id": "milady-001"}
    )
```

## REST APIs

### Display Control API
- **Base URL**: `http://display-api:8000`
- **Authentication**: Bearer token or API key

#### Endpoints

**Displays Management**
```http
GET /api/v1/displays
POST /api/v1/displays/{id}/configure
GET /api/v1/displays/{id}/status
POST /api/v1/displays/{id}/screenshot
```

**Example Request**
```bash
curl -X GET "http://display-api:8000/api/v1/displays" \
  -H "Authorization: Bearer <token>"
```

### Infrastructure API
- **Base URL**: Varies by service
- **Authentication**: Kubernetes service account tokens

#### LiteLLM Proxy
- **Configuration**: `deploy/litellm-proxy/`
- **Purpose**: Unified LLM API gateway
- **Supported Models**: Mistral-7B, QWQ-32B-AWQ, Deep-Coder-14B-AWQ

```python
import openai

client = openai.OpenAI(
    base_url="http://litellm-proxy:4000/v1",
    api_key="your-api-key"
)

response = client.chat.completions.create(
    model="mistral-7b",
    messages=[{"role": "user", "content": "Hello MiladyOS!"}]
)
```

## WebSocket APIs

### Real-time Updates
- **Display Status**: Live display monitoring
- **Training Progress**: AutoDidact training updates
- **System Metrics**: Real-time infrastructure monitoring

### Connection Example
```javascript
const ws = new WebSocket('ws://miladyos-api:8000/ws');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    console.log('Received:', data);
};

ws.send(JSON.stringify({
    type: 'subscribe',
    channel: 'training_progress'
}));
```

## gRPC Services

### High-Performance Communication
- **Service Discovery**: Node registration and discovery
- **Model Inference**: High-throughput AI model requests
- **Data Streaming**: Bulk data transfer operations

### Protocol Buffers
```protobuf
service MiladyOSService {
  rpc GetNodeStatus(NodeRequest) returns (NodeStatus);
  rpc ExecuteInference(InferenceRequest) returns (InferenceResponse);
  rpc StreamData(stream DataChunk) returns (stream DataChunk);
}
```

## Development Setup

### Local Development
1. **Clone Repository**
```bash
git clone https://github.com/theycallmeloki/MiladyOS.git
cd MiladyOS
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
```

3. **Environment Configuration**
```bash
cp .env.example .env
# Edit .env with your configuration
```

4. **Start Development Server**
```bash
python main.py serve --all-tools
```

### Docker Development
```bash
# Build development image
docker build -t miladyos:dev .

# Run with development settings
docker run -it --rm \
  -v $(pwd):/app \
  -p 8000:8000 \
  miladyos:dev
```

## SDK & Libraries

### Python SDK
```python
from miladyos import MiladyOSClient

client = MiladyOSClient(
    base_url="http://localhost:8000",
    api_key="your-api-key"
)

# Execute AI training
result = client.autodidact.train(
    dataset="apollo13",
    model="llama-8b",
    steps=100
)

# Control displays
client.display.screenshot(display_id="main")
```

### JavaScript/TypeScript SDK
```typescript
import { MiladyOSClient } from '@miladyos/sdk';

const client = new MiladyOSClient({
  baseUrl: 'http://localhost:8000',
  apiKey: 'your-api-key'
});

// Monitor training progress
const training = await client.autodidact.startTraining({
  dataset: 'apollo13',
  model: 'llama-8b',
  steps: 100
});

await training.onProgress((progress) => {
  console.log(`Training progress: ${progress.percentage}%`);
});
```

## Authentication

### API Key Authentication
```http
Authorization: Bearer sk-miladyos-1234567890abcdef
```

### Service Account Tokens
```bash
# Get service account token
kubectl -n miladyos get secret miladyos-api-token \
  -o jsonpath='{.data.token}' | base64 -d
```

### NFT-Based Authentication
```python
from miladyos.auth import NFTAuth

auth = NFTAuth(
    wallet_address="0x1234567890abcdef",
    private_key="your-private-key",
    contract_address="0xcontract-address"
)

token = auth.authenticate()
```

## Error Handling

### Standard Error Responses
```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Invalid model parameters",
    "details": {
      "field": "model_name",
      "reason": "Model not found"
    }
  }
}
```

### HTTP Status Codes
- `200 OK` - Success
- `400 Bad Request` - Invalid request
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Access denied
- `429 Too Many Requests` - Rate limited
- `500 Internal Server Error` - Server error

## Rate Limiting

### Default Limits
- **API Requests**: 1000/hour per API key
- **Model Inference**: 100/minute per model
- **WebSocket Connections**: 10 concurrent per client

### Headers
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1640995200
```