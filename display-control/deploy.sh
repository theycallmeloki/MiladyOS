#!/bin/bash
set -e

echo "=== Display Control Deployment ==="
echo "This script will deploy the display control system to your balena fleet."
echo "Fleet: gh_theycallmeloki/miladyos-arm (2233971)"
echo ""

# Check if balena CLI exists in parent directory
if [ ! -d "../balena-cli" ]; then
  echo "Balena CLI not found in parent directory."
  echo "Looking for balena CLI in current directory..."
  
  if [ ! -d "./balena-cli" ]; then
    echo "Balena CLI not found. Please make sure it's installed."
    exit 1
  else
    BALENA_PATH="./balena-cli"
  fi
else
  BALENA_PATH="../balena-cli"
fi

echo "Using balena CLI at $BALENA_PATH"

# Check if logged in
$BALENA_PATH/balena whoami || $BALENA_PATH/balena login

# Push to the fleet
echo "Pushing to fleet..."
$BALENA_PATH/balena push gh_theycallmeloki/miladyos-arm --nocache
