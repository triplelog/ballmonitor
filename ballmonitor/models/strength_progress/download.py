"""Download the fit20 training-record file for the strength_progress research (data/raw/).

    python -m ballmonitor.models.strength_progress.download          # resumable, ~350 MB

Source: Steele, Fisher, Giessing, Androulakis-Korakakis, Wolf, Kroeske & Reuters (2022),
"Long-term time-course of strength adaptation to minimal dose resistance training through
retrospective longitudinal growth modeling", Research Quarterly for Exercise and Sport;
data and code on OSF project https://osf.io/jn6ay/ (CC BY 4.0).

The file URL is looked up through the OSF API (folder "Data and Code"), then fetched with
HTTP Range requests so an interrupted download continues where it stopped. Nothing here is
used at prediction time; `research.py` builds the small committed CSVs from the raw file.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

NODE = "jn6ay"
API = f"https://api.osf.io/v2/nodes/{NODE}/files/osfstorage/"
FOLDER = "Data and Code"
FILE = "fit20_final.csv"
HEADERS = {"User-Agent": "ballmonitor strength_progress research (open-source)"}
RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"
CHUNK = 1 << 20


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        return json.load(r)


def find_file(name: str = FILE) -> tuple[str, int]:
    """(download URL, size in bytes) of `name` in the OSF project's data folder."""
    for item in _get_json(API)["data"]:
        if item["attributes"]["kind"] == "folder" and item["attributes"]["name"] == FOLDER:
            href = item["relationships"]["files"]["links"]["related"]["href"]
            for f in _get_json(href)["data"]:
                if f["attributes"]["name"] == name:
                    return f["links"]["download"], int(f["attributes"]["size"])
    raise SystemExit(f"{name} not found in OSF project {NODE}")


def download(name: str = FILE, out_dir: Path = RAW_DIR) -> Path:
    url, size = find_file(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / name
    part = dest.with_suffix(dest.suffix + ".part")
    if dest.exists() and dest.stat().st_size == size:
        print(f"{dest} already complete ({size:,} bytes)")
        return dest
    have = part.stat().st_size if part.exists() else 0
    headers = dict(HEADERS)
    if have:
        headers["Range"] = f"bytes={have}-"
    print(f"{url} -> {dest} ({size:,} bytes, resuming at {have:,})")
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        mode = "ab" if have and r.status == 206 else "wb"
        if mode == "wb":
            have = 0
        with open(part, mode) as fh:
            while chunk := r.read(CHUNK):
                fh.write(chunk)
                have += len(chunk)
    if have != size:
        raise SystemExit(f"incomplete: {have:,} of {size:,} bytes; run again to resume")
    part.rename(dest)
    print(f"done: {dest}")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default=FILE, help="file name in the OSF 'Data and Code' folder")
    args = ap.parse_args()
    download(args.file)


if __name__ == "__main__":
    main()
