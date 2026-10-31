# 27K

A browser pitching game. Choose a pitch and how hard to throw it. The strike zone wanders while you aim, and you click where to aim it. The ball breaks from there and scatters by your control. Every rule (swing chance, contact, umpire, zone chaos, fatigue, base running…) is a [MathZetta](../../mathzetta) formula that you can replace.

It is a rewrite of the 2018 iOS prototype in `../27K`, with no code shared.

## Run

```bash
npm run serve      # http://localhost:8027/ (ES modules need http); also the multiplayer server
npm test           # rules, pitch movement and the catcher's advice, multiplayer, a 300-game sim, every challenge, a season in each format, nine career seasons
npm run sim -- 500 7 my-formulas.json   # games, seed, optional formula overrides
npm run build      # static copy of the game in dist/ (see Static hosting)
```

### Static hosting

With Multiplayer switched off, the game needs no server: everything runs in the browser and saves to localStorage and IndexedDB. `npm run build` (after `npm install`; `tools/build-static.js`) writes `dist/`: the page, styles and sources, plus only the MathZetta files the game loads (it follows the imports from the import map's entry points, about 23 files and 180 KB, into `lib/mathzetta/`) with the import map pointed there. Upload `dist/` as-is to any static host (GitHub Pages, Netlify, Cloudflare Pages, a plain web server), at the root of a domain or in a subfolder; the addresses are relative. It has to be served over http(s), not opened as a file. Saves belong to the address, so games from `localhost:8027` don't carry over. Multiplayer, when it returns, needs `tools/serve.js` (or the Dockerfile).

No dependencies. Plain ES modules, canvas and localStorage.

## Playing

Quick Game and Challenges & Achievements are open. Season, Career and Multiplayer are built (and still tested) but show as *coming later* on the menu: their screens go back to the menu, and a saved season or career game isn't offered under Continue.

- **Quick Game:** pick your team, opponent, home/away, innings and difficulty, set your lineup card (batting order, bench swaps, starting pitcher), and play.
- **Pitching:** use 1–9 or the buttons to pick a pitch and set the velocity and movement effort sliders, then press Space to start the zone moving and click to throw. The zone first jumps to a new spot (at least half its drift range away, in a random direction), so you can't throw before it has moved. Before you press Space, the dashed guide shows how the pitch will break from the pointer (or the middle of the zone), with a ring for one standard deviation of scatter. The **break guide** setting keeps it while the zone moves (*always shown*) or takes it away once the zone starts moving (*hidden*), so you have to remember the break.
- **Phones and tablets:** the score bar stays pinned at the top, and the pitch buttons and Pitch button sit right under the field. Tap the field (or Pitch) to start the zone; then put a finger down to aim, drag to adjust (the break guide follows), and lift to throw. Sideways, the field is on the left and the pitching controls on the right.
- **Movement:** break is real-world in direction. A right-hander's arm side is the third-base side, where a right-handed batter stands (screen left), so his slider, sweeper, cutter and curve break right, away from a righty, and his changeup, sinker and two-seamer fade left, in on him; a lefty is the mirror image.
- **Keys:** every pitch has its own letter, shown on its button (F four-seam, S slider or sinker, C changeup or curve, and so on; never two the same in one arsenal); 1–9 work too.
- **Pitch clock** (in Quick Game setup or under the field): starts when you press Pitch, runs from the end of the last pitch, or off; 20 seconds by default (5 to 60). Like a stadium clock it appears on the field only for its last 10 seconds. If it runs out, the pitch is a ball. The length is the `pitchClock` formula, `clockSetting` by default (Pitch Clock Panic sets 3.5).
- **Catcher calls pitches** (*Pitch calling* in setup, or *Catcher calls pitches* under the field; off by default): before each pitch the catcher (`callPitch` in `src/engine/advice.js`) picks the pitch and a spot from the same run-value scores as the mound visit, so the batter, the count and what he has already seen this at-bat (the formulas' `pitchSeen`, `sameAsLast`, `veloDiff`, `locDiff`) all count. He mixes it up rather than always calling the single best option. The pitch is selected for you and the spot is ringed on the zone, labelled with the pitch; your job is to hit it (the break guide shows where it will end up). *Shake off* asks for a different pitch; picking a pitch yourself has him set up a spot for it. After the pitch, the banner says how far it ended from the spot.
- **Catcher's visit** (once an inning, button under Pitch): calls time, stops the clock and resets it (and the zone) for when he goes back. The catcher (`src/engine/advice.js`) scores every pitch you have at every spot with the game's own formulas (swing, umpire, contact, hits), averaged over your scatter plus a little aiming error, in runs for the current count. He gives his two best plans (pitch, spot, strike/whiff/ball/hit chances, why it works, where to aim so it breaks into the spot), the mistake to avoid, and notes on the hitter: hot and cold zones, pitch types, eye, power, platoon, what he has seen this at-bat, and your fatigue. *Throw it* selects that pitch and marks the spot on the zone for the next pitch.
- **Scouting:** the batter card shows how he has hit each pitch type (PA, AVG, OPS, K%, whiff rate) against the league, with the pitcher's own pitches first. Every league starts with a simulated past season, and every game adds to it. Batters have their own strengths against particular pitch types (`typeSkill`, added to `vsPitch`). The Lineup tab shows each hitter's ratings and best and worst pitch; click one for his full report.
- **Your offense** is simmed. By default the whole half-inning runs automatically, showing each batter's last pitch, with the count, outs, runners and score updating after each one. Turn off *Sim our half-innings automatically* (on the batting panel, or *When you bat* in setup) to manage each batter: pinch hit, sim one batter (shown pitch by pitch), or sim the rest of the inning.
- **Bullpen:** bring in a reliever between pitches. Fatigue lowers velocity and break and raises scatter and zone speed.
- The game saves after every pitch; **Continue** on the menu resumes it.

## Layout

| Path | What |
| --- | --- |
| `src/engine/formulas.js` | Every formula with its default text, plus every variable formulas may use (with descriptions and sample values). `createFormulas(overrides)` compiles them once; `F.eval(id, scope)` never throws, and a broken formula falls back to its default. |
| `src/engine/game.js` | Game state (plain JSON) and `throwPitch()`, the single path every pitch takes, plus base running, innings, walk-offs, box score, pitching changes and pinch hitting. |
| `src/engine/pitch.js` | Pitch shape (velocity, break, scatter), where it lands, distance to the zone edge, heat-map lookup. |
| `src/engine/ai.js` | Computer pitch selection, aiming and bullpen use. |
| `src/engine/advice.js` | The catcher's visit: every pitch and spot scored in runs with the formulas, plus scouting notes. |
| `src/engine/zone.js` | The wandering strike zone. |
| `src/engine/league.js`, `data.js` | Teams, players, ratings, heat maps, pitch types. |
| `src/ui/` | Screens (menu, setup, lineup, game) and the canvas view. |
| `node_modules/mathzetta` | MathZetta, linked from `../../mathzetta` by `npm install` (the page maps it with an import map). |
| `src/engine/tracker.js`, `achievements.js`, `challenges.js` | Your pitching stats per game/inning/at-bat, the achievements read from them, and challenge setups and goals. |
| `src/engine/levels.js`, `season.js`, `competition.js`, `regions.js` | Levels of play; seasons (rest, stats, leaders); the stage engine and the four formats (pools, leagues, brackets, series); places and name pools. |
| `src/engine/simStats.js` | Headless computer-vs-computer games and league stats (used by the sim and the lab). |
| `src/engine/career.js`, `src/ui/careerScreens.js`, `src/ui/idb.js` | Career mode: the pitcher, his seasons and starts, XP and training, offers, the draft, free agency; saved in IndexedDB. |
| `server/mp.js`, `tools/serve.js` | The server: static files plus the multiplayer API (games, seats, turns, time limits). |
| `test/` | `rules.js` (situations with forced outcomes), `advice.js` (break directions, the catcher's plans), `sim.js` (league stats vs MLB), `challenges.js` (every challenge, played by the computer). |

Coordinates are inches, laid out as on the field view: +x toward first base (a right-handed batter stands at −x, a lefty at +x), +y up, with (0, 0) at the centre of the zone.

The field is seen from behind the plate: a right-handed batter on the left, pitches coming toward you. The batter is posed in 3D (his own inches: toward the plate, up, toward the mound) and drawn side-on, his back half to you, feet and shoulders lined up parallel to the plate's edge, with key poses for the stance, stride, contact, extension and finish; the bat starts back over his near shoulder and swings out toward the mound (`src/ui/plate.js`).

## Seasons

*Coming later (not on the menu yet).* Menu → **Season**. Each level has its own format (`src/engine/competition.js`):

| Level | Format |
| --- | --- |
| Youth (6 inn.) | **World Tournament**: 128 teams, 64 US (states, big states split, DC and territories) and 64 international (countries and regions, with rosters named to match). 32 pools of four play a round robin; the 16 US and 16 international pool winners play down to a US and an international champion, who meet for the World Championship. |
| High school (7 inn.) | Pick a **state**: its 16 biggest cities each send a school. Home and away against everyone (30 games), then an eight-team state tournament. |
| College (9 inn.) | **8 regional conferences of 8**, schools named for their states. 50 games (29 non-conference, then a three-game series with each conference rival); conference champions and the 24 best other records make **8 four-team regionals**; regional winners go to the **College World Series** (two pools of four, then a best-of-three final). |
| Pro (9 inn.) | Twelve teams, 30, 60 or 162 games; top four play best-of-five semifinals and a best-of-seven Championship Series. |

Ratings are relative to the level (about 50 is average there), and pitches are slower at lower levels (`levelVelo`), so the same formulas work everywhere. Pitchers need rest after they throw (`restDays` formula) and come out at the `pitchLimit`. The hub shows your next game (play it, sim it, sim a week or to the end, with series scores), your schedule, scores around the league, every stage's standings (pools, conference tables, brackets), your roster with season stats and who is resting, and league leaders.

`node test/season.js` sims a whole season in each format and checks the structure (game counts, pools, series lengths, a champion) and that the books balance.

## Career

*Coming later (not on the menu yet).* Menu → **Career**. One pitcher, from 12 years old to retirement; you control only him.

- **Create him**: name, hand, a style (power, finesse or movement: starting ratings and first two pitches), and a hometown (any of the 16 biggest cities in a state). At 12 he pitches for his region in the Youth World Tournament, then four seasons for his hometown high school.
- **Each season** sims until his turn in the rotation. Choose how many starts you pitch yourself: every start, every other one (plus the postseason), key starts (the opener, every 4th, and the postseason), or none. Change it any time; the rest are simmed. Between starts: *Sim to his next start*, *Sim to the next start you pitch*, *Sim the rest of the season*.
- **On the mound** you pitch until the manager comes to get the ball (the `careerHook` formula: fatigue, runners, runs allowed, pitch limits); your team's at-bats and the rest of the game are simmed.
- **Getting better**: each outing earns XP (`xpForOuting`). Spend it on any pitch's velocity, movement or control, or on stamina (`trainingCost`, steeper past 70), or on a new pitch once he's old enough (`pitchCost`; curveball at 14, slider 15, splitter 17…). Every off-season he grows (or, after 32, fades) by the `growth` formula.
- **Moving on**: after high school, scholarship offers from four colleges (home region keener) or the pro draft (projected by a scout score); after three college years, declare or stay a fourth; in the pros, free agency each winter (re-sign, two other teams, or retire), and a Hall of Fame score at the end.
- Ratings are kept on the pro scale and shifted to each level (a 40 is a strong 12-year-old). Careers are saved in IndexedDB; a start in progress resumes from the menu.

`node test/career.js` plays a whole career by simulation (youth to retirement, spending XP); `npm test` runs the first nine seasons. Ideas for later are in [docs/career.md](docs/career.md).

## Multiplayer

*Coming later (not on the menu yet).* Menu → **Multiplayer**. Two people play one game and take turns: the home player pitches the top of every inning, the away player the bottom, and each side's hitters bat against the other player's pitching.

- **Start a game**: choose the level, innings, a **time limit per half** (none, 2 minutes up to 3 days), your side, and standard or your custom formulas. You get a six-letter code and an invite link (`#join=CODE`); the game starts when someone joins. Tick *Both players on this device* to take turns at one screen.
- **Your games** in the lobby shows every game you're in: score, inning, whose turn it is and how long is left, refreshed every few seconds. The menu shows how many games are waiting on you, the tab title shows *(n) Your turn*, and you can turn on a browser notification for when your turn comes.
- **Managing**: before your team bats, you get a short turn to set it up: the full lineup card before its first at-bat (order, positions, bench swaps), and after that substitutions and pinch hitters, with each hitter's OPS against the pitch types of the pitcher he'll face. The order of turns is: away manages, home pitches the top, home manages, away pitches the bottom, and so on. You can turn this off when creating a game.
- **Pitching your half**: the server decides every pitch from your inputs, so you can stop and come back at any point. When your half ends the other player is up; while you wait, the page watches their progress and hands you the ball when they finish.
- **Time limit**: if your half's time runs out, the computer pitches the rest of it (noted in the play-by-play) and the turn passes on.
- Resign (or cancel an unjoined game) from the lobby.

The server keeps games in `data/mp/` and listens on your network; it prints the address to share (other people can't use your `localhost`). The server is the referee: browsers send only inputs, it rolls the dice with a random state they never see, and it checks every move. To host games for other people (Tailscale, a tunnel, or a small server with Docker and Caddy for HTTPS) and for what is and isn't protected against cheating, see [docs/hosting.md](docs/hosting.md).

`node test/mp.js` checks the multiplayer rules without a browser.

## Formula Lab

Menu → **Formula Lab**. Every formula in the game, grouped and described:

- Edit the text with live checking; MathZetta shows it typeset and read aloud.
- **Try it**: sliders for the variables the formula uses, your draft vs the default.
- **Graph** the formula against any variable (draft, saved and default curves; hover to read values).
- **League impact**: simulate 100–1000 computer-vs-computer games with your rules and compare 19 stats with the defaults and MLB.
- A warning if a formula uses a variable that isn't known yet when it runs (e.g. `edge` in zone speed).
- **Presets** (Arcade, Chaos zone, Robot umpire, Generous umpire, Dead-ball era, Three true outcomes), **export** as JSON or a share link (`#formulas=…`), **import**.

Saved formulas apply at once, including to a game in progress, and live in `localStorage['new27k.formulas']`.
Formulas can use `+ - * / ^`, `min`, `max`, `abs`, `sqrt`, `exp`, `ln`, `floor`, `random()`, comparisons, `and`/`or`, and `if … then … else …`.

## Challenges and achievements

Menu → **Challenges & Achievements**.

**16 challenges** (`src/engine/challenges.js`), each a set situation with a goal and 1–3 stars. You pitch for your Quick Game team against the league's best lineup, with the standard formulas (challenges ignore your custom rules so stars are comparable):

- *Quick:* Close It Out, Full Count Bases Loaded, Running on Fumes, Slow and Low (eephus + palmball), Three Up Three Down, Heart of the Order, Knuckleball Only, Pitch Clock Panic (3.5 s clock), Strike Out the Side, Houdini (bases loaded, nobody out), Chaos Zone, Immaculate Inning.
- *Medium* (your offense simmed automatically): The Gauntlet (5 K in the first 9 batters), Strikeout Sprint, Perfect Three.
- *Epic:* **27 Strikeouts**: only strikeouts make outs (a caught ball is just a strike, even strike three), so every out is a K; win the game.

**26 achievements** (`src/engine/achievements.js`) unlock in any game you pitch, at-bat feats (Thank the Catcher, Painted the Corner, Triple Digits, Back from 3-0, Buzzer Beater…), inning feats (1-2-3, Struck Out the Side, Immaculate Inning, Houdini, Heart of the Order…) and game feats (10/15/20 K, Six Straight, Golden Sombrero, Complete Game, Maddux, No-Hitter, Perfect Game, and a true 27K under normal rules). Strikeout feats don't count in the 27 Strikeouts mode.

`node test/challenges.js 300 [hunter|ai]` plays every challenge with a computer pitcher to check they finish and how hard they are; `hunter` aims like a skilled player chasing strikeouts.

## Defaults

With the default formulas, computer-vs-computer play comes out close to MLB rates: about 4.4 runs a game, .240/.316/.385, 23% K, 9% BB and a .290 BABIP.
