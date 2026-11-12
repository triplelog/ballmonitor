#!/usr/bin/env bash
# Installs 27k.caddy into the shared Caddy (on the server, from /srv/ballmonitor-27k/deploy).
#   ./caddy-site.sh           install and reload only if the file changed
#   ./caddy-site.sh --force   validate and reload even if it is unchanged
# Validates as the caddy user (as the service runs) and puts the previous file back if
# validation or the reload fails, so the other sites keep their working config.
set -euo pipefail
cd "$(dirname "$0")"
SITE=/etc/caddy/sites/27k.caddy
FORCE="${1:-}"

if ! grep -q 'import /etc/caddy/sites/\*.caddy' /etc/caddy/Caddyfile; then
	echo "error: /etc/caddy/Caddyfile does not import /etc/caddy/sites/*.caddy; not touching it." >&2
	exit 1
fi
if [ "$FORCE" != --force ] && sudo cmp -s 27k.caddy "$SITE"; then
	echo "Caddy site file unchanged."
	exit 0
fi

BACKUP=$(mktemp)
if sudo test -f "$SITE"; then sudo cp "$SITE" "$BACKUP"; else : > "$BACKUP"; fi
restore() {
	if [ -s "$BACKUP" ]; then sudo install -m 644 "$BACKUP" "$SITE"; else sudo rm -f "$SITE"; fi
}
validate() {
	sudo -u caddy -H caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
}

sudo install -m 644 27k.caddy "$SITE"
if ! validate >/tmp/27k.caddy-validate.log 2>&1; then
	tail -n 20 /tmp/27k.caddy-validate.log
	restore
	echo "error: Caddy config invalid; previous 27K site file restored, Caddy not reloaded." >&2
	exit 1
fi
if ! sudo systemctl reload caddy; then
	sudo journalctl -u caddy -n 20 --no-pager || true
	restore
	sudo systemctl reload caddy || true
	echo "error: Caddy reload failed (log above); previous 27K site file restored." >&2
	exit 1
fi
echo "Caddy site file installed and Caddy reloaded."
