#!/usr/bin/env bash
# Lists what a deploy leaves behind on the Pi, run there by deploy.sh.
#
#     stale_files.sh <release folder> <app folder>
#
# Prints one line per path, relative to the app folder:
#     remove <path>    the deploy owns it and the release no longer has it
#     leftover <path>  not the deploy's to delete; shown so a person decides
#
# The deploy copies files but never deleted any, so a module dropped from the
# repo stayed importable on the Pi (jev_shadow.py, tools/separate_scan_pages.py)
# and the tests the first install copied stayed frozen at 2026-09-17. Only
# code and prompts are the deploy's to remove: .env, state/, venv/, logs/,
# templates/ and the hand-made backups beside them are never listed for
# removal, whatever the release holds.
set -euo pipefail

# Absolute before the cd below: deploy.sh passes the release as "app",
# relative to the upload folder.
RELEASE="$(cd "$1" && pwd)"
APP="$2"
# Compared against a wrong or empty folder, every module would look dropped.
if [[ ! -f "$RELEASE/main.py" || ! -d "$RELEASE/prompts" ]]; then
    echo "stale_files.sh: $RELEASE is not a release (no main.py or prompts/)" >&2
    exit 1
fi

# Development only: deploy.sh never copies these, so any copy on the Pi is
# left over from an older install.
DEV_DIRS=(tests docs .githooks promptfoo)
# Runtime folders and files the deploy never looks inside.
KEEP=(venv state logs templates incoming_scans __pycache__)

cd "$APP"
for dir in "${DEV_DIRS[@]}"; do
    [[ -e "$dir" ]] && echo "remove $dir"
done

prune=()
for dir in "${DEV_DIRS[@]}" "${KEEP[@]}"; do
    prune+=(-path "./$dir" -prune -o)
done
# state.bak-* folders hold data, not code.
prune+=(-path './state.bak-*' -prune -o)

# Code and prompts the release no longer has.
find . "${prune[@]}" -type f \( -name '*.py' -o -path './prompts/*.md' \) -print |
    sed 's|^\./||' | sort |
    while read -r path; do
        [[ -e "$RELEASE/$path" ]] || echo "remove $path"
    done

# Hand-made copies and backups: listed, never removed.
find . -maxdepth 2 \( -path ./venv -o -path ./state \) -prune -o \
    \( -name '*.bak' -o -name '*~' -o -name 'state.bak-*' \) -print |
    sed 's|^\./||' | sort | sed 's/^/leftover /'
