"""Universal URL Ingestion Engine for Race Results.

Supports:
1. Native API integration for RunSignup URLs (auto-extracting race_id and event results)
2. Generic HTML Table Extractor with fuzzy semantic column resolution (place, name, age, gender, time)
3. Monospace ASCII / Preformatted text parser (<pre> tags from legacy timing services)
4. Local SQLite database caching (data/races.db) for instant re-queries
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


@dataclass
class FinishRecord:
    place: int
    first_name: str
    last_name: str
    gender: str  # 'M', 'F', or 'X'
    age: int | None
    chip_time_sec: float
    chip_time_str: str
    division: str | None = None


# Semantic column matcher regexes
COLUMN_PATTERNS = {
    "place": re.compile(
        r"^(?:(?:o['a]?ll|overall)?\s*(?:place|pl|rank|pos|#)|place|rank|pos|overall|oa|o'all|#)$",
        re.IGNORECASE,
    ),
    "name": re.compile(
        r"^(?:runner\s*name|athlete(?:\s*name)?|name|participant|runner|full\s*name)$",
        re.IGNORECASE,
    ),
    "first_name": re.compile(r"^(?:first(?:\s*name)?|fname)$", re.IGNORECASE),
    "last_name": re.compile(r"^(?:last(?:\s*name)?|lname|surname)$", re.IGNORECASE),
    "bib": re.compile(r"^(?:bib(?:\s*#)?|bib\s*num|no|num)$", re.IGNORECASE),
    "age": re.compile(r"^(?:age|ag|a)$", re.IGNORECASE),
    "gender": re.compile(r"^(?:sex|gender|g|s|m/f)$", re.IGNORECASE),
    "chip_time": re.compile(
        r"^(?:chip\s*time|net\s*time|chip|net|time|finish(?:\s*time)?|clock\s*time|gun\s*time)$",
        re.IGNORECASE,
    ),
    "gun_time": re.compile(r"^(?:gun\s*time|clock\s*time|clock|gun)$", re.IGNORECASE),
    "pace": re.compile(r"^(?:pace|min/mi|min/km|avg\s*pace)$", re.IGNORECASE),
    "division": re.compile(r"^(?:div(?:\s*place)?|division|age\s*group|ag\s*place|cat)$", re.IGNORECASE),
}


def parse_time_to_seconds(t_str: str) -> float | None:
    """Parse h:mm:ss.s or mm:ss.s into total seconds."""
    clean = t_str.strip()
    m = re.match(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$", clean)
    if not m:
        return None
    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2))
    seconds = int(m.group(3))
    fraction = float(f"0.{m.group(4)}") if m.group(4) else 0.0
    return hours * 3600 + minutes * 60 + seconds + fraction


def format_seconds_to_time(sec: float) -> str:
    total_sec = round(sec, 1)
    h = int(total_sec // 3600)
    m = int((total_sec % 3600) // 60)
    s = total_sec % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:04.1f}" if s % 1 else f"{h}:{m:02d}:{int(s):02d}"
    return f"{m}:{s:04.1f}" if s % 1 else f"{m}:{int(s):02d}"


class RaceResultsIngester:
    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = Path(__file__).parent / "data" / "races.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite caching schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS races (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT UNIQUE,
                    platform TEXT,
                    race_name TEXT,
                    distance_cat TEXT,
                    city TEXT,
                    state TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id INTEGER REFERENCES races(id),
                    year INTEGER,
                    date TEXT,
                    temp_f REAL,
                    dew_point_f REAL,
                    total_finishers INTEGER
                );

                CREATE TABLE IF NOT EXISTS finishes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER REFERENCES events(id),
                    place INTEGER,
                    first_name TEXT,
                    last_name TEXT,
                    gender TEXT,
                    age INTEGER,
                    chip_time_sec REAL,
                    chip_time_str TEXT,
                    division TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_races_url ON races(source_url);
                CREATE INDEX IF NOT EXISTS idx_finishes_event ON finishes(event_id);
            """)

    def ingest_url(
        self, url: str, force_refresh: bool = False, html: str | None = None
    ) -> tuple[dict[str, Any], list[FinishRecord]]:
        """Ingest results from any race URL (RunSignup, HTML table, or ASCII text).

        Returns metadata dict and list of FinishRecord items.
        """
        # 1. Check database cache (only if html not provided directly)
        if not force_refresh and html is None:
            cached = self._load_from_db(url)
            if cached:
                return cached

        # 2. Identify platform / handler
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc.lower()

        if "runsignup.com" in domain and html is None:
            meta, records = self._ingest_runsignup(url)
        else:
            meta, records = self._ingest_generic_web(url, html=html)

        # 3. Store in SQLite cache if finishes were found
        if records:
            self._save_to_db(url, meta, records)

        return meta, records

    def discover_race_years(self, url: str, html: str | None = None) -> dict[int, str]:
        """Discover URLs for previous years from a race results page or platform API.

        Discovers:
        1. RunSignup API result sets if a RunSignup URL.
        2. HTML <select> dropdown menus containing year options.
        3. Archive navigation links (<a> tags) linking to past editions.
        4. URL pattern variations if a 4-digit year is present in the URL path or query.

        Returns a dict mapping {year: url} sorted descending by year.
        """
        discovered: dict[int, str] = {}
        parsed_base = urllib.parse.urlparse(url)
        base_domain = parsed_base.netloc.lower()

        # Detect current year from URL if present
        url_year_match = re.search(r"\b(20\d\d|19\d\d)\b", url)
        current_year = int(url_year_match.group(1)) if url_year_match else None
        if current_year:
            discovered[current_year] = url

        # 1. RunSignup platform handling
        if "runsignup.com" in base_domain:
            m = re.search(r"/Race/Results/(\d+)", url, re.IGNORECASE) or re.search(r"/Race/(\d+)/Results", url, re.IGNORECASE)
            if m:
                race_id = m.group(1)
                try:
                    rs_url = f"https://runsignup.com/rest/race/{race_id}/results/get-result-sets?format=json"
                    req = urllib.request.Request(rs_url, headers={"User-Agent": "ballmonitor-race-podium/0.5.0"})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        rs_data = json.loads(resp.read().decode("utf-8"))
                        for rset in rs_data.get("result_sets", []):
                            rset_id = rset.get("result_set_id")
                            name = rset.get("name", "")
                            ym = re.search(r"\b(20\d\d|19\d\d)\b", name) or re.search(
                                r"\b(20\d\d|19\d\d)\b", rset.get("event_date", "")
                            )
                            if ym and rset_id:
                                yr = int(ym.group(1))
                                discovered[yr] = f"https://runsignup.com/Race/Results/{race_id}?resultSetId={rset_id}"
                except Exception:
                    pass

        # If html is not provided and not runsignup (or runsignup returned nothing), fetch page html
        if html is None and "runsignup.com" not in base_domain:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ballmonitor/0.5.0)"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    html = resp.read().decode("utf-8", errors="replace")
            except Exception:
                html = None

        if not html:
            # URL pattern fallback
            if len(discovered) <= 1 and current_year:
                for past_y in range(current_year - 1, max(current_year - 5, 2015), -1):
                    if past_y not in discovered:
                        discovered[past_y] = url.replace(str(current_year), str(past_y))
            return {y: discovered[y] for y in sorted(discovered.keys(), reverse=True)}

        soup = BeautifulSoup(html, "html.parser")

        # 2. Check <select> dropdowns for year selectors
        selects = soup.find_all("select")
        for sel in selects:
            attrs_str = " ".join([
                sel.get("name", ""),
                sel.get("id", ""),
                " ".join(sel.get("class", [])),
            ]).lower()

            options = sel.find_all("option")
            has_year_options = False
            sel_matches: list[tuple[int, str]] = []

            form = sel.find_parent("form")
            form_action = form.get("action", "") if form else ""

            for opt in options:
                opt_text = opt.get_text(strip=True)
                opt_val = opt.get("value", "").strip()
                data_url = opt.get("data-url", "") or opt.get("data-href", "")

                ym = re.search(r"\b(19\d\d|20\d\d)\b", opt_text) or re.search(r"\b(19\d\d|20\d\d)\b", opt_val)
                if ym:
                    year = int(ym.group(1))
                    if 1980 <= year <= 2035:
                        has_year_options = True
                        target_url = None
                        if data_url:
                            target_url = urllib.parse.urljoin(url, data_url)
                        elif opt_val.startswith("http://") or opt_val.startswith("https://") or opt_val.startswith("/"):
                            target_url = urllib.parse.urljoin(url, opt_val)
                        elif form_action:
                            param_name = sel.get("name", "year")
                            sep = "&" if "?" in form_action else "?"
                            target_url = urllib.parse.urljoin(url, f"{form_action}{sep}{param_name}={opt_val}")
                        elif current_year and str(year) in opt_val:
                            target_url = url.replace(str(current_year), str(year))
                        else:
                            parsed = urllib.parse.urlparse(url)
                            qs = urllib.parse.parse_qs(parsed.query)
                            param_name = sel.get("name", "year")
                            qs[param_name] = [str(opt_val or year)]
                            new_query = urllib.parse.urlencode(qs, doseq=True)
                            target_url = urllib.parse.urlunparse(parsed._replace(query=new_query))

                        if target_url:
                            sel_matches.append((year, target_url))

            is_year_select = (
                any(w in attrs_str for w in ("year", "past", "history", "archive", "edition", "event", "date", "season"))
                or has_year_options
            )
            if is_year_select:
                for y, u in sel_matches:
                    discovered[y] = u

        # 3. Check <a> links for year archives
        links = soup.find_all("a", href=True)
        for a in links:
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            text = a.get_text(strip=True)
            combined = f"{text} {href}".lower()

            ym = re.search(r"\b(19\d\d|20\d\d)\b", text) or re.search(r"\b(19\d\d|20\d\d)\b", href)
            if ym:
                year = int(ym.group(1))
                if 1980 <= year <= 2035:
                    context = f"{combined} {' '.join(a.get('class', []))} {a.parent.get('class', []) if a.parent else ''}".lower()
                    is_archive_link = (
                        any(w in context for w in ("result", "past", "history", "archive", "edition", "previous", "prior", "race"))
                        or len(text.strip()) == 4
                        or f"/{year}" in href
                        or f"year={year}" in href
                    )
                    if is_archive_link:
                        abs_url = urllib.parse.urljoin(url, href)
                        if year not in discovered or not discovered[year]:
                            discovered[year] = abs_url

        # 4. Pattern fallback if only 1 year was found and original URL has a year
        if len(discovered) <= 1 and current_year:
            for past_y in range(current_year - 1, max(current_year - 5, 2015), -1):
                if past_y not in discovered:
                    discovered[past_y] = url.replace(str(current_year), str(past_y))

        return {y: discovered[y] for y in sorted(discovered.keys(), reverse=True)}

    def ingest_multi_year(
        self,
        url: str,
        max_years: int = 5,
        html_by_url: dict[str, str] | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Discover and ingest multiple years of race results starting from a URL.

        Returns a list of dicts:
        [{"year": int, "url": str, "records": list[FinishRecord], "meta": dict, "total_finishers": int}, ...]
        sorted descending by year.
        """
        primary_html = html_by_url.get(url) if html_by_url else None
        discovered_years = self.discover_race_years(url, html=primary_html)
        if not discovered_years:
            discovered_years = {2024: url}

        editions: list[dict[str, Any]] = []
        for year, year_url in sorted(discovered_years.items(), reverse=True)[:max_years]:
            sub_html = html_by_url.get(year_url) if html_by_url else None
            try:
                meta, records = self.ingest_url(year_url, force_refresh=force_refresh, html=sub_html)
                if records:
                    meta["year"] = year
                    editions.append({
                        "year": year,
                        "url": year_url,
                        "meta": meta,
                        "records": records,
                        "total_finishers": len(records),
                    })
            except Exception:
                continue

        return editions

    def _ingest_runsignup(self, url: str) -> tuple[dict[str, Any], list[FinishRecord]]:
        """Fetch results directly via RunSignup public REST API."""
        m = re.search(r"/Race/Results/(\d+)", url, re.IGNORECASE) or re.search(r"/Race/(\d+)/Results", url, re.IGNORECASE)
        if not m:
            raise ValueError(f"Could not extract race_id from RunSignup URL: {url}")
        race_id = m.group(1)

        # Fetch race details to locate events
        req = urllib.request.Request(
            f"https://runsignup.com/rest/race/{race_id}?format=json",
            headers={"User-Agent": "ballmonitor-race-podium/0.5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        race_obj = data.get("race", {})
        race_name = race_obj.get("name", "RunSignup Race")
        events = race_obj.get("events", [])
        city = race_obj.get("address", {}).get("city")
        state = race_obj.get("address", {}).get("state")

        # Pick primary running event
        target_event = None
        for ev in events:
            dist = ev.get("distance", "")
            if any(d in dist.lower() for d in ("5k", "10k", "half", "marathon", "mile")):
                target_event = ev
                break
        if not target_event and events:
            target_event = events[0]

        records: list[FinishRecord] = []
        if target_event:
            event_id = target_event["event_id"]
            results_url = f"https://runsignup.com/rest/race/{race_id}/results/get-results?event_id={event_id}&format=json&num=500"
            req2 = urllib.request.Request(results_url, headers={"User-Agent": "ballmonitor-race-podium/0.5.0"})
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                res_data = json.loads(resp2.read().decode("utf-8"))

            for set_item in res_data.get("individual_result_sets", []):
                for row in set_item.get("results", []):
                    try:
                        time_sec = float(row.get("chip_time") or row.get("clock_time") or 0)
                        if time_sec <= 0:
                            continue
                        age = int(row["age"]) if row.get("age") and str(row["age"]).isdigit() else None
                        records.append(
                            FinishRecord(
                                place=int(row.get("place", len(records) + 1)),
                                first_name=row.get("first_name", "Runner").strip().title(),
                                last_name=row.get("last_name", "").strip().title(),
                                gender=row.get("gender", "M").strip().upper()[:1],
                                age=age,
                                chip_time_sec=time_sec,
                                chip_time_str=format_seconds_to_time(time_sec),
                                division=row.get("division"),
                            )
                        )
                    except (ValueError, KeyError):
                        continue

        meta = {
            "platform": "runsignup",
            "race_name": race_name,
            "city": city,
            "state": state,
            "total_finishers": len(records),
        }
        return meta, records

    def _ingest_generic_web(
        self, url: str, html: str | None = None
    ) -> tuple[dict[str, Any], list[FinishRecord]]:
        """Fetch and parse generic HTML tables or ASCII text from arbitrary web URL."""
        if html is None:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ballmonitor/0.5.0)"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_bytes = resp.read()
            html_text = raw_bytes.decode("utf-8", errors="replace")
        else:
            html_text = html

        soup = BeautifulSoup(html_text, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else "Road Race"

        # 1. Try HTML Table parsing
        records = self._parse_html_tables(soup)

        # 2. If no table, try <pre> tag ASCII parsing
        if not records:
            pre_tags = soup.find_all("pre")
            for tag in pre_tags:
                records = self._parse_ascii_text(tag.get_text())
                if records:
                    break

        m_yr = re.search(r"\b(20\d\d|19\d\d)\b", title) or re.search(r"\b(20\d\d|19\d\d)\b", url)
        year_val = int(m_yr.group(1)) if m_yr else 2024

        meta = {
            "platform": "generic_html",
            "race_name": title,
            "year": year_val,
            "total_finishers": len(records),
        }
        return meta, records

    def _parse_html_tables(self, soup: BeautifulSoup) -> list[FinishRecord]:
        """Extract finishes from HTML table using fuzzy semantic header matching."""
        tables = soup.find_all("table")
        if not tables:
            return []

        best_table = max(tables, key=lambda t: len(t.find_all("tr")))
        rows = best_table.find_all("tr")
        if len(rows) < 2:
            return []

        # Find header row
        header_idx = -1
        col_mapping: dict[int, str] = {}
        for r_idx, row in enumerate(rows[:5]):
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            mapping = {}
            for c_idx, text in enumerate(cells):
                clean_text = re.sub(r"[^\w\s/'#]", "", text).strip()
                for col_name, pattern in COLUMN_PATTERNS.items():
                    if pattern.match(clean_text) and col_name not in mapping.values():
                        mapping[c_idx] = col_name
                        break
            if "chip_time" in mapping.values() or "name" in mapping.values():
                header_idx = r_idx
                col_mapping = mapping
                break

        if not col_mapping or header_idx == -1:
            return []

        records: list[FinishRecord] = []
        for row in rows[header_idx + 1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < len(col_mapping) / 2:
                continue

            entry: dict[str, Any] = {}
            for c_idx, col_name in col_mapping.items():
                if c_idx < len(cells):
                    entry[col_name] = cells[c_idx]

            raw_time = entry.get("chip_time") or entry.get("gun_time") or ""
            sec = parse_time_to_seconds(raw_time)
            if sec is None or sec <= 0:
                continue

            # Split name if needed
            full_name = entry.get("name", "")
            if full_name:
                parts = full_name.split(None, 1)
                fn = parts[0]
                ln = parts[1] if len(parts) > 1 else ""
            else:
                fn = entry.get("first_name", "Runner")
                ln = entry.get("last_name", "")

            # Age
            age_val = None
            if "age" in entry and str(entry["age"]).isdigit():
                age_val = int(entry["age"])

            # Gender
            g = entry.get("gender", "M").strip().upper()
            g_clean = "F" if g.startswith("F") else "M"

            # Place
            place_str = entry.get("place", str(len(records) + 1))
            place_val = int(re.sub(r"\D", "", place_str)) if re.search(r"\d", place_str) else len(records) + 1

            records.append(
                FinishRecord(
                    place=place_val,
                    first_name=fn.title(),
                    last_name=ln.title(),
                    gender=g_clean,
                    age=age_val,
                    chip_time_sec=sec,
                    chip_time_str=format_seconds_to_time(sec),
                    division=entry.get("division"),
                )
            )

        return records

    def _parse_ascii_text(self, text: str) -> list[FinishRecord]:
        """Extract finishes from monospace ASCII text (<pre> tags)."""
        import textwrap

        text = textwrap.dedent(text)
        lines = [line.rstrip() for line in text.strip().split("\n") if line.strip()]
        if len(lines) < 3:
            return []

        header_idx = -1
        col_spans: list[tuple[int, str]] = []
        for l_idx, line in enumerate(lines[:10]):
            words = re.finditer(r"\b\w+(?:['#]\w+)?\b", line)
            matches = []
            for w in words:
                word_text = w.group(0)
                for col_name, pattern in COLUMN_PATTERNS.items():
                    if pattern.match(word_text):
                        matches.append((w.start(), col_name))
                        break
            if len(matches) >= 3:
                header_idx = l_idx
                col_spans = sorted(matches, key=lambda x: x[0])
                break

        if not col_spans:
            return []

        spans: list[tuple[int, int | None, str]] = []
        for i in range(len(col_spans)):
            start = col_spans[i][0]
            col = col_spans[i][1]
            end = col_spans[i + 1][0] if i + 1 < len(col_spans) else None
            spans.append((start, end, col))

        start_row = header_idx + 1
        if start_row < len(lines) and re.match(r"^[\s=\-]+$", lines[start_row]):
            start_row += 1

        records: list[FinishRecord] = []
        for line in lines[start_row:]:
            if len(line.strip()) < 10 or re.match(r"^[\s=\-]+$", line):
                continue
            entry: dict[str, Any] = {}
            for start, end, col_name in spans:
                val = line[start:end].strip() if end else line[start:].strip()
                if col_name in ("age", "gender", "place"):
                    val = val.split()[0] if val.split() else ""
                entry[col_name] = val

            raw_time = entry.get("chip_time") or entry.get("gun_time") or ""
            sec = parse_time_to_seconds(raw_time)
            if sec is None:
                # Fallback: search for time regex on the line
                t_match = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\b", line)
                if t_match:
                    raw_time = t_match.group(1)
                    sec = parse_time_to_seconds(raw_time)

            if sec is None or sec <= 0:
                continue

            full_name = entry.get("name", "Runner")
            parts = full_name.split(None, 1)
            fn = parts[0]
            ln = parts[1] if len(parts) > 1 else ""

            age_val = int(entry["age"]) if "age" in entry and str(entry["age"]).isdigit() else None
            g = entry.get("gender", "M").strip().upper()
            g_clean = "F" if g.startswith("F") else "M"
            place_val = int(entry["place"]) if "place" in entry and str(entry["place"]).isdigit() else len(records) + 1

            records.append(
                FinishRecord(
                    place=place_val,
                    first_name=fn.title(),
                    last_name=ln.title(),
                    gender=g_clean,
                    age=age_val,
                    chip_time_sec=sec,
                    chip_time_str=format_seconds_to_time(sec),
                    division=entry.get("division"),
                )
            )

        return records

    def _save_to_db(self, url: str, meta: dict[str, Any], records: list[FinishRecord]) -> None:
        """Cache scraped race into local SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO races (source_url, platform, race_name, city, state) VALUES (?, ?, ?, ?, ?)",
                (url, meta.get("platform"), meta.get("race_name"), meta.get("city"), meta.get("state")),
            )
            race_id = cur.lastrowid

            cur.execute(
                "INSERT INTO events (race_id, year, total_finishers) VALUES (?, ?, ?)",
                (race_id, int(meta.get("year", 2024)), len(records)),
            )
            event_id = cur.lastrowid

            cur.executemany(
                """INSERT INTO finishes
                   (event_id, place, first_name, last_name, gender, age, chip_time_sec, chip_time_str, division)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        event_id,
                        r.place,
                        r.first_name,
                        r.last_name,
                        r.gender,
                        r.age,
                        r.chip_time_sec,
                        r.chip_time_str,
                        r.division,
                    )
                    for r in records
                ],
            )

    def _load_from_db(self, url: str) -> tuple[dict[str, Any], list[FinishRecord]] | None:
        """Load cached race results from SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            race = cur.execute("SELECT * FROM races WHERE source_url = ?", (url,)).fetchone()
            if not race:
                return None

            event = cur.execute("SELECT * FROM events WHERE race_id = ? ORDER BY id DESC LIMIT 1", (race["id"],)).fetchone()
            if not event:
                return None

            rows = cur.execute("SELECT * FROM finishes WHERE event_id = ? ORDER BY place ASC", (event["id"],)).fetchall()
            records = [
                FinishRecord(
                    place=r["place"],
                    first_name=r["first_name"],
                    last_name=r["last_name"],
                    gender=r["gender"],
                    age=r["age"],
                    chip_time_sec=r["chip_time_sec"],
                    chip_time_str=r["chip_time_str"],
                    division=r["division"],
                )
                for r in rows
            ]
            meta = {
                "platform": race["platform"],
                "race_name": race["race_name"],
                "city": race["city"],
                "state": race["state"],
                "total_finishers": len(records),
                "cached": True,
            }
            return meta, records
