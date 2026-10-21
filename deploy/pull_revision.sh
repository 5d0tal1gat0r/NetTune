#!/usr/bin/env bash
# Copies one kind of month folder (<year>/<MES>/<folder>/) off the Pi's share.
#
# Run on the P340, after pull_backups.sh, by the nettune-pull user timer
# (deploy/workbench/). Only that folder comes across, by default the review
# images in .revision: no memoria, nothing from Parking. Nothing is ever
# deleted here.
#
#     deploy/pull_revision.sh                       # into ~/NetTuneData/revision
#     NETTUNE_PI=nettune-pull@100.64.0.10 deploy/pull_revision.sh /data/revision
#     NETTUNE_FOLDER=.escaneos_originales deploy/pull_revision.sh ~/NetTuneData/originals
set -euo pipefail

PI="${NETTUNE_PI:-100.64.0.10}"
SHARE="${NETTUNE_SHARE:-/srv/security_scans/incoming_scans}"
SRC="${NETTUNE_SRC:-$PI:$SHARE/}"
FOLDER="${NETTUNE_FOLDER:-.revision}"
DEST="${1:-$HOME/NetTuneData/revision}"

mkdir -p "$DEST"
rsync -a --timeout=60 --prune-empty-dirs \
    --include='/[0-9][0-9][0-9][0-9]/' --include='/[0-9][0-9][0-9][0-9]/*/' --include="/[0-9][0-9][0-9][0-9]/*/$FOLDER/***" \
    --exclude='*' \
    "$SRC" "$DEST/"
echo "$FOLDER folders in $DEST"
