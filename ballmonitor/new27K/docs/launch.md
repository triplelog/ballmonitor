# Launching 27K

The plan agreed on 2026-11-12, and where each step stands. Hosting the
multiplayer server itself is in [hosting.md](hosting.md).

## What is free and what is paid

- **Free, everywhere:** every single-player mode (Quick Game, Challenges &
  Achievements, Season, Career, Formula Lab). It runs in the browser and
  costs nothing to host.
- **Free:** the daily challenge and its leaderboard, and every style
  option (team name and colours, your pitcher's name and number, field
  themes).
- **Free multiplayer:** two active games at a time for everyone.
- **27K Premium (one payment, about $5):** up to 100 active games, and the
  right to *host* the bigger things. Only the host needs Premium; whoever
  they invite plays free.
- **Support 27K:** a link to the itch.io page (pay what you want) on the
  menu, on itch and on ballmonitor.com.

Nothing that makes you a better pitcher is ever sold.

## Where it lives

- **ballmonitor.com/27k/**: our own copy (`ballmonitor build-site` copies
  `dist/`). Not an embed of itch's player.
- **itch.io**: the same build, uploaded as an HTML game (`npm run itch`).
- Saves belong to each address until players can sign in.
- Later: other web portals; Steam as a wrapped desktop build.

## Steps

1. **Single-player on itch.io.** Ready to upload; see the checklist below.
2. **The multiplayer server online, for friends.** `server/mp.js` plays
   two-player games by alternating half-innings, with the server as
   referee. Done (2026-11-12): the server's address and the invite page
   are settings of each build (`MP_SERVER`, `INVITE_PAGE`), the server
   lets listed sites use it (`ALLOW_ORIGINS`), Multiplayer appears on the
   menu only when a server answers, and games untouched for a month are
   deleted. See hosting.md, *One server, several copies of the game*.
   **Still to do (needs the owner):** rent the small server, point a name
   at it (e.g. `27k.ballmonitor.com`), run it behind HTTPS (hosting.md,
   option 2), then rebuild the static copies with `MP_SERVER` set.
3. **Accounts and the unlock.** "Log in with itch.io" (OAuth with PKCE) as
   the player account in place of the per-browser id; the server asks
   itch whether that account owns 27K Premium
   (`GET api.itch.io/games/<id>/ownership`) and applies the limits: 2
   active games, or 100 with Premium, counted for the host only.
4. **Coming back.** A "your turn" notice when the tab is closed (browser
   notifications first, then email), and a list of recent opponents with
   "challenge again". itch has no friends list to borrow.
5. **Daily challenge.** The same hitters and the same dice for everyone
   each day, with a leaderboard. Free. Next after the server is online.
6. **Style options, free for everyone:** team name, colours and cap logo;
   your pitcher's name and number; field themes.
7. **Leagues and tournaments** (hosting one needs Premium). *On hold for
   now.* Both players
   pitch their halves of a game *at the same time* against the other's
   lineup, any time before the deadline, and the server puts the box score
   together; nobody waits on anybody. One game a day by default (three a
   day or shorter games as options), a missed deadline is pitched by the
   computer, and the formats come from `src/engine/competition.js`
   (round robin, then a bracket).
8. **Premium extras:** career multiplayer stats and pitch charts; your Formula Lab rules in games you host (shown to the other
   player before they join); a supporter badge.

## itch.io checklist (step 1)

1. `npm install`, `npm test`, then `npm run itch` → `27k-itch.zip`
   (`index.html` at the top of the zip, about 80 files, under 1 MB).
2. On itch: *Create new project* → Kind of project **HTML** → upload the
   zip → tick **This file will be played in the browser**.
3. Embed options: **Click to launch in fullscreen** (the three-column
   layout wants about 1280 × 800; smaller frames fall back to the
   one-column phone layout, which works but hides the side panels below
   the field). Tick **Mobile friendly**, orientation **Portrait** (it
   also plays sideways).
4. Pricing: **No payments** to start, or **$0 or donate** for the Support
   27K link.
5. Cover, screenshots and description: candidates and advice are in
   [store/](store/README.md). Needed from the owner: the itch account and
   page address, and the final choice of each.

After the page exists, add its address as the *Support 27K* link on the
menu (`src/ui/screens.js`).

## Before each release

- `npm test` (rules, catcher's advice, multiplayer, 300 simulated games,
  every challenge, a season at each level, nine career seasons).
- Play one inning in a desktop browser and on a phone.
- `npm run build`, then from the repository root `ballmonitor build-site`
  so ballmonitor.com/27k/ gets the same build.
