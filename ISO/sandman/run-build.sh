#!/usr/bin/env bash
# MiladyOS ISO build — sandman job entrypoint (see docs/SANDMAN-BUILD.md).
#
# sandman jobs are unprivileged, so this does not run live-build directly: it
# drives the worker's Docker through a mounted socket, and the host daemon runs
# ISO/build.sh's privileged live-build container. All build state lives on a
# persistent host directory that is mounted at *the same path* it has on the
# host, so the nested `docker -v` arguments resolve.
#
# Volume contract (sandman podSpec hostPath volumes):
#   /sandman/volumes/miladyos-repo   the MiladyOS checkout (source)
#   /sandman/volumes/milady-iso      persistent build dir (cache + out),
#                                    mirrored at the same path on the host
#   /sandman/volumes/docker          host docker socket (DOCKER_HOST)
#
# Env:
#   PAYLOAD=1|0      embed the miladyos image payload (default 0)
#   UPLOAD_ISO=1|0   copy the finished ISO into $OUT (default 0; GBs)
#   DRY=1            set the tree up and stop before building (smoke test)
set -euo pipefail

SRC=${SRC:-/sandman/volumes/miladyos-repo}
WORK=${WORK:-/sandman/volumes/milady-iso}
DOCKER_SOCK=${DOCKER_SOCK:-/sandman/volumes/docker}
OUT=${OUT:-$WORK/sandman-out}
PAYLOAD=${PAYLOAD:-0}
UPLOAD_ISO=${UPLOAD_ISO:-0}
DRY=${DRY:-0}
export DOCKER_HOST=${DOCKER_HOST:-unix://$DOCKER_SOCK}

REPO="$WORK/src/MiladyOS"
ISO_DIR="$REPO/ISO"
export CACHE_DIR="$WORK/cache"
export OUT_DIR="$WORK/out"

log() { printf 'iso-build: %s\n' "$*" >&2; }

[ -d "$SRC" ]          || { log "source volume missing: $SRC"; exit 1; }
[ -S "$DOCKER_SOCK" ]  || { log "docker socket missing: $DOCKER_SOCK"; exit 1; }
docker version >/dev/null 2>&1 || { log "cannot reach the host docker ($DOCKER_SOCK)"; exit 1; }
[ -f "$SRC/ISO/build.sh" ] || { log "$SRC does not look like the MiladyOS repo"; exit 1; }

mkdir -p "$WORK/src" "$CACHE_DIR" "$OUT_DIR/payload" "$OUT"

# --- 1. materialize the source tree -----------------------------------------
# .git comes along: version.sh needs the commit count, and a dev build wants
# uncommitted local changes. The build's own caches are excluded.
log "syncing source: $SRC -> $REPO"
mkdir -p "$REPO"
rsync -a --delete \
    --exclude 'ISO/.cache/' --exclude 'ISO/out/' \
    --exclude 'AutoDidact/saved_data/' --exclude 'AutoDidact/rounds/' \
    --exclude '.venv/' \
    "$SRC/" "$REPO/"

# The copied tree is owned by the host user but we run as root; tell git so
# rev-parse/version.sh (both run here) accept it.
git config --global --add safe.directory '*'

COMMIT=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)
SHORT=${COMMIT:0:12}
VERSION=$(bash "$ISO_DIR/version.sh")

# --- 2. request params riding the sandman datum (optional) ------------------
# A request-*.json in the input view may override the env defaults.
for f in /sandman/in/*/request-*.json; do
    [ -f "$f" ] || continue
    log "request: $f"
    PAYLOAD=$(jq -r '.payload // '"$PAYLOAD" "$f")
    UPLOAD_ISO=$(jq -r '.upload_iso // '"$UPLOAD_ISO" "$f")
done

log "version=$VERSION commit=$SHORT payload=$PAYLOAD upload=$UPLOAD_ISO"
log "cache=$CACHE_DIR out=$OUT_DIR"
if [ "$DRY" = 1 ]; then
    log "DRY=1 — tree ready, not building"
    ls -la "$REPO" | head
    exit 0
fi

# --- 3. build (the host daemon does the privileged part) --------------------
LOG="$OUT_DIR/build-$VERSION.log"
ARGS=()
[ "$PAYLOAD" = 1 ] || ARGS+=(--no-payload)
START=$(date +%s)
log "build.sh ${ARGS[*]:-} (log: $LOG)"
set -o pipefail
( cd "$ISO_DIR" && bash build.sh "${ARGS[@]}" ) 2>&1 | tee "$LOG"
END=$(date +%s)

ISO_FILE=$(ls -t "$OUT_DIR"/miladyos-*.iso 2>/dev/null | head -1)
[ -n "$ISO_FILE" ] || { log "no ISO produced"; exit 1; }

# --- 4. manifest + tracking -------------------------------------------------
K3S=$(grep -oE 'k3s version [^ ]+' "$LOG" | tail -1 | awk '{print $3}' || true)
SIZE=$(stat -c %s "$ISO_FILE")
SHA=$(sha256sum "$ISO_FILE" | awk '{print $1}')
BUILT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LINE=$(jq -cn \
    --arg version "$VERSION" --arg commit "$COMMIT" --arg built "$BUILT" \
    --arg iso "$(basename "$ISO_FILE")" --arg sha "$SHA" \
    --arg k3s "${K3S:-}" --argjson size "$SIZE" \
    --argjson payload "$([ "$PAYLOAD" = 1 ] && echo true || echo false)" \
    --argjson secs "$((END - START))" \
    '{version:$version,commit:$commit,built:$built,iso:$iso,size:$size,sha256:$sha,k3s:$k3s,payload:$payload,seconds:$secs}')

printf '%s\n' "$LINE" | tee "$OUT_DIR/manifest-$VERSION.json" >> "$OUT_DIR/builds.jsonl"
printf '%s\n' "$LINE" > "$OUT/manifest.json"          # committed to the output repo
cp "$OUT_DIR/builds.jsonl" "$OUT/builds.jsonl"
[ "$UPLOAD_ISO" = 1 ] && cp "$ISO_FILE" "$OUT/"
log "done: $LINE"
