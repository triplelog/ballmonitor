# Store page material

Candidates for the itch.io page (and any other store). Made from the game
itself on 2026-11-12; retake them when the look changes.

## Cover (itch.io: 630 × 500; these are 1260 × 1000)

| File | What | |
| --- | --- | --- |
| `cover-a.png` | The ballpark, the zone with a curveball's break drawn on it, the logo over the crowd. | **Suggested.** Shows what you do in the game at a glance, and the logo reads at thumbnail size. |
| `cover-b.png` | A strikeout on the corner, closer in. | More action, but busier when small. |
| `cover-c.png` | The logo on dark green, 27 dots for 27 outs. | Cleanest at tiny sizes; says least about the game. |

The source is `cover.html` (`?v=a`, `b` or `c`): it draws the field with
the game's own code, so a change to the field shows up in a re-render.
Serve this folder's parent (`python3 -m http.server 8131` in the game
folder) and screenshot `http://localhost:8131/docs/store/cover.html?v=a`
at 630 × 500, device scale 2, with headless Chrome.

## Screenshots (1280 × 800)

In the order to show them (itch shows the first three or four without scrolling):

1. `02-strikeout.png`: the payoff: the banner, the at-bat's pitches on the zone, achievements popping.
2. `01-aiming.png`: the core move: the zone, the break guide, the heat map.
3. `03-catchers-visit.png`: the catcher's advice (depth, and a friendly way in for people who don't know pitching).
4. `06-season.png`: a college season's bracket (there is a long game here).
5. `05-formula-lab.png`: every rule is a formula you can change (what no other baseball game has).
6. `04-challenges.png`: challenges and achievements.
7. `07-career.png`: the career screen. The weakest of the set: it's a 12-year-old's first season. Retake it from a career a few seasons in.

A short GIF or video of one at-bat (pick, aim, throw, strikeout) would do
more than any still; itch plays a GIF as the cover when you hover.

## Short description

itch.io's "short description or tagline" shows under the title in search
and on cards. Keep it under about 80 characters, say what the player
*does*, and use the word people search for (baseball, pitching).

- **Suggested:** *A baseball pitching game: pick your pitch, read the moving zone, paint the corners.*
- *You're the pitcher. 27 outs to get. Every pitch is yours to call.*
- *Baseball from the mound: outthink hitters one pitch at a time.*

For the page body, lead with one sentence and a GIF, then short bullets:
what you do each pitch; the modes (Quick Game, Challenges, Season,
Career); the Formula Lab; "free, no ads, plays in the browser, on phones
too". Tags: `baseball`, `sports`, `simulation`, `strategy`,
`singleplayer`, `browser`, `mobile-friendly`. Genre: Sports.
