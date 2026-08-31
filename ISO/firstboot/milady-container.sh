#!/bin/sh
# Run the MiladyOS control-plane container on this node.
# Mirrors install_miladyos.sh / scripts/builder.sh flags; GPU flags are
# injected by /etc/milady/gpu.env when present. Role env comes from
# /etc/milady/node.conf (server -> KUBERNETES_MODE, agent -> join URL).
set -e

IMAGE="${MILADYOS_IMAGE:-ogmiladyloki/milady:latest}"
NAME=miladyos

# --- role env ------------------------------------------------------------------
ROLE=agent
[ -f /etc/milady/node.conf ] && . /etc/milady/node.conf 2>/dev/null || true
K8S_ENV=""
if [ "$ROLE" = "server" ]; then
    K8S_ENV="--env KUBERNETES_MODE=true --env DISABLE_DOCKER=false"
else
    K8S_ENV="--env KUBERNETES_MODE=true --env DISABLE_DOCKER=false"
fi

# --- GPU flags ------------------------------------------------------------------
GPU_FLAGS=""
if [ -f /etc/milady/gpu.env ]; then
    . /etc/milady/gpu.env
    GPU_FLAGS="${GPU_FLAGS:-}"
fi

# clean any prior run
docker rm -f "$NAME" >/dev/null 2>&1 || true

# shellcheck disable=SC2086
echo "milady-container: starting $IMAGE (role=$ROLE)" > /dev/console 2>/dev/null || true
exec docker run $GPU_FLAGS $K8S_ENV \
    --name "$NAME" \
    --privileged \
    --user root \
    --restart=unless-stopped \
    --net=host \
    --env JENKINS_ADMIN_ID="${JENKINS_ADMIN_ID:-milady}" \
    --env JENKINS_ADMIN_PASSWORD="${JENKINS_ADMIN_PASSWORD:-milady}" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    "$IMAGE"
