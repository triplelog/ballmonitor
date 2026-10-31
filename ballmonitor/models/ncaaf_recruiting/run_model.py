#!/usr/bin/env python3
"""
CLI runner for the cfbRec offer-based college football recruiting rankings.

Usage:
    python run_model.py 2024
    python run_model.py 2024 --breakdown
    python run_model.py 2024 --unit offense
    python run_model.py 2024 --unit run_def --top 15
    python run_model.py 2024 --top 15 --compare-rivals --geo
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models import RankingMethod
from src.data_loader import DataLoader
from src.elo_engine import EloEngine
from src.position_model import PositionalRankingEngine


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run offer-based recruiting rankings using Plackett-Luce or Sequential Elo."
    )
    parser.add_argument(
        "pos_year",
        nargs="?",
        type=int,
        default=None,
        help="Recruiting class year (e.g., 2024).",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=None,
        help="Recruiting class year (default: 2024).",
    )
    parser.add_argument(
        "--method",
        "-m",
        choices=["plackett_luce", "sequential_elo"],
        default="plackett_luce",
        help="Ranking methodology (default: plackett_luce).",
    )
    parser.add_argument(
        "--decay",
        type=float,
        default=0.95,
        help="Rank decay discount factor across team recruits (default: 0.95).",
    )
    parser.add_argument(
        "--power",
        type=float,
        default=0.5,
        help="Recruit offer-quality power exponent (default: 0.5).",
    )
    parser.add_argument(
        "--top",
        "-n",
        type=int,
        default=25,
        help="Number of teams to display (default: 25).",
    )
    parser.add_argument(
        "--compare-rivals",
        "-c",
        action="store_true",
        help="Display comparison against official Rivals star-based class rank.",
    )
    parser.add_argument(
        "--geo",
        "-g",
        action="store_true",
        help="Display geographic metrics (avg recruit distance in miles, national %%).",
    )
    parser.add_argument(
        "--breakdown",
        "-b",
        action="store_true",
        help="Display positional breakdown: Offense vs Defense and Run vs Pass.",
    )
    parser.add_argument(
        "--unit",
        "-u",
        choices=["all", "offense", "defense", "run_off", "pass_off", "run_def", "pass_def"],
        default="all",
        help="Rank and display by specific unit or phase (default: all).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "md", "csv"],
        default="text",
        help="Output format (text, md, csv).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional path to write CSV output.",
    )
    return parser.parse_args()


def render_table(result, rivals_map, top_n, fmt, show_rivals, show_geo):
    teams = result.teams[:top_n]

    if fmt == "csv":
        header = ["Rank", "Team", "Elo", "Commits", "Offers", "Score", "Avg Recruit Score"]
        if show_geo:
            header.extend(["Avg Dist (mi)", "National %"])
        if show_rivals:
            header.extend(["Rivals Rank", "Diff"])
        lines = [",".join(header)]
        for t in teams:
            row = [
                str(t.rank),
                t.name,
                f"{t.elo:.1f}",
                str(t.commits_count),
                str(t.offers_count),
                f"{t.total_score:.2f}",
                f"{t.avg_recruit_score:.2f}",
            ]
            if show_geo:
                row.extend([f"{t.avg_recruit_distance:.1f}", f"{t.national_pct:.1f}%"])
            if show_rivals:
                r_info = rivals_map.get(t.name)
                r_rank = str(r_info[0]) if r_info else "N/A"
                diff = str(r_info[0] - t.rank) if r_info else "N/A"
                row.extend([r_rank, diff])
            lines.append(",".join(row))
        return "\n".join(lines)

    if fmt == "md":
        header = "| Rank | Team | Elo | Commits | Score |"
        divider = "|:---:|:---|:---:|:---:|:---:|"
        if show_geo:
            header += " Avg Dist | Nat % |"
            divider += ":---:|:---:|"
        if show_rivals:
            header += " Rivals Rank | Diff |"
            divider += ":---:|:---:|"
        method_name = "Plackett-Luce" if result.method == RankingMethod.PLACKETT_LUCE else "Sequential Elo"
        lines = [f"### Class of {result.year} Offer-Based Recruiting Rankings ({method_name})", "", header, divider]
        for t in teams:
            row = f"| {t.rank} | **{t.name}** | {t.elo:.1f} | {t.commits_count} | {t.total_score:.2f} |"
            if show_geo:
                row += f" {t.avg_recruit_distance:.0f} mi | {t.national_pct:.0f}% |"
            if show_rivals:
                r_info = rivals_map.get(t.name)
                r_rank = str(r_info[0]) if r_info else "N/A"
                diff = f"{r_info[0] - t.rank:+d}" if r_info else "N/A"
                row += f" {r_rank} | {diff} |"
            lines.append(row)
        return "\n".join(lines)

    # Standard Text table
    method_str = "PLACKETT-LUCE" if result.method == RankingMethod.PLACKETT_LUCE else "SEQUENTIAL ELO"
    lines = [
        "=" * 80,
        f"     CLASS OF {result.year} OFFER-BASED RECRUITING RANKINGS ({method_str})",
        "=" * 80,
    ]
    hdr = f"{'Rank':4s}  {'Team':<22s}  {'Elo':>6s}  {'Commits':>7s}  {'Score':>7s}"
    if show_geo:
        hdr += f"  {'AvgDist':>7s}  {'Nat%':>5s}"
    if show_rivals:
        hdr += f"  {'Rivals':>6s}  {'Diff':>5s}"
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for t in teams:
        row = f"{t.rank:3d}.  {t.name:<22s}  {t.elo:6.1f}  {t.commits_count:7d}  {t.total_score:7.2f}"
        if show_geo:
            row += f"  {t.avg_recruit_distance:6.0f}m  {t.national_pct:4.0f}%"
        if show_rivals:
            r_info = rivals_map.get(t.name)
            r_rank = f"{r_info[0]:4d}" if r_info else " N/A"
            diff = f"{r_info[0] - t.rank:+4d}" if r_info else "  N/A"
            row += f"  {r_rank}  {diff}"
        lines.append(row)

    return "\n".join(lines)


def render_positional_table(pos_result, unit_choice, top_n, fmt):
    """Render the positional / run-pass breakdown table."""
    unit_key_map = {
        "all": "overall",
        "offense": "offense",
        "defense": "defense",
        "run_off": "run_offense",
        "pass_off": "pass_offense",
        "run_def": "run_defense",
        "pass_def": "pass_defense",
    }
    criterion = unit_key_map.get(unit_choice, "overall")
    sorted_teams = pos_result.rank_by(criterion)[:top_n]

    unit_title_map = {
        "all": "OVERALL & UNIT BREAKDOWN (OFF/DEF & RUN/PASS)",
        "offense": "OFFENSIVE RECRUITING RANKINGS (RUN & PASS)",
        "defense": "DEFENSIVE RECRUITING RANKINGS (RUN & PASS)",
        "run_off": "RUN OFFENSE RECRUITING RANKINGS",
        "pass_off": "PASS OFFENSE RECRUITING RANKINGS",
        "run_def": "RUN DEFENSE RECRUITING RANKINGS",
        "pass_def": "PASS DEFENSE RECRUITING RANKINGS",
    }
    title = unit_title_map.get(unit_choice, "POSITIONAL BREAKDOWN")

    if fmt == "csv":
        header = [
            "Rank", "Team", "Commits", "Overall Score",
            "Offense Score", "Offense Rank", "Run Off Score", "Pass Off Score",
            "Defense Score", "Defense Rank", "Run Def Score", "Pass Def Score"
        ]
        lines = [",".join(header)]
        for idx, t in enumerate(sorted_teams, 1):
            row = [
                str(idx),
                t.name,
                str(t.commits_count),
                f"{t.overall_score:.2f}",
                f"{t.offense_score:.2f}",
                str(t.offense_rank),
                f"{t.run_offense_score:.2f}",
                f"{t.pass_offense_score:.2f}",
                f"{t.defense_score:.2f}",
                str(t.defense_rank),
                f"{t.run_defense_score:.2f}",
                f"{t.pass_defense_score:.2f}",
            ]
            lines.append(",".join(row))
        return "\n".join(lines)

    if fmt == "md":
        lines = [
            f"### Class of {pos_result.year} {title}",
            "",
            "| Rank | Team | Overall | Offense (Run / Pass) | Off Rank | Defense (Run / Pass) | Def Rank |",
            "|:---:|:---|:---:|:---:|:---:|:---:|:---:|",
        ]
        for idx, t in enumerate(sorted_teams, 1):
            off_str = f"{t.offense_score:.1f} ({t.run_offense_score:.1f} / {t.pass_offense_score:.1f})"
            def_str = f"{t.defense_score:.1f} ({t.run_defense_score:.1f} / {t.pass_defense_score:.1f})"
            lines.append(f"| {idx} | **{t.name}** | {t.overall_score:.1f} | {off_str} | #{t.offense_rank} | {def_str} | #{t.defense_rank} |")
        return "\n".join(lines)

    # Standard Text table
    lines = [
        "=" * 102,
        f"     CLASS OF {pos_result.year} {title}",
        "=" * 102,
    ]
    hdr = f"{'Rank':<5} {'Team':<20} {'Overall':<8} | {'Offense (Run / Pass)':<26} {'Off#':<6} | {'Defense (Run / Pass)':<26} {'Def#'}"
    lines.append(hdr)
    lines.append("-" * 102)

    for idx, t in enumerate(sorted_teams, 1):
        off_detail = f"{t.offense_score:5.1f} ({t.run_offense_score:4.1f} / {t.pass_offense_score:4.1f})"
        def_detail = f"{t.defense_score:5.1f} ({t.run_defense_score:4.1f} / {t.pass_defense_score:4.1f})"
        row = f"{idx:<5} {t.name:<20} {t.overall_score:<8.2f} | {off_detail:<26} #{t.offense_rank:<5} | {def_detail:<26} #{t.defense_rank}"
        lines.append(row)

    return "\n".join(lines)


def main():
    args = parse_args()
    year = args.pos_year or args.year or 2024

    loader = DataLoader(PROJECT_ROOT / "data")
    try:
        recruits = loader.load_recruits(year, geolocate=args.geo)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    rivals_map = loader.load_rivals_rankings(year)
    show_rivals = args.compare_rivals or (args.format != "text")

    method_enum = (
        RankingMethod.PLACKETT_LUCE
        if args.method == "plackett_luce"
        else RankingMethod.SEQUENTIAL_ELO
    )
    engine = EloEngine(
        method=method_enum,
        quality_power=args.power,
        rank_decay=args.decay,
    )
    result = engine.run(year, recruits)

    # Positional evaluation if requested
    if args.breakdown or args.unit != "all":
        pos_engine = PositionalRankingEngine()
        pos_result = pos_engine.evaluate(result)
        output = render_positional_table(pos_result, args.unit, args.top, args.format)
    else:
        output = render_table(result, rivals_map, args.top, args.format, show_rivals, args.geo)

    print(output)

    if args.output:
        if args.breakdown or args.unit != "all":
            csv_out = render_positional_table(pos_result, args.unit, len(pos_result.teams), "csv")
        else:
            csv_out = render_table(result, rivals_map, len(result.teams), "csv", show_rivals=True, show_geo=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(csv_out)
        print(f"\nSaved full rankings to {args.output}")


if __name__ == "__main__":
    main()
