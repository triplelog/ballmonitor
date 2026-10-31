"""Downloads you run yourself: NBA award PDFs, NHL (PHWA) ballot PDFs, AP women's ballot pages.

    python -m ballmonitor.models.ranked_choice.tools.download nba   [--dry-run] [--delay 5]
    python -m ballmonitor.models.ranked_choice.tools.download nhl   [--dry-run] [--delay 5]
    python -m ballmonitor.models.ranked_choice.tools.download ap-wbb URL [URL ...]

These sources are not fetched by `ballmonitor fetch` (or the daily build) because each site's
robots.txt asks automated crawlers to stay out of these paths:
  - NBA: `Disallow: /wp-content/uploads/` on ak-static.cms.nba.com, where the PDFs live.
  - NHL: the PHWA posts the ballots as Google Drive files; drive.google.com disallows `/uc`,
    the download endpoint.
  - AP: apnews.com blocks AI agents by name; its women's ballots exist only there.
Running this script is your decision, for your own non-commercial use; check each site's
terms first. It downloads only the specific public documents listed in the manifests
(`data/raw/nba/manifest.csv`, `data/raw/nhl/manifest.csv`), one at a time with a pause, using
the system `curl` with its normal user agent, never re-downloads a file it already has, and
stops at the first sign of rate limiting.

Run from the project folder (the one with pyproject.toml) after activating the venv:

    cd ~/Desktop/projects/ballmonitor && source .venv/bin/activate

Re-running picks up where it stopped (files already downloaded are skipped). Afterwards
rebuild the ballot files from what you downloaded:

    ballmonitor fetch ranked_choice --offline
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent.parent
RAW = MODEL_DIR / "data" / "raw"


def curl(url: str, out: Path) -> tuple[int, str]:
    """Download url to out with the system curl. Returns (HTTP status, content type)."""
    if not shutil.which("curl"):
        sys.exit("curl not found on PATH")
    tmp = out.with_suffix(out.suffix + ".part")
    res = subprocess.run(["curl", "-sS", "-L", "--max-time", "120", "-o", str(tmp),
                          "-w", "%{http_code} %{content_type}", url], capture_output=True, text=True)
    status, _, ctype = (res.stdout.strip() + "  ").partition(" ")
    code = int(status) if status.isdigit() else 0
    if code == 200 and tmp.exists():
        tmp.replace(out)
    else:
        tmp.unlink(missing_ok=True)
    return code, ctype.strip()


def is_pdf(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


def run_list(items: list[tuple[str, Path]], delay: float, dry: bool, need_pdf: bool = True) -> None:
    todo = [(u, p) for u, p in items if not p.exists() and not Path(str(p) + ".404").exists()]
    print(f"{len(items)} files listed, {len(items) - len(todo)} already here, {len(todo)} to download"
          + (" (dry run)" if dry else ""))
    ok = 0
    for n, (url, path) in enumerate(todo, 1):
        print(f"[{n}/{len(todo)}] {path.name}  <-  {url}")
        if dry:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        code, ctype = curl(url, path)
        if code in (403, 429) or code >= 500:
            print(f"  stopped: HTTP {code}. Try again later (or with a longer --delay).")
            break
        if code == 404:
            Path(str(path) + ".404").write_text("404\n")
            print("  404 - gone; won't retry")
        elif code != 200:
            print(f"  HTTP {code}; skipped")
        elif need_pdf and not is_pdf(path):
            path.rename(path.with_suffix(".notpdf.html"))
            print(f"  got {ctype or 'something'} instead of a PDF (saved as .notpdf.html); "
                  "download this one by hand in a browser")
        else:
            ok += 1
        time.sleep(delay)
    if not dry:
        print(f"downloaded {ok}. Next: ballmonitor fetch ranked_choice --offline")


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        sys.exit(f"{path} not found - run `ballmonitor fetch ranked_choice` once to build the manifests")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_nba(args) -> None:
    rows = [r for r in read_manifest(RAW / "nba" / "manifest.csv") if r["scope"] == "single_winner"]
    items = [(r["pdf_url"], RAW / "nba" / "pdf" / r["pdf_url"].rsplit("/", 1)[-1]) for r in rows]
    run_list(items, args.delay, args.dry_run)


def cmd_nhl(args) -> None:
    items = []
    for r in read_manifest(RAW / "nhl" / "manifest.csv"):
        m = re.search(r"/file/d/([\w-]+)", r["drive_url"])
        if m:
            items.append((f"https://drive.google.com/uc?export=download&id={m.group(1)}",
                          RAW / "nhl" / r["expected_file"]))
    run_list(items, args.delay, args.dry_run)


def cmd_ap_wbb(args) -> None:
    """Save AP women's ballot pages as-is (the parser is written from a saved page)."""
    out = RAW / "ap" / "wbb"
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    items = []
    for i, url in enumerate(args.urls):
        slug = re.sub(r"[^\w-]+", "-", url.split("://", 1)[-1])[:80].strip("-")
        items.append((url, out / f"{stamp}_{i}_{slug}.html"))
    run_list(items, args.delay, args.dry_run, need_pdf=False)
    print(f"saved under {out}. If the ballots are missing from the saved file (pages built by "
          "JavaScript), use the browser's File > Save Page As (complete page) instead.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("nba", cmd_nba), ("nhl", cmd_nhl)):
        p = sub.add_parser(name)
        p.add_argument("--dry-run", action="store_true", help="list what would be downloaded")
        p.add_argument("--delay", type=float, default=5.0, help="seconds between downloads (default 5)")
        p.set_defaults(fn=fn)
    p = sub.add_parser("ap-wbb", help="save AP women's poll ballot page(s) by URL")
    p.add_argument("urls", nargs="+")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delay", type=float, default=3.0)
    p.set_defaults(fn=cmd_ap_wbb)
    args = ap.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
