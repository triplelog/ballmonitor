#!/usr/bin/env bash
# Copy the box's nightly backups of the 27K multiplayer games to this computer (no sudo needed):
#   deploy/pull-backups.sh                 → ~/Backups/ballmonitor-27k/
#   DEST=/Volumes/x SERVER=user@host deploy/pull-backups.sh
# A copy off the box is what saves the games if the box itself is lost.
set -euo pipefail
SERVER="${SERVER:-rwilcox@64.177.56.111}"
DEST="${DEST:-$HOME/Backups/ballmonitor-27k}"
mkdir -p "$DEST"
rsync -a "$SERVER:/var/backups/ballmonitor-27k/" "$DEST/"
echo "$(ls "$DEST" | wc -l | tr -d ' ') backups in $DEST, newest: $(ls -1t "$DEST" | head -1)"
