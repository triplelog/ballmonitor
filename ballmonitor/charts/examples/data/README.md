# Baseball data for the examples

From the [Lahman Baseball Database](https://sabr.org/lahman-database/)
(Sean Lahman, licensed CC BY-SA 3.0), seasons 1871–2024. `make-data.py`
builds the three files from Lahman's Batting, Pitching, People and Teams tables.

- **batting.csv** — a row per player season with 400 or more at bats (16,230):
  `player, year, team, league, born, G, AB, R, H, 2B, 3B, HR, RBI, SB, CS, BB, SO, HBP, SF`.
- **pitching.csv** — a row per pitcher season with 100 or more innings (15,216):
  `player, year, team, league, born, W, L, G, GS, SV, IPouts, H, ER, HR, BB, SO`.
  Innings are `IPouts / 3`; ERA is `27 ER / IPouts`, strikeouts per nine innings `27 SO / IPouts`.
- **teams.csv** — each team season's batting totals, summed over all its
  players (3,075): `year, team, league, name, AB, R, H, 2B, 3B, HR, BB, SO, SB, CS, HBP, SF`.

A player traded during a season has a row for each team. `born` is the
birth year (blank when unknown), so `year - born` is roughly the age.

Some stats weren't recorded in early seasons and read 0 there, not blank:
caught stealing (CS) before 1920, and in only one league most years until
1951; sacrifice flies (SF) before 1954. Filter by year when a formula uses
them (`year >= 1954` for on-base percentage with SF).
