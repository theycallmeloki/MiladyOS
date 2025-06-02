# NFT Authentication Integration for MiladyOS

Simple and direct High Integrity Milady NFT authentication middleware for the existing MiladyOS infrastructure.

## Architecture Overview

```
Web3 Wallet → MetaMask → NFT Auth Middleware → Existing MiladyOS MCP Server
                ↓
         Direct integration with running MiladyOS services
```

## Features

- **High Integrity Milady NFT Only**: Single contract authentication (0xf01B34d9418874258B35b0507AB53ED971CBB8D3)
- **Direct Integration**: Works with existing MiladyOS deployment without complex setup
- **Redis Caching**: Uses existing Redis instance for performance
- **Web3 Client**: Browser-based MetaMask integration
- **Middleware Approach**: Simple Python decorator for existing endpoints

## Supported Network

- Ethereum Mainnet only (High Integrity Milady contract)

## Access Control

- **NFT Requirement**: High Integrity Milady (0xf01B34d9418874258B35b0507AB53ED971CBB8D3)
- **Access Level**: Protects sensitive MCP endpoints
- **Minimum Tokens**: 1 High Integrity Milady NFT

## Integration with Existing MiladyOS

This approach integrates directly with your running MiladyOS deployment:

```bash
# 1. Update secrets with your API keys
kubectl create secret generic nft-auth-config \
  --from-literal=ethereum-rpc-url="https://mainnet.infura.io/v3/YOUR_KEY" \
  --from-literal=etherscan-api-key="YOUR_ETHERSCAN_KEY"

# 2. Apply the integration patch
kubectl apply -k deploy/nft-auth/

# 3. The middleware will be automatically mounted into the existing MiladyOS pod
```

## Usage

### Web Interface
1. Load the Web3 auth client in your browser
2. Connect MetaMask wallet
3. System automatically verifies High Integrity Milady ownership
4. Authenticated requests include Bearer token

### API Integration
```python
# In your MCP server code, protect endpoints:
from nft_auth_middleware import require_nft_auth

@app.route('/execute_command', methods=['POST'])
@require_nft_auth
def execute_command():
    wallet = request.nft_wallet  # Available after auth
    # Your existing command execution logic
```

## Configuration

Minimal configuration required:

```yaml
ETHEREUM_RPC_URL: "https://mainnet.infura.io/v3/YOUR_KEY"
ETHERSCAN_API_KEY: "YOUR_ETHERSCAN_KEY"
HIGH_INTEGRITY_MILADY_CONTRACT: "0xf01B34d9418874258B35b0507AB53ED971CBB8D3"
```

## Benefits of This Approach

- **No Service Disruption**: Works with existing MiladyOS without downtime
- **Simple Integration**: Just mount middleware files and add decorators
- **Uses Existing Infrastructure**: Leverages current Redis and network setup
- **Minimal Attack Surface**: No new services or complex authentication flows
- **High Integrity Milady Focus**: Single contract, simple ownership verification

## Security Features

- **Wallet Signature Verification**: Cryptographic proof of wallet ownership
- **NFT Ownership Verification**: Real-time blockchain verification
- **Caching**: Reduces blockchain API calls while maintaining security
- **Rate Limiting**: Built-in protection against API abuse

## Development

```bash
# Test NFT ownership locally
python3 nft-auth-middleware.py

# Test Web3 integration
# Open index.html with the JavaScript client in a browser
```

## File Structure

```
deploy/nft-auth/
├── README.md                    # This file
├── nft-auth-middleware.py       # Python middleware for MCP server
├── nft-web3-auth.js            # JavaScript Web3 client
├── integration-patch.yaml      # Kubernetes integration patch
├── kustomization.yaml          # Kustomize configuration
├── scripts/kubectl-nft-auth    # kubectl plugin (optional)
└── rbac/nft-auth-rbac.yaml     # Basic RBAC (if needed)
```