"""Download the BMClab running-training dataset into data/raw/ (resumable, cached).

    python -m ballmonitor.models.running_progress.download              # weekly files (~59 MB)
    python -m ballmonitor.models.running_progress.download --levels w,d # + daily (~309 MB more)

Dataset: Afonseca LA, Watanabe RN, Duarte M (2022). "A public dataset on long-distance
running training in 2019 and 2020." PeerJ / Figshare, doi:10.6084/m9.figshare.16620238
(version 5), CC BY 4.0. One parquet file per year and aggregation level
(d = day, w = week, m = month, q = quarter); columns datetime, athlete, distance (km),
duration (min), gender, age_group, country, major.

The file list (names, sizes, md5) comes from the Figshare API, so nothing is hard-coded
but the article id. A file whose size and md5 already match is skipped; a partial file is
resumed with an HTTP Range request. Nothing here is used at prediction time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ARTICLE = "https://api.figshare.com/v2/articles/16620238"
HEADERS = {"User-Agent": "ballmonitor running_progress research (open-source; cached)"}
RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"
CHUNK = 1 << 20


def file_list() -> list[dict]:
    req = urllib.request.Request(ARTICLE, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as fh:
        return json.load(fh)["files"]


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def fetch(f: dict, out: Path) -> None:
    want = f.get("computed_md5") or f.get("supplied_md5")
    if out.exists() and out.stat().st_size == f["size"] and (not want or md5(out) == want):
        print(f"ok      {out.name}")
        return
    have = out.stat().st_size if out.exists() else 0
    if have > f["size"]:
        out.unlink()
        have = 0
    headers = dict(HEADERS)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(f["download_url"], headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        mode = "ab" if have and resp.status == 206 else "wb"
        with open(out, mode) as fh:
            while block := resp.read(CHUNK):
                fh.write(block)
    if want and md5(out) != want:
        raise RuntimeError(f"{out.name}: md5 mismatch; delete it and re-run")
    print(f"fetched {out.name} ({f['size'] / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--levels", default="w", help="comma list of d,w,m,q (default w)")
    ap.add_argument("--years", default="2019,2020")
    args = ap.parse_args()
    levels = set(args.levels.split(","))
    years = set(args.years.split(","))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for f in file_list():
        name = f["name"]
        if not name.startswith("run_ww_") or not name.endswith(".parquet"):
            continue
        _, _, year, level = name[: -len(".parquet")].split("_")
        if year in years and level in levels:
            fetch(f, RAW_DIR / name)


if __name__ == "__main__":
    main()
