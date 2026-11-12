#!/usr/bin/env bash
# Ship the 27K multiplayer server to the shared box, install dependencies, and restart. Run from
# your own computer, in a terminal (sudo asks for a password):
#   deploy/deploy.sh                    (the default SERVER below)
#   SERVER=user@host deploy/deploy.sh
# The first run creates /srv/ballmonitor-27k and runs install.sh there.
set -euo pipefail
cd "$(dirname "$0")/.."             # the game folder (new27K)
SERVER="${SERVER:-rwilcox@64.177.56.111}"
REMOTE=/srv/ballmonitor-27k

ssh -t "$SERVER" "[ -d $REMOTE ] || (sudo mkdir -p $REMOTE && sudo chown \$(id -un): $REMOTE)"
# The server needs server/, src/ (the game engine it referees with), tools/serve.js, package*.json
# and deploy/. node_modules is installed on the box; games live in /var/lib, not here.
rsync -az --delete --exclude node_modules/ --exclude /data/ --exclude /dist/ --exclude /docs/ \
	--exclude /test/ --exclude /.git-27k-history/ --exclude '*.zip' --exclude .DS_Store \
	./ "$SERVER:$REMOTE/"

ssh -t "$SERVER" "set -e; cd $REMOTE; chmod -R a+rX $REMOTE
	if ! systemctl cat ballmonitor-27k.service >/dev/null 2>&1; then deploy/install.sh; exit; fi
	npm ci --omit=dev --no-audit --no-fund; chmod -R a+rX $REMOTE
	if ! cmp -s deploy/ballmonitor-27k.service /etc/systemd/system/ballmonitor-27k.service; then
		sudo install -m 644 deploy/ballmonitor-27k.service /etc/systemd/system/ballmonitor-27k.service && sudo systemctl daemon-reload
	fi
	sudo systemctl restart ballmonitor-27k
	deploy/caddy-site.sh
	sleep 1
	systemctl is-active ballmonitor-27k caddy
	curl -fsS http://127.0.0.1:3004/api/mp/ping && echo '  ← 27K answers on 127.0.0.1:3004'"
