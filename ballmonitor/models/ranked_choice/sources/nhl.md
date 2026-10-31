# NHL awards: PHWA individual ballots (`sources/nhl.py`)

The Professional Hockey Writers' Association has published each voter's ballot every
year since the 2017-18 awards (posts on thephwa.com, one per season). In scope here:
**Hart, Norris, Calder, Selke, Lady Byng**. Each one is a 5-place ballot scored
**10-7-5-3-1** (the PHWA trophy points system; Lady Byng uses the same five places and points.
Check this against the published totals once the files are in).

Out of scope, so not parsed (the posts link them anyway):
- **All-Star and All-Rookie teams**: position-tiered ballots, one file per position.
- **Masterton**: the posts link it, but it is not a ranked league-wide vote.
- **Conn Smythe**: separate posts with a small panel of about 18 voters.

## Where the data is, and why most of it has to be downloaded by hand

| season | post | award files |
|---|---|---|
| 2017-18 | thephwa.com/2018/06/21/nhl-awards-ballots-from-phwa-members/ | Drive (Hart linked directly; the other awards through bit.ly links that redirect to Drive) |
| 2018-19 | thephwa.com/2019/06/20/2019-nhl-awards-ballots-from-phwa-members/ | Drive (some `open?id=` links, rewritten to `/file/d/<id>/view`) |
| 2019-20 | thephwa.com/2020/09/22/2019-nhl-awards-ballots-from-phwa-members-2/ | Drive |
| 2020-21 … 2025-26 | thephwa.com/<year>/…/phwa-…-nhl-awards-ballots/ | Drive |

None of the posts has an HTML table: every ballot file is a **PDF on Google Drive**.
Drive's robots.txt allows `/file/...`. But the `/file/d/<id>/view` page only holds the
file name, not its content. The routes that serve the content are all disallowed: `/uc`,
`/drive-viewer/...` page images, and `drive.usercontent.google.com` (which has
`Disallow: /`). So the module **does not download the PDFs**. It fetches each allowed view
page once to record the file name, then reads copies you download yourself.

### Manual download

Open each link in a normal browser, download the PDF and save it as

    ballmonitor/models/ranked_choice/data/raw/nhl/manual/<season>_<award>.pdf

where `<award>` is one of `hart`, `norris`, `calder`, `selke` or `lady_byng`, and `<season>`
looks like `2024-25`. Two other names also work: the Drive file id (`<id>.pdf`), and the
extensions `.csv`, `.xlsx` or `.txt` (see Parsing). Running `ballmonitor fetch` / `nhl.fetch()`
prints every missing file with its link. It also writes
`data/raw/nhl/manifest.csv` (season, award, expected file, Drive URL, Drive file name, have).

| season | Hart | Norris | Calder | Selke | Lady Byng |
|---|---|---|---|---|---|
| 2017-18 | [1JhhXqB6…](https://drive.google.com/file/d/1JhhXqB6MhFmvYczOil3S1Rv2sAoF_uOY/view) ("corrected results") | [14LM4bkq…](https://drive.google.com/file/d/14LM4bkq0Xssa5GmOKgJhg0pUhreCh_Eg/view) | [1YTiXT_9…](https://drive.google.com/file/d/1YTiXT_9onW6xkeXvnDdk8AXiknNoAfqy/view) | [1KwBRwdl…](https://drive.google.com/file/d/1KwBRwdlym2G9StVXL-9Kcgo3E45b2k5M/view) | [1SXXuriY…](https://drive.google.com/file/d/1SXXuriYGAnaiMfQPRak6woAonnO6OYub/view) |
| 2018-19 | [1LcqOhRj…](https://drive.google.com/file/d/1LcqOhRjM3UcYBZJEvzLr27BSGSuawn7Z/view) | [1BcCdVGb…](https://drive.google.com/file/d/1BcCdVGbcaSFU8aYDXk-6z3qhW4VyBSaH/view) | [1eKcRt_J…](https://drive.google.com/file/d/1eKcRt_JNVxErFqBtUHyfPDXW_qp_5r0Q/view) | [1azUPwCJ…](https://drive.google.com/file/d/1azUPwCJrnRa_ykOf5T48MlDQLHdK8Hff/view) | [1Jm6QAz6…](https://drive.google.com/file/d/1Jm6QAz696b6qbjTyLdOhyQs-L6j0d9l6/view) |
| 2019-20 | [1DovZ9dG…](https://drive.google.com/file/d/1DovZ9dGa_ghanx5T9iybdj0pMaxIBIaB/view) | [1Y07x9ps…](https://drive.google.com/file/d/1Y07x9psEFd5SgPGDcYfk64iXdsR_Iwqh/view) | [1RUV95kC…](https://drive.google.com/file/d/1RUV95kCzXunhJgyQP4Qi4TwsR7kB4Oy9/view) | [1MGXiwsK…](https://drive.google.com/file/d/1MGXiwsKyWkGXRQ25mM86YBPFTYhlIOXV/view) | [144p6uFd…](https://drive.google.com/file/d/144p6uFdPDZ9XQ2s4gcvg5e5fDTPAw9H0/view) |
| 2020-21 | [15PvxwdX…](https://drive.google.com/file/d/15PvxwdX0aSgNiOi4FPfhw0BNHMkZeG9D/view) | [1WmP8sh1…](https://drive.google.com/file/d/1WmP8sh1ySSTM0M2mf9aJK-exyuI9vah7/view) | [1gjmt8ed…](https://drive.google.com/file/d/1gjmt8edZxCCSwEVMfqk6wbi0BSVfGjHq/view) | [1u0LYy9U…](https://drive.google.com/file/d/1u0LYy9UykBzBhCbZjX9SFhOywa1c6ECp/view) | [1i5flHDQ…](https://drive.google.com/file/d/1i5flHDQsuMPfcwGyeP3eIoe1fl-ZOlwC/view) |
| 2021-22 | [1b3LX970…](https://drive.google.com/file/d/1b3LX970_5RrQd6Voj6g8PHouT5mt47sQ/view) | [1cd1Ik-F…](https://drive.google.com/file/d/1cd1Ik-FtCmmx1WxmjTdIN4m8te4Jkens/view) | [1rgZyodF…](https://drive.google.com/file/d/1rgZyodF3uxUSGhDLsi7pB5QbzFZ9zgRk/view) | [1xVhpNcG…](https://drive.google.com/file/d/1xVhpNcGrtdR463XnjMzu3SBEe-FIAj7Q/view) | [1yfnYDgH…](https://drive.google.com/file/d/1yfnYDgH3PwhQbe63Fi6GwjSSEJaA8Euz/view) |
| 2022-23 | [13gtNP8a…](https://drive.google.com/file/d/13gtNP8asXOBxMjRRrUssEhEroCX88_eD/view) | [1f-u68bz…](https://drive.google.com/file/d/1f-u68bzJ2hRCFtATrmrVwL8UXzyBIcch/view) | [1DVFfWsx…](https://drive.google.com/file/d/1DVFfWsxW7da4PQArtwVnzVv1EN3hTrXN/view) | [1zLRBiHL…](https://drive.google.com/file/d/1zLRBiHLh7R8W8hYIsM3ubqTQln1vJYlB/view) | [1SxicTeB…](https://drive.google.com/file/d/1SxicTeBLCbQM2udtkc6NUqjUtwEKHDWl/view) |
| 2023-24 | [1kx2tsV8…](https://drive.google.com/file/d/1kx2tsV81MuF8Q_ISn7KbT6DeJkMKYgZb/view) | [1WDzKUpX…](https://drive.google.com/file/d/1WDzKUpXYGhKmBigLCwO1FNUP5-yRye0R/view) | [1GMNyItZ…](https://drive.google.com/file/d/1GMNyItZ7I6nZQZc7EOqtcqbwZ-9FMB4p/view) | [1mweVeFX…](https://drive.google.com/file/d/1mweVeFX1hdAIew4egTOsGfcorl261CWj/view) | [1yReNikR…](https://drive.google.com/file/d/1yReNikRjKOLAugWkAb9M1Fr72E4qkdZy/view) |
| 2024-25 | [1eCIYQ0u…](https://drive.google.com/file/d/1eCIYQ0uHhxmzxIYxtgW0SJu-K6zs9KJw/view) | [1eOYRF7c…](https://drive.google.com/file/d/1eOYRF7cVYFEHOco0kv_LHyGxJ99IZUUG/view) | [1C-JDy4c…](https://drive.google.com/file/d/1C-JDy4cwlOEjexViUtzXgwUY8JeQNJEd/view) | [1-59Insi…](https://drive.google.com/file/d/1-59InsifCCHEUz1OzrOqEtW0nLm45yc_/view) | [1XWmy9wE…](https://drive.google.com/file/d/1XWmy9wEFsFdv2HEixjZDjyhnUm9I2ELD/view) |
| 2025-26 | [1caeK_Gl…](https://drive.google.com/file/d/1caeK_GlEwBw_P5HnbLhPBXYSbp5xNiQo/view) | [1PKZnavS…](https://drive.google.com/file/d/1PKZnavSNakOW8QH3NWzvcQRbKHW9lyXO/view) | [1KwbzX8t…](https://drive.google.com/file/d/1KwbzX8t4EFY59dfzdWC7pXnW_IC5EuZf/view) | [1pVFa9C9…](https://drive.google.com/file/d/1pVFa9C9sSBMVv5aW1lyNwA7Z03l3Pwf-/view) | [1FRXq5fR…](https://drive.google.com/file/d/1FRXq5fRYmAEItrvdQBKo3-6gH1CYdC77/view) |

## Parsing (`parse_file`)

The parser has not yet been checked against a real PHWA PDF, because none could be
fetched within the robots rules. It is driven by the file's header row, so it does not
depend on one exact layout:

- **Header row**: a row with at least 3 ordinal place columns (`1st`, `First`,
  `1st Place`, `1` …). The other header cells are matched to roles:
  - voter: `Voter`, `Name`, `First`/`Last`. Separate first-name and last-name columns are joined.
  - affiliation: `Outlet`, `Affiliation`, `Media`, `Publication`, `Chapter` …
  - team: a `Team` column placed after a place column belongs to that place.
  If no voter column is labelled, the first column before the places is the voter and the
  second is the affiliation.
- **Summary table**: a header with `Player` or `Points`/`Pts`/`Total` is read as the
  official results (player, team, first-place votes, points). These fill `published` and
  are checked against the points recomputed from the ballots. Any mismatch is logged as
  `MISMATCH`. Without a summary table, `published` stays `""`.
- **Player cells**: `Name (TEAM)`, `Name, TEAM`, `Name - TEAM` and `Last, First` are all
  recognised. `candidate_id` is an ASCII slug of the name (`Juraj Slafkovský` →
  `juraj-slafkovsky`), so the same player gets the same id across voters and seasons, as
  long as the PDFs spell the name the same way.
- **Formats**:
  - PDF: pypdf `extract_text(extraction_mode="layout")`. Columns are split on runs of 2 or
    more spaces and lined up with the header positions.
  - CSV and TSV/TXT.
  - XLSX: a small stdlib reader.

  If a PDF parses badly, a hand conversion to CSV with the same columns works too.
- Ballots that don't have exactly 5 places are kept but logged.

`date` is the "revealed <Month day>" date given next to the award in the post (2024-25
onward). Where there is none, it is the post date. `url` is the Drive view link.

## Caching and politeness

- Requests are at least 1.5 s apart, with the User-Agent
  `ballmonitor-ranked-choice/0.1 (personal, non-commercial research)`.
- Posts are cached in `data/raw/nhl/posts/<season>.html`. A post is fetched again only if
  it still has unrevealed awards (fewer than 6 links).
- Drive view pages are cached in `data/raw/nhl/drive/<id>.html`. Resolved bit.ly targets
  go in `data/raw/nhl/links.json`. The sitemap (`sitemap.xml`) is fetched again when
  online, to find new seasons.
- `offline=True` rebuilds everything from the cache plus `manual/`.

## Status (2026-10-27)

- 9 seasons × 5 awards = 45 contests are located, each with its Drive link and file name.
  All 45 are PDFs.
- 0 contests have been parsed, because no manual files are present yet. The output
  CSVs are written with a header row only.

Gaps:
- The PDFs need a one-time manual download.
- The 2017-18 Hart file is labelled "corrected results".
- Whether the PDFs include official totals is unknown until they are downloaded. Official
  totals are also on NHL.com, but they are not used here.


## Parser for the real PHWA PDFs (added after the user downloaded them)

`parse_phwa_pdf` reads the PHWA's own table, the same every season 2017-18 to 2025-26:
No. | voter last | voter first | affiliation | 5 cells "Player Name, Team" (all five awards,
Lady Byng included, are 10-7-5-3-1). Layout text from pypdf (shared reader in
`nba_pdf.py`). Typos handled: a period typed for the comma ("Evgeni Malkin. Pittsburgh
Penguins"), a pick split over two cells ("Jesper Wallstedt," + "Minnesota Wild"; "Riley
Sheahan, Edmonton" + "Oilers"), a missing comma ("Artemi Panarin Columbus Blue Jackets",
split at a team name seen elsewhere). One spelling and id per player across seasons
(accents kept; aliases Sebastain/Sebastian Aho, Mitchell/Mitch Marner, Christopher/Chris
Tanev).

Result: 45 contests, 7,895 ballots, every ballot 5 places. The PDFs carry no totals, so
published tallies from news reports are checked in the tests: 2017-18 Hart (Hall 1264,
MacKinnon 1194, with place counts), 2021-22 Norris (Makar 1631, Josi 1606, with place
counts), 2024-25 Hart (Hellebuyck 1346, Draisaitl 1209), 2025-26 Hart (Kucherov 1436,
McDavid 1426) - all exact.
