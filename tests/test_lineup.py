"""Lineup (daily batting-order puzzle): the expected-runs chain, its JavaScript twin and the built puzzles."""

import itertools
import json
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
