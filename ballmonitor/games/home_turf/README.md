# Home Turf (play-test version)

A strategy game on a map of where big-leaguers were born. Four managers (you and three AI) snake-draft
43 territories in 8 regions. Each territory's soldiers are real players born there, called up best first. Battles
are fought with their real seasons. On the site at ballmonitor.com/hometurf/ (the build copies `web/`);
locally `ballmonitor serve`, then `/hometurf/`.

## Rules (rules.toml has every number)

- **Draft.** The managers snake-draft every territory in random seat order. Each territory comes with
  its best native.
- **Opening call-ups.** Each manager places `start_callups` (16). A call-up is the best remaining
  native of one of your territories.
- **Each turn:** call-ups (one per `territories_per_callup` = 3 territories held, at least
  `callups_min` = 3, plus the bonus of every region held whole), then battles, then one move between
  connected territories you hold.
- **Battle.** You pick one soldier from a territory with 2+ soldiers. The defender picks one at the
  same time (secret picks). Each plays one of his remaining real seasons, drawn at random and used up.
  The defender adds `home_field` (+0.5 WAR). The higher season wins, ties go to the defender
  (compared in whole tenths of WAR), and the loser is out of the game. Take the last soldier and the
  territory, with its bench, is yours. You then choose who moves in (shortcuts: strongest, weakest,
  half, all but one).
- **Empty territories.** A defender who wins on his last season, with nobody left on the bench,
  retires and leaves his territory empty. It stays his, and any neighbor with 2+ soldiers can walk
  in without a battle.
- **Retire and release.** A soldier with no seasons left retires and his territory calls up a
  replacement. One whose best remaining season is under `release_below` (1.0 WAR) can be released
  for a call-up.
- **The end.** You choose the length at the start (`[lengths.*]` in rules.toml):
  - **15 rounds.**
  - **9 innings:** at least 4 call-ups or 1 per 2 territories, and AI managers fight up to 9
    battles per turn, so there's about as much action as 15 rounds.
  - **No limit:** until one manager holds every territory.

  At the end: 1 point per territory plus held regions' bonuses. Ties are broken by the remaining
  strength on the board. "End game now" scores any game. Games save as you play; "Save a copy"
  keeps up to 8 named copies (Saves to load).
- **What you see.** Each manager's territories, region points and players on the board. For every
  soldier and bench player: seasons left, and the median, total, best and worst WAR of those seasons.
- **Autorank.** Settings let the game pick your defender (by default) and/or your attacker.
  - *Smart*: the cheapest player who is at least even against the other side's stack.
  - *Best*: your strongest.
  - *Weakest*: save your stars.

  "Place them for me" and "Play my turn for me" use the AI.

## Files

- `territories.toml`: the map. 43 territories; each lists its birthplaces (Lahman states and
  countries; California split at 35.8°N, Pennsylvania at 77.5°W), its region, land borders and sea
  lanes, and its map position. North and South Carolina are separate. 8 regions with bonuses:
  - Pacific West +3
  - Plains & Prairies +4
  - Southwest +2
  - Great Lakes +4
  - Northeast +5
  - Upper South +3
  - Deep South +4
  - Caribbean +2

  Each region is drawn as a shaded area on the map. Edit freely; the build checks the map,
  including that every region is one connected piece.
- `rules.toml`: every rule number.
- `build.py` (`python -m ballmonitor.games.home_turf.build`) writes `web/data/game.json`. It holds
  rosters of the 60 best natives per territory by career Open WAR (`models/open_war`), with every
  season. The rosters are stored compactly: name, birth year, and seasons as a start year plus year
  gaps with WAR in tenths. `engine.js` `prepare()` expands them on load. That's 257 KB (74 KB as
  downloaded), half the plain form, with the same players and seasons. The build needs Open WAR's
  `data/seasons.csv`, which is local only (`ballmonitor fetch open_war`).
- `web/engine.js`: the rules and the AI (pure; node tests in `tests/test_home_turf.py`).
- `web/game.js`: the page. The game is saved in the browser (localStorage `bm.hometurf.v1`).

## What the play-tests showed (AI-only games under node)

| rules | winner's share of the map | games won by conquest | finishes within 5 pts | battles per game |
|---|---|---|---|---|
| 8 opening call-ups, 12 AI battles/turn, aggression 1.35 | 65% | 6 of 60 | 9 of 60 | 312 |
| home field 1.0 instead of 0.5 | 56% | 2 | 18 | 318 |
| **16 opening, 6 AI battles/turn, aggression 1.6 (current)** | 49% | 0 | 18 | 288 |

- About 36% of battles are won by the side with the lower chance, so stars usually win but not
  always.
- With thin opening stacks the game snowballed; the current numbers fixed most of that.
- Soldiers rarely run out of seasons before they lose, so retirement call-ups are rare. Releases
  happen a few times a game.
- First pick won 20 of 60 games on the old 12-region map. With the 8 connected regions, the third
  pick won 98 of 200 games and the fourth 17. The third pick always opened with New York and took
  the whole Northeast (+5), because the AI never broke into a region a rival had started. The AI
  draft now blocks: a territory in a region one rival is filling up alone is worth
  `ai.draft_block` (6) × the rival's share × the bonus. Over 400 games the four draft positions
  then won 112, 95, 82 and 111 (blocking 3: 75% more wins for the third pick; 5 and 8 were less
  even).

Game lengths (60 AI-only games each, current rules):

| length | battles | captures | winner's share | within 5 pts | round-3 leader won |
|---|---|---|---|---|---|
| 15 rounds | 290 | 66 | 49% | 21 | 35 |
| 9 innings, 15-round pacing | 185 | 43 | 42% | 24 | 36 |
| **9 innings (current: more call-ups and AI battles)** | 257 | 73 | 49% | 20 | 39 |
| no limit, stopped after 60 rounds (30 games) | 824 | 143 | 87% | 0 | 16 |

A no-limit game rarely ends by conquest (3 of 30 by round 60), hence "End game now".

Season filters: dropping seasons under 10 PA and 2 IP would remove only 6% of Open WAR's rows
(8.5 → 8.0 MB) and 1.5% of the game's seasons. Not worth changing who gets which seasons; the
compact format halved the file instead.

## Fixes from a review (2026-11-22)

All verified before fixing; the node tests cover the engine ones.
- **Battle card color.** It was inverted when an attack won without capturing.
- **Reload mid-capture.** Reloading during a capture locked the game; the move-in dialog now comes
  back.
- **Five exact ties went to the attacker**, through float sums like −0.4 + 0.5.
- **A defender winning on his last season** (empty bench) handed his territory to the attacker who
  had lost. Such territories are now empty and can be walked into.
- **Starting or loading a game during an AI turn** let the old turn keep playing; a run counter
  stops it.
- **Disabled buttons, safe storage, wording.**
  - "Moved this turn" is now disabled.
  - Browser storage failures are caught.
  - Wording fixed: "You attack" vs "The Scout attacks", "1 territory", and the 9-inning numbers in
    How to play.

Improvements:
- **Inspect first.** A first click shows a territory's soldiers and bench; draft or call up with
  the button, or a second click.
- **Defend dialog.** It is skipped when you have one defender.
- **Strength badges.** Each territory shows a small badge with its soldiers' combined median WAR,
  and a tooltip lists them.
- **Labels and border.** Labels sit on top of every line. The Mexico–Venezuela border curves below
  the islands (`bend` in territories.toml).
- **Faster redraws.** The map is built once and updated in place; fortify targets come from a single
  search.
- **Dialogs.** Optional ones close with Esc or a click outside; required ones (moving in, picking a
  defender) don't.
- **Phones.** Tables scroll inside their panel; less essential columns hide under 560 px. Dialog
  buttons stay pinned at the bottom.
- **Smaller saves.** Players knocked out keep only their name.

Not done (it changes the balance, so it needs its own simulation round): weighting the "Smart"
pick toward the opponent's likelier soldiers, and AI call-ups that aim at region bonuses.

## Ideas not done yet

- Human opponents (27K's multiplayer server).
- A daily seeded game.
- Lineup battles (3 against 2).
- A batter-against-pitcher platoon edge.
- Showing the opponents' picks over time.
- A limit on a person's battles per turn (the AI has one).
- Sound and animation.
