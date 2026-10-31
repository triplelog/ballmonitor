# College football game replay (`cfb_replay`)

**Question:** How should a finished college football game be paced into a ~60-second
replay, and which plays swung ESPN's win probability most?

**Status:** draft (v0.4.0)

This is the data/timeline half of a "game in 60 seconds" vertical video (YouTube Short
style). It does not estimate anything new: it reads ESPN's play-by-play and **ESPN's own
win probability**, measures how much each play moved it, and decides how long each play
stays on screen. By default (`structure = "chart"`, v0.4.0) the WP curve runs **down the
left** of the frame and ~14 **annotated plays** (every score, then the biggest swings)
appear one at a time on the right, each pointing at its moment on the curve; the time axis
is warped so every card fits. `structure = "sections"` (variant `chapters`, v0.3.0) tells
the game in ~10 titled sections; `structure = "plays"` (variant `plays_only`) keeps the
v0.2.0 per-play pacing. A separate canvas renderer draws the video from `extras` (contract below).

## Inputs

| input | meaning | example |
|---|---|---|
| `game` | ESPN event id (string or int) | `"401858274"` |
| `home`, `away`, `date` | alternative to `game`: team names (school, nickname, abbreviation or full name) and the game date `YYYY-MM-DD` (US date). When all three are given they take precedence over `game` | `"Kansas"`, `"Baylor"`, `"2026-10-24"` |
| `duration_sec` | optional; overrides the `duration_sec` param | `45` |

## Data source

- `https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event=<id>`:
  `drives.previous[].plays[]` (play-by-play), `winprobability[]` (`homeWinPercentage` per
  `playId`), `header.competitions[0]` (teams, colors, ranks, records, final score, status),
  `gameInfo.venue`.
- `…/college-football/scoreboard?dates=YYYYMMDD&groups=80&limit=300` finds a game from team
  names + date (FBS games only).
- Lookup order: `data/games/<id>.json` (bundled, trimmed, committed) → `data/raw/summary_<id>.json`
  (full responses cached from earlier downloads; gitignored) → the network if `allow_network`
  is true. Only completed games are cached. Scoreboards are cached as
  `data/raw/scoreboard_YYYYMMDD.json` for past dates.
- `ballmonitor fetch cfb_replay [--offline]` rebuilds the bundled games (`fetch.py`, list in
  `BUNDLED`). `espn.py` holds the loader, the team/date lookup and the trimming.
- **Win probability is ESPN's** (their in-game model), used as published and labelled
  "ESPN" in every output (`extras.game.wp_source = "ESPN"`). The first `winprobability`
  entry, whose `playId` is not a play, is ESPN's pregame value; if it is missing the first
  published value is used (noted in the steps).
- ESPN's site API is public but **unofficial and undocumented**; it can change or disappear
  without notice. Personal, non-commercial use only; the bundled game files are small
  trimmed copies kept so the examples and tests run offline.

### Example games

| example | game | why |
|---|---|---|
| `default` | 401858275 Syracuse at North Carolina (31-30 OT), 2026-10-24 | six WP lead changes, OT trade of touchdowns, walk-off 4th-down TD (75.6-point swing) |
| `pitt_miami` | 401858274 Pittsburgh at Miami (52-23), 2026-10-24 | a lopsided game: shows how pacing behaves when no play moves WP much (biggest swing 3.6%) |
| `baylor_kansas` | 401856834 Baylor at Kansas (25-24), 2026-10-24 | nine lead changes, pick-six, go-ahead TD at 1:13 and a blocked 45-yard FG at 0:18 (54.1-point swing); also exercises lookup by team names + date |

## Method

1. **Load** the summary; sort ESPN events by `sequenceNumber` (drive order is not always
   chronological, e.g. in overtime).
2. **Drop non-plays.** Events whose type starts with an entry of `drop_types` (Timeout,
   End Period / End of Half / End of Regulation / End of Game, Official Timeout, Two-minute
   warning) are not shown. Their WP change (ESPN sometimes moves WP at a period end, and the
   final 0%/100% usually arrives on "End of Game") is folded into the previous play, so the
   WP chain stays contiguous and ends at ESPN's final value. Non-plays before the first play
   are ignored, so the first play always starts from the pregame WP.
3. **Scores.** ESPN's running score on ordinary plays is unreliable (it sometimes shows a
   score from later in the game); the score on plays flagged `scoringPlay` is consistent.
   So the score changes only on scoring plays and is carried forward.
4. **Swing.** For play *i*: `wp_home_before` = `wp_home_after` of play *i−1* (pregame WP for
   the first), `wp_home_after` = ESPN WP for the play (previous value if ESPN has none),
   `swing = after − before` (home perspective, signed), `abs_swing = |swing|`.
5. **Flags.** `scoring` = ESPN `scoringPlay` or the score changed. `turnover` = ESPN
   `isTurnover`, an interception type, or a turnover on downs (4th-down rush/pass/sack where
   possession changes, or the text says so).
6. **Highlights.** The `highlight_count` largest `abs_swing` plays with
   `abs_swing ≥ highlight_min_swing`; `top_plays` lists them by `abs_swing` descending.
7. **Headline** (first match): scoring play → `TOUCHDOWN <SCHOOL>` (≥6 points or a
   touchdown type; school = team whose score rose), `FIELD GOAL` (3), `SAFETY` (2);
   `BLOCKED FIELD GOAL`; `MISSED FIELD GOAL`; turnover → `INTERCEPTION`, `FUMBLE`,
   `TURNOVER ON DOWNS`, else `TURNOVER`; `|swing| ≥ big_play_swing` → `BIG PLAY`; else null.
8. **Pacing.** body = `duration_sec − intro_sec − outro_sec`. Each play gets a weight from
   formula **`play_weight`**:

   w = base_weight + swing_k · |swing|^swing_power + scoring_bonus · scoring
       + turnover_bonus · turnover + highlight_bonus · highlight

   and a duration `clamp(λ · w, min_play_sec, max_play_sec)`. λ is found by bisection so
   the durations sum to the body exactly (the clamped total is continuous and increasing
   in λ); the last float residue goes to the unclamped plays and the last play's end is
   pinned to `duration_sec − outro_sec`. Edge cases: if every play at the floor already
   overfills the body (very short videos) or every play at the cap can't fill it (very few
   plays), all plays get equal shares and the steps say the floor/cap was not honoured.
9. **Timeline.** `t_start` of the first play = `intro_sec`; each `t_start` = previous
   `t_end`; last `t_end` = `duration_sec − outro_sec`.

Steps 1–5 are shared. Steps 6–9 and "Quiet drives" below are the **`structure = "plays"`**
path (v0.2.0, unchanged); the default **`structure = "sections"`** path is described in
"Sections".

**Quiet drives** (applied after highlights are chosen, before pacing). A drive with at
least `drive_collapse_min_plays` plays, no highlight and no play with |swing| ≥
`drive_collapse_max_swing` (default 0.10, the same line as "BIG PLAY") becomes **one
timeline event** (`kind = "drive"`): "PITT drive · 6 plays, 23 yards, 2:51 · Punt" from
ESPN's drive summary and result. Its swing is the drive's net change (first play's WP
before → last play's WP after), its score is the score after the drive, and its screen
time comes from formula `drive_weight` with its own floor `min_drive_sec` (0.6 s: long
enough to read, still quick). Set `drive_collapse_max_swing = 0` to show every play.

Defaults (60 s, intro 1.5 s, outro 2.5 s, play floor 0.08 s, drive floor 0.6 s, cap 5 s,
`swing_k` 10, `swing_power` 2, `highlight_bonus` 3, 10 highlights, drives collapsed below
a 0.10 swing) give, on the bundled games: 60–80 timeline events instead of ~180 plays
(15–22 quiet drives collapsed), the ten highlights held ~3.9–5 s each (~43 s), quiet
drives ~0.6 s each, and the remaining plays of eventful drives flashing at 0.08 s. The
`short_cut` variant restores the v0.1.0 30-second pacing (6 highlights, 3.5 s cap).

## Chart (default, `structure = "chart"`, v0.4.0)

Code: `chart.py`. The frame: compact scoreboard on top; below it a vertical WP chart on
the left (x = home WP: away 100% at the left edge, 50% in the middle, home 100% at the
right; y = game time, top to bottom, area between the line and 50% in the leading team's
colour); annotation cards on the right, each with a pointer straight across to its play.

1. **Importance** of each play — formula `chart_importance`
   (`abs_swing + chart_score_bonus·scoring + key_turnover_bonus·turnover + key_long_bonus·long_play`).
2. **Cards** — every scoring play, then the most important other plays with
   |swing| ≥ `chart_min_swing` (0.03), up to `chart_cards` (14). If there are more scores than
   cards (a shootout), the most important scores are kept. The `chart_large_cards` (4) most
   important cards are **large** (bigger text, a "Q4 2:28 · TOUCHDOWN" line); normal cards
   put the time inline. Scoring cards are tinted in the scoring team's colour and show the
   new score (away–home, as on the scoreboard); other cards show the swing and team.
   Card text is `phrase` from the summary parser ("Syracuse: 4-yard TD pass from Angeli to
   Russell"), or for an ordinary gain "Miami completes a 21-yard pass to Toney".
3. **Warped time axis** — each card gets a vertical slot (1 unit, `chart_large_units` = 1.7
   for large cards), with `chart_margin_units` (0.35) above the first and below the last;
   `slot_h = units / total`. A card's play sits at its slot's centre (`y`), so the pointer is
   horizontal. Plays between two cards are spaced evenly between their centres (plays
   before the first card / after the last fill the margins). Busy stretches with many cards
   are stretched, long quiet ones compressed.
4. **Reveal timing** — the body (duration − intro − outro) is split among the cards by
   formula `chart_reveal_weight` (`1 + chart_reveal_k·importance + chart_large_bonus·large`),
   clamped to [`chart_min_reveal_sec`, `chart_max_reveal_sec`] = [2.2, 7] s and scaled to
   fill the body exactly (same `allocate` as the other modes). In card *i*'s window the
   line draws from the previous card's play down to this card's play over the first
   `chart_draw_share` (25%), the card slides in, and the rest is the pause. Plays after the
   last card are drawn during the last window's pause.
5. The outro shows the final score over the complete chart with every card.

## Sections (variant `chapters`, `structure = "sections"`)

All code in `sections.py`; every number below is a param or formula in `config.toml`.

1. **WP series.** h₀ = pregame home WP, hⱼ = home WP after play j−1 (j = 1…n). A boundary
   "before play j" sits at hⱼ.
2. **Allowed boundaries.** A boundary may only fall where formula **`boundary_pref`**
   (`3·scoring + 2·turnover + new_drive`, judged on the play before it; a PAT/conversion play
   right after doesn't count) is > 0: right after a score, right after a turnover, or where a
   new ESPN drive starts (ESPN drives begin with the kickoff, so "after a TD" and "before the
   kickoff" are the same spot). So boundaries never cut a drive awkwardly.
3. **Zig-zag pivots.** On h sampled at the allowed boundaries (plus start and end), a running
   peak (valley) is confirmed once WP falls (rises) from it by ≥ `section_min_reversal`
   (0.08); ties keep the earliest point. If that gives more than `n_sections − 1` pivots, the
   threshold is multiplied by `section_reversal_growth` (1.15) until it doesn't — the
   smallest back-and-forths disappear first, i.e. the smallest-|swing| neighbours merge.
4. **Splits.** While there are fewer than `n_sections` (10) sections, or a section has more
   than `section_max_scores` (3) scoring plays: pick the section with the highest
   **`split_priority`** = |swing| + `split_length_k`·plays/total + `split_scores_k`·scores,
   and split it before the play c maximising **`split_score`** = |swing of play c−1| +
   `split_boundary_k`·boundary_pref(c) (largest single swing, preferring right after a
   score), among allowed boundaries leaving ≥ `min_section_plays` (3) per side. A section
   with too many scores is split between scores first (this can push the count above
   `n_sections`). The first half is labelled `pivot = "split"`; the last section `"end"`.
5. **Key plays** (≤ 4, time order): every scoring play, then the section's highlights, then
   other plays ranked by **`key_weight`** = |swing| + `key_turnover_bonus`·turnover +
   `key_kick_bonus`·blocked/missed kick + `key_long_bonus`·(gain ≥ `long_play_yards`), if
   ≥ `key_min_weight`, up to `section_key_plays` (3). A section with none holds its
   biggest-swing play. Highlights: the `section_highlight_count` (4) largest-|swing| plays.
6. **Reading play text** (`parse_play`, regexes on the cleaned ESPN text, both ESPN styles:
   "S.Angeli pass complete … to C.Russell III … for 4 yards … TOUCHDOWN" and "Cataurus Hicks
   36 Yd pass from Holden Geriner (… Kick)"): kind (TD pass / TD run / pick-six / fumble,
   punt or kick return TD / FG / safety / interception / fumble / turnover on downs /
   blocked or missed FG / blocked punt / penalty / sack / pass / rush), yards, passer,
   receiver, runner, defender, conversion (2-pt good/failed from the points on the TD play
   and the text; missed PAT from the text). Names are surnames ("B.Edwards Jr." → Edwards).
   Unrecognised text falls back to the ESPN play type (kind "play"). Scorer = the team
   whose score rose.
7. **Summary** (≤ `summary_max_chars`, 180): the key plays in order as clauses with a team
   subject — first score "X scores on a 75-yard TD pass from Angeli to Hatcher" / "X kicks a
   39-yard field goal" / "X gets a safety", then "Y answers with …" (other team) or "adds …"
   (same team); non-scoring: "X intercepts Lagway", "X stops Y on 4th down", "X blocks a
   45-yard Y field goal", "X hits a 28-yard pass to Russell", "X breaks a 39-yard run by
   Edwards". Long/big ordinary plays are only narrated when WP moved toward the team that
   made them (ESPN WP glitches are skipped). A section ending mid-drive within
   `section_end_deep_yards` adds "X drives to the UNC 10". Two clauses per sentence, the
   subject is dropped when repeated, back-to-back repeats become "twice". If too long it
   drops non-scoring clauses beyond the top one, then player names, then uses abbreviations,
   then drops all non-scoring clauses — **scores are always named**. A section with nothing
   notable describes the drives: "Defenses trade punts", "X reaches the BU 30 but no
   points", "X runs out the clock to win 25-24".
8. **Title** (≤ `section_title_chars`, 40; abbreviations if needed), first rule that applies:
   last section and the winner took the lead → "X wins it in OT" / "X wins it late"; both
   teams scored in OT → "Back-and-forth in OT"; a pick-six that flipped the lead → "Pick-six
   flips it"; last section, winner leading but in doubt (WP ≤ `title_close_wp`) → "X seals it"
   / "X holds on"; WP moved ≥ `title_momentum_swing` toward a team that didn't score →
   its turnover ("Kansas blocks a field goal"), deep drive or "Momentum swings to X";
   first points → "X strikes first" / "X strikes, Y answers"; lead change → "X takes the
   lead" / "X goes ahead" / "X ties it at 23"; both scored → "X and Y trade scores"; one team
   → "X answers" (if the other team scored last), "X goes up 17-0", "X pulls away, 31-7",
   "X chips away"; no score → its turnover, momentum, or "Defenses take over".
9. **Timing.** body = duration − intro − outro (56 s). Section weight = formula
   **`section_weight`** = `section_base` + `section_swing_k`·|swing| +
   `section_score_bonus`·scores + `section_play_k`·plays + `section_late_bonus`·late; section
   time = clamp(λ·w, floor, `max_section_sec`) with λ solved by `allocate` so sections fill
   the body exactly, floor = max(`min_section_sec`, `section_title_sec` + `min_play_sec`·other
   plays + `key_min_sec`·key plays) (the cap is raised to the largest floor if needed).
   Inside a section: the first `section_title_sec` (0.6 s) is the **title lead-in**, added to
   the start of the section's first play (the renderer shows title + summary then;
   `title_sec` in the section); non-key plays each get `section_rest_share` of the rest ÷
   their number, clamped to [`min_play_sec`, `rest_play_max_sec`] (0.08–0.3 s); key plays
   split what is left by **`key_hold_weight`** = 1 + `hold_swing_k`·|swing| +
   `hold_score_bonus`·scoring + `hold_highlight_bonus`·highlight (floor `key_min_sec`, 0.6 s),
   so every score is held. Boundaries are rounded cumulative sums, the last pinned exactly.
   `max_play_sec` and the drive params are not used in this structure.

Results on the bundled games (defaults): 10 sections each (scores per section ≤ 3), section
times 3.0–8.0 s, key plays 0.6–5.3 s (the OT walk-off TD 5.26 s, the Kansas go-ahead TD 3.37 s),
ordinary plays 0.08–0.30 s.

## Output

Text outcomes: **Biggest swing (ESPN WP)** (primary; probability = |swing|), final score
for each team (`int`), pregame home WP (`pct`), and a "Biggest swings" group with the
highlight plays (probability = |swing|, note = quarter, clock, which team it favoured,
short text).

In sections mode there is also a **"Sections"** group: one outcome per section, label
"N. title", probability = |section swing|, note = the summary cut to `section_note_chars`
(71, one line); the full summaries are in the steps.

`extras` (the renderer contract; keys and types are stable):

- `game`: `{id, date (ISO UTC), venue (str|null), status_text, home: TEAM, away: TEAM,
  final: {home, away}, pregame_wp_home (0–1), wp_source: "ESPN"}`;
  TEAM = `{name, short, abbr, color "#rrggbb", alt_color "#rrggbb", rank (int|null), record (str|null)}`.
- `timeline`: `{duration_sec, intro_sec, outro_sec, fps, width, height}` (60, 1080×1920 by default).
- `plays` (game order): `{idx, id, quarter (5+ = OT), clock "MM:SS", down, distance,
  yardline_text, possession ("home"|"away"|null), yards_to_endzone, text, short_text (≤90,
  no clock/jersey numbers/tacklers/formation), type, scoring, turnover, home_score,
  away_score (after the play), wp_home_before, wp_home_after, swing, abs_swing, t_start,
  t_end, highlight, headline, kind ("play"|"drive")}`. Kickoffs have null down/distance;
  `yardline_text` falls back to "ABBR NN" from `yardsToEndzone` when ESPN gives no
  `possessionText`. Collapsed drives (`kind = "drive"`) also carry `n_plays`,
  `drive_summary`, `drive_result` and `end_yards_to_endzone` (at the last snap); their
  quarter/clock/yardline are the drive's first play and down/distance are null.
- `top_plays`: idx of the highlight plays by `abs_swing` descending (`highlight_count` = 10
  in plays mode, `section_highlight_count` = 4 in sections mode).
- `structure`: `"chart"` | `"sections"` | `"plays"`.
- **chart mode only:** every play carries `y` (0–1, warped vertical position, non-decreasing),
  `key` (has a card) and, for card plays, `phrase`. `annotations` (game order): `{idx, play
  (play idx), size ("large"|"normal"), units, slot_h (fraction of chart height), y (= the
  play's y), t_start, t_show (= the play's t_start: the line reaches it and the card
  appears), t_end (next card's t_start; last = duration − outro), headline, label
  ("Touchdown", "Field goal", "Blocked kick", "Big play", …), phrase, swing, abs_swing, team
  ("home"|"away": the scorer, or the team the swing favoured), scoring, quarter, clock,
  home_score, away_score, importance}`. Text outcomes add an "Annotated plays" group.
- **sections mode only:** `plays` holds **every** real play (`kind = "play"`, no collapsed
  drives) with two extra keys, `section` (section idx) and `phrase` (str|null, key/highlight plays only), `key` (bool: in its section's
  `key_plays`). `sections` (game order): `{idx, first_play, last_play (play idx,
  inclusive), t_start, t_end (video s; first t_start = intro_sec, contiguous, last t_end =
  duration − outro), title_sec (lead-in at t_start while the title shows), wp_home_start,
  wp_home_end, swing (home view, signed), pivot ("peak"|"valley"|"split"|"end"),
  score_start {home, away}, score_end {home, away}, title (≤40), summary (≤180),
  key_plays (≤4 play idx, time order, every scoring play included), scoring_plays}`.

## Assumptions and known weaknesses

- Sections follow ESPN's WP, so a section is a "momentum" stretch, not a quarter; with WP
  noise a short section can be about very little (e.g. the OT possession before the
  walk-off). Titles/summaries are template text: accurate but plain, and play text ESPN
  writes in an unusual way falls back to generic phrases ("a touchdown", "a score").
- Blowouts have no real pivots; sections then come from splits at scores, so they read as a
  list of scores.

- Everything rests on ESPN's WP model; its glitches pass straight through. Example: in the
  pitt_miami game a 2-yard Pitt completion in Q1 is the "biggest swing" (+3.6 points, reversed
  on the next play), apparently because ESPN's running score briefly jumped ahead.
- In blowouts all swings are small, so the highlights are chosen among small swings; the
  `highlight_min_swing` floor (1 point) keeps pure noise out but the cut is less dramatic.
- Swing measures win-probability impact, not spectacle: a 70-yard TD when up 30 barely
  registers, a kneel-down can't, a late 4th-down stop can dominate. Scoring/turnover bonuses
  soften this.
- Non-play WP drift is credited to the previous play.
- Overtime plays all carry clock "00:00" (ESPN does not time OT).
- The 0.05 s floor is 1.5 frames at 30 fps: ordinary plays are a flicker, by design.
- Depends on an unofficial API; bundled games keep the examples working if it changes.

- Chart mode: the vertical axis is not proportional to game time (quarter lines show
  where each quarter starts), and in a blowout most cards are scores with tiny swings.
  Normal cards use 22–32 px text, readable on a phone but not large.

## Variants

- `chapters` — `structure = "sections"`: the v0.3.0 ~10 titled sections.
- `plays_only` — `structure = "plays"`: the v0.2.0 per-play pacing (tests check it
  reproduces v0.2.0's extras exactly, apart from the new `structure` key).
- `short_cut` — (structure = plays) the v0.1.0 30-second cut: up to 6 highlights, 0.05 s play floor, 0.4 s drive floor, 3.5 s cap.

## Backtest data

None. This is a presentation model (there is no "actual" to score against).

## References

- ESPN site API (unofficial): `site.api.espn.com/apis/site/v2/sports/football/college-football/{summary,scoreboard}`.
- ESPN win probability: ESPN Analytics' in-game college football win probability model, as
  published in the summary's `winprobability` array.

## Changelog

- 0.4.0 — new default `structure = "chart"` (`chart.py`): vertical WP chart with up to
  `chart_cards` annotated plays revealed one at a time, warped time axis (`chart_large_cards`,
  `chart_large_units`, `chart_margin_units`), reveal pauses by formula `chart_reveal_weight`
  (`chart_reveal_k`, `chart_large_bonus`, `chart_min/max_reveal_sec`, `chart_draw_share`),
  importance by formula `chart_importance` (`chart_score_bonus`, `chart_min_swing`). New
  `extras.annotations`, per-play `y`. Sections kept as variant `chapters`.

- 0.3.0 (addition) — key and highlight plays carry `phrase`, a natural one-line description from the summary parser (e.g. "Syracuse: 4-yard TD pass from Angeli to Russell"); the renderer's cards use it.

- 0.3.0 — new default `structure = "sections"`: ~10 sections from zig-zag WP pivots at
  drive/score/turnover boundaries, topped up by splits (`n_sections`, `section_min_reversal`,
  `section_reversal_growth`, `min_section_plays`, `section_max_scores`, formulas
  `boundary_pref`, `split_priority`, `split_score`); key plays (`section_key_plays`,
  `key_weight`, `section_highlight_count` = 4); titles and summaries generated from the play
  text (`summary_max_chars`, `section_title_chars`, …); section timing (`section_weight`,
  `key_hold_weight`, `min/max_section_sec`, `section_title_sec` lead-in). New `extras`:
  `structure`, `sections`, per-play `section`/`key`; "Sections" outcome group. v0.2.0
  behaviour kept as `structure = "plays"` (variant `plays_only`; `short_cut` uses it).
  `clean_text`/`allocate` moved to `sections.py` (still importable from `model.py`).

- 0.2.0 — 60-second default (10 highlights, 0.08 s floor, 5 s cap); quiet drives collapsed
  into one quick event each (`drive_collapse_max_swing`, `drive_collapse_min_plays`,
  `min_drive_sec`, `drive_base`, formula `drive_weight`); `allocate` takes per-event floors;
  `long_cut` variant replaced by `short_cut` (30 s).

- 0.1.0 — initial version: ESPN WP swings, weight formula + clamped bisection pacing,
  highlights and headlines, three bundled games.
