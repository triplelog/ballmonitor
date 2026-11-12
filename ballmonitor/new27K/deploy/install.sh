#!/usr/bin/env bash
# One-time setup of the 27K multiplayer server on the shared box (64.177.56.111, Ubuntu 24.04).
# deploy.sh copies the game to /srv/ballmonitor-27k and runs this the first time. Safe to re-run.
# It never edits the shared /etc/caddy/Caddyfile, ufw or other sites.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(pwd)" != /srv/ballmonitor-27k ]; then
	echo "error: run from /srv/ballmonitor-27k (the systemd unit expects that path)." >&2
	exit 1
fi

echo "==> Checking the box"
command -v caddy >/dev/null || { echo "error: Caddy is not installed." >&2; exit 1; }
command -v node >/dev/null || { echo "error: Node.js is not installed (the digitizer.fun games server uses it too)." >&2; exit 1; }
grep -q 'import /etc/caddy/sites/\*.caddy' /etc/caddy/Caddyfile || {
	echo "error: /etc/caddy/Caddyfile does not import /etc/caddy/sites/*.caddy." >&2; exit 1; }
if ss -ltn | grep -q '127.0.0.1:3004 ' && ! systemctl is-active --quiet ballmonitor-27k; then
	echo "error: port 3004 is already used by something else; pick another in deploy/ballmonitor-27k.service and deploy/27k.caddy." >&2
	exit 1
fi

echo "==> Dependencies (MathZetta, the formula reader)"
npm ci --omit=dev --no-audit --no-fund
chmod -R a+rX /srv/ballmonitor-27k

echo "==> Service user and state directory"
if ! getent passwd ballmonitor-27k >/dev/null; then
	sudo adduser --system --group --home /var/lib/ballmonitor-27k --shell /usr/sbin/nologin ballmonitor-27k
fi
sudo chmod 750 /var/lib/ballmonitor-27k

echo "==> systemd unit"
sudo install -m 644 deploy/ballmonitor-27k.service /etc/systemd/system/ballmonitor-27k.service
sudo systemctl daemon-reload
sudo systemctl enable ballmonitor-27k.service
sudo systemctl restart ballmonitor-27k.service
sleep 1
curl -fsS http://127.0.0.1:3004/api/mp/ping && echo "  ← 27K answers on 127.0.0.1:3004"

echo "==> Caddy site"
deploy/caddy-site.sh

echo
echo "Done. Check: curl https://27k.ballmonitor.com/api/mp/ping"
