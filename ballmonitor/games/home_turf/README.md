# Home Turf (play-test version)

A strategy game on a map of where big-leaguers were born. Four managers (you and three AI) draft
40 territories in 7 regions. Each territory's soldiers are real players born there, called up best first,
with their seasons from 1901 on (`min_year`). Battles
are fought with their real seasons. On the site at ballmonitor.com/hometurf/ (the build copies `web/`);
locally `ballmonitor serve`, then `/hometurf/`.

## Rules (rules.toml has every number)

- **Draft.** The managers draft every territory, 10 each. The order is random, then rotates: 1 2 3 4,
  2 3 4 1, 3 4 1 2, 4 1 2 3, ... (no back-to-back picks). Each territory comes with its best native.
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
  - **9 innings** (the default): at least 4 call-ups or 1 per 2 territories, and AI managers fight
    up to 9 battles per turn, so there's about as much action as the old 15 rounds.
  - **Doubleheader (18 innings):** the base pacing (at least 3 call-ups, up to 6 AI battles).
  - **No limit:** until one manager holds every territory.

  Saves from before these lengths keep their 15 rounds (`max_rounds` in rules.toml).
- **AI ability.** Also chosen at the start (`[levels.*]`: a pick strategy and `[ai]` overrides
  for the AI seats):
  - **Rookie:** attacks recklessly with a random player, ignores regions, drafts loosely.
  - **Pro:** picks players well but doesn't play for regions, drafts loosely.
  - **All-Star** (the default): the AI below.
  - **Hall of Fame:** All-Star, but picks its battles (5 a turn, at better odds) and drafts for
    itself instead of blocking rivals.

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

- `territories.toml`: the map. 40 territories; each lists its birthplaces (Lahman states and
  countries), its region, the territories it borders (land or sea, all drawn as solid lines) and its
  map position. One California, one Pennsylvania; Massachusetts with Connecticut and Rhode Island
  (S. New England); North and South Carolina are
  separate. 7 regions with bonuses:
  - West +3 (with the Desert Southwest and the Pacific Rim)
  - Plains & Prairies +4 (with Canada and Oklahoma)
  - Great Lakes +3
  - Northeast +3 (with the Old World)
  - Upper South +3
  - South +6 (with Texas)
  - Latin America +3 (Mexico & Central America, the Caribbean, Venezuela)

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

## AI tournaments (2026-11-22)

Each candidate behavior played in 2 of the 4 seats against the current AI in the other 2, over the
same game seeds (seats rotating). 50% means no better; the ± is the 95% margin.

| behavior (rules.toml `[ai]`) | its seats won |
|---|---|
| control | 50.2% ± 4.9 (400 games) |
| "Smart" assumes their stronger soldiers likelier (`smart_model = "weighted"`) | 46.5% ± 4.9 |
| "Smart" predicts their pick (`"predict"`) | 47.8% ± 4.9 |
| call-ups aim at regions (`place_region` 1 / 3) | 52.3% / 51.2% ± 4.9 |
| attacks aim at regions (`attack_region` 3 / 5 / 8 / 12) | 55.5% / 55.0% / 55.9% / 57.4% ± 3.4 (800) |
| attacks 8 + call-ups 1 | 57.6% ± 2.4 (1,600) |

**Adopted:** `attack_region = 8` and `place_region = 1`. A territory's region value (`regionStake`)
counts:
- completing one of my regions: bonus ÷ territories still missing, if 2 or fewer are missing
- breaking a rival's whole region: half its bonus
- holding a whole region of mine: its bonus

Attacks multiply their odds by 1 + 8 × value ÷ 10. Call-ups add it for threatened territories in a
held region, and next to the territories that would complete one.

"Smart" stays `average`; the smarter guesses were no better.

**Fairness.** With the stronger AI in every seat, the snake draft's end picks won far more:
116/75/74/135 of 400. The 3-territory Southwest was the culprit: easy to take whole and hold.
Oklahoma moved to the Southwest, with Southwest and Plains both +3. That gives 205/205/171/219 of
800 (chi² 6.3, within chance).

**The 40-territory map (2026-11-22).** One California and one Pennsylvania; Massachusetts,
Connecticut and Rhode Island as S. New England; Desert Southwest to the West, Texas to the South
(+6), Oklahoma to the Plains, Mexico to Latin America; seasons from 1901 on. Wins by draft
position, AI in every seat, 9 innings, 800 games each:

| map, draft and AI | wins by draft position | chi² |
|---|---|---|
| 39 territories (one New England), snake | 136 / 164 / 200 / 300 | 77 |
| 39, rotating draft | 103 / 291 / 193 / 213 | 90 |
| 40, snake | 158 / 155 / 210 / 277 | 49 |
| 40, rotating draft | 155 / 264 / 167 / 214 | 37 |
| 40, rotating, AI draft noise 2 / 3 | 149 / 269 / 196 / 186, 162 / 262 / 197 / 179 | 38, 29 |
| **40, rotating, AI draft noise 4 (adopted)**, three seed sets | 175 / 219 / 222 / 184, 147 / 236 / 231 / 186, 168 / 233 / 215 / 184 | 8.6, 26, 13 |
| 40, snake, AI draft noise 4, three seed sets | 182 / 189 / 206 / 223, 163 / 168 / 220 / 249, 165 / 191 / 208 / 236 | 5.1, 26, 13 |

- With 39 territories one manager drafts 9 and the rest 10.
- In a snake draft the ends (positions 1 and 4) get two picks in a row and can take two of a
  region before anyone blocks. The rotating draft (1234, 2341, 3412, 4123, ...) has none.
- Balanced-looking orders were worse. With 1234 3412 ... every position's picks add up to the
  same, but position 3 gets picks 3 and 5 and won 43%; others 22–56%. Whoever has pick 5 soon
  after an early pick does best.
- The deeper cause was the AI's draft. With `draft_noise` 0.8 it drafted Texas, Alabama, California,
  Pennsylvania, New York in that order every game, so one draft pattern decided the positions. At 4
  the drafts vary and both orders are much fairer. The AI loses almost nothing: noise 2 / 3 / 4 in
  two seats against 0.8 won 49.4% / 48.0% / 47.0% (± 3.5).
- Draft position still matters some: 18–29% instead of 25%. Doubleheader: 83/115/110/92 of 400
  (chi² 6.8).
- Also tried and dropped: letting the last drafter lead off each round, and extra opening call-ups
  for the manager who drafts fewer.

Regions held at the end (800 games): Great Lakes 143, West 123, Upper South 125, Northeast 121,
Latin America 83, Plains 79, South 44. The two big regions (7 and 8 territories) are the hardest to
hold whole.

**The old AI against the new**, same map: 43.8% ± 2.8 (1,200 games).

**Pacing**, current rules, 60 games each:

| length | battles | captures | winner's share of the map | within 5 points | round-3 leader won |
|---|---|---|---|---|---|
| 15 rounds | 274 | 90 | 49% | 14 | 32 |
| 9 innings | 242 | 85 | 47% | 13 | 42 |

**Doubleheader pacing**, 60 games each:

| 18 innings with | battles | captures | winner's share | within 5 points | round-3 leader won |
|---|---|---|---|---|---|
| **the base pacing (adopted)** | 320 | 105 | 52% | 18 | 32 |
| the 9-inning pacing | 441 | 150 | 63% | 8 | 33 |
| the 9-inning call-ups only | 385 | 86 | 47% | 18 | 37 |

The base pacing gives the most comebacks and close games; the 9-inning pacing snowballs.

## AI levels (2026-11-22)

Each level played in 2 seats against All-Star in the other 2 (9 innings, rotating seats, same
seeds, 800 games, 40-territory map; ± is the 95% margin):

| level | its seats won |
|---|---|
| Rookie | 35.0% ± 3.3 |
| Pro | 42.5% ± 3.4 |
| All-Star | 49.6% ± 3.5 |
| Hall of Fame | 68.8% ± 3.2 |

What moves the needle (each change in 2 seats against All-Star):

| change | won |
|---|---|
| no draft blocking (first map) | 71.0% |
| fewer battles: at most 5 a turn, attack at 2.0× the defender (not 9 at 1.45×) | 60.9% |
| the same, without region play | 60.6% |
| no region play, loose draft and call-ups | 42.5–47.3% |
| reckless: up to 12 battles at 1.2× | 32.9% (smart picks), 35.0% (random) |
| random picks (first map) | 45.5% |

- **Draft blocking** (`draft_block`) takes territories a rival needs for a region. It was added to
  even out the draft positions, but head to head it costs a lot. Hall of Fame drops it.
- **The 9-inning pacing** (up to 9 battles a turn at 1.45×) keeps games lively, but it makes the AI
  overextend. A manager who picks his battles beats it. Hall of Fame does that; Rookie goes the
  other way.

## Ideas not done yet

- Human opponents (27K's multiplayer server).
- A daily seeded game.
- Lineup battles (3 against 2).
- A batter-against-pitcher platoon edge.
- Showing the opponents' picks over time.
- A limit on a person's battles per turn (the AI has one).
- Sound and animation.
