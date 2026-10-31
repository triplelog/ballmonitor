"""
Scenario & "What-If" Analysis Engine:
Allows forcing specific outcomes, such as a team winning out the rest of the season,
losing out, or forcing specific head-to-head game winners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

@dataclass
class Scenario:
    # Teams that win all remaining regular-season schedule games
    wins_out: set[str] = field(default_factory=set)
    # Teams that lose all remaining regular-season schedule games
    loses_out: set[str] = field(default_factory=set)
    # Specific forced game outcomes: (home_id, away_id) -> winner_id
    forced_games: dict[tuple[str, str], str] = field(default_factory=dict)
    # Forced conference champions: conf_name -> team_id
    forced_conf_champs: dict[str, str] = field(default_factory=dict)
    # Temporary rating overrides: team_id -> new_rating
    rating_overrides: dict[str, float] = field(default_factory=dict)

    def is_forced(self, home_id: str, away_id: str) -> str | None:
        """Returns winner_id if this game has a predetermined winner, else None."""
        # 1. Direct forced game matchup
        if (home_id, away_id) in self.forced_games:
            return self.forced_games[(home_id, away_id)]
        if (away_id, home_id) in self.forced_games:
            return self.forced_games[(away_id, home_id)]

        # 2. Wins-out vs non-wins-out
        home_wins_out = home_id in self.wins_out
        away_wins_out = away_id in self.wins_out

        if home_wins_out and not away_wins_out:
            return home_id
        if away_wins_out and not home_wins_out:
            return away_id

        # 3. Loses-out vs non-loses-out
        home_loses_out = home_id in self.loses_out
        away_loses_out = away_id in self.loses_out

        if home_loses_out and not away_loses_out:
            return away_id
        if away_loses_out and not home_loses_out:
            return home_id

        return None

    @classmethod
    def from_string(cls, scenario_str: str | None) -> Scenario:
        """
        Parses a human-readable scenario specification string.
        Examples:
        - "texas:win_out"
        - "ohio_state:win_out,penn_state:win_out"
        - "texas_am>lsu"
        - "alabama:lose_out"
        """
        if not scenario_str:
            return cls()

        sc = cls()
        tokens = [t.strip() for t in scenario_str.split(",") if t.strip()]
        for tok in tokens:
            if ":" in tok:
                team_part, action = tok.split(":", 1)
                t_id = team_part.strip().lower().replace(" ", "_")
                action = action.strip().lower()
                if action in ("win_out", "wins_out", "wins"):
                    sc.wins_out.add(t_id)
                elif action in ("lose_out", "loses_out", "losses"):
                    sc.loses_out.add(t_id)
                elif action.startswith("champ="):
                    conf = t_id.upper()
                    champ = action.split("=", 1)[1].strip().lower().replace(" ", "_")
                    sc.forced_conf_champs[conf] = champ
            elif ">" in tok:
                # winner > loser
                winner, loser = tok.split(">", 1)
                w_id = winner.strip().lower().replace(" ", "_")
                l_id = loser.strip().lower().replace(" ", "_")
                sc.forced_games[(w_id, l_id)] = w_id
                sc.forced_games[(l_id, w_id)] = w_id

        return sc
