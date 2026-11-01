import json
import re

import pytest

from ballmonitor.core import registry
from ballmonitor.models.cfb_replay.model import allocate, clean_text

GAMES = ["401858274", "401858275", "401856834"]
OFFLINE = {"allow_network": False}


def run(inputs, variant=None, **overrides):
    return registry.load_model("cfb_replay", variant, {**OFFLINE, **overrides}).predict(inputs)


def run_plays(inputs, **overrides):
    """structure = plays (the v0.2.0 per-play pacing)."""
    return run(inputs, "plays_only", **overrides)


@pytest.fixture(scope="module", params=GAMES)
def pred(request):
    return run_plays({"game": request.param})


def run_sections(inputs, **overrides):
    """structure = sections (the v0.3.0 chapters)."""
    return run(inputs, "chapters", **overrides)


@pytest.fixture(scope="module", params=GAMES)
def spred(request):
    return run_sections({"game": request.param})


@pytest.fixture(scope="module", params=GAMES)
def cpred(request):
    return run({"game": request.param})


PARAMS = registry.load_model("cfb_replay").params


def durations(plays):
    return [pl["t_end"] - pl["t_start"] for pl in plays]


# ---- timeline contract ------------------------------------------------------------------


def test_durations_sum_exactly(pred):
    tl, plays = pred.extras["timeline"], pred.extras["plays"]
    assert tl["duration_sec"] == PARAMS.duration_sec == 60.0
    assert plays[0]["t_start"] == tl["intro_sec"]
    assert plays[-1]["t_end"] == tl["duration_sec"] - tl["outro_sec"]
    total = tl["intro_sec"] + sum(durations(plays)) + tl["outro_sec"]
    assert total == pytest.approx(tl["duration_sec"], abs=1e-9)


def test_times_monotone_and_contiguous(pred):
    plays = pred.extras["plays"]
    for a, b in zip(plays, plays[1:]):
        assert b["t_start"] == a["t_end"]
    assert all(pl["t_end"] > pl["t_start"] for pl in plays)
    assert [pl["idx"] for pl in plays] == list(range(len(plays)))


def test_floor_and_cap_respected(pred):
    p = PARAMS
    for pl in pred.extras["plays"]:
        d = pl["t_end"] - pl["t_start"]
        floor = p.min_drive_sec if pl["kind"] == "drive" else p.min_play_sec
        assert floor - 1e-6 <= d <= p.max_play_sec + 1e-6


def test_big_swings_get_more_time_than_small(pred):
    plays = pred.extras["plays"]
    held = [pl for pl in plays if pl["highlight"]]
    ordinary = [pl for pl in plays if pl["kind"] == "play" and not (pl["highlight"] or pl["scoring"] or pl["turnover"])]
    assert min(durations(held)) > max(durations(ordinary))
    smallest = min(ordinary, key=lambda pl: pl["abs_swing"])
    assert smallest["t_end"] - smallest["t_start"] == pytest.approx(PARAMS.min_play_sec, abs=1e-6)
    # Highlights are held for seconds; ordinary plays flash by at the floor.
    assert all(d >= 2.0 for d in durations(held))
    at_floor = sum(1 for pl in ordinary if pl["t_end"] - pl["t_start"] < PARAMS.min_play_sec + 1e-4)
    assert at_floor > len(ordinary) / 2


def test_highlight_count_and_order(pred):
    plays, top = pred.extras["plays"], pred.extras["top_plays"]
    assert len(top) == int(PARAMS.highlight_count) or len(top) == sum(pl["highlight"] for pl in plays)
    assert len(top) <= int(PARAMS.highlight_count)
    assert [pl["idx"] for pl in plays if pl["highlight"]] == sorted(top)
    swings = [plays[k]["abs_swing"] for k in top]
    assert swings == sorted(swings, reverse=True)
    others = [pl["abs_swing"] for pl in plays if not pl["highlight"] and pl["kind"] == "play"]
    assert min(swings) >= max(others)


def test_swing_signs_and_wp_chain(pred):
    game, plays = pred.extras["game"], pred.extras["plays"]
    assert plays[0]["wp_home_before"] == game["pregame_wp_home"]
    for a, b in zip(plays, plays[1:]):
        assert b["wp_home_before"] == a["wp_home_after"]
    for pl in plays:
        assert 0.0 <= pl["wp_home_before"] <= 1.0 and 0.0 <= pl["wp_home_after"] <= 1.0
        assert pl["swing"] == pytest.approx(pl["wp_home_after"] - pl["wp_home_before"], abs=1e-6)
        assert pl["abs_swing"] == pytest.approx(abs(pl["swing"]))


def test_play_fields(pred):
    keys = {"idx", "id", "quarter", "clock", "down", "distance", "yardline_text", "possession",
            "yards_to_endzone", "text", "short_text", "type", "scoring", "turnover", "home_score",
            "away_score", "wp_home_before", "wp_home_after", "swing", "abs_swing", "t_start", "t_end",
            "highlight", "headline", "kind"}
    drive_keys = keys | {"n_plays", "drive_summary", "drive_result", "end_yards_to_endzone"}
    for pl in pred.extras["plays"]:
        assert set(pl) == (drive_keys if pl["kind"] == "drive" else keys)
        if pl["kind"] == "drive":
            continue
        assert len(pl["short_text"]) <= 90 and not pl["short_text"].startswith("(")
        assert len(pl["clock"]) == 5 and pl["clock"][2] == ":"
        assert pl["possession"] in ("home", "away", None)
        assert pl["down"] in (None, 1, 2, 3, 4)
        if not (pl["highlight"] or pl["scoring"] or pl["turnover"]) and pl["abs_swing"] < 0.10:
            assert pl["headline"] is None or "FIELD GOAL" in pl["headline"]
    json.dumps(pred.extras)


def test_game_header(pred):
    g = pred.extras["game"]
    assert g["wp_source"] == "ESPN"
    for side in ("home", "away"):
        t = g[side]
        assert set(t) == {"name", "short", "abbr", "color", "alt_color", "rank", "record"}
        assert len(t["color"]) == 7 and t["color"].startswith("#")
    plays = pred.extras["plays"]
    assert (plays[-1]["home_score"], plays[-1]["away_score"]) == (g["final"]["home"], g["final"]["away"])
    scores = [(pl["home_score"], pl["away_score"]) for pl in plays]
    assert all(b[0] >= a[0] and b[1] >= a[1] for a, b in zip(scores, scores[1:]))
    assert pred.extras["timeline"] == {"duration_sec": 60.0, "intro_sec": 1.5, "outro_sec": 2.5,
                                       "fps": 30, "width": 1080, "height": 1920}


# ---- known values from the bundled games ------------------------------------------------


def test_default_game_known_values():
    # every play, uncollapsed, so each scoring play keeps its own headline
    pred = run(registry.load_example("cfb_replay", "pitt_miami"), drive_collapse_max_swing=0.0)
    g = pred.extras["game"]
    assert g["home"]["abbr"] == "MIA" and g["away"]["abbr"] == "PITT"
    assert g["final"] == {"home": 52, "away": 23}
    assert g["pregame_wp_home"] == pytest.approx(0.9252)
    assert g["home"]["rank"] == 1 and g["away"]["rank"] is None
    assert g["venue"] == "Hard Rock Stadium"
    assert pred.extras["plays"][0]["yardline_text"] == "MIA 35"  # kickoff, from yardsToEndzone
    heads = [pl["headline"] for pl in pred.extras["plays"] if pl["headline"]]
    assert heads.count("TOUCHDOWN MIAMI") == 7 and heads.count("TOUCHDOWN PITTSBURGH") == 3
    assert "SAFETY" in heads and "FIELD GOAL" in heads and "FUMBLE" in heads


def test_overtime_walkoff():
    pred = run_plays({"game": "401858275"})
    plays, top = pred.extras["plays"], pred.extras["top_plays"]
    best = plays[top[0]]
    assert best["quarter"] == 5 and best["headline"] == "TOUCHDOWN SYRACUSE"
    assert best["swing"] < -0.7  # toward the away team
    assert best["t_end"] - best["t_start"] == pytest.approx(PARAMS.max_play_sec)
    assert pred.primary.probability == pytest.approx(best["abs_swing"])
    assert pred.extras["game"]["status_text"] == "Final/OT"


def test_lookup_by_teams_and_date():
    pred = run({"home": "Kansas", "away": "Baylor", "date": "2026-10-24"})
    assert pred.extras["game"]["id"] == "401856834"
    best = pred.extras["plays"][pred.extras["top_plays"][0]]
    assert best["headline"] == "BLOCKED FIELD GOAL" and best["turnover"] and best["swing"] > 0.5


# ---- overrides --------------------------------------------------------------------------


def test_duration_override_input():
    pred = run({"game": "401858274", "duration_sec": 45})
    plays = pred.extras["plays"]
    assert pred.extras["timeline"]["duration_sec"] == 45.0
    assert plays[-1]["t_end"] == 45.0 - 2.5


def test_more_highlights_and_bigger_cap():
    pred = run_plays({"game": "401858275"}, highlight_count=8)
    assert len(pred.extras["top_plays"]) == 8
    small = run_plays({"game": "401858275"}, max_play_sec=2.0)
    assert max(durations(small.extras["plays"])) <= 2.0 + 1e-6


def test_raising_floor_shrinks_highlights():
    base = run_plays({"game": "401856834"})
    floor = run_plays({"game": "401856834"}, min_play_sec=0.15)
    k = base.extras["top_plays"][1]
    held = lambda p: p.extras["plays"][k]["t_end"] - p.extras["plays"][k]["t_start"]  # noqa: E731
    assert held(floor) < held(base)


def test_formula_override():
    pred = run_plays({"game": "401858274"}, drive_collapse_max_swing=0.0, **{"formulas.play_weight": "1"})
    d = durations(pred.extras["plays"])
    assert max(d) == pytest.approx(min(d))


# ---- allocation + text helpers ----------------------------------------------------------


def test_allocate_hits_body_and_bounds():
    w = [0.0] * 150 + [0.1, 0.5, 1.0, 5.0]
    d, _ = allocate(w, 26.0, 0.05, 3.5)
    assert sum(d) == pytest.approx(26.0)
    assert all(0.05 - 1e-9 <= x <= 3.5 + 1e-9 for x in d)
    assert d[-1] >= d[-2] >= d[-3] >= d[-4] >= d[0]


def test_allocate_infeasible_floor_gives_equal_shares():
    d, how = allocate([1.0] * 10, 0.2, 0.05, 3.5)
    assert d == pytest.approx([0.02] * 10) and "floors scaled down" in how


def test_clean_text():
    raw = "(12:29) Shotgun #21 J.Mallory rush middle for 16 yards gain to the PIT00 TOUCHDOWN, clock 12:25"
    assert clean_text(raw, 90) == "J.Mallory rush middle for 16 yards gain to the PIT00 TOUCHDOWN"
    assert len(clean_text("word " * 50, 90)) <= 90


# ---- errors -----------------------------------------------------------------------------


@pytest.mark.parametrize("game", ["abc", "12", "", "4018582x4"])
def test_bad_game_id(game):
    with pytest.raises(ValueError):
        run({"game": game})


def test_unknown_game_offline():
    with pytest.raises(ValueError):
        run({"game": "999999999"})


def test_unknown_teams_offline():
    with pytest.raises(ValueError):
        run({"home": "Nowhere State", "away": "Baylor", "date": "2026-10-24"})


def test_too_short_duration():
    with pytest.raises(ValueError):
        run({"game": "401858274", "duration_sec": 3})


# ---- collapsed drives ---------------------------------------------------------------------


def test_quiet_drives_collapse_and_big_ones_stay(pred):
    p = PARAMS
    plays = pred.extras["plays"]
    drives = [pl for pl in plays if pl["kind"] == "drive"]
    assert drives, "every bundled game has at least one quiet drive"
    for d in drives:
        assert d["n_plays"] >= p.drive_collapse_min_plays and not d["highlight"]
        assert d["t_end"] - d["t_start"] >= p.min_drive_sec - 1e-6
        assert " drive" in d["short_text"]
    # every highlight survives as its own play
    assert all(plays[k]["kind"] == "play" for k in pred.extras["top_plays"])


def test_collapse_can_be_switched_off():
    on = run_plays({"game": "401858275"})
    off = run_plays({"game": "401858275"}, drive_collapse_max_swing=0.0)
    assert all(pl["kind"] == "play" for pl in off.extras["plays"])
    assert len(off.extras["plays"]) > len(on.extras["plays"])
    # the win-probability chain and final score are unchanged by collapsing
    for pred in (on, off):
        assert pred.extras["plays"][-1]["wp_home_after"] == off.extras["plays"][-1]["wp_home_after"]


def test_allocate_per_item_floors():
    d, _ = allocate([0.0, 0.0, 1.0], 3.0, [0.5, 0.2, 0.2], 5.0)
    assert d[0] == pytest.approx(0.5) and d[1] == pytest.approx(0.2) and sum(d) == pytest.approx(3.0)


def test_short_cut_variant_is_30_seconds():
    pred = run({"game": "401858275"}, variant="short_cut")
    assert pred.extras["timeline"]["duration_sec"] == 30.0


def test_short_cut_variant_keeps_per_play_structure():
    pred = run({"game": "401858275"}, variant="short_cut")
    assert pred.extras["structure"] == "plays"


# ---- v0.2.0 reproduced by structure = plays ----------------------------------------------

# sha256 of the v0.2.0 extras (floats rounded to 6 places), recorded before v0.3.0.
V020 = {
    "401858274": "285a591375892421cd059f37cc83d0c35b1a4159f1d183726de9b1fb904a99fa",
    "401858275": "10db141531ab196913d0fe7a33f688a63acaeaca1d89b2fd82b658eff3ac982f",
    "401856834": "fd8f9db070a132657a04de069b1992f646d59f7c0fb966ac97b10ecaf2e80e1b",
}


def _rounded(o):
    if isinstance(o, float):
        return round(o, 6)
    if isinstance(o, dict):
        return {k: _rounded(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_rounded(v) for v in o]
    return o


@pytest.mark.parametrize("game", GAMES)
def test_plays_structure_reproduces_v020(game):
    import hashlib
    extras = dict(run_plays({"game": game}).extras)
    assert extras.pop("structure") == "plays" and "sections" not in extras
    digest = hashlib.sha256(json.dumps(_rounded(extras), sort_keys=True).encode()).hexdigest()
    assert digest == V020[game]


# ---- sections (variant chapters) ---------------------------------------------------------

SECTION_KEYS = {"idx", "first_play", "last_play", "t_start", "t_end", "title_sec", "wp_home_start",
                "wp_home_end", "swing", "pivot", "score_start", "score_end", "title", "summary",
                "key_plays", "scoring_plays"}


def own(pl, secs):
    """A play's own screen time (the section title lead-in removed from the section's first play)."""
    s = secs[pl["section"]]
    return pl["t_end"] - pl["t_start"] - (s["title_sec"] if pl["idx"] == s["first_play"] else 0.0)


def test_sections_contiguous_and_cover_all_plays(spred):
    ex = spred.extras
    secs, plays = ex["sections"], ex["plays"]
    assert ex["structure"] == "sections"
    assert all(pl["kind"] == "play" for pl in plays)  # no drive collapsing
    assert secs[0]["first_play"] == 0 and secs[-1]["last_play"] == len(plays) - 1
    for i, s in enumerate(secs):
        assert set(s) == SECTION_KEYS and s["idx"] == i
        assert s["last_play"] >= s["first_play"]
        assert s["pivot"] in ("peak", "valley", "split", "end")
        for k in range(s["first_play"], s["last_play"] + 1):
            assert plays[k]["section"] == i
            assert plays[k]["key"] == (k in s["key_plays"])
        assert s["swing"] == pytest.approx(s["wp_home_end"] - s["wp_home_start"], abs=1e-6)
        assert s["wp_home_start"] == plays[s["first_play"]]["wp_home_before"]
        assert s["wp_home_end"] == plays[s["last_play"]]["wp_home_after"]
    for a, b in zip(secs, secs[1:]):
        assert b["first_play"] == a["last_play"] + 1
        assert b["score_start"] == a["score_end"]
    assert secs[-1]["pivot"] == "end"
    json.dumps(ex)


def test_about_n_sections(spred):
    assert abs(len(spred.extras["sections"]) - PARAMS.n_sections) <= 2


def test_every_score_is_a_key_play(spred):
    ex = spred.extras
    plays, secs = ex["plays"], ex["sections"]
    scoring = [pl["idx"] for pl in plays if pl["scoring"]]
    assert sorted(k for s in secs for k in s["scoring_plays"]) == scoring
    for s in secs:
        assert set(s["scoring_plays"]) <= set(s["key_plays"])
        assert 1 <= len(s["key_plays"]) <= 4 and s["key_plays"] == sorted(s["key_plays"])
    # highlights are inside sections and held as key plays
    assert len(ex["top_plays"]) == PARAMS.section_highlight_count
    assert all(plays[k]["key"] and plays[k]["highlight"] for k in ex["top_plays"])


def test_summaries_name_every_score(spred):
    ex = spred.extras
    plays = ex["plays"]
    for s in ex["sections"]:
        assert len(s["summary"]) <= PARAMS.summary_max_chars and s["summary"].endswith(".")
        assert 0 < len(s["title"]) <= PARAMS.section_title_chars
        pts = [max(plays[k]["home_score"] - (plays[k - 1]["home_score"] if k else 0),
                   plays[k]["away_score"] - (plays[k - 1]["away_score"] if k else 0)) for k in s["scoring_plays"]]
        text = s["summary"]
        tds = len(re.findall(r"\bTD\b|touchdown|pick-six", text))
        fgs = len(re.findall(r"field goal|\bFG\b", text))
        safeties = len(re.findall(r"safety", text))
        assert tds >= sum(1 for x in pts if x >= 6), text
        assert fgs >= sum(1 for x in pts if x == 3), text
        assert safeties >= sum(1 for x in pts if x == 2), text


def test_section_times_exact(spred):
    ex = spred.extras
    tl, secs, plays = ex["timeline"], ex["sections"], ex["plays"]
    assert secs[0]["t_start"] == tl["intro_sec"] == plays[0]["t_start"]
    assert secs[-1]["t_end"] == tl["duration_sec"] - tl["outro_sec"] == plays[-1]["t_end"]
    for a, b in zip(secs, secs[1:]):
        assert b["t_start"] == a["t_end"]
    for a, b in zip(plays, plays[1:]):
        assert b["t_start"] == a["t_end"] and b["t_end"] > b["t_start"]
    for s in secs:
        assert plays[s["first_play"]]["t_start"] == s["t_start"]
        assert plays[s["last_play"]]["t_end"] == s["t_end"]
        assert s["title_sec"] == pytest.approx(PARAMS.section_title_sec)
        assert PARAMS.min_section_sec - 1e-6 <= s["t_end"] - s["t_start"]
    total = sum(s["t_end"] - s["t_start"] for s in secs)
    assert total == pytest.approx(tl["duration_sec"] - tl["intro_sec"] - tl["outro_sec"], abs=1e-9)


def test_key_plays_held_longer(spred):
    ex = spred.extras
    secs, plays = ex["sections"], ex["plays"]
    key = [own(pl, secs) for pl in plays if pl["key"]]
    other = [own(pl, secs) for pl in plays if not pl["key"]]
    assert min(key) > max(other)
    assert min(other) >= PARAMS.min_play_sec - 1e-6
    assert max(other) <= PARAMS.rest_play_max_sec + 1e-6
    assert min(key) >= PARAMS.key_min_sec - 1e-6


def test_sections_outcomes_and_steps(spred):
    group = [o for o in spred.outcomes if o.group == "Sections"]
    assert len(group) == len(spred.extras["sections"])
    for o, s in zip(group, spred.extras["sections"]):
        assert o.label == f"{s['idx'] + 1}. {s['title']}"
        assert o.probability == pytest.approx(abs(s["swing"]))
        assert len(o.note) <= PARAMS.section_note_chars
    assert spred.primary.label == "Biggest swing (ESPN WP)"
    assert any("Zig-zag pivots" in st for st in spred.steps)


def test_ot_game_section_text():
    ex = run_sections({"game": "401858275"}).extras
    last = ex["sections"][-1]
    assert "Syracuse" in last["title"] and "OT" in last["title"]
    assert "Syracuse scores on a 4-yard TD pass from Angeli to Russell" in last["summary"]
    assert "2-pt" in last["summary"]
    text = " ".join(s["summary"] for s in ex["sections"])
    assert "76-yard TD pass from Angeli to Hatcher" in text
    assert "3-yard TD run by Hill (PAT missed)" in text
    assert ex["sections"][0]["title"] == "North Carolina strikes first"
    assert last["score_end"] == {"home": 30, "away": 31}


def test_baylor_kansas_section_text():
    ex = run_sections({"game": "401856834"}).extras
    text = " ".join(s["summary"] for s in ex["sections"])
    assert "42-yard pick-six by Jordan" in text
    assert "Kansas blocks a 45-yard Baylor field goal" in text
    assert any(s["title"] == "Pick-six flips it" for s in ex["sections"])


def test_more_sections_param():
    few = run_sections({"game": "401858275"}, n_sections=6).extras["sections"]
    many = run_sections({"game": "401858275"}, n_sections=14).extras["sections"]
    assert len(few) < len(many)
    assert abs(len(few) - 6) <= 2 and abs(len(many) - 14) <= 2


def test_score_bonus_moves_time_to_scoring_sections():
    base = run_sections({"game": "401858274"}).extras["sections"]
    more = run_sections({"game": "401858274"}, section_score_bonus=3.0).extras["sections"]
    dur = lambda s: s["t_end"] - s["t_start"]  # noqa: E731
    two = [i for i, s in enumerate(base) if len(s["scoring_plays"]) >= 2]
    one = [i for i, s in enumerate(base) if len(s["scoring_plays"]) == 1]
    assert two and one
    gap = lambda secs: sum(dur(secs[i]) for i in two) / len(two) - sum(dur(secs[i]) for i in one) / len(one)  # noqa: E731
    assert gap(more) > gap(base)


def test_text_helpers():
    from ballmonitor.models.cfb_replay.sections import surname, parse_play, zigzag
    assert surname("S.Angeli") == "Angeli" and surname("B.Edwards Jr.") == "Edwards"
    assert surname("C.Russell III") == "Russell" and surname("Holden Geriner") == "Geriner"
    pl = {"text": "Cataurus Hicks 36 Yd pass from Holden Geriner (Antonio Chadha Kick)", "type": "Passing Touchdown",
          "scoring": True, "turnover": False, "_points": (0, 7)}
    info = parse_play(pl)
    assert (info["kind"], info["yards"], info["passer"], info["receiver"]) == ("pass_td", 36, "Geriner", "Hicks")
    fg = parse_play({"text": "Shay Barker 30 Yd Field Goal", "type": "Field Goal Good", "scoring": True,
                     "turnover": False, "_points": (0, 3)})
    assert (fg["kind"], fg["yards"]) == ("fg", 30)
    # peaks/valleys need a reversal of at least the threshold
    assert zigzag([0.5, 0.6, 0.4, 0.45, 0.9], 0.15) == [(1, "peak"), (2, "valley")]
    assert zigzag([0.5, 0.6, 0.4, 0.45, 0.9], 0.3) == [(2, "valley")]  # 0.6 -> 0.4 is too small a drop
    assert zigzag([0.5, 0.6, 0.4, 0.45, 0.9], 0.6) == []


# ---- chart (default structure, v0.4.0) ------------------------------------------------------

def test_chart_timeline_exact_and_contiguous(cpred):
    ex = cpred.extras
    tl, plays, notes = ex["timeline"], ex["plays"], ex["annotations"]
    assert ex["structure"] == "chart"
    assert plays[0]["t_start"] == tl["intro_sec"]
    assert plays[-1]["t_end"] == tl["duration_sec"] - tl["outro_sec"]
    for a, b in zip(plays, plays[1:]):
        assert b["t_start"] == a["t_end"] and b["t_end"] > b["t_start"]
    # cards appear one at a time, in game order, each when the line reaches its play
    assert notes[0]["t_start"] == tl["intro_sec"]
    assert notes[-1]["t_end"] == tl["duration_sec"] - tl["outro_sec"]
    for a, b in zip(notes, notes[1:]):
        assert b["t_start"] == pytest.approx(a["t_end"]) and b["play"] > a["play"]
    for n in notes:
        assert n["t_start"] <= n["t_show"] < n["t_end"]
        assert n["t_show"] == plays[n["play"]]["t_start"]


def test_chart_reveals_clamped_and_fill_body(cpred):
    notes, tl = cpred.extras["annotations"], cpred.extras["timeline"]
    durs = [n["t_end"] - n["t_start"] for n in notes]
    assert sum(durs) == pytest.approx(tl["duration_sec"] - tl["intro_sec"] - tl["outro_sec"])
    for d in durs:
        assert PARAMS.chart_min_reveal_sec - 1e-6 <= d <= PARAMS.chart_max_reveal_sec + 1e-6


def test_chart_every_score_gets_a_card(cpred):
    plays, notes = cpred.extras["plays"], cpred.extras["annotations"]
    scores = [pl["idx"] for pl in plays if pl["scoring"]]
    cards = [n["play"] for n in notes]
    assert len(cards) <= max(PARAMS.chart_cards, 1)
    if len(scores) <= PARAMS.chart_cards:
        assert set(scores) <= set(cards)
    for n in notes:
        pl = plays[n["play"]]
        assert pl["scoring"] or pl["abs_swing"] >= PARAMS.chart_min_swing
        assert n["phrase"] and n["label"]


def test_chart_warp_puts_cards_at_slot_centres(cpred):
    plays, notes = cpred.extras["plays"], cpred.extras["annotations"]
    ys = [pl["y"] for pl in plays]
    assert all(0.0 <= y <= 1.0 for y in ys) and ys == sorted(ys)
    assert sum(n["slot_h"] for n in notes) < 1.0
    for n in notes:
        assert plays[n["play"]]["y"] == pytest.approx(n["y"], abs=1e-5)
    for a, b in zip(notes, notes[1:]):  # neighbouring slots touch: centres half a slot each apart
        assert b["y"] - a["y"] == pytest.approx((a["slot_h"] + b["slot_h"]) / 2, abs=1e-5)
    large = [n for n in notes if n["size"] == "large"]
    assert len(large) == min(PARAMS.chart_large_cards, len(notes))
    assert min(n["importance"] for n in large) >= max(
        (n["importance"] for n in notes if n["size"] == "normal"), default=0)


def test_chart_bigger_plays_pause_longer():
    notes = run({"game": "401858275"}).extras["annotations"]
    dur = {n["play"]: n["t_end"] - n["t_start"] for n in notes}
    big = max(notes, key=lambda n: n["importance"])
    small = min(notes, key=lambda n: n["importance"])
    assert dur[big["play"]] > dur[small["play"]]


def test_chart_known_cards():
    notes = run({"game": "401858275"}).extras["annotations"]
    assert len(notes) == 14 and sum(n["scoring"] for n in notes) == 11
    last = notes[-1]
    assert last["phrase"] == "Syracuse: 4-yard TD pass from Angeli to Russell and the 2-pt try"
    assert last["label"] == "Touchdown" and last["size"] == "large" and last["team"] == "away"
    assert (last["away_score"], last["home_score"]) == (31, 30)
    bk = run({"game": "401856834"}).extras["annotations"]
    assert any(n["phrase"] == "Kansas blocks a 45-yard Baylor field goal" and n["label"] == "Blocked kick"
               for n in bk)


def test_chart_card_count_param():
    few = run({"game": "401856834"}, chart_cards=8).extras["annotations"]
    assert len(few) == 8
    # more scores than cards: the most important scores are kept
    pm = run({"game": "401858274"}, chart_cards=5).extras["annotations"]
    assert len(pm) == 5 and all(n["scoring"] for n in pm)


def test_chart_outcomes(cpred):
    group = [o for o in cpred.outcomes if o.group == "Annotated plays"]
    assert len(group) == len(cpred.extras["annotations"])
    assert any("Structure = chart" in st for st in cpred.steps)


def test_site_page_is_valid_and_covers_every_bundled_game():
    from ballmonitor.core import registry, views
    from ballmonitor.models.cfb_replay import site

    model = registry.load_model("cfb_replay")
    p = views.clean(site.page(model))
    assert views.check(p) == []
    options = p["views"][0]["options"]
    assert len(options) == len(registry.example_names("cfb_replay"))
    for o in options:
        chart, swings = o["views"]
        xs = [x for x, _ in chart["series"][0]["points"]]
        assert xs == sorted(xs) and xs[0] == 0 and xs[-1] <= 60 + site.OT_WIDTH
        assert all(0 <= y <= 1 for _, y in chart["series"][0]["points"])
        assert [r["swing"] for r in swings["rows"]] == sorted((r["swing"] for r in swings["rows"]), reverse=True)
