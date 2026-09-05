#!/usr/bin/env bash
# Resume the complete local collection, then export every output for SFT.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
collection_dir="${1:-$script_dir/saved_data/milady_style}"
concurrency="${2:-64}"
teacher_dir="${3:-/media/laneone/storage/models/miladymodel}"
python3 -u "$script_dir/build_style_dataset.py" generate \
  --directory "$collection_dir" --limit 0 --concurrency "$concurrency" \
  --teacher-directory "$teacher_dir"
# A fresh export directory preserves any earlier snapshots on reruns.
export_dir="$(mktemp -d "$collection_dir/export-full-XXXXXXXX")"
python3 -u "$script_dir/build_style_dataset.py" export \
  --directory "$collection_dir" --export-directory "$export_dir"
printf 'Full SFT export: %s\n' "$export_dir"
