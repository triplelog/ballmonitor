"""
Command-Line Interface for the College Football Bowl Simulator.
Supports:
- Rest-of-season simulation & 12-team CFP projections
- Power rankings switching (--ratings fpi | results | custom.csv)
- What-if scenario analysis (--win-out | --lose-out | --scenario)
- Team bowl probabilities, bowl win odds, and opponent breakdowns (overall & per bowl)
- Historical backtesting against past seasons
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    CURRENT_DIR = Path(__file__).resolve().parent
    if str(CURRENT_DIR) not in sys.path:
        sys.path.insert(0, str(CURRENT_DIR))
    from backtest import Backtester
    from config import SimConfig
    from engine import BowlEngine, SimulationResults
    from scenarios import Scenario
else:
    from .backtest import Backtester
    from .config import SimConfig
    from .engine import BowlEngine, SimulationResults
    from .scenarios import Scenario

def format_percentage(val: float) -> str:
    if val >= 0.999:
        return ">99%"
    if val <= 0.001 and val > 0:
        return "<0.1%"
    if val == 0.0:
        return "0.0%"
    return f"{val * 100:.1f}%"

def print_team_card(summary, format_type: str = "table") -> None:
    s = summary
    if format_type == "md":
        print(f"### {s.team_name} ({s.conf}) — Postseason Outlook")
        print(f"- **Power Rating:** {s.rating:+.1f}")
        print(f"- **Projected Record:** {s.record_mean_wins:.1f} - {s.record_mean_losses:.1f}")
        print(f"- **Bowl Eligible Probability:** {format_percentage(s.p_eligible)}")
        print(f"- **Conference Title Probability:** {format_percentage(s.p_conf_champ)}")
        print(f"- **12-Team CFP Probability:** {format_percentage(s.p_cfp)} (First-Round Bye: {format_percentage(s.p_cfp_bye)})")
        if s.national_champ_prob > 0.005:
            print(f"- **National Championship Probability:** {format_percentage(s.national_champ_prob)}")
        print(f"- **Overall Probability of Winning a Bowl Game:** {format_percentage(s.p_win_any_bowl)}")

        print("\n**Top Projected Opponents (Overall Across All Postseason Games):**")
        print("| Opponent | Probability Facing | Win Rate vs Opp |")
        print("| :--- | :--- | :--- |")
        for opp, pr, wr in s.overall_opponents[:6]:
            print(f"| {opp} | {format_percentage(pr)} | {format_percentage(wr)} |")

        print("\n**Projected Postseason Destinations & Game Win Odds:**")
        for bid, bname, prob in s.top_bowls:
            if prob < 0.005:
                continue
            detail = s.bowls_detail.get(bid)
            win_cond = detail.p_win_conditional if detail else 0.0
            win_uncond = detail.p_win_unconditional if detail else 0.0
            print(f"\n#### {bname} — Selection Chance: {format_percentage(prob)}")
            print(f"- **P(Win Game | In This Bowl):** {format_percentage(win_cond)}")
            print(f"- **P(Reach & Win This Bowl):** {format_percentage(win_uncond)}")
            if detail and detail.opponents:
                print(f"- **Projected Opponents in {bname}:**")
                for opp, opp_pr, opp_wr in detail.opponents[:4]:
                    print(f"  - {opp}: {format_percentage(opp_pr)} chance (Win % vs {opp}: {format_percentage(opp_wr)})")
    else:
        print("=" * 76)
        print(f" {s.team_name.upper()} ({s.conf}) | Power Rating: {s.rating:+.1f}")
        print("=" * 76)
        print(f" Projected Record:                 {s.record_mean_wins:.1f} - {s.record_mean_losses:.1f}")
        print(f" Bowl Eligible Probability:        {format_percentage(s.p_eligible)}")
        print(f" Conf Champion Probability:        {format_percentage(s.p_conf_champ)}")
        print(f" 12-Team CFP Probability:          {format_percentage(s.p_cfp)} (Quarterfinal Bye: {format_percentage(s.p_cfp_bye)})")
        if s.national_champ_prob > 0.005:
            print(f" National Championship Win Prob:   {format_percentage(s.national_champ_prob)}")
        print(f" OVERALL PROBABILITY OF WINNING A BOWL / CFP GAME: {format_percentage(s.p_win_any_bowl)}")
        if s.top_seeds:
            seeds_str = ", ".join(f"#{sd} ({format_percentage(pr)})" for sd, pr in list(s.top_seeds.items())[:4])
            print(f" Most Likely Playoff Seeds:        {seeds_str}")
        if s.conf_rank_probs:
            rank_parts = []
            for r in range(1, 5):
                if r in s.conf_rank_probs:
                    rank_parts.append(f"#{r}: {format_percentage(s.conf_rank_probs[r])}")
            p5_plus = sum(p for r, p in s.conf_rank_probs.items() if r >= 5)
            if p5_plus > 0.005:
                rank_parts.append(f"#5+: {format_percentage(p5_plus)}")
            exp_str = f" (Exp Rank: {s.expected_non_playoff_rank:.1f})" if s.expected_non_playoff_rank else ""
            print(f" Non-CFP Conf Pecking Order Odds:  {' | '.join(rank_parts)}{exp_str}")
        print("-" * 76)
        print(" MOST LIKELY POSTSEASON OPPONENTS (OVERALL):")
        for opp, pr, wr in s.overall_opponents[:6]:
            print(f"   vs {opp:<24} {format_percentage(pr):>7} chance  (Win Rate vs {opp}: {format_percentage(wr)})")
        print("-" * 76)
        print(" PROJECTED BOWL DESTINATIONS & GAME WIN PROBABILITIES:")
        for bid, bname, prob in s.top_bowls:
            if prob < 0.005:
                continue
            detail = s.bowls_detail.get(bid)
            win_cond = detail.p_win_conditional if detail else 0.0
            win_uncond = detail.p_win_unconditional if detail else 0.0
            bar = "█" * int(prob * 25)
            print(f"\n   ➤ {bname:<30} {format_percentage(prob):>7}  {bar}")
            print(f"     P(Win Game | in bowl): {format_percentage(win_cond):<7} | P(Reach & Win): {format_percentage(win_uncond)}")
            if detail and detail.opponents:
                opp_str = ", ".join(f"{op} ({format_percentage(p)}, {format_percentage(w)} win%)" for op, p, w in detail.opponents[:3])
                print(f"     Projected Opponents: {opp_str}")
        print("=" * 76)

def print_bowl_card(summary, format_type: str = "table") -> None:
    b = summary
    if format_type == "md":
        print(f"### {b.bowl_name} ({b.city}, {b.state})")
        print(f"- **Type:** {'College Football Playoff' if b.is_cfp else 'Non-CFP Bowl'}")
        print("\n**Most Likely Participating Teams:**")
        print("| Team | Probability |")
        print("| :--- | :--- |")
        for tm, pr in b.top_teams[:8]:
            print(f"| {tm} | {format_percentage(pr)} |")
        if b.top_matchups:
            print("\n**Most Likely Matchups:**")
            print("| Matchup | Probability |")
            print("| :--- | :--- |")
            for t1, t2, pr in b.top_matchups[:5]:
                print(f"| {t1} vs {t2} | {format_percentage(pr)} |")
    else:
        print("=" * 68)
        print(f" {b.bowl_name.upper()} | {b.city}, {b.state}")
        print(f" Category: {'College Football Playoff' if b.is_cfp else 'Standard Bowl Game'}")
        print("=" * 68)
        print(" Top Contenders to Play in this Bowl:")
        for tm, pr in b.top_teams[:8]:
            bar = "█" * int(pr * 30)
            print(f"   {tm:<28} {format_percentage(pr):>7}  {bar}")
        if b.top_matchups:
            print("-" * 68)
            print(" Most Likely Projected Matchups:")
            for t1, t2, pr in b.top_matchups[:5]:
                print(f"   {t1} vs {t2:<24} {format_percentage(pr):>7}")
        print("=" * 68)

def print_cfp_summary(results: SimulationResults, format_type: str = "table") -> None:
    top_cfp = sorted(
        results.team_summaries.values(),
        key=lambda s: (s.p_cfp, s.p_cfp_bye),
        reverse=True
    )[:18]

    if format_type == "md":
        print("### Projected 12-Team College Football Playoff Field")
        print(f"*Ratings Source: {results.active_ratings_source}*")
        if results.active_scenario:
            print(f"*Scenario: {results.active_scenario}*")
        print("| Team | Conf | Proj Record | P(CFP) | P(Top-4 Bye) | P(Win Title) | Top Seed |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for s in top_cfp:
            top_sd = list(s.top_seeds.keys())[0] if s.top_seeds else "-"
            print(f"| {s.team_name} | {s.conf} | {s.record_mean_wins:.1f}-{s.record_mean_losses:.1f} | {format_percentage(s.p_cfp)} | {format_percentage(s.p_cfp_bye)} | {format_percentage(s.national_champ_prob)} | #{top_sd} |")

        print("\n**Expected CFP Bids by Conference:**")
        print("| Conference | Expected Bids |")
        print("| :--- | :--- |")
        for conf, mean_bids in results.conf_cfp_bids_mean.items():
            if mean_bids > 0.05:
                print(f"| {conf} | {mean_bids:.2f} |")
    else:
        print("=" * 80)
        print(f" 12-TEAM COLLEGE FOOTBALL PLAYOFF PROJECTIONS [Ratings: {results.active_ratings_source}]")
        if results.active_scenario:
            print(f" Scenario: {results.active_scenario}")
        print("=" * 80)
        print(f" {'Team':<20} {'Conf':<10} {'Proj W-L':<10} {'P(CFP)':<10} {'P(Bye)':<10} {'P(Title)':<10}")
        print("-" * 80)
        for s in top_cfp:
            rec_str = f"{s.record_mean_wins:.1f}-{s.record_mean_losses:.1f}"
            print(f" {s.team_name:<20} {s.conf:<10} {rec_str:<10} {format_percentage(s.p_cfp):<10} {format_percentage(s.p_cfp_bye):<10} {format_percentage(s.national_champ_prob):<10}")
        print("=" * 80)
        print(" Expected CFP Bids by Conference:")
        for conf, mean_bids in results.conf_cfp_bids_mean.items():
            if mean_bids > 0.05:
                print(f"   {conf:<16} {mean_bids:.2f} bids")
        print("=" * 80)

def print_conference_pecking_order(results: SimulationResults, conf_query: str | None = None, format_type: str = "table") -> None:
    orders = results.conference_pecking_orders
    confs_to_show = []
    if conf_query:
        cq = conf_query.lower()
        for c in orders.keys():
            if cq == c.lower() or cq in c.lower():
                confs_to_show.append(c)
    else:
        priority = ["SEC", "Big Ten", "Big 12", "ACC", "MWC", "AAC", "Sun Belt"]
        for p in priority:
            if p in orders:
                confs_to_show.append(p)

    for conf in confs_to_show:
        rows = orders[conf]
        if format_type == "md":
            print(f"\n### {conf} — Non-Playoff Bowl Selection Pecking Order Odds")
            print("| Team | Proj W-L | P(CFP) | P(#1 Pick) | P(#2 Pick) | P(#3 Pick) | P(#4 Pick) | P(#5+) | Exp Rank |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for r in rows:
                exp_str = f"{r['expected_rank']:.1f}" if r['expected_rank'] is not None else "-"
                p5_plus = r['p_rank_5'] + r['p_rank_6_plus']
                print(f"| {r['team_name']} | {r['proj_record']} | {format_percentage(r['p_cfp'])} | {format_percentage(r['p_rank_1'])} | {format_percentage(r['p_rank_2'])} | {format_percentage(r['p_rank_3'])} | {format_percentage(r['p_rank_4'])} | {format_percentage(p5_plus)} | {exp_str} |")
        else:
            print("=" * 88)
            print(f" {conf.upper()} — NON-PLAYOFF BOWL SELECTION PECKING ORDER ODDS")
            print("=" * 88)
            print(f" {'Team':<18} {'Proj W-L':<9} {'P(CFP)':<8} {'#1 Pick':<8} {'#2 Pick':<8} {'#3 Pick':<8} {'#4 Pick':<8} {'#5+ Pick':<9} {'Exp Rank':<8}")
            print("-" * 88)
            for r in rows:
                exp_str = f"{r['expected_rank']:.1f}" if r['expected_rank'] is not None else "-"
                p5_plus = r['p_rank_5'] + r['p_rank_6_plus']
                print(f" {r['team_name']:<18} {r['proj_record']:<9} {format_percentage(r['p_cfp']):<8} {format_percentage(r['p_rank_1']):<8} {format_percentage(r['p_rank_2']):<8} {format_percentage(r['p_rank_3']):<8} {format_percentage(r['p_rank_4']):<8} {format_percentage(p5_plus):<9} {exp_str:<8}")
            print("=" * 88)
            print(" * Ranks indicate selection priority order among non-CFP bowl-eligible conference teams.\n")

def print_historical_analysis(format_type: str = "table") -> None:
    try:
        from bowls.analysis import HistoricalAnalyzer
    except ImportError:
        from analysis import HistoricalAnalyzer

    analyzer = HistoricalAnalyzer()
    rep = analyzer.analyze_repeat_avoidance()
    brand = analyzer.analyze_brand_bias()
    dist = analyzer.analyze_distance_influence()

    if format_type == "md":
        print("### Historical College Football Bowl Selection Trends (2014–2023)")
        print("\n#### 1. Repeat Bowl Avoidance")
        print(f"- **Total Non-CFP Slots Evaluated:** {rep.non_cfp_slots_evaluated}")
        print(f"- **Non-CFP Consecutive Repeats:** {rep.non_cfp_repeats} ({rep.non_cfp_repeat_rate*100:.2f}%)")
        print(f"- **Expected Rate under Random Selection:** {rep.expected_random_repeat_rate*100:.1f}%")
        print(f"- **Repeat Suppression Ratio:** {rep.repeat_suppression_ratio*100:.1f}% suppression")

        print("\n#### 2. Brand & Fanbase Selection Bias")
        print(f"- **Estimated Brand Premium:** +{brand.brand_win_equivalent_premium:.1f} wins equivalent in bowl tiering")
        print("| Brand Tier | Tier-1 Bowl Selection Rate (7–8 Win Teams) |")
        print("| :--- | :--- |")
        for tier, pct in brand.prestige_by_brand_at_8_wins.items():
            print(f"| {tier} | {pct}% |")

        print("\n#### 3. Geographic Proximity & Drive-In Attendance")
        print(f"- **Average Campus Distance:** {dist.overall_avg_distance_miles} miles (Median: {dist.overall_median_distance_miles} miles)")
        print(f"- **Drive-In Rate (< 400 miles):** {dist.drive_in_pct_under_400_miles}%")
        print("\n| Regional Bowl | Drive-in Rate (< 400 mi) | Average Distance |")
        print("| :--- | :--- | :--- |")
        for r in dist.regional_bowls_proximity:
            print(f"| {r['bowl_name']} | {r['drive_in_pct']}% | {r['avg_distance']} mi |")
    else:
        print("=" * 78)
        print(" HISTORICAL BOWL SELECTION EMPIRICAL ANALYSIS (2014–2023)")
        print("=" * 78)
        print(" 1. CONSECUTIVE-YEAR REPEAT AVOIDANCE:")
        print(f"    Total Non-CFP Team Slots Analyzed:  {rep.non_cfp_slots_evaluated}")
        print(f"    Observed Consecutive Repeats:      {rep.non_cfp_repeats} ({rep.non_cfp_repeat_rate*100:.2f}%)")
        print(f"    Expected Rate (Random Baseline):   {rep.expected_random_repeat_rate*100:.1f}%")
        print(f"    Repeat Suppression Ratio:          {rep.repeat_suppression_ratio*100:.1f}% suppression")
        print("-" * 78)
        print(" 2. BRAND & FANBASE SELECTION BIAS:")
        print(f"    Estimated Brand Premium:           +{brand.brand_win_equivalent_premium:.1f} wins equivalent")
        print("    Tier-1 Bowl Selection Rate for Teams with 7-8 Wins:")
        for tier, pct in brand.prestige_by_brand_at_8_wins.items():
            print(f"      {tier:<24}: {pct}%")
        print("-" * 78)
        print(" 3. GEOGRAPHIC PROXIMITY & DRIVE-IN ATTENDANCE:")
        print(f"    Overall Average Campus Distance:   {dist.overall_avg_distance_miles} miles (Median: {dist.overall_median_distance_miles} mi)")
        print(f"    Overall Drive-in Rate (<400 mi):   {dist.drive_in_pct_under_400_miles}%")
        print("    Regional Bowl Proximity Bias:")
        for r in dist.regional_bowls_proximity:
            print(f"      {r['bowl_name']:<36}: {r['drive_in_pct']}% within 400 mi (avg {r['avg_distance']} mi)")
        print("=" * 78)

def main():
    parser = argparse.ArgumentParser(
        prog="bowls",
        description="College Football Season Simulation, CFP Seeding & Bowl Picking Model"
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to run")

    # Global options added to subparsers
    def add_common_args(p):
        p.add_argument("--sims", type=int, default=2000, help="Number of Monte Carlo simulations")
        p.add_argument("--ratings", type=str, default="default", help="Power ratings: default (FPI), fpi, results, or path/to/file.csv")
        p.add_argument("--win-out", type=str, help="Team name or ID forced to win all remaining games")
        p.add_argument("--lose-out", type=str, help="Team name or ID forced to lose all remaining games")
        p.add_argument("--scenario", type=str, help="Custom scenario specification (e.g. 'texas:win_out,texas_am>lsu')")
        p.add_argument("--format", choices=["table", "md", "json"], default="table", help="Output format")

    # run command
    run_parser = subparsers.add_parser("run", help="Run full season simulations")
    add_common_args(run_parser)
    run_parser.add_argument("--export", type=str, help="Export output to a JSON file")

    # team command
    team_parser = subparsers.add_parser("team", help="Inspect a specific team's bowl outlook, win odds, and opponents")
    team_parser.add_argument("name", type=str, help="Team name or ID (e.g. 'Texas', 'Iowa', 'Ohio State')")
    add_common_args(team_parser)

    # bowl command
    bowl_parser = subparsers.add_parser("bowl", help="Inspect a specific bowl's projected field and matchups")
    bowl_parser.add_argument("name", type=str, help="Bowl name or ID (e.g. 'Pop-Tarts Bowl', 'Citrus Bowl')")
    add_common_args(bowl_parser)

    # cfp command
    cfp_parser = subparsers.add_parser("cfp", help="Show 12-team CFP projections")
    add_common_args(cfp_parser)

    # backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Backtest model accuracy against previous seasons")
    backtest_parser.add_argument("--season", type=int, default=2023, help="Historical season to backtest (e.g. 2023)")
    backtest_parser.add_argument("--sims", type=int, default=1500, help="Number of simulations")

    # pecking-order command
    pecking_parser = subparsers.add_parser("pecking-order", help="Show non-playoff conference pecking order odds")
    pecking_parser.add_argument("--conf", type=str, help="Conference filter (e.g. SEC, Big Ten, Big 12, ACC)")
    add_common_args(pecking_parser)

    # history / analyze command
    history_parser = subparsers.add_parser("history", help="Analyze historical bowl trends (repeats, brands, distance)")
    history_parser.add_argument("--format", choices=["table", "md"], default="table")

    # list command
    subparsers.add_parser("list", help="List all bowl games and tie-ins")

    args = parser.parse_args()

    # Build scenario from flags if present
    def build_scenario(args_obj) -> Scenario | None:
        sc = Scenario()
        has_sc = False
        if getattr(args_obj, "scenario", None):
            sc = Scenario.from_string(args_obj.scenario)
            has_sc = True
        if getattr(args_obj, "win_out", None):
            sc.wins_out.add(args_obj.win_out.lower().replace(" ", "_"))
            has_sc = True
        if getattr(args_obj, "lose_out", None):
            sc.loses_out.add(args_obj.lose_out.lower().replace(" ", "_"))
            has_sc = True
        return sc if has_sc else None

    if not args.command or args.command == "run":
        sims = getattr(args, "sims", 2000)
        fmt = getattr(args, "format", "table")
        ratings_src = getattr(args, "ratings", "default")
        export_path = getattr(args, "export", None)
        scenario = build_scenario(args)

        engine = BowlEngine(config=SimConfig(simulations=sims), ratings_source=ratings_src)
        results = engine.run(scenario=scenario)

        if export_path:
            with open(export_path, "w") as f:
                json.dump(results.to_dict(), f, indent=2)
            print(f"Results exported to {export_path}", file=sys.stderr)

        if fmt == "json":
            print(json.dumps(results.to_dict(), indent=2))
        else:
            print_cfp_summary(results, format_type=fmt)
            print("\n")
            featured_bowls = [
                "citrus_bowl", "alamo_bowl", "pop_tarts_bowl",
                "reliaquest_bowl", "gator_bowl", "holiday_bowl",
                "music_city_bowl", "texas_bowl"
            ]
            for b_id in featured_bowls:
                if b_id in results.bowl_summaries:
                    print_bowl_card(results.bowl_summaries[b_id], format_type=fmt)
                    print()

    elif args.command == "team":
        ratings_src = getattr(args, "ratings", "default")
        scenario = build_scenario(args)
        engine = BowlEngine(config=SimConfig(simulations=args.sims), ratings_source=ratings_src)
        results = engine.run(scenario=scenario)

        query = args.name.lower().replace(" ", "_")
        matched = None
        for t_id, s in results.team_summaries.items():
            if query == t_id or query == s.team_name.lower() or query in t_id or query in s.team_name.lower():
                matched = s
                break
        if matched:
            print_team_card(matched, format_type=args.format)
        else:
            print(f"Error: Team '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "bowl":
        ratings_src = getattr(args, "ratings", "default")
        scenario = build_scenario(args)
        engine = BowlEngine(config=SimConfig(simulations=args.sims), ratings_source=ratings_src)
        results = engine.run(scenario=scenario)

        query = args.name.lower().replace(" ", "_")
        matched = None
        for b_id, b in results.bowl_summaries.items():
            if query in b_id or query in b.bowl_name.lower():
                matched = b
                break
        if matched:
            print_bowl_card(matched, format_type=args.format)
        else:
            print(f"Error: Bowl '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "cfp":
        ratings_src = getattr(args, "ratings", "default")
        scenario = build_scenario(args)
        engine = BowlEngine(config=SimConfig(simulations=args.sims), ratings_source=ratings_src)
        results = engine.run(scenario=scenario)
        print_cfp_summary(results, format_type=args.format)

    elif args.command == "backtest":
        print(f"Running historical backtest for {args.season} season ({args.sims} simulations)...", file=sys.stderr)
        backtester = Backtester(season=args.season)
        scorecard = backtester.run_backtest(sims=args.sims)
        print(scorecard.summary_table())

    elif args.command == "pecking-order":
        ratings_src = getattr(args, "ratings", "default")
        scenario = build_scenario(args)
        engine = BowlEngine(config=SimConfig(simulations=args.sims), ratings_source=ratings_src)
        results = engine.run(scenario=scenario)
        print_conference_pecking_order(results, conf_query=args.conf, format_type=args.format)

    elif args.command in ("history", "analyze"):
        print_historical_analysis(format_type=args.format)

    elif args.command == "list":
        engine = BowlEngine()
        print(f"{'Bowl Name':<34} {'City, State':<22} {'Tie-Ins / Type'}")
        print("=" * 80)
        for b in engine.bowls:
            if b.is_cfp:
                tie_str = f"CFP {b.cfp_round.title()}"
            else:
                c1 = b.tie_in_1.get("conf", "Open")
                c2 = b.tie_in_2.get("conf", "Open")
                tie_str = f"{c1} vs {c2}"
            print(f"{b.name:<34} {b.city + ', ' + b.state:<22} {tie_str}")

if __name__ == "__main__":
    main()
