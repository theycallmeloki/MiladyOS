#!/bin/bash
# Launch the MiladyOS control-plane container.
#
# Default: pull the CI-built image from Docker Hub and run it. The image is
# built upstream on GitHub Actions (this host no longer builds it locally) —
# see scripts/build_all.sh:
#     ./scripts/build_all.sh --image --watch   # build + push on CI, then wait
#     ./scripts/builder.sh                     # pull :latest from Hub + run
#
# Local variant (iterate on the Dockerfile offline, no CI involved):
#     ./scripts/builder.sh --local             # build local image + run
#     ./scripts/builder.sh --local --fresh     # --no-cache rebuild + run
#
# Kubeconfig: read from $HOME/.kube/config at launch and passed in as
# MILADY_KUBECONFIG_CONTENT so MiladyCI.import_context can auto-attach the
# kaniko secret. Runtime env only — never baked into the public image.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

IMAGE="ogmiladyloki/miladyos"
LOCAL=0
BUILD_FLAGS=()
for a in "$@"; do
  case "$a" in
    --local) LOCAL=1 ;;
    --fresh) BUILD_FLAGS+=(--no-cache) ;;
    --help|-h) sed -n '1,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "builder.sh: unknown arg '$a' (--local --fresh)"; exit 1 ;;
  esac
done

docker stop miladyos >/dev/null 2>&1 || true
docker rm miladyos >/dev/null 2>&1 || true

if [ "$LOCAL" = 1 ]; then
  echo ">> building local image: $IMAGE ${BUILD_FLAGS[*]:-}"
  docker build -t "$IMAGE" "${BUILD_FLAGS[@]}" .
else
  echo ">> pulling $IMAGE:latest from Docker Hub"
  docker pull "$IMAGE:latest"
fi

# Run as the image default user (milady), NOT root: forgejo refuses to run as
# root (RUN_USER=milady in startup.sh's app.ini) and would otherwise skip
# Phase B. Add the host docker group so the wp agent / kaniko / scratch-build
# reach the docker socket.
DOCKER_GID="$(stat -c %g /var/run/docker.sock 2>/dev/null || echo 981)"
echo ">> launching miladyos"
docker run -d --name miladyos --privileged --restart=unless-stopped --net=host \
  --group-add "$DOCKER_GID" \
  --env MILADY_ADMIN_ID=milady --env MILADY_ADMIN_PASSWORD=milady \
  --env MILADY_KUBECONFIG_CONTENT="$(cat "${KUBECONFIG:-$HOME/.kube/config}" 2>/dev/null || true)" \
  -v /var/run/docker.sock:/var/run/docker.sock "$IMAGE"
docker ps --filter name=miladyos

# Wait until the stack is genuinely usable before returning. A plain [ -s ]
# check on .secrets is NOT enough: startup.sh writes the agent/grpc keys first
# and appends WOODPECKER_TOKEN= last, so an early import could see a non-empty
# file with no token yet and fail on first use (the client re-reads, but the
# first call still errors). Block until the token line actually exists so the
# next step (MCP import / job_run) is clean.
echo ">> waiting for forgejo + woodpecker + MCP + kaniko token..."
READY=0
for i in $(seq 1 60); do
  fg="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:3000/ 2>/dev/null || true)"
  wp="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8000/ 2>/dev/null || true)"
  tok="$(docker exec miladyos sh -c "grep -q '^WOODPECKER_TOKEN=' /var/lib/woodpecker/.secrets && echo yes || echo no" 2>/dev/null || true)"
  if [ "$fg" = "200" ] && [ "$wp" = "200" ] && [ "$tok" = "yes" ]; then READY=1; break; fi
  sleep 3
done
if [ "$READY" = 1 ]; then
  echo ">> miladyos ready (forgejo + woodpecker + MCP, kaniko token present)"
else
  echo ">> WARNING: not fully ready after $((i * 3))s — check: docker logs --follow miladyos"
fi
