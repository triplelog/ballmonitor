"""One real HTML file per public address, built from one real HTML source file per page.

Every page of the site has a source file in web/site/ at its own address: `index.html` (home),
`<address>/index.html` (each forecast page), `charts/index.html`, `tables/index.html` (the template
of every /tables/<id>/), `about/`, `privacy/`, `terms/` and `404.html`. A source file is a whole
page, so Claude UI's Editor can show and edit it as it is: its words (title, summary, "How this
works", the home page's intro and games) are plain HTML in the file. The parts that come from the
numbers are marked:

- `data-slot="<name>"`: an element the build (and then site.js) fills: a forecast page's
  `headline` and `views`, the home page's `models`, the charts page's `chart-picks` and `chart`,
  the tables template's `table`;
- `data-fill="<key>"`: a span whose text is a value from the page's `fill` (site.py), e.g. the
  newest recruiting class;
- `data-text="title|summary|how"`: the page's words, read into data/views/<address>.json (home
  page cards, the menu, link previews).

The blocks between `<!-- shell:head -->`, `<!-- shell:sidebar -->` and `<!-- shell:footer -->`
markers are the same on every page. The build takes them from index.html; `python -m
ballmonitor.web.pages sync` copies them into the other source files (Claude UI's Editor does that
too when one is edited there).

The build writes a copy of the source file at every address it serves (a forecast page's file
also at each of its dropdown options, /ncaaf_bowls/team/georgia/; the charts file at every chart),
with that address's <title>, description, canonical link and share tags, and the slots filled with
the page's words and links, so the page reads without JavaScript. site.js then fills the slots with
the full tables and charts.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from ballmonitor.core import views

SITE_DIR = Path(__file__).resolve().parent / "site"
SITE_NAME = "Ball Monitor"
# The text pages (web/site/<name>/index.html), linked from every page's footer.
TEXT_PAGES = ("about", "privacy", "terms")
# First parts of addresses the site itself uses; a page address may not be one of these.
RESERVED = {"static", "data", "charts", "tables", "triple", "lineup", "27k", "editor.html", "replay.html",
            "index.html", "404.html", "robots.txt", "sitemap.xml", *TEXT_PAGES}
SHARED = ("shell:head", "shell:sidebar", "shell:footer")   # identical on every page; index.html's win

esc = html.escape


# ── source files ──────────────────────────────────────────────────────────────

def address_file(address: str) -> Path:
    """The source file of a top-level page (`ncaaf_bowls`, `charts`, `about`; "" = home)."""
    return SITE_DIR / address / "index.html" if address else SITE_DIR / "index.html"


def source_file(path: str) -> Path | None:
    """The source file that serves an address: its own file, else its first part's file (a
    forecast page's dropdown options, a chart, a data table). None when there is none."""
    parts = [p for p in path.split("/") if p]
    if any(p.startswith(".") or "\\" in p for p in parts):
        return None
    if parts and parts[-1] == "index.html":
        parts.pop()
    for n in (len(parts), 1):
        f = address_file("/".join(parts[:n]))
        if n <= len(parts) and f.is_file():
            return f
    return None


def source_files() -> list[Path]:
    """Every page source (index.html files; 404.html stands alone)."""
    return sorted(SITE_DIR.rglob("index.html"))


def _block(name: str) -> re.Pattern:
    return re.compile(rf"<!-- {re.escape(name)} -->.*?<!-- /{re.escape(name)} -->", re.S)


def shared_blocks(text: str) -> dict[str, str]:
    return {name: m.group(0) for name in SHARED if (m := _block(name).search(text))}


_SIDE_H1 = re.compile(r'<h1 class="side-title">(.*?)</h1>', re.S)


def with_shared(text: str, master: str, home: bool = False) -> str:
    """`text` with its shell blocks replaced by `master`'s (each block must be in both). The
    sidebar's `<h1 class="side-title">` is the home page's heading; other pages have their own
    <h1>, so there it becomes a <p> with the same words and look."""
    for name, block in shared_blocks(master).items():
        if not home:
            block = _SIDE_H1.sub(r'<p class="side-title">\1</p>', block)
        text, n = _block(name).subn(lambda _m, b=block: b, text, count=1)
        if n != 1:
            raise ValueError(f"a page source is missing its <!-- {name} --> block")
    return text


def sync() -> list[Path]:
    """Copy index.html's shell blocks into every other source file. Returns the files changed."""
    master = address_file("").read_text(encoding="utf-8")
    changed = []
    for f in source_files():
        text = f.read_text(encoding="utf-8")
        new = with_shared(text, master, home=f == address_file(""))
        if new != text:
            f.write_text(new, encoding="utf-8")
            changed.append(f)
    return changed


_TEXT = re.compile(r'<(\w+)\b[^>]*\bdata-text="(\w+)"[^>]*>(.*?)</\1\s*>', re.S)
_FILL = re.compile(r'(<span\b[^>]*\bdata-fill="(\w+)"[^>]*>)(.*?)(</span>)', re.S)


def plain(fragment: str) -> str:
    """Text of an HTML fragment: comments and tags dropped, entities read, whitespace collapsed."""
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def read_text(path: Path) -> dict[str, str]:
    """A page source's words: {"title": ..., "summary": ..., "how": ...} from its data-text
    elements, with each data-fill span as a {placeholder} (filled from the page's `fill`).
    Empty ones are left out; {} when the file doesn't exist."""
    if not path.is_file():
        return {}
    out = {}
    for _tag, key, inner in _TEXT.findall(path.read_text(encoding="utf-8")):
        text = plain(_FILL.sub(lambda m: "{" + m.group(2) + "}", inner))
        if text and key not in out:
            out[key] = text
    return out


def fill_spans(text: str, fill: dict) -> str:
    return _FILL.sub(lambda m: m.group(1) + (esc(str(fill[m.group(2)])) if m.group(2) in fill else m.group(3))
                     + m.group(4), text)


def fill_slots(text: str, slots: dict[str, str]) -> str:
    """Put each slot's HTML inside its `data-slot` element (a slot missing from the page fails the
    build rather than ship a page without its numbers)."""
    for name, content in slots.items():
        pattern = re.compile(rf'(<(\w+)\b[^>]*\bdata-slot="{re.escape(name)}"[^>]*>)(.*?)(</\2\s*>)', re.S)
        text, n = pattern.subn(lambda m, c=content: m.group(1) + c + m.group(4), text, count=1)
        if n != 1:
            raise ValueError(f'page source has no data-slot="{name}" element')
    return text


def _meta(text: str, limit: int = 200) -> str:
    """A description for <meta>: one line, at most `limit` characters, cut at a word."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def head_title(text: str) -> str:
    m = re.search(r"<title>([^<]*)</title>", text)
    title = html.unescape(m.group(1)) if m else SITE_NAME
    return title.removesuffix(f" · {SITE_NAME}")


def head_description(text: str) -> str:
    m = re.search(r'<meta name="description" content="([^"]*)">', text)
    return html.unescape(m.group(1)) if m else ""


def shell(template: str, *, site_url: str, path: str, title: str, description: str,
          slots: dict[str, str] | None = None, fill: dict | None = None, master: str | None = None) -> str:
    """A page source made into the page at `path`: its head tags for this address, its slots and
    data-fill spans filled, and (given `master`, the home page source) the shared shell blocks."""
    url = site_url + path
    full_title = title if title == SITE_NAME else f"{title} · {SITE_NAME}"
    description = _meta(description)
    subs = [
        (r"<title>[^<]*</title>", f"<title>{esc(full_title)}</title>"),
        (r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{esc(description)}">'),
        (r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{esc(url)}">'),
        (r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{esc(full_title)}">'),
        (r'<meta property="og:description" content="[^"]*">',
         f'<meta property="og:description" content="{esc(description)}">'),
        (r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{esc(url)}">'),
    ]
    out = with_shared(template, master, home=path == "/") if master else template
    for pattern, repl in subs:
        # a function, so backslashes in a title or description are kept as they are
        out, n = re.subn(pattern, lambda _m, r=repl: r, out, count=1)
        if n != 1:  # a source file changed shape: fail the build rather than ship pages without their tags
            raise ValueError(f"page source: no match for {pattern[:40]!r}")
    return fill_spans(fill_slots(out, slots or {}), fill or {})


# ── the generated parts (what the slots hold before site.js runs) ───────────────

def _cell(cls: str, *parts: str) -> str:
    return f'<section class="ss-cell {cls}">' + "".join(p for p in parts if p) + "</section>"


def _pickers(views_: list[dict]) -> list[dict]:
    return [v for v in views_ if v.get("kind") == "picker"]


def option_slug(o: dict) -> str:
    return o.get("slug") or views.slug(o["label"])


def headline(page: dict) -> str:
    return ((f'<p class="headline">{esc(page["headline"])}</p>' if page.get("headline") else "")
            + (f'<span class="ss-chip">{esc(page["updated"])}</span>' if page.get("updated") else ""))


def _pct(p: float) -> str:
    """A 0-1 chance as site.js's fmt(p, "pct") writes it (whole percents)."""
    if p == 0:
        return "–"
    if 0 < p * 100 < 0.5:
        return "<1%"
    if 99.5 < p * 100 < 100:
        return ">99%"
    return f"{p * 100:.0f}%"


def bracket_html(v: dict, address: str, slugs: dict[str, set[str]], model: str = "") -> str:
    """A views.bracket as HTML, the same markup site.js's renderBracket draws (one column per
    round; team names link to their picker option when it exists)."""
    def name(text: str) -> str:
        link = v.get("link")
        if link and views.slug(text) in slugs.get(link, set()):
            return f'<a href="/{address}/{link}/{views.slug(text)}/">{esc(text)}</a>'
        return esc(text)

    def side(t: dict, won: bool) -> str:
        p = t.get("p")
        return (f'<li class="bk-team{" won" if won else ""}"><span class="bk-seed">{esc(str(t.get("seed", "")))}</span>'
                f'<span class="bk-name">{name(t["name"])}</span>'
                f'<span class="bk-p">{_pct(p) if isinstance(p, (int, float)) else ""}</span></li>')

    src = f' data-src="ballmonitor/models/{esc(model)}/site.py#{esc(v["id"])}.rounds"' if model else ""
    cols = []
    for r, rd in enumerate(v["rounds"]):
        games = "".join(
            '<div class="bk-game"><ul>' + "".join(side(t, g.get("winner") == i) for i, t in enumerate(g["teams"])) + "</ul>"
            + (f'<p class="bk-where">{esc(g["where"])}</p>' if g.get("where") else "") + "</div>"
            for g in rd["games"])
        if v.get("champion") and r == len(v["rounds"]) - 1:   # the champion, under the last game
            games += f'<p class="bk-champ"><span>Champion</span>{name(v["champion"])}</p>'
        cols.append(f'<div class="bk-round"><h4 class="bk-round-name"{src}>{esc(rd["name"])}</h4><div class="bk-games">{games}</div></div>')
    return f'<div class="bracket" tabindex="0" role="group" aria-label="{esc(v["title"])}">{"".join(cols)}</div>'


def model_pages(address: str, page: dict, cls: str) -> dict[str, tuple[str, str, dict]]:
    """{path: (title, description, slots)} for a forecast page and each of its picker options."""
    out = {}
    sections = []
    slugs = {v["id"]: {option_slug(o) for o in v["options"]} for v in _pickers(page["views"])}
    for v in page["views"]:
        if v.get("kind") == "bracket":   # drawn whole: it reads without the script
            sections.append(_cell(cls, f'<div class="ss-band">{esc(v["title"])}</div>',
                                  f'<p class="subtitle">{esc(v["subtitle"])}</p>' if v.get("subtitle") else "",
                                  bracket_html(v, address, slugs, page.get("model", "")),
                                  f'<p class="note">{esc(v["note"])}</p>' if v.get("note") else ""))
        elif v.get("kind") == "picker":
            links = "".join(f'<li><a href="/{address}/{v["id"]}/{option_slug(o)}/">{esc(o["label"])}</a></li>'
                            for o in v["options"])
            sections.append(_cell(cls, f'<div class="ss-band">{esc(v["title"])}</div>',
                                  f'<p class="subtitle">{esc(v["subtitle"])}</p>' if v.get("subtitle") else "",
                                  f'<ul class="option-links">{links}</ul>'))
        else:
            sections.append(_cell(cls, f'<div class="ss-band">{esc(v["title"])}</div>',
                                  f'<p class="subtitle">{esc(v["subtitle"])}</p>' if v.get("subtitle") else "",
                                  '<p class="loading">Loading the numbers…</p>'))
    out[f"/{address}/"] = (page["title"], " ".join(filter(None, [page.get("summary"), page.get("headline")])),
                           {"headline": headline(page), "views": "".join(sections)})
    for v in _pickers(page["views"]):
        for o in v["options"]:
            intro = o.get("intro", "")
            option = _cell(cls, f'<div class="ss-band">{esc(v["title"])}: {esc(o["label"])}</div>',
                           f'<p class="intro">{esc(intro)}</p>' if intro else "",
                           f'<p><a href="/{address}/">All of {esc(page["title"])}</a></p>')
            title = f"{o['label']}: {page['title']}"
            out[f"/{address}/{v['id']}/{option_slug(o)}/"] = (title, intro or page.get("summary", ""),
                                                             {"headline": "", "views": option})
    return out


def home_page(site: dict) -> dict[str, str]:
    """The home page's links, grouped by sport (site.js redraws them from the same data/site.json)."""
    groups: dict[str, list[dict]] = {}
    for m in site["models"]:
        groups.setdefault(m["sport"], []).append(m)

    def item(href: str, title: str, summary: str, srcs: tuple[str, str]) -> str:
        return (f'<li><a class="model-link" href="{href}"><b data-src="{srcs[0]}">{esc(title)}</b>'
                f'<p data-src="{srcs[1]}">{esc(summary)}</p></a></li>')

    def card_list(items: list[str]) -> str:
        return '<ul class="model-list">' + "".join(items) + "</ul>"

    cells = []
    if site.get("tables"):
        cells.append(_cell("ss-p4", '<div class="ss-band">Data tables</div>', card_list(
            [item(f"/tables/{t['id']}/", t["title"], t["summary"], (table_src(t, "title"), table_src(t, "summary")))
             for t in site["tables"]])))
    cells += [_cell(views.cell_class(sport), f'<div class="ss-band">{esc(sport)}</div>', card_list(
                  [item(f"/{m['name']}/", m["title"], m["summary"],
                        (page_src(m["name"], "title"), page_src(m["name"], "summary"))) for m in ms]))
              for sport, ms in groups.items()]
    if site.get("charts"):
        words = charts_text()
        cells.append(_cell(views.cell_class("Baseball"), '<div class="ss-band">Charts</div>', card_list(
            [item("/charts/", words.get("title", "Baseball charts"), words.get("summary", ""),
                  (page_src("charts", "title"), page_src("charts", "summary")))])))
    return {"models": "".join(cells)}


def table_page(t: dict, cls: str) -> tuple[str, str, dict]:
    labels = t.get("labels", {})
    key = "".join(f"<dt>{esc(k)}</dt><dd>{esc(f'{labels[k]}: {v}' if labels.get(k, k).lower() != k else v)}</dd>"
                  for k, v in t.get("columns", {}).items())
    kicker = f"{t['sport'] + ' · ' if t.get('sport') else ''}Data table"
    body = "".join([
        _cell(f"{cls} page-head", '<a class="back" href="/">← Home</a>',
              f'<div class="ss-kicker">{esc(kicker)}</div>', f'<h1 class="ss-title" data-src="{table_src(t, "title")}">{esc(t["title"])}</h1>',
              f'<p class="summary" data-src="{table_src(t, "summary")}">{esc(t["summary"])}</p>'),
        _cell(f"{cls} live-cell", '<p class="loading">Loading the table…</p>'),
        _cell(f"{cls} how", '<div class="ss-band">How this works</div>', f'<p data-src="{table_src(t, "how")}">{esc(t["how"])}</p>',
              f'<details class="column-key"><summary>What the columns mean</summary><p class="key-hint">{esc(next(("Type a filter with these short names, like " + x["filter"] + "." for x in t.get("examples", []) if x.get("filter")), "Type a filter with these short names."))}</p><dl>{key}</dl></details>'
              if key else "") if t.get("how") else ""])
    return t["title"], t["summary"], {"table": body}


def charts_text() -> dict[str, str]:
    """The charts page's words (title, summary), as written in web/site/charts/index.html."""
    return read_text(address_file("charts"))


# Where script-drawn text is written (data-src="<file>#<key>", repo-relative; site.js marks the same
# elements), so a change made by eye in Claude UI's Editor can be put in its source.
def page_src(address: str, key: str) -> str:
    return f"ballmonitor/web/site/{address}/index.html#{key}"


def table_src(t: dict, key: str) -> str:
    return f"ballmonitor/web/tables.toml#{t['id']}.{key}"


def chart_src(c: dict, key: str) -> str:
    return f"ballmonitor/web/charts.toml#{c['id']}.{key}"


def chart_pages(charts: list[dict]) -> dict[str, tuple[str, str, dict]]:
    links = '<ul class="option-links">' + "".join(
        f'<li><a href="/charts/{c["id"]}/">{esc(c["title"])}</a></li>' for c in charts) + "</ul>"
    words = read_text(address_file("charts"))
    title, summary = words.get("title", "Baseball charts"), words.get("summary", "")
    out = {"/charts/": (title, summary, {"chart-picks": links, "chart": ""})}
    for c in charts:
        out[f"/charts/{c['id']}/"] = (f"{c['title']}: {title}", c["intro"], {"chart-picks": links, "chart": (
            f'<div class="ss-band" data-src="{chart_src(c, "title")}">{esc(c["title"])}</div>'
            f'<p class="chart-intro" data-src="{chart_src(c, "intro")}">{esc(c["intro"])}</p>'
            '<p class="loading">Loading the chart…</p>')})
    return out


def text_page(name: str) -> tuple[str, str, dict]:
    """A text page's (title, description, slots): its words are all in its source file."""
    text = address_file(name).read_text(encoding="utf-8")
    return head_title(text), head_description(text), {}


def redirect_page(site_url: str, to_path: str) -> str:
    """A stub at an old address that sends the reader (and search engines) to the new one."""
    url = esc(site_url + to_path)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Moved · {SITE_NAME}</title>'
            f'<link rel="canonical" href="{url}"><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={esc(to_path)}">'
            f'<script>location.replace({to_path!r} + location.search + location.hash)</script></head>'
            f'<body><p>This page moved to <a href="{esc(to_path)}">{url}</a>.</p></body></html>')


def write(target: Path, path: str, text: str) -> None:
    """Write `text` as `<target><path>index.html` (path like /ncaaf_bowls/team/georgia/)."""
    dest = target / path.strip("/") / "index.html" if path.strip("/") else target / "index.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] != ["sync"]:
        sys.exit("usage: python -m ballmonitor.web.pages sync   (copy index.html's shell blocks to every page)")
    changed = sync()
    print("\n".join(str(f.relative_to(SITE_DIR)) for f in changed) or "every page already matches index.html")
