# Site text edits

A running list of the owner's text changes to ballmonitor.com and where each one was put. Claude
adds a line for every change it makes on the owner's behalf (see CLAUDE.md, "Text edits from the
Editor"). Changes the owner types straight into a page's HTML in Claude UI's Editor save themselves
and show up in `git diff`; they're listed here only when Claude carried them somewhere else too.

Where text lives:

| on the page | written in |
|---|---|
| headings, intros, sidebar, footer, Games cards, About/Privacy/Terms | the page file itself, `web/site/<address>/index.html` (edit in place) |
| a forecast page's title, summary, "How this works" (also its home card and menu link) | `web/site/<address>/index.html`, the `data-text` elements |
| a forecast page's headline, table/chart titles, subtitles, notes, dropdown intros | `models/<model>/site.py` (the view's `id` is in `data-src`) |
| a data table's title, summary, "How this works" (also its home card and menu link) | `web/tables.toml`, the `[[table]]` with that `id` |
| a chart's name and intro | `web/charts.toml`, the `[[chart]]` with that `id` |
| the Charts home card and menu link | `web/site/charts/index.html` (its title and summary) |
| buttons and labels like "← Home", "Show all", "What the columns mean" | `web/static/site.js` |

Every piece of text drawn by the script carries `data-src="<file>#<key>"` naming its source.

## Log

| date | page | change | written to |
|---|---|---|---|
