"""Turn a dated training log into weekly totals and the model's features (stdlib only).

The same definitions are re-implemented with numpy in research.py (to build ~5 million
cases quickly); research.py checks on a random sample that both give identical numbers.

Weeks are counted back from `today`: week 0 is the 7 days before today, week 1 the 7 days
before that, and so on. The series runs from the week of the first log entry (at most
`lookback_weeks` back) to week 0, oldest first; a week without entries is a rest week
(0 km). A week whose total is implausible for running (average pace outside
[min_pace, max_pace] or more than max_week_km) is treated as missing: it counts neither as
a run week nor as a rest week (the BMClab data has no activity-type check beyond Strava's
"run" label, and a few weeks are clearly cycling or GPS errors).

Windows (all ending at today):  recent = last `recent_weeks` (4), base = last
`base_weeks` (12), long = the whole series (up to `lookback_weeks`, 26).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

KM_PER_MILE = 1.609344

# Countries of the BMClab dataset that lie in the southern temperate zone (seasons six
# months away from the north). Geography, not a tunable: near-equator countries stay north.
SOUTHERN_COUNTRIES = frozenset({
    "Argentina", "Australia", "Bolivia", "Botswana", "Brazil", "Chile", "East Timor", "Fiji",
    "Lesotho", "Mauritius", "Namibia", "New Zealand", "Paraguay", "Peru", "South Africa",
    "Uruguay", "Zimbabwe", "Angola",
})


@dataclass
class Window:
    weeks: int          # weeks in the window that are not missing
    run_weeks: int      # of those, weeks with any running
    km: float           # total km over the non-missing weeks
    minutes: float      # total minutes over the non-missing weeks

    @property
    def km_per_week(self) -> float:
        return self.km / self.weeks if self.weeks else 0.0

    @property
    def pace(self) -> float | None:
        """Average pace in seconds per km (total time / total distance), None without runs."""
        return self.minutes * 60.0 / self.km if self.km > 0 else None


@dataclass
class Features:
    series_weeks: int                     # weeks in the log series (<= lookback_weeks)
    missing_weeks: int                    # weeks dropped as implausible
    recent: Window
    base: Window
    long: Window
    tanda: Window                         # window used for Tanda's K and P (8 weeks)
    share: float                          # base run_weeks / base weeks
    since: int                            # weeks since the last run week (0 = ran last week)
    lp_base: float                        # ln(base pace, s/km)
    tr_recent: float                      # ln(recent pace / base pace); 0 if no recent run
    tr_long: float                        # ln(base pace / long pace)
    lk_base: float                        # ln(base km/week + km_offset)
    ktr_recent: float                     # ln((recent km/wk + off) / (base km/wk + off))
    ktr_long: float                       # ln((base km/wk + off) / (long km/wk + off))
    week_mids: list[dt.date] = field(default_factory=list)  # mid-date of each base week
    weekly: list[tuple[float | None, float | None]] = field(default_factory=list)


# ── input parsing ──────────────────────────────────────────────────────────

def as_date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value).strip())


def parse_minutes(value: Any) -> float:
    """Duration in minutes: a number (minutes) or "h:mm:ss" / "mm:ss"."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    parts = [float(x) for x in str(value).strip().split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] + parts[1] / 60.0
    if len(parts) == 3:
        return parts[0] * 60.0 + parts[1] + parts[2] / 60.0
    raise ValueError(f"cannot read duration {value!r} (use minutes or h:mm:ss)")


def entry_km(entry: dict[str, Any]) -> float:
    if "km" in entry:
        return float(entry["km"])
    if "miles" in entry:
        return float(entry["miles"]) * KM_PER_MILE
    raise ValueError(f"log entry {entry} needs km or miles")


def entry_minutes(entry: dict[str, Any]) -> float:
    for key in ("time", "duration", "minutes"):
        if key in entry:
            return parse_minutes(entry[key])
    raise ValueError(f"log entry {entry} needs time (h:mm:ss) or minutes")


def weekly_totals(inputs: dict[str, Any], today: dt.date, lookback: int) -> tuple[list[list[float]], int]:
    """[[km, minutes], ...] oldest first, last = week 0; and the number of ignored entries.

    Accepts `log` (dated entries, daily or weekly) or `weekly_km` + `weekly_minutes`
    (lists, oldest first, last = the 7 days before today)."""
    if "weekly_km" in inputs:
        km = [float(x) for x in inputs["weekly_km"]]
        mins = [float(x) for x in inputs["weekly_minutes"]]
        if len(km) != len(mins):
            raise ValueError("weekly_km and weekly_minutes must have the same length")
        rows = [[k, m] for k, m in zip(km, mins)][-lookback:]
        return rows, 0
    log = inputs.get("log") or []
    if not log:
        raise ValueError("give a training log: [[log]] entries (date, km, time) or weekly_km + weekly_minutes")
    totals: dict[int, list[float]] = {}
    ignored = 0
    for entry in log:
        d = as_date(entry["date"])
        days = (today - d).days
        if days < 1:        # on or after today: not known yet
            ignored += 1
            continue
        k = (days - 1) // 7
        if k >= lookback:   # older than the lookback
            ignored += 1
            continue
        t = totals.setdefault(k, [0.0, 0.0])
        t[0] += entry_km(entry)
        t[1] += entry_minutes(entry)
    if not totals:
        raise ValueError("no log entries in the lookback window before today")
    span = max(totals) + 1
    return [totals.get(k, [0.0, 0.0]) for k in range(span - 1, -1, -1)], ignored


# ── features ───────────────────────────────────────────────────────────────

def clean(rows: list[list[float]], p: Any) -> list[tuple[float | None, float | None]]:
    out = []
    for km, mins in rows:
        if km < 0 or mins < 0:
            raise ValueError("distances and durations must be >= 0")
        if km > 0:
            pace = mins / km  # min/km
            if pace < p.min_pace_min_per_km or pace > p.max_pace_min_per_km or km > p.max_week_km:
                out.append((None, None))
                continue
        out.append((km, mins if km > 0 else 0.0))
    return out


def window(weekly: list[tuple[float | None, float | None]], n: int) -> Window:
    part = weekly[-n:]
    ok = [(k, m) for k, m in part if k is not None]
    return Window(len(ok), sum(1 for k, _ in ok if k > 0), sum(k for k, _ in ok), sum(m for _, m in ok))


def week_mid(today: dt.date, k: int) -> dt.date:
    """Mid-date of week k before today (week k covers today-7(k+1) .. today-7k-1)."""
    return today - dt.timedelta(days=7 * k + 4)


def target_week_mids(today: dt.date, horizon: int, n: int) -> list[dt.date]:
    """Mid-dates of the n weeks ending `horizon` weeks after today."""
    return [today + dt.timedelta(days=7 * (horizon - n + j) + 3) for j in range(n)]


def summarise(rows: list[list[float]], today: dt.date, p: Any) -> Features:
    weekly = clean(rows, p)
    missing = sum(1 for k, _ in weekly if k is None)
    recent = window(weekly, int(p.recent_weeks))
    base = window(weekly, int(p.base_weeks))
    long = window(weekly, int(p.lookback_weeks))
    tanda = window(weekly, int(p.tanda_weeks))
    if base.run_weeks < p.min_run_weeks:
        raise ValueError(
            f"the last {int(p.base_weeks)} weeks have {base.run_weeks} weeks with running; the model "
            f"needs at least {int(p.min_run_weeks)} (min_run_weeks) to estimate a current pace")
    run_idx = [i for i, (k, _) in enumerate(weekly) if k]
    since = len(weekly) - 1 - run_idx[-1]
    off = p.km_offset
    lp_base = math.log(base.pace)
    tr_recent = math.log(recent.pace / base.pace) if recent.pace else 0.0
    tr_long = math.log(base.pace / long.pace)
    lk_base = math.log(base.km_per_week + off)
    n = len(weekly)
    mids = [week_mid(today, k) for k in range(min(n, int(p.base_weeks)) - 1, -1, -1)]
    return Features(
        series_weeks=n, missing_weeks=missing, recent=recent, base=base, long=long, tanda=tanda,
        share=base.run_weeks / base.weeks, since=min(since, int(p.base_weeks)),
        lp_base=lp_base, tr_recent=tr_recent, tr_long=tr_long, lk_base=lk_base,
        ktr_recent=math.log(recent.km_per_week + off) - lk_base,
        ktr_long=lk_base - math.log(long.km_per_week + off),
        week_mids=mids, weekly=weekly,
    )


def season_value(dates: list[dt.date], prefix: str, southern: bool, p: Any) -> float:
    """Mean seasonal offset (param <prefix>_mMM) over the months of `dates`; southern-
    hemisphere runners use the month six months away."""
    vals = []
    for d in dates:
        m = d.month
        if southern:
            m = (m + 5) % 12 + 1
        vals.append(float(p[f"{prefix}_m{m:02d}"]))
    return sum(vals) / len(vals)
