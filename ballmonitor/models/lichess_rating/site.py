"""Public page: a rating log kept in the visitor's browser, with the model's prediction for a
date they pick, plus two small tables: what the model says for example players, and what
really happened to the Lichess test players in data/backtest.csv.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views lichess_rating`). The tool
(web/static/apps/lichess_rating.js) is a copy of model.py + dist.py, fed the model's fitted
parameters from here; tests/test_lichess_rating_app.py checks it against model.predict. The log
stays in the visitor's browser (localStorage `bm.log.lichess_rating.v1`); the only network call
the tool makes is the optional "Fill from my Lichess account" button, straight to lichess.org.
No player names are shown.
"""

from __future__ import annotations

import csv
import statistics

from ballmonitor.core import views as V
from ballmonitor.models.lichess_rating.dist import FEATURES, LEVEL_KEYS, LEVELS
from ballmonitor.models.lichess_rating.model import SPEEDS

STORAGE_KEY = "bm.log.lichess_rating.v1"
# the formula the tool copies (config.toml [formulas.p_active]); a different one fails the build
P_ACTIVE_EXPR = ("logistic(active_intercept + active_activity * activity + active_idle * idle + "
                 "active_experience * experience + active_log_horizon * log_horizon)")
CHANGE_TERMS = ("intercept",) + FEATURES + ("log_horizon",)
ACTIVE_TERMS = ("intercept", "activity", "idle", "experience", "log_horizon")

# Example players for the tables (made up, labelled as such on the page): rated EXAMPLE_RATING,
# no change over the last 3 months, even results against players of their own rating.
EXAMPLE_RATING = 1500
EXAMPLE_HORIZON = 91
EXAMPLE_ACTIVE = (30, 90, 1)             # games in the last 28 days, 91 days, days since the last game
EXPERIENCE_ROWS = (20, 100, 500, 2000)   # rated games so far
ACTIVITY_ROWS = (("Plays most days", 30, 90, 1), ("Plays about once a week", 4, 13, 2),
                 ("Plays now and then", 1, 4, 10), ("Stopped a month ago", 0, 10, 30))
ACTIVITY_GAMES = 500
BACKTEST_SPEED = "blitz"
LICHESS_GAME_CAP = 1000                  # games read per "Fill from Lichess" (it streams ~20 a second)


def calculator_data(model) -> dict:
    """Everything the tool needs: the fitted coefficients and limits (read from the config, so a
    refit reaches the page) and the storage key."""
    p = model.params
    expr = " ".join(str(p.expr("p_active")).split())
    if expr != P_ACTIVE_EXPR:
        raise ValueError("the Lichess tool copies formulas.p_active; it is now " + expr)
    return {
        "storage_key": STORAGE_KEY,
        "model": "lichess_rating",
        "levels": list(LEVELS),
        "active": [float(p[f"active_{t}"]) for t in ACTIVE_TERMS],
        "change_terms": list(CHANGE_TERMS),
        "change": [[float(p[f"change_{k}_{t}"]) for t in CHANGE_TERMS] for k in LEVEL_KEYS],
        "caps": {"games": float(p.cap_games), "below_peak": float(p.cap_below_peak),
                 "trend": float(p.cap_trend), "form": float(p.cap_form)},
        "band_scale": float(p.band_scale),
        "milestone_step": float(p.milestone_step),
        "speeds": list(SPEEDS),
        "default_speed": "blitz",
        "default_days": EXAMPLE_HORIZON,
        "lichess_cap": LICHESS_GAME_CAP,
    }


def _example(model, games_total: float, games_28: float, games_91: float, days_since: float) -> dict:
    r = EXAMPLE_RATING
    pred = model.predict({"rating": r, "speed": "blitz", "horizon_days": EXAMPLE_HORIZON,
                          "games_total": games_total, "games_last_28_days": games_28,
                          "games_last_91_days": games_91, "days_since_last_game": days_since})
    q = pred.extras["quantiles"]
    return {"play": pred.extras["p_active"], "mid": round(q[0.5]), "low": round(q[0.1]), "high": round(q[0.9]),
            "up": next(o.probability for o in pred.outcomes if o.label == "Higher than today")}


def _backtest_rows(model) -> list[dict]:
    """What happened to the real test players (data/backtest.csv, blitz), by how far ahead."""
    with open(model.dir / "data" / "backtest.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["speed"] == BACKTEST_SPEED]
    out = []
    for h in sorted({int(r["horizon_days"]) for r in rows}):
        rs = [r for r in rows if int(r["horizon_days"]) == h]
        changes = sorted(float(r["actual_rating"]) - float(r["rating"]) for r in rs)
        held = 0
        for r in rs:
            inputs, actual = model.backtest_case(r)
            lo, hi = model.predict(inputs).outcomes[0].interval
            held += lo - 0.5 <= actual <= hi + 0.5   # the page shows whole points
        n = len(changes)
        out.append({"ahead": {30: "1 month", 91: "3 months", 182: "6 months", 365: "1 year"}.get(h, f"{h} days"),
                    "n": n, "played": sum(r["played_after"] == "1" for r in rs) / n,
                    "within": statistics.median(abs(c) for c in changes),
                    "low": changes[int(0.1 * (n - 1))], "high": changes[int(round(0.9 * (n - 1)))],
                    "held": held / n})
    return out


def _signed(x: float) -> str:
    return f"+{x:.0f}" if x > 0 else f"{x:.0f}".replace("-", "−")


def page(model) -> dict:
    tool = V.app(
        "your_log", "Your rating log and forecast", "lichess_rating", calculator_data(model),
        subtitle="Write down your Lichess rating now and then (or fill it in from your account), add a few "
                 "numbers from your stats page, and pick a date: you get the most likely rating then and "
                 "the chances of reaching your next milestones.",
        note="The model learned from Lichess "
             "blitz players in 2014-2016 and was tested on other players in 2016-2017; today's players may "
             "differ, and bullet, rapid and classical use the blitz fit.")

    exp_rows = []
    for g in EXPERIENCE_ROWS:
        e = _example(model, g, *EXAMPLE_ACTIVE)
        exp_rows.append({"games": f"{g:,}", "play": e["play"], "mid": e["mid"],
                         "range": f"{_signed(e['low'])} to {_signed(e['high'])}", "up": e["up"]})
    by_exp = V.table(
        "by_experience", "Typical change in 3 months, by experience",
        [V.col("games", "Rated games so far"), V.col("play", "Plays again", "pct"),
         V.col("mid", "Most likely change", "signed", decimals=0), V.col("range", "8 in 10 between"),
         V.col("up", "Chance higher", "pct", bar=True)],
        exp_rows,
        subtitle=f"Example players (made up, not real people): rated {EXAMPLE_RATING}, playing most days, "
                 "steady for the last 3 months, with even results.",
        note="New players' ratings swing the most; experienced players' ratings barely move.")

    act_rows = []
    for label, g28, g91, idle in ACTIVITY_ROWS:
        e = _example(model, ACTIVITY_GAMES, g28, g91, idle)
        act_rows.append({"who": label, "play": e["play"], "mid": e["mid"],
                         "range": f"{_signed(e['low'])} to {_signed(e['high'])}", "up": e["up"]})
    by_act = V.table(
        "by_activity", "Typical change in 3 months, by how often you play",
        [V.col("who", "Player"), V.col("play", "Plays again", "pct"),
         V.col("mid", "Most likely change", "signed", decimals=0), V.col("range", "8 in 10 between"),
         V.col("up", "Chance higher", "pct", bar=True)],
        act_rows,
        subtitle=f"Example players (made up): rated {EXAMPLE_RATING} with {ACTIVITY_GAMES} rated games so far.",
        note="A rating only moves when you play rated games, so players who may have stopped mostly stay put.")

    bt = _backtest_rows(model)
    real = V.table(
        "what_happened", "What really happened to Lichess players",
        [V.col("ahead", "Looking ahead"), V.col("n", "Players", "int"), V.col("played", "Played again", "pct"),
         V.col("within", "Half moved at most", "int"), V.col("range", "8 in 10 moved between"),
         V.col("held", "Our 8-in-10 range held", "pct")],
        [{**r, "within": round(r["within"]), "range": f"{_signed(r['low'])} to {_signed(r['high'])}"} for r in bt],
        subtitle="Real blitz players from the Lichess open database (2016-2017), none of whom the model "
                 "learned from: how far their rating moved, in points.",
        note="Many players stop playing for a while, which is why half barely moved. The range should hold "
             "for about 8 in 10 players.")

    three = next(r for r in bt if r["ahead"] == "3 months")
    ex = _example(model, 500, *EXAMPLE_ACTIVE)
    headline = (f"A {EXAMPLE_RATING} blitz player who plays most days is most likely {_signed(ex['mid'])} points "
                f"from today 3 months on, 8 in 10 between {_signed(ex['low'])} and {_signed(ex['high'])}. "
                f"Of real players, only {three['played']:.0%} played again within 3 months.")

    return V.page(
        title="Lichess rating forecast",
        headline=headline,
        summary="Keep a log of your Lichess rating and see where it is likely to be on any date you pick, "
                "and your chances of reaching the next 100.",
        sport="More sports",
        updated="Learned from Lichess games 2014-2016, tested on 2016-2017",
        how=("A Lichess rating only changes when you play rated games, so the forecast has two parts: the "
             "chance you play again in that speed before the date, and how far your rating tends to move if "
             "you do. Both were learned from a sample of real players in the Lichess open database "
             "(blitz games, 2014-2016) and checked on other players' later games (2016-2017). Today's players, and "
             "the other speeds, may behave a little differently."),
        views=[tool, by_exp, by_act, real],
    )
