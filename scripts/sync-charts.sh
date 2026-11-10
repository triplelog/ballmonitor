#!/bin/sh
# Copy pyslots' baseball charts into Ball Monitor: ballmonitor/charts/ (committed, so the daily CI
# build needs nothing outside this repo), served at /charts/ and shown at #/charts (site.js).
#
#   embed/pyslots-embed.js, embed/inlinemath/   the embeddable form (Python runs in the visitor's
#                                               browser, Pyodide from jsDelivr) and its maths styles
#   examples/index.json, charts/*.py, data/     the chart templates (formula slots) and their data
#
# pyslots lives in the mathzetta collection (~/Desktop/portfolio/mathzetta/pyslots; PYSLOTS overrides).
# Run this after changing a template or the form there; the population model (models/) stays there.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
src=${PYSLOTS:-$here/../../mathzetta/pyslots}
[ -f "$src/web/embed.js" ] || { echo "no pyslots at $src (set PYSLOTS)" >&2; exit 1; }
(cd "$src" && npm run --silent build)
out=$here/ballmonitor/charts
rm -rf "$out"
mkdir -p "$out/embed" "$out/examples/charts" "$out/examples/data"
cp "$src/dist/pyslots-embed.js" "$out/embed/"
cp -R "$src/dist/inlinemath" "$out/embed/"
cp "$src"/examples/charts/*.py "$out/examples/charts/"
cp "$src"/examples/data/*.csv "$src/examples/data/README.md" "$out/examples/data/"
# the chart templates only
node -e '
const fs = require("fs");
const all = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
fs.writeFileSync(process.argv[2], JSON.stringify(all.filter((t) => t.file.startsWith("charts/")), null, 1) + "\n");
' "$src/examples/index.json" "$out/examples/index.json"
cat > "$out/README.md" <<'TXT'
# Baseball charts (copied from pyslots: scripts/sync-charts.sh)

Don't edit these files here: change them in pyslots (~/Desktop/portfolio/mathzetta/pyslots) and run
`scripts/sync-charts.sh` again. The data is from the Lahman Baseball Database (CC BY-SA 3.0; see
examples/data/README.md).
TXT
du -sh "$out"
