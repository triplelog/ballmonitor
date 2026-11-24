// Ball Monitor public page. Shows the tables and charts that `ballmonitor build-site` wrote to
// data/site.json and data/views/<model>.json (from each model's site.py). It never runs a
// model: every number on the page was computed at build time.
// Addresses are real paths (/ncaaf_bowls/, /ncaaf_bowls/team/georgia/, /tables/<id>/, /charts/<id>/):
// each page has a source file in web/site/ holding its words as plain HTML, and the build writes it
// at every address it serves (web/pages.py). This script leaves those words alone and fills only the
// parts marked data-slot (tables, charts, headline) and data-fill (a number in a sentence). Links
// between pages are followed without reloading: the new page's <main> is fetched and swapped in.
// Old #/ addresses are turned into paths on arrival.
"use strict";

const app = document.getElementById("app");
const cache = {};
// The open model page and its pickers: /<model>/<picker id>/<option slug>/ selects an option.
let current = { model: null, pickers: {} };
const slugify = (t) => String(t).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, ...kids) {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return n;
}

async function getJSON(path) {
  if (!cache[path]) {
    cache[path] = fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return r.json();
    });
  }
  return cache[path];
}

// ── number formatting (values arrive raw: seconds, 0-1 probabilities) ────────
function fmtTime(sec) {
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const pad = (x) => String(x).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function fmt(v, kind = "text", decimals, zeroDash = true) {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v !== "number") return String(v);
  switch (kind) {
    case "pct": {
      const d = decimals ?? 0;
      if (v === 0) return zeroDash ? "–" : "0%";
      const p = v * 100;
      if (p > 0 && p < 0.5 * Math.pow(10, -d)) return `<${(Math.pow(10, -d)).toString()}%`;
      if (p < 100 && p > 100 - 0.5 * Math.pow(10, -d)) return `>${(100 - Math.pow(10, -d)).toString()}%`;
      return `${p.toFixed(d)}%`;
    }
    case "time": return fmtTime(v);
    case "int": return Math.round(v).toLocaleString("en-US");
    case "signed": {
      const d = decimals ?? 1;
      return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
    }
    case "number": return v.toLocaleString("en-US", { minimumFractionDigits: decimals ?? 1, maximumFractionDigits: decimals ?? 1 });
    default: return String(v);
  }
}

// Where a piece of script-drawn text is written, as a data-src attribute ("<file>#<key>", repo-relative),
// so a change made by eye in Claude UI's Editor can be put in its source (CLAUDE.md, "Text edits").
const SITE_SRC = "ballmonitor/web/site";
const src = (file, key) => ({ "data-src": key ? `${file}#${key}` : file });
const pageSrc = (address, key) => src(`${SITE_SRC}/${address}/index.html`, key);
const tableSrc = (t, key) => src("ballmonitor/web/tables.toml", `${t.id}.${key}`);
const chartSrc = (c, key) => src("ballmonitor/web/charts.toml", `${c.id}.${key}`);
// a forecast page's tables, charts, headline and dropdown intros come from its model's site.py
let viewFile = "";
const viewSrc = (key) => src(viewFile, key);
// the charts page's name and summary, as written in web/site/charts/index.html
const MORE_SPORT = "More sports";   // its pages go in the home page's "More tables and charts" card
const chartsTitle = (site) => (site.charts_text || {}).title || "Baseball charts";

// ── Shioh cells: each sport owns one cell colour ─────────────────────────────
// (the map is core/views.py SPORT_CELL, sent in data/site.json as `cells`)
let SPORT_CELL = {};
const cellClass = (sport) => SPORT_CELL[sport] || "ss-p1";
const cell = (cls, ...kids) => el("section", { class: `ss-cell ${cls}` }, ...kids);

// sidebar: one link per forecast page, grouped like the home page
async function renderNav(active) {
  const site = await getJSON("/data/site.json");
  const nav = document.getElementById("nav-models");
  if (!nav.childElementCount) {
    nav.append(...(site.tables || []).map((t) => el("a", { href: `/tables/${t.id}/`, "data-route": `tables/${t.id}`, ...tableSrc(t, "title") }, t.title)));
    nav.append(...site.models.map((m) => el("a", { href: `/${m.name}/`, "data-route": m.name, ...pageSrc(m.name, "title") }, m.title)));
    if ((site.charts || []).length) nav.append(el("a", { href: "/charts/", "data-route": "charts", ...pageSrc("charts", "title") }, chartsTitle(site)));
  }
  for (const a of document.querySelectorAll(".ss-nav a[data-route]")) {
    if (a.dataset.route === active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

// ── the page's own HTML (web/site/<address>/index.html) ─────────────────────────
// <main data-page="<key>"> says which page's words are on screen. Going to another page fetches
// that address and swaps its <main> in (its words, its empty slots); then the slots are filled.
async function ensurePage(key) {
  if (app.dataset.page === key) return true;
  try {
    const r = await fetch(location.pathname);
    if (!r.ok) throw new Error(`${location.pathname}: ${r.status}`);
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    const main = doc.getElementById("app");
    if (!main) throw new Error(`${location.pathname}: no <main id="app">`);
    if (key === "") homeDescription = metaDescription(doc) || homeDescription;
    for (const a of [...app.attributes]) if (a.name !== "id") app.removeAttribute(a.name);
    for (const a of main.attributes) if (a.name !== "id") app.setAttribute(a.name, a.value);
    app.replaceChildren(...[...main.childNodes].map((n) => document.importNode(n, true)));
    return true;
  } catch (e) {
    console.error(e);
    location.reload();   // let the browser load it the ordinary way
    return false;
  }
}

// Fill a slot (an element marked data-slot="<name>"); a page whose slot was removed gets the
// content at the end of <main> instead, so no numbers go missing.
function fillSlot(name, ...kids) {
  const slot = app.querySelector(`[data-slot="${name}"]`);
  if (slot) slot.replaceChildren(...kids.flat().filter(Boolean));
  else app.append(...kids.flat().filter(Boolean));
}

// A value in a sentence (<span data-fill="first_year">), from the page's `fill` (site.py).
function fillSpans(fill) {
  for (const n of app.querySelectorAll("[data-fill]")) {
    if (fill && fill[n.dataset.fill] !== undefined) n.textContent = String(fill[n.dataset.fill]);
  }
}

// A page with no source of its own (not found, an error): drawn whole into <main>.
function drawWhole(...kids) {
  for (const a of [...app.attributes]) if (a.name !== "id" && a.name !== "class") app.removeAttribute(a.name);
  app.dataset.page = "!";
  app.replaceChildren(...kids);
}

// ── home ──────────────────────────────────────────────────────────────────────
// The headline, intro and games list are written in web/site/index.html; the forecast pages,
// tables and charts come from data/site.json.
async function renderHome() {
  const site = await getJSON("/data/site.json");
  if (!(await ensurePage(""))) return;
  setHead("Ball Monitor", homeDescription, "/");
  // Sport cards before the Games card (web/site/index.html); the "More sports" pages and the
  // charts share one card after it (slot "more"), like pages.home_page.
  const groups = {};
  for (const m of site.models) if (m.sport !== MORE_SPORT) (groups[m.sport] = groups[m.sport] || []).push(m);
  const more = site.models.filter((m) => m.sport === MORE_SPORT);
  const modelItem = (m) => el("li", {}, el("a", { class: "model-link", href: `/${m.name}/` },
    el("b", pageSrc(m.name, "title"), m.title),
    el("p", pageSrc(m.name, "summary"), m.summary),
    m.updated ? el("span", { class: "ss-chip" }, m.updated) : null));
  fillSlot("models",
    (site.tables || []).length ? cell("ss-p4",
      el("div", { class: "ss-band" }, "Data tables"),
      el("ul", { class: "model-list" }, site.tables.map((t) =>
        el("li", {}, el("a", { class: "model-link", href: `/tables/${t.id}/` },
          el("b", tableSrc(t, "title"), t.title), el("p", tableSrc(t, "summary"), t.summary)))))) : null,
    ...Object.entries(groups).map(([sport, models]) =>
      cell(cellClass(sport),
        el("div", { class: "ss-band" }, sport),
        el("ul", { class: "model-list" }, models.map(modelItem)))),
  );
  const charts = (site.charts || []).length;
  fillSlot("more", more.length || charts ? cell("ss-p2",
    el("div", { class: "ss-band" }, "More tables and charts"),
    el("ul", { class: "model-list" }, more.map(modelItem),
      charts ? el("li", {}, el("a", { class: "model-link", href: "/charts/" },
        el("b", pageSrc("charts", "title"), chartsTitle(site)),
        el("p", pageSrc("charts", "summary"), (site.charts_text || {}).summary || ""))) : null)) : null);
  renderNav("");
  window.scrollTo(0, 0);
}

// ── model page ───────────────────────────────────────────────────────────────
async function renderModel(name, pick) {
  if (current.model === name && pick && current.pickers[pick.id]) {  // same page: just switch the picker
    current.pickers[pick.id].go(pick.slug, { scroll: true, remember: true });
    return;
  }
  let page;
  try {
    page = await getJSON(`/data/views/${name}.json`);
  } catch (e) {
    // an old address (e.g. a page that was split in two): data/site.json maps it to the new one
    const redirects = (await getJSON("/data/site.json").catch(() => ({}))).redirects || {};
    const to = (pick && redirects[`${name}/${pick.id}/${pick.slug}`]) || redirects[name];
    if (to) { location.replace(`/${to}/`); return; }
    notFound("That forecast doesn't exist.");
    return;
  }
  if (!(await ensurePage(name))) return;
  setHead(page.title, page.summary, `/${name}/`);
  const cls = cellClass(page.sport);
  current = { model: name, title: page.title, summary: page.summary, pickers: {},
    // each picker's option slugs: a table cell or bracket name links only to an option that exists
    slugs: Object.fromEntries(page.views.filter((v) => v.kind === "picker").map((v) => [v.id, new Set(v.options.map((o) => o.slug || slugify(o.label)))])) };
  viewFile = `ballmonitor/models/${page.model}/site.py`;
  pending = pick || null;
  // the title, summary and "How this works" are the page's own HTML; the rest is filled in here
  fillSpans(page.fill);
  // Forecast pages show just the tables and charts (owner's call, 2026-11-23): no headline, no
  // subtitles, notes or dropdown intros (still in site.py, for link previews and the editor).
  fillSlot("headline",
    page.updated ? el("span", { class: "ss-chip" }, page.updated) : null,
    jumpBar(page.views));
  fillSlot("views", ...page.views.map((v) => renderView(v, cls, false)));
  renderNav(name);
  if (pick && current.pickers[pick.id]) current.pickers[pick.id].go(pick.slug, { scroll: true, remember: true });
  else window.scrollTo(0, 0);
}
let pending = null;

// Back/Forward between addresses of the page on screen (/ncaaf_bowls/ ⇄ /ncaaf_bowls/team/georgia/):
// switch the pickers back instead of drawing the page again, so searches, sorting and the scroll
// position stay. `saved` is what the click handler stored in that history entry before leaving it.
// Returns false when the page on screen isn't that one (then it's drawn as usual).
function samePage(p, saved) {
  if (!current.model || p[0] !== current.model || app.dataset.page !== current.model) return false;
  const pick = p.length >= 3 ? { id: p[1], slug: p[2] } : null;
  if (pick && !current.pickers[pick.id]) return false;
  const picks = { ...((saved && saved.picks) || {}) };
  if (pick) picks[pick.id] = pick.slug;
  for (const [id, slug] of Object.entries(picks)) current.pickers[id]?.go(slug, { remember: false });
  if (pick) {
    const o = current.pickers[pick.id].option();
    setHead(`${o.label}: ${current.title}`, o.intro || current.summary, location.pathname);
  } else setHead(current.title, current.summary, `/${current.model}/`);
  if (saved && typeof saved.scroll === "number") window.scrollTo(0, saved.scroll);
  return true;
}
// what the pickers on screen show, kept in the history entry being left
const shownPicks = () => Object.fromEntries(Object.entries(current.pickers).map(([id, pk]) => [id, pk.slug()]));

// "On this page": a line of links to the page's sections, under the headline, when it has 4 or more.
// Each link has the words (and the data-src) of its section's title.
function jumpBar(views) {
  if (views.length < 4) return null;
  return el("nav", { class: "jump-bar", "aria-label": "On this page" },
    el("span", { class: "jump-label" }, "On this page:"),
    views.map((v) => el("a", { href: `#v-${v.id}`, ...viewSrc(`${v.id}.title`), onclick: (e) => {
      // scrolled here rather than by the address bar's #, which would count as leaving the page
      const to = document.getElementById(`v-${v.id}`);
      if (!to) return;
      e.preventDefault();
      to.setAttribute("tabindex", "-1");
      to.scrollIntoView({ block: "start" });
      to.focus({ preventScroll: true });
    } }, v.title)));
}

// A top-level view is its own cell with a heading band; a view inside a picker is a
// section band within the picker's cell.
function viewShell(v, body, cls, nested) {
  // `show_title: false`: no heading (the title still labels the view for screen readers)
  const head = v.show_title === false ? null
    : nested ? el("h3", { class: "ss-section", ...viewSrc(`${v.id}.title`) }, v.title)
      : el("div", { class: "ss-band", ...viewSrc(`${v.id}.title`) }, v.title);
  const kids = [head, body].filter(Boolean);
  const label = head ? null : v.title;
  return nested ? el("div", { class: `view view-${v.kind}`, id: `v-${v.id}`, role: label && "region", "aria-label": label }, ...kids)
    : el("section", { class: `ss-cell ${cls} view view-${v.kind}`, id: `v-${v.id}`, "aria-label": label }, ...kids);
}

function renderView(v, cls, nested) {
  switch (v.kind) {
    case "table": return viewShell(v, renderTable(v), cls, nested);
    case "bar": return viewShell(v, renderBars(v), cls, nested);
    case "line": return viewShell(v, renderLine(v), cls, nested);
    case "picker": return renderPicker(v, cls);
    case "app": return viewShell(v, renderApp(v), cls, nested);
    case "bracket": return viewShell(v, renderBracket(v), cls, nested);
    default: return el("p", {}, `Unknown view ${v.kind}`);
  }
}

// ── table ─────────────────────────────────────────────────────────────────────
// A won-lost record ("10-2", "9-3-1"; a hyphen or an en dash): sorts by share of games won (a tie
// counts half), then by wins, instead of as text ("9-1" after "10-0", not before it). At most three
// digits a part, so a date (2026-11-20) isn't taken for one.
const RECORD = /^\s*(\d{1,3})\s*[-–]\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\s*$/;
function recordKey(s) {
  const m = typeof s === "string" && s.match(RECORD);
  if (!m) return null;
  const w = +m[1], l = +m[2], t = +(m[3] || 0), g = w + l + t;
  return [g ? (w + t / 2) / g : 0, w];
}
function compareValues(x, y) {
  if (typeof x === "number" && typeof y === "number") return x - y;
  const rx = recordKey(x), ry = recordKey(y);
  if (rx && ry) return rx[0] - ry[0] || rx[1] - ry[1];
  return String(x).localeCompare(String(y));
}
// a column of records sorts best-first on its first click, like a number column
const recordColumn = (rows, key) => rows.some((r) => recordKey(r[key])) && rows.every((r) => r[key] === null || r[key] === undefined || r[key] === "" || recordKey(r[key]));

// The address of a picker option named `text` on the page on screen (/<model>/<picker>/<slug>/),
// or null when the picker has no such option (no link to a page that doesn't exist).
function optionHref(picker, text) {
  if (!picker || !current.model || text === null || text === undefined || text === "") return null;
  const slug = slugify(text), have = current.slugs && current.slugs[picker];
  return !have || have.has(slug) ? `/${current.model}/${picker}/${slug}/` : null;
}
// A cell holding a list of names (views.col `sep`): its text, and its parts, each linked if it can be.
const cellSep = (c) => (c.sep ?? ", ");
const cellString = (c, val) => (Array.isArray(val) ? val.join(cellSep(c)) : val);
function linkedParts(c, val) {
  const out = [];
  val.forEach((part, i) => {
    if (i) out.push(cellSep(c));
    const href = c.link ? optionHref(c.link, part) : null;
    out.push(href ? el("a", { href }, part) : part);
  });
  return out;
}

function renderTable(v) {
  const state = { q: "", sort: v.sort || null, desc: v.sort_desc !== false, all: !v.page_size, qf: null };
  const max = {};
  for (const c of v.columns) {
    if (c.bar) max[c.key] = Math.max(...v.rows.map((r) => (typeof r[c.key] === "number" ? Math.abs(r[c.key]) : 0)), 1e-9);
  }
  const heatCols = v.columns.filter((c) => c.heat);
  const heatMax = Math.max(1e-9, ...v.rows.flatMap((r) => heatCols.map((c) => (typeof r[c.key] === "number" ? r[c.key] : 0))));
  const numeric = (c) => c.fmt !== "text";
  // the column that stays put when the table scrolls sideways: an explicit `sticky` column, else
  // the first linked one (team names), else the first text column
  const stickKey = (v.columns.find((c) => c.sticky) || v.columns.find((c) => c.link) || v.columns.find((c) => !numeric(c)) || {}).key;
  const wrap = el("div", { class: "table-wrap" });
  const search = v.search ? el("input", { class: "search", type: "search", placeholder: "Search…", "aria-label": `Search ${v.title}`,
    oninput: (e) => { state.q = e.target.value.trim().toLowerCase(); draw(); } }) : null;
  const more = el("button", { class: "ss-btn more", onclick: () => { state.all = true; draw(); } });

  // Columns menu: the reader picks which columns to show (remembered per table in this browser);
  // columns marked `hidden` start off. The name column that stays put can't be hidden.
  const colsKey = `ballmonitor:cols:${current.model}:${v.id}`;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(colsKey) || "null"); } catch { /* private mode */ }
  state.hide = new Set(Array.isArray(saved) ? saved.filter((k) => k !== stickKey) : v.columns.filter((c) => c.hidden).map((c) => c.key));
  const shownCols = () => v.columns.filter((c) => !state.hide.has(c.key));
  const chooser = v.columns.length >= 4 ? el("details", { class: "col-chooser" },
    el("summary", {}, "Columns"),
    el("div", { class: "col-list" }, v.columns.map((c) => el("label", {},
      el("input", { type: "checkbox", ...(state.hide.has(c.key) ? {} : { checked: "" }), ...(c.key === stickKey ? { disabled: "" } : {}),
        onchange: (e) => {
          if (e.target.checked) state.hide.delete(c.key); else state.hide.add(c.key);
          try { localStorage.setItem(colsKey, JSON.stringify([...state.hide])); } catch { /* private mode */ }
          draw();
        } }), ` ${c.label}`)))) : null;

  // Quick filters (views.table quick_filters): "All" and one button per value of one column.
  const qf = v.quick_filters;
  const qfButtons = qf ? [null, ...qf.values].map((value) => el("button", { type: "button", class: "ss-btn small",
    "aria-pressed": value === null ? "true" : "false", "data-value": value ?? "",
    onclick: (e) => {
      state.qf = value;
      for (const b of e.currentTarget.parentNode.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b === e.currentTarget));
      draw();
    } }, value === null ? "All" : value)) : null;
  const quick = qf ? el("div", { class: "quick-filters", role: "group", "aria-label": `Show only one ${(v.columns.find((c) => c.key === qf.key) || {}).label || qf.key}` }, qfButtons) : null;

  function rows() {
    let rs = v.rows;
    if (state.qf !== null) rs = rs.filter((r) => String(r[qf.key] ?? "") === state.qf);
    if (state.q) rs = rs.filter((r) => v.columns.some((c) => String(cellString(c, r[c.key]) ?? "").toLowerCase().includes(state.q)));
    if (state.sort) {
      const k = state.sort, dir = state.desc ? -1 : 1;
      const col = v.columns.find((c) => c.key === k) || {};
      rs = [...rs].sort((a, b) => {
        const x = cellString(col, a[k]), y = cellString(col, b[k]);
        if (x === y) return 0;
        if (x === null || x === undefined || x === "") return 1;
        if (y === null || y === undefined || y === "") return -1;
        return compareValues(x, y) * dir;
      });
    }
    return rs;
  }

  function draw() {
    const rs = rows();
    const shown = state.all || state.q || state.qf !== null ? rs : rs.slice(0, v.page_size);
    // each header is a button (keyboard and screen readers can sort); aria-sort says which is sorted
    const head = el("tr", {}, shownCols().map((c) => el("th", {
      class: [numeric(c) ? "num" : "", c.key === stickKey ? "stick" : "", state.sort === c.key ? (state.desc ? "sorted desc" : "sorted asc") : ""].join(" ").trim() || null,
      scope: "col",
      "aria-sort": state.sort === c.key ? (state.desc ? "descending" : "ascending") : null,
    }, el("button", { type: "button", class: "sort", title: `Sort by ${c.label}`,
      onclick: () => {
        if (state.sort === c.key) state.desc = !state.desc;
        else { state.sort = c.key; state.desc = (numeric(c) || recordColumn(v.rows, c.key)) && !c.low_first; }
        draw();
        wrap.querySelector(`th[aria-sort] button`)?.focus();
      } }, c.label))));
    const body = shown.map((r) => el("tr", {}, shownCols().map((c) => {
      const val = r[c.key];
      const text = Array.isArray(val) ? val.join(cellSep(c)) : fmt(val, c.fmt, c.decimals);
      const align = c.align || (numeric(c) ? "num" : "");
      if (c.bar && typeof val === "number") {
        const w = Math.max(0, Math.min(100, (Math.abs(val) / max[c.key]) * 100));
        return el("td", { class: `${align} barcell` }, el("span", { class: "cellbar", style: `width:${w}%` }), el("span", { class: "cellval" }, text));
      }
      if (c.heat && typeof val === "number" && val > 0) {
        const a = Math.round(Math.min(1, val / heatMax) * 80);
        return el("td", { class: `${align} heat${a > 42 ? " dark" : ""}`, style: `background: color-mix(in srgb, var(--ss-accent) ${a}%, transparent)` }, text);
      }
      const href = c.link && text && !Array.isArray(val) ? optionHref(c.link, val) : null;
      const out = c.url && text && /^https:\/\//.test(r[c.url] || "") ? r[c.url] : null;   // an outside page (new tab)
      const content = Array.isArray(val) ? linkedParts(c, val) : href ? el("a", { href }, text)
        : out ? el("a", { href: out, target: "_blank", rel: "noopener", title: "Opens in a new tab" }, text) : text;
      return el("td", { class: [align, text.length > 36 ? "long" : "", c.key === stickKey ? "stick" : ""].join(" ").trim() || null }, content);
    })));
    wrap.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
    const hidden = rs.length - shown.length;
    more.textContent = `Show all ${rs.length}`;
    more.hidden = hidden <= 0;
    if ((state.q || state.qf !== null) && !rs.length) wrap.append(el("p", { class: "note" }, "No matches."));
  }
  draw();
  return el("div", {}, quick, (search || chooser) ? el("div", { class: "table-tools" }, search, chooser) : null, wrap, more);
}

// ── apps: interactive tools (static/apps/<name>.js, views.app) ─────────────────
// A lightweight tool that computes in the browser: a copy of its model's formulas, checked against
// the Python model by a test. Its script loads the first time it's shown.
const appScripts = {};
function loadApp(name) {
  const version = (siteData && siteData.assets && siteData.assets[`apps/${name}.js`]) || "";
  return appScripts[name] = appScripts[name] || new Promise((resolve, reject) => {
    const s = el("script", { src: `/static/apps/${name}.js${version ? `?v=${version}` : ""}`, defer: "" });
    s.onload = () => (window.BM_APPS && window.BM_APPS[name] ? resolve(window.BM_APPS[name]) : reject(new Error(`no app ${name}`)));
    s.onerror = () => { delete appScripts[name]; reject(new Error(`could not load the ${name} app`)); };
    document.head.append(s);
  });
}

function renderApp(v) {
  const host = el("div", { class: `app app-${v.app}` }, el("p", { class: "loading" }, "Loading…"));
  loadApp(v.app).then((app) => app.mount(host, v.data, { el, svg, fmt, renderLine })).catch((e) => {
    host.replaceChildren(el("p", {}, "This part of the page didn't load. Try again in a moment."));
    console.error(e);
  });
  return host;
}

// ── horizontal bars ───────────────────────────────────────────────────────────
function renderBars(v) {
  const max = Math.max(...v.items.map((i) => Math.abs(i.value)), 1e-9);
  return el("div", { class: "bars" }, v.items.map((i) =>
    el("div", { class: "barrow" },
      el("span", { class: "barlabel" }, i.label, i.sub ? el("small", {}, ` ${i.sub}`) : null),
      el("span", { class: "bartrack" }, el("span", { class: "barfill", style: `width:${(Math.abs(i.value) / max) * 100}%` })),
      el("span", { class: "barval" }, fmt(i.value, v.fmt, v.decimals)))));
}

// ── bracket (views.bracket): one column per round, scrolling sideways on a phone ──
// web/pages.py writes the same markup into the page before this script runs (bracket_html).
function renderBracket(v) {
  const name = (t) => {
    const href = v.link ? optionHref(v.link, t.name) : null;
    return href ? el("a", { href }, t.name) : t.name;
  };
  const side = (t, won) => el("li", { class: `bk-team${won ? " won" : ""}` },
    el("span", { class: "bk-seed" }, t.seed ?? ""),
    el("span", { class: "bk-name" }, name(t)),
    el("span", { class: "bk-p" }, typeof t.p === "number" ? fmt(t.p, "pct") : ""));
  // the champion (if given) sits under the last round's game
  const rounds = v.rounds.map((rd, r) => el("div", { class: "bk-round" },
    el("h4", { class: "bk-round-name", ...viewSrc(`${v.id}.rounds`) }, rd.name),
    el("div", { class: "bk-games" }, rd.games.map((g) => el("div", { class: "bk-game" },
      el("ul", {}, g.teams.map((t, i) => side(t, g.winner === i))),
      g.where ? el("p", { class: "bk-where" }, g.where) : null)),
      v.champion && r === v.rounds.length - 1 ? el("p", { class: "bk-champ" }, el("span", {}, "Champion"), name({ name: v.champion })) : null)));
  return el("div", { class: "bracket", tabindex: "0", role: "group", "aria-label": v.title }, rounds);
}

// ── line chart ────────────────────────────────────────────────────────────────
const COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}

function timeTicks(lo, hi) {
  const steps = [15, 30, 60, 120, 300, 600, 900, 1800, 3600];
  const step = steps.find((s) => (hi - lo) / s <= 6) || 3600;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  return out;
}

function renderLine(v) {
  const W = 720, H = 340, L = 64, R = 16, T = 14, B = 46;
  const all = v.series.flatMap((s) => [...s.points, ...(s.band || []).flatMap((b) => [[b[0], b[1]], [b[0], b[2]]])]);
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  let x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = v.y_min ?? Math.min(...ys), y1 = v.y_max ?? Math.max(...ys);
  if (v.y_min === undefined && v.y_max === undefined) { const pad = (y1 - y0) * 0.06 || 1; y0 -= pad; y1 += pad; }
  if (x1 === x0) x1 = x0 + 1;
  const X = (x) => L + ((x - x0) / (x1 - x0)) * (W - L - R);
  const Y = (y) => T + (v.y_reverse ? (y - y0) / (y1 - y0) : 1 - (y - y0) / (y1 - y0)) * (H - T - B);
  const yt = v.y_fmt === "time" ? timeTicks(y0, y1) : niceTicks(y0, y1);
  const xt = v.x_fmt === "time" ? timeTicks(x0, x1) : niceTicks(x0, x1, 6);
  const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": v.title });
  for (const t of yt) {
    g.append(svg("line", { x1: L, x2: W - R, y1: Y(t), y2: Y(t), class: "grid" }));
    g.append(svg("text", { x: L - 8, y: Y(t) + 4, class: "tick", "text-anchor": "end" }, fmt(t, v.y_fmt, v.y_fmt === "pct" ? 0 : undefined, false)));
  }
  if (v.x_ticks) {
    for (const [t, label] of v.x_ticks) {
      g.append(svg("line", { x1: X(t), x2: X(t), y1: T, y2: H - B, class: "grid" }));
      // a label at either edge of the plot lines up with the edge instead of running off it
      const anchor = X(t) > W - R - 30 ? "end" : X(t) < L + 30 ? "start" : "middle";
      g.append(svg("text", { x: X(t), y: H - B + 18, class: "tick", "text-anchor": anchor }, label));
    }
  } else {
    for (const t of xt) {
      g.append(svg("text", { x: X(t), y: H - B + 18, class: "tick", "text-anchor": "middle" }, fmt(t, v.x_fmt, v.x_fmt === "number" ? (Number.isInteger(t) ? 0 : 1) : undefined)));
    }
  }
  if (v.x_label) g.append(svg("text", { x: (L + W - R) / 2, y: H - 6, class: "axis", "text-anchor": "middle" }, v.x_label));
  if (v.y_label) g.append(svg("text", { x: 14, y: (T + H - B) / 2, class: "axis", "text-anchor": "middle", transform: `rotate(-90 14 ${(T + H - B) / 2})` }, v.y_label));
  v.series.forEach((s, i) => {
    const color = COLORS[i % COLORS.length];
    if (s.band && s.band.length) {
      const up = s.band.map((b) => `${X(b[0])},${Y(b[2])}`), down = [...s.band].reverse().map((b) => `${X(b[0])},${Y(b[1])}`);
      g.append(svg("polygon", { points: [...up, ...down].join(" "), fill: color, opacity: 0.15 }));
    }
    const d = s.points.map((p, j) => `${j ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    g.append(svg("path", { d, fill: "none", stroke: color, "stroke-width": 2.5, "stroke-linejoin": "round" }));
  });
  for (const m of v.markers || []) {
    const c = svg("circle", { cx: X(m.x), cy: Y(m.y), r: 4.5, class: "marker" });
    c.append(svg("title", {}, m.label));
    g.append(c);
  }
  const legend = v.series.length > 1 ? el("div", { class: "legend" }, v.series.map((s, i) =>
    el("span", {}, el("i", { style: `background:${COLORS[i % COLORS.length]}` }), s.name))) : null;
  return el("div", {}, legend, el("div", { class: "chart-wrap" }, g));
}

// ── picker (dropdown that swaps groups of views) ──────────────────────────────
function renderPicker(v, cls) {
  const body = el("div", { class: "picked" });
  const select = el("select", { "aria-label": v.label, onchange: (e) => show(+e.target.value, true) },
    v.options.map((o, i) => el("option", { value: i }, o.label)));
  // `remember`: put this option in the address bar (/<model>/<picker>/<slug>/) so it can be shared.
  // A big page's options carry `src` instead of views (builder.split_options): fetched when shown.
  let findInput = null;
  async function show(i, remember) {
    select.value = String(i);
    // the name is in the dropdown now: don't leave old typing in the find box (unless it's being typed
    // in: a whole name switches as it's typed, and "Georgia" may be on its way to "Georgia Tech")
    if (findInput && document.activeElement !== findInput) findInput.value = "";
    const o = v.options[i];
    if (o.src && !o.views.length) {
      body.replaceChildren(el("p", { class: "loading" }, "Loading…"));
      try {
        o.views = (await getJSON(o.src)).views;
      } catch (e) {
        body.replaceChildren(el("p", {}, "This part of the page didn't load. Try again in a moment."));
        console.error(e);
        return;
      }
      if (select.value !== String(i)) return;   // another option was picked meanwhile
    }
    body.replaceChildren(...o.views.map((w) => renderView(w, cls, true)));
    if (remember && current.model) {
      const path = `/${current.model}/${v.id}/${o.slug || slugify(o.label)}/`;
      history.replaceState(history.state, "", path);
      setHead(`${o.label}: ${current.title}`, o.intro || current.summary, path);
    }
  }
  const fromAddress = pending && pending.id === v.id ? v.options.findIndex((o) => (o.slug || slugify(o.label)) === pending.slug) : -1;
  show(fromAddress >= 0 ? fromAddress : v.default || 0);
  const slugOf = (o) => o.slug || slugify(o.label);
  current.pickers[v.id] = {
    // show the option with this slug; `remember` puts it in the address bar, `scroll` brings the picker into view
    go(slug, { scroll = false, remember = false } = {}) {
      const i = v.options.findIndex((o) => slugOf(o) === slug);
      if (i >= 0 && (remember || String(i) !== select.value)) show(i, remember);
      if (scroll) document.getElementById(`v-${v.id}`)?.scrollIntoView({ block: "start" });
    },
    option: () => v.options[+select.value],
    slug: () => slugOf(v.options[+select.value]),
  };
  // Long lists also get a type-to-find box (matches anywhere in the option's name).
  let find = null;
  if (v.options.length > 12 && v.find !== false) {
    const listId = `dl-${v.id}`;
    find = el("span", { class: "pick-find" },
      findInput = el("input", { class: "search", type: "search", list: listId, placeholder: `Find a ${v.label.toLowerCase()}…`,
        "aria-label": `Find a ${v.label.toLowerCase()}`,
        // switch only on a whole name (typed, or picked from the list) or on Enter (the first
        // name containing what was typed), not on every letter
        oninput: (e) => {
          const q = e.target.value.trim().toLowerCase();
          const i = v.options.findIndex((o) => o.label.toLowerCase() === q);
          if (q && i >= 0 && String(i) !== select.value) show(i, true);
        },
        onkeydown: (e) => {
          if (e.key !== "Enter") return;
          const q = e.target.value.trim().toLowerCase();
          // best match: the name starts with it, then a word in it does, then it's anywhere in the name
          const names = v.options.map((o) => o.label.toLowerCase());
          const i = !q ? -1 : [(n) => n.startsWith(q), (n) => n.split(/[\s(-]+/).some((w) => w.startsWith(q)), (n) => n.includes(q)]
            .map((test) => names.findIndex(test)).find((k) => k >= 0) ?? -1;
          if (i >= 0) { e.preventDefault(); e.target.value = ""; show(i, true); }
        } }),
      el("datalist", { id: listId }, v.options.map((o) => el("option", { value: o.label }))));
  }
  return el("section", { class: `ss-cell ${cls} view view-picker`, id: `v-${v.id}` },
    el("div", { class: "ss-band", ...viewSrc(`${v.id}.title`) }, v.title),
    el("div", { class: "pick-row" }, el("label", { class: "pick" }, `${v.label}: `, select), find, copyLink(() => {
      const o = v.options[+select.value];
      return `${location.origin}/${current.model}/${v.id}/${o.slug || slugify(o.label)}/`;
    })),
    body);
}

// "Copy link": the address already names the picked option (/<model>/<picker>/<slug>/).
function copyLink(url) {
  const btn = el("button", { class: "ss-btn copy-link", type: "button", onclick: async () => {
    const href = url();
    try {
      await navigator.clipboard.writeText(href);
      window.ssToast ? ssToast("Link copied") : (btn.textContent = "Link copied");
    } catch {
      window.prompt("Copy this link:", href);
    }
  } }, "Copy link");
  return btn;
}

// ── live data tables (web/tables.toml) at /tables/<id>/: queries go to a tabdn table server ──
// The embed script comes from the server itself (one per server address), so the table always
// matches the server's version. Nothing is computed here: the server filters and sorts.
const embedScripts = {};
function loadEmbed(server) {
  const src = `${server}web/vendor/tabview-embed.js`;
  return embedScripts[src] = embedScripts[src] || new Promise((resolve, reject) => {
    const s = el("script", { src, defer: "" });
    s.onload = () => (window.Tabview ? resolve(window.Tabview) : reject(new Error("no Tabview in the script")));
    s.onerror = () => { delete embedScripts[src]; reject(new Error(`could not load ${src}`)); };
    document.head.append(s);
  });
}

const TABLE_HIDE = ["compiled", "helper", "computed", "stats", "group", "variables", "cards"];
// A Try button may also bring named formulas (`defs`), added columns (`computed`) and, with
// `variables = true`, the variables box where the visitor edits those formulas (web/tables.toml).
function exampleExtras(x, t) {
  if (!x.defs && !x.computed) return {};
  // added columns join the columns shown (by formula, as tabview's `show` names them)
  const added = (Array.isArray(x.computed) ? x.computed : []).map((c) => c.formula).filter(Boolean);
  return { defs: x.defs || {}, computed: x.computed || "", hide: TABLE_HIDE.filter((p) => !(x.variables && p === "variables")),
    ...(t.options.show ? { show: [...t.options.show, ...added] } : {}) };
}

async function renderDataTable(id) {
  const site = await getJSON("/data/site.json");
  // /tables/ alone (the template's own address, e.g. in Claude UI's Editor) shows the first table
  const t = (site.tables || []).find((x) => x.id === id) || (id ? null : (site.tables || [])[0]);
  current = { model: null, pickers: {} };
  if (!t) return notFound("That table isn't on the site.");
  if (!(await ensurePage("tables"))) return;
  setHead(t.title, t.summary, `/tables/${t.id}/`);
  const cls = cellClass(t.sport);
  const host = el("div", { class: "live-table" }, el("p", { class: "loading" }, "Loading the table…"));
  let shownTable = null;
  const show = async (options) => {
    try {
      const Tabview = await loadEmbed(t.server);
      try { shownTable?.destroy?.(); } catch { /* an older embed */ }
      // fans get the filter (its numbers draggable), the Try buttons, sorting, the column list, downloads
      // and the full page button; adding columns, variables, stats, groups and cards stay on tabdn.com.
      // `labels` and `timing` need tabview 2026-11-10 or later, `variables`/`cards` 2026-11-22 (an older
      // embed ignores them).
      shownTable = Tabview.mount(host, { server: t.server, backend: t.backend, theme: "light", timing: false,
        hide: TABLE_HIDE, ...t.options, ...options });
    } catch (e) {
      host.replaceChildren(el("p", {}, "The table server isn't responding right now. Please try again in a bit."));
      console.error(e);
    }
  };
  // The Try button whose filter and sort are on screen is pressed (aria-pressed); the table's own
  // filter and sort (t.options) count as the one that matches them. Typing a filter un-presses it.
  const sameSort = (a, b) => (a || null) === (b || null) || (a && b && a.column === b.column && !!a.desc === !!b.desc);
  const press = (btn) => { for (const b of examples?.querySelectorAll("button") || []) b.setAttribute("aria-pressed", String(b === btn)); };
  const examples = t.examples.length ? el("div", { class: "examples" },
    el("span", { class: "small" }, "Try: "),
    ...t.examples.map((x) => el("button", { class: "ss-btn small", type: "button",
      "aria-pressed": String((x.filter || "") === (t.options.filter || "") && sameSort(x.sort, t.options.sort)),
      onclick: (e) => { press(e.currentTarget); show({ filter: x.filter || "", sort: x.sort || null, ...exampleExtras(x, t) }); } }, x.label))) : null;
  host.addEventListener("input", () => press(null));
  // the name a filter uses, then the header it has on the page and what it means
  const labels = t.labels || {};
  // how to use the names, with the first Try example's filter (web/pages.py writes the same line)
  const sample = (t.examples.find((x) => x.filter) || {}).filter;
  const key = Object.keys(t.columns).length ? el("details", { class: "column-key" },
    el("summary", {}, "What the columns mean"),
    el("p", { class: "key-hint" }, sample ? `Type a filter with these short names, like ${sample}.` : "Type a filter with these short names."),
    el("dl", {}, ...Object.entries(t.columns).flatMap(([k, v]) => [el("dt", {}, k),
      el("dd", {}, labels[k] && labels[k].toLowerCase() !== k ? `${labels[k]}: ${v}` : v)]))) : null;
  fillSlot("table",
    cell(`${cls} page-head`,
      el("a", { class: "back", href: "/" }, "← Home"),
      el("div", { class: "ss-kicker" }, `${t.sport ? t.sport + " · " : ""}Data table`),
      el("h1", { class: "ss-title", ...tableSrc(t, "title") }, t.title),
      el("p", { class: "summary", ...tableSrc(t, "summary") }, t.summary),
      examples, key),
    cell(`${cls} live-cell`, host),
    t.how ? cell(`${cls} how`, el("div", { class: "ss-band" }, "How this works"), el("p", tableSrc(t, "how"), t.how)) : null);
  renderNav(`tables/${t.id}`);
  window.scrollTo(0, 0);
  show({});
}

// ── baseball charts (charts/: pyslots' form and templates, scripts/sync-charts.sh) ──
// The visitor's formulas fill a Python
// (matplotlib) template, which runs in their browser (Pyodide, loaded from jsDelivr on the first run).
const CHARTS = "/charts/";
let pyslotsScript = null;
function loadPyslots() {
  return pyslotsScript = pyslotsScript || new Promise((resolve, reject) => {
    const s = el("script", { src: `${CHARTS}embed/pyslots-embed.js`, defer: "" });
    s.onload = () => (window.Pyslots ? resolve(window.Pyslots) : reject(new Error("no Pyslots in the script")));
    s.onerror = () => { pyslotsScript = null; reject(new Error("could not load the charts script")); };
    document.head.append(s);
  });
}
const chartSlug = (file) => file.replace(/^charts\//, "").replace(/\.py$/, "");
// Python (Pyodide, from jsDelivr) is loaded once per visit, on the first chart drawn. A visitor who
// hasn't drawn a chart yet gets a "Draw the chart" button instead of a download they didn't ask for;
// once they have (this visit, or before: remembered in this browser), charts draw as soon as they open.
// The form itself is mounted only then: pyslots' embed runs its first chart even with autoRun: false.
const DRAWN_KEY = "ballmonitor:charts:drawn";
let chartDrawn = false;
const drewBefore = () => { try { return localStorage.getItem(DRAWN_KEY) === "1"; } catch { return false; } };

// The buttons under a chart: Reset formulas (mount the form again with the chart's starting
// formulas) and Download PNG (the picture pyslots drew, an <img> in its .pse-out). Both work from
// outside the form, through Pyslots.mount and the page, so charts/ (a copy of pyslots) stays as it is.
function chartTools(host, t, mount) {
  const note = el("p", { class: "chart-first", role: "status" }, chartDrawn ? null : "Loading Python for your first chart (takes a few seconds)…");
  note.hidden = chartDrawn;
  const reset = el("button", { type: "button", class: "ss-btn small", onclick: () => mount() }, "Reset formulas");
  const download = el("a", { class: "ss-btn small", download: `${t.id}.png`, "aria-disabled": "true", href: null }, "Download PNG");
  const watch = () => {
    const img = host.querySelector(".pse-out img");
    const ready = img && img.src && !host.querySelector(".pse-out.stale");
    if (img && !chartDrawn) {
      chartDrawn = true;
      try { localStorage.setItem(DRAWN_KEY, "1"); } catch { /* private mode */ }
    }
    if (img) note.hidden = true;
    if (ready) { download.href = img.src; download.removeAttribute("aria-disabled"); }
    else { download.removeAttribute("href"); download.setAttribute("aria-disabled", "true"); }
  };
  new MutationObserver(watch).observe(host, { childList: true, subtree: true, attributes: true, attributeFilter: ["src", "class"] });
  return { note, bar: el("div", { class: "chart-tools" }, reset, download) };
}

// The charts come from web/charts.toml (data/site.json): a name, an intro and starting formulas for
// one of the templates. An old address naming a template (/charts/scatter/) opens its first chart.
async function renderCharts(slug) {
  const site = await getJSON("/data/site.json");
  const charts = site.charts || [];
  current = { model: null, pickers: {} };
  const t = charts.find((x) => x.id === slug) || charts.find((x) => chartSlug(x.template) === slug) || charts[0];
  if (!t) return notFound("There are no charts yet.");
  if (!(await ensurePage("charts"))) return;
  // the page's title, summary and "How this works" are in web/site/charts/index.html
  const pageTitle = app.querySelector("h1")?.textContent.trim() || "Baseball charts";
  setHead(slug ? `${t.title}: ${pageTitle}` : pageTitle, t.intro, slug ? `/charts/${t.id}/` : "/charts/");
  const groups = {};
  for (const x of charts) (groups[x.group] = groups[x.group] || []).push(x);
  const host = el("div", { class: "live-chart" }, el("p", { class: "loading" }, "Loading the chart…"));
  let Pyslots = null;
  const saveData = !!(navigator.connection && navigator.connection.saveData);
  const mount = () => Pyslots.mount(host, { site: new URL(CHARTS, location.href).href, template: t.template, title: t.title,
    formulas: t.formulas || {} });
  const tools = chartTools(host, t, () => Pyslots && mount().catch((e) => console.error(e)));
  const draw = async () => {
    tools.note.hidden = chartDrawn;
    tools.bar.hidden = false;
    host.replaceChildren(el("p", { class: "loading" }, "Loading the chart…"));
    try {
      Pyslots = await loadPyslots();
      await mount();
    } catch (e) {
      tools.note.hidden = true;
      host.replaceChildren(el("p", {}, "Couldn't load the chart right now. Please try again in a bit."));
      console.error(e);
    }
  };
  // readers in data-saver mode always press the button themselves
  const atOnce = (chartDrawn || drewBefore()) && !saveData;
  if (!atOnce) {
    tools.note.hidden = tools.bar.hidden = true;
    host.replaceChildren(el("div", { class: "chart-ask" },
      el("button", { type: "button", class: "ss-btn", onclick: draw }, "Draw the chart"),
      el("span", { class: "small" }, "Your first chart loads Python in your browser (a few seconds). After that, charts draw automatically.")));
  }
  fillSlot("chart-picks",
    ...Object.entries(groups).map(([g, xs]) => el("div", { class: "chart-group" },
      el("span", { class: "chart-group-name" }, g),
      el("div", { class: "chart-group-buttons" }, ...xs.map((x) => el("a", { class: "ss-btn small", href: `/charts/${x.id}/`, ...chartSrc(x, "title"),
        ...(x === t ? { "aria-current": "page" } : {}) }, x.title))))));
  fillSlot("chart",
    el("div", { class: "ss-band", ...chartSrc(t, "title") }, t.title),
    el("p", { class: "chart-intro", ...chartSrc(t, "intro") }, t.intro),
    tools.note, host, tools.bar);
  renderNav("charts");
  window.scrollTo(0, 0);
  if (atOnce) await draw();
}

// ── page head: title, description and canonical address follow the page shown ──
// The home page's description, as written in its own file (web/site/index.html): the one in this
// document if the visit started at home, else read from the home page when it's fetched (ensurePage).
const metaDescription = (doc) => doc.querySelector('meta[name="description"]')?.getAttribute("content") || "";
let homeDescription = app.dataset.page === "" && !app.hasAttribute("data-static") ? metaDescription(document) : "";
function setHead(title, description, path) {
  const full = title === "Ball Monitor" ? title : `${title} · Ball Monitor`;
  document.title = full;
  const url = `${location.origin}${path}`;
  const set = (sel, attr, value) => { const n = document.querySelector(sel); if (n && value) n.setAttribute(attr, value); };
  set('meta[name="description"]', "content", description || homeDescription);
  set('meta[property="og:description"]', "content", description || homeDescription);
  set('meta[property="og:title"]', "content", full);
  set('link[rel="canonical"]', "href", url);
  set('meta[property="og:url"]', "content", url);
}

function notFound(message) {
  setHead("Page not found", null, location.pathname);
  drawWhole(cell("ss-p2", el("div", { class: "ss-band" }, "Page not found"),
    el("p", {}, `${message} `, el("a", { href: "/" }, "See everything"))));
}

function failed(e) {
  drawWhole(cell("ss-p2", el("div", { class: "ss-band" }, "Something went wrong"),
    el("p", {}, `This page didn't load (${e.message}). Try again in a moment, or `, el("a", { href: "/" }, "go to the home page"), ".")));
  console.error(e);
}

// ── routing: / (home), /<page>/[<picker>/<option>/], /tables/<id>/, /charts/[<id>/] ──
// The text pages (/about/ ...) are plain HTML: <main data-static> is left as it is.
const parts = (path) => path.split("/").filter(Boolean).map(decodeURIComponent);

let routedPath = null;   // the address last drawn (a change of only the # part draws nothing)
function route() {
  routedPath = location.pathname + location.search;
  const p = parts(location.pathname);
  if (p[p.length - 1] === "index.html") p.pop();
  if (app.hasAttribute("data-static")) { renderNav(p.join("/")).catch(() => {}); return; }
  if (p[0] === "charts") return renderCharts(p[1] || "").catch(failed);
  if (p[0] === "tables") return renderDataTable(p[1] || "").catch(failed);
  if (!p.length) current = { model: null, pickers: {} };
  return (p.length ? renderModel(p[0], p.length >= 3 ? { id: p[1], slug: p[2] } : null) : renderHome()).catch(failed);
}

// Links to pages this script draws are followed without reloading; the rest (games, text pages,
// the editor, other sites) load normally.
function drawnHere(url) {
  if (url.origin !== location.origin || url.hash) return false;
  const p = parts(url.pathname);
  if (!p.length) return true;
  if (p[0] === "charts" || p[0] === "tables") return true;
  return siteData ? siteData.models.some((m) => m.name === p[0]) || p[0] in (siteData.redirects || {}) : false;
}

document.addEventListener("click", (e) => {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const a = e.target.closest("a[href]");
  if (!a || a.target || a.hasAttribute("download") || app.hasAttribute("data-static")) return;
  if (EDITOR) return;   // in Claude UI's Editor every page loads from its own file
  const url = new URL(a.href, location.href);
  if (!drawnHere(url)) return;
  e.preventDefault();
  if (url.pathname + url.search !== location.pathname + location.search) {
    // remember where this page was scrolled and what its pickers showed, for Back (samePage)
    history.replaceState({ ...(history.state || {}), scroll: window.scrollY, picks: shownPicks() }, "");
    history.pushState(null, "", url.pathname + url.search);
  }
  focusAfter(route());
});

// An open Columns menu closes on a click outside it, or on Escape (focus goes back to its button).
document.addEventListener("click", (e) => {
  for (const d of document.querySelectorAll("details.col-chooser[open]")) if (!d.contains(e.target)) d.open = false;
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  for (const d of document.querySelectorAll("details.col-chooser[open]")) {
    d.open = false;
    if (d.contains(document.activeElement)) d.querySelector("summary")?.focus();
  }
});

// After in-site navigation, move keyboard and screen-reader focus to the new page's heading
// (a picker link focuses the picker instead, which the page scrolls to).
function focusAfter(done, keepScroll) {
  Promise.resolve(done).then(() => {
    const p = parts(location.pathname);
    // /<page>/<picker id>/<option>/: that picker's dropdown (a page can have several pickers)
    const target = p.length >= 3 && !["charts", "tables"].includes(p[0])
      ? app.querySelector(`#v-${CSS.escape(p[1])} select`) : app.querySelector("h1");
    if (!target) return;
    if (target.tagName === "H1") target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: keepScroll || target.tagName !== "H1" });
  }).catch(() => {});
}

window.addEventListener("popstate", (e) => {
  if (location.pathname + location.search === routedPath) return;   // only the # changed
  if (app.hasAttribute("data-static") || !drawnHere(new URL(location.href))) { location.reload(); return; }
  const p = parts(location.pathname);
  if (p[p.length - 1] === "index.html") p.pop();
  if (samePage(p, e.state)) { routedPath = location.pathname + location.search; focusAfter(null, true); return; }
  const saved = e.state;
  focusAfter(Promise.resolve(route()).then(() => {
    if (saved && typeof saved.scroll === "number") window.scrollTo(0, saved.scroll);
  }), !!saved);
});

// An old #/ address (shared before the site used paths): #/data/<id> is now /tables/<id>/.
function fromHash() {
  const m = location.hash.match(/^#\/(.*?)\/?$/);
  if (!m) return false;
  const rest = m[1].replace(/^data\//, "tables/");
  history.replaceState(null, "", rest ? `/${rest}/` : "/");
  return true;
}

// Claude UI's Editor marks every element of the file it shows (data-cui): there, links load pages
// the ordinary way, so what is on screen is always the file being edited.
const EDITOR = !!document.querySelector("[data-cui]");

let siteData = null;
const sitePromise = getJSON("/data/site.json").then((s) => { siteData = s; SPORT_CELL = s.cells || {}; return s; });
getJSON("/data/manifest.json").then((m) => {
  for (const n of document.querySelectorAll(".built")) n.textContent = `Updated ${m.build_date}.`;
}).catch(() => {});
if (fromHash() && app.hasAttribute("data-static")) location.reload();
sitePromise.catch(() => {}).finally(route);
