# The itch.io page, field by field

Page: **https://robmwilc.itch.io/27-strikeouts** (dashboard → *Edit game*).
Everything to upload is in this folder or one level up; every value to type
is below, in the order itch's form shows the fields. itch moves fields around
now and then: match by name. Where a choice is yours to make, it says so.

Before you start: `npm test`, then `npm run itch` in `new27K/`. That writes
`new27K/27k-itch.zip` (`index.html` at the top, 70 files, under 1 MB, no
absolute paths: itch's limits are 1,000 files, 500 MB and relative paths only).

## Edit game (the main form)

| Field | What to enter |
| --- | --- |
| **Title** | `27K` (what the game calls itself on its menu and logo). If you'd rather keep the address's words in it, `27K: 27 Strikeouts`. *Your call.* |
| **Project URL** | `27-strikeouts` (already set; leave it, changing it breaks links). |
| **Short description or tagline** | `A baseball pitching game: pick your pitch, read the moving zone, paint the corners.` |
| **Classification** | Games |
| **Kind of project** | HTML |
| **Release status** | Released (every single-player mode is finished; multiplayer works). Pick *In development* if you'd rather signal that accounts and Premium are coming. *Your call.* |
| **Pricing** | **$0 or donate**. Suggested donation: $3 (any amount works; itch shows it on the download/support prompt). |

### Uploads

1. **Upload files** → `new27K/27k-itch.zip`.
2. On the uploaded file, tick **This file will be played in the browser**.
3. Leave the platform boxes (Windows, macOS, Linux, Android) unticked: it is a browser game.

### Embed options (appear once the zip is marked "played in the browser")

| Option | Setting | Why |
| --- | --- | --- |
| **Launch mode** (Embed in page / Click to launch in fullscreen) | **Click to launch in fullscreen** | The three-column game wants about 1280 × 800; fullscreen gives it the whole window. |
| **Viewport dimensions** | 1280 × 800 (only used if you switch to *Embed in page*) | |
| **Mobile friendly** | ticked | Phones get the one-column layout (and itch always launches fullscreen on phones). |
| **Orientation** (shown after *Mobile friendly*) | Portrait | It plays sideways too, but the phone layout is made for portrait. |
| **Click to play / Automatically start on page load** | Click to play (the default) | Sound needs a click to start anyway. |
| **Fullscreen button** | off (fullscreen launch already fills the screen) | |
| **Enable scrollbars** | off | The game scrolls its own panels. |
| **SharedArrayBuffer support** (if shown) | off | Not used. |

### Details

**Description** (rich-text editor: use *Heading 2* for the headings, bullets
for the lists, and upload the GIF with the editor's image button):

> **You're on the mound.** Pick a pitch, set how hard to throw it and how much
> to make it move, then aim at a strike zone that won't sit still. Paint the
> corners, change speeds, and get 27 outs before they score more than your
> hitters do.
>
> *(image: `docs/store/at-bat.gif`)*
>
> ## Every pitch is your call
> - Choose from your pitcher's arsenal: four-seamers, sliders, curveballs, changeups, splitters and more, each with its own break.
> - Aim where you want it to start; it breaks from there and scatters by your control. Edges are hardest to hit, and the umpire doesn't always give them.
> - Hitters have hot and cold zones, remember what they've seen, and get fooled by a change of speed or location.
> - Stuck? Call a catcher's visit and he'll tell you what to throw.
>
> ## Ways to play
> - **Quick Game**: one game, one to nine innings, five difficulty levels.
> - **Challenges & Achievements**: short puzzles (Strike Out the Side, Houdini, Immaculate Inning, 27 Strikeouts…) with one, two and three stars.
> - **Season**: a full college season with standings, a conference tournament and a bracket.
> - **Career**: start at 12 and pitch through youth ball, high school, college and the pros, spending XP on your pitches.
> - **Multiplayer**: send a friend a link; you take turns pitching to each other's lineups.
> - **Formula Lab**: every rule of the game is a formula you can read and change.
>
> Free, no ads, plays in the browser, on phones too. Your games are saved in your browser.

| Field | What to enter |
| --- | --- |
| **Genre** | Sports |
| **Tags** (up to 10) | `baseball`, `sports`, `pitching`, `simulation`, `strategy`, `singleplayer`, `multiplayer`, `browser`, `mobile-friendly`, `casual` |
| **AI generation disclosure** | *Your call, and answer it truthfully.* For reference: the code was written with an AI coding assistant (Claude); the graphics are drawn by the game's own code; there is no recorded audio, voice or AI-made art. itch asks per kind of content (graphics, sound, text, code), so tick what applies. |
| **App store links** | none |
| **Custom noun** | leave empty ("game") |
| **Download & install instructions** | leave empty (browser game) |
| **Community** | Comments |
| **Visibility & access** | **Draft** while you check it (below), then **Public**. |

### Right-hand column (media)

| Field | File |
| --- | --- |
| **Cover image** (630 × 500 suggested) | `docs/store/cover-a.png` (it is 1260 × 1000, twice the size: itch scales it down sharply). The other candidates are `cover-b.png` and `cover-c.png` (see README.md). |
| **Animated cover** (itch shows it when someone hovers over the cover in listings; upload it under the cover if the form offers *Upload GIF*) | `docs/store/at-bat-cover.gif` (630 × 500, 1.3 MB) |
| **Gameplay video or trailer** | Needs a YouTube or Vimeo link. `docs/store/at-bat.mp4` is ready to upload there; leave this empty until it is. |
| **Screenshots**, in this order | `02-strikeout.png`, `01-aiming.png`, `03-catchers-visit.png`, `06-season.png`, `05-formula-lab.png`, `04-challenges.png`, `07-career.png` |

Press **Save**.

## Metadata tab (appears after the first save)

| Field | What to enter |
| --- | --- |
| **Made with** | `JavaScript` (HTML5 canvas, no engine) |
| **Inputs** | Mouse, Keyboard, Touchscreen |
| **Accessibility** | leave empty (nothing there is claimed honestly yet) |
| **Average session** | About a half-hour (a 9-inning game; challenges take a few minutes) |
| **Languages** | English |
| **Multiplayer** | Server-based networked |
| **Player count** | 1–2 |
| **Links** | `https://ballmonitor.com/27k/` (the same game on Ball Monitor) |

## Edit theme (on the page itself, "Edit theme")

Optional. The game's own colours suit it: background `#0b1410` (dark green),
text `#e8efe9`, links `#ffd166` (the 27K yellow). Use `cover-c.png`'s logo as
the banner if you want one.

## Check before switching to Public

1. Open the page while it's a draft (itch lets you view your own draft) and
   press **Run game**. The menu should show **Multiplayer** (not "coming
   later"). There is no "Support 27K" line on itch itself; that link only
   shows on ballmonitor.com/27k/.
2. Start a multiplayer game on itch and join it from ballmonitor.com/27k/ in
   another browser (or the other way round). If Multiplayer is missing on
   itch, the frame's address isn't on the server's list: open the browser's
   developer tools, find the game frame's address (it starts with
   `https://html…itch.zone`), and tell Claude: it goes in `ALLOW_ORIGINS`
   (`deploy/ballmonitor-27k.service`), then `deploy/deploy.sh`.
3. On a phone: open the page, launch, play one at-bat.
4. Switch **Visibility** to **Public**.
