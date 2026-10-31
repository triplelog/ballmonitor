"""Export a cfb_replay timeline to a vertical MP4 (1080x1920, 30 fps, silent).

    ballmonitor export-replay --game 401858274 [--out replay.mp4] [--set duration_sec=25]

Runs the cfb_replay model, renders every frame with the same canvas renderer the website
uses (web/static/replay.js, via replay.html in headless Chrome) and pipes the frames to
ffmpeg (H.264, yuv420p, faststart — the format short-video apps expect).

Needs the optional `video` extra (`pip install -e '.[video]'`) and ffmpeg on PATH. Uses the
installed Google Chrome if present, else Playwright's Chromium (`playwright install chromium`).
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

from ballmonitor.core import registry

STATIC = Path(__file__).resolve().parent / "static"


def export(game: str | None, out: Path, overrides: dict, inputs_toml: str | None = None,
           fps: int | None = None, quality: float = 0.92, log=print) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH (macOS: brew install ffmpeg)")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("video export needs Playwright: pip install -e '.[video]'") from exc

    inputs = tomllib.loads(inputs_toml) if inputs_toml else {}
    if game:
        inputs["game"] = game
    model = registry.load_model("cfb_replay", None, overrides)
    pred = model.predict(inputs)
    extras = pred.to_dict()["extras"]
    timeline = extras["timeline"]
    fps = fps or int(timeline.get("fps", 30))
    duration = float(timeline["duration_sec"])
    frames = int(round(duration * fps))
    g = extras["game"]
    log(f"{g['away']['abbr']} at {g['home']['abbr']} ({g['date'][:10]}): {len(extras['plays'])} plays, "
        f"{duration:g}s at {fps} fps = {frames} frames")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(fps),
         "-i", "-", "-vf", "scale=in_range=full:out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto((STATIC / "replay.html").as_uri())
        page.wait_for_function("typeof window.loadReplay === 'function'")
        page.evaluate("data => window.loadReplay(data)", json.loads(json.dumps(extras, default=str)))
        for f in range(frames):
            data_url = page.evaluate("([t, q]) => window.renderAt(t, q)", [f / fps, quality])
            ffmpeg.stdin.write(base64.b64decode(data_url.split(",", 1)[1]))
            if f and f % (fps * 5) == 0:
                log(f"  rendered {f}/{frames} frames")
        browser.close()
    ffmpeg.stdin.close()
    if ffmpeg.wait() != 0:
        raise RuntimeError("ffmpeg failed to encode the video")
    log(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return out
