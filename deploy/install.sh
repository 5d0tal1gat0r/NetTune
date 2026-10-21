#!/usr/bin/env bash
#
# Idempotent installer for the Security Log Processor on the Raspberry Pi.
# Safe to re-run: it upgrades an existing install in place.
#
#   sudo ./deploy/install.sh
#
# Reads OPENAI_API_KEY from the environment or from an existing .env.

set -euo pipefail

APP_DIR=/opt/security_log_processor
DATA_DIR=/srv/security_scans
INCOMING_DIR="$DATA_DIR/incoming_scans"
SERVICE_USER=scanproc
SERVICE_NAME=security-log-processor.service
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo."

# --- 1. system packages ---------------------------------------------------
log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip samba samba-common-bin poppler-utils tesseract-ocr

# --- 2. service account ---------------------------------------------------
if id "$SERVICE_USER" &>/dev/null; then
    log "Service user $SERVICE_USER already exists"
else
    log "Creating service user $SERVICE_USER"
    useradd --system --create-home --home-dir /var/lib/"$SERVICE_USER" \
            --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- 3. directories -------------------------------------------------------
log "Creating directory tree"
# Only create what is missing. Rewriting an existing directory's mode or owner
# would clobber deliberate permissions -- and $INCOMING_DIR may be a mount point.
make_dir() {
    if [[ -d "$1" ]]; then
        return 0
    fi
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0775 "$1"
}
if mountpoint -q "$INCOMING_DIR" 2>/dev/null; then
    warn "$INCOMING_DIR is a mount point; leaving its ownership alone."
fi
for dir in "$APP_DIR" "$DATA_DIR" "$INCOMING_DIR"; do
    make_dir "$dir"
done
# No month folders here: the service lays out <year>/<MES>/ with its
# subfolders every time it starts (month_folders.ensure_month_tree), in the
# layout the code expects, so the two can never disagree.

# --- 4. application code --------------------------------------------------
log "Syncing application code to $APP_DIR"
if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
    # Glob inside SOURCE_DIR, not the caller's working directory.
    # Drop modules deleted upstream so they cannot still be imported.
    find "$APP_DIR" -maxdepth 1 -name '*.py' -delete
    rm -rf "$APP_DIR/nettune" "$APP_DIR/ocr_feedback"
    ( cd "$SOURCE_DIR" || exit 1
      # Not tests: development only, and deploy.sh never updates them.
      for item in *.py nettune ocr_feedback tools feedback prompts templates deploy \
                  requirements.txt pytest.ini pyproject.toml; do
          [[ -e "$item" ]] || continue
          cp -r "$item" "$APP_DIR/"
      done )
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# --- 5. virtualenv --------------------------------------------------------
log "Building virtualenv"
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    sudo -u "$SERVICE_USER" python3 -m venv "$APP_DIR/venv"
fi
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -q --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

# --- 6. configuration -----------------------------------------------------
if [[ -f "$APP_DIR/.env" ]]; then
    log "Keeping existing $APP_DIR/.env"
else
    API_KEY="${OPENAI_API_KEY:-}"
    [[ -n "$API_KEY" ]] || warn "No OPENAI_API_KEY given; edit $APP_DIR/.env before starting."
    log "Writing $APP_DIR/.env"
    cat > "$APP_DIR/.env" <<ENVEOF
OPENAI_API_KEY=$API_KEY
INCOMING_SCANS_DIR=$INCOMING_DIR
TEMPLATE_PATH=$APP_DIR/templates/template.docx
STATE_DB=$APP_DIR/state/processed.sqlite3
WATCH_MODE=auto
POLL_INTERVAL=5
OPENAI_MODEL=gpt-5.4
READINGS_PER_PAGE=2
PDF_DPI=300
MONTHLY_BUDGET_EUR=5
SPEND_DB=$APP_DIR/state/spend.sqlite3
ENVEOF
fi
chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 "$APP_DIR/state" "$APP_DIR/logs"

# --- 7. samba share -------------------------------------------------------
log "Configuring Samba share"
SMB_CONF=/etc/samba/smb.conf
SMB_BACKUP=""
if [[ -f "$SMB_CONF" ]]; then
    SMB_BACKUP="$SMB_CONF.bak.$(date +%Y%m%d%H%M%S)"
    cp "$SMB_CONF" "$SMB_BACKUP"
    log "Backed up smb.conf to $SMB_BACKUP"
else
    warn "$SMB_CONF does not exist; creating a minimal one."
    printf '[global]\n   workgroup = WORKGROUP\n   map to guest = Bad User\n' > "$SMB_CONF"
fi

if grep -q '^\[incoming_scans\]' "$SMB_CONF"; then
    CONFIGURED_PATH="$(awk '/^\[incoming_scans\]/{f=1;next} /^\[/{f=0} f&&/^[[:space:]]*path[[:space:]]*=/{print $NF; exit}' "$SMB_CONF")"
    if [[ "$CONFIGURED_PATH" == "$INCOMING_DIR" ]]; then
        log "Existing [incoming_scans] share already points at $INCOMING_DIR"
    else
        warn "An [incoming_scans] share already exists with path '$CONFIGURED_PATH'."
        warn "It should be '$INCOMING_DIR'. A wrong path is exactly why a mapped"
        warn "drive fails with NT_STATUS_BAD_NETWORK_NAME. Fix it by hand in"
        warn "$SMB_CONF, then re-run this script."
    fi
else
    cat "$APP_DIR/deploy/samba-incoming-scans.conf" >> "$SMB_CONF"
    log "Appended share definition"
    if [[ -n "${SAMBA_HOSTS_ALLOW:-}" ]]; then
        sed -i "s|^   # hosts allow = .*|   hosts allow = $SAMBA_HOSTS_ALLOW|" "$SMB_CONF"
        log "Restricted the share to: $SAMBA_HOSTS_ALLOW"
    fi
fi

# Guest access needs this in [global], or the colleague's mapped drive breaks.
if ! testparm -s --parameter-name="map to guest" 2>/dev/null | grep -qi "bad user"; then
    warn "'map to guest' is not 'Bad User'. Guest access to the share may be"
    warn "refused, which would break the colleague's existing mapped drive."
fi

if testparm -s >/dev/null 2>&1; then
    # Reload, not restart: this box also serves printing, and a restart would
    # tear down every live SMB session including in-flight print jobs.
    systemctl reload smbd || systemctl restart smbd
    log "Samba configuration reloaded"
else
    if [[ -n "$SMB_BACKUP" ]]; then
        cp "$SMB_BACKUP" "$SMB_CONF"
        warn "testparm rejected the new smb.conf; ROLLED BACK to $SMB_BACKUP"
    fi
    die "Samba configuration invalid. Nothing was changed. Check $SMB_CONF."
fi

# --- 8. systemd service ---------------------------------------------------
log "Installing $SERVICE_NAME"
cp "$APP_DIR/deploy/$SERVICE_NAME" "/etc/systemd/system/$SERVICE_NAME"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

sleep 3
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Service is running."
else
    warn "Service is not active. Recent log:"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
    exit 1
fi

# --- 9. nightly backup of the review databases ----------------------------
log "Installing the nightly database backup"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0755 /var/backups/nettune
cp "$APP_DIR/deploy/nettune-backup.service" "$APP_DIR/deploy/nettune-backup.timer" \
    /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nettune-backup.timer

cat <<SUMMARY

$(log "Install complete")

  Code      $APP_DIR
  Scans     $INCOMING_DIR
  Share     \\\\$(tailscale ip -4 2>/dev/null | head -1 || hostname -I | awk '{print $1}')\\incoming_scans

  Logs      journalctl -u $SERVICE_NAME -f
  Restart   systemctl restart $SERVICE_NAME

$( [[ -z "${SAMBA_HOSTS_ALLOW:-}" ]] && printf '%s' "  NOTE: the share is guest-writable and reachable from any host that can
        reach port 445. To limit it to your tailnet, re-run with:
          sudo SAMBA_HOSTS_ALLOW=\"100.64.0.0/10 127.0.0.1\" ./deploy/install.sh" )

SUMMARY
