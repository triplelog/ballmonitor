"""structure = "chart" (v0.4.0): a vertical win-probability chart with annotated plays.

The game runs top to bottom down the left of the frame; cards on the right point to the
moments that mattered. Three steps, all tunable in config.toml:

1. Pick cards: every scoring play, then the most important other plays (formula
   `chart_importance`), up to `chart_cards`. The `chart_large_cards` most important get a
   bigger card.
2. Warp time: each card gets a vertical slot (`chart_large_units` for big cards, 1 for the
   rest) and its play sits at the slot's centre; plays between two cards are spread evenly
   between them, so quiet stretches are compressed and busy ones stretched.
3. Time: cards appear one at a time; each card's reveal lasts formula `chart_reveal_weight`
   scaled to fill the body (clamped to [chart_min_reveal_sec, chart_max_reveal_sec]). During a
   reveal the line draws down to the card's play; plays after the last card are drawn in the
   last reveal.
"""

from __future__ import annotations

from typing import Any

from ballmonitor.models.cfb_replay import sections


def importance(pl: dict, info: dict, p) -> float:
    kick = info["kind"] in ("blocked_fg", "missed_fg", "blocked_punt")
    long_play = (info["kind"] in ("pass", "rush") and info["yards"] is not None
                 and info["yards"] >= p.long_play_yards)
    return float(p.formula("chart_importance", abs_swing=pl["abs_swing"], scoring=float(pl["scoring"]),
                           turnover=float(pl["turnover"] or kick), long_play=float(long_play)))


LABELS = {"pass_td": "Touchdown", "rush_td": "Touchdown", "td": "Touchdown", "int_td": "Pick six",
          "fumble_td": "Fumble return TD", "punt_ret_td": "Punt return TD", "kick_ret_td": "Kick return TD",
          "block_td": "Block return TD", "fg": "Field goal", "safety": "Safety", "blocked_fg": "Blocked kick", "missed_fg": "Missed kick",
          "blocked_punt": "Blocked punt", "interception": "Interception", "fumble": "Fumble", "downs": "Turnover on downs",
          "turnover": "Turnover", "sack": "Sack"}


def label(pl: dict, info: dict) -> str:
    """Short kind of play for a card ('Touchdown', 'Field goal', 'Big play'): no team names."""
    if info["kind"] in LABELS:
        return LABELS[info["kind"]]
    if pl["scoring"]:
        return "Score"
    if pl["turnover"]:
        return "Turnover"
    return "Big play"


def fallback_phrase(pl: dict, info: dict, name) -> str:
    """An ordinary gain that still swung WP: 'Miami completes a 21-yard pass' / 'Pitt runs for 6 yards'."""
    team, y = name(pl.get("possession")), info["yards"]
    if info["kind"] == "pass" and y is not None:
        who = f" to {info['receiver']}" if info.get("receiver") else ""
        return f"{team} completes a {y}-yard pass{who}" if y > 0 else f"{team}: incomplete pass"
    if info["kind"] == "rush" and y is not None:
        return f"{team} runs for {y} yard{'s' if abs(y) != 1 else ''}" if y else f"{team}: no gain"
    return sections.clean_text(pl["short_text"], 80)


def build(plays: list[dict[str, Any]], pregame: float, ctx: dict[str, Any], headline, name) -> tuple:
    p, steps = ctx["p"], ctx["steps"]
    intro, body, duration, outro = ctx["intro"], ctx["body"], ctx["duration"], ctx["outro"]
    infos = [sections.parse_play(pl) for pl in plays]
    for pl in plays:
        pl["headline"] = headline(pl)
    imp = [importance(pl, info, p) for pl, info in zip(plays, infos)]

    # 1. cards: every score, then the most important other plays
    n_cards = int(p.chart_cards)
    scores = [k for k, pl in enumerate(plays) if pl["scoring"]]
    others = sorted((k for k in range(len(plays)) if not plays[k]["scoring"]
                     and plays[k]["abs_swing"] >= p.chart_min_swing), key=lambda k: (-imp[k], k))
    if len(scores) > n_cards:  # a shootout: keep the most important scores
        scores = sorted(sorted(scores, key=lambda k: (-imp[k], k))[:n_cards])
    cards = sorted(set(scores + others[: max(0, n_cards - len(scores))]))
    if not cards:
        cards = [max(range(len(plays)), key=lambda k: imp[k])]
    by_imp = sorted(cards, key=lambda k: (-imp[k], k))
    large = set(by_imp[: int(p.chart_large_cards)])
    top = by_imp[: int(p.section_highlight_count)]
    steps.append(f"Structure = chart. Cards: {len(scores)} scoring plays + "
                 f"{len(cards) - len([k for k in cards if plays[k]['scoring']])} other plays by "
                 f"chart_importance = {p.expr('chart_importance')} (|swing| >= {p.chart_min_swing:g}), "
                 f"target chart_cards = {n_cards}; {len(large)} large cards.")

    # 2. warp: card slots, plays between cards spread evenly
    units = [float(p.chart_large_units) if k in large else 1.0 for k in cards]
    margin = float(p.chart_margin_units)
    total = sum(units) + 2 * margin
    anchors, acc = [], margin
    for u in units:
        anchors.append((acc + u / 2) / total)
        acc += u
    y = [0.0] * len(plays)
    knots = [(-1, 0.0)] + list(zip(cards, anchors)) + [(len(plays) - 1, 1.0)]
    if cards[-1] == len(plays) - 1:
        knots = knots[:-1]
    for (k0, y0), (k1, y1) in zip(knots, knots[1:]):
        for k in range(max(k0 + 1, 0), k1 + 1):
            y[k] = y0 + (y1 - y0) * (k - k0) / (k1 - k0)
    for pl, v in zip(plays, y):
        pl["y"] = round(v, 6)
    span = [(anchors[i] - (anchors[i - 1] if i else 0.0)) for i in range(len(cards))]
    steps.append(f"Time axis warped so each card's play sits at its slot centre: plays between cards "
                 f"spread evenly; slot units 1 (normal) / {p.chart_large_units:g} (large), margins "
                 f"{margin:g}. Largest stretch {max(span):.2f} of the height, smallest {min(span):.2f}.")

    # 3. reveal timing
    weights = [float(p.formula("chart_reveal_weight", importance=imp[k], scoring=float(plays[k]["scoring"]),
                               large=float(k in large))) for k in cards]
    durs, how = sections.allocate(weights, body, float(p.chart_min_reveal_sec), float(p.chart_max_reveal_sec))
    t, starts = intro, []
    for i, d in enumerate(durs):
        starts.append(t)
        t = duration - outro if i == len(durs) - 1 else t + d
    ends = starts[1:] + [duration - outro]
    draw = float(p.chart_draw_share)
    prev = -1
    for i, k in enumerate(cards):
        seg = list(range(prev + 1, k + 1))
        if i == len(cards) - 1:
            seg = list(range(prev + 1, len(plays)))
        span_t = (ends[i] - starts[i])
        # plays up to the card are drawn in the first `draw` share; trailing plays (last card only)
        # are drawn after the card's own pause
        upto = [j for j in seg if j <= k]
        after = [j for j in seg if j > k]
        lead = span_t * draw
        for n, j in enumerate(upto):
            plays[j]["t_start"] = starts[i] + lead * n / len(upto)
            plays[j]["t_end"] = starts[i] + lead * (n + 1) / len(upto)
        if after:
            tail0 = starts[i] + span_t * (1 - draw)
            plays[k]["t_end"] = tail0
            for n, j in enumerate(after):
                plays[j]["t_start"] = tail0 + (ends[i] - tail0) * n / len(after)
                plays[j]["t_end"] = tail0 + (ends[i] - tail0) * (n + 1) / len(after)
        else:
            plays[k]["t_end"] = ends[i]
        prev = seg[-1]
    for a, b in zip(plays, plays[1:]):  # exact contiguity
        b["t_start"] = a["t_end"]
    plays[-1]["t_end"] = duration - outro
    steps.append(f"Reveals: weight = {p.expr('chart_reveal_weight')}, clamped to "
                 f"[{p.chart_min_reveal_sec:g}, {p.chart_max_reveal_sec:g}] s ({how}): "
                 + ", ".join(f"{d:.1f}" for d in durs) + " s.")

    annotations = []
    for i, k in enumerate(cards):
        pl = plays[k]
        phrase = sections.play_phrase(pl, infos[k], name, p) or fallback_phrase(pl, infos[k], name)
        pl["phrase"] = phrase
        pl["key"] = True
        annotations.append({
            "idx": i, "play": k, "size": "large" if k in large else "normal", "units": units[i],
            "slot_h": round(units[i] / total, 6),
            "y": round(anchors[i], 6), "t_start": starts[i], "t_show": pl["t_start"], "t_end": ends[i],
            "headline": pl["headline"] or ("SCORE" if pl["scoring"] else pl["type"].upper()),
            "label": label(pl, infos[k]),
            "phrase": phrase, "swing": pl["swing"], "abs_swing": pl["abs_swing"],
            "team": ("home" if pl["swing"] >= 0 else "away") if not pl["scoring"]
            else (infos[k]["scorer"] or ("home" if pl["swing"] >= 0 else "away")),
            "scoring": pl["scoring"], "quarter": pl["quarter"], "clock": pl["clock"],
            "home_score": pl["home_score"], "away_score": pl["away_score"],
            "importance": round(imp[k], 4),
        })
    for k, pl in enumerate(plays):
        pl["highlight"] = k in top
        pl.setdefault("key", False)
    return plays, top, annotations
