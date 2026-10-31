"""College football game replay: ESPN play-by-play + win probability -> a paced video timeline.

See MODEL.md. The output contract in `extras` (game / timeline / plays / top_plays /
structure / sections) is consumed by a separate canvas renderer; keep its keys and types
stable. Segmentation, summaries and section timing live in sections.py.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.models.cfb_replay import chart, espn, sections
from ballmonitor.models.cfb_replay.sections import allocate, clean_text  # noqa: F401  (re-exported)

OFFENSE_TYPES = {"rush", "pass reception", "pass incompletion", "sack", "pass", "fumble recovery (own)"}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _hex(color: Any, fallback: str) -> str:
    text = str(color or "").strip().lstrip("#").lower()
    if re.fullmatch(r"[0-9a-f]{6}", text):
        return "#" + text
    if re.fullmatch(r"[0-9a-f]{3}", text):
        return "#" + "".join(c * 2 for c in text)
    return fallback


def _clock(text: Any) -> str:
    m = re.fullmatch(r"\s*(\d+):(\d{1,2})\s*", str(text or ""))
    if not m:
        return "00:00"
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"


def _iso(date: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(date, fmt).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
    return date


DRIVE_RESULTS = {
    "TD": "Touchdown", "FG": "Field goal", "MISSED FG": "Missed field goal", "PUNT": "Punt",
    "INT": "Interception", "FUMBLE": "Fumble", "DOWNS": "Turnover on downs", "SAFETY": "Safety",
    "END OF HALF": "End of half", "END OF GAME": "End of game", "BLOCKED FG": "Blocked field goal",
    "BLOCKED PUNT": "Blocked punt", "INT TD": "Pick-six", "FUMBLE TD": "Fumble return TD",
}


class CfbReplayModel(BaseModel):
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        steps: list[str] = []
        shown: dict[str, Any] = {}

        # ---- find and load the game ---------------------------------------------------
        # home + away + date wins over `game` (so `--in home=.. --in away=.. --in date=..`
        # works on top of the default example, which sets `game`).
        if inputs.get("home") and inputs.get("away") and inputs.get("date"):
            shown.update(home=inputs["home"], away=inputs["away"], date=inputs["date"])
            game_id, how = espn.find_game(self.dir, str(inputs["home"]), str(inputs["away"]),
                                          str(inputs["date"]), allow_network=bool(p.allow_network),
                                          timeout=float(p.fetch_timeout_sec))
            shown["game"] = game_id
            ignored = f" (input game={inputs['game']} ignored)" if inputs.get("game") not in (None, "") else ""
            steps.append(f"Game lookup: {how}{ignored}.")
        elif inputs.get("game") not in (None, ""):
            game_id = espn.normalize_game_id(inputs["game"])
            shown["game"] = game_id
        else:
            raise ValueError("give `game` (ESPN event id) or `home`, `away` and `date` (YYYY-MM-DD)")
        data, source = espn.load_summary(self.dir, game_id, allow_network=bool(p.allow_network),
                                         timeout=float(p.fetch_timeout_sec))
        if not espn.is_summary(data):
            raise ValueError(f"no usable ESPN summary for game {game_id}")
        steps.append(f"Loaded ESPN summary for event {game_id} ({source}).")

        duration = float(inputs.get("duration_sec") or p.duration_sec)
        if inputs.get("duration_sec"):
            shown["duration_sec"] = f"{duration:g}"
        intro, outro = float(p.intro_sec), float(p.outro_sec)
        body = duration - intro - outro
        if body <= 0:
            raise ValueError(f"duration_sec {duration:g} leaves no time after intro {intro:g}s + outro {outro:g}s")

        # ---- game header --------------------------------------------------------------
        comp = data["header"]["competitions"][0]
        sides = {c.get("homeAway"): c for c in comp["competitors"]}
        if set(sides) != {"home", "away"}:
            raise ValueError(f"game {game_id} does not list a home and an away team")
        team_side = {str(sides[s]["team"].get("id")): s for s in ("home", "away")}

        def team(side: str) -> dict[str, Any]:
            c = sides[side]
            t = c["team"]
            rank = _int_or_none(c.get("rank") or (c.get("curatedRank") or {}).get("current"))
            record = next((r.get("summary") for r in c.get("record") or [] if r.get("type") == "total"), None)
            return {
                "name": t.get("displayName") or t.get("location") or side,
                "short": t.get("location") or t.get("shortDisplayName") or t.get("displayName") or side,
                "abbr": t.get("abbreviation") or "",
                "color": _hex(t.get("color"), p.fallback_color),
                "alt_color": _hex(t.get("alternateColor"), p.fallback_alt_color),
                "rank": rank if rank is not None and 0 < rank < p.unranked_rank else None,
                "record": record,
            }

        home, away = team("home"), team("away")
        self._abbr = {"home": home["abbr"], "away": away["abbr"]}
        final = {s: _int_or_none(sides[s].get("score")) for s in ("home", "away")}
        status = (comp.get("status") or {}).get("type") or {}
        venue = ((data.get("gameInfo") or {}).get("venue") or {}).get("fullName") or None
        steps.append(f"{away['name']} at {home['name']}, {comp.get('date', '?')}, {venue or 'venue n/a'}: "
                     f"{status.get('detail', '?')} {away['abbr']} {final['away']} - {home['abbr']} {final['home']}.")
        if not status.get("completed"):
            steps.append("Warning: ESPN does not mark this game completed; the replay covers plays so far.")

        # ---- plays + ESPN win probability ---------------------------------------------
        drives = data.get("drives", {}).get("previous", [])
        drive_meta = {di: {"description": d.get("description") or "", "result": d.get("result") or ""}
                      for di, d in enumerate(drives)}
        events = [dict(pl, _drive=di) for di, d in enumerate(drives) for pl in d.get("plays", [])]
        events.sort(key=lambda pl: _int_or_none(pl.get("sequenceNumber")) or 0)
        if not events:
            raise ValueError(f"game {game_id} has no play-by-play on ESPN")
        wp_list = data.get("winprobability") or []
        wp = {str(w.get("playId")): float(w["homeWinPercentage"]) for w in wp_list
              if w.get("homeWinPercentage") is not None}
        if not wp:
            raise ValueError(f"game {game_id} has no ESPN win probability")
        event_ids = {str(e.get("id")) for e in events}
        pre_entry = next((w for w in wp_list if str(w.get("playId")) not in event_ids), None)
        if pre_entry is not None and wp_list.index(pre_entry) == 0:
            pregame = float(pre_entry["homeWinPercentage"])
            steps.append(f"Pregame home WP (ESPN, the WP entry before the first play) = {pregame:.1%}.")
        else:
            pregame = float(wp_list[0]["homeWinPercentage"])
            steps.append(f"No separate pregame WP entry; using ESPN's first published WP {pregame:.1%}.")

        # Scores: ESPN's running score on ordinary plays is unreliable (it sometimes shows a
        # score from later in the game), but the score on plays flagged scoringPlay is
        # consistent. So the score only changes on scoring plays and is carried forward.
        cleaned: dict[str, list[int]] = {"home": [], "away": []}
        cur = {"home": 0, "away": 0}
        flagged = [e for e in events if e.get("scoringPlay")]
        for e in events:
            if e.get("scoringPlay") or not flagged:
                for side, key in (("home", "homeScore"), ("away", "awayScore")):
                    v = _int_or_none(e.get(key))
                    if v is not None:
                        cur[side] = max(cur[side], v) if flagged else max(cur[side], min(v, final[side] or v))
            cleaned["home"].append(cur["home"])
            cleaned["away"].append(cur["away"])
        mismatched = sum(1 for i, e in enumerate(events)
                         if (_int_or_none(e.get("homeScore")), _int_or_none(e.get("awayScore")))
                         != (cleaned["home"][i], cleaned["away"][i]))
        steps.append(f"Scores taken from ESPN's {len(flagged)} scoring plays and carried forward "
                     f"({mismatched} other events showed a different running score and were ignored).")
        if (cur["home"], cur["away"]) != (final["home"], final["away"]):
            steps.append(f"Warning: play-by-play ends {cur['home']}-{cur['away']} but ESPN's final is "
                         f"{final['home']}-{final['away']}; the outro should use the final.")

        drop = tuple(str(t).strip().lower().replace("-", " ") for t in p.drop_types if str(t).strip())
        plays: list[dict[str, Any]] = []
        running = pregame
        dropped = no_wp = 0
        for i, e in enumerate(events):
            pid = str(e.get("id"))
            type_text = ((e.get("type") or {}).get("text") or "").strip()
            after = wp.get(pid)
            if after is None:
                no_wp += 1
            if drop and type_text.lower().replace("-", " ").startswith(drop):
                dropped += 1
                if plays:
                    if after is not None:
                        plays[-1]["wp_home_after"] = after
                        running = after
                    plays[-1]["home_score"] = cleaned["home"][i]
                    plays[-1]["away_score"] = cleaned["away"][i]
                continue
            if after is None:
                after = running
            plays.append(self._play(e, type_text, len(plays), running, after,
                                    cleaned["home"][i], cleaned["away"][i], team_side))
            running = after
        if not plays:
            raise ValueError(f"game {game_id} has no real plays after dropping {sorted(drop)}")
        prev_home, prev_away = 0, 0
        for pl in plays:
            pl["swing"] = round(pl["wp_home_after"] - pl["wp_home_before"], 6)
            pl["abs_swing"] = abs(pl["swing"])
            dh, da = pl["home_score"] - prev_home, pl["away_score"] - prev_away
            pl["scoring"] = bool(pl["_espn_scoring"] or dh > 0 or da > 0)
            pl["_points"] = (dh, da)
            prev_home, prev_away = pl["home_score"], pl["away_score"]
        steps.append(f"{len(events)} ESPN events -> {len(plays)} plays: dropped {dropped} non-plays "
                     f"(timeouts, period ends; see drop_types), their WP change folded into the "
                     f"previous play. {no_wp} events had no ESPN WP (kept the previous value).")
        last_wp = plays[-1]["wp_home_after"]
        steps.append(f"Swing = WP after - WP before (home view). Pregame {pregame:.1%} -> final {last_wp:.1%}; "
                     f"swings sum to {sum(pl['swing'] for pl in plays):+.3f}.")

        # ---- structure: per-play pacing (v0.2.0) or sections ------------------------------
        ctx = {"p": p, "steps": steps, "home": home, "away": away, "duration": duration, "intro": intro,
               "outro": outro, "body": body, "drive_meta": drive_meta, "final": final}
        structure = str(p.structure)
        if structure == "plays":
            plays, top, groups, more = self._by_plays(plays, ctx)
        elif structure == "chart":
            plays, top, groups, more = self._by_chart(plays, pregame, ctx)
        else:
            plays, top, groups, more = self._by_sections(plays, pregame, ctx)

        # ---- outputs ------------------------------------------------------------------
        biggest = plays[top[0]] if top else max(plays, key=lambda it: it["abs_swing"])
        outcomes = [
            Outcome("Biggest swing (ESPN WP)", probability=biggest["abs_swing"], fmt="pct",
                    note=self._note(biggest, home, away)),
            Outcome(f"Final: {home['short']} (home)", estimate=float(final["home"] or 0), fmt="int"),
            Outcome(f"Final: {away['short']} (away)", estimate=float(final["away"] or 0), fmt="int"),
            Outcome(f"Pregame {home['short']} win prob (ESPN)", probability=pregame, fmt="pct"),
        ]
        for rank, k in enumerate(top, 1):
            pl = plays[k]
            outcomes.append(Outcome(f"{rank}. {pl['headline'] or pl['type']}", probability=pl["abs_swing"],
                                    fmt="pct", group="Biggest swings", note=self._note(pl, home, away)))
        outcomes.extend(groups)

        public = [{key: v for key, v in pl.items() if not key.startswith("_")} for pl in plays]
        extras = {
            "game": {
                "id": game_id,
                "date": _iso(comp.get("date", "")),
                "venue": venue,
                "status_text": status.get("detail") or status.get("description") or "",
                "home": home,
                "away": away,
                "final": {"home": int(final["home"] or 0), "away": int(final["away"] or 0)},
                "pregame_wp_home": pregame,
                "wp_source": "ESPN",
            },
            "timeline": {"duration_sec": duration, "intro_sec": intro, "outro_sec": outro,
                         "fps": int(p.fps), "width": int(p.width), "height": int(p.height)},
            "plays": public,
            "top_plays": top,
            "structure": structure,
            **more,
        }
        return self.prediction(inputs=shown, outcomes=outcomes, steps=steps, extras=extras)

    # ----------------------------------------------------------------------------------

    def _by_plays(self, plays: list[dict[str, Any]], ctx: dict[str, Any]):
        """v0.2.0: every play paced on its own, quiet drives collapsed into one event."""
        p, steps, home, away = ctx["p"], ctx["steps"], ctx["home"], ctx["away"]
        duration, intro, outro, body = ctx["duration"], ctx["intro"], ctx["outro"], ctx["body"]
        drive_meta = ctx["drive_meta"]
        # ---- highlights + headlines ---------------------------------------------------
        order = sorted(range(len(plays)), key=lambda k: (-plays[k]["abs_swing"], k))
        top = [k for k in order if plays[k]["abs_swing"] >= p.highlight_min_swing][: int(p.highlight_count)]
        for k, pl in enumerate(plays):
            pl["highlight"] = k in top
            pl["headline"] = self._headline(pl, home, away)
        steps.append(f"Highlights: the {len(top)} largest |swing| plays with |swing| >= "
                     f"{p.highlight_min_swing:g} (max {int(p.highlight_count)}).")

        # ---- collapse quiet drives into one event ----------------------------------------
        top_ids = [plays[k]["id"] for k in top]
        cap = float(p.drive_collapse_max_swing)
        items: list[dict[str, Any]] = []
        k = 0
        n_collapsed = n_folded = 0
        while k < len(plays):
            j = k
            while j + 1 < len(plays) and plays[j + 1]["_drive"] == plays[k]["_drive"]:
                j += 1
            grp = plays[k:j + 1]
            quiet = (cap > 0 and plays[k]["_drive"] is not None and len(grp) >= int(p.drive_collapse_min_plays)
                     and not any(pl["highlight"] for pl in grp) and max(pl["abs_swing"] for pl in grp) < cap)
            if quiet:
                items.append(self._drive_event(grp, drive_meta.get(plays[k]["_drive"], {})))
                n_collapsed += 1
                n_folded += len(grp)
            else:
                items.extend(grp)
            k = j + 1
        for n, it in enumerate(items):
            it["idx"] = n
        top = [next(n for n, it in enumerate(items) if it["id"] == pid) for pid in top_ids]
        steps.append(f"Quiet drives (>= {int(p.drive_collapse_min_plays)} plays, no highlight, every |swing| < "
                     f"{cap:g}) shown as one event each: {n_collapsed} drives ({n_folded} plays) collapsed; "
                     f"{len(items)} timeline events.")

        # ---- pacing -------------------------------------------------------------------
        weights, lows = [], []
        negative = 0
        lo, hi, lo_drive = float(p.min_play_sec), float(p.max_play_sec), float(p.min_drive_sec)
        for it in items:
            if it["kind"] == "drive":
                w = p.formula("drive_weight", abs_swing=it["abs_swing"], scoring=float(it["scoring"]),
                              turnover=float(it["turnover"]), n_plays=float(it["n_plays"]))
                lows.append(lo_drive)
            else:
                w = p.formula("play_weight", abs_swing=it["abs_swing"], scoring=float(it["scoring"]),
                              turnover=float(it["turnover"]), highlight=float(it["highlight"]))
                lows.append(lo)
            if w < 0:
                negative += 1
                w = 0.0
            weights.append(w)
        durations, how = allocate(weights, body, lows, hi)
        plays = items
        steps.append(f"Video {duration:g}s = intro {intro:g}s + body {body:g}s + outro {outro:g}s.")
        steps.append(f"Weight per collapsed drive = {p.expr('drive_weight')} (floor {lo_drive:g}s).")
        steps.append(f"Weight per play = {p.expr('play_weight')}"
                     + (f" ({negative} negative weights set to 0)" if negative else "") + ".")
        n_floor = sum(1 for d, l in zip(durations, lows) if abs(d - l) < 1e-9)
        n_cap = sum(1 for d in durations if abs(d - hi) < 1e-9)
        steps.append(f"Time = clamp(scale x weight, {lo:g}s, {hi:g}s), scale solved so plays fill the body "
                     f"({how}): {n_floor} events at their floor, {n_cap} at the cap, "
                     f"{len(plays) - n_floor - n_cap} in between.")
        # Boundaries are the rounded cumulative sums (no drift); the last is pinned exactly.
        end_body = duration - outro
        t, cum = intro, 0.0
        for k, (pl, d) in enumerate(zip(plays, durations)):
            pl["t_start"] = t
            cum += d
            t = end_body if k == len(plays) - 1 else round(intro + cum, 9)
            pl["t_end"] = t
        held = ", ".join(f"#{k} {plays[k]['t_end'] - plays[k]['t_start']:.2f}s" for k in top)
        steps.append(f"Highlight hold times: {held or 'none'}; "
                     f"highlights total {sum(plays[k]['t_end'] - plays[k]['t_start'] for k in top):.2f}s.")
        steps.append(f"Check: first play starts at {plays[0]['t_start']:g}s, last ends at {plays[-1]['t_end']:g}s "
                     f"= duration {duration:g}s - outro {outro:g}s.")

        return plays, top, [], {}

    def _by_chart(self, plays: list[dict[str, Any]], pregame: float, ctx: dict[str, Any]):
        """v0.4.0: vertical WP chart, time axis warped around annotated plays revealed one by one."""
        home, away, steps = ctx["home"], ctx["away"], ctx["steps"]
        plays, top, annotations = chart.build(plays, pregame, ctx, lambda pl: self._headline(pl, home, away),
                                              sections.Namer(home, away))
        steps.append(f"Video {ctx['duration']:g}s = intro {ctx['intro']:g}s + body {ctx['body']:g}s + "
                     f"outro {ctx['outro']:g}s; first play starts at {plays[0]['t_start']:g}s, last ends at "
                     f"{plays[-1]['t_end']:g}s.")
        limit = int(ctx["p"].section_note_chars)
        when = lambda a: f"Q{a['quarter']} {a['clock']}" if a["quarter"] <= 4 else "OT"  # noqa: E731
        groups = [Outcome(f"{when(a)} {a['headline']}", probability=a["abs_swing"], fmt="pct",
                          group="Annotated plays", note=sections._fit([a["phrase"]], limit))
                  for a in annotations]
        return plays, top, groups, {"annotations": annotations}

    def _by_sections(self, plays: list[dict[str, Any]], pregame: float, ctx: dict[str, Any]):
        """v0.3.0: ~n_sections sections between WP peaks/valleys, each with a title and summary."""
        p, steps, home, away = ctx["p"], ctx["steps"], ctx["home"], ctx["away"]
        duration, intro, outro, body = ctx["duration"], ctx["intro"], ctx["outro"], ctx["body"]
        final = ctx["final"]

        order = sorted(range(len(plays)), key=lambda k: (-plays[k]["abs_swing"], k))
        top = [k for k in order if plays[k]["abs_swing"] >= p.highlight_min_swing][: int(p.section_highlight_count)]
        for k, pl in enumerate(plays):
            pl["highlight"] = k in top
            pl["headline"] = self._headline(pl, home, away)
        steps.append(f"Structure = sections. Highlights: the {len(top)} largest |swing| plays with |swing| >= "
                     f"{p.highlight_min_swing:g} (max section_highlight_count = {int(p.section_highlight_count)}); "
                     f"every play is kept (no drive collapsing).")

        series = [pregame] + [pl["wp_home_after"] for pl in plays]
        secs = sections.segment(plays, series, p, steps)
        infos = [sections.parse_play(pl) for pl in plays]
        name = sections.Namer(home, away)
        winner = ("home" if (final["home"] or 0) > (final["away"] or 0) else
                  "away" if (final["away"] or 0) > (final["home"] or 0) else None)
        prev_scorer = None
        for i, s in enumerate(secs):
            a, b = s["a"], s["b"]
            s["idx"] = i
            s["first_play"], s["last_play"] = a, b
            s["wp_home_start"], s["wp_home_end"] = series[a], series[b + 1]
            s["swing"] = round(series[b + 1] - series[a], 6)
            before = plays[a - 1] if a > 0 else None
            s["score_start"] = {"home": before["home_score"] if before else 0,
                                "away": before["away_score"] if before else 0}
            s["score_end"] = {"home": plays[b]["home_score"], "away": plays[b]["away_score"]}
            s["scoring_plays"] = [k for k in range(a, b + 1) if plays[k]["scoring"]]
            s["key_plays"] = sections.pick_keys(plays, infos, s, p)
            last = plays[b]
            s["_late"] = last["quarter"] >= 5 or (last["quarter"] == 4 and
                                                  sections._seconds(last["clock"]) <= p.late_game_sec)
            ctx_s = {"winner": winner, "is_last": i == len(secs) - 1, "prev_scorer": prev_scorer}
            # last section, no score, winner has the ball at the end -> "runs out the clock"
            s["_closes"] = (winner if i == len(secs) - 1 and winner and not s["scoring_plays"]
                            and plays[b]["possession"] == winner else None)
            s["title"] = sections.title_for(plays, infos, s["key_plays"], s, ctx_s, name, p)
            s["summary"] = sections.summary_for(plays, infos, s["key_plays"], s, name, ctx["drive_meta"], p)
            if s["scoring_plays"]:
                prev_scorer = infos[s["scoring_plays"][-1]]["scorer"]
            for k in range(a, b + 1):
                plays[k]["section"] = i
                plays[k]["key"] = k in s["key_plays"]
                # A natural one-line description for the renderer's cards ("Syracuse: 4-yard TD
                # pass from Angeli to Russell"), from the same parser as the summaries.
                if plays[k]["key"] or plays[k]["highlight"]:
                    plays[k]["phrase"] = sections.play_phrase(plays[k], infos[k], name, p)
        steps.append(f"Key plays per section: every scoring play, then highlights, then other plays by "
                     f"key_weight = {p.expr('key_weight')} (>= {p.key_min_weight:g}), up to "
                     f"{int(p.section_key_plays)} (hard cap {sections.MAX_KEY_PLAYS}); a quiet section holds "
                     f"its biggest-swing play.")

        steps.append(f"Video {duration:g}s = intro {intro:g}s + body {body:g}s + outro {outro:g}s.")
        sections.time_sections(secs, plays, intro, body, duration - outro, p, steps)
        steps.append(f"Within a section: the first {p.section_title_sec:g}s is a title lead-in (added to the "
                     f"first play's start); other plays share section_rest_share = {p.section_rest_share:g} of the "
                     f"rest (each {p.min_play_sec:g}-{p.rest_play_max_sec:g}s); key plays split the remainder by "
                     f"key_hold_weight = {p.expr('key_hold_weight')} (floor {p.key_min_sec:g}s).")
        steps.append(f"Check: first play starts at {plays[0]['t_start']:g}s, last ends at {plays[-1]['t_end']:g}s "
                     f"= duration {duration:g}s - outro {outro:g}s.")
        for s in secs:
            steps.append(f"S{s['idx'] + 1} {s['title']}: {s['summary']}")

        keys = ("idx", "first_play", "last_play", "t_start", "t_end", "title_sec", "wp_home_start",
                "wp_home_end", "swing", "pivot", "score_start", "score_end", "title", "summary",
                "key_plays", "scoring_plays")
        public = [{k: s[k] for k in keys} for s in secs]
        limit = int(p.section_note_chars)
        groups = [Outcome(f"{s['idx'] + 1}. {s['title']}", probability=abs(s["swing"]), fmt="pct",
                          group="Sections", note=sections._fit([s["summary"]], limit)) for s in secs]
        return plays, top, groups, {"sections": public}


    # ----------------------------------------------------------------------------------

    def _play(self, e: dict, type_text: str, idx: int, before: float, after: float,
              home_score: int, away_score: int, team_side: dict[str, str]) -> dict[str, Any]:
        p = self.params
        start, end = e.get("start") or {}, e.get("end") or {}
        kickoff = "kickoff" in type_text.lower()
        down = _int_or_none(start.get("down"))
        if kickoff or down not in (1, 2, 3, 4):
            down = None
        distance = _int_or_none(start.get("distance")) if down is not None else None
        start_team = str((start.get("team") or {}).get("id") or "")
        if not start_team:
            start_team = next((str(t.get("id")) for t in e.get("teamParticipants") or []
                               if t.get("type") == "offense"), "")
        end_team = str((end.get("team") or {}).get("id") or "")
        text = str(e.get("text") or "")
        lower_type = type_text.lower()
        on_downs = ("turnover on downs" in text.lower()
                    or (start.get("down") == 4 and lower_type in OFFENSE_TYPES
                        and start_team and end_team and start_team != end_team))
        turnover = bool(e.get("isTurnover")) or on_downs or "interception" in lower_type
        return {
            "idx": idx,
            "id": str(e.get("id")),
            "kind": "play",
            "quarter": _int_or_none((e.get("period") or {}).get("number")) or 0,
            "clock": _clock((e.get("clock") or {}).get("displayValue")),
            "down": down,
            "distance": distance,
            "yardline_text": start.get("possessionText") or self._yardline(start, start_team, team_side),
            "possession": team_side.get(start_team),
            "yards_to_endzone": _int_or_none(start.get("yardsToEndzone")),
            "text": text,
            "short_text": clean_text(text, int(p.short_text_chars)),
            "type": type_text,
            "scoring": False,  # set after scores are known
            "turnover": turnover,
            "home_score": home_score,
            "away_score": away_score,
            "wp_home_before": before,
            "wp_home_after": after,
            "_espn_scoring": bool(e.get("scoringPlay")),
            "_drive": e.get("_drive"),
            "_on_downs": on_downs,
        }

    def _drive_event(self, grp: list[dict[str, Any]], meta: dict[str, str]) -> dict[str, Any]:
        """One timeline event standing for a whole quiet drive."""
        first, last = grp[0], grp[-1]
        # ESPN opens a drive with the kickoff, whose "possession" is the kicking team: take the
        # drive's team (and starting spot) from its first non-kickoff snap.
        snaps = [pl for pl in grp if "kickoff" not in pl["type"].lower() and pl["possession"]] or grp
        counts: dict[str, int] = {}
        for pl in snaps:
            if pl["possession"]:
                counts[pl["possession"]] = counts.get(pl["possession"], 0) + 1
        side = max(counts, key=counts.get) if counts else (first["possession"] or last["possession"])
        start = next((pl for pl in snaps if pl["possession"] == side), first)
        abbr = self._abbr.get(side, "") if side else ""
        result = DRIVE_RESULTS.get(meta.get("result", "").upper(), meta.get("result", "").title())
        summary = meta.get("description") or f"{len(grp)} plays"
        text = " · ".join(x for x in (f"{abbr} drive".strip(), summary, result) if x)
        swing = round(last["wp_home_after"] - first["wp_home_before"], 6)
        return {
            "idx": first["idx"], "id": f"drive-{first['id']}", "kind": "drive",
            "quarter": first["quarter"], "clock": first["clock"], "down": None, "distance": None,
            "yardline_text": start["yardline_text"], "possession": side,
            "yards_to_endzone": start["yards_to_endzone"],
            "end_yards_to_endzone": next((pl["yards_to_endzone"] for pl in reversed(snaps)
                                          if pl["possession"] == side), last["yards_to_endzone"]),
            "text": text, "short_text": text, "type": "Drive",
            "scoring": any(pl["scoring"] for pl in grp), "turnover": any(pl["turnover"] for pl in grp),
            "home_score": last["home_score"], "away_score": last["away_score"],
            "wp_home_before": first["wp_home_before"], "wp_home_after": last["wp_home_after"],
            "swing": swing, "abs_swing": abs(swing), "highlight": False, "headline": None,
            "n_plays": len(grp), "drive_summary": summary, "drive_result": result,
            "_drive": first["_drive"],
        }

    def _yardline(self, start: dict, team_id: str, team_side: dict[str, str]) -> str | None:
        """'MIA 35' from yardsToEndzone when ESPN gives no possessionText (e.g. kickoffs)."""
        yte = _int_or_none(start.get("yardsToEndzone"))
        side = team_side.get(team_id)
        if yte is None or side is None or not 0 < yte < 100:
            return None
        if yte == 50:
            return "50"
        own, opp = self._abbr[side], self._abbr["away" if side == "home" else "home"]
        return f"{own} {100 - yte}" if yte > 50 else f"{opp} {yte}"

    def _headline(self, pl: dict[str, Any], home: dict, away: dict) -> str | None:
        dh, da = pl["_points"]
        kind = pl["type"].lower()
        if pl["scoring"]:
            scorer = home if dh >= da else away
            points = max(dh, da)
            if points >= 6 or "touchdown" in kind:
                return f"TOUCHDOWN {scorer['short'].upper()}"
            if points == 3 or "field goal good" in kind:
                return "FIELD GOAL"
            if points == 2 or "safety" in kind:
                return "SAFETY"
        if "blocked field goal" in kind:
            return "BLOCKED FIELD GOAL"
        if "field goal missed" in kind or "missed field goal" in kind:
            return "MISSED FIELD GOAL"
        if pl["turnover"]:
            if "interception" in kind:
                return "INTERCEPTION"
            if "fumble" in kind or "fumble" in pl["text"].lower():
                return "FUMBLE"
            if pl["_on_downs"]:
                return "TURNOVER ON DOWNS"
            return "TURNOVER"
        if pl["abs_swing"] >= self.params.big_play_swing:
            return "BIG PLAY"
        return None

    @staticmethod
    def _note(pl: dict[str, Any], home: dict, away: dict) -> str:
        q = f"Q{pl['quarter']}" if pl["quarter"] <= 4 else ("OT" if pl["quarter"] == 5 else f"{pl['quarter'] - 4}OT")
        toward = home["abbr"] if pl["swing"] >= 0 else away["abbr"]
        return f"{q} {pl['clock']}, toward {toward}: {pl['short_text']}"
