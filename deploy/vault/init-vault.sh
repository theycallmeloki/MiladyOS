#!/bin/bash

echo "Initializing Vault..."

# Initialize Vault on the first pod
kubectl exec -n vault vault-0 -- vault operator init \
  -key-shares=5 \
  -key-threshold=3 \
  -format=json > vault-init-keys.json

if [ $? -eq 0 ]; then
  echo "Vault initialized successfully!"
  echo "IMPORTANT: Save the vault-init-keys.json file securely!"
  
  # Extract unseal keys and root token
  UNSEAL_KEY_1=$(cat vault-init-keys.json | jq -r '.unseal_keys_b64[0]')
  UNSEAL_KEY_2=$(cat vault-init-keys.json | jq -r '.unseal_keys_b64[1]')
  UNSEAL_KEY_3=$(cat vault-init-keys.json | jq -r '.unseal_keys_b64[2]')
  ROOT_TOKEN=$(cat vault-init-keys.json | jq -r '.root_token')
  
  echo "Unsealing Vault pods..."
  
  # Unseal all vault pods
  for i in 0 1 2; do
    echo "Unsealing vault-$i..."
    kubectl exec -n vault vault-$i -- vault operator unseal $UNSEAL_KEY_1
    kubectl exec -n vault vault-$i -- vault operator unseal $UNSEAL_KEY_2
    kubectl exec -n vault vault-$i -- vault operator unseal $UNSEAL_KEY_3
  done
  
  echo "Vault unsealed successfully!"
  echo "Root Token: $ROOT_TOKEN"
  echo ""
  echo "To access Vault UI, run:"
  echo "kubectl port-forward -n vault svc/vault-ui 8200:8200"
  echo "Then visit http://localhost:8200 and login with the root token"
else
  echo "Vault might already be initialized. Check vault-0 logs."
fi