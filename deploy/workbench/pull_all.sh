#!/usr/bin/env bash
# The nightly pulls: DB backups, review images and the original scans. Each
# runs even when an earlier one fails; the exit status is non-zero if any failed.
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data="${NETTUNE_DATA:-$HOME/NetTuneData}"
status=0
NETTUNE_SRC=nettune-backups:./ "$here/pull_backups.sh" "$data/backups" || status=1
NETTUNE_SRC=nettune-revision:./ "$here/pull_revision.sh" "$data/revision" || status=1
NETTUNE_SRC=nettune-revision:./ NETTUNE_FOLDER=.escaneos_originales \
    "$here/pull_revision.sh" "$data/originals" || status=1
exit "$status"
