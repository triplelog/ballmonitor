"""Home Turf (ballmonitor/games/home_turf): the map's rules and the game engine (engine.js under node)."""

import json
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest

from ballmonitor.games.home_turf import build

GAME = Path(__file__).resolve().parent.parent / "ballmonitor" / "games" / "home_turf"
ENGINE = GAME / "web" / "engine.js"
DATA = GAME / "web" / "data" / "game.json"
NODE = shutil.which("node")


def node(script: str):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(f"const E = require({json.dumps(str(ENGINE))});\nconst data = E.prepare(require({json.dumps(str(DATA))}));\n" + script)
    try:
        out = subprocess.run([NODE, fh.name], capture_output=True, text=True, timeout=300)
    finally:
        Path(fh.name).unlink()
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_map_is_valid_and_connected():
    m = build.load_map()   # raises on unknown regions, one-way borders, a birthplace in two territories
    terr = m["territories"]
    seen, todo = {"texas"}, ["texas"]
    while todo:
        t = todo.pop()
        for n in terr[t].get("land", []) + terr[t].get("sea", []):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    assert seen == set(terr), f"not reachable: {set(terr) - seen}"
    for rid, r in m["regions"].items():
        assert r["bonus"] >= 1 and any(t["region"] == rid for t in terr.values())


def test_game_data_matches_the_map():
    game = json.loads(DATA.read_text())
    rules = tomllib.loads((GAME / "rules.toml").read_text())
    assert game["rules"] == rules
    assert {t["id"] for t in game["territories"]} == set(build.load_map()["territories"])
    for tid, roster in game["rosters"].items():
        assert 0 < len(roster) <= rules["roster_depth"]
        career = [sum(r["s"][1::2]) for r in roster]   # compact form: WAR x 10 at odd places
        assert all(a >= b - 1 for a, b in zip(career, career[1:])), tid   # best first (rounding aside)
    names = [(r["n"], r["b"], r["s"][0]) for roster in game["rosters"].values() for r in roster]
    assert len(names) == len(set(names))   # a player belongs to one territory


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_compact_rosters_expand_to_real_seasons():
    out = node("""
const ruth = Object.values(data.rosters).flat().find((p) => p.name === 'Babe Ruth');
console.log(JSON.stringify({ first: ruth.seasons[0], y1921: ruth.seasons.find((s) => s[0] === 1921), n: ruth.seasons.length, war: ruth.war }));""")
    assert out["first"][0] == 1914 and out["n"] == 22 and out["y1921"][1] > 9 and out["war"] > 140


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_battle_chances_and_home_field():
    out = node("""
const A = { seasons: [[2000, 5.0], [2001, 1.0]] }, D = { seasons: [[1990, 4.0]] };
const tie = { seasons: [[1, 3.0]] }, tie2 = { seasons: [[2, 3.5]] };
console.log(JSON.stringify({
  p: E.winProb(A, D, 0.5),          // 5.0 > 4.5 wins, 1.0 doesn't: 1/2
  noHome: E.winProb(A, D, 0),       // still 1/2
  tie: E.winProb(tie2, tie, 0.5),   // 3.5 vs 3.0 + 0.5: a tie goes to the defender
}));""")
    assert out == {"p": 0.5, "noHome": 0.5, "tie": 0}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_full_ai_games_keep_the_rules():
    out = node("""
const results = [];
for (let g = 0; g < 12; g++) {
  const st = E.newGame(data, { seed: `t-${g}`, humanSeats: [] });
  while (st.phase === 'draft') E.aiDraft(st, data);
  const draftedAll = Object.values(st.owner).every((o) => o !== null);
  let guard = 0, problems = [];
  while (st.phase !== 'over' && guard++ < 5000) {
    if (st.phase === 'deploy') { E.aiPlace(st, data); continue; }
    E.aiTurn(st, data);
    // invariants: every soldier in exactly one stack, every non-empty territory owned, no soldier without seasons
    const where = {};
    for (const [t, stack] of Object.entries(st.stacks)) for (const s of stack) { if (where[s]) problems.push(`${s} twice`); where[s] = t; }
    for (const [t, stack] of Object.entries(st.stacks)) if (stack.length && st.owner[t] === null) problems.push(`${t} unowned`);
    for (const s of Object.keys(where)) if (!st.soldiers[s].seasons.length) problems.push(`${s} has no seasons`);
    if (st.phase !== 'over') E.endTurn(st, data);
  }
  results.push({ draftedAll, over: st.phase === 'over', rounds: st.round, problems: problems.slice(0, 3), log: st.log.length,
                 winner: st.winner, seats: st.standings.length });
}
const again = E.newGame(data, { seed: 't-0', humanSeats: [] });
while (again.phase === 'draft') E.aiDraft(again, data);
const first = E.newGame(data, { seed: 't-0', humanSeats: [] });
while (first.phase === 'draft') E.aiDraft(first, data);
console.log(JSON.stringify({ results, same: JSON.stringify(again.owner) === JSON.stringify(first.owner) }));""")
    assert out["same"]   # the same seed gives the same game
    for r in out["results"]:
        assert r["draftedAll"] and r["over"] and not r["problems"], r
        assert r["rounds"] <= 16 and r["seats"] == 4


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_game_lengths():
    out = node("""
const play = (length, cap) => {
  const st = E.newGame(data, { seed: `len-${length}`, humanSeats: [], length });
  while (st.phase === 'draft') E.aiDraft(st, data);
  let guard = 0;
  while (st.phase !== 'over' && st.round <= cap && guard++ < 20000) {
    if (st.phase === 'deploy') { E.aiPlace(st, data); continue; }
    E.aiTurn(st, data); if (st.phase !== 'over') E.endTurn(st, data);
  }
  return { phase: st.phase, round: st.round, maxRounds: E.R(st, data).max_rounds, callupsMin: E.R(st, data).callups_min, aiAttacks: E.R(st, data).ai.max_attacks };
};
console.log(JSON.stringify({ innings: play('innings', 99), standard: play('standard', 99), unlimited: play('unlimited', 20) }));""")
    assert out["innings"]["phase"] == "over" and out["innings"]["round"] == 10 and out["innings"]["maxRounds"] == 9
    assert out["innings"]["callupsMin"] == 4 and out["innings"]["aiAttacks"] == 9          # the 9-inning pacing
    assert out["standard"]["round"] == 16 and out["standard"]["callupsMin"] == 3
    assert out["unlimited"]["maxRounds"] == 0 and out["unlimited"]["round"] > 16           # still going after 20 rounds


def test_regions_are_connected_and_few():
    m = build.load_map()   # load_map also raises if a region is in pieces
    assert len(m["regions"]) <= 8
    assert {"north_carolina", "south_carolina"} <= set(m["territories"]) and "carolinas" not in m["territories"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_season_stats():
    out = node("""console.log(JSON.stringify([E.seasonStats([[1, 2.0], [2, -0.5], [3, 6.1], [4, 3.0]]), E.seasonStats([[1, 1.5]]), E.seasonStats([])]));""")
    assert out[0] == {"n": 4, "median": 2.5, "total": 10.6, "best": 6.1, "worst": -0.5}
    assert out[1]["median"] == 1.5 and out[2]["n"] == 0 and out[2]["median"] is None
