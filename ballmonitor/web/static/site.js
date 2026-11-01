// Ball Monitor public page. Shows the tables and charts that `ballmonitor build-site` wrote to
// data/site.json and data/views/<model>.json (from each model's site.py). It never runs a
// model: every number on the page was computed at build time.
"use strict";

const app = document.getElementById("app");
const cache = {};

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

// ── home ──────────────────────────────────────────────────────────────────────
async function renderHome() {
  const site = await getJSON("data/site.json");
  document.title = "Ball Monitor";
  const groups = {};
  for (const m of site.models) (groups[m.sport] = groups[m.sport] || []).push(m);
  app.replaceChildren(
    el("section", { class: "hero" },
      el("h1", {}, "Sports odds and forecasts, in plain numbers"),
      el("p", {}, "Playoff chances, polls re-counted, race-time predictions and more. Every page is a table or a chart, refreshed from the latest data.")),
    ...Object.entries(groups).map(([sport, models]) =>
      el("section", { class: "group" },
        el("h2", {}, sport),
        el("div", { class: "cards" }, models.map((m) =>
          el("a", { class: "card", href: `#/${m.name}` },
            el("h3", {}, m.title),
            el("p", {}, m.summary),
            m.updated ? el("span", { class: "updated" }, m.updated) : null))))),
    el("section", { class: "group" },
      el("h2", {}, "Games"),
      el("div", { class: "cards" },
        el("a", { class: "card", href: "triple/" }, el("h3", {}, "Triple Play"), el("p", {}, "A daily puzzle: put each player (or city) in the right part of three circles.")),
        el("a", { class: "card", href: "27k/" }, el("h3", {}, "27K"), el("p", {}, "A pitching game: get 27 outs.")),
        el("a", { class: "card", href: "game.html" }, el("h3", {}, "Pitch Guesser"), el("p", {}, "Guess the next pitch in real big-league situations and beat the model.")))),
  );
  window.scrollTo(0, 0);
}

// ── model page ───────────────────────────────────────────────────────────────
async function renderModel(name) {
  let page;
  try {
    page = await getJSON(`data/views/${name}.json`);
  } catch (e) {
    app.replaceChildren(el("p", { class: "loading" }, "That page doesn't exist. "), el("a", { href: "#/" }, "Back to all forecasts"));
    return;
  }
  document.title = `${page.title} · Ball Monitor`;
  app.replaceChildren(
    el("a", { class: "back", href: "#/" }, "← All forecasts"),
    el("header", { class: "page-head" },
      el("p", { class: "kicker" }, page.sport),
      el("h1", {}, page.title),
      el("p", { class: "summary" }, page.summary),
      page.updated ? el("span", { class: "updated" }, page.updated) : null),
    ...page.views.map(renderView),
    page.how ? el("section", { class: "how" },
      el("h2", {}, "How this works"),
      el("p", {}, page.how),
      el("p", { class: "small" }, el("a", { href: `editor.html?model=${encodeURIComponent(name)}` }, "Full method, settings and assumptions →"))) : null,
  );
  window.scrollTo(0, 0);
}

function viewShell(v, body) {
  return el("section", { class: `view view-${v.kind}`, id: `v-${v.id}` },
    el("h2", {}, v.title),
    v.subtitle ? el("p", { class: "subtitle" }, v.subtitle) : null,
    body,
    v.note ? el("p", { class: "note" }, v.note) : null);
}

function renderView(v) {
  switch (v.kind) {
    case "table": return viewShell(v, renderTable(v));
    case "bar": return viewShell(v, renderBars(v));
    case "line": return viewShell(v, renderLine(v));
    case "picker": return renderPicker(v);
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
  const wrap = el("div", { class: "table-wrap" });
  const search = v.search ? el("input", { class: "search", type: "search", placeholder: "Search…", "aria-label": `Search ${v.title}`,
    oninput: (e) => { state.q = e.target.value.trim().toLowerCase(); draw(); } }) : null;
  const more = el("button", { class: "more", onclick: () => { state.all = true; draw(); } });

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
    const head = el("tr", {}, v.columns.map((c) => el("th", {
      class: [numeric(c) ? "num" : "", state.sort === c.key ? (state.desc ? "sorted desc" : "sorted asc") : ""].join(" ").trim() || null,
      title: "Sort",
      onclick: () => {
        if (state.sort === c.key) state.desc = !state.desc;
        else { state.sort = c.key; state.desc = numeric(c); }
        draw();
      },
    }, c.label)));
    const body = shown.map((r) => el("tr", {}, v.columns.map((c) => {
      const val = r[c.key];
      const text = fmt(val, c.fmt, c.decimals);
      const align = c.align || (numeric(c) ? "num" : "");
      if (c.bar && typeof val === "number") {
        const w = Math.max(0, Math.min(100, (Math.abs(val) / max[c.key]) * 100));
        return el("td", { class: `${align} barcell` }, el("span", { class: "cellbar", style: `width:${w}%` }), el("span", { class: "cellval" }, text));
      }
      if (c.heat && typeof val === "number" && val > 0) {
        const a = Math.round(Math.min(1, val / heatMax) * 70);
        return el("td", { class: `${align} heat`, style: `background: color-mix(in srgb, var(--c1) ${a}%, transparent)` }, text);
      }
      return el("td", { class: [align, text.length > 36 ? "long" : ""].join(" ").trim() || null }, text);
    })));
    wrap.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
    const hidden = rs.length - shown.length;
    more.textContent = `Show all ${rs.length}`;
    more.hidden = hidden <= 0;
    if (state.q && !rs.length) wrap.append(el("p", { class: "note" }, "No matches."));
  }
  draw();
  return el("div", {}, search, wrap, more);
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
function renderPicker(v) {
  const body = el("div", { class: "picked" });
  const select = el("select", { "aria-label": v.label, onchange: (e) => show(+e.target.value) },
    v.options.map((o, i) => el("option", { value: i }, o.label)));
  function show(i) {
    select.value = String(i);
    body.replaceChildren(...v.options[i].views.map(renderView));
  }
  show(v.default || 0);
  // Long lists also get a type-to-find box (matches anywhere in the option's name).
  let find = null;
  if (v.options.length > 12) {
    const listId = `dl-${v.id}`;
    find = el("span", { class: "pick-find" },
      el("input", { class: "search", type: "search", list: listId, placeholder: `Find a ${v.label.toLowerCase()}…`,
        "aria-label": `Find a ${v.label.toLowerCase()}`,
        oninput: (e) => {
          const q = e.target.value.trim().toLowerCase();
          if (!q) return;
          const exact = v.options.findIndex((o) => o.label.toLowerCase() === q);
          const i = exact >= 0 ? exact : v.options.findIndex((o) => o.label.toLowerCase().includes(q));
          if (i >= 0 && String(i) !== select.value) show(i);
        } }),
      el("datalist", { id: listId }, v.options.map((o) => el("option", { value: o.label }))));
  }
  return el("section", { class: "view view-picker", id: `v-${v.id}` },
    el("h2", {}, v.title),
    v.subtitle ? el("p", { class: "subtitle" }, v.subtitle) : null,
    el("div", { class: "pick-row" }, el("label", { class: "pick" }, `${v.label}: `, select), find),
    v.note ? el("p", { class: "note" }, v.note) : null,
    body);
}

// ── routing: #/ (home) and #/<model> ─────────────────────────────────────────
function route() {
  const m = location.hash.match(/^#\/([a-z0-9_]+)/);
  (m ? renderModel(m[1]) : renderHome()).catch((e) => {
    app.replaceChildren(el("p", { class: "loading" }, `Something went wrong loading this page (${e.message}).`));
  });
}

window.addEventListener("hashchange", route);
getJSON("data/manifest.json").then((m) => {
  document.getElementById("built").textContent = `Updated ${m.build_date}.`;
}).catch(() => {});
route();
