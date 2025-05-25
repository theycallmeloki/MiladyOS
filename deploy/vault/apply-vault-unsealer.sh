#!/bin/bash

# Script to apply vault unsealer with secret keys
# This script reads the unseal keys from the vault-init-keys.json backup

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VAULT_INIT_KEYS_FILE="${SCRIPT_DIR}/../../vault-secrets-backup/vault-init-keys.json"

# Check if vault-init-keys.json exists
if [ ! -f "$VAULT_INIT_KEYS_FILE" ]; then
    echo "Error: vault-init-keys.json not found at $VAULT_INIT_KEYS_FILE"
    echo "Please ensure you have the vault initialization keys backed up"
    exit 1
fi

# Extract unseal keys
UNSEAL_KEY_1=$(cat "$VAULT_INIT_KEYS_FILE" | jq -r '.unseal_keys_b64[0]')
UNSEAL_KEY_2=$(cat "$VAULT_INIT_KEYS_FILE" | jq -r '.unseal_keys_b64[1]')
UNSEAL_KEY_3=$(cat "$VAULT_INIT_KEYS_FILE" | jq -r '.unseal_keys_b64[2]')

# Create the secret
echo "Creating vault-threshold-keys secret..."
kubectl create secret generic vault-threshold-keys \
  -n vault \
  --from-literal=key1="$UNSEAL_KEY_1" \
  --from-literal=key2="$UNSEAL_KEY_2" \
  --from-literal=key3="$UNSEAL_KEY_3" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret created successfully"

# Apply the unsealer configuration
echo "Applying vault unsealer configuration..."
kubectl apply -f "${SCRIPT_DIR}/vault-unsealer-config.yaml"

echo "Vault unsealer configured successfully"