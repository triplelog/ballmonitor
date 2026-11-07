#!/usr/bin/env python3
"""Record everything a COROS Live Tracking link exposes, to learn what can be extracted.

    python3 coros_watch.py https://s.coros.com/XJbwrsx0 [--out ~/coros-watch] [--before 15] [--after 60]

Standard library only. It does what the public tracking page (faq.coros.com/share/sport-live)
does, at the same pace, and saves every response:

- resolves the short link to its id/key/region and saves the page (its __INITIAL_STATE__ names
  the file hosts) plus the page's JavaScript, once;
- waits until `--before` minutes before the scheduled start (startTimestamp from the API),
  checking every 10 minutes meanwhile;
- then polls `<fastflow>/sport/live/query` at the interval the server asks for
  (`requestInterval`, 5 s), saving each new response;
- downloads every file the response points to (sport detail JSON, location files: text rows
  separated by ";") from the file host, keeping each new version;
- polls `/sport/live/queryAnnotation` (photos, voice notes, pins), asks
  `/sport/live/queryAnnotationFile` for new ones and downloads the files they point to;
- snapshots the page every 5 minutes;
- stops `--after` minutes after the scheduled end, or later if the activity is still running
  (never past `--max-hours` in total), then writes summary.txt and a .tar.gz of everything.

Output (under --out/<trip>/): page/, js/, query/*.json (each distinct response), query.jsonl
(every poll: time, status, headers, body), annotation/, files/<path>/<time>_<sha>.<ext>,
files.jsonl, log.txt, summary.txt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import sys
import tarfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
PAGE_ORIGIN = "https://faq.coros.com"
FASTFLOW = {"1": "https://fastflow.coros.com", "2": "https://fastflowcn.coros.com",
            "3": "https://fastfloweu.coros.com", "4": "https://fastflowsg.coros.com"}
DEFAULT_FILE_HOST = "https://map-oss-us.coros.com"
DEFAULT_INTERVAL = 5          # seconds; the server says requestInterval = 5
WAIT_CHECK_EVERY = 600        # while waiting for the start, query every 10 minutes
PAGE_EVERY = 300              # page snapshot every 5 minutes while active
STILL_RUNNING_WINDOW = 600    # keep going past the end while updates are newer than this (s)
STALE_WARN_AFTER = 120        # live but no new data from the watch for this long: say so (s)
STALE_WARN_EVERY = 300        # ...and repeat the warning this often (s)
PATH_KEYS = re.compile(r"(path|url|file|src|dir)", re.I)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def stamp(t: dt.datetime | None = None) -> str:
    return (t or now_utc()).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"


class Watcher:
    def __init__(self, url: str, out: Path, before: int, after: int, max_hours: float):
        self.share_url = url
        self.root_out = out
        self.before, self.after, self.max_hours = before, after, max_hours
        self.started = time.time()
        self.out: Path | None = None
        self.log_lines: list[str] = []
        self.last_query_body = None
        self.file_hashes: dict[str, str] = {}
        self.errors_saved: set[tuple[str, int]] = set()
        self.seen_annotations: set[str] = set()
        self.fetched_media: set[str] = set()
        self.last_annotation_body = None
        self.counts = {"polls": 0, "distinct_queries": 0, "file_versions": 0, "errors": 0,
                       "annotations": 0, "media": 0, "page_snapshots": 0}
        self.keys_seen: set[str] = set()
        self.statuses: list[tuple[str, object, object]] = []

    # ── plumbing ─────────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        line = f"{now_utc():%Y-%m-%d %H:%M:%S}Z {msg}"
        print(line, flush=True)
        self.log_lines.append(line)
        if self.out:
            with (self.out / "log.txt").open("a") as fh:
                fh.write(line + "\n")

    def http(self, url: str, data: dict | None = None, timeout: int = 20) -> tuple[int, dict, bytes, str]:
        headers = {"User-Agent": UA, "Origin": PAGE_ORIGIN, "Referer": PAGE_ORIGIN + "/",
                   "Accept": "application/json, text/plain, */*"}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json;charset=UTF-8"
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.status, dict(res.headers), res.read(), res.geturl()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read() or b"", url

    def save(self, rel: str, content: bytes) -> Path:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def append(self, rel: str, record: dict) -> None:
        with (self.out / rel).open("a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ── setup ────────────────────────────────────────────────────────────────
    def resolve(self) -> None:
        status, headers, body, final = self.http(self.share_url)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(final).query)
        self.id, self.key = q["id"][0], q["key"][0]
        self.region = q.get("regionId", ["1"])[0]
        self.fastflow = FASTFLOW.get(self.region, FASTFLOW["1"])
        html = body.decode("utf-8", "replace")
        m = re.search(r'"sportLiveFileHost":"([^"]+)"', html)
        self.file_host = m.group(1).replace("\\u002F", "/") if m else DEFAULT_FILE_HOST
        trip = self.query_once(record=False)
        trip_id = ((trip or {}).get("data") or {}).get("sportLiveTrip", {}).get("tripId") or self.id[:16]
        self.out = self.root_out / f"trip-{trip_id}"
        (self.out / "page").mkdir(parents=True, exist_ok=True)
        self.save(f"page/{stamp()}.html", body)
        self.save("page/final_url.txt", final.encode())
        for src in re.findall(r'https://static\.coros\.com/coros-web-faq/public/js/[^"\\]+\.js', html.replace("\\u002F", "/")):
            s, _, js, _ = self.http(src, timeout=60)
            if s == 200:
                self.save("js/" + src.rsplit("/", 1)[1], js)
        self.trip = (trip or {}).get("data", {}).get("sportLiveTrip", {})
        self.log(f"link -> id={self.id[:12]}... key={self.key} region={self.region} api={self.fastflow} "
                 f"files={self.file_host} out={self.out}")

    # ── one query poll ───────────────────────────────────────────────────────
    def query_once(self, record: bool = True) -> dict | None:
        url = f"{self.fastflow}/sport/live/query?id={self.id}&key={self.key}"
        t0 = now_utc()
        status, headers, body, _ = self.http(url)
        text = body.decode("utf-8", "replace")
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if not record:
            return data
        self.counts["polls"] += 1
        self.append("query.jsonl", {"t": t0.isoformat(), "status": status, "ms": round((now_utc() - t0).total_seconds() * 1000),
                                    "headers": {k: v for k, v in headers.items() if k.lower() in ("date", "etag", "last-modified", "v", "mr")},
                                    "body": data if data is not None else text[:5000]})
        if text != self.last_query_body:
            self.last_query_body = text
            self.counts["distinct_queries"] += 1
            self.save(f"query/{stamp(t0)}.json", body)
            if data:
                self.walk_keys(data.get("data"), "")
                trip = (data.get("data") or {}).get("sportLiveTrip") or {}
                self.statuses.append((t0.isoformat(), trip.get("status"), trip.get("updateTimestamp")))
                self.log(f"query: new response ({len(body)} B) status={trip.get('status')} "
                         f"update={trip.get('updateTimestamp')} keys={sorted((data.get('data') or {}).keys())}")
        return data

    def walk_keys(self, obj, prefix: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                self.keys_seen.add(f"{prefix}{k}")
                self.walk_keys(v, f"{prefix}{k}.")
        elif isinstance(obj, list):
            for v in obj[:3]:
                self.walk_keys(v, f"{prefix}[].")

    # ── files the response points to ─────────────────────────────────────────
    def file_refs(self, obj, key: str = "") -> list[str]:
        refs = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                refs += self.file_refs(v, k)
        elif isinstance(obj, list):
            for v in obj:
                refs += self.file_refs(v, key)
        elif isinstance(obj, str) and obj and PATH_KEYS.search(key or ""):
            if obj.endswith("/") or "s.coros.com" in obj or obj.startswith("https://faq."):
                return refs  # folders can't be listed; the share page itself is saved separately
            if "/" in obj or obj.startswith("http"):
                refs.append(obj)
        return refs

    def fetch_files(self, data: dict | None) -> None:
        for ref in dict.fromkeys(self.file_refs((data or {}).get("data"))):
            url = ref if ref.startswith("http") else f"{self.file_host}/{ref.lstrip('/')}"
            sep = "&" if "?" in url else "?"
            t0 = now_utc()
            status, headers, body, _ = self.http(f"{url}{sep}t={int(time.time() * 1000)}", timeout=30)
            sha = hashlib.sha1(body).hexdigest()[:10]
            changed = status == 200 and self.file_hashes.get(url) != sha
            self.append("files.jsonl", {"t": t0.isoformat(), "url": url, "status": status, "bytes": len(body),
                                        "sha": sha, "changed": changed,
                                        "headers": {k: v for k, v in headers.items()
                                                    if k.lower() in ("etag", "last-modified", "content-type", "content-length")}})
            if status != 200 and (url, status) not in self.errors_saved:  # e.g. 403 before the file exists
                self.errors_saved.add((url, status))
                self.save(f"files/_errors/{stamp(t0)}_{status}_{Path(urllib.parse.urlparse(url).path).name}.txt", body)
            if changed:
                self.file_hashes[url] = sha
                rel = urllib.parse.urlparse(url).path.lstrip("/")
                ext = Path(rel).suffix or ".txt"
                self.save(f"files/{rel}/{stamp(t0)}_{sha}{ext}", body)
                self.counts["file_versions"] += 1
                rows = body.count(b";")
                self.log(f"file: {rel} v{sha} {len(body)} B" + (f", {rows} ';' rows" if rows else ""))

    # ── photos, voice notes, pins ────────────────────────────────────────────
    def annotations(self) -> None:
        url = f"{self.fastflow}/sport/live/queryAnnotation?id={self.id}&key={self.key}"
        status, _, body, _ = self.http(url)
        text = body.decode("utf-8", "replace")
        if text == self.last_annotation_body:
            return
        self.last_annotation_body = text
        self.save(f"annotation/{stamp()}_list.json", body)
        try:
            items = json.loads(text).get("data") or []
        except ValueError:
            return
        ids = [str(i.get("annotationId")) for i in items if isinstance(i, dict) and i.get("annotationId")]
        new = [i for i in ids if i not in self.seen_annotations]
        self.log(f"annotations: {len(items)} listed, {len(new)} new")
        if not new:
            return
        self.seen_annotations.update(new)
        self.counts["annotations"] += len(new)
        s, _, fbody, _ = self.http(f"{self.fastflow}/sport/live/queryAnnotationFile",
                                   data={"id": self.id, "key": self.key, "annotationIdList": new})
        self.save(f"annotation/{stamp()}_files.json", fbody)
        try:
            fdata = json.loads(fbody)
        except ValueError:
            return
        for ref in dict.fromkeys(self.file_refs(fdata.get("data"))):
            url = ref if ref.startswith("http") else f"{self.file_host}/{ref.lstrip('/')}"
            if url in self.fetched_media:
                continue
            self.fetched_media.add(url)
            ms, _, media, _ = self.http(url, timeout=60)
            if ms == 200:
                self.save("annotation/media/" + urllib.parse.urlparse(url).path.lstrip("/"), media)
                self.counts["media"] += 1
                self.log(f"media: {url} {len(media)} B")

    def page_snapshot(self) -> None:
        status, _, body, _ = self.http(self.share_url)
        if status == 200:
            self.save(f"page/{stamp()}.html.gz", gzip.compress(body))
            self.counts["page_snapshots"] += 1

    # ── main loop ────────────────────────────────────────────────────────────
    def run(self) -> None:
        self.resolve()
        start = int(self.trip.get("startTimestamp") or time.time())
        end = int(self.trip.get("endTimestamp") or start + 3600)
        begin_at = start - self.before * 60
        stop_at = end + self.after * 60
        hard_stop = self.started + self.max_hours * 3600
        fmt = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")  # noqa: E731
        self.log(f"scheduled {fmt(start)} -> {fmt(end)}; recording {fmt(begin_at)} -> {fmt(stop_at)} "
                 f"(longer if still running, at most until {fmt(hard_stop)})")

        while time.time() < begin_at and time.time() < hard_stop:  # waiting: a check every 10 minutes
            self.guard(self.query_once)
            time.sleep(max(1, min(WAIT_CHECK_EVERY, begin_at - time.time())))

        self.log("recording")
        last_page = 0.0
        last_upd, last_upd_seen, last_warn = 0, time.time(), 0.0
        got_data = False
        while time.time() < hard_stop:
            tick = time.time()
            data = self.guard(self.query_once)
            self.guard(self.fetch_files, data)
            self.guard(self.annotations)
            if tick - last_page >= PAGE_EVERY:
                self.guard(self.page_snapshot)
                last_page = tick
            trip = ((data or {}).get("data") or {}).get("sportLiveTrip") or {}
            upd = int(trip.get("updateTimestamp") or 0)
            # COROS bumps updateTimestamp whenever the phone uploads; live but frozen = no data arriving
            if upd != last_upd:
                if last_upd and trip.get("status") == 1 and (not got_data or last_warn):
                    self.log("data arriving from the watch" + (" again" if got_data else ""))
                    got_data, last_warn = True, 0.0
                last_upd, last_upd_seen = upd, time.time()
            elif (trip.get("status") == 1 and time.time() - last_upd_seen > STALE_WARN_AFTER
                  and time.time() - last_warn > STALE_WARN_EVERY):
                mins = (time.time() - last_upd_seen) / 60
                self.log(f"WARNING: live but no new data from the watch for {mins:.0f} min "
                         "(is the phone connected to the watch, with the COROS app open?)")
                last_warn = time.time()
            if time.time() >= stop_at and not (upd and time.time() - upd < STILL_RUNNING_WINDOW):
                break
            interval = (data or {}).get("data", {}).get("requestInterval") if isinstance(data, dict) else None
            interval = interval if isinstance(interval, (int, float)) and 1 <= interval <= 120 else DEFAULT_INTERVAL
            time.sleep(max(0.5, interval - (time.time() - tick)))
        self.guard(self.page_snapshot)
        self.finish()

    def guard(self, fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 - keep recording through network hiccups
            self.counts["errors"] += 1
            self.log(f"error in {fn.__name__}: {type(e).__name__}: {e}")
            if self.counts["errors"] % 20 == 1:
                self.log(traceback.format_exc().strip().replace("\n", " | "))
            time.sleep(2)
            return None

    def finish(self) -> None:
        summary = {
            "share_url": self.share_url, "trip": self.trip, "counts": self.counts,
            "status_changes": self.statuses,
            "response_keys_seen": sorted(self.keys_seen),
            "files": {u: h for u, h in self.file_hashes.items()},
        }
        (self.out / "summary.txt").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        archive = self.out.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.out, arcname=self.out.name)
        self.log(f"done: {self.counts}; archive {archive} ({archive.stat().st_size // 1024} KB)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("url", help="the COROS Live Tracking link (https://s.coros.com/...)")
    ap.add_argument("--out", type=Path, default=Path.home() / "coros-watch")
    ap.add_argument("--before", type=int, default=15, help="start recording this many minutes before the scheduled start")
    ap.add_argument("--after", type=int, default=60, help="keep recording this many minutes after the scheduled end")
    ap.add_argument("--max-hours", type=float, default=30.0, help="never run longer than this in total")
    a = ap.parse_args(argv)
    Watcher(a.url, a.out.expanduser(), a.before, a.after, a.max_hours).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
