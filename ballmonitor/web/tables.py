"""Live data tables from tabdn table servers (tables.toml): which are on the site, and a check.

A table is on the site when its server has an address. `public()` gives what site.js needs
(written into data/site.json by the build); `check()` asks each server for its columns and
reports tables that don't answer or name columns the server doesn't have.
"""

from __future__ import annotations

import json
import tomllib
import urllib.request
from pathlib import Path

TABLES_FILE = Path(__file__).parent / "tables.toml"
BACKENDS = ("tabc", "sqldn")
REQUIRED = ("id", "title", "summary", "server", "path", "backend")


def load(path: Path = TABLES_FILE) -> dict:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = validate(cfg)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return cfg


def validate(cfg: dict) -> list[str]:
    errs, ids = [], set()
    servers = cfg.get("servers", {})
    for i, t in enumerate(cfg.get("table", [])):
        at = t.get("id", f"table {i + 1}")
        errs += [f"{at}: needs {k}" for k in REQUIRED if not t.get(k)]
        if t.get("id") in ids:
            errs.append(f"{at}: id used twice")
        ids.add(t.get("id"))
        if t.get("server") and t["server"] not in servers:
            errs.append(f"{at}: server {t['server']!r} is not in [servers]")
        if t.get("backend") and t["backend"] not in BACKENDS:
            errs.append(f"{at}: backend must be one of {BACKENDS}")
        if t.get("path") and not t["path"].endswith("/"):
            errs.append(f"{at}: path must end with /")
        for ex in t.get("examples", []):
            if not ex.get("label"):
                errs.append(f"{at}: every example needs a label")
    for name, url in servers.items():
        if url and not (url.startswith("https://") or url.startswith("http://")) or url and not url.endswith("/"):
            errs.append(f"server {name}: address must start with http(s):// and end with /")
    return errs


def address(cfg: dict, t: dict) -> str:
    """The table's address (server + path), or "" when its server has none yet."""
    base = cfg.get("servers", {}).get(t["server"], "")
    return base + t["path"] if base else ""


def public(cfg: dict | None = None) -> list[dict]:
    """The tables with a server address, as site.js uses them."""
    cfg = cfg or load()
    out = []
    for t in cfg.get("table", []):
        url = address(cfg, t)
        if not url:
            continue
        options = {k: t[k] for k in ("filter", "sort", "hidden", "limit", "computed", "stats", "table") if k in t}
        if t.get("order"):
            options["show"] = t["order"]   # tabview: only these columns, in this order (the rest can be ticked on)
        out.append({"id": t["id"], "title": t["title"], "summary": t["summary"], "sport": t.get("sport", ""),
                    "how": t.get("how", ""), "server": url, "backend": t["backend"], "options": options,
                    "examples": t.get("examples", []), "columns": t.get("columns", {})})
    return out


def check(cfg: dict | None = None, timeout: float = 10.0) -> list[tuple[str, bool, str]]:
    """(table id, ok, message) for every table with an address: does it answer, and does it have
    every column the config names (order, sort, column key)."""
    cfg = cfg or load()
    out = []
    for t in cfg.get("table", []):
        url = address(cfg, t)
        if not url:
            out.append((t["id"], True, f"skipped: server {t['server']!r} has no address yet"))
            continue
        meta = "meta.json" if t["backend"] == "sqldn" else "columns.json"
        try:
            with urllib.request.urlopen(url + meta, timeout=timeout) as res:
                info = json.loads(res.read())
        except Exception as exc:  # noqa: BLE001 - reported per table
            out.append((t["id"], False, f"{url}{meta}: {exc}"))
            continue
        have = column_names(info, t.get("table"))
        named = set(t.get("order", [])) | set(t.get("columns", {})) | ({t["sort"]["column"]} if t.get("sort") else set())
        missing = sorted(named - have) if have else []
        out.append((t["id"], not missing, f"{len(have)} columns" + (f"; not on the server: {', '.join(missing)}" if missing else "")))
    return out


def column_names(info: dict, table: str | None = None) -> set[str]:
    """Column names from tabc's columns.json ({"columns": [{"name": …}]}) or sqldn's meta.json
    ({"tables": [{"name": …, "columns": [{"name": …}]}]}: the named table, else every table's)."""
    if "tables" in info:
        tabs = [t for t in info["tables"] if table in (None, t["name"])]
        return {c["name"] for t in tabs for c in t.get("columns", [])}
    return {c["name"] for c in info.get("columns", [])}
