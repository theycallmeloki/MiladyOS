#!/usr/bin/env bash
# Publish the ISO builder + runner images to the registry as KanikoBuilds.
#
# The "other way" that needs no container and no Woodpecker: kaniko-submit.py
# applies a KanikoBuild CR straight to the cluster and the registry holds the
# result. Tags are content-addressed (hash of the Dockerfile), so an unchanged
# Dockerfile is a registry hit — kaniko-submit's own skip guard makes a re-run
# a no-op.
#
#   ISO/sandman/publish-images.sh [builder|runner|all]     # default all
#
# Then an ISO build uses the builder image instead of docker-building it:
#   MILADY_BUILDER_IMAGE=$(ISO/sandman/publish-images.sh builder) bash ISO/build.sh
#
# Env: REGISTRY (default miladyosregistry.transparentlyrotatableproxy.site),
#      KANIKO_TIMEOUT (seconds, default 1200). kubeconfig follows
#      kaniko-submit.py's own default (override with KUBECONFIG).
set -euo pipefail

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_DIR="$(cd "$ISO_DIR/.." && pwd)"
REG="${REGISTRY:-miladyosregistry.transparentlyrotatableproxy.site}"
SUBMIT="$REPO_DIR/deploy/kaniko/kaniko-submit.py"
WHAT="${1:-all}"

[ -f "$SUBMIT" ] || { echo "missing $SUBMIT" >&2; exit 1; }

# tag_for <prefix> <dockerfile> — content-addressed, so the tag is a cache key.
tag_for() { printf '%s%s' "$1" "$(sha256sum "$2" | cut -c1-12)"; }

# publish <prefix> <name> <context> <dockerfile> — dest on stdout, chatter on stderr.
publish() {
    local prefix=$1 name=$2 ctx=$3 df=$4 tag dest
    tag="$(tag_for "$prefix" "$df")"
    dest="$REG/$name:$tag"
    echo "== $name -> $dest" >&2
    python3 "$SUBMIT" --context "$ctx" --destination "$dest" \
        --timeout-seconds "${KANIKO_TIMEOUT:-1200}" >&2
    printf '%s\n' "$dest"
}

case "$WHAT" in
    builder|all) BUILDER="$(publish b milady-iso-builder "$ISO_DIR/builder" "$ISO_DIR/builder/Dockerfile")" ;;
esac
case "$WHAT" in
    runner|all)  RUNNER="$(publish r milady-iso-runner  "$ISO_DIR/sandman" "$ISO_DIR/sandman/Dockerfile")" ;;
esac

# The Woodpecker step's `image:` cannot be content-addressed, so also move the
# runner to the stable :1 tag (best-effort; needs host docker + registry trust).
if [ -n "${RUNNER:-}" ] && command -v docker >/dev/null 2>&1; then
    REG_BASE="${RUNNER%:*}"
    if docker pull -q "$RUNNER" >/dev/null 2>&1 \
        && docker tag "$RUNNER" "$REG_BASE:1" \
        && docker push -q "$REG_BASE:1" >/dev/null 2>&1; then
        echo "== runner stable tag: $REG_BASE:1" >&2
    else
        echo "== runner :1 tag skipped (docker/registry unavailable)" >&2
    fi
fi

{
    echo
    echo "# ISO build inputs (pull from the registry, no docker build):"
    if [ -n "${BUILDER:-}" ]; then echo "export MILADY_BUILDER_IMAGE=$BUILDER"; fi
    if [ -n "${RUNNER:-}" ]; then echo "# woodpecker iso-build.yml image: ${RUNNER%:*}:1 (stable tag)"; fi
} >&2
if [ -n "${BUILDER:-}" ]; then printf '%s\n' "$BUILDER"; fi
exit 0
