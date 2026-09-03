#!/bin/sh
# kaniko-builder transform: submit one KanikoBuild per datum.
# The input-repo env var ($builds) stages ONLY this datum; locate spec.json
# under it (subtree datums nest one level: $builds/<datum>/spec.json).
# Kubeconfig arrives bound as $KUBECONFIG_CONTENT (sandman secret binding).
set -e
: "${builds:?no input datum dir}"
mkdir -p "$HOME/.kube"
printf '%s' "$KUBECONFIG_CONTENT" > "$HOME/.kube/config"
chmod 600 "$HOME/.kube/config"
export KUBECONFIG="$HOME/.kube/config"
SPEC=$(find "$builds" -maxdepth 2 -name spec.json | head -1)
[ -n "$SPEC" ] || { echo "kaniko-builder: no spec.json under $builds"; exit 1; }
DEST=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["destination"])' "$SPEC")
CTX=$(dirname "$SPEC")
echo "kaniko-builder: building $DEST from $CTX"
python3 /app/kaniko-submit.py --context "$CTX" --destination "$DEST" --timeout-seconds "${KANIKO_TIMEOUT:-1500}"
