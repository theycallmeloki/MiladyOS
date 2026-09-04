#!/usr/bin/env bash
# emacs-gotty — open the emacsclient terminal attached to the MiladyOS emacs
# daemon. This is the operator surface where you watch milady operate a live
# emacs over MCP: buffers, files, commands appear in real time. Inside emacs,
# run M-x shell (or M-x eshell / M-x term) for a real bash when you need it.
#
# Wait briefly for the daemon (started by startup.sh) to be reachable so an
# impatient click doesn't error out; then attach a terminal frame to it.
set -u
for _ in $(seq 1 20); do
    if emacsclient -e '(emacs-version)' >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
exec emacsclient -t
