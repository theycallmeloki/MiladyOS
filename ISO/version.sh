#!/usr/bin/env bash
# MiladyOS version — 5-octet agentic semver: MAJOR.MINOR.PATCH.BUILD.COMMIT
#
#   MAJOR.MINOR.PATCH.BUILD : version.json (manual, source of truth)
#   COMMIT                 : git commit count (automatic, monotonic)
#
# Prints e.g. "0.0.0.0.562". Used by ISO build.sh and the CI workflows so the
# container image tag and ISO filename always match the exact repo state.

# Side note from dev: The versioning scheme is intentionally designed to be simple and monotonic. 
# It does not follow traditional semantic versioning rules, 
# as the focus is on ensuring that each build can be uniquely identified and traced 
# back to a specific state of the repository. 
# This approach helps maintain consistency across builds and deployments, especially in automated environments.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="$(jq -r .version "$REPO_DIR/version.json")"
COUNT="$(git -C "$REPO_DIR" rev-list --count HEAD)"

echo "${PREFIX}.${COUNT}"
