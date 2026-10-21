# The P340 workbench

The ThinkStation P340 Tiny at home keeps every copy of the NetTune review
data and runs `ocr_feedback` on it. It only ever *reads* from the Pi; the Pi
sends nothing and does not notice when the P340 is off.

| machine | role |
|---|---|
| laptop | development: code, tests, deploys |
| Pi | production: pipeline + dashboard, writes `state/feedback.sqlite3` |
| P340 | data home: pulls backups, review images and original scans nightly, runs exports |

## 1. Disk and account (once)

The data holds names (raw readings, sheet images).

1. Put `~/NetTuneData` on an encrypted (LUKS) disk or partition.
2. `chmod 700 ~/NetTuneData`.
3. Do not share it outside the tailnet (no Samba, no sync service).

## 2. SSH keys and read-only account on the Pi (once: keys on P340, config on Pi)

### On the P340: Generate two SSH key pairs

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/nettune_backups
ssh-keygen -t ed25519 -N "" -f ~/.ssh/nettune_revision
```

### On the P340: Create ~/.ssh/config host aliases

Each alias points to the same Pi host but with its own key; `IdentitiesOnly yes` and `BatchMode yes` ensure unattended operation:

```
Host nettune-backups
    HostName 100.64.0.10
    User nettune-pull
    IdentityFile ~/.ssh/nettune_backups
    IdentitiesOnly yes
    BatchMode yes

Host nettune-revision
    HostName 100.64.0.10
    User nettune-pull
    IdentityFile ~/.ssh/nettune_revision
    IdentitiesOnly yes
    BatchMode yes
```

### On the P340: Verify and record the Pi's host key

```bash
ssh-keyscan -t ed25519 100.64.0.10 >> ~/.ssh/known_hosts
# Verify the fingerprint against the Pi's ssh output
```

### On the Pi: Create the nettune-pull account and authorize both keys

```bash
sudo adduser --disabled-password --gecos "" nettune-pull
sudo -u nettune-pull mkdir -p ~nettune-pull/.ssh
```

Add two lines to `~nettune-pull/.ssh/authorized_keys`; each key can read only its folder and only from the P340's Tailscale IP:

```bash
# Replace P340_TAILNET_IP with 100.x.y.z from the P340 and paste its nettune_backups key:
echo 'restrict,from="P340_TAILNET_IP",command="/usr/bin/rrsync -ro /var/backups/nettune" ssh-ed25519 AAAA... p340-backups' | \
    sudo -u nettune-pull tee -a ~nettune-pull/.ssh/authorized_keys

# Replace P340_TAILNET_IP and paste the nettune_revision key:
echo 'restrict,from="P340_TAILNET_IP",command="/usr/bin/rrsync -ro /srv/security_scans/incoming_scans" ssh-ed25519 AAAA... p340-revision' | \
    sudo -u nettune-pull tee -a ~nettune-pull/.ssh/authorized_keys

# Verify permissions
sudo -u nettune-pull ls /var/backups/nettune /srv/security_scans/incoming_scans
```

If the `.revision` folders are not readable by `nettune-pull`, add it to the group that owns them (`sudo adduser nettune-pull scanproc`) rather than widening permissions.

**Note:** On older Debian, `rrsync` is not at `/usr/bin/rrsync`. Copy it from `/usr/share/doc/rsync/scripts/rrsync` (possibly gunzipped) to `/usr/local/bin/rrsync`, then `chmod +x` it, and adjust the `command=` paths above.

## 3. Code and venv (once, then `git pull` to update)

```bash
git clone git@github.com:5d0tal1gat0r/NetTune.git ~/NetTune/security_log_processor
cd ~/NetTune/security_log_processor
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python -m pytest -q
```

## 4. Nightly pull (once, unattended setup)

### Copy the systemd units

```bash
mkdir -p ~/.config/systemd/user
cp deploy/workbench/nettune-pull.* ~/.config/systemd/user/
systemctl --user daemon-reload
```

### Test each pull manually before enabling the timer

Run each script in dry-run mode to verify SSH and rsync work without errors:

```bash
# Dry-run backups (does not write)
rsync -n -av --timeout=60 nettune-backups:./ ~/NetTuneData/backups/

# Dry-run revision images (does not write)
rsync -n -av --timeout=60 nettune-revision:./ ~/NetTuneData/revision/
```

Once both succeed, run the real pulls:

```bash
NETTUNE_SRC=nettune-backups:./ deploy/pull_backups.sh ~/NetTuneData/backups
NETTUNE_SRC=nettune-revision:./ deploy/pull_revision.sh ~/NetTuneData/revision
```

### Enable the timer

```bash
systemctl --user enable --now nettune-pull.timer
loginctl enable-linger "$USER"        # run while nobody is logged in
systemctl --user start nettune-pull.service   # first copy now
journalctl --user -u nettune-pull.service -n 20
```

Backups land in `~/NetTuneData/backups/YYYY-MM-DD/`, images in
`~/NetTuneData/revision/<year>/<MES>/.revision/`, and the original scan PDFs
in `~/NetTuneData/originals/<year>/<MES>/.escaneos_originales/`. The last two
use the same `nettune-revision` key; nothing changes on the Pi.

## 5. Export a month

```bash
cd ~/NetTune/security_log_processor
DAY=$(ls ~/NetTuneData/backups | tail -1)
./venv/bin/python -m ocr_feedback export \
    --profile feedback/nettune.toml \
    --feedback-db ~/NetTuneData/backups/$DAY/feedback.sqlite3 \
    --adapter nettune.ops.nettune_feedback:truth_source \
    --adapter-arg entries_db=$HOME/NetTuneData/backups/$DAY/memoria_entries.sqlite3 \
    --adapter-arg year=2026 --adapter-arg month=OCTUBRE \
    --out ~/NetTuneData/datasets --label 2026-10
```
Each export is a new folder; nothing is overwritten. Months from before
capture started export too, from the stored `original_text` only.
