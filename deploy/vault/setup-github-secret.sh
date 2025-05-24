#!/bin/bash

# This script helps you store GitHub token in Vault and create ArgoCD repository configuration

echo "Please enter your GitHub token (it will be hidden):"
read -s GITHUB_TOKEN

if [ -z "$GITHUB_TOKEN" ]; then
    echo "Error: GitHub token cannot be empty"
    exit 1
fi

echo ""
echo "Please enter your GitHub username:"
read GITHUB_USERNAME

if [ -z "$GITHUB_USERNAME" ]; then
    echo "Error: GitHub username cannot be empty"
    exit 1
fi

echo ""
echo "Please enter your GitHub repository URL (e.g., https://github.com/username/repo):"
read GITHUB_REPO_URL

if [ -z "$GITHUB_REPO_URL" ]; then
    echo "Error: Repository URL cannot be empty"
    exit 1
fi

# Get Vault root token
ROOT_TOKEN=$(cat vault-init-keys.json | jq -r '.root_token')

# Store GitHub credentials in Vault
echo "Storing GitHub credentials in Vault..."
kubectl exec -n vault vault-0 -- sh -c "export VAULT_TOKEN=$ROOT_TOKEN && vault kv put secret/argocd/github-repo username=$GITHUB_USERNAME password=$GITHUB_TOKEN url=$GITHUB_REPO_URL"

# Create ArgoCD repository secret
echo "Creating ArgoCD repository secret..."
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: github-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: git
  url: $GITHUB_REPO_URL
  username: $GITHUB_USERNAME
  password: $GITHUB_TOKEN
EOF

echo ""
echo "GitHub repository configured successfully!"
echo "You can now create ArgoCD applications that reference this repository."