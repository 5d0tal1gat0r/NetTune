# Deploying to the Raspberry Pi (`rpi-n`, 100.64.0.10)

## The topology

The colleague's PC needs **no changes**. The Pi hosts the SMB share; their
existing mapped drive keeps pointing at `\\100.64.0.10\incoming_scans`.

```
Colleague's PC                    Raspberry Pi (rpi-n)
──────────────                    ────────────────────
mapped drive      ── Tailscale ──▶ smbd  ──▶ /srv/security_scans/incoming_scans/<MES>/
\\100.64.0.10\                              │
  incoming_scans                             │ inotify fires (the write is
                                             │ local to the Pi)
                                             ▼
                                    security-log-processor.service
                                             │
                                    OpenAI Vision → filtering agent → .docx
                                             │
                        ┌────────────────────┴────────────────────┐
                        ▼                                         ▼
     incoming_scans/<MES>/<ts>_Report.docx          processed_reports/<MES>/…
     (visible on the colleague's drive)             (canonical copy on the Pi)
                        │
                        ▼
     incoming_scans/<year>/<MES>/.escaneos_originales/<original scan>
```

**Why the Pi must host the share.** inotify does not fire for writes made by
an SMB or NFS *peer*. If the Pi mounted the colleague's folder instead, the
watcher would sit silent forever. With the Pi as the server, smbd performs the
write locally and inotify sees it. If you ever must invert this, use
`srv-security_scans-incoming_scans.mount.example` and set `WATCH_MODE=polling`.

## The memoria template

`templates/MEMORIA.docx` is **not in git**: it is the manager's own monthly
report, carrying the security contractor, the month's billing total and the
full list of units in the centre. Copy it onto the machine yourself:

```bash
scp "MEMORIA 2026 JUNIO.docx" pi:/opt/security_log_processor/templates/MEMORIA.docx
```

Any month's memoria works as the template. Keep one placeholder entry under
each of the five headings -- the four subheadings of 3.1.2 Correctivo and
"Intervenciones Seguridad:" -- because new entries are written by cloning an
existing one to inherit its list numbering and formatting. The service refuses
to start filling a block that has none rather than inventing a paragraph style.

## Install

From this repo, on the Pi:

```bash
git clone <this repo> ~/security_log_processor
cd ~/security_log_processor
sudo OPENAI_API_KEY=sk-... ./deploy/install.sh
```

The installer is idempotent. It creates the `scanproc` service user, builds
the venv, writes `/opt/security_log_processor/.env`, appends the Samba share
(backing up `smb.conf` first), and enables the service.

## Deploying an update

From the admin laptop, never by copying files by hand:

```bash
deploy/deploy.sh --dry-run   # what would change on the Pi; needs no sudo
deploy/deploy.sh             # deploy; asks for the Pi's sudo password once
```

It deploys exactly the commit at `HEAD` (uncommitted changes are listed and
left out), after the test suite passes on that same snapshot. It waits until
the processor is not reading a scan, writes only the files git tracks (never
`.env`, `state/`, `venv/`, `logs/` or `templates/`; tests and docs are not
shipped), updates any systemd unit that changed, restarts both services, and
checks that the files match, both services run and the dashboard answers. It
never changes the venv: if the Pi's packages do not satisfy
`requirements.txt`, it stops before restarting anything and says what pip
would do. The deployed commit is written to `/opt/security_log_processor/DEPLOYED`.


### Maintenance notice

While a deploy installs, anyone on the LAN who opens the dashboard sees
"Panel en mantenimiento" instead of the panel, and nothing they send is
written; the page reloads itself every 30 seconds and shows the dashboard
again once the services are back. From Tailscale the panel works as usual,
with a strip saying the notice is on.

For longer work on the Pi's live data (reprocessing a month, fixing the
database by hand), put the notice up yourself:

```bash
deploy/maintenance.sh on       # asks for the Pi's sudo password
deploy/maintenance.sh status   # needs no sudo
deploy/maintenance.sh off
```

A deploy never takes down a notice it did not put up, and a deploy that
fails halfway leaves its notice up: switch it off once the Pi is fixed.
The switch is the file `state/MANTENIMIENTO`.

## Verify

```bash
systemctl status security-log-processor
journalctl -u security-log-processor -f
smbclient -L //100.64.0.10 -N          # share must be listed
smbclient //100.64.0.10/incoming_scans -N -c 'ls'   # must NOT say BAD_NETWORK_NAME
```

Drop a JPEG into `incoming_scans/2026/AGOSTO/` from the colleague's mapped drive; a
`.docx` should appear beside it within a minute and the original should move
into `2026/AGOSTO/.escaneos_originales/` (hidden on the share).

## Configuration (`/opt/security_log_processor/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | — | required |
| `INCOMING_SCANS_DIR` | `incoming_scans` | watched tree |
| `OPENAI_MODEL` | `gpt-4o` | vision + analysis model |
| `WATCH_MODE` | `auto` | `auto` polls only on network mounts; force with `inotify`/`polling` |
| `POLL_INTERVAL` | `5` | seconds between polls in polling mode |
| `STABILITY_TIMEOUT` | `30` | seconds to wait for a scan's size to settle |
| `STATE_DB` | `state/processed.sqlite3` | dedupe ledger + cached stages |
| `WRITE_REPORT_BESIDE_SCAN` | `true` | also write the report into the month folder |
| `OPENAI_MODEL` | `gpt-5.4` | chosen for self-consistency: mini agreed with itself on 0% of entries, 5.4 on 91% |
| `READINGS_PER_PAGE` | `2` | two of gpt-5.4 measured better than three |
| `PDF_DPI` | `300` | PDF rasterisation resolution |
| `MONTHLY_BUDGET_EUR` | `5` | hard cap, enforced before every API call |
| `RETRY_BASE_DELAY` | `60` | seconds before the first retry, doubling thereafter |
| `RETRY_MAX_ATTEMPTS` | `4` | total attempts, not extra retries |
| `NOTIFY_TO` | — | who gets the "listo para revisar" email; empty sends nothing |
| `SMTP_HOST` / `SMTP_PORT` | — / `587` | mail server; 587 uses STARTTLS, 465 SSL |
| `SMTP_USER` / `SMTP_PASSWORD` | — | the sending account; for Gmail an app password |
| `SMTP_FROM` | `SMTP_USER` | sender shown on the email |
| `DASHBOARD_URL` | `http://localhost:8080` | the address the link in the email opens. The Tailscale address, `http://100.64.0.10:8080`, opens from anywhere; a LAN address only in the office |
| `DASHBOARD_HOSTNAMES` | *(empty)* | more names the dashboard answers to; its own `<hostname>.local` always works |
| `NOTIFY_SETTLE_SECONDS` | `120` | quiet time after the last scan before the email goes |

## Share security

The share is **guest-writable**, matching how the colleague's existing mapped
drive connects. Anyone who can reach port 445 on the Pi can read, write and
delete the whole scan tree. Once you have confirmed the colleague's PC reaches
the Pi over Tailscale rather than the LAN, lock it down:

```bash
sudo SAMBA_HOSTS_ALLOW="100.64.0.0/10 127.0.0.1" ./deploy/install.sh
```

The installer never restarts smbd (this box also serves printing, and a restart
would kill in-flight print jobs) -- it reloads. If `testparm` rejects the new
config it rolls `smb.conf` back to the backup it took and stops.

## The review dashboard

A second service, `nettune-dashboard`, serves the review page a colleague
uses to check the memoria against the sheets and correct what the model
misread. It shares the entry store and the scan tree with
`security-log-processor` but runs as its own process: the dashboard dying
does not stop transcription, and a stuck transcription does not take the
dashboard down with it.

Install it the same way, from this repo, on the Pi:

```bash
sudo cp deploy/nettune-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nettune-dashboard
```

It listens on port `8080`. Only two networks may reach it -- the centre's LAN
(`192.168.50.0/24`) and the Tailscale range (`100.64.0.0/10`), the same ranges
Samba is restricted to -- everything else gets refused before any route runs.
Within the Tailscale range the page also shows the technical numbers (spend,
model, service state); on the LAN it does not.

The colleague's bookmark is the Pi's name -- `http://raspberrypi.local:8080/`,
which keeps working when the router gives the Pi another address (the IP,
`http://192.168.50.37:8080/` today, works too) --
which redirects to whichever month has something in it to check.

```bash
systemctl status nettune-dashboard
journalctl -u nettune-dashboard -f
```

## Backups

The review work -- every correction, confirmation and hand-added line --
lives only in the three databases in `state/`. `nettune-backup.timer` copies
them every night at 02:30 into `/var/backups/nettune/YYYY-MM-DD/`, through
SQLite's backup API (a consistent copy while the services write), checks
each copy, and keeps 30 days. `install.sh` sets it up; on an existing Pi:

```bash
sudo install -d -o scanproc -g scanproc -m 0755 /var/backups/nettune
sudo cp deploy/nettune-backup.service deploy/nettune-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nettune-backup.timer
sudo systemctl start nettune-backup.service      # one now, to check
journalctl -u nettune-backup -n 20
```

Those copies are on the same SD card. Pull them off it from the admin
laptop, whenever it is on the tailnet -- they then survive the card dying:

```bash
deploy/pull_backups.sh            # into ~/NetTuneBackups, keeps everything
```

To restore a day: stop both services, copy its files over `state/`, start
them again.

## Troubleshooting

**`NT_STATUS_BAD_NETWORK_NAME` when connecting to the share.** The `path =` in
`/etc/samba/smb.conf` points at a directory that does not exist. Check it
matches `/srv/security_scans/incoming_scans`, then `sudo systemctl restart smbd`.

**Scans appear but nothing happens.** Confirm the watcher's mode:
`journalctl -u security-log-processor | grep Watching`. If the tree is on a
network mount it must say `polling`.

**A scan is stuck in the incoming folder.** Look for "Giving up on" in the
journal: after `RETRY_MAX_ATTEMPTS` failures the scan is left for manual review.
"The page looks blank" means the transcription came back empty and the scan was
deliberately not retried.

**Reports being re-processed.** Should be impossible — `.docx` is not in the
image allowlist — but the SHA-256 ledger in `STATE_DB` is the backstop. Delete
it only if you deliberately want everything reprocessed (and re-billed).
