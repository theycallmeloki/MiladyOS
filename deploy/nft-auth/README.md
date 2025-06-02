# NFT Authentication Service for MiladyOS

Standalone High Integrity Milady NFT authentication service similar to TinyAuth, designed to protect any Kubernetes application without modifying the applications themselves.

## Architecture Overview

```
User → Ingress Controller → NFT Auth Service → Protected Application
       (auth-url check)     (login/verify)     (if authenticated)
```

## How It Works

Just like TinyAuth, this service acts as an authentication gateway:

1. **Ingress Integration**: Uses `nginx.ingress.kubernetes.io/auth-url` annotations
2. **Standalone Service**: Runs as separate deployment, doesn't modify your apps
3. **Web3 Authentication**: Browser-based MetaMask integration with NFT verification
4. **Session Management**: Secure cookie-based sessions

## Features

- **High Integrity Milady NFT Only**: Single contract authentication (0xf01B34d9418874258B35b0507AB53ED971CBB8D3)
- **TinyAuth-Style Integration**: Protect any service via ingress annotations
- **Web3 Authentication**: MetaMask wallet connection and signature verification
- **Redis Caching**: Fast NFT ownership verification with caching
- **Session Cookies**: Secure HTTP-only session management

## Quick Start

### 1. Deploy the Service

```bash
# Update the secret with your API keys
kubectl patch secret nft-auth-config -p '{"stringData":{"ethereum-rpc-url":"https://mainnet.infura.io/v3/YOUR_KEY","etherscan-api-key":"YOUR_ETHERSCAN_KEY"}}'

# Deploy the authentication service
kubectl apply -k deploy/nft-auth/
```

### 2. Protect Any Application

Add these annotations to any ingress to require NFT authentication:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: your-protected-app
  annotations:
    # NFT Authentication
    nginx.ingress.kubernetes.io/auth-url: "http://nft-auth-service.default.svc.cluster.local/auth"
    nginx.ingress.kubernetes.io/auth-signin: "http://nft-auth-service.default.svc.cluster.local/login?rd=$scheme://$best_http_host$request_uri"
    nginx.ingress.kubernetes.io/auth-signin-redirect-param: "rd"
    # Optional: Pass wallet info to your app
    nginx.ingress.kubernetes.io/auth-response-headers: "X-Auth-User,X-Auth-NFT"
spec:
  # ... your existing ingress config
```

## Authentication Flow

1. **User visits protected URL** → Ingress checks auth with `/auth` endpoint
2. **Not authenticated** → Redirected to `/login` page
3. **Connect MetaMask** → Wallet connection and NFT ownership verification
4. **Sign message** → Cryptographic proof of wallet ownership
5. **Session created** → Secure cookie set, user redirected back
6. **Access granted** → Future requests pass through automatically

## Configuration

The service uses these environment variables:

```yaml
HIGH_INTEGRITY_MILADY_CONTRACT: "0xf01B34d9418874258B35b0507AB53ED971CBB8D3"
ETHEREUM_RPC_URL: "https://mainnet.infura.io/v3/YOUR_KEY"
ETHERSCAN_API_KEY: "YOUR_ETHERSCAN_KEY"
SECRET_KEY: "your-session-secret"
```

## Security Features

- **Cryptographic Verification**: Wallet signature proves ownership
- **Real-time NFT Check**: Verifies current NFT ownership on-chain
- **Session Security**: HTTP-only, secure cookies with expiration
- **Caching**: Redis caching prevents blockchain spam
- **Rate Limiting**: Built-in protection against abuse

## File Structure

```
deploy/nft-auth/
├── README.md                      # This file
├── nft-auth-service.py           # Main authentication service
├── nft-auth-deployment.yaml     # Kubernetes deployment
├── example-protected-ingress.yaml # Example usage
└── kustomization.yaml           # Kustomize configuration
```

## Benefits

- **Zero App Changes**: Protect any existing app without code changes
- **Kubernetes Native**: Uses standard ingress annotations
- **High Integrity Milady Focus**: Single NFT contract, simple verification
- **Production Ready**: Proper health checks, resource limits, caching