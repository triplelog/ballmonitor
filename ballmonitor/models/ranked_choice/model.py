"""Re-count published ranked ballots (AP Top 25, MLB/NBA/NHL awards) with other voting methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction, Table
from ballmonitor.models.ranked_choice import ballots as data
from ballmonitor.models.ranked_choice import voting as v

LABELS = {"official": "Official points", "borda": "Borda", "custom_points": "Custom points",
          "plurality": "Plurality", "irv": "Instant runoff", "coombs": "Coombs", "baldwin": "Baldwin",
          "bucklin": "Bucklin", "copeland": "Copeland", "schulze": "Schulze", "ranked_pairs": "Ranked pairs",
          "minimax": "Minimax", "kemeny": "Kemeny-Young"}
SHORT = {"official": "Off", "borda": "Borda", "custom_points": "Cust", "plurality": "Plur", "irv": "IRV",
         "coombs": "Coombs", "baldwin": "Bald", "bucklin": "Buck", "copeland": "Cope", "schulze": "Schu",
         "ranked_pairs": "RP", "minimax": "Mmax", "kemeny": "Kem"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class RankedChoiceModel(BaseModel):
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        steps: list[str] = []
        contest, rows, names, teams = self._load(inputs, steps)
        ballots = [r["ranking"] for r in rows]
        if not ballots:
            raise ValueError("no ballots for this contest")
        n_places = int(contest.get("n_places") or max(len(b) for b in ballots))
        cands = v.candidates_of(ballots)
        name = lambda c: names.get(c, c)  # noqa: E731
        steps.append(f"{len(ballots)} ballots ranking {n_places} places; {len(cands)} candidates named on "
                     f"at least one ballot.")

        # ---- official points and the shared tie-break ---------------------------------------
        pts = data.points_list(contest)
        if pts:
            official_pts = lambda r, n: pts[r - 1] if r <= len(pts) else 0.0  # noqa: E731
            steps.append(f"Official points by place: {', '.join(f'{x:g}' for x in pts)}.")
        else:
            official_pts = lambda r, n: float(p.formula("borda_points", rank=r, n_places=n_places))  # noqa: E731
            steps.append("No official points table: 'official' = Borda (formula borda_points).")
        counts = v.place_counts(ballots, cands, n_places)
        off_score = {c: sum(official_pts(r + 1, n_places) * k for r, k in enumerate(counts[c])) for c in cands}
        tiebreak = {c: (off_score[c], counts[c][0]) for c in cands}
        steps.append("Ties in every method are broken by official points, then first-place votes, then name.")
        self._check_published(contest, off_score, counts, steps)

        # ---- count every method --------------------------------------------------------------
        methods = list(dict.fromkeys([str(p.method)] + [str(m) for m in p.compare_methods]))
        for m in methods:
            if m not in LABELS:
                raise ValueError(f"unknown method '{m}' in compare_methods (choices: {', '.join(LABELS)})")
        d = v.pairwise(ballots, cands, str(p.unranked))
        positions = n_places
        results: dict[str, v.Result] = {}
        for m in methods:
            results[m] = self._count(m, ballots, cands, d, tiebreak, official_pts, n_places, positions)
        cw, cl = v.condorcet_winner(d, cands), v.condorcet_loser(d, cands)
        smith = v.smith_set(d, cands, tiebreak)
        steps.append(f"Pairwise matrix: d[a][b] = ballots ranking a above b (unranked = '{p.unranked}': "
                     + ("a name left off a ballot is beaten by every name on it)." if p.unranked == "below"
                        else "a ballot only counts pairs it ranks both of)."))
        steps.append("Condorcet winner (beats every rival head to head): "
                     + (f"{name(cw)}." if cw else f"none - a cycle; Smith set = {', '.join(name(c) for c in smith)}."))
        for m in methods:
            r = results[m]
            line = f"{LABELS[m]}: winner {name(r.order[0])}; ranks by {r.score_label}."
            if m in ("borda", "custom_points"):
                line += f" Points = {p.expr('borda_points' if m == 'borda' else 'custom_points')}."
            if m in ("schulze", "ranked_pairs"):
                line += f" Strength = {p.pairwise_measure}."
            if m == "minimax":
                line += f" Strength = {p.minimax_measure}."
            if m == "kemeny" and not r.exact:
                line += f" Approximate: exact over the top {int(p.kemeny_exact_max)}, local search below."
            steps.append(line + (" " + self._names("; ".join(r.log[:3]), names) if r.log else ""))

        # ---- outcomes -----------------------------------------------------------------------
        main = results[str(p.method)]
        official_order = results["official"].order if "official" in results else \
            self._count("official", ballots, cands, d, tiebreak, official_pts, n_places, positions).order
        show = int(p.show_places) or n_places
        winner = main.order[0]
        first_share = counts[winner][0] / len(ballots)
        same = winner == official_order[0]
        outcomes = [Outcome(f"Winner ({LABELS[str(p.method)]}): {name(winner)}", probability=first_share,
                            fmt="pct", note=("first-place share; same as the official winner" if same else
                                             f"first-place share; official winner: {name(official_order[0])}"))]
        off_pos = {c: i + 1 for i, c in enumerate(official_order)}
        for i, c in enumerate(main.order[:show], 1):
            delta = off_pos[c] - i
            move = "same" if delta == 0 else (f"up {delta}" if delta > 0 else f"down {-delta}")
            team = f" ({teams[c]})" if teams.get(c) else ""
            outcomes.append(Outcome(f"{i}. {name(c)}{team}", estimate=float(off_score[c]), fmt="number",
                                    group=f"Ranking: {LABELS[str(p.method)]} (value = official points)",
                                    note=f"official {_ordinal(off_pos[c])} ({move}); {counts[c][0]} first-place "
                                         + ("vote" if counts[c][0] == 1 else "votes")))
        for m in methods:
            w = results[m].order[0]
            outcomes.append(Outcome(LABELS[m], probability=counts[w][0] / len(ballots), fmt="pct",
                                    group="Winner by method (value = winner's first-place share)",
                                    note=name(w) + ("" if w == official_order[0] else "  <- differs from official")))
        table = v.disagreements({m: results[m].order for m in methods}, show)
        split = [c for c, places in table.items() if len(set(places.values())) > 1]
        grid_rows = sorted(table, key=lambda c: (table[c][str(p.method)], c))
        grid = Table(f"Place by method (top {show} of any method)", ["Candidate"] + [SHORT[m] for m in methods],
                     [[name(c) + (" *" if c in split else "")] + [str(table[c][m]) for m in methods]
                      for c in grid_rows],
                     note="* = the methods disagree. " + ", ".join(f"{SHORT[m]} = {LABELS[m]}" for m in methods) + ".")
        steps.append(f"{len(split)} of the {len(table)} candidates in any method's top {show} are not placed "
                     f"the same by every method.")
        a, b = official_order[0], official_order[1] if len(official_order) > 1 else official_order[0]
        if a != b:
            ab, ba = v.head_to_head(d, a, b)
            outcomes.append(Outcome(f"{name(a)} vs {name(b)}", probability=ab / max(ab + ba, 1), fmt="pct",
                                    group="Head to head (official 1st vs 2nd)",
                                    note=f"{ab} ballots rank {name(a)} higher, {ba} rank {name(b)} higher"))
        if cw:
            rival = min((c for c in cands if c != cw), key=lambda c: d[cw][c] - d[c][cw])
            wins, losses = v.head_to_head(d, cw, rival)
            outcomes.append(Outcome("Condorcet winner", probability=wins / max(wins + losses, 1), fmt="pct",
                                    group="Head to head (official 1st vs 2nd)",
                                    note=f"{name(cw)}; closest rival {name(rival)} ({wins}-{losses})"))
        else:
            outcomes.append(Outcome("Condorcet winner: none", estimate=float(len(smith)), fmt="int",
                                    group="Head to head (official 1st vs 2nd)",
                                    note="value = size of the Smith set: " + ", ".join(name(c) for c in smith)))

        distinct = list({(r["voter"], r["affiliation"]): r for r in rows}.values())
        dist = sorted(((v.footrule(r["ranking"], main.order, n_places), r) for r in distinct),
                      key=lambda x: (-x[0], x[1]["voter"]))
        for k, r in dist[: int(p.outlier_count)]:
            who = r["voter"] + (f" ({r['affiliation']})" if r["affiliation"] else "")
            outcomes.append(Outcome(who, estimate=float(k), fmt="int",
                                    group=f"Most unusual ballots (value = footrule distance from {LABELS[str(p.method)]})",
                                    note="top 3: " + ", ".join(name(c) for c in r["ranking"][:3])))
        if dist:
            mean = sum(k for k, _ in dist) / len(dist)
            steps.append(f"Unusual ballots: Spearman footrule between each ballot and the {LABELS[str(p.method)]} "
                         f"top {n_places} (unlisted = place {n_places + 1}); mean {mean:.1f}.")

        top_pair = main.order[:show]
        extras = {
            "contest": {k: contest.get(k, "") for k in ("contest_id", "source", "sport", "league", "award", "season",
                                                         "week", "date", "title", "url")},
            "n_ballots": len(ballots), "n_places": n_places,
            "candidates": {c: {"name": name(c), "team": teams.get(c, ""), "first": counts[c][0],
                               "official_points": off_score[c]} for c in cands},
            "orders": {m: results[m].order for m in methods},
            "scores": {m: results[m].scores for m in methods},
            "exact": {m: results[m].exact for m in methods},
            "condorcet_winner": cw, "condorcet_loser": cl, "smith_set": smith,
            "pairwise_top": {"candidates": top_pair, "matrix": [[d[x][y] if x != y else None for y in top_pair]
                                                                for x in top_pair]},
            "unusual": [{"voter": r["voter"], "affiliation": r["affiliation"], "distance": k,
                         "ballot": r["ranking"]} for k, r in dist[: int(p.outlier_count)]],
        }
        data_dir = Path(self.dir) / "data" / "ballots"
        extras["index"] = {s: [[r["contest_id"], r.get("title", r["contest_id"])] for r in data.contests(data_dir, s)]
                           for s in data.SOURCES if data.contests(data_dir, s)}
        shown = {"contest": contest.get("title") or contest.get("contest_id", ""), "ballots": str(len(ballots)),
                 "method": LABELS[str(p.method)]}
        return self.prediction(inputs=shown, outcomes=outcomes, steps=steps, extras=extras, tables=[grid])

    # ----------------------------------------------------------------------------------------

    def _load(self, inputs: dict[str, Any], steps: list[str]):
        if inputs.get("ballots"):
            raw = inputs["ballots"]
            if not isinstance(raw, list) or not all(isinstance(b, list) for b in raw):
                raise ValueError("ballots must be a list of lists of names, best first")
            weights = inputs.get("weights") or [1] * len(raw)
            if len(weights) != len(raw):
                raise ValueError("weights must have one entry per ballot")
            rows, names = [], {}
            for i, (b, w) in enumerate(zip(raw, weights)):
                if len(set(b)) != len(b):
                    raise ValueError(f"ballot {i + 1} names a candidate twice")
                for _ in range(int(w)):
                    rows.append({"voter": f"ballot {i + 1}", "affiliation": "", "ranking": [str(c) for c in b]})
                for c in b:
                    names[str(c)] = str(c)
            contest = {"contest_id": "custom", "title": str(inputs.get("title", "Custom ballots")),
                       "points": ",".join(str(x) for x in inputs.get("points", [])),
                       "n_places": str(max(len(b) for b in raw))}
            steps.append(f"Custom ballots from the inputs ({len(raw)} distinct, {len(rows)} after weights).")
            return contest, rows, names, {}
        cid = str(inputs.get("contest", "")).strip()
        if not cid:
            raise ValueError("give `contest` (e.g. 'mlb-2024-al-mvp', 'ap-cfb-latest') or `ballots`")
        data_dir = Path(self.dir) / "data" / "ballots"
        contest = data.resolve(data_dir, cid)
        rows, names, teams = data.ballots_for(data_dir, contest)
        steps.append(f"Contest {contest['contest_id']}: {contest.get('title', '')}"
                     + (f" ({contest['date']})" if contest.get("date") else "")
                     + f"; ballots from {contest.get('url') or 'the source'}.")
        return contest, rows, names, teams

    @staticmethod
    def _names(text: str, names: dict[str, str]) -> str:
        """Candidate ids in a method's log -> display names (longest id first)."""
        for cid in sorted(names, key=len, reverse=True):
            if cid != names[cid] and cid in text:
                text = text.replace(cid, names[cid])
        return text

    def _check_published(self, contest, off_score, counts, steps):
        pub = data.published(contest)
        if not pub:
            return
        bad = [(c, pts, off_score.get(c, 0.0)) for c, pts, _ in pub if abs(off_score.get(c, 0.0) - pts) > 1e-6]
        if bad:
            steps.append(f"WARNING: recomputed official points differ from the published totals for {len(bad)} "
                         f"candidates (first: {bad[0][0]} published {bad[0][1]:g}, recomputed {bad[0][2]:g}).")
        else:
            steps.append(f"Check: recomputed official points match all {len(pub)} published totals.")

    def _count(self, m, ballots, cands, d, tiebreak, official_pts, n_places, positions) -> v.Result:
        p = self.params
        if m == "official":
            return v.positional(ballots, cands, official_pts, tiebreak, "official points")
        if m == "borda":
            return v.positional(ballots, cands, lambda r, n: float(p.formula("borda_points", rank=r, n_places=n_places)),
                                tiebreak, "Borda points")
        if m == "custom_points":
            return v.positional(ballots, cands, lambda r, n: float(p.formula("custom_points", rank=r, n_places=n_places)),
                                tiebreak, "custom points")
        if m == "plurality":
            return v.plurality(ballots, cands, tiebreak)
        if m in ("irv", "coombs", "baldwin", "bucklin"):
            return v.elimination(m, ballots, cands, tiebreak, str(p.elimination_ordering), positions)
        if m == "copeland":
            return v.copeland(d, cands, tiebreak, float(p.copeland_tie_score))
        if m == "schulze":
            return v.schulze(d, cands, tiebreak, str(p.pairwise_measure))
        if m == "ranked_pairs":
            return v.ranked_pairs(d, cands, tiebreak, str(p.pairwise_measure))
        if m == "minimax":
            return v.minimax(d, cands, tiebreak, str(p.minimax_measure))
        if m == "kemeny":
            start = v.schulze(d, cands, tiebreak, str(p.pairwise_measure)).order
            return v.kemeny(d, cands, tiebreak, int(p.kemeny_exact_max), start)
        raise ValueError(m)
