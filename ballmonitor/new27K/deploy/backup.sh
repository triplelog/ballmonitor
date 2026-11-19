#!/bin/sh
# Nightly copy of the 27K multiplayer games, run on the box as root by ballmonitor-27k-backup.timer
# (installed by deploy/backup-units.sh). One .tar.gz per day in /var/backups/ballmonitor-27k, the
# newest $KEEP kept, readable by the deploy user's group so deploy/pull-backups.sh can copy them off
# the box without sudo.
set -eu
SRC=/var/lib/ballmonitor-27k
DIR=/var/backups/ballmonitor-27k
KEEP="${KEEP:-14}"
f="$DIR/27k-games-$(date +%F).tar.gz"
tar -czf "$f.tmp" -C "$(dirname "$SRC")" "$(basename "$SRC")"
chgrp "$(stat -c %G "$DIR")" "$f.tmp"
chmod 640 "$f.tmp"
mv "$f.tmp" "$f"
ls -1t "$DIR"/27k-games-*.tar.gz | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "backed up $(find "$SRC" -name '*.json' | wc -l) games to $f"
