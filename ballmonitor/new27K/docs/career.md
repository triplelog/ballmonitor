# Career mode

Built: see the README's Career section. This page keeps the design and what's still to come.

One pitcher, from a 12-year-old in the Youth World Tournament to the big
leagues, pitching for different teams and learning pitches along the way.

## The path

| Age | Level | What happens |
| --- | --- | --- |
| 12 | Youth | You pitch for your home region (a state or a country) in the 128-team World Tournament: 3 to 8 games. |
| 14–17 | High school | Four seasons for your hometown school (one of your state's 16 cities): 30 games and the state tournament each year. Scouts start to show up. |
| 18 | Decision | **College offers** (from the conferences, based on your stats, velocity and region) or the **pro draft** (a round, based on the same). |
| 18–21 | College | Up to four seasons; draft-eligible after the third. Regionals and the College World Series are your showcase. |
| 21+ | Pro | Draft, then (optionally) minor-league levels before the majors; contracts, trades and free agency move you between teams; aging and retirement; a Hall of Fame score. |

## How a season plays

- You're a player, not the manager: the season engine sims every game, and stops when **your pitcher is used**:
  - **starter**: you pitch from the first pitch, in your turn in the rotation (rest rules decide when);
  - **reliever**: the computer manager calls you in mid-game; you take over at that moment.
- You stay in until the manager pulls you (fatigue, pitch count, how it's going; a formula) or the game ends; the rest is simmed and you see the result.
- Everything else (standings, brackets, leaders) is the existing season hub, centred on your pitcher.

## Getting better

- **XP** from each outing (outs, strikeouts, wins, big games), via a formula.
- **Spend it** on ratings per pitch (velocity, movement, control), stamina, and **new pitches**: changeup from youth, curveball and slider in high school, splitter, cutter and sweeper later, knuckleball and eephus as rare unlocks.
- **Bullpen sessions** between starts: a short aiming drill on the moving zone (hit the targets) that earns training XP. Skill at the core mechanic makes you better, not just grinding.
- **Growth and aging**: natural velocity gains through the teens, a peak around 27–30, then decline.
- **Arm health**: high effort and big pitch counts (the sliders you already use) add strain; strain raises injury risk. It makes the effort sliders a real decision across a career, not just a pitch.

## Moving up

Ratings are relative to each level, so a career player keeps an absolute rating and is converted with each level's `ratingShift` (a high-school 70 is roughly a college 59). Your pitcher is added to a generated team at each level.

## Formulas to add (all editable in the Formula Lab)

`xpForOuting`, `growth` (by age), `pitchUnlockCost`, `armStrain`, `injuryChance`, `managerHook` (when you come out), `scoutInterest` (offers), `draftRound`.

## Engine and app work

- A "player mode" for seasons: sim until your pitcher appears, hand over control mid-game, sim the rest.
- A career save that outlives a season, in **IndexedDB** rather than localStorage (a college season alone is about 1.2 MB, and a career keeps every year's summary).
- Screens: create a pitcher, the career hub (age, ratings, arm health, pitches, offers), training, a year-by-year record.
- Later: minor-league levels, contracts, career achievements, and career pitchers facing each other in multiplayer.

## Still to come

Done: youth → high school → college → pro as a starter; play-mode options and sim controls; XP, training and pitch unlocks; growth and aging; college offers, the draft, free agency; a Hall of Fame score.

Next:
1. Relief roles (the manager calling him in mid-game) and bullpen-session training drills.
2. Arm health and injuries (strain from high effort and pitch counts).
3. Minor leagues, contracts and trades, career achievements; international hometowns.
