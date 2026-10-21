#!/usr/bin/env bash
# Deploys the committed code to the Pi, from the admin laptop.
#
# Replaces the hand-typed scp + sudo install commands, which went wrong three
# times on 2026-09-30: run from the wrong folder (nothing copied, services
# left stopped), stale copies in /tmp installed instead of the new ones, and
# an older command pasted after a newer one. This deploys exactly what is
# committed at HEAD -- not the working tree -- after the test suite passes
# on that same snapshot, and checks the result.
#
#     deploy/deploy.sh --dry-run   # what would change on the Pi; needs no sudo
#     deploy/deploy.sh             # deploy; asks for the Pi's sudo password once
#     deploy/deploy.sh --force     # also when the processor is busy reading a scan
#
# While it installs, the dashboard shows the LAN a maintenance notice
# (see deploy/maintenance.sh); it comes down once the services are running.
#
# Only files git tracks are written, less the development-only ones (tests,
# docs). The only things deleted on the Pi are code and prompts the release
# no longer has, and development folders an older install left there
# (deploy/stale_files.sh decides; hand-made backups are only listed). .env,
# state/, venv/, logs/ and templates/ are never touched, and neither is the
# venv: if the installed packages do not match requirements.txt, it stops and
# says so.
set -euo pipefail

PI="${NETTUNE_PI:-100.64.0.10}"
APP=/opt/security_log_processor
DRY_RUN=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --force) FORCE=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*"; }
die() { printf '\033[31mxx  %s\033[0m\n' "$*" >&2; exit 1; }

# Wherever it is run from: the repo is the folder above this script.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

COMMIT="$(git rev-parse --short HEAD)"
say "Deploying $COMMIT: $(git log -1 --format=%s)"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    warn "Uncommitted changes are NOT deployed (only commit $COMMIT is):"
    git status --short --untracked-files=no | sed 's/^/      /'
fi
if git rev-parse --verify -q '@{u}' >/dev/null && [[ -n "$(git log '@{u}..HEAD' --oneline)" ]]; then
    warn "Commit $COMMIT is not pushed yet."
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git archive HEAD | tar -x -C "$WORK"

say "Running the tests on exactly that snapshot"
if [[ -f templates/MEMORIA.docx ]]; then
    mkdir -p "$WORK/templates" && cp templates/MEMORIA.docx "$WORK/templates/"
fi
(cd "$WORK" && OPENAI_API_KEY=test "$REPO/venv/bin/python" -m pytest -q -p no:cacheprovider \
    >"$WORK.tests.log" 2>&1) || { tail -20 "$WORK.tests.log"; die "Tests failed; nothing deployed."; }
rm -f "$WORK.tests.log"
rm -rf "$WORK/templates"

# A folder of its own on the Pi, named for this run: never a shared /tmp
# name that an older upload could still be sitting under.
# An absolute path: the install step runs under sudo, where ~ is /root.
STAGE="$(ssh -o BatchMode=yes "$PI" 'echo "$HOME"')/.nettune-deploy-$COMMIT-$$"
say "Uploading to $PI:$STAGE"
ssh -o BatchMode=yes "$PI" "mkdir -p '$STAGE'"
rsync -a --delete "$WORK/" "$PI:$STAGE/app/"
cleanup_stage() { ssh -o BatchMode=yes "$PI" "rm -rf '$STAGE'" || true; }
trap 'rm -rf "$WORK"; cleanup_stage' EXIT

EXCLUDES=(--exclude=.env --exclude=state/ --exclude=venv/ --exclude=logs/
          --exclude=templates/ --exclude=__pycache__/
          # Development only: never run on the Pi.
          --exclude=tests/ --exclude=ocr_feedback/tests/ --exclude=docs/ --exclude=.githooks/ --exclude=promptfoo/)
say "Files that change on the Pi"
CHANGES="$(ssh -o BatchMode=yes "$PI" \
    "rsync -rlcn --itemize-changes ${EXCLUDES[*]} '$STAGE/app/' $APP/" | grep -E '^[<>c.]f' || true)"
if [[ -z "$CHANGES" ]]; then
    echo "      none: the Pi already runs this code."
else
    echo "$CHANGES" | awk '{print "      " $2}'
fi
STALE="$(ssh -o BatchMode=yes "$PI" "bash '$STAGE/app/deploy/stale_files.sh' '$STAGE/app' $APP")"
REMOVE="$(echo "$STALE" | sed -n 's/^remove //p')"
LEFTOVER="$(echo "$STALE" | sed -n 's/^leftover //p')"
say "Removed from the Pi: no longer in the release"
if [[ -z "$REMOVE" ]]; then
    echo "      none"
else
    echo "$REMOVE" | sed 's/^/      /'
fi
if [[ -n "$LEFTOVER" ]]; then
    warn "Hand-made copies on the Pi, left alone (delete by hand if unwanted):"
    echo "$LEFTOVER" | sed "s|^|      $APP/|"
fi
if (( DRY_RUN )); then
    say "Dry run: nothing changed."
    exit 0
fi
[[ -z "$CHANGES" && -z "$REMOVE" ]] && { say "Nothing to deploy."; exit 0; }

# A restart in the middle of reading a scan throws that scan's progress
# away (the readings are cached, but the run starts over): wait until the
# processor has been quiet for a minute.
if (( ! FORCE )); then
    for attempt in $(seq 1 20); do
        busy="$(ssh -o BatchMode=yes "$PI" \
            "journalctl -u security-log-processor --since '-60 s' -o cat --no-pager | \
             grep -cE 'page\\(s\\) to read|Page [0-9]+/|Rendered|Turned|New scan detected' || true")"
        [[ "$busy" == 0 ]] && break
        (( attempt == 20 )) && die "The processor is still reading a scan; try later or use --force."
        warn "The processor is reading a scan; waiting ($attempt/20)"
        sleep 30
    done
fi

say "Installing on the Pi (sudo password)"
cat >"$WORK/.remote.sh" <<REMOTE
set -euo pipefail
cd '$STAGE'
# The venv is never changed from here: a pin that does not match what is
# installed (opencv 5.0.0 against the 5.0.0.93 running) would have pip
# swap out a working package. Asked first; a mismatch stops the deploy
# before anything is restarted.
# From a copy scanproc may read: it can enter neither the upload folder
# (mktemp's 0700) nor, through /dev/stdin, a pipe root opened.
requirements="\$(mktemp /tmp/nettune-requirements.XXXXXX)"
trap 'rm -f "\$requirements"' EXIT
install -m 0644 app/requirements.txt "\$requirements"
if ! pip_says="\$(sudo -u scanproc $APP/venv/bin/pip install --dry-run --no-cache-dir -q \
        -r "\$requirements" 2>&1)"; then
    echo "pip cannot satisfy requirements.txt (nothing restarted):"
    echo "\$pip_says" | tail -3
    exit 1
fi
missing="\$(echo "\$pip_says" | grep -i '^Would install' || true)"
if [[ -n "\$missing" ]]; then
    echo "The Pi's packages do not match requirements.txt: \$missing"
    echo "Nothing restarted. Review, then: sudo -u scanproc $APP/venv/bin/pip install -r $APP/requirements.txt"
    exit 1
fi
# The colleague sees "Panel en mantenimiento" while files change and the
# services restart, not a half-updated page. Only switched off again below
# if this deploy switched it on: a notice someone put up by hand
# (deploy/maintenance.sh on) stays up. A failure on the way leaves it on.
flag=$APP/state/MANTENIMIENTO
turned_on=0
if [[ ! -e "\$flag" ]]; then
    sudo -u scanproc touch "\$flag"
    turned_on=1
    echo "maintenance notice on"
fi
trap 'echo "The maintenance notice is still on; once fixed: deploy/maintenance.sh off"' ERR
rsync -rlc --chown=scanproc:scanproc --chmod=D755,F644 ${EXCLUDES[*]} app/ $APP/
# Decided again here, not taken from the laptop's listing: only what the
# script names now is removed, each path checked to stay inside the app.
bash app/deploy/stale_files.sh app $APP | sed -n 's/^remove //p' |
    while IFS= read -r path; do
        case "\$path" in ''|/*|*..*) echo "refusing to remove '\$path'"; exit 1 ;; esac
        rm -rf -- "$APP/\$path"
        echo "removed \$path"
    done
reload=0
for unit in security-log-processor.service nettune-dashboard.service \
            nettune-backup.service nettune-backup.timer; do
    if [[ -f /etc/systemd/system/\$unit ]] && ! cmp -s app/deploy/\$unit /etc/systemd/system/\$unit; then
        cp app/deploy/\$unit /etc/systemd/system/\$unit
        echo "updated \$unit"
        reload=1
    fi
done
(( reload )) && systemctl daemon-reload
echo "$COMMIT \$(date -Is)" > $APP/DEPLOYED
# Month folders laid out an older way move to the current layout, with the
# processor stopped so no scan is filed into a folder while it moves. A
# month already laid out the current way has nothing to move. A file left in
# place is listed, and does not stop the deploy.
systemctl stop security-log-processor
(cd $APP && sudo -u scanproc $APP/venv/bin/python tools/rename_month_folders.py | tail -5) \
    || echo "rename_month_folders left something in place; see above"
systemctl restart security-log-processor nettune-dashboard
sleep 3
systemctl is-active security-log-processor nettune-dashboard
if (( turned_on )); then
    rm -f "\$flag"
    echo "maintenance notice off"
else
    echo "maintenance notice left on (it was on before the deploy): deploy/maintenance.sh off"
fi
REMOTE
rsync -a "$WORK/.remote.sh" "$PI:$STAGE/remote.sh"
ssh -t "$PI" "sudo bash '$STAGE/remote.sh'" || die "Install failed on the Pi; see above."

say "Checking"
mismatch="$(ssh -o BatchMode=yes "$PI" "cd '$STAGE/app' && \
    rsync -rlcn --itemize-changes ${EXCLUDES[*]} ./ $APP/ | grep -E '^[<>c.]f' || true")"
[[ -z "$mismatch" ]] || die "Files on the Pi still differ from $COMMIT: $mismatch"
left="$(ssh -o BatchMode=yes "$PI" "bash '$STAGE/app/deploy/stale_files.sh' '$STAGE/app' $APP" |
    sed -n 's/^remove //p')"
[[ -z "$left" ]] || die "Files the release dropped are still on the Pi: $left"
status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://$PI:8080/")"
[[ "$status" == 200 || "$status" == 303 ]] || die "The dashboard answered $status."
say "Deployed $COMMIT: files match, both services running, dashboard answering."
