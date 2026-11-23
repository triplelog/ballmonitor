"""Public page (/mltt/): the current MLTT season for fans. Standings with expected points, luck and
schedule strength; Final Four and title chances; every player's value; what a Golden Game head
start is worth; and a page per team (/mltt/team/<team>/). Built at site-build time from the
committed data/*.csv; the page only displays these numbers.
"""

from __future__ import annotations

import datetime as dt

from ballmonitor.core import views as V

from . import engine as E


def _day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _ranks(values: dict[str, float | None]) -> dict[str, int | None]:
    """1 = the hardest schedule (strongest opponents)."""
    order = sorted((t for t, v in values.items() if v is not None), key=lambda t: -values[t])
    return {t: (order.index(t) + 1 if t in order else None) for t in values}


def page(model) -> dict:
    p = model.params
    data = model.data()
    season = data.current_season()
    r = E.rules(p)
    R = model.ratings(season)
    teams = E.team_season(data, R, season, p)
    sim = E.simulate_season(data, R, season, p)["teams"]
    players = E.player_season(data, R, season, p)
    played = sum(1 for m in data.matches if m.season == season and m.final)
    left = sum(1 for m in data.matches if m.season == season and not m.final and m.stage == "regular")
    final = left == 0

    sos = _ranks({t: d["sos"] for t, d in teams.items()})
    sos_left = _ranks({t: d["sos_left"] for t, d in teams.items()})
    standings = []
    for t, d in teams.items():
        standings.append({"team": t, "div": d["division"], "wl": f"{d['w']}-{d['l']}", "pct": d["pct"],
                          "xpct": d["xpct"], "luck": d["luck"], "rally": d["rally_pct"],
                          "close": f"{d['close_won']}-{d['close'] - d['close_won']}",
                          "sos": sos[t], "sos_left": sos_left[t]})
    divisions = sorted({d["div"] for d in standings if d["div"]})
    standings_table = V.table(
        "standings", "Standings, adjusted for luck",
        [V.col("team", "Team", link="team"), V.col("div", "Division", hidden=True), V.col("wl", "W-L"),
         V.col("pct", "Points won", "pct", decimals=1), V.col("xpct", "Expected", "pct", decimals=1),
         V.col("luck", "Luck (pts)", "signed", decimals=1), V.col("rally", "Rallies won", "pct", decimals=1, hidden=True),
         V.col("close", "11-10 games", hidden=True),
         V.col("sos", "Schedule so far", "int", low_first=True), V.col("sos_left", "Schedule left", "int", low_first=True)],
        standings, sort="pct",
        subtitle="Ranked by share of team points won. Expected shows what each team's rallies were worth game by game, "
                 "and Luck is the gap between actual and expected points.",
        note="Schedule rank 1 is the toughest set of opponents. 11-10 games are basically coin flips.",
        quick_filters=("div", divisions) if divisions else None)

    odds = [{"team": t, "div": teams.get(t, {}).get("division", ""), "proj": s["pct"], "ff": s["playoff"],
             "final": s["final"], "champ": s["champ"]} for t, s in sim.items()]
    odds_table = V.table(
        "odds", "Final Four odds" if not final else "Final Four odds (regular season complete)",
        [V.col("team", "Team", link="team"), V.col("div", "Division"),
         V.col("proj", "Projected points won", "pct", decimals=1), V.col("ff", "Final Four", "pct", bar=True),
         V.col("final", "Reach the final", "pct"), V.col("champ", "Win the MLTT Cup", "pct", bar=True)],
        odds, sort="champ",
        subtitle=f"Based on {int(p.simulations):,} simulations of the {left} remaining regular-season matches. "
                 "The top two teams in each division make the Final Four.",
        note="Each simulation accounts for uncertainty in true team strength. MLTT matches are unpredictable—historically, "
             "the favorite wins about 60% of the time.")

    prow = []
    for d in players.values():
        if not d["games"]:
            continue
        prow.append({"name": d["name"], "team": d["team"], "games": d["games"], "win": d["won"] / d["games"],
                     "rally": d["rallies_won"] / d["rallies"] if d["rallies"] else None, "vs": d["game_vs_avg"],
                     "paa": d["paa"], "wpa": d["wpa"]})
    players_table = V.table(
        "players", "Player value",
        [V.col("name", "Player"), V.col("team", "Team", link="team"), V.col("games", "Games", "int"),
         V.col("win", "Games won", "pct"), V.col("rally", "Rallies won", "pct", decimals=1, hidden=True),
         V.col("vs", "Win vs. average player", "pct"),
         V.col("paa", "Points above average", "signed", decimals=1, bar=True),
         V.col("wpa", "Match wins added", "signed", decimals=2)],
        prow, sort="wpa", search=True, page_size=25,
        subtitle="Points above average measures how many team points a player won compared to an average MLTT player "
                 "facing the same opponents. Match wins added totals how much each game shifted their team's odds of "
                 "winning the match (split in doubles, and shared across all five players in the Golden Game).",
        note="Win vs. average player is the estimated chance to win a single game against an average MLTT player, based on "
             "every rally since 2024 and the SPINDEX rating they had at the time.")

    # the possible head starts: Stage One leads have the parity of its game count (15 games: 1, 3, 5)
    n = r.stage_one_games
    starts = sorted({min(lead, r.max_head_start) for lead in range(n % 2, n + 1, 2)})
    head = V.bar("head_start", "Value of a Golden Game head start",
                 [{"label": f"{h} point{'s' if h != 1 else ''} ahead" if h else "Tied",
                   "value": E.race_win(h, 0, 0.5, r.golden_to)} for h in starts],
                 subtitle=f"Win odds for the Stage One leader in the race to {r.golden_to}, assuming evenly matched teams.",
                 note=f"The Stage One leader starts up by their margin, capped at {r.max_head_start} points. With "
                      f"{n} Stage One games, one team always enters ahead.")

    team_opts = []
    for t in sorted(teams):
        d = teams[t]
        rows = []
        for m in data.matches:
            if m.season != season or t not in (m.team_a, m.team_b):
                continue
            home = m.team_a == t
            opp = m.team_b if home else m.team_a
            if m.final:
                pf, pa = (m.points_a, m.points_b) if home else (m.points_b, m.points_a)
                rows.append({"date": m.date, "opp": opp, "score": f"{pf}-{pa}", "result": "W" if pf > pa else "L",
                             "chance": None})
            else:
                win, _ = _forecast(data, R, p, r, t, opp, season)
                rows.append({"date": m.date, "opp": opp, "score": "", "result": "", "chance": win})
        mt = V.table(f"matches_{V.slug(t)}", "Matches",
                     [V.col("date", "Date"), V.col("opp", "Opponent", link="team"), V.col("score", "Points"),
                      V.col("result", "Result"), V.col("chance", "Win odds", "pct")], rows,
                     note="Win odds for upcoming matches are based on the lineups each team has used so far.")
        roster = [x for x in prow if x["team"] == t]
        rt = V.table(f"players_{V.slug(t)}", "Players",
                     [V.col("name", "Player"), V.col("games", "Games", "int"), V.col("win", "Games won", "pct"),
                      V.col("vs", "Win vs. average player", "pct"),
                      V.col("paa", "Points above average", "signed", decimals=1),
                      V.col("wpa", "Match wins added", "signed", decimals=2)], roster or
                     [{"name": "No games yet", "games": 0, "win": None, "vs": None, "paa": None, "wpa": None}],
                     sort="paa")
        s = sim.get(t, {})
        intro = (f"{d['w']}-{d['l']}, {d['pct']:.1%} of points won ({d['division']}). "
                 f"Final Four odds: {s.get('playoff', 0):.0%}." if d["pct"] is not None else f"{d['division']}.")
        team_opts.append(V.option(t, [mt, rt], intro=intro))
    team_picker = V.picker("team", "Team by team", "Team", team_opts)

    fav = max(sim.items(), key=lambda kv: kv[1]["champ"])
    lucky = max(teams.values(), key=lambda d: d["luck"])
    unlucky = min(teams.values(), key=lambda d: d["luck"])
    headline = (f"{fav[0]} are the current title favorites ({fav[1]['champ']:.0%}). {lucky['team']} have won "
                f"{lucky['luck']:.0f} more points than their rallies were worth, while {unlucky['team']} have won "
                f"{-unlucky['luck']:.0f} fewer.")
    last = data.meta.get("last_result", "")
    return V.page(
        title="Major League Table Tennis", sport="More sports",
        summary="MLTT standings adjusted for luck, schedule strength, Final Four odds, and player value ratings.",
        how="Each player gets a single rating: their chance of winning a rally against an average MLTT opponent, "
            "estimated from every rally since 2024 and anchored by their SPINDEX rating at the time. Using MLTT's "
            "exact rules—games to 11, the Golden Game, and its head start—we turn those ratings into game and match "
            f"odds, then simulate the rest of the season {int(p.simulations):,} times.",
        updated=f"Results through {_day(last)}" + (" (final)" if final else "") if last else "",
        headline=headline, fill={"season": season, "played": played},
        views=[V.clean(standings_table), V.clean(odds_table), V.clean(players_table), head, V.clean(team_picker)])


def _forecast(data, R, p, r, a: str, b: str, season: int) -> tuple[float, float]:
    sa = E.team_slots(data, R, a, season)
    sb = E.team_slots(data, R, b, season)
    gp, q = E.slot_game_probs(sa, sb, p, r)
    return E.summarize(E.match_distribution(gp, q, r), r)
