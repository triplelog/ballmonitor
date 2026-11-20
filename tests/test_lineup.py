"""Lineup (daily batting-order puzzle): the expected-runs chain, its JavaScript twin and the built puzzles."""

import itertools
import json
import math
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from ballmonitor.games.lineup import chain, generate

WEB = Path(__file__).resolve().parent.parent / "ballmonitor" / "games" / "lineup" / "web"
PUZZLES = WEB / "puzzles" / "daily"
RULES = chain.load_rules()


def r(k, bb, s, d, t, h):
    return [k, bb, s, d, t, h, round(1 - (k + bb + s + d + t + h), 10)]


UNEVEN = [r(.12, .18, .14, .04, .005, .03), r(.28, .10, .10, .04, 0, .065), r(.06, .05, .22, .05, .01, .01),
          r(.20, .08, .13, .045, .005, .035), r(.15, .07, .15, .04, .01, .02), r(.25, .12, .12, .05, 0, .06),
          r(.10, .06, .17, .05, .005, .015), r(.22, .05, .12, .035, .005, .02), r(.18, .09, .15, .05, .01, .03)]


def test_every_move_adds_up_to_one():
    for key, moves in chain.transitions(RULES["advance"]).items():
        assert abs(sum(m[0] for m in moves) - 1) < 1e-12, key
        assert all(0 <= no <= 3 and 0 <= nb < 8 and runs >= 0 for _, no, nb, runs in moves), key


def test_hand_calculated_home_run_or_strikeout():
    """Each batter homers with chance h, else strikes out: runs per inning = 3h / (1 - h)."""
    h = 0.1
    runs = chain.expected_runs(list(range(9)), [r(1 - h, 0, 0, 0, 0, h)] * 9, RULES)
    assert runs == pytest.approx(RULES["game"]["innings"] * 3 * h / (1 - h), rel=1e-6)
    assert chain.expected_runs(list(range(9)), [r(1, 0, 0, 0, 0, 0)] * 9, RULES) == 0


def test_better_hitters_score_more_and_order_matters():
    base = chain.expected_runs(list(range(9)), UNEVEN, RULES)
    better = [x[:] for x in UNEVEN]
    better[0] = r(.12, .18, .14, .04, .005, .06)          # more home runs, fewer outs
    assert chain.expected_runs(list(range(9)), better, RULES) > base
    assert chain.expected_runs(list(range(9)), UNEVEN, RULES) != chain.expected_runs(list(range(8, -1, -1)), UNEVEN, RULES)


def test_all_orders_matches_one_order_at_a_time():
    np = pytest.importorskip("numpy")
    orders, runs = chain.all_orders(UNEVEN, RULES)
    assert len(runs) == 362880 and np.all(np.isfinite(runs))
    rng = random.Random(3)
    for i in [0, len(runs) - 1, int(runs.argmax()), int(runs.argmin())] + [rng.randrange(len(runs)) for _ in range(4)]:
        assert runs[i] == pytest.approx(chain.expected_runs([int(x) for x in orders[i]], UNEVEN, RULES), abs=1e-9)
    assert list(orders[5]) == list(list(itertools.permutations(range(9)))[5])


def test_chain_agrees_with_random_seasons():
    """Play many random games with the same rules: the average lands on the chain's number."""
    order = list(range(9))
    exact = chain.expected_runs(order, UNEVEN, RULES)
    trans = chain.transitions(RULES["advance"])
    rng = random.Random(7)
    games, total = 6000, 0
    for _ in range(games):
        slot = 0
        for _ in range(RULES["game"]["innings"]):
            outs = bases = 0
            while outs < 3:
                o = rng.choices(chain.OUTCOMES, weights=UNEVEN[order[slot]])[0]
                moves = trans[(outs, bases, o)]
                _, outs, bases, runs = rng.choices(moves, weights=[m[0] for m in moves])[0]
                total += runs
                slot = (slot + 1) % 9
    assert total / games == pytest.approx(exact, abs=4 * 3.2 / games ** 0.5)   # ~3.2 runs sd per game


def test_run_distribution_hand_calculated():
    """Home run (chance h) or strikeout: a game's runs are negative binomial, C(R+26, 26) h^R (1-h)^27."""
    h = 0.1
    dist = chain.run_distribution(list(range(9)), [r(1 - h, 0, 0, 0, 0, h)] * 9, RULES)
    for runs in range(8):
        assert dist[runs] == pytest.approx(math.comb(runs + 26, 26) * h ** runs * (1 - h) ** 27, rel=1e-9)
    assert chain.run_distribution(list(range(9)), [r(1, 0, 0, 0, 0, 0)] * 9, RULES)[0] == 1


def test_run_distribution_adds_up_to_expected_runs():
    for order in (list(range(9)), [4, 2, 7, 0, 8, 1, 3, 6, 5]):
        dist = chain.run_distribution(order, UNEVEN, RULES)
        assert sum(dist) == pytest.approx(1, abs=1e-6)
        assert sum(i * x for i, x in enumerate(dist)) == pytest.approx(chain.expected_runs(order, UNEVEN, RULES), abs=1e-4)
        assert dist[-1] < 1e-6                    # the lumped "30 or more" cell is negligible


def test_clone_runs():
    assert chain.clone_runs(UNEVEN[0], RULES) == pytest.approx(chain.expected_runs([0] * 9, [UNEVEN[0]] * 9, RULES))
    assert chain.clone_runs(UNEVEN[0], RULES) > chain.clone_runs(UNEVEN[7], RULES)   # the better hitter


def node_eval(expr: str):
    """Run chain.js under Node and return JSON.stringify(expr)."""
    script = ("globalThis.window = globalThis;" + (WEB / "chain.js").read_text(encoding="utf-8") +
              f"console.log(JSON.stringify({expr}));")
    return json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_javascript_distribution_and_clones_match_python():
    rules = json.dumps({"advance": RULES["advance"], "game": RULES["game"]})
    cases = [(UNEVEN, list(range(9))), (UNEVEN, [4, 2, 7, 0, 8, 1, 3, 6, 5])]
    for p in (built() if (PUZZLES / "index.json").exists() else [])[::97]:
        rates = [c["rates"] for c in p["players"]]
        cases += [(rates, p["best"]["order"]), (rates, p["worst"]["order"])]
    js = node_eval(f"{json.dumps(cases)}.map(([rates, o]) => [LineupChain.runDistribution(o, rates, {rules}), "
                   f"LineupChain.expectedRuns(o, rates, {rules}).runs, rates.map((x) => LineupChain.cloneRuns(x, {rules}))])")
    for (rates, order), (dist, runs, clones) in zip(cases, js):
        assert dist == pytest.approx(chain.run_distribution(order, rates, RULES), abs=1e-12)
        assert runs == pytest.approx(chain.expected_runs(order, rates, RULES), abs=1e-9)
        assert clones == pytest.approx([chain.clone_runs(x, RULES) for x in rates], abs=1e-9)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_javascript_chain_matches_python():
    orders = [list(range(9)), [4, 2, 7, 0, 8, 1, 3, 6, 5]]
    script = ("globalThis.window = globalThis;" + (WEB / "chain.js").read_text(encoding="utf-8") +
              f"const rates = {json.dumps(UNEVEN)}, rules = {json.dumps({'advance': RULES['advance'], 'game': RULES['game']})};"
              f"console.log(JSON.stringify({json.dumps(orders)}.map((o) => LineupChain.expectedRuns(o, rates, rules).runs)));")
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    for o, js in zip(orders, out):
        assert js == pytest.approx(chain.expected_runs(o, UNEVEN, RULES), abs=1e-9)


def built():
    if not (PUZZLES / "index.json").exists():
        pytest.skip("puzzles not built")
    out = []
    for f in sorted(PUZZLES.glob("20*.json")):
        out += json.loads(f.read_text())
    return out


def test_index_matches_files():
    index = json.loads((PUZZLES / "index.json").read_text()) if (PUZZLES / "index.json").exists() else pytest.skip()
    puzzles = built()
    assert [p["date"] for p in index["puzzles"]] == [p["date"] for p in puzzles]
    assert [p["number"] for p in puzzles] == list(range(1, len(puzzles) + 1))


def test_every_puzzle_has_the_right_shape():
    for p in built():
        players = p["players"]
        assert [c["pos"] for c in players] == generate.POS_ORDER, p["date"]
        assert len({c["id"] for c in players}) == 9, p["date"]
        for c in players:
            assert len(c["rates"]) == 7 and abs(sum(c["rates"]) - 1) < 1e-9 and min(c["rates"]) >= 0
        assert p["rules"] == {"advance": RULES["advance"], "game": RULES["game"]}
        q = p["percentiles"]
        assert q == sorted(q) and q[0] == pytest.approx(p["worst"]["runs"]) and q[-1] == pytest.approx(p["best"]["runs"])
        assert sorted(p["best"]["order"]) == list(range(9)) and p["orders"] == 362880
        assert p["best"]["runs"] - p["worst"]["runs"] > 0.08, p["date"]   # the order has to matter
        assert generate.off_realistic([{"obp": c["obp"], "slg": c["slg"]} for c in players]) < 0.002, p["date"]


def test_stored_best_order_is_what_the_chain_says():
    for p in built()[:: 60]:
        rates = [c["rates"] for c in p["players"]]
        assert chain.expected_runs(p["best"]["order"], rates, RULES) == pytest.approx(p["best"]["runs"], abs=1e-6)
        assert chain.expected_runs(p["worst"]["order"], rates, RULES) == pytest.approx(p["worst"]["runs"], abs=1e-6)


def test_stored_page_extras():
    """OPS and nine-clone runs on every card (no real plate appearances); the near-best orders and
    the hitter-by-slot grid agree with the chain."""
    puzzles = built()
    for p in puzzles:
        top = p["top"]
        assert top[0] == ["".join(map(str, p["best"]["order"])), p["best"]["runs"]], p["date"]
        assert [t[1] for t in top] == sorted((t[1] for t in top), reverse=True) and len(top) == generate.TOP_ORDERS
        assert len({t[0] for t in top}) == len(top)
        for h, row in enumerate(p["grid"]):
            assert len(row) == 9 and all(code[slot] == str(h) for slot, (_, code) in enumerate(row))
            assert max(runs for runs, _ in row) == p["best"]["runs"]
            assert row[p["best"]["order"].index(h)][0] == p["best"]["runs"]
        for c in p["players"]:
            assert "pa" not in c and c["ops"] == pytest.approx(c["obp"] + c["slg"], abs=0.0011)
    for p in puzzles[::45]:
        rates = [c["rates"] for c in p["players"]]
        for c in p["players"]:
            assert c["clones"] == pytest.approx(chain.clone_runs(c["rates"], RULES), abs=6e-4)
        for code, runs in p["top"][1::6]:
            assert chain.expected_runs([int(x) for x in code], rates, RULES) == pytest.approx(runs, abs=1e-6)
        runs, code = p["grid"][3][5]
        assert chain.expected_runs([int(x) for x in code], rates, RULES) == pytest.approx(runs, abs=1e-6)


def test_puzzle_files_stay_small():
    for f in PUZZLES.glob("20*.json"):
        assert f.stat().st_size < 250_000, f.name     # one month, fetched whole by the page
