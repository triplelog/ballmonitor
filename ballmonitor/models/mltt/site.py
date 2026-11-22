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
        "standings", "Standings, with luck taken out",
        [V.col("team", "Team", link="team"), V.col("div", "Division", hidden=True), V.col("wl", "W-L"),
         V.col("pct", "Points won", "pct", decimals=1), V.col("xpct", "Expected", "pct", decimals=1),
         V.col("luck", "Luck (points)", "signed", decimals=1), V.col("rally", "Rallies won", "pct", decimals=1, hidden=True),
         V.col("close", "11-10 games", hidden=True),
         V.col("sos", "Schedule so far", "int", low_first=True), V.col("sos_left", "Schedule left", "int", low_first=True)],
        standings, sort="pct",
        subtitle="Teams are ranked by the share of team points they have won. Expected: the share their rallies "
                 "were worth, game by game. Luck: points won minus expected.",
        note="Schedule: 1 = the strongest opponents. 11-10 games are close to coin flips.",
        quick_filters=("div", divisions) if divisions else None)

    odds = [{"team": t, "div": teams.get(t, {}).get("division", ""), "proj": s["pct"], "ff": s["playoff"],
             "final": s["final"], "champ": s["champ"]} for t, s in sim.items()]
    odds_table = V.table(
        "odds", "Final Four chances" if not final else "Final Four chances (regular season over)",
        [V.col("team", "Team", link="team"), V.col("div", "Division"),
         V.col("proj", "Projected points won", "pct", decimals=1), V.col("ff", "Final Four", "pct", bar=True),
         V.col("final", "Reach the final", "pct"), V.col("champ", "Win the MLTT Cup", "pct", bar=True)],
        odds, sort="champ",
        subtitle=f"From {int(p.simulations):,} simulations of the {left} regular-season matches left. The top two "
                 "in each division reach the Final Four.",
        note="Each simulated season also draws how much better or worse each team really is than its results. "
             "MLTT matches are hard to call: in past seasons the favorite won about 60% of the time.")

    prow = []
    for d in players.values():
        if not d["games"]:
            continue
        prow.append({"name": d["name"], "team": d["team"], "games": d["games"], "win": d["won"] / d["games"],
                     "rally": d["rallies_won"] / d["rallies"] if d["rallies"] else None, "vs": d["game_vs_avg"],
                     "paa": d["paa"], "wpa": d["wpa"]})
    players_table = V.table(
        "players", "Who adds the most",
        [V.col("name", "Player"), V.col("team", "Team", link="team"), V.col("games", "Games", "int"),
         V.col("win", "Games won", "pct"), V.col("rally", "Rallies won", "pct", decimals=1, hidden=True),
         V.col("vs", "Beats an average player", "pct"),
         V.col("paa", "Points above average", "signed", decimals=1, bar=True),
         V.col("wpa", "Match wins added", "signed", decimals=2)],
        prow, sort="wpa", search=True, page_size=25,
        subtitle="Points above average: team points a player won beyond what an average MLTT player would have won "
                 "against the same opponents. Match wins added: how much each game they won or lost moved their "
                 "team's chance of winning the match, summed (doubles split in two; the Golden Game shared by the five).",
        note="Beats an average player: the chance to win one game against an average MLTT player, from every rally "
             "since 2024 and the player's MLTT rating at the time.")

    # the possible head starts: Stage One leads have the parity of its game count (15 games: 1, 3, 5)
    n = r.stage_one_games
    starts = sorted({min(lead, r.max_head_start) for lead in range(n % 2, n + 1, 2)})
    head = V.bar("head_start", "What a Golden Game head start is worth",
                 [{"label": f"{h} point{'s' if h != 1 else ''} ahead" if h else "Level",
                   "value": E.race_win(h, 0, 0.5, r.golden_to)} for h in starts],
                 subtitle=f"Chance the Stage One leader wins the race to {r.golden_to}, if the teams are even.",
                 note=f"The leader starts ahead by its Stage One lead, up to {r.max_head_start} points. With "
                      f"{n} Stage One games there is always a leader.")

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
                      V.col("result", "Result"), V.col("chance", "Chance to win", "pct")], rows,
                     note="Chance to win: for matches still to play, from the lineup the team has used so far.")
        roster = [x for x in prow if x["team"] == t]
        rt = V.table(f"players_{V.slug(t)}", "Players",
                     [V.col("name", "Player"), V.col("games", "Games", "int"), V.col("win", "Games won", "pct"),
                      V.col("vs", "Beats an average player", "pct"),
                      V.col("paa", "Points above average", "signed", decimals=1),
                      V.col("wpa", "Match wins added", "signed", decimals=2)], roster or
                     [{"name": "No games yet", "games": 0, "win": None, "vs": None, "paa": None, "wpa": None}],
                     sort="paa")
        s = sim.get(t, {})
        intro = (f"{d['w']}-{d['l']}, {d['pct']:.1%} of points won ({d['division']}). "
                 f"Final Four chance {s.get('playoff', 0):.0%}." if d["pct"] is not None else f"{d['division']}.")
        team_opts.append(V.option(t, [mt, rt], intro=intro))
    team_picker = V.picker("team", "Team by team", "Team", team_opts)

    fav = max(sim.items(), key=lambda kv: kv[1]["champ"])
    lucky = max(teams.values(), key=lambda d: d["luck"])
    unlucky = min(teams.values(), key=lambda d: d["luck"])
    headline = (f"{fav[0]} are the title favorites ({fav[1]['champ']:.0%}); {lucky['team']} have won "
                f"{lucky['luck']:.0f} points more than their rallies were worth, {unlucky['team']} "
                f"{-unlucky['luck']:.0f} fewer")
    last = data.meta.get("last_result", "")
    return V.page(
        title="Major League Table Tennis", sport="More sports",
        summary="Standings with luck taken out, Final Four chances and every player's value in MLTT.",
        how="Every player gets one number: their chance of winning a rally against an average MLTT player, from every "
            "rally since 2024 and their MLTT rating at the time. MLTT's rules (games to 11, the Golden Game and its head start) "
            "turn that into the chance of winning each game and match; the rest of the season is simulated "
            f"{int(p.simulations):,} times.",
        updated=f"MLTT results through {_day(last)}" + (" (final)" if final else "") if last else "",
        headline=headline, fill={"season": season, "played": played},
        views=[V.clean(standings_table), V.clean(odds_table), V.clean(players_table), head, V.clean(team_picker)])


def _forecast(data, R, p, r, a: str, b: str, season: int) -> tuple[float, float]:
    sa = E.team_slots(data, R, a, season)
    sb = E.team_slots(data, R, b, season)
    gp, q = E.slot_game_probs(sa, sb, p, r)
    return E.summarize(E.match_distribution(gp, q, r), r)
