#!/usr/bin/env bash
# Copies the Pi's nightly database backups onto this machine.
#
# The Pi keeps them on its own SD card, which does not survive the card
# dying; this is the copy that does. Run it from the admin laptop whenever it
# is on the tailnet -- by hand, or from a user timer or cron entry:
#
#     deploy/pull_backups.sh                  # into ~/NetTuneBackups
#     NETTUNE_PI=100.64.0.10 deploy/pull_backups.sh /some/other/folder
#
# Nothing is ever deleted here: the Pi keeps 30 days, this keeps everything.
# NETTUNE_SRC can override the source (full rsync path; used by tests and unattended P340 timer).
set -euo pipefail

PI="${NETTUNE_PI:-100.64.0.10}"
SRC="${NETTUNE_SRC:-$PI:/var/backups/nettune/}"
DEST="${1:-$HOME/NetTuneBackups}"

mkdir -p "$DEST"
rsync -a --timeout=60 "$SRC" "$DEST/"
latest=$(ls -1 "$DEST" | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | tail -1 || true)
echo "Backups in $DEST; latest: ${latest:-none}"
