#!/usr/bin/env bash
# Resume local judging, then export only faithful, styled pairs; never train.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 -u "$script_dir/screen_style_pairs.py" screen --concurrency "${1:-4}"
python3 -u "$script_dir/screen_style_pairs.py" export
