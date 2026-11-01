"""Public page: how ESPN's win probability moved through each bundled finished game.

Not a forecast: the numbers are ESPN's published in-game win probability, read through the
model's own play parser (predict()). Built at site-build time; the page only displays them.
"""

from __future__ import annotations

import datetime as dt

from ballmonitor.core import registry
from ballmonitor.core import views as V

QUARTER_MIN = 15  # minutes in a college football quarter
OT_WIDTH = 6      # chart minutes given to overtime (it has no game clock)
MARKERS = 5       # labelled plays on each chart
SWINGS = 10       # rows in each "biggest plays" table


def _day(iso: str) -> str:
    d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
    return f"{d:%b} {d.day}, {d.year}"


def _clock(c: str) -> str:
    m, s = c.split(":")
    return f"{int(m)}:{s}"


def _when(pl: dict) -> str:
    q = pl["quarter"]
    if q <= 4:
        return f"Q{q} {_clock(pl['clock'])}"
    return "OT" if q == 5 else f"{q - 4}OT"


def _minutes(plays: list[dict]) -> list[float]:
    """Elapsed game minutes per play; overtime plays are spread evenly after minute 60."""
    ot = [k for k, pl in enumerate(plays) if pl["quarter"] > 4]
    xs = []
    for k, pl in enumerate(plays):
        if pl["quarter"] > 4:
            xs.append(4 * QUARTER_MIN + OT_WIDTH * (ot.index(k) + 1) / (len(ot) + 1))
            continue
        m, s = pl["clock"].split(":")
        left = int(m) + int(s) / 60
        xs.append((pl["quarter"] - 1) * QUARTER_MIN + (QUARTER_MIN - min(left, QUARTER_MIN)))
    for k in range(1, len(xs)):  # keep the line moving forward if ESPN's clock jitters
        xs[k] = max(xs[k], xs[k - 1])
    return xs


def _label(pl: dict, teams: tuple[str, ...]) -> str:
    """'TOUCHDOWN KANSAS' -> 'Touchdown Kansas'; plays with no headline use ESPN's play type."""
    if pl.get("headline") and pl["headline"] != "BIG PLAY":
        text = pl["headline"].capitalize()
        for t in teams:
            text = text.replace(t.lower(), t)
        return text
    return (pl["type"] or "Play").capitalize()


def _game(model, example: str) -> tuple[str, list[dict], dict]:
    pr = model.predict(registry.load_example(model.dir.name, example))
    e = pr.extras
    g, plays = e["game"], [pl for pl in e["plays"] if pl.get("kind", "play") == "play"]
    home, away, final = g["home"], g["away"], g["final"]
    hs, as_ = home["short"], away["short"]
    winner = hs if final["home"] > final["away"] else as_
    ot = " in overtime" if any(pl["quarter"] > 4 for pl in plays) else ""
    score = f"{max(final.values())}-{min(final.values())}"
    label = f"{as_} at {hs}, {_day(g['date'])}"

    xs = _minutes(plays)
    pts = [(0.0, g["pregame_wp_home"])] + [(x, pl["wp_home_after"]) for x, pl in zip(xs, plays)]
    biggest = sorted(range(len(plays)), key=lambda k: (-plays[k]["abs_swing"], k))
    markers = [{"x": xs[k], "y": plays[k]["wp_home_after"], "label": _label(plays[k], (hs, as_))}
               for k in sorted(biggest[:MARKERS])]
    chart = V.line(
        f"wp_{g['id']}", f"{hs}'s chance to win, play by play",
        [V.series(hs, pts)],
        x_label="", y_label=f"{hs} win chance",
        x_fmt="number", y_fmt="pct", y_min=0, y_max=1, markers=markers,
        x_ticks=[(0, "Kickoff"), (15, "Q2"), (30, "Half"), (45, "Q4"), (60, "OT" if ot else "End")],
        subtitle=f"{winner} won {score}{ot} at {g['venue'] or 'home'}. Before kickoff ESPN gave "
                 f"{hs} a {g['pregame_wp_home']:.0%} chance. Dots mark the {MARKERS} plays that moved it most.")

    def abbr(side: dict) -> str:
        return side["abbr"] or side["short"]

    rows = [{
        "when": _when(plays[k]),
        "play": plays[k]["short_text"],
        "helped": hs if plays[k]["swing"] >= 0 else as_,
        "swing": plays[k]["abs_swing"],
        "after": plays[k]["wp_home_after"],
        "score": f"{abbr(away)} {plays[k]['away_score']}, {abbr(home)} {plays[k]['home_score']}",
    } for k in biggest[:SWINGS]]
    swings = V.table(
        f"swings_{g['id']}", "The plays that swung the game",
        [V.col("when", "When"), V.col("play", "Play"), V.col("helped", "Helped"),
         V.col("swing", "Swing", "pct", bar=True), V.col("after", f"{hs} chance after", "pct"),
         V.col("score", "Score after")],
        rows, subtitle="Swing: how much one play moved the win chance, toward the team it helped.")
    return label, [chart, swings], {**g, "biggest": plays[biggest[0]]["abs_swing"]}


def page(model) -> dict:
    examples = registry.example_names(model.dir.name)
    games = [(ex, *_game(model, ex)) for ex in examples]
    games.sort(key=lambda t: -t[3]["biggest"])  # most dramatic finish first
    days = sorted({_day(t[3]["date"]) for t in games})
    by_game = V.picker(
        "by_game", "Replay a game", "Game", [V.option(t[1], t[2]) for t in games],
        subtitle="Pick a game to see how each play changed the home team's chance to win.")
    return V.page(
        title="College football game replays",
        summary="How each play changed the chance to win in a few finished games, from nail-biters to a blowout.",
        sport="College football",
        order=40,
        updated=f"Finished games of {', '.join(days)}",
        how=("This is a look back, not a prediction. The line is ESPN's own win probability after every "
             "play of a finished game; we read it from ESPN's play-by-play and pick out the plays that "
             "moved it the most."),
        views=[by_game],
    )
