"""One real HTML file per public address, so search engines and link previews see every page.

The site is one page (site.html + site.js) that draws whatever address it is opened at. The build
writes a copy of site.html at every address (`/ncaaf_bowls/`, `/ncaaf_bowls/team/georgia/`,
`/tables/qb-games/`, `/charts/aging-power/`, `/about/`, ...), each with its own <title>, description,
canonical link and share tags, and with the page's words (title, summary, headline, the list of
teams/bowls/years, "How this works") already in <main>, so the page reads without JavaScript.
site.js then replaces <main>'s contents with the full tables and charts. The text pages (About,
Privacy, Terms) are HTML fragments in web/pages/*.html, shown as they are.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from ballmonitor.core import views

PAGES_DIR = Path(__file__).resolve().parent / "pages"
SITE_NAME = "Ball Monitor"
# The text pages: address -> fragment file (web/pages/<name>.html). Linked from every page's footer.
TEXT_PAGES = ("about", "privacy", "terms")
# First parts of addresses the site itself uses; a page address may not be one of these.
RESERVED = {"static", "data", "charts", "tables", "triple", "lineup", "27k", "editor.html", "replay.html",
            "index.html", "404.html", "robots.txt", "sitemap.xml", *TEXT_PAGES}

esc = html.escape


def _meta(text: str, limit: int = 200) -> str:
    """A description for <meta>: one line, at most `limit` characters, cut at a word."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def shell(template: str, *, site_url: str, path: str, title: str, description: str, body: str,
          static: bool = False) -> str:
    """site.html with this page's head tags and `body` inside <main id="app">. `static`: site.js
    leaves <main> as it is (the text pages)."""
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
        (r'(<main class="ss-main" id="app"[^>]*>).*?(</main>)',
         lambda m: m.group(1).replace('id="app"', 'id="app" data-static' if static else 'id="app"')
         + "\n" + body + "\n    " + m.group(2)),
    ]
    out = template
    for pattern, repl in subs:
        # a function, so backslashes in a title or description are kept as they are
        out, n = re.subn(pattern, repl if callable(repl) else (lambda _m, r=repl: r), out, count=1, flags=re.S)
        if n != 1:  # site.html changed shape: fail the build rather than ship pages without their tags
            raise ValueError(f"site.html: no match for {pattern[:40]!r}")
    return out


def _cell(cls: str, *parts: str) -> str:
    return f'<section class="ss-cell {cls}">' + "".join(p for p in parts if p) + "</section>"


def _head(cls: str, kicker: str, title: str, summary: str = "", headline: str = "", updated: str = "") -> str:
    return _cell(f"{cls} page-head",
                 '<a class="back" href="/">← Home</a>',
                 f'<div class="ss-kicker">{esc(kicker)}</div>' if kicker else "",
                 f'<h1 class="ss-title">{esc(title)}</h1>',
                 f'<p class="summary">{esc(summary)}</p>' if summary else "",
                 f'<p class="headline">{esc(headline)}</p>' if headline else "",
                 f'<span class="ss-chip">{esc(updated)}</span>' if updated else "")


def _pickers(views_: list[dict]) -> list[dict]:
    return [v for v in views_ if v.get("kind") == "picker"]


def option_slug(o: dict) -> str:
    return o.get("slug") or views.slug(o["label"])


def model_pages(address: str, page: dict, cls: str) -> dict[str, tuple[str, str, str]]:
    """{path: (title, description, body)} for a forecast page and each of its picker options."""
    out = {}
    how = _cell(f"{cls} how", '<div class="ss-band">How this works</div>', f"<p>{esc(page['how'])}</p>") \
        if page.get("how") else ""
    sections = []
    for v in page["views"]:
        if v.get("kind") == "picker":
            links = "".join(f'<li><a href="/{address}/{v["id"]}/{option_slug(o)}/">{esc(o["label"])}</a></li>'
                            for o in v["options"])
            sections.append(_cell(cls, f'<div class="ss-band">{esc(v["title"])}</div>',
                                  f'<p class="subtitle">{esc(v["subtitle"])}</p>' if v.get("subtitle") else "",
                                  f'<ul class="option-links">{links}</ul>'))
        else:
            sections.append(_cell(cls, f'<div class="ss-band">{esc(v["title"])}</div>',
                                  f'<p class="subtitle">{esc(v["subtitle"])}</p>' if v.get("subtitle") else "",
                                  '<p class="loading">Loading the numbers…</p>'))
    head = _head(cls, page.get("sport", ""), page["title"], page.get("summary", ""), page.get("headline", ""),
                 page.get("updated", ""))
    out[f"/{address}/"] = (page["title"], " ".join(filter(None, [page.get("summary"), page.get("headline")])),
                           "\n".join([head, *sections, how]))
    for v in _pickers(page["views"]):
        for o in v["options"]:
            intro = o.get("intro", "")
            body = "\n".join([
                _head(cls, page.get("sport", ""), page["title"], page.get("summary", "")),
                _cell(cls, f'<div class="ss-band">{esc(v["title"])}: {esc(o["label"])}</div>',
                      f'<p class="intro">{esc(intro)}</p>' if intro else "",
                      f'<p><a href="/{address}/">All of {esc(page["title"])}</a></p>'),
                how])
            title = f"{o['label']}: {page['title']}"
            out[f"/{address}/{v['id']}/{option_slug(o)}/"] = (title, intro or page.get("summary", ""), body)
    return out


def home_page(site: dict) -> str:
    """The home page's links, grouped by sport (site.js redraws it from the same data/site.json)."""
    groups: dict[str, list[dict]] = {}
    for m in site["models"]:
        groups.setdefault(m["sport"], []).append(m)

    def item(href: str, title: str, summary: str) -> str:
        return f'<li><a class="model-link" href="{href}"><b>{esc(title)}</b><p>{esc(summary)}</p></a></li>'

    cells = [_cell(views.cell_class(sport), f'<div class="ss-band">{esc(sport)}</div>', '<ul class="model-list">'
                   + "".join(item(f"/{m['name']}/", m["title"], m["summary"]) for m in ms) + "</ul>")
             for sport, ms in groups.items()]
    if site.get("tables"):
        cells.append(_cell("ss-p4", '<div class="ss-band">Data tables</div>', '<ul class="model-list">'
                           + "".join(item(f"/tables/{t['id']}/", t["title"], t["summary"]) for t in site["tables"])
                           + "</ul>"))
    if site.get("charts"):
        cells.append(_cell(views.cell_class("Baseball"), '<div class="ss-band">Charts</div>',
                           '<ul class="model-list">' + item("/charts/", "Baseball charts", CHARTS_SUMMARY) + "</ul>"))
    return "\n".join(cells)


def table_page(t: dict, cls: str) -> tuple[str, str, str]:
    labels = t.get("labels", {})
    key = "".join(f"<dt>{esc(k)}</dt><dd>{esc(f'{labels[k]}: {v}' if labels.get(k, k).lower() != k else v)}</dd>"
                  for k, v in t.get("columns", {}).items())
    body = "\n".join([
        _head(cls, f"{t['sport'] + ' · ' if t.get('sport') else ''}Data table", t["title"], t["summary"]),
        _cell(f"{cls} live-cell", '<p class="loading">Loading the table…</p>'),
        _cell(f"{cls} how", '<div class="ss-band">How this works</div>', f"<p>{esc(t['how'])}</p>",
              f'<details class="column-key"><summary>What the columns mean</summary><dl>{key}</dl></details>'
              if key else "") if t.get("how") else ""])
    return t["title"], t["summary"], body


CHARTS_SUMMARY = ("Every big-league season from 1871 to 2024, charted. Pick a chart, or change any of its boxes "
                  "and draw it again.")


def chart_pages(charts: list[dict], cls: str) -> dict[str, tuple[str, str, str]]:
    links = "".join(f'<li><a href="/charts/{c["id"]}/">{esc(c["title"])}</a></li>' for c in charts)
    out = {"/charts/": ("Baseball charts", CHARTS_SUMMARY,
                        _head(cls, "Baseball · Charts", "Baseball charts", CHARTS_SUMMARY)
                        + _cell(cls, f'<ul class="option-links">{links}</ul>'))}
    for c in charts:
        out[f"/charts/{c['id']}/"] = (f"{c['title']}: Baseball charts", c["intro"], "\n".join([
            _head(cls, "Baseball · Charts", "Baseball charts", CHARTS_SUMMARY),
            _cell(cls, f'<div class="ss-band">{esc(c["title"])}</div>', f'<p class="chart-intro">{esc(c["intro"])}</p>',
                  '<p class="loading">Loading the chart…</p>')]))
    return out


def text_page(name: str) -> tuple[str, str, str]:
    """A text page's (title, description, body) from web/pages/<name>.html, whose first lines are
    <!-- title: ... --> and <!-- description: ... -->."""
    text = (PAGES_DIR / f"{name}.html").read_text(encoding="utf-8")
    fields = dict(re.findall(r"<!--\s*(title|description):\s*(.*?)\s*-->", text))
    if "title" not in fields or "description" not in fields:
        raise ValueError(f"web/pages/{name}.html needs <!-- title: … --> and <!-- description: … --> lines")
    return fields["title"], fields["description"], text


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
