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
        for n in terr[t]["links"]:
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
console.log(JSON.stringify({ innings: play('innings', 99), doubleheader: play('doubleheader', 99), standard: play('standard', 99),
  unlimited: play('unlimited', 20), offered: Object.keys(data.rules.lengths) }));""")
    assert out["innings"]["phase"] == "over" and out["innings"]["round"] == 10 and out["innings"]["maxRounds"] == 9
    assert out["innings"]["callupsMin"] == 4 and out["innings"]["aiAttacks"] == 9          # the 9-inning pacing
    assert out["doubleheader"]["phase"] == "over" and out["doubleheader"]["round"] == 19 and out["doubleheader"]["maxRounds"] == 18
    assert out["offered"] == ["innings", "doubleheader", "unlimited"]
    assert out["standard"]["round"] == 16 and out["standard"]["callupsMin"] == 3            # an old save: the base rules
    assert out["unlimited"]["maxRounds"] == 0 and out["unlimited"]["round"] > 16           # still going after 20 rounds


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_ai_levels():
    out = node("""
const st = (level) => E.newGame(data, { seed: 'lv', humanSeats: [0], level });
const pick = (s) => s.seats.map((x) => [x.ai, x.strategy, x.ai_over || null]);
const rookie = st('rookie'), hof = st('hof'), dflt = st(undefined), old = st(undefined); delete old.level;
old.seats.forEach((x) => { delete x.ai_over; });
console.log(JSON.stringify({ levels: Object.keys(data.rules.levels), rookie: pick(rookie), hof: pick(hof), dflt: dflt.level,
  block: [E.aiP(rookie, data, 1, 'draft_block'), E.aiP(hof, data, 1, 'draft_block'), E.aiP(old, data, 1, 'draft_block')],
  attacks: [E.aiP(rookie, data, 1, 'max_attacks'), E.aiP(dflt, data, 1, 'max_attacks')] }));""")
    assert out["levels"] == ["rookie", "pro", "allstar", "hof"] and out["dflt"] == "allstar"
    assert out["rookie"][0][0] is False and out["rookie"][0][2] is None    # the human seat is untouched
    assert all(s[1] == "random" for s in out["rookie"][1:]) and all(s[1] == "smart" for s in out["hof"][1:])
    assert out["block"][1] == 0 and out["block"][0] == out["block"][2] > 0   # HoF drafts greedily; old saves keep the defaults
    assert out["attacks"][0] == 12 and out["attacks"][1] == 9               # Rookie attacks recklessly; the 9-inning pace otherwise


def test_regions_are_connected_and_few():
    m = build.load_map()   # load_map also raises if a region is in pieces
    assert len(m["regions"]) == 7
    assert {"north_carolina", "south_carolina"} <= set(m["territories"]) and "carolinas" not in m["territories"]
    t = m["territories"]
    assert {"california", "pennsylvania", "northern_new_england", "southern_new_england", "northern_plains"} <= set(t)
    assert not {"socal", "pa_east", "massachusetts", "minnesota"} & set(t) and len(t) % 4 == 0   # 10 each in the draft
    assert t["southern_new_england"]["members"] == ["MA", "CT", "RI"] and m["regions"]["south"]["bonus"] == 6
    assert (t["southwest"]["region"], t["texas"]["region"], t["oklahoma"]["region"], t["central_america"]["region"]) \
        == ("west", "south", t["kansas"]["region"], "latin_america")
    assert all("sea" not in x for x in t.values())   # every border is one kind, drawn solid


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_even_rotating_draft_and_modern_seasons():
    out = node("""
const st = E.newGame(data, { seed: 'draft', humanSeats: [] });
const o = st.draftOrder, n = st.seats.length;
const counts = st.seats.map((_, k) => o.filter((x) => x === k).length);
const doubles = o.filter((x, i) => i > 0 && x === o[i - 1]).length;
const first = Math.min(...Object.values(data.rosters).flat().map((p) => p.seasons[0][0]));
console.log(JSON.stringify({ counts, doubles, round2: o.slice(n, 2 * n).join(), expect2: [...o.slice(1, n), o[0]].join(), first, minYear: data.rules.min_year }));""")
    assert len(set(out["counts"])) == 1 and out["doubles"] == 0     # 10 each, never two picks in a row
    assert out["round2"] == out["expect2"]                          # the order rotates by one each round
    assert out["first"] >= out["minYear"] == 1901


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_season_stats():
    out = node("""console.log(JSON.stringify([E.seasonStats([[1, 2.0], [2, -0.5], [3, 6.1], [4, 3.0]]), E.seasonStats([[1, 1.5]]), E.seasonStats([])]));""")
    assert out[0] == {"n": 4, "median": 2.5, "total": 10.6, "best": 6.1, "worst": -0.5}
    assert out[1]["median"] == 1.5 and out[2]["n"] == 0 and out[2]["median"] is None


SETUP = """
const st = E.newGame(data, { seed: 'fix', humanSeats: [0] });
while (st.phase === 'draft') E.aiDraft(st, data);
while (st.phase === 'deploy') E.aiPlace(st, data);
E.skipPlacement(st, data);   // straight to battles
const seat = st.turn;
let from = null, to = null;
for (const t of data.territories) if (st.owner[t.id] === seat) for (const n of [...t.land, ...t.sea]) if (!from && st.owner[n] !== seat) { from = t.id; to = n; }
const make = (tid, seasons) => { const sid = E.callup(st, data, tid) || null; st.soldiers[sid].seasons = seasons; return sid; };
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_exact_ties_go_to_the_defender():
    out = node("""
const pairs = [[0.1, -0.4], [-0.3, -0.8], [-0.6, -1.1], [-1.7, -2.2], [-3.9, -4.4], [5.5, 5.0]];
console.log(JSON.stringify(pairs.map(([a, d]) => [E.beats(a, d, 0.5), E.winProb({ seasons: [[1, a]] }, { seasons: [[1, d]] }, 0.5)])));""")
    assert all(b is False and p == 0 for b, p in out)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_last_defender_retiring_is_not_a_capture_and_empty_land_can_be_walked_into():
    out = node(SETUP + """
st.stacks[from] = []; st.stacks[to] = [];
const a1 = make(from, [[1999, 1.0]]), a2 = make(from, [[1998, 0.5], [1997, 0.4]]), a3 = make(from, [[1996, 2.0]]);
const d1 = make(to, [[2000, 5.0]]);
const defender = st.owner[to];
st.bench[to] = data.rosters[to].length;   // nobody left to call up there
const r = E.battle(st, data, from, to, a1, d1);
const after = { attackerWins: r.attackerWins, captured: !!r.captured, owner: st.owner[to] === defender, empty: st.stacks[to].length === 0 };
const canWalk = E.canOccupy(st, data, from, to);
E.occupy(st, data, from, to);
const capturing = !!st.capture;
E.moveIn(st, data, [a2]);
console.log(JSON.stringify({ after, canWalk, capturing, nowMine: st.owner[to] === seat, moved: st.stacks[to].includes(a2),
  stayed: st.stacks[from].length, prunedLoser: st.soldiers[a1].seasons.length === 0 && st.soldiers[a1].name.length > 0,
  log: st.log.slice(-3).map((l) => l.text) }));""")
    assert out["after"] == {"attackerWins": False, "captured": False, "owner": True, "empty": True}
    assert out["canWalk"] and out["capturing"] and out["nowMine"] and out["moved"] and out["stayed"] == 1
    assert out["prunedLoser"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_managers_names_take_the_right_verb():
    out = node(SETUP + """
console.log(JSON.stringify([E.act(st, 0, 'attacks'), E.act(st, 1, 'attacks'), E.act(st, 0, 'is picking'), E.act(st, 0, 'calls up'),
  E.act(st, 0, 'captures'), E.act(st, 0, 'releases'), E.act(st, 0, 'wins'), st.seats[1].name]));""")
    assert out[0] == "You attack" and out[1] == f"{out[7]} attacks"
    assert out[2:7] == ["You are picking", "You call up", "You capture", "You release", "You win"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_region_stake():
    out = node("""
const st = E.newGame(data, { seed: 'stake', humanSeats: [] });
for (const t of data.territories) st.owner[t.id] = 1;               // seat 1 holds everything ...
const sw = data.territories.filter((t) => t.region === 'west').map((t) => t.id);
sw.forEach((t, k) => { st.owner[t] = k === 0 ? 1 : 0; });           // ... except the West, where seat 0 lacks one
const bonus = data.regions.west.bonus;
console.log(JSON.stringify({ completes: E.regionStake(st, data, 0, sw[0]), bonus,
  holdWhole: E.regionStake(st, data, 1, 'texas' === sw[0] ? sw[1] : 'new_york'),
  plainsWhole: E.regionStake(st, data, 0, 'kansas'), plainsBonus: data.regions.plains.bonus }));""")
    assert out["completes"] == out["bonus"]              # the one missing territory: completing is worth the bonus
    assert out["plainsWhole"] == pytest.approx(0.5 * out["plainsBonus"])  # breaking a rival's whole region counts half
