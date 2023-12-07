#!/bin/bash

# Start Caddy in the background
caddy run --config /etc/caddy/Caddyfile &

# Sleep for a few seconds to ensure Caddy starts
sleep 5

# Start Ollama in the background
OLLAMA_HOST=0.0.0.0 ollama serve &

# Sleep to start
sleep 5

# Start Jenkins in the foreground
/usr/local/bin/jenkins.sh
