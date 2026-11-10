// Ball Monitor public page. Shows the tables and charts that `ballmonitor build-site` wrote to
// data/site.json and data/views/<model>.json (from each model's site.py). It never runs a
// model: every number on the page was computed at build time.
// Addresses are real paths (/ncaaf_bowls/, /ncaaf_bowls/team/georgia/, /tables/<id>/, /charts/<id>/):
// the build writes a copy of this page at each one (web/pages.py), and links between them are
// followed here without reloading. Old #/ addresses are turned into paths on arrival.
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
    nav.append(...site.models.map((m) => el("a", { href: `/${m.name}/`, "data-route": m.name }, m.title)));
    nav.append(...(site.tables || []).map((t) => el("a", { href: `/tables/${t.id}/`, "data-route": `tables/${t.id}` }, t.title)));
    if ((site.charts || []).length) nav.append(el("a", { href: "/charts/", "data-route": "charts" }, "Baseball charts"));
  }
  for (const a of document.querySelectorAll(".ss-nav a[data-route]")) {
    if (a.dataset.route === active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

// ── home ──────────────────────────────────────────────────────────────────────
// Home page text lives in <template>s in index.html (edited from Claude UI's Content page).
const copy = (id) => document.getElementById(id).content.cloneNode(true);

async function renderHome() {
  const site = await getJSON("/data/site.json");
  setHead("Ball Monitor", null, "/");
  const groups = {};
  for (const m of site.models) (groups[m.sport] = groups[m.sport] || []).push(m);
  app.replaceChildren(
    cell("ss-p1",
      el("h1", { class: "ss-title" }, copy("home-title").textContent.trim()),
      el("div", { class: "home-intro" }, ...copy("home-intro").childNodes)),
    ...Object.entries(groups).map(([sport, models]) =>
      cell(cellClass(sport),
        el("div", { class: "ss-band" }, sport),
        el("ul", { class: "model-list" }, models.map((m) =>
          el("li", {}, el("a", { class: "model-link", href: `/${m.name}/` },
            el("b", {}, m.title),
            el("p", {}, m.summary),
            m.updated ? el("span", { class: "ss-chip" }, m.updated) : null)))))),
    (site.tables || []).length ? cell("ss-p4",
      el("div", { class: "ss-band" }, "Data tables"),
      el("ul", { class: "model-list" }, site.tables.map((t) =>
        el("li", {}, el("a", { class: "model-link", href: `/tables/${t.id}/` },
          el("b", {}, t.title), el("p", {}, t.summary)))))) : null,
    (site.charts || []).length ? cell(cellClass("Baseball"),
      el("div", { class: "ss-band" }, "Charts"),
      el("ul", { class: "model-list" }, el("li", {}, el("a", { class: "model-link", href: "/charts/" },
        el("b", {}, "Baseball charts"),
        el("p", {}, `${site.charts.length} charts of every season since 1871 (how hitters age, power by decade, the best seasons), and you can change any of them.`))))) : null,
    cell("ss-p3",
      el("div", { class: "ss-band" }, "Games"),
      el("ul", { class: "model-list" }, [...copy("home-games").querySelectorAll("li")].map((li) =>
        el("li", {}, el("a", { class: "model-link", href: li.dataset.href || "/" }, ...li.childNodes))))),
  );
  renderNav("");
  window.scrollTo(0, 0);
}

// ── model page ───────────────────────────────────────────────────────────────
async function renderModel(name, pick) {
  if (current.model === name && pick && current.pickers[pick.id]) {  // same page: just switch the picker
    current.pickers[pick.id](pick.slug, true);
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
  setHead(page.title, page.summary, `/${name}/`);
  const cls = cellClass(page.sport);
  current = { model: name, title: page.title, pickers: {} };
  pending = pick || null;
  app.replaceChildren(
    cell(`${cls} page-head`,
      el("a", { class: "back", href: "/" }, "← Home"),
      el("div", { class: "ss-kicker" }, page.sport),
      el("h1", { class: "ss-title" }, page.title),
      el("p", { class: "summary" }, page.summary),
      page.headline ? el("p", { class: "headline" }, page.headline) : null,
      page.updated ? el("span", { class: "ss-chip" }, page.updated) : null),
    ...page.views.map((v) => renderView(v, cls, false)),
    page.how ? cell(`${cls} how`,
      el("div", { class: "ss-band" }, "How this works"),
      el("p", {}, page.how),
      el("p", { class: "small" }, el("a", { href: `/editor.html?model=${encodeURIComponent(page.model || name)}` }, "Full method, settings and assumptions →"))) : null,
  );
  renderNav(name);
  if (pick && current.pickers[pick.id]) current.pickers[pick.id](pick.slug, true);
  else window.scrollTo(0, 0);
}
let pending = null;

// A top-level view is its own cell with a heading band; a view inside a picker is a
// section band within the picker's cell.
function viewShell(v, body, cls, nested) {
  const kids = [
    nested ? el("h3", { class: "ss-section" }, v.title) : el("div", { class: "ss-band" }, v.title),
    v.subtitle ? el("p", { class: "subtitle" }, v.subtitle) : null,
    body,
    v.note ? el("p", { class: "note" }, v.note) : null,
  ];
  return nested ? el("div", { class: `view view-${v.kind}`, id: `v-${v.id}` }, ...kids)
    : el("section", { class: `ss-cell ${cls} view view-${v.kind}`, id: `v-${v.id}` }, ...kids);
}

function renderView(v, cls, nested) {
  switch (v.kind) {
    case "table": return viewShell(v, renderTable(v), cls, nested);
    case "bar": return viewShell(v, renderBars(v), cls, nested);
    case "line": return viewShell(v, renderLine(v), cls, nested);
    case "picker": return renderPicker(v, cls);
    default: return el("p", {}, `Unknown view ${v.kind}`);
  }
}

// ── table ─────────────────────────────────────────────────────────────────────
function renderTable(v) {
  const state = { q: "", sort: v.sort || null, desc: v.sort_desc !== false, all: !v.page_size };
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

  function rows() {
    let rs = v.rows;
    if (state.q) rs = rs.filter((r) => v.columns.some((c) => String(r[c.key] ?? "").toLowerCase().includes(state.q)));
    if (state.sort) {
      const k = state.sort, dir = state.desc ? -1 : 1;
      rs = [...rs].sort((a, b) => {
        const x = a[k], y = b[k];
        if (x === y) return 0;
        if (x === null || x === undefined || x === "") return 1;
        if (y === null || y === undefined || y === "") return -1;
        return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
      });
    }
    return rs;
  }

  function draw() {
    const rs = rows();
    const shown = state.all || state.q ? rs : rs.slice(0, v.page_size);
    // each header is a button (keyboard and screen readers can sort); aria-sort says which is sorted
    const head = el("tr", {}, shownCols().map((c) => el("th", {
      class: [numeric(c) ? "num" : "", c.key === stickKey ? "stick" : "", state.sort === c.key ? (state.desc ? "sorted desc" : "sorted asc") : ""].join(" ").trim() || null,
      scope: "col",
      "aria-sort": state.sort === c.key ? (state.desc ? "descending" : "ascending") : null,
    }, el("button", { type: "button", class: "sort", title: `Sort by ${c.label}`,
      onclick: () => {
        if (state.sort === c.key) state.desc = !state.desc;
        else { state.sort = c.key; state.desc = numeric(c) && !c.low_first; }
        draw();
        wrap.querySelector(`th[aria-sort] button`)?.focus();
      } }, c.label))));
    const body = shown.map((r) => el("tr", {}, shownCols().map((c) => {
      const val = r[c.key];
      const text = fmt(val, c.fmt, c.decimals);
      const align = c.align || (numeric(c) ? "num" : "");
      if (c.bar && typeof val === "number") {
        const w = Math.max(0, Math.min(100, (Math.abs(val) / max[c.key]) * 100));
        return el("td", { class: `${align} barcell` }, el("span", { class: "cellbar", style: `width:${w}%` }), el("span", { class: "cellval" }, text));
      }
      if (c.heat && typeof val === "number" && val > 0) {
        const a = Math.round(Math.min(1, val / heatMax) * 80);
        return el("td", { class: `${align} heat${a > 42 ? " dark" : ""}`, style: `background: color-mix(in srgb, var(--ss-accent) ${a}%, transparent)` }, text);
      }
      const content = c.link && text ? el("a", { href: `/${current.model}/${c.link}/${slugify(val)}/` }, text) : text;
      return el("td", { class: [align, text.length > 36 ? "long" : "", c.key === stickKey ? "stick" : ""].join(" ").trim() || null }, content);
    })));
    wrap.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
    const hidden = rs.length - shown.length;
    more.textContent = `Show all ${rs.length}`;
    more.hidden = hidden <= 0;
    if (state.q && !rs.length) wrap.append(el("p", { class: "note" }, "No matches."));
  }
  draw();
  return el("div", {}, (search || chooser) ? el("div", { class: "table-tools" }, search, chooser) : null, wrap, more);
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
  const Y = (y) => T + (1 - (y - y0) / (y1 - y0)) * (H - T - B);
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
      g.append(svg("text", { x: X(t), y: H - B + 18, class: "tick", "text-anchor": "middle" }, label));
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
  async function show(i, remember) {
    select.value = String(i);
    const o = v.options[i];
    if (o.src && !o.views.length) {
      body.replaceChildren(o.intro ? el("p", { class: "intro" }, o.intro) : "", el("p", { class: "loading" }, "Loading…"));
      try {
        o.views = (await getJSON(o.src)).views;
      } catch (e) {
        body.replaceChildren(el("p", {}, "This part of the page didn't load. Try again in a moment."));
        console.error(e);
        return;
      }
      if (select.value !== String(i)) return;   // another option was picked meanwhile
    }
    body.replaceChildren(o.intro ? el("p", { class: "intro" }, o.intro) : "", ...o.views.map((w) => renderView(w, cls, true)));
    if (remember && current.model) {
      const path = `/${current.model}/${v.id}/${o.slug || slugify(o.label)}/`;
      history.replaceState(null, "", path);
      setHead(`${o.label}: ${current.title}`, o.intro || null, path);
    }
  }
  const fromAddress = pending && pending.id === v.id ? v.options.findIndex((o) => (o.slug || slugify(o.label)) === pending.slug) : -1;
  show(fromAddress >= 0 ? fromAddress : v.default || 0);
  current.pickers[v.id] = (slug, scroll) => {
    const i = v.options.findIndex((o) => (o.slug || slugify(o.label)) === slug);
    if (i >= 0) show(i, true);
    if (scroll) document.getElementById(`v-${v.id}`)?.scrollIntoView({ block: "start" });
  };
  // Long lists also get a type-to-find box (matches anywhere in the option's name).
  let find = null;
  if (v.options.length > 12) {
    const listId = `dl-${v.id}`;
    find = el("span", { class: "pick-find" },
      el("input", { class: "search", type: "search", list: listId, placeholder: `Find a ${v.label.toLowerCase()}…`,
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
          if (i >= 0) { e.preventDefault(); show(i, true); }
        } }),
      el("datalist", { id: listId }, v.options.map((o) => el("option", { value: o.label }))));
  }
  return el("section", { class: `ss-cell ${cls} view view-picker`, id: `v-${v.id}` },
    el("div", { class: "ss-band" }, v.title),
    v.subtitle ? el("p", { class: "subtitle" }, v.subtitle) : null,
    el("div", { class: "pick-row" }, el("label", { class: "pick" }, `${v.label}: `, select), find, copyLink(() => {
      const o = v.options[+select.value];
      return `${location.origin}/${current.model}/${v.id}/${o.slug || slugify(o.label)}/`;
    })),
    v.note ? el("p", { class: "note" }, v.note) : null,
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

async function renderDataTable(id) {
  const site = await getJSON("/data/site.json");
  const t = (site.tables || []).find((x) => x.id === id);
  current = { model: null, pickers: {} };
  if (!t) return notFound("That table isn't on the site.");
  setHead(t.title, t.summary, `/tables/${id}/`);
  const cls = cellClass(t.sport);
  const host = el("div", { class: "live-table" }, el("p", { class: "loading" }, "Loading the table…"));
  const show = async (options) => {
    try {
      const Tabview = await loadEmbed(t.server);
      // fans get the filter, the Try buttons, sorting, the column list and downloads; adding columns,
      // stats and groups stay on tabdn.com. `labels` and `timing` need tabview 2026-11-10 or later
      // (an older embed ignores them).
      Tabview.mount(host, { server: t.server, backend: t.backend, theme: "light", timing: false,
        hide: ["compiled", "helper", "computed", "stats", "group"], ...t.options, ...options });
    } catch (e) {
      host.replaceChildren(el("p", {}, "The table server isn't answering right now. Try again in a little while."));
      console.error(e);
    }
  };
  const examples = t.examples.length ? el("div", { class: "examples" },
    el("span", { class: "small" }, "Try: "),
    ...t.examples.map((x) => el("button", { class: "ss-btn small", type: "button",
      onclick: () => show({ filter: x.filter || "", sort: x.sort || null }) }, x.label))) : null;
  // the name a filter uses, then the header it has on the page and what it means
  const labels = t.labels || {};
  const key = Object.keys(t.columns).length ? el("details", { class: "column-key" },
    el("summary", {}, "What the columns mean"),
    el("dl", {}, ...Object.entries(t.columns).flatMap(([k, v]) => [el("dt", {}, k),
      el("dd", {}, labels[k] && labels[k].toLowerCase() !== k ? `${labels[k]}: ${v}` : v)]))) : null;
  app.replaceChildren(
    cell(`${cls} page-head`,
      el("a", { class: "back", href: "/" }, "← Home"),
      el("div", { class: "ss-kicker" }, `${t.sport ? t.sport + " · " : ""}Data table`),
      el("h1", { class: "ss-title" }, t.title),
      el("p", { class: "summary" }, t.summary),
      examples, key),
    cell(`${cls} live-cell`, host),
    t.how ? cell(`${cls} how`, el("div", { class: "ss-band" }, "How this works"), el("p", {}, t.how)) : null);
  renderNav(`tables/${id}`);
  window.scrollTo(0, 0);
  show({});
}

// ── baseball charts (charts/: pyslots' form and templates, scripts/sync-charts.sh) ──
// The other exception to "nothing computed in the browser": the visitor's formulas fill a Python
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

// The charts come from web/charts.toml (data/site.json): a name, an intro and starting formulas for
// one of the templates. An old address naming a template (/charts/scatter/) opens its first chart.
async function renderCharts(slug) {
  const site = await getJSON("/data/site.json");
  const charts = site.charts || [];
  current = { model: null, pickers: {} };
  const t = charts.find((x) => x.id === slug) || charts.find((x) => chartSlug(x.template) === slug) || charts[0];
  if (!t) return notFound("There are no charts yet.");
  setHead(slug ? `${t.title}: Baseball charts` : "Baseball charts", t.intro, slug ? `/charts/${t.id}/` : "/charts/");
  const cls = cellClass("Baseball");
  const groups = {};
  for (const x of charts) (groups[x.group] = groups[x.group] || []).push(x);
  const host = el("div", { class: "live-chart" }, el("p", { class: "loading" }, "Loading the chart…"));
  app.replaceChildren(
    cell(`${cls} page-head`,
      el("a", { class: "back", href: "/" }, "← Home"),
      el("div", { class: "ss-kicker" }, "Baseball · Charts"),
      el("h1", { class: "ss-title" }, "Baseball charts"),
      el("p", { class: "summary" }, "Every big-league season from 1871 to 2024, charted. Pick a chart, or change any of its boxes and draw it again."),
      el("nav", { class: "chart-picks", "aria-label": "Charts" },
        ...Object.entries(groups).map(([g, xs]) => el("div", { class: "chart-group" },
          el("span", { class: "chart-group-name" }, g),
          el("div", { class: "chart-group-buttons" }, ...xs.map((x) => el("a", { class: "ss-btn small", href: `/charts/${x.id}/`,
            ...(x === t ? { "aria-current": "page" } : {}) }, x.title))))))),
    cell(`${cls} chart-cell`,
      el("div", { class: "ss-band" }, t.title),
      el("p", { class: "chart-intro" }, t.intro),
      host),
    cell(`${cls} how`, el("div", { class: "ss-band" }, "How this works"),
      el("p", {}, "Each box is a formula over a season's numbers (HR, AB, BB…). What you type is read by ",
        el("a", { href: "https://mathzetta.com/" }, "MathZetta"),
        ", shown as maths, and the chart is drawn by a short Python program right in your browser. The first chart downloads Python into your browser (a few seconds, and a sizeable download on a phone plan; afterwards it's cached); nothing you type is sent anywhere."),
      el("p", { class: "small" }, "Data: the Lahman Baseball Database (SABR, CC BY-SA 3.0): hitters with 400+ at-bats and pitchers with 100+ innings in a season.")));
  renderNav("charts");
  window.scrollTo(0, 0);
  try {
    const Pyslots = await loadPyslots();
    // the first chart downloads Python (Pyodide); readers in data-saver mode press Run themselves
    const saveData = !!(navigator.connection && navigator.connection.saveData);
    await Pyslots.mount(host, { site: new URL(CHARTS, location.href).href, template: t.template, title: t.title,
      formulas: t.formulas || {}, autoRun: !saveData });
  } catch (e) {
    host.replaceChildren(el("p", {}, "The chart couldn't load. Try again in a little while."));
    console.error(e);
  }
}

// ── page head: title, description and canonical address follow the page shown ──
const HOME_DESCRIPTION = document.querySelector('meta[name="description"]')?.content || "";
function setHead(title, description, path) {
  const full = title === "Ball Monitor" ? title : `${title} · Ball Monitor`;
  document.title = full;
  const url = `${location.origin}${path}`;
  const set = (sel, attr, value) => { const n = document.querySelector(sel); if (n && value) n.setAttribute(attr, value); };
  set('meta[name="description"]', "content", description || HOME_DESCRIPTION);
  set('meta[property="og:description"]', "content", description || HOME_DESCRIPTION);
  set('meta[property="og:title"]', "content", full);
  set('link[rel="canonical"]', "href", url);
  set('meta[property="og:url"]', "content", url);
}

function notFound(message) {
  setHead("Page not found", null, location.pathname);
  app.replaceChildren(cell("ss-p2", el("div", { class: "ss-band" }, "Page not found"),
    el("p", {}, `${message} `, el("a", { href: "/" }, "See everything"))));
}

function failed(e) {
  app.replaceChildren(cell("ss-p2", el("div", { class: "ss-band" }, "Something went wrong"),
    el("p", {}, `This page didn't load (${e.message}). Try again in a moment, or `, el("a", { href: "/" }, "go to the home page"), ".")));
  console.error(e);
}

// ── routing: / (home), /<page>/[<picker>/<option>/], /tables/<id>/, /charts/[<id>/] ──
// The text pages (/about/ ...) are plain HTML: <main data-static> is left as it is.
const parts = (path) => path.split("/").filter(Boolean).map(decodeURIComponent);

function route() {
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
  const url = new URL(a.href, location.href);
  if (!drawnHere(url)) return;
  e.preventDefault();
  if (url.pathname + url.search !== location.pathname + location.search) history.pushState(null, "", url.pathname + url.search);
  focusAfter(route());
});

// After in-site navigation, move keyboard and screen-reader focus to the new page's heading
// (a picker link focuses the picker instead, which the page scrolls to).
function focusAfter(done) {
  Promise.resolve(done).then(() => {
    const target = parts(location.pathname).length >= 3 && !["charts", "tables"].includes(parts(location.pathname)[0])
      ? app.querySelector(".view-picker select") : app.querySelector("h1");
    if (!target) return;
    if (target.tagName === "H1") target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: target.tagName !== "H1" ? true : false });
  }).catch(() => {});
}

window.addEventListener("popstate", () => {
  if (app.hasAttribute("data-static") || !drawnHere(new URL(location.href))) location.reload();
  else focusAfter(route());
});

// An old #/ address (shared before the site used paths): #/data/<id> is now /tables/<id>/.
function fromHash() {
  const m = location.hash.match(/^#\/(.*?)\/?$/);
  if (!m) return false;
  const rest = m[1].replace(/^data\//, "tables/");
  history.replaceState(null, "", rest ? `/${rest}/` : "/");
  return true;
}

let siteData = null;
const sitePromise = getJSON("/data/site.json").then((s) => { siteData = s; SPORT_CELL = s.cells || {}; return s; });
getJSON("/data/manifest.json").then((m) => {
  for (const n of document.querySelectorAll(".built")) n.textContent = `Updated ${m.build_date}.`;
}).catch(() => {});
if (fromHash() && app.hasAttribute("data-static")) location.reload();
sitePromise.catch(() => {}).finally(route);
