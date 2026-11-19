#!/usr/bin/env bash
# Install (or update) the nightly backup of the 27K games on the box. Run from /srv/ballmonitor-27k
# by install.sh and deploy.sh; safe to re-run. Backups go to /var/backups/ballmonitor-27k, group-readable
# by the user who deploys (so deploy/pull-backups.sh can copy them home without sudo).
set -euo pipefail
cd "$(dirname "$0")/.."
sudo install -d -m 750 -o root -g "$(id -gn)" /var/backups/ballmonitor-27k
changed=0
for unit in ballmonitor-27k-backup.service ballmonitor-27k-backup.timer; do
	if ! cmp -s "deploy/$unit" "/etc/systemd/system/$unit"; then
		sudo install -m 644 "deploy/$unit" "/etc/systemd/system/$unit"
		changed=1
	fi
done
[ "$changed" = 1 ] && sudo systemctl daemon-reload
sudo systemctl enable --now ballmonitor-27k-backup.timer >/dev/null
echo "Backups: $(systemctl list-timers ballmonitor-27k-backup.timer --no-pager | sed -n 2p | awk '{print "next at", $1, $2, $3}')"
