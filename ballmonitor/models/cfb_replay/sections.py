"""Sections for cfb_replay (structure = "sections"): cut the ESPN win-probability curve into
~10 sections at its peaks and valleys, pick each section's key plays, write a short title and
summary from the play text, and time the sections and their plays.

Also holds the text/timing helpers shared with the per-play structure (`clean_text`,
`allocate`). Standard library only; every tunable number comes from `p` (the model params).
See MODEL.md, "Sections".
"""

from __future__ import annotations

import re
from typing import Any

MAX_KEY_PLAYS = 4  # output contract: a section lists at most 4 key plays


# ---------------------------------------------------------------------------------------
# Shared helpers


def clean_text(text: str, limit: int) -> str:
    """ESPN play text -> short readable line (no clock, jersey numbers, tacklers, formation)."""
    s = str(text or "")
    s = re.sub(r"^\s*\(\s*\d{1,2}:\d{2}\s*\)\s*", "", s)                       # leading (12:34)
    s = re.sub(r"^(No Huddle-)?(Shotgun|Pistol|Under Center|No Huddle)\s*", "", s, flags=re.I)
    s = re.sub(r"\(H:[^)]*\)", "", s)                                            # holder / snapper
    s = re.sub(r"\((#\d+ [^()]*?)\)", "", s)                                    # (#15 D.McDonald; ...)
    s = re.sub(r",?\s*clock \d{1,2}:\d{2}", "", s, flags=re.I)
    s = re.sub(r"#\d+\s+", "", s)                                                # jersey numbers
    s = re.sub(r"\s+", " ", s).strip(" ,.")
    s = s.replace(" ,", ",")
    if len(s) > limit:
        cut = s[: limit - 1]
        if " " in cut[limit // 2:]:
            cut = cut[: cut.rfind(" ")]
        s = cut.rstrip(" ,.;") + "…"
    return s


def allocate(weights: list[float], body: float, lo, hi: float) -> tuple[list[float], str]:
    """Durations clamp(lam * w, lo_i, hi) summing to `body`; lam found by bisection.

    `lo` is one floor for every item or a list (collapsed drives have their own floor).
    Returns (durations, how) where `how` describes the case for the steps.
    """
    n = len(weights)
    if n == 0:
        return [], "no plays"
    los = list(lo) if isinstance(lo, (list, tuple)) else [float(lo)] * n
    if sum(los) >= body:
        k = body / sum(los)
        return [x * k for x in los], f"floors sum {sum(los):.2f}s >= body {body:.2f}s: floors scaled down to fit"
    if n * hi <= body:
        return [body / n] * n, f"{n} items x cap {hi:g}s <= body {body:.2f}s: equal shares (cap exceeded)"

    def total(lam: float) -> float:
        return sum(min(max(lam * w, l), hi) for w, l in zip(weights, los))

    positive = [i for i, w in enumerate(weights) if w > 0]
    zero = [i for i in range(n) if weights[i] <= 0]
    if not positive or len(positive) * hi + sum(los[i] for i in zero) < body:
        # Not reachable by scaling weights: weighted items get the cap, the rest share what's left.
        rest = body - len(positive) * hi
        zl = sum(los[i] for i in zero) or 1.0
        return ([hi if w > 0 else rest * los[i] / zl for i, w in enumerate(weights)],
                "weights too few: weighted items capped, rest share remainder")
    lam_lo, lam_hi = 0.0, 1.0
    while total(lam_hi) < body:
        lam_hi *= 2.0
    for _ in range(200):
        mid = (lam_lo + lam_hi) / 2
        if total(mid) < body:
            lam_lo = mid
        else:
            lam_hi = mid
    lam = lam_hi
    durations = [min(max(lam * w, l), hi) for w, l in zip(weights, los)]
    # Remove the last float residue on the unclamped items (or any item if none are free).
    residue = body - sum(durations)
    free = [i for i, d in enumerate(durations) if los[i] < d < hi] or list(range(n))
    for i in free:
        durations[i] += residue / len(free)
    return durations, f"scale = {lam:.4g} s per unit weight"


def _other(side: str | None) -> str | None:
    return {"home": "away", "away": "home"}.get(side or "")


def _seconds(clock: str) -> int:
    m = re.fullmatch(r"(\d+):(\d{2})", clock or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else 0


def _fit(options: list[str], limit: int) -> str:
    """First option that fits `limit` characters, else the last one cut at a word."""
    for s in options:
        if len(s) <= limit:
            return s
    s = options[-1]
    cut = s[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;") + "…"


# ---------------------------------------------------------------------------------------
# Reading ESPN play text

_SUFFIX = r"(?:\s(?:Jr\.?|Sr\.?|II|III|IV|V)(?=[\s,]|$))"
NAME = rf"(?:[A-Z][A-Za-z'\-]*\.)*[A-Z][A-Za-z'\-]+{_SUFFIX}?"
# ESPN's other text style: "Cataurus Hicks 36 Yd pass from Holden Geriner (Antonio Chadha Kick)",
# "Javian Mallory 2 Yd Run (...)", "Shay Barker 30 Yd Field Goal", "X 45 Yd Interception Return".
_ALT = re.compile(r"^(?P<who>[A-Z][\w.'\- ]*?) (?P<y>\d+) Yd (?P<what>pass from|run|field goal|"
                  r"interception return|fumble return|punt return|kickoff return)"
                  r"(?: (?P<qb>[A-Z][\w.'\-]*(?: [A-Z][\w.'\-]*)*))?", re.I)


def surname(name: str | None) -> str | None:
    """'S.Angeli' -> 'Angeli', 'B.Edwards Jr.' -> 'Edwards', 'Holden Geriner' -> 'Geriner'."""
    if not name:
        return None
    s = re.sub(r"\s+(?:Jr\.?|Sr\.?|II|III|IV|V)\s*$", "", name.strip())
    if "." in s:
        s = s.rsplit(".", 1)[1].strip() or s
    parts = s.split()
    return parts[-1] if parts else None


def _search(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text)
    return m.group(group) if m else None


def _int(text: str | None) -> int | None:
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def parse_play(pl: dict[str, Any]) -> dict[str, Any]:
    """What happened on a play, from ESPN's text and type: kind, yards and the players involved.

    Falls back to the ESPN play type (kind "play") when the text matches nothing.
    """
    t = clean_text(pl["text"], 10 ** 6)
    low, typ = t.lower(), pl["type"].lower()
    dh, da = pl.get("_points", (0, 0))
    pts = max(dh, da)
    info: dict[str, Any] = {"kind": "play", "yards": None, "passer": None, "receiver": None,
                            "runner": None, "kicker": None, "defender": None, "conversion": None,
                            "foul": None, "foul_team": None,
                            "scorer": ("home" if dh >= da else "away") if pl["scoring"] else None}
    alt = _ALT.match(t)
    info["passer"] = surname(_search(rf"({NAME}) pass (?:complete|incomplete|intercepted)", t))
    info["receiver"] = surname(_search(rf"pass complete .*? to ({NAME})", t))
    info["runner"] = surname(_search(rf"({NAME}) (?:rush|run|scramble)", t))
    gain = re.search(r"for (?:a )?(loss of )?(\d+) y(?:ar)?ds?( loss)?", t)
    if gain:
        info["yards"] = -int(gain.group(2)) if (gain.group(1) or gain.group(3)) else int(gain.group(2))
    elif "no gain" in low:
        info["yards"] = 0
    ret = _int(_search(r"return(?:s|ed)? (?:for )?(\d+) y(?:ar)?ds?", t))
    returner = surname(_search(rf"({NAME}) return(?:s|ed)? (?:for )?\d+", t))
    td = pl["scoring"] and (pts >= 6 or "touchdown" in typ or "touchdown" in low)

    if pl["scoring"] and td:
        if "interception" in typ or "intercepted" in low or (alt and alt["what"].lower() == "interception return"):
            info.update(kind="int_td", yards=ret, defender=surname(_search(rf"intercepted by ({NAME})", t)) or returner)
        elif "fumble" in typ and "return" in typ or (alt and alt["what"].lower() == "fumble return"):
            info.update(kind="fumble_td", yards=ret, defender=returner)
        elif "punt" in typ or " punt " in f" {low} " or (alt and alt["what"].lower() == "punt return"):
            info.update(kind="punt_ret_td", yards=ret, defender=returner)
        elif "kickoff" in typ or "kickoff" in low or (alt and alt["what"].lower() == "kickoff return"):
            info.update(kind="kick_ret_td", yards=ret, defender=returner)
        elif "blocked" in typ:
            info.update(kind="block_td", yards=ret)
        elif "pass" in typ or "pass complete" in low or (alt and alt["what"].lower() == "pass from"):
            info["kind"] = "pass_td"
        elif "rush" in typ or info["runner"] or (alt and alt["what"].lower() == "run"):
            info["kind"] = "rush_td"
        else:
            info["kind"] = "td"
        if alt and info["kind"] in ("pass_td", "rush_td", "int_td", "fumble_td", "punt_ret_td", "kick_ret_td"):
            info["yards"] = int(alt["y"])
            if info["kind"] == "pass_td":
                info.update(receiver=surname(alt["who"]), passer=surname(alt["qb"]))
            elif info["kind"] == "rush_td":
                info["runner"] = surname(alt["who"])
            else:
                info["defender"] = surname(alt["who"])
        # conversion: points on the TD play include it (8 = two-point try good)
        two_try = re.search(r"(?:pass|rush|run) attempt (successful|good|failed|no good)|two[- ]point[^.]*?"
                            r"(successful|good|failed|no good)", low)
        if pts == 8 or (two_try and (two_try.group(1) or two_try.group(2)) in ("successful", "good")):
            info["conversion"] = "2pt_good"
        elif two_try:
            info["conversion"] = "2pt_failed"
        elif re.search(r"kick attempt (?:failed|no good|blocked)|pat (?:failed|no good|blocked)", low):
            info["conversion"] = "pat_failed"
    elif pl["scoring"] and (pts == 3 or "field goal" in typ):
        info["kind"] = "fg"
        info["yards"] = (_int(_search(r"from (\d+) y", t)) or _int(_search(r"(\d+) (?:yd|yard)s? field goal", low))
                         or (int(alt["y"]) if alt else None))
        info["kicker"] = surname(_search(rf"({NAME}) (?:\d+ yd )?field goal", t) or (alt["who"] if alt else None))
    elif pl["scoring"] and (pts == 2 or "safety" in typ or "safety" in low):
        info["kind"] = "safety"
    elif pl["scoring"]:
        info["kind"] = "score"
    elif "field goal" in low and "blocked" in (typ + " " + low):
        info.update(kind="blocked_fg", yards=_int(_search(r"from (\d+) y", t)))
    elif "field goal missed" in typ or "missed field goal" in typ or ("field goal" in low and "no good" in low):
        info.update(kind="missed_fg", yards=_int(_search(r"from (\d+) y", t)))
    elif "blocked punt" in typ or ("punt" in low and "blocked" in low):
        info["kind"] = "blocked_punt"
    elif pl["turnover"]:
        if "interception" in typ or "intercepted" in low:
            info.update(kind="interception", defender=surname(_search(rf"intercepted by ({NAME})", t)))
        elif "fumble" in typ or "fumble" in low:
            info["kind"] = "fumble"
        elif pl.get("_on_downs"):
            info["kind"] = "downs"
        else:
            info["kind"] = "turnover"
    elif "penalty" in typ:
        m = re.search(r"PENALTY (\w+) ([A-Za-z' \-]+?)(?: \(| \d| declined|\.|,|$)", t)
        info.update(kind="penalty", foul=m.group(2).strip().lower() if m else None,
                    foul_team=m.group(1) if m else None)
    elif "sack" in typ or " sacked" in low:
        info["kind"] = "sack"
    elif "fumble" in low:
        info["kind"] = "fumble_kept"
    elif "pass" in typ or "pass complete" in low:
        info["kind"] = "pass"
    elif "rush" in typ or info["runner"]:
        info["kind"] = "rush"
    return info


TD_KINDS = {"pass_td", "rush_td", "int_td", "fumble_td", "punt_ret_td", "kick_ret_td", "block_td", "td"}
TURNOVER_KINDS = {"interception", "fumble", "downs", "turnover", "blocked_fg", "blocked_punt", "missed_fg"}


# ---------------------------------------------------------------------------------------
# Segmentation


def zigzag(series: list[float], threshold: float) -> list[tuple[int, str]]:
    """Peaks and valleys of `series` that are confirmed by a reversal of at least `threshold`.

    Returns (i, "peak"|"valley") with 0 < i < len(series) - 1 (interior points only). Ties keep
    the earliest point.
    """
    pivots: list[tuple[int, str]] = []
    direction, hi_i, lo_i, ext = 0, 0, 0, 0
    for j in range(1, len(series)):
        v = series[j]
        if direction == 0:
            if v > series[hi_i]:
                hi_i = j
            if v < series[lo_i]:
                lo_i = j
            if series[hi_i] - series[lo_i] >= threshold:
                if hi_i == j:
                    direction, ext = 1, j
                    pivots.append((lo_i, "valley"))
                else:
                    direction, ext = -1, j
                    pivots.append((hi_i, "peak"))
        elif direction == 1:
            if v > series[ext]:
                ext = j
            elif series[ext] - v >= threshold:
                pivots.append((ext, "peak"))
                direction, ext = -1, j
        else:
            if v < series[ext]:
                ext = j
            elif v - series[ext] >= threshold:
                pivots.append((ext, "valley"))
                direction, ext = 1, j
    return [(j, k) for j, k in pivots if 0 < j < len(series) - 1]


def _is_conversion(pl: dict[str, Any]) -> bool:
    typ = pl["type"].lower()
    return any(w in typ for w in ("extra point", "two point", "two-point", "2pt", "conversion", "pat"))


def boundary_pref(plays: list[dict], j: int, p) -> float:
    """How good a section boundary before play j is (after a score / turnover / at a new drive)."""
    prev, nxt = plays[j - 1], plays[j]
    scoring = prev["scoring"] and not _is_conversion(nxt)
    new_drive = prev.get("_drive") != nxt.get("_drive") and not _is_conversion(nxt)
    return p.formula("boundary_pref", scoring=float(scoring), turnover=float(prev["turnover"]),
                     new_drive=float(new_drive))


def segment(plays: list[dict], series: list[float], p, steps: list[str]) -> list[dict[str, Any]]:
    """Contiguous sections [a, b] (play idx, inclusive) covering every play."""
    n = len(plays)
    target = max(1, int(p.n_sections))
    # Boundaries may only fall where a new ESPN drive starts or right after a score/turnover
    # (boundary_pref > 0); the zig-zag runs on home WP sampled at those points.
    good = [j for j in range(1, n) if boundary_pref(plays, j, p) > 0]
    points = [0] + good + [n]
    sampled = [series[j] for j in points]

    def pivots_at(threshold: float) -> list[tuple[int, str]]:
        return [(points[i], kind) for i, kind in zigzag(sampled, threshold)]

    threshold = float(p.section_min_reversal)
    pivots = pivots_at(threshold)
    first_found = len(pivots)
    raised = 0
    while len(pivots) + 1 > target:
        threshold *= float(p.section_reversal_growth)
        pivots = pivots_at(threshold)
        raised += 1
    peaks = sum(1 for _, k in pivots if k == "peak")
    msg = (f"Section boundaries may fall at {len(good)} points (new drive, or right after a score/turnover: "
           f"boundary_pref = {p.expr('boundary_pref')} > 0). Zig-zag pivots of home WP at those points "
           f"(a peak/valley counts once WP reverses by >= {p.section_min_reversal:g}): {first_found} found")
    if raised:
        msg += (f"; more than {target - 1}, so the reversal threshold was raised x"
                f"{p.section_reversal_growth:g} {raised} times to {threshold:.3f}")
    steps.append(msg + f" -> {len(pivots)} pivots ({peaks} peaks, {len(pivots) - peaks} valleys).")
    good_set = set(good)

    secs: list[dict[str, Any]] = []
    start = 0
    for j, kind in pivots:
        secs.append({"a": start, "b": j - 1, "pivot": kind})
        start = j
    secs.append({"a": start, "b": n - 1, "pivot": "end"})

    def n_scores(s: dict) -> int:
        return sum(1 for k in range(s["a"], s["b"] + 1) if plays[k]["scoring"])

    def swing(s: dict) -> float:
        return series[s["b"] + 1] - series[s["a"]]

    max_scores = int(p.section_max_scores)
    min_plays = int(p.min_section_plays)
    splits = forced = 0
    while True:
        over = [s for s in secs if n_scores(s) > max_scores]
        if not over and len(secs) >= target:
            break
        best = None
        for s in (over or secs):
            min_len = 1 if over else min_plays
            cands = list(range(s["a"] + min_len, s["b"] + 2 - min_len))
            cands = [c for c in cands if c in good_set] or cands
            if over:
                cands = [c for c in cands if any(plays[k]["scoring"] for k in range(s["a"], c))
                         and any(plays[k]["scoring"] for k in range(c, s["b"] + 1))]
            if not cands:
                continue
            prio = p.formula("split_priority", abs_swing=abs(swing(s)), n_plays=float(s["b"] - s["a"] + 1),
                             total_plays=float(n), n_scores=float(n_scores(s)))
            c = max(cands, key=lambda c: (p.formula("split_score", abs_swing=plays[c - 1]["abs_swing"],
                                                    pref=boundary_pref(plays, c, p)), -c))
            if best is None or prio > best[0]:
                best = (prio, s, c)
        if best is None:
            break
        _, s, c = best
        i = secs.index(s)
        secs[i:i + 1] = [{"a": s["a"], "b": c - 1, "pivot": "split"}, {"a": c, "b": s["b"], "pivot": s["pivot"]}]
        splits += 1
        forced += bool(over)
    steps.append(f"Split {splits} sections (formula split_priority = {p.expr('split_priority')} picks the "
                 f"section, split_score = {p.expr('split_score')} picks the point; at least {min_plays} plays "
                 f"per side, at an allowed boundary when there is one)" + (f", {forced} of them because a section had > {max_scores} scores" if forced else "")
                 + f" -> {len(secs)} sections (target n_sections = {target}).")
    return secs


# ---------------------------------------------------------------------------------------
# Key plays


def key_weight(pl: dict, info: dict, p) -> float:
    kick = info["kind"] in ("blocked_fg", "missed_fg", "blocked_punt")
    long_play = (info["kind"] in ("pass", "rush") and info["yards"] is not None
                 and info["yards"] >= p.long_play_yards)
    return p.formula("key_weight", abs_swing=pl["abs_swing"], turnover=float(pl["turnover"] or kick),
                     kick=float(kick), long_play=float(long_play))


def pick_keys(plays: list[dict], infos: list[dict], s: dict, p) -> list[int]:
    """Scoring plays first, then highlights, then the most notable other plays, in time order."""
    span = range(s["a"], s["b"] + 1)
    chosen = [k for k in span if plays[k]["scoring"]][:MAX_KEY_PLAYS]
    limit = max(int(p.section_key_plays), len(chosen))
    for k in sorted((k for k in span if plays[k]["highlight"] and k not in chosen),
                    key=lambda k: -plays[k]["abs_swing"]):
        if len(chosen) < MAX_KEY_PLAYS:
            chosen.append(k)
    others = sorted(((key_weight(plays[k], infos[k], p), k) for k in span if k not in chosen),
                    key=lambda x: (-x[0], x[1]))
    for w, k in others:
        if len(chosen) >= limit or w < p.key_min_weight:
            break
        chosen.append(k)
    if not chosen:  # a quiet section still holds its biggest-swing play
        chosen = [max(span, key=lambda k: (plays[k]["abs_swing"], -k))]
    return sorted(chosen)


# ---------------------------------------------------------------------------------------
# Titles and summaries


def play_phrase(pl: dict, info: dict, name: "Namer", p) -> str | None:
    """'Syracuse: 4-yard TD pass from Angeli to Russell' / 'Kansas blocks a 45-yard field goal'."""
    if pl["scoring"]:
        team = name(info.get("scorer")) if info.get("scorer") else None
        phrase = score_phrase(info, 0)
        phrase = phrase[2:] if phrase.startswith("a ") else phrase
        phrase = phrase[:1].upper() + phrase[1:]
        return f"{team}: {phrase}" if team and team != "A team" else phrase
    clause = event_clause(pl, info, 0, name, False, p)
    return f"{clause[0]} {clause[1]}" if clause else None


class Namer:
    def __init__(self, home: dict, away: dict):
        self.t = {"home": home, "away": away}
        self.by_abbr = {str(home["abbr"]).upper(): "home", str(away["abbr"]).upper(): "away"}

    def __call__(self, side: str | None, abbr: bool = False) -> str:
        if side not in self.t:
            return "A team" if not abbr else "Team"
        return self.t[side]["abbr"] if abbr else self.t[side]["short"]


def _yd(y: int | None, level: int) -> str:
    return f"{y}-yard " if y and y > 0 and level < 5 else ""


def score_phrase(info: dict, level: int) -> str:
    """Noun phrase for a score: 'a 75-yard TD pass from Angeli to Russell'."""
    k, ys, names = info["kind"], _yd(info["yards"], level), level < 2
    by = lambda who: f" by {who}" if names and who else ""  # noqa: E731
    if k == "pass_td":
        s = f"a {ys}TD pass"
        if names and info["passer"] and info["receiver"]:
            s += f" from {info['passer']} to {info['receiver']}"
        elif names and info["receiver"]:
            s += f" to {info['receiver']}"
    elif k == "rush_td":
        s = f"a {ys}TD run" + by(info["runner"])
    elif k == "int_td":
        s = f"a {ys}pick-six" + by(info["defender"])
    elif k == "fumble_td":
        s = f"a {ys}fumble-return TD" + by(info["defender"])
    elif k == "punt_ret_td":
        s = f"a {ys}punt-return TD" + by(info["defender"])
    elif k == "kick_ret_td":
        s = f"a {ys}kick-return TD" + by(info["defender"])
    elif k == "block_td":
        s = "a blocked-kick TD"
    elif k == "td":
        s = "a touchdown"
    elif k == "fg":
        s = f"a {ys}field goal" if level < 3 else f"a {ys}FG"
    elif k == "safety":
        s = "a safety"
    else:
        s = "a score"
    if level < 4:
        s += {"2pt_good": " and the 2-pt try", "2pt_failed": " (2-pt try fails)",
              "pat_failed": " (PAT missed)"}.get(info["conversion"] or "", "")
    return s


def event_clause(pl: dict, info: dict, level: int, name: "Namer", abbr: bool, p) -> tuple[str, str] | None:
    """(team, predicate) for a non-scoring key play, or None if there is nothing worth saying.

    Turnovers and kicking-game plays are always described. Other plays only when they are long
    (>= long_play_yards) or swung WP by >= big_play_swing *toward* the team that made them
    (ESPN WP sometimes jumps the other way on an ordinary play; those are not narrated).
    """
    off = pl["possession"]
    dfn = _other(off)
    O, D = name(off, abbr), name(dfn, abbr)
    k, y, names = info["kind"], info["yards"], level < 2
    ys = _yd(abs(y) if y else None, level)
    if k == "interception":
        return D, (f"intercepts {info['passer']}" if names and info["passer"] else "picks off a pass")
    if k == "fumble":
        return D, f"recovers a {O} fumble"
    if k == "downs":
        return D, f"stops {O} on 4th down"
    if k == "blocked_fg":
        return D, f"blocks a {ys}{O} field goal"
    if k == "missed_fg":
        return O, f"misses a {ys}field goal"
    if k == "blocked_punt":
        return D, f"blocks a {O} punt"
    if k == "turnover":
        return D, "forces a turnover"
    if off is None:
        return None
    toward = "home" if pl["swing"] > 0 else "away"
    big = pl["abs_swing"] >= p.big_play_swing
    long_play = y is not None and y >= p.long_play_yards
    flag = re.search(r"PENALTY (\w+) ([A-Za-z' \-]+?)(?: \(| \d| declined|\.|,|$)", pl["text"])
    extra = ""
    if flag and "declined" not in pl["text"][flag.start():flag.start() + 80].lower() and names:
        extra = f" plus a {flag.group(2).strip().lower()} penalty"
    if k == "pass" and y is not None and y > 0 and (long_play or (big and toward == off)):
        rec = f" to {info['receiver']}" if names and info["receiver"] else ""
        return O, f"hits a {ys}pass{rec}{extra}"
    if k == "rush" and y is not None and y > 0 and (long_play or (big and toward == off)):
        who = f" by {info['runner']}" if names and info["runner"] and info["runner"] != name(off) else ""
        return O, (f"breaks a {ys}run{who}" if long_play else f"gets a {ys}run{who.replace(' by ', ' from ')}") + extra
    if not big:
        return None
    if k == "sack" and toward == dfn:
        return D, (f"sacks {info['passer']}" if names and info["passer"] else "gets a big sack")
    if k == "penalty" and info["foul"]:
        side = name.by_abbr.get(str(info["foul_team"]).upper())
        if side is not None and toward == _other(side):
            return name(side, abbr), f"is flagged for {info['foul']}"
    return None


def _articles(text: str) -> str:
    """'a 8-yard' -> 'an 8-yard', 'a 11-yard' -> 'an 11-yard' (numbers read as 'eight', 'eleven', ...)."""
    return re.sub(r"\ba (?=(?:8|11|18|8\d)\b)", "an ", text)


def _join(clauses: list[tuple[str, str]]) -> str:
    """Two clauses per sentence: 'A does x, then does y. B does z.' (subject omitted if repeated)."""
    # back-to-back repeats -> "twice" / "N times"; a later repeat -> "again"
    runs: list[list] = []
    for c in clauses:
        if runs and runs[-1][0] == c:
            runs[-1][1] += 1
        else:
            runs.append([c, 1])
    seen: set = set()
    once = []
    for (subj, pred), count in runs:
        more = {1: "", 2: " twice"}.get(count, f" {count} times")
        once.append((subj, pred + more + (" again" if (subj, pred) in seen and count == 1 else "")))
        seen.add((subj, pred))
    clauses = once
    sentences = []
    for i in range(0, len(clauses), 2):
        pair = clauses[i:i + 2]
        text = f"{pair[0][0]} {pair[0][1]}"
        if len(pair) == 2:
            subj, pred = pair[1]
            text += f", then {pred}" if subj == pair[0][0] else f", then {subj} {pred}"
        sentences.append(text[0].upper() + text[1:] + ".")
    return _articles(" ".join(sentences))


def summary_for(plays: list[dict], infos: list[dict], keys: list[int], s: dict, name: Namer,
                drive_meta: dict, p) -> str:
    """1-2 sentences naming every score in order, plus the key non-scoring moment(s)."""
    limit = int(p.summary_max_chars)
    nonscoring = [k for k in keys if not plays[k]["scoring"]]
    ranked = sorted(nonscoring, key=lambda k: -key_weight(plays[k], infos[k], p))

    def build(level: int, abbr: bool, keep: int) -> str:
        kept = set(ranked[:keep])
        clauses: list[tuple[str, str]] = []
        last_scorer = None
        for k in keys:
            pl, info = plays[k], infos[k]
            if pl["scoring"]:
                side = info["scorer"]
                np = score_phrase(info, level)
                if last_scorer is None:
                    verb = "kicks" if info["kind"] == "fg" else "gets" if info["kind"] == "safety" else "scores on"
                elif last_scorer == side:
                    verb = "adds"
                else:
                    verb = "answers with"
                clauses.append((name(side, abbr), f"{verb} {np}"))
                last_scorer = side
            elif k in kept:
                c = event_clause(pl, info, level, name, abbr, p)
                if c:
                    clauses.append(c)
        deep = _deep_finish(plays, s, p)
        if deep and keep:
            clauses.append((name(deep[0], abbr), f"drives to the {deep[1]}"))
        return _join(clauses) if clauses else quiet_summary(plays, s, name, drive_meta, abbr, p)

    options = []
    for level, abbr, keep in ((0, False, len(ranked)), (0, False, 1), (2, False, 1), (2, True, 1),
                              (4, True, 0), (5, True, 0)):
        options.append(build(level, abbr, keep))
    return _fit(options, limit)


def _deep_finish(plays: list[dict], s: dict, p) -> tuple[str, str] | None:
    """(team, yardline) when the section ends mid-drive within section_end_deep_yards of the end zone."""
    b = s["b"]
    if b + 1 >= len(plays) or plays[b]["scoring"] or plays[b]["turnover"]:
        return None
    nxt = plays[b + 1]
    if (nxt.get("_drive") != plays[b].get("_drive") or not nxt["possession"] or not nxt["yardline_text"]
            or nxt["yards_to_endzone"] is None or nxt["yards_to_endzone"] > p.section_end_deep_yards):
        return None
    return nxt["possession"], nxt["yardline_text"]


def quiet_summary(plays: list[dict], s: dict, name: Namer, drive_meta: dict, abbr: bool, p) -> str:
    """No score and no notable play: describe the drives (punts, how far they got)."""
    punts: dict[str, int] = {}
    deepest = None
    seen: set = set()
    for k in range(s["a"], s["b"] + 1):
        pl = plays[k]
        d = pl.get("_drive")
        snap = "kickoff" not in pl["type"].lower() and pl["possession"]
        if snap and pl["yards_to_endzone"] is not None and (deepest is None or pl["yards_to_endzone"] < deepest[0]):
            deepest = (pl["yards_to_endzone"], pl["possession"], pl["yardline_text"])
        last_of_drive = k + 1 >= len(plays) or plays[k + 1].get("_drive") != d
        if d is not None and d not in seen and last_of_drive:
            seen.add(d)
            if str((drive_meta.get(d) or {}).get("result", "")).upper() == "PUNT" and snap:
                punts[pl["possession"]] = punts.get(pl["possession"], 0) + 1
    parts = []
    if s.get("_closes"):
        end = s["score_end"]
        parts.append(f"{name(s['_closes'], abbr)} runs out the clock to win "
                     f"{max(end['home'], end['away'])}-{min(end['home'], end['away'])}")
    if len(punts) == 2:
        parts.append("Defenses trade punts")
    elif punts:
        side, cnt = next(iter(punts.items()))
        parts.append(f"{name(side, abbr)} punts" + {1: "", 2: " twice"}.get(cnt, f" {cnt} times"))
    if deepest and deepest[0] <= p.quiet_deep_yards and deepest[2]:
        parts.append(f"{name(deepest[1], abbr)} reaches the {deepest[2]} but no points")
    if not parts:
        parts.append("Neither team scores")
    text = "; ".join(parts)
    return _articles(text[0].upper() + text[1:] + ".")


def title_for(plays: list[dict], infos: list[dict], keys: list[int], s: dict, ctx: dict, name: Namer, p) -> str:
    """Short headline (<= section_title_chars) from the scores, leads and key plays."""
    a, b = s["a"], s["b"]
    h0, a0 = s["score_start"]["home"], s["score_start"]["away"]
    h1, a1 = s["score_end"]["home"], s["score_end"]["away"]
    lead = lambda d: "home" if d > 0 else "away" if d < 0 else None  # noqa: E731
    L0, L1 = lead(h0 - a0), lead(h1 - a1)
    scores = [(infos[k]["scorer"], infos[k]["kind"]) for k in range(a, b + 1) if plays[k]["scoring"]]
    sides = list(dict.fromkeys(sd for sd, _ in scores))
    last = plays[b]
    in_ot = plays[a]["quarter"] >= 5
    late = last["quarter"] >= 5 or (last["quarter"] == 4 and _seconds(last["clock"]) <= p.late_game_sec)
    winner, is_last = ctx["winner"], ctx["is_last"]
    pick6 = [sd for sd, kd in scores if kd == "int_td"]
    notable = sorted((k for k in keys if not plays[k]["scoring"] and infos[k]["kind"] in TURNOVER_KINDS),
                     key=lambda k: -plays[k]["abs_swing"])

    def options(abbr: bool) -> list[str]:
        N = lambda sd: name(sd, abbr)  # noqa: E731
        out = []
        if is_last and winner and scores and L0 != winner and L1 == winner:
            out.append(f"{N(winner)} wins it in OT" if last["quarter"] >= 5 else
                       f"{N(winner)} wins it late" if late else f"{N(winner)} goes ahead for good")
        if in_ot and len(sides) == 2:
            out.append("Back-and-forth in OT")
        if pick6 and L1 == pick6[0] and L0 != pick6[0]:
            out.append("Pick-six flips it")
        if s.get("_closes") and not scores:
            out.append(f"{N(winner)} runs out the clock")
        wp_w = s["wp_home_start"] if winner == "home" else 1 - s["wp_home_start"]
        if is_last and winner and late and L0 == winner and L1 == winner and wp_w <= p.title_close_wp:
            if notable and _other(plays[notable[0]]["possession"]) == winner:
                out.append(f"{N(winner)} seals it")
            out.append(f"{N(winner)} holds on")
        fav = "home" if s["swing"] > 0 else "away"
        if abs(s["swing"]) >= p.title_momentum_swing and fav not in sides:
            mine = [k for k in notable if _other(plays[k]["possession"]) == fav or
                    (infos[k]["kind"] == "missed_fg" and plays[k]["possession"] != fav)]
            if mine:
                kd = infos[mine[0]]["kind"]
                out.append({"interception": f"{N(fav)} picks one off", "fumble": f"{N(fav)} forces a fumble",
                            "downs": f"{N(fav)} gets a 4th-down stop", "blocked_fg": f"{N(fav)} blocks a field goal",
                            "missed_fg": f"{N(_other(fav))} misses a field goal",
                            "blocked_punt": f"{N(fav)} blocks a punt"}.get(kd, f"{N(fav)} forces a turnover"))
            deep = _deep_finish(plays, s, p)
            if deep and deep[0] == fav:
                out.append(f"{N(fav)} drives to the {deep[1]}")
            out.append(f"Momentum swings to {N(fav)}")
        if scores and h0 == 0 and a0 == 0:
            first = scores[0][0]
            out.append(f"{N(first)} strikes, {N(_other(first))} answers" if len(sides) == 2
                       else f"{N(first)} strikes first")
        if scores and L1 != L0:
            if L1 is None:
                out.append(f"{N(scores[-1][0])} ties it at {h1}")
            elif L0 is None:
                out.append(f"{N(L1)} goes ahead")
            else:
                out.append(f"{N(L1)} takes the lead")
        if len(sides) == 2:
            out.append(f"{N(sides[0])} and {N(sides[1])} trade scores")
        if len(sides) == 1:
            x = sides[0]
            if pick6:
                out.append(f"Pick-six for {N(x)}")
            if ctx["prev_scorer"] not in (None, x):
                out.append(f"{N(x)} answers")
            elif L1 == x:
                hi_, lo_ = max(h1, a1), min(h1, a1)
                out.append(f"{N(x)} pulls away, {hi_}-{lo_}" if len(scores) >= 2 else f"{N(x)} goes up {hi_}-{lo_}")
            else:
                out.append(f"{N(x)} rallies" if len(scores) >= 2 else f"{N(x)} chips away")
        if not scores:
            if notable:
                k = notable[0]
                kd, off = infos[k]["kind"], plays[k]["possession"]
                dfn = _other(off)
                out.append({"interception": f"{N(dfn)} picks one off", "fumble": f"{N(dfn)} forces a fumble",
                            "downs": f"{N(dfn)} gets a 4th-down stop",
                            "blocked_fg": f"{N(dfn)} blocks a field goal",
                            "missed_fg": f"{N(off)} misses a field goal",
                            "blocked_punt": f"{N(dfn)} blocks a punt"}.get(kd, f"{N(dfn)} forces a turnover"))
            if abs(s["swing"]) >= p.big_play_swing:
                out.append(f"Momentum swings to {N('home' if s['swing'] > 0 else 'away')}")
            out.append("Defenses take over")
        return out

    limit = int(p.section_title_chars)
    full, short = options(False), options(True)
    return _articles(_fit([full[0], short[0]], limit))


# ---------------------------------------------------------------------------------------
# Timing


def time_sections(secs: list[dict], plays: list[dict], intro: float, body: float, end_body: float,
                  p, steps: list[str]) -> None:
    """Section durations from formula section_weight (clamped, filling the body), then play times."""
    title, lo_play, key_min = float(p.section_title_sec), float(p.min_play_sec), float(p.key_min_sec)
    weights, floors = [], []
    for s in secs:
        n_key = len(s["key_plays"])
        n_other = s["b"] - s["a"] + 1 - n_key
        floors.append(max(float(p.min_section_sec), title + n_other * lo_play + n_key * key_min))
        w = p.formula("section_weight", abs_swing=abs(s["swing"]), n_scores=float(len(s["scoring_plays"])),
                      n_plays=float(s["b"] - s["a"] + 1), late=float(s["_late"]))
        weights.append(max(w, 0.0))
    hi = max(float(p.max_section_sec), max(floors))
    durations, how = allocate(weights, body, floors, hi)
    steps.append(f"Section weight = {p.expr('section_weight')}; time = clamp(scale x weight, floor, "
                 f"{hi:g}s) filling the {body:g}s body ({how}). Floor = max(min_section_sec "
                 f"{p.min_section_sec:g}s, title {title:g}s + {lo_play:g}s per other play + {key_min:g}s "
                 f"per key play).")
    t, cum = intro, 0.0
    for k, (s, d) in enumerate(zip(secs, durations)):
        s["t_start"] = t
        cum += d
        t = end_body if k == len(secs) - 1 else round(intro + cum, 9)
        s["t_end"] = t
        s["_weight"] = weights[k]

    rest_share, rest_max = float(p.section_rest_share), float(p.rest_play_max_sec)
    for s in secs:
        span = list(range(s["a"], s["b"] + 1))
        keys = s["key_plays"]
        others = [k for k in span if k not in keys]
        D = s["t_end"] - s["t_start"]
        lead = min(title, D / 2)
        R = D - lead
        own: dict[int, float] = {}
        per = 0.0
        if others:
            per = min(max(R * rest_share / len(others), lo_play), rest_max)
            per = max(0.0, min(per, (R - len(keys) * min(key_min, R / max(len(keys), 1))) / len(others)))
            for k in others:
                own[k] = per
        key_total = R - per * len(others)
        kw = [max(p.formula("key_hold_weight", abs_swing=plays[k]["abs_swing"], scoring=float(plays[k]["scoring"]),
                            highlight=float(plays[k]["highlight"])), 0.0) for k in keys]
        kd, _ = allocate(kw, key_total, min(key_min, key_total / len(keys)), key_total)
        own.update(zip(keys, kd))
        own[span[0]] += lead
        tt, cum = s["t_start"], 0.0
        for i, k in enumerate(span):
            plays[k]["t_start"] = tt
            cum += own[k]
            tt = s["t_end"] if i == len(span) - 1 else round(s["t_start"] + cum, 9)
            plays[k]["t_end"] = tt
        s["title_sec"] = lead
        held = "/".join(f"{own[k] - (lead if k == span[0] else 0):.2f}" for k in keys)
        steps.append(f"S{s['idx'] + 1}: plays {s['a']}-{s['b']}, WP {s['wp_home_start']:.0%}->"
                     f"{s['wp_home_end']:.0%} ({s['swing']:+.1%}, {s['pivot']}), {len(s['scoring_plays'])} "
                     f"scores, weight {s['_weight']:.2f} -> {D:.2f}s: title {lead:.2f}s, key {held}s, "
                     f"{len(others)} others {per:.2f}s each.")
