"""Rebuild the bundled example games for cfb_replay from ESPN's summary API.

    ballmonitor fetch cfb_replay [--offline]

For each game in BUNDLED, downloads the summary (or, with --offline, reads the cached copy
in data/raw/summary_<id>.json), keeps the full response in data/raw/ (gitignored) and writes
a trimmed copy to data/games/<id>.json (committed, so examples and tests run offline).
Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

from ballmonitor.models.cfb_replay import espn

# Games bundled with the model (see MODEL.md "Example games" for why each was chosen).
BUNDLED = {
    "401858274": "Pittsburgh at Miami, 2026-10-24 (default example; lopsided)",
    "401858275": "Syracuse at North Carolina, 2026-10-24 (OT, lead changes, walk-off TD)",
    "401856834": "Baylor at Kansas, 2026-10-24 (25-24, blocked FG in final minute)",
}
TIMEOUT_SEC = 30.0


def fetch(model_dir: Path, offline: bool = False) -> list[str]:
    lines = []
    raw = espn.raw_dir(model_dir)
    raw.mkdir(parents=True, exist_ok=True)
    out_dir = espn.games_dir(model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for game_id, label in BUNDLED.items():
        cached = raw / f"summary_{game_id}.json"
        if offline:
            if not cached.exists():
                lines.append(f"skip {game_id}: no cached {cached.name} (run without --offline)")
                continue
            data = json.loads(cached.read_text(encoding="utf-8"))
        else:
            data = espn._get_json(espn.SUMMARY_URL.format(id=game_id), TIMEOUT_SEC)
            if not espn.is_summary(data):
                raise ValueError(f"ESPN has no summary for {game_id}")
            cached.write_text(json.dumps(data), encoding="utf-8")
        trimmed = espn.trim_summary(data)
        path = out_dir / f"{game_id}.json"
        path.write_text(json.dumps(trimmed, separators=(",", ":")), encoding="utf-8")
        plays = sum(len(d["plays"]) for d in trimmed["drives"]["previous"])
        lines.append(f"wrote {path.relative_to(model_dir)}: {label}; {plays} plays, "
                     f"{len(trimmed['winprobability'])} WP points, {path.stat().st_size // 1024} KB")
    return lines
