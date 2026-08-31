#!/usr/bin/env bash
# MiladyOS version — 5-octet agentic semver: MAJOR.MINOR.PATCH.BUILD.COMMIT
#
#   MAJOR.MINOR.PATCH.BUILD : version.json (manual, source of truth)
#   COMMIT                 : git commit count (automatic, monotonic)
#
# Prints e.g. "0.0.0.0.562". Used by ISO build.sh and the CI workflows so the
# container image tag and ISO filename always match the exact repo state.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="$(jq -r .version "$REPO_DIR/version.json")"
COUNT="$(git -C "$REPO_DIR" rev-list --count HEAD)"

echo "${PREFIX}.${COUNT}"
