#!/usr/bin/env bash
# Switches the dashboard's maintenance notice on the Pi, from the admin laptop.
#
# While it is on, anyone on the LAN who opens the dashboard sees "Panel en
# mantenimiento" and nothing they send is written; from Tailscale the panel
# works as usual, with a reminder strip. deploy.sh switches it on and off by
# itself around a deploy; this is for longer work on the Pi's live data --
# reprocessing a month, fixing the database by hand.
#
#     deploy/maintenance.sh status   # is it on? needs no sudo
#     deploy/maintenance.sh on       # asks for the Pi's sudo password
#     deploy/maintenance.sh off      # asks for the Pi's sudo password
set -euo pipefail

PI="${NETTUNE_PI:-100.64.0.10}"
# Beside the database, in state/, which a deploy never touches.
FLAG=/opt/security_log_processor/state/MANTENIMIENTO

status() {
    local code=0
    ssh -o BatchMode=yes "$PI" "test -e '$FLAG'" || code=$?
    case "$code" in
        0) echo "Mantenimiento ACTIVADO: la LAN ve el aviso; Tailscale ve el panel." ;;
        1) echo "Mantenimiento desactivado: el panel funciona para todos." ;;
        *) echo "No se pudo consultar la Pi ($PI)." >&2; exit 1 ;;
    esac
}

case "${1:-}" in
    status) status ;;
    on)  ssh -t "$PI" "sudo -u scanproc touch '$FLAG'" && status ;;
    off) ssh -t "$PI" "sudo -u scanproc rm -f '$FLAG'" && status ;;
    *) echo "Uso: $0 on|off|status" >&2; exit 2 ;;
esac
