#!/usr/bin/env bash
# build_all.sh — manually trigger the three MiladyOS release workflows via gh.
#
# All three are workflow_dispatch (manual); nothing builds on a plain commit.
# Cut releases deliberately when ready:
#
#   ./scripts/build_all.sh                 # docker image + milady binary + ISO
#   ./scripts/build_all.sh --image         # container image only
#   ./scripts/build_all.sh --milady        # milady binary only
#   ./scripts/build_all.sh --iso           # JIT ISO only
#   ./scripts/build_all.sh --watch         # poll until the triggered runs finish
#
# Each run derives its own 0.0.0.0.<commit-count> version, so consecutive runs
# bump automatically. Requires the `gh` CLI, authed to the MiladyOS repo.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

IMG_WF="docker_build_push.yml"
MILADY_WF="milady-release.yml"
ISO_WF="iso-jit.yml"

do_image=0; do_milady=0; do_iso=0; watch=0
for a in "$@"; do
  case "$a" in
    --image)  do_image=1 ;;
    --milady) do_milady=1 ;;
    --iso)    do_iso=1 ;;
    --watch)  watch=1 ;;
    --help|-h)
      sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "build_all.sh: unknown arg '$a' (--image --milady --iso --watch)"; exit 1 ;;
  esac
done
# no subset selected -> all three
if [ "$do_image$do_milady$do_iso" = "000" ]; then
  do_image=1; do_milady=1; do_iso=1
fi

command -v gh >/dev/null 2>&1 || { echo "build_all.sh: gh CLI is required"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "build_all.sh: not authenticated to GitHub"; exit 1; }

declare -a RUNS=()   # "databaseId:label"

trigger() { # $1 = workflow file, $2 = label
  echo ">> triggering: $2 ($1)"
  if ! gh workflow run "$1"; then
    echo "!! failed to trigger $1"; return 1
  fi
  # the run may take a moment to register
  sleep 4
  id="$(gh run list --workflow="$1" --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
  echo "   queued run: ${id:-n/a}"
  [ -n "$id" ] && RUNS+=("$id:$2")
}

[ "$do_image"  = 1 ] && trigger "$IMG_WF"   "docker image"
[ "$do_milady" = 1 ] && trigger "$MILADY_WF" "milady binary"
[ "$do_iso"    = 1 ] && trigger "$ISO_WF"   "JIT ISO"

if [ "$watch" = 1 ] && [ "${#RUNS[@]}" -gt 0 ]; then
  echo ">> watching runs..."
  while :; do
    busy=0
    for entry in "${RUNS[@]}"; do
      id="${entry%%:*}"; label="${entry##*:}"
      st="$(gh run view "$id" --json status,conclusion \
            --jq '(.status)+"/"+(.conclusion//"running")' 2>/dev/null || echo "gone")"
      case "$st" in
        completed/*) echo "   $label ($id): done ($st)" ;;
        *) busy=1 ;;
      esac
    done
    [ "$busy" = 0 ] && { echo ">> all triggered runs finished"; break; }
    sleep 15
  done
else
  echo ">> triggered. Watch with: gh run watch --exit-status  (or re-run with --watch)"
fi
