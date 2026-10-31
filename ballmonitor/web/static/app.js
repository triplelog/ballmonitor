// ballmonitor browser UI. Clean, simple, responsive results exploration for every model.
// Zero build step, vanilla JS, zero external dependencies.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const MODEL_META = {
  ncaaf_recruiting: {
    category: "college",
    categoryLabel: "🏈 College Sports",
    shortName: "Football Recruiting Rankings",
    highlights: ["Football Classes 2012–2027", "Plackett-Luce Offer Elo", "Projected 4-Season SRS"],
  },
  ncaaf_bowls: {
    category: "college",
    categoryLabel: "🏈 College Sports",
    shortName: "Bowl & CFP Projections",
    highlights: ["Live ESPN Schedule & FPI", "2026 12-Team CFP", "2026-27 Bowl Tie-Ins"],
  },
  race_time: {
    category: "running",
    categoryLabel: "🏃 Distance Running",
    shortName: "Race Time Predictions",
    highlights: ["Personal Riegel Curve", "Calibrated 80% Ranges", "Elevation, Weather & GPX"],
  },
  race_podium: {
    category: "running",
    categoryLabel: "🏃 Distance Running",
    shortName: "Race Award Predictions",
    highlights: ["Division Podium (1st–5th)", "Field-Size Adjusted History", "Calibrated 80% Ranges"],
  },
  bvp_similarity: {
    category: "baseball",
    categoryLabel: "⚾ Baseball",
    shortName: "Baseball Player Similarity",
    highlights: ["Pitcher & Batter Peers", "Markov Count Micro-Sim", "Empirical Bayes Blend"],
  },
  next_pitch: {
    category: "baseball",
    categoryLabel: "⚾ Baseball",
    shortName: "Baseball Pitch Predictor",
    highlights: ["Count & Sequence Tree", "LightGBM Correction", "Interactive Pitch Game"],
  },
  mlb_bullpen: {
    category: "baseball",
    categoryLabel: "⚾ Baseball",
    shortName: "Bullpen Usage Predictor",
    highlights: ["Fitted on 30k Real Bullpen Calls", "Role × Situation Choice", "Fatigue & Rest Rules"],
  },
  cfb_replay: {
    category: "college",
    categoryLabel: "🏈 College Sports",
    shortName: "Game Replay (Shorts)",
    highlights: ["60-Second Vertical Replay", "Annotated Win-Probability Chart", "Export to MP4"],
  },
  college_diamond: {
    category: "diamond",
    categoryLabel: "🥎 College Baseball & Softball",
    shortName: "NCAA Baseball & Softball Projections",
    highlights: ["Season + Conference Tourney Sim", "RPI Selection & Seeding", "Regionals → Omaha / OKC"],
  },
  ranked_choice: {
    category: "ratings",
    categoryLabel: "🏆 Dominance Ratings",
    shortName: "Ranked-Choice Re-Counts",
    highlights: ["Real AP, MLB & NHL Ballots", "13 Voting Methods", "Condorcet Winners & Outlier Voters"],
  },
  dad: {
    category: "ratings",
    categoryLabel: "🏆 Dominance Ratings",
    shortName: "DAD Ratings & Rankings",
    highlights: ["Opponent-Adjusted Strength (σ)", "Wins Above Default", "Basketball, Football, Soccer, Baseball, Softball"],
  },
};

const FRIENDLY_FIELD_OPTIONS = {
  method: ["plackett_luce", "sequential_elo", "tree", "gbm"],
  gender: ["M", "F"],
  stand: ["R", "L", "S"],
  starter_hand: ["R", "L"],
  target: ["Mile", "5k", "8k", "10k", "10 mi", "half", "marathon", "50k"],
  balls: [0, 1, 2, 3],
  strikes: [0, 1, 2],
  outs: [0, 1, 2],
};

// Dropdown options that only make sense for one model (keyed by model name).
const MODEL_FIELD_OPTIONS = {
  college_diamond: { sport: ["baseball", "softball"] },
};

const POPULAR_ENTITIES = {
  pitchers: [
    "Dylan Cease", "Tarik Skubal", "Logan Webb", "Zack Wheeler", "Kevin Gausman",
    "Aaron Nola", "Paul Skenes", "Corbin Burnes", "Gerrit Cole", "Freddy Peralta",
    "Chris Sale", "Cole Ragans", "Sonny Gray", "Tyler Glasnow", "Max Fried"
  ],
  batters: [
    "Aaron Judge", "Shohei Ohtani", "Juan Soto", "Vladimir Guerrero Jr.", "Matt Olson",
    "Bobby Witt Jr.", "Yordan Alvarez", "Gunnar Henderson", "Freddie Freeman", "Bryce Harper",
    "Kyle Tucker", "Rafael Devers", "Mookie Betts", "Corey Seager", "Jose Altuve"
  ],
  teams: [
    "Ohio State", "Georgia", "Texas", "Alabama", "Michigan", "Oregon", "Penn State",
    "Notre Dame", "Tennessee", "Ole Miss", "NYY", "LAD", "BAL", "PHI", "HOU"
  ],
  college_teams: [
    "Ohio State", "Georgia", "Texas", "Alabama", "Michigan", "Oregon", "Penn State",
    "Notre Dame", "Tennessee", "Ole Miss", "LSU", "Clemson", "Miami (FL)", "Florida State"
  ],
  mlb_teams: [
    "NYY", "LAD", "BAL", "PHI", "HOU", "ATL", "SD", "CLE", "BOS", "KC", "DET", "MIN", "MIL", "ARI", "CHC"
  ],
  races: [
    "Cherry Blossom 10 Mile", "City Autumn 5K", "Run for the Oaks 10K",
    "Boston Marathon", "Chicago Marathon", "New York City Marathon"
  ]
};

const state = {
  models: [],
  viewMode: "home",     // "home" | "model"
  homeCategory: "all",
  detail: null,         // model detail from server
  activeExample: "default",
  values: {},           // current param values
  loaded: {},           // param values as loaded from variant/config
  exprs: {},            // current formula expressions
  loadedExprs: {},
  lastPrediction: null, // latest Prediction object
  pinned: null,         // pinned baseline Prediction object
  runTimer: null,
  runSeq: 0,
  activeFilterGroup: "all",
  searchQuery: "",
  runnerCurveMode: "pace",
  entities: {},
  manifest: null,
  isStaticMode: false,
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function staticFallback(path, body) {
  if (path === "/api/models") {
    const res = await fetch("data/models.json");
    return await res.json();
  }
  if (path.startsWith("/api/models/") && path.endsWith("/run")) {
    const parts = path.split("/");
    const modelName = parts[3];

    const exName = state.activeExample || "default";
    const res = await fetch(`data/models/${modelName}/examples/${exName}.json`);
    if (res.ok) return await res.json();
    throw new Error(`No precomputed result for ${modelName} / ${exName} on the static site.`);
  }
  if (path.startsWith("/api/models/")) {
    const cleanPath = path.split("?")[0];
    const modelName = cleanPath.replace("/api/models/", "");
    const res = await fetch(`data/models/${modelName}.json`);
    return await res.json();
  }
  throw new Error(`Static endpoint not supported for ${path}`);
}

async function api(path, body) {
  if (state.isStaticMode) {
    if (body !== undefined && !path.endsWith("/run")) {
      throw new Error("Saving needs the local server — run `ballmonitor serve`.");
    }
    return staticFallback(path, body);
  }
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// Live when the `ballmonitor serve` API answers; otherwise the static bundle (GitHub Pages, file://).
async function detectLiveServer() {
  if (location.protocol === "file:") return false;
  try {
    const res = await fetch("/api/models");
    if (!res.ok || !(res.headers.get("content-type") || "").includes("json")) return false;
    state.models = await res.json();
    return true;
  } catch (_) {
    return false;
  }
}

function setStatus(message, kind = "") {
  const elNode = $("#status");
  if (!elNode) return;
  elNode.textContent = message;
  elNode.className = `status ${kind}`;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) {
      node.append(child instanceof Node ? child : document.createTextNode(child));
    }
  }
  return node;
}

function formatTime(seconds) {
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function formatValue(v, fmt) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number" && Number.isNaN(v)) return "n/a";
  switch (fmt) {
    case "pct": return `${(v * 100).toFixed(1)}%`;
    case "time": return formatTime(v);
    case "currency": return `$${v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 })}`;
    case "int": return Math.round(v).toLocaleString();
    case "points": return `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
    default:
      if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
      return Math.abs(v) < 1 ? Number(v.toPrecision(3)).toString() : v.toFixed(2);
  }
}

function formatDelta(d, fmt) {
  if (Math.abs(d) < 1e-9) return "—";
  const sign = d > 0 ? "+" : "−";
  if (fmt === "time") return sign + formatTime(d);
  if (fmt === "pct") return `${sign}${Math.abs(d * 100).toFixed(1)} pts`;
  return sign + formatValue(Math.abs(d), fmt);
}

const formatProb = (p) => (p === null || p === undefined ? "" : p < 0.001 ? "<0.1%" : p > 0.999 ? ">99.9%" : `${(p * 100).toFixed(1)}%`);

// ── Model List, Home View & Initialization ───────────────────────────────────

async function init() {
  // 1. Live server or static bundle?
  state.isStaticMode = !(await detectLiveServer());
  if (state.isStaticMode) {
    try {
      const mRes = await fetch("data/manifest.json");
      if (mRes.ok) {
        state.manifest = await mRes.json();
        const metaEl = $("#build-meta");
        if (metaEl && state.manifest.build_date) {
          metaEl.innerHTML = `Data Synced: <strong>${esc(state.manifest.build_date)}</strong>`;
        }
      }
    } catch (_) {}
  }

  // 2. Fetch full entity autocomplete lists (1,166+ batters, 1,548+ pitchers)
  try {
    const eRes = await fetch("data/entities.json").catch(() => null);
    if (eRes && eRes.ok) {
      state.entities = await eRes.json();
    }
  } catch (_) {}


  if (!state.entities || !state.entities.batters?.length) {
    state.entities = structuredClone(POPULAR_ENTITIES);
  }

  if (state.isStaticMode) state.models = await api("/api/models");

  renderModelCounts();
  renderSidebarList();
  renderHomeView();

  // Populate topbar quick select
  const quick = $("#quick-model-select");
  quick.replaceChildren(
    el("option", { value: "" }, "Jump to model…"),
    ...state.models.map((m) => el("option", { value: m.name }, `${m.title}`))
  );
  quick.addEventListener("change", (e) => {
    if (e.target.value) selectModel(e.target.value);
    else showHome();
  });

  // Sidebar search filter
  $("#model-search").addEventListener("input", (e) => {
    renderSidebarList(e.target.value.toLowerCase().trim());
  });

  // Home navigation buttons
  $("#brand-home-link")?.addEventListener("click", (e) => {
    e.preventDefault();
    showHome();
  });
  $("#home-nav-btn")?.addEventListener("click", () => showHome());
  $("#sidebar-home-btn")?.addEventListener("click", () => showHome());


  // Resolve initial route from URL path (/model/<name>), query (?model=<name>), or hash (#model=<name>)
  const pathParts = location.pathname.split("/").filter(Boolean);
  let fromUrl = null;
  if (pathParts.length === 1 && state.models.some((m) => m.name === pathParts[0])) {
    fromUrl = pathParts[0];
  } else if (pathParts.length === 2 && (pathParts[0] === "model" || pathParts[0] === "models")) {
    fromUrl = pathParts[1];
  }
  if (!fromUrl) {
    fromUrl = new URLSearchParams(location.search).get("model") || new URLSearchParams(location.hash.slice(1)).get("model");
  }

  if (fromUrl && state.models.some((m) => m.name === fromUrl)) {
    await selectModel(fromUrl);
  } else {
    showHome();
  }

  // Back/forward between home and models
  window.addEventListener("popstate", () => {
    const name = new URLSearchParams(location.hash.slice(1)).get("model");
    if (name && state.models.some((m) => m.name === name)) selectModel(name, null, false, null, false);
    else showHome(false);
  });
}

function modelCountLabel() {
  const n = state.models.length;
  return `${n} model${n === 1 ? "" : "s"}`;
}

function renderModelCounts() {
  const n = state.models.length;
  const calibrated = state.models.filter((m) => m.status === "calibrated").length;
  const badge = $("#model-count-badge");
  if (badge) badge.textContent = String(n);
  const hero = $("#home-hero-badge");
  if (hero) hero.textContent = `${modelCountLabel()} (${calibrated} calibrated) · Interactive Explorer`;

  // Category chips, counted from the live model list
  const bar = $("#home-category-bar");
  if (!bar) return;
  const cats = new Map();
  for (const m of state.models) {
    const meta = MODEL_META[m.name] || { category: "other", categoryLabel: "📊 Other" };
    const entry = cats.get(meta.category) || { label: meta.categoryLabel, count: 0 };
    entry.count++;
    cats.set(meta.category, entry);
  }
  const chip = (cat, label) => el("button", {
    class: `filter-chip ${state.homeCategory === cat ? "active" : ""}`,
    "data-cat": cat,
    onclick: () => {
      state.homeCategory = cat;
      bar.querySelectorAll(".filter-chip").forEach((b) => b.classList.toggle("active", b.dataset.cat === cat));
      renderHomeView();
    },
  }, label);
  bar.replaceChildren(
    chip("all", `All Models (${n})`),
    ...[...cats].map(([cat, c]) => chip(cat, `${c.label} (${c.count})`)),
  );
}

function showHome(push = true) {
  const wasModel = state.viewMode === "model";
  state.viewMode = "home";
  $("#home-view")?.classList.remove("hidden");
  $("#main-layout")?.classList.add("hidden");
  $("#workspace-view-toggle")?.classList.add("hidden");
  $("#autorun-wrap")?.classList.add("hidden");
  $("#run-btn")?.classList.add("hidden");
  $("#sidebar-home-btn")?.classList.add("active");
  $$("#model-list li").forEach((li) => li.classList.remove("active"));
  const quick = $("#quick-model-select");
  if (quick) quick.value = "";
  $("#model-heading").innerHTML = `<strong>Model Showcase</strong> · ${esc(modelCountLabel())}`;
  if (push && wasModel) history.pushState(null, "", location.pathname + location.search);
}

function renderHomeView() {
  const grid = $("#home-models-grid");
  if (!grid) return;
  grid.replaceChildren();

  const items = state.models.filter((m) => {
    if (state.homeCategory === "all") return true;
    const meta = MODEL_META[m.name] || {};
    return meta.category === state.homeCategory;
  });

  for (const m of items) {
    const meta = MODEL_META[m.name] || {
      categoryLabel: "📊 Model",
      shortName: m.title,
      highlights: [],
    };
    const examples = m.examples || ["default"];

    const presetChips = el("div", { class: "home-presets" },
      el("span", { class: "hint", style: "margin-right: 2px;" }, "Presets:"),
      ...examples.slice(0, 4).map((ex) =>
        el("button", {
          class: "home-preset-btn",
          onclick: (e) => {
            e.stopPropagation();
            selectModel(m.name, null, false, ex);
          },
        }, ex.replace(/_/g, " "))
      )
    );

    const actions = el("div", { style: "display: flex; gap: 8px; align-items: center;" },
      m.name === "next_pitch"
        ? el("a", {
            href: "game.html",
            class: "ghost small",
            style: "text-decoration: none; border: 1px solid var(--border); padding: 5px 10px; border-radius: 6px; font-weight: 600;",
          }, "⚾ Pitch Game")
        : null,
      el("button", {
        class: "primary small",
        style: "padding: 6px 12px;",
        onclick: () => selectModel(m.name),
      }, "Explore Model →")
    );

    const card = el("article", { class: "home-card" },
      el("div", { class: "home-card-top" },
        el("span", { class: "home-cat-pill" }, meta.categoryLabel),
        el("span", { class: `badge ${m.status}` }, m.status)
      ),
      el("h2", { class: "home-card-title", onclick: () => selectModel(m.name) }, m.title),
      m.question ? el("p", { class: "home-card-question" }, `“${m.question}”`) : null,
      m.description ? el("p", { class: "home-card-desc" }, m.description) : null,
      meta.highlights?.length
        ? el("div", { class: "scenario-pills", style: "margin-top: 2px;" },
            ...meta.highlights.map((h) => el("span", { class: "scenario-pill" }, h))
          )
        : null,
      presetChips,
      el("div", { class: "home-card-foot" },
        el("span", { class: "hint" }, `v${m.version || "0.1.0"} · ${m.examples_count || examples.length} scenarios`),
        actions
      )
    );
    grid.append(card);
  }
}

function renderSidebarList(filter = "") {
  const list = $("#model-list");
  if (!list) return;
  list.replaceChildren();

  const filtered = filter
    ? state.models.filter((m) => m.title.toLowerCase().includes(filter) || m.name.toLowerCase().includes(filter))
    : state.models;

  for (const m of filtered) {
    const li = el("li", {
      "data-name": m.name,
      class: state.viewMode === "model" && state.detail?.name === m.name ? "active" : "",
      onclick: () => selectModel(m.name),
    },
      el("span", {}, m.title),
      el("span", { class: `badge ${m.status}` }, m.status)
    );
    list.append(li);
  }
}

async function selectModel(name, variant = null, keepInputs = false, initialExample = null, push = true) {
  let detail;
  try {
    detail = await api(`/api/models/${name}${variant ? `?variant=${encodeURIComponent(variant)}` : ""}`);
  } catch (err) {
    setStatus(err.message, "error");
    return;
  }

  state.viewMode = "model";
  $("#home-view")?.classList.add("hidden");
  $("#main-layout")?.classList.remove("hidden");
  $("#workspace-view-toggle")?.classList.remove("hidden");
  $("#autorun-wrap")?.classList.remove("hidden");
  $("#run-btn")?.classList.remove("hidden");
  $("#sidebar-home-btn")?.classList.remove("active");

  const switchedModel = !state.detail || state.detail.name !== name;
  state.detail = detail;
  state.values = Object.fromEntries(detail.params.map((p) => [p.name, p.value]));
  state.loaded = structuredClone(state.values);
  state.exprs = Object.fromEntries(detail.formulas.map((f) => [f.name, f.expr]));
  state.loadedExprs = { ...state.exprs };
  if (switchedModel) {
    state.pinned = null;
    state.activeFilterGroup = "all";
    state.searchQuery = "";
  }

  if (location.hash !== `#model=${name}`) {
    if (push) history.pushState(null, "", `#model=${name}`);
    else history.replaceState(null, "", `#model=${name}`);
  }

  $$("#model-list li").forEach((li) => li.classList.toggle("active", li.dataset.name === name));
  const quick = $("#quick-model-select");
  if (quick) quick.value = name;

  $("#model-heading").innerHTML = `<strong>${esc(detail.title)}</strong> · <span class="badge ${detail.status}">${esc(detail.status)}</span> · v${esc(detail.version)} · ${esc(detail.question)}`;

  renderExamples(keepInputs && !switchedModel, initialExample);
  renderFriendlyInputs();
  renderVariants();
  renderParams();
  renderFormulas();
  $("#docs").innerHTML = markdown(detail.doc || "_No MODEL.md documentation available yet._");
  renderBaseline();
  applyStaticMode();

  const stub = detail.status === "stub";
  $("#run-btn").disabled = stub;

  if (stub) {
    renderStubView(detail);
    setStatus("Model blueprint — plan and draft parameters displayed.", "");
    showTab("explore");
  } else {
    if (switchedModel) showTab("explore");
    run();
  }
}

function renderExamples(keepInputs, preferredExample = null) {
  const select = $("#example-select");
  const pillsBox = $("#example-pills");
  const names = Object.keys(state.detail.examples || {});
  select.replaceChildren(
    el("option", { value: "" }, names.length ? "Switch scenario…" : "No examples"),
    ...names.map((n) => el("option", { value: n }, n.replace(/_/g, " "))),
  );

  if (!keepInputs) {
    const start = (preferredExample && names.includes(preferredExample))
      ? preferredExample
      : (names.includes("default") ? "default" : names[0]);
    state.activeExample = start || "";
    $("#inputs").value = start ? state.detail.examples[start] : "";
  }

  if (pillsBox) {
    pillsBox.replaceChildren(
      ...names.map((n) =>
        el("button", {
          class: `example-pill ${state.activeExample === n ? "active" : ""}`,
          onclick: () => {
            state.activeExample = n;
            $("#inputs").value = state.detail.examples[n];
            renderExamples(true);
            renderFriendlyInputs();
            scheduleRun();
          },
        }, n.replace(/_/g, " "))
      )
    );
  }
}

// ── Friendly Quick-Input Form Controls (Synced with TOML) ────────────────────

function parseTopLevelTomlScalars(tomlText) {
  const lines = tomlText.split("\n");
  const fields = [];
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (trimmed.startsWith("[")) break; // stop at first table/array-of-tables section
    const m = trimmed.match(/^([a-zA-Z0-9_]+)\s*=\s*(.+)$/);
    if (!m) continue;
    const key = m[1];
    let rawVal = m[2].replace(/\s+#.*$/, "").trim();
    if (rawVal.startsWith("[") || rawVal.startsWith("{")) continue; // skip inline arrays/tables
    let type = "string";
    let value = rawVal;
    if ((rawVal.startsWith('"') && rawVal.endsWith('"')) || (rawVal.startsWith("'") && rawVal.endsWith("'"))) {
      value = rawVal.slice(1, -1);
      type = "string";
    } else if (rawVal === "true" || rawVal === "false") {
      value = rawVal === "true";
      type = "boolean";
    } else if (!Number.isNaN(Number(rawVal))) {
      value = Number(rawVal);
      type = "number";
    }
    fields.push({ key, value, type, lineIndex: i });
  }
  return fields;
}

function updateTomlScalar(key, newVal, type) {
  const lines = $("#inputs").value.split("\n");
  const formatted = type === "string"
    ? `"${String(newVal).replace(/"/g, '\\"')}"`
    : type === "boolean"
    ? (newVal ? "true" : "false")
    : String(newVal);

  const re = new RegExp(`^(\\s*${key}\\s*=\\s*)([^#\\n]+)(.*)$`);
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (t.startsWith("[")) break;
    if (re.test(lines[i])) {
      lines[i] = lines[i].replace(re, `$1${formatted}$3`);
      $("#inputs").value = lines.join("\n");
      scheduleRun();
      return;
    }
  }
}

function renderFriendlyInputs() {
  const box = $("#friendly-inputs");
  if (!box) return;
  box.replaceChildren();

  const fields = parseTopLevelTomlScalars($("#inputs").value);
  if (!fields.length) return;

  for (const f of fields) {
    const labelText = f.key.replace(/_/g, " ");
    let inputNode;
    const opts = (MODEL_FIELD_OPTIONS[state.detail?.name] || {})[f.key] || FRIENDLY_FIELD_OPTIONS[f.key];

    if (opts) {
      const allOpts = opts.map(String).includes(String(f.value)) ? opts : [f.value, ...opts];
      inputNode = el("select", {
        onchange: (e) => {
          const v = f.type === "number" ? Number(e.target.value) : e.target.value;
          updateTomlScalar(f.key, v, f.type);
        },
      },
        ...allOpts.map((o) => el("option", { value: String(o), selected: String(o) === String(f.value) }, String(o)))
      );
    } else if (f.type === "boolean") {
      inputNode = el("select", {
        onchange: (e) => updateTomlScalar(f.key, e.target.value === "true", "boolean"),
      },
        el("option", { value: "true", selected: f.value === true }, "Yes (true)"),
        el("option", { value: "false", selected: f.value === false }, "No (false)")
      );
    } else if (f.type === "number") {
      inputNode = el("input", {
        type: "number",
        step: "any",
        value: f.value,
        oninput: (e) => {
          if (e.target.value !== "" && !Number.isNaN(Number(e.target.value))) {
            updateTomlScalar(f.key, Number(e.target.value), "number");
          }
        },
      });
    } else {
      inputNode = el("input", {
        type: "text",
        value: f.value,
        oninput: (e) => updateTomlScalar(f.key, e.target.value, "string"),
      });
    }

    if (state.isStaticMode) inputNode.disabled = true;
    const fieldWrapper = el("div", { class: "friendly-field" },
      el("label", {}, labelText),
      inputNode
    );
    box.append(fieldWrapper);

    if (f.type === "string") {
      const k = f.key.toLowerCase();
      let entityType = null;
      let placeholder = "";
      if (k === "pitcher" || k === "pitcher_id" || k === "pitcher_name") {
        entityType = "pitchers";
        placeholder = "e.g. Dylan Cease or Tarik Skubal";
      } else if (k === "batter" || k === "batter_id" || k === "batter_name") {
        entityType = "batters";
        placeholder = "e.g. Aaron Judge or Shohei Ohtani";
      } else if (["team", "focus_team", "team_a", "team_b", "opponent", "home_team", "away_team"].includes(k)) {
        if (state.detail?.name === "mlb_bullpen") {
          entityType = "mlb_teams";
          placeholder = "e.g. NYY, LAD, BAL";
        } else if (state.detail?.name?.startsWith("ncaaf")) {
          entityType = "college_teams";
          placeholder = "e.g. Ohio State or Texas";
        } else {
          entityType = "teams";
          placeholder = "Search team…";
        }
      } else if (k === "race" || k === "race_name") {
        entityType = "races";
        placeholder = "e.g. Cherry Blossom 10 Mile";
      }

      if (entityType) {
        setupAutocomplete(inputNode, entityType, placeholder, f.key);
      }
    }
  }
}

function setupAutocomplete(inputNode, entityType, placeholder, fieldKey) {
  if (placeholder) inputNode.placeholder = placeholder;
  inputNode.setAttribute("autocomplete", "off");
  inputNode.setAttribute("spellcheck", "false");

  const wrapper = el("div", { class: "autocomplete-wrapper" });
  inputNode.parentNode.replaceChild(wrapper, inputNode);
  wrapper.appendChild(inputNode);

  const dropdown = el("div", { class: "autocomplete-dropdown" });
  wrapper.appendChild(dropdown);

  let activeIdx = -1;
  let matches = [];

  function getEntities() {
    const list = state.entities?.[entityType];
    if (Array.isArray(list) && list.length > 0) return list;
    return POPULAR_ENTITIES[entityType] || [];
  }

  function renderDropdown(val) {
    dropdown.replaceChildren();
    const all = getEntities();
    const q = (val || "").trim().toLowerCase();

    if (!q) {
      matches = (POPULAR_ENTITIES[entityType] || all).slice(0, 8);
      dropdown.appendChild(el("div", { class: "autocomplete-header" }, "Popular Suggestions"));
    } else {
      matches = all.filter((item) => item.toLowerCase().includes(q)).slice(0, 10);
      if (!matches.length) {
        dropdown.appendChild(el("div", { class: "autocomplete-item", style: "color: var(--muted); cursor: default;" }, "No matching names"));
        dropdown.classList.add("open");
        return;
      }
    }

    activeIdx = -1;
    matches.forEach((item, idx) => {
      const row = el("div", {
        class: "autocomplete-item",
        onmousedown: (e) => {
          e.preventDefault();
          choose(item);
        }
      });

      if (q && item.toLowerCase().includes(q)) {
        const start = item.toLowerCase().indexOf(q);
        const end = start + q.length;
        row.append(
          document.createTextNode(item.slice(0, start)),
          el("span", { class: "autocomplete-match" }, item.slice(start, end)),
          document.createTextNode(item.slice(end))
        );
      } else {
        row.textContent = item;
      }
      dropdown.appendChild(row);
    });

    dropdown.classList.add("open");
  }

  function choose(item) {
    inputNode.value = item;
    dropdown.classList.remove("open");
    updateTomlScalar(fieldKey, item, "string");
    scheduleRun();
  }

  inputNode.addEventListener("focus", () => {
    renderDropdown(inputNode.value);
  });

  inputNode.addEventListener("input", () => {
    renderDropdown(inputNode.value);
  });

  inputNode.addEventListener("keydown", (e) => {
    if (!dropdown.classList.contains("open")) {
      if (e.key === "ArrowDown") {
        renderDropdown(inputNode.value);
        e.preventDefault();
      }
      return;
    }

    const items = dropdown.querySelectorAll(".autocomplete-item:not([style*='cursor: default'])");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = (activeIdx + 1) % items.length;
      items.forEach((it, i) => it.classList.toggle("selected", i === activeIdx));
      if (items[activeIdx]) items[activeIdx].scrollIntoView({ block: "nearest" });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = (activeIdx - 1 + items.length) % items.length;
      items.forEach((it, i) => it.classList.toggle("selected", i === activeIdx));
      if (items[activeIdx]) items[activeIdx].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      if (activeIdx >= 0 && activeIdx < matches.length) {
        e.preventDefault();
        choose(matches[activeIdx]);
      }
    } else if (e.key === "Escape") {
      dropdown.classList.remove("open");
    }
  });

  inputNode.addEventListener("blur", () => {
    setTimeout(() => dropdown.classList.remove("open"), 250);
  });
}

// The static bundle only has base-config results, so every editor is read-only there.
function applyStaticMode() {
  $("#static-note")?.classList.toggle("hidden", !state.isStaticMode);
  $("#tweak-static-note")?.classList.toggle("hidden", !state.isStaticMode);
  if (!state.isStaticMode) return;
  $$("#panel-tweak input, #panel-tweak select, #panel-tweak textarea, #panel-tweak button").forEach((n) => { n.disabled = true; });
  $("#run-btn")?.classList.add("hidden");
  $("#pin-btn")?.classList.add("hidden");
}

function renderVariants() {
  const select = $("#variant-select");
  if (!select) return;
  const d = state.detail;
  select.replaceChildren(
    el("option", { value: "" }, "base (config.toml)"),
    ...d.variants.map((v) => el("option", { value: v, selected: v === d.variant }, v)),
  );
  const desc = $("#variant-desc");
  if (desc) desc.textContent = d.variant ? d.variant_description || "(no description)" : "Defaults from config.toml.";
}

// ── Parameter & Formula Editors ──────────────────────────────────────────────

function renderParams() {
  const box = $("#params");
  if (!box) return;
  box.replaceChildren();
  if (!state.detail.params.length) box.append(el("p", { class: "muted" }, "No parameters."));
  for (const p of state.detail.params) box.append(paramRow(p));
}

function paramRow(p) {
  const row = el("div", { class: "param", "data-param": p.name });
  const value = state.values[p.name];
  const update = (v) => {
    state.values[p.name] = v;
    syncParamRow(row, p);
    scheduleRun();
  };
  let control;

  if (p.choices) {
    control = el("select", { onchange: (e) => update(p.choices[e.target.selectedIndex]) },
      p.choices.map((c) => el("option", { selected: same(c, value) }, String(c))));
  } else if (typeof p.default === "boolean") {
    control = el("input", { type: "checkbox", checked: value, onchange: (e) => update(e.target.checked) });
  } else if (typeof p.default === "number") {
    const num = el("input", { type: "number", step: "any", value, min: p.range?.[0], max: p.range?.[1] });
    const parts = [num];
    let slider = null;
    if (p.range) {
      slider = el("input", { type: "range", min: p.range[0], max: p.range[1], step: (p.range[1] - p.range[0]) / 200, value });
      slider.addEventListener("input", () => { num.value = slider.value; update(Number(slider.value)); });
      parts.unshift(slider);
    }
    num.addEventListener("input", () => {
      if (num.value === "" || Number.isNaN(Number(num.value))) return;
      if (slider) slider.value = num.value;
      update(Number(num.value));
    });
    control = el("span", { class: "param-control" }, parts);
  } else {
    const text = el("input", { type: "text", value: typeof value === "string" ? value : JSON.stringify(value) });
    text.addEventListener("input", () => {
      if (typeof p.default === "string") return update(text.value);
      try { update(JSON.parse(text.value)); text.setCustomValidity(""); }
      catch { text.setCustomValidity("Not valid JSON/TOML value"); text.reportValidity(); }
    });
    control = text;
  }

  const reset = el("button", { class: "ghost small reset", title: `Reset to default (${JSON.stringify(p.default)})` }, "reset");
  reset.addEventListener("click", () => {
    state.values[p.name] = structuredClone(p.default);
    row.replaceWith(paramRow(p));
    scheduleRun();
  });

  const meta = [];
  if (p.range) meta.push(`range ${p.range[0]} – ${p.range[1]}`);
  meta.push(`default ${JSON.stringify(p.default)}`);
  if (p.source) meta.push(`source: ${p.source}`);

  row.append(
    el("div", { class: "param-row" },
      el("span", { class: "dot" }),
      el("span", { class: "param-name", title: p.name }, p.name),
      el("span", { class: "param-control" }, control, el("span", { class: "unit" }, p.unit || "")),
      reset),
    el("div", { class: "param-desc" }, p.description),
    el("div", { class: "param-meta" }, meta.join(" · ")),
  );
  syncParamRow(row, p);
  return row;
}

function syncParamRow(row, p) {
  const changed = !same(state.values[p.name], p.default);
  row.classList.toggle("changed", changed);
  row.querySelector(".dot").classList.toggle("changed", changed);
}

function renderFormulas() {
  const box = $("#formulas");
  if (!box) return;
  box.replaceChildren();
  const fs = state.detail.formulas;
  const help = $("#formula-help");
  if (help) {
    help.innerHTML = fs.length
      ? `Numeric parameters available by name. Built-ins: <code>${state.detail.functions.join("</code> <code>")}</code>`
      : "";
  }
  if (!fs.length) box.append(el("p", { class: "muted" }, "No formulas."));
  for (const f of fs) box.append(formulaRow(f));
}

function formulaRow(f) {
  const row = el("div", { class: "formula" });
  const area = el("textarea", { rows: Math.max(1, Math.ceil(f.expr.length / 55)), spellcheck: "false" });
  area.value = state.exprs[f.name];
  const sync = () => {
    const changed = state.exprs[f.name] !== f.default;
    row.classList.toggle("changed", changed);
    row.querySelector(".dot").classList.toggle("changed", changed);
  };
  area.addEventListener("input", () => { state.exprs[f.name] = area.value; sync(); scheduleRun(); });
  const reset = el("button", { class: "ghost small reset", title: "Reset to config.toml" }, "reset");
  reset.addEventListener("click", () => { state.exprs[f.name] = f.default; area.value = f.default; sync(); scheduleRun(); });
  const vars = f.variables.length ? ` Model supplies: ${f.variables.join(", ")}.` : "";
  row.append(
    el("div", { class: "param-row" }, el("span", { class: "dot" }), el("span", { class: "param-name" }, `ƒ ${f.name}`), reset),
    area,
    el("div", { class: "param-desc" }, f.description + vars),
  );
  sync();
  return row;
}

function overrides() {
  const out = {};
  for (const [k, v] of Object.entries(state.values)) if (!same(v, state.loaded[k])) out[k] = v;
  for (const [k, v] of Object.entries(state.exprs)) if (v !== state.loadedExprs[k]) out[`formulas.${k}`] = v;
  return out;
}

// ── Model Execution ──────────────────────────────────────────────────────────

function scheduleRun() {
  const autorunEl = $("#autorun");
  if (autorunEl && !autorunEl.checked) return;
  if (state.detail?.status === "stub") return;
  clearTimeout(state.runTimer);
  state.runTimer = setTimeout(run, 250);
}

async function run() {
  if (!state.detail || state.detail.status === "stub") return;
  const seq = ++state.runSeq;
  const started = performance.now();
  try {
    const result = await api(`/api/models/${state.detail.name}/run`, {
      variant: state.detail.variant, overrides: overrides(), inputs_toml: $("#inputs").value,
    });
    if (seq !== state.runSeq) return;

    $("#report").textContent = result.text;
    $("#markdown").textContent = result.markdown;
    $("#json").textContent = JSON.stringify(result.prediction, null, 2);
    $$(".report").forEach((r) => r.classList.remove("stale"));

    state.lastPrediction = result.prediction;
    const n = Object.keys(overrides()).length;
    if (state.isStaticMode) {
      setStatus(`Precomputed result for “${(state.activeExample || "default").replace(/_/g, " ")}”`, "ok");
    } else {
      setStatus(`Ran in ${Math.round(performance.now() - started)} ms${n ? ` · ${n} edit${n > 1 ? "s" : ""} on top of ${state.detail.variant || "base"}` : ""}`, "ok");
    }

    renderExploreView(result.prediction);
    renderTableView(result.prediction);
    renderTraceView(result.prediction);
    renderBaseline();
  } catch (err) {
    if (seq !== state.runSeq) return;
    setStatus(err.message, "error");
    $$(".report").forEach((r) => r.classList.add("stale"));
  }
}

// ── 🌟 EXPLORE TAB: Rich Web UI to Explore Results ───────────────────────────

function renderExploreView(pred) {
  const container = $("#explore-view");
  container.replaceChildren();

  if (!pred || !pred.outcomes || !pred.outcomes.length) {
    container.append(el("div", { class: "empty-state" }, "No outcomes produced by this run."));
    return;
  }

  const primary = pred.outcomes[0];
  const isProb = primary.estimate === null;
  const primaryVal = isProb ? primary.probability : primary.estimate;
  const formattedPrimary = isProb ? formatProb(primaryVal) : formatValue(primaryVal, primary.fmt);

  let deltaBadge = null;
  if (state.pinned && state.pinned.model === pred.model) {
    const bPrimary = state.pinned.outcomes[0];
    if (bPrimary) {
      const bVal = isProb ? bPrimary.probability : bPrimary.estimate;
      const d = primaryVal - bVal;
      if (Math.abs(d) > 1e-9) {
        const dText = isProb ? formatDelta(d, "pct") : formatDelta(d, primary.fmt);
        deltaBadge = el("span", { class: `hero-delta-pill ${d > 0 ? "up" : "down"}` },
          `${d > 0 ? "▲" : "▼"} ${dText} vs baseline`
        );
      }
    }
  }

  // 1. Hero Card
  const heroCard = el("section", { class: "hero-card" });
  const heroTop = el("div", { class: "hero-top" },
    el("div", { class: "hero-primary-wrap" },
      el("div", { class: "hero-eyebrow" }, primary.label || "Primary Outcome"),
      el("div", { class: "hero-value" }, formattedPrimary)
    ),
    deltaBadge
  );

  // Interval Whisker Chart
  let whisker = null;
  if (primary.interval) {
    const [lo, hi] = primary.interval;
    const span = hi - lo;
    const est = primary.estimate ?? ((lo + hi) / 2);
    const pct = span > 0 ? Math.max(0, Math.min(100, ((est - lo) / span) * 100)) : 50;

    whisker = el("div", { class: "whisker-wrap" },
      el("div", { class: "whisker-meta" },
        el("strong", {}, `${pred.interval_level ? `${Math.round(pred.interval_level * 100)}% Confidence Range` : "Confidence Interval"}`),
        el("span", {}, `${formatValue(lo, primary.fmt)} — ${formatValue(hi, primary.fmt)}`)
      ),
      el("div", { class: "whisker-bar-container" },
        el("div", { class: "whisker-range-fill", style: "left: 0%; width: 100%;" }),
        el("div", { class: "whisker-dot", style: `left: ${pct}%;`, title: `Estimate: ${formatValue(est, primary.fmt)}` })
      ),
      el("div", { class: "whisker-labels" },
        el("span", {}, `Low: ${formatValue(lo, primary.fmt)}`),
        el("span", {}, `Point: ${formatValue(est, primary.fmt)}`),
        el("span", {}, `High: ${formatValue(hi, primary.fmt)}`)
      )
    );
  }

  const scenarioPills = el("div", { class: "scenario-pills" });
  for (const [k, v] of Object.entries(pred.inputs || {})) {
    scenarioPills.append(el("span", { class: "scenario-pill" }, el("strong", {}, `${k}: `), String(v)));
  }

  heroCard.append(heroTop);
  if (whisker) heroCard.append(whisker);
  if (primary.note) heroCard.append(el("p", { class: "muted", style: "margin: 0; font-size: 13px;" }, primary.note));
  heroCard.append(scenarioPills);
  container.append(heroCard);

  // 2. Model-Specific Visual Explorer Modules (All 8 Models)
  renderModelSpecificExplorer(pred, container);

  // 3. Outcomes Explorer Breakdown
  renderOutcomesBreakdown(pred, container);

  // 4. Key Calculation Highlights & Assumptions
  renderHighlightsAndAssumptions(pred, container);
}

// ── Model-Specific Interactive Result Explorers (All 8 Models) ───────────────

function renderModelSpecificExplorer(pred, container) {
  const modelName = pred.model;
  const extras = pred.extras || {};

  // 1. RACE TIME PREDICTIONS (Calibrated Runner Curve + Environmental + GPX)
  if (modelName === "race_time" || modelName === "runner_curve") {
    renderRunnerCurveExplorer(pred, container);
  }

  // 2. RACE AWARD / PODIUM PREDICTIONS
  else if (modelName === "race_podium") {
    const places = pred.outcomes.filter((o) => /place/i.test(o.label) && o.estimate !== null);
    const medal = ["🥇 1st", "🥈 2nd", "🥉 3rd"];
    if (places.length) {
      container.append(
        el("section", { class: "ladder-section" },
          el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
            el("div", { class: "section-title" }, "Projected Division Finishing Times"),
            el("span", { class: "hint" }, `${pred.inputs?.Race || ""} · ${pred.inputs?.Division || ""}`)
          ),
          el("div", { class: "podium-grid" },
            ...places.map((o, idx) =>
              el("div", { class: `podium-card ${idx === 0 ? "gold" : ""}` },
                el("div", { class: "podium-place" }, medal[idx] || `#${idx + 1}`),
                el("div", { class: "podium-name" }, formatValue(o.estimate, o.fmt)),
                o.interval
                  ? el("div", { class: "podium-meta" },
                      `${Math.round((pred.interval_level || 0.8) * 100)}%: ${formatValue(o.interval[0], o.fmt)} – ${formatValue(o.interval[1], o.fmt)}`)
                  : null,
                o.note ? el("div", { class: "podium-meta" }, o.note) : null
              )
            )
          )
        )
      );
    }
    const probs = pred.outcomes.filter((o) => o.probability !== null && o.probability !== undefined);
    if (probs.length) {
      container.append(
        el("div", { class: "explore-grid" },
          ...probs.map((o) =>
            el("div", { class: "stat-card" },
              el("div", { class: "stat-card-title" }, o.label),
              el("div", { class: "stat-card-value" }, formatProb(o.probability)),
              o.note ? el("div", { class: "stat-card-sub" }, o.note) : null
            )
          )
        )
      );
    }
  }

  // 3. BASEBALL PLAYER SIMILARITY (BvP Similarity)
  else if (modelName === "bvp_similarity") {
    const pProf = extras.pitcher_profile;
    const bProf = extras.batter_profile;
    if (pProf && bProf) {
      const taleCard = el("section", { class: "ladder-section" },
        el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
          el("div", { class: "section-title" }, "Pitcher vs. Batter Tale of the Tape"),
          el("span", { class: "hint" }, `${extras.pooled_pa || 0} Peer Archetype PAs (${extras.eff_pa || 0} effective)`)
        ),
        el("div", { class: "versus-grid" },
          el("div", { class: "player-box" },
            el("div", { class: "player-box-title" },
              el("span", {}, `⚾ ${pProf.name}`),
              el("span", { class: "badge calibrated" }, `${pProf.throws}HP`)
            ),
            el("div", { class: "player-stats-row" },
              el("span", {}, `FB Velo: ${pProf.velo_fb} mph`),
              el("span", {}, `K%: ${(pProf.k_pct * 100).toFixed(1)}%`),
              el("span", {}, `BB%: ${(pProf.bb_pct * 100).toFixed(1)}%`),
              el("span", {}, `xwOBA: ${pProf.xwoba.toFixed(3)}`),
              el("span", {}, `0-0 Zone: ${(pProf.f_zone_pct * 100).toFixed(1)}%`)
            )
          ),
          el("div", { class: "versus-badge" }, "VS"),
          el("div", { class: "player-box" },
            el("div", { class: "player-box-title" },
              el("span", {}, `🏏 ${bProf.name}`),
              el("span", { class: "badge draft" }, `${bProf.bats}HB`)
            ),
            el("div", { class: "player-stats-row" },
              el("span", {}, `HardHit: ${(bProf.hard_hit_pct * 100).toFixed(1)}%`),
              el("span", {}, `K%: ${(bProf.k_pct * 100).toFixed(1)}%`),
              el("span", {}, `BB%: ${(bProf.bb_pct * 100).toFixed(1)}%`),
              el("span", {}, `xwOBA: ${bProf.xwoba.toFixed(3)}`),
              el("span", {}, `2S Chase: ${(bProf.chase_2s_pct * 100).toFixed(1)}%`)
            )
          )
        )
      );
      container.append(taleCard);
    }

    // Component synthesis cards: each shows its share of the final xwOBA blend
    const msW = extras.w_microsim ?? 0;
    const pctOf = (w) => `${((w ?? 0) * (1 - msW) * 100).toFixed(0)}%`;
    const compGrid = el("div", { class: "explore-grid" },
      el("div", { class: "stat-card" },
        el("div", { class: "stat-card-title" }, "Log5 Platoon Baseline"),
        el("div", { class: "stat-card-value" }, (extras.base_xwoba ?? 0.315).toFixed(3)),
        el("div", { class: "stat-card-sub" }, `xwOBA weight: ${pctOf(extras.w_baseline)}`)
      ),
      el("div", { class: "stat-card" },
        el("div", { class: "stat-card-title" }, "Peer Archetype Pool"),
        el("div", { class: "stat-card-value" }, (extras.arch_xwoba ?? 0.315).toFixed(3)),
        el("div", { class: "stat-card-sub" }, `xwOBA weight: ${pctOf(extras.w_arch)} · ${extras.pooled_pa || 0} pooled PAs`)
      ),
      el("div", { class: "stat-card" },
        el("div", { class: "stat-card-title" }, "Markov Count Micro-Sim"),
        el("div", { class: "stat-card-value" }, (extras.ms_xwoba ?? 0.315).toFixed(3)),
        el("div", { class: "stat-card-sub" }, `xwOBA weight: ${(msW * 100).toFixed(0)}% · K/BB weight: ${((extras.w_microsim_rates ?? 0) * 100).toFixed(0)}% · sim K ${((extras.ms_k || 0) * 100).toFixed(1)}%, BB ${((extras.ms_bb || 0) * 100).toFixed(1)}%`)
      )
    );
    container.append(compGrid);

    // Similar Pitchers & Similar Batters Cards
    const simP = extras.similar_pitchers || [];
    const simB = extras.similar_batters || [];
    if (simP.length || simB.length) {
      const peersGrid = el("div", { class: "explore-grid" });
      if (simP.length) {
        peersGrid.append(
          el("section", { class: "ladder-section" },
            el("div", { class: "section-head", style: "margin: 0 0 6px 0;" },
              el("div", { class: "section-title" }, "Most Similar Pitchers"),
              el("span", { class: "hint" }, "Cosine + Stuff/Count similarity")
            ),
            ...simP.slice(0, 5).map((p) => {
              const pct = Math.round(p.similarity * 100);
              return el("div", { class: "prob-item", style: "cursor: pointer;", onclick: () => updateTomlScalar("pitcher", p.name, "string") },
                el("div", { class: "prob-item-head" },
                  el("span", {}, el("strong", {}, `#${p.rank} ${p.name}`), el("span", { class: "prob-item-note" }, ` (${p.velo_fb} mph · xwOBA ${p.xwoba.toFixed(3)})`)),
                  el("span", { class: "prob-item-val" }, `${pct}%`)
                ),
                el("div", { class: "prob-bar-track" },
                  el("div", { class: "prob-bar-fill high", style: `width: ${pct}%;` })
                )
              );
            })
          )
        );
      }
      if (simB.length) {
        peersGrid.append(
          el("section", { class: "ladder-section" },
            el("div", { class: "section-head", style: "margin: 0 0 6px 0;" },
              el("div", { class: "section-title" }, "Most Similar Batters"),
              el("span", { class: "hint" }, "Swing/Chase + Damage similarity")
            ),
            ...simB.slice(0, 5).map((b) => {
              const pct = Math.round(b.similarity * 100);
              return el("div", { class: "prob-item", style: "cursor: pointer;", onclick: () => updateTomlScalar("batter", b.name, "string") },
                el("div", { class: "prob-item-head" },
                  el("span", {}, el("strong", {}, `#${b.rank} ${b.name}`), el("span", { class: "prob-item-note" }, ` (HH ${(b.hard_hit_pct * 100).toFixed(0)}% · xwOBA ${b.xwoba.toFixed(3)})`)),
                  el("span", { class: "prob-item-val" }, `${pct}%`)
                ),
                el("div", { class: "prob-bar-track" },
                  el("div", { class: "prob-bar-fill medium", style: `width: ${pct}%;` })
                )
              );
            })
          )
        );
      }
      container.append(peersGrid);
    }
  }

  // 4. NEXT PITCH PREDICTOR
  else if (modelName === "next_pitch") {
    const pitchOutcomes = pred.outcomes.filter((o) => o.probability !== null);

    const matrix = el("section", { class: "ladder-section" },
      el("div", { class: "section-head", style: "margin: 0;" },
        el("div", { class: "section-title" }, "Pitch Type Probability Distribution"),
        el("div", { style: "display: flex; gap: 10px; align-items: center;" },
          el("span", { class: "hint" }, `Method: ${extras.method || "gbm"} · ${ (extras.history_pitches || 0).toLocaleString() } historical pitches`),
          el("a", { href: "game.html", class: "primary small", style: "text-decoration: none; padding: 3px 9px; font-size: 11.5px;" }, "⚾ Test Yourself in Pitch Game →")
        )
      ),
      el("div", { style: "display: flex; flex-direction: column; gap: 8px; margin-top: 6px;" },
        ...pitchOutcomes.map((p) => {
          const prob = p.probability;
          const pct = Math.round(prob * 1000) / 10;
          return el("div", { class: "prob-item" },
            el("div", { class: "prob-item-head" },
              el("span", {},
                el("strong", {}, p.label),
                p.note ? el("span", { class: "prob-item-note" }, ` (${p.note})`) : null
              ),
              el("span", { class: "prob-item-val" }, `${pct.toFixed(1)}%`)
            ),
            el("div", { class: "prob-bar-track" },
              el("div", { class: `prob-bar-fill ${prob > 0.3 ? "high" : prob > 0.15 ? "medium" : "low"}`, style: `width: ${pct}%;` })
            )
          );
        })
      )
    );

    container.append(matrix);
  }

  // 5. MLB BULLPEN USAGE PREDICTOR
  else if (modelName === "mlb_bullpen") {
    const relievers = pred.outcomes.filter((o) => o.group === "Appearance Probability");

    const rosterSection = el("section", { class: "ladder-section" },
      el("div", { class: "section-head", style: "margin: 0 0 10px 0;" },
        el("div", { class: "section-title" }, "Bullpen Hierarchy & Reliever Availability"),
        el("span", { class: "hint" }, `${extras.n_simulations || 500} Monte Carlo game simulations`)
      ),
      el("div", { class: "roster-grid" },
        ...relievers.map((r) => {
          const prob = r.probability ?? 0;
          const pct = Math.round(prob * 100);
          let role = "middle";
          if (r.note.includes("closer")) role = "closer";
          else if (r.note.includes("setup")) role = "setup";
          else if (r.note.includes("long")) role = "long";

          return el("div", { class: "pitcher-card" },
            el("div", { class: "pitcher-head" },
              el("span", { class: "pitcher-name" }, r.label),
              el("span", { class: `role-pill role-${role}` }, role)
            ),
            el("div", { class: "prob-bar-track" },
              el("div", { class: `prob-bar-fill ${pct > 65 ? "high" : pct > 35 ? "medium" : "low"}`, style: `width: ${pct}%;` })
            ),
            el("div", { class: "pitcher-metrics" },
              el("span", {}, "Appearance: ", el("strong", {}, `${pct}%`)),
              el("span", {}, r.note.split("|")[1]?.trim() || "")
            )
          );
        })
      )
    );

    container.append(rosterSection);

    const br = extras.bullpen_runs;
    if (br) {
      const signed = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
      container.append(
        el("div", { class: "explore-grid" },
          el("div", { class: "stat-card" },
            el("div", { class: "stat-card-title" }, "Bullpen Runs vs Average"),
            el("div", { class: "stat-card-value" }, signed(br.vs_average)),
            el("div", { class: "stat-card-sub" }, "+ = more runs than a league-average pen over the same outs")
          ),
          el("div", { class: "stat-card" },
            el("div", { class: "stat-card-title" }, "Availability Effect (vs Usual)"),
            el("div", { class: "stat-card-value" }, signed(br.vs_usual)),
            el("div", { class: "stat-card-sub" }, "Today's likely arms vs this pen's usual mix")
          ),
          el("div", { class: "stat-card" },
            el("div", { class: "stat-card-title" }, "Expected Bullpen Runs"),
            el("div", { class: "stat-card-value" }, br.expected_runs.toFixed(2)),
            el("div", { class: "stat-card-sub" },
              `${Math.round((br.interval_level || 0.8) * 100)}%: ${br.interval[0].toFixed(1)}–${br.interval[1].toFixed(1)} · ${(br.expected_outs / 3).toFixed(1)} expected IP`)
          )
        )
      );
    }
  }

  // 6. NCAAF BOWLS & CFP EXPLORER
  else if (modelName === "ncaaf_bowls") {
    const cfpTeams = extras.cfp_teams || [];
    const topBowls = extras.top_bowls || [];
    const topOpps = extras.top_opponents || [];

    const bowlsGrid = el("div", { class: "explore-grid" });
    if (extras.projected_record) {
      bowlsGrid.append(
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Projected Record"),
          el("div", { class: "stat-card-value" }, extras.projected_record),
          el("div", { class: "stat-card-sub" }, `${extras.conference || "FBS"} · Power Rating: ${extras.rating ?? "—"}`)
        )
      );
    }
    if (extras.p_conf_champ !== undefined) {
      bowlsGrid.append(
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Conference Title Odds"),
          el("div", { class: "stat-card-value" }, `${(extras.p_conf_champ * 100).toFixed(1)}%`),
          el("div", { class: "stat-card-sub" }, `First-Round CFP Bye: ${((extras.p_cfp_bye || 0) * 100).toFixed(1)}%`)
        )
      );
    }
    if (topBowls.length) {
      const topBowl = topBowls[0];
      bowlsGrid.append(
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Most Likely Bowl"),
          el("div", { class: "stat-card-value", style: "font-size: 1.2rem;" }, topBowl.bowl),
          el("div", { class: "stat-card-sub" }, `Appearance: ${(topBowl.probability * 100).toFixed(1)}% · Win Rate: ${((topBowl.win_prob_cond || 0) * 100).toFixed(0)}%`)
        )
      );
    }
    container.append(bowlsGrid);

    if (cfpTeams.length) {
      const cfpSection = el("section", { class: "ladder-section" },
        el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
          el("div", { class: "section-title" }, "12-Team College Football Playoff Field Projections"),
          el("span", { class: "hint" }, "Click any team to inspect its bowl & opponent profile")
        ),
        el("div", { class: "roster-grid" },
          ...cfpTeams.slice(0, 8).map((t) => {
            const pct = Math.round(t.cfp_prob * 100);
            return el("div", {
              class: "pitcher-card",
              style: "cursor: pointer;",
              onclick: () => {
                updateTomlScalar("team", t.team, "string");
                renderFriendlyInputs();
              },
            },
              el("div", { class: "pitcher-head" },
                el("span", { class: "pitcher-name" }, `#${t.rank} ${t.team}`),
                el("span", { class: "badge calibrated" }, t.conf)
              ),
              el("div", { class: "prob-bar-track" },
                el("div", { class: `prob-bar-fill ${pct > 65 ? "high" : pct > 35 ? "medium" : "low"}`, style: `width: ${pct}%;` })
              ),
              el("div", { class: "pitcher-metrics" },
                el("span", {}, "CFP: ", el("strong", {}, `${pct}%`)),
                el("span", {}, `Title: ${(t.champ_prob * 100).toFixed(1)}% · ${t.record || ""}`)
              )
            );
          })
        )
      );
      container.append(cfpSection);
    }
  }

  // 7. COLLEGE RECRUITING RANKINGS (NCAAF, MBB, WBB)
  else if (modelName === "ncaaf_recruiting") {
    const recGrid = el("div", { class: "explore-grid" });
    if (extras.rank) {
      recGrid.append(
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, `${extras.sport_label || "National"} Rank`),
          el("div", { class: "stat-card-value" }, `#${extras.rank}`),
          el("div", { class: "stat-card-sub" }, `${extras.team} (${extras.year || 2024})`)
        ),
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Class Composite Score"),
          el("div", { class: "stat-card-value" }, `${extras.score} pts`),
          el("div", { class: "stat-card-sub" }, `Avg Recruit Caliber: ${extras.avg_score ?? "—"}`)
        ),
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Program Offer Elo"),
          el("div", { class: "stat-card-value" }, Math.round(extras.elo || 1500)),
          el("div", { class: "stat-card-sub" }, `${extras.commits || 0} signed commitments`)
        )
      );
    }
    container.append(recGrid);

    const commits = extras.team_commits || [];
    const rankings = extras.rankings || [];
    if (commits.length || rankings.length) {
      const splitSec = el("div", { class: "explore-grid" });
      if (commits.length) {
        splitSec.append(
          el("section", { class: "ladder-section" },
            el("div", { class: "section-head", style: "margin: 0 0 6px 0;" },
              el("div", { class: "section-title" }, `${extras.team} Top Commits`),
              el("span", { class: "hint" }, "Ranked by Plackett-Luce offer caliber")
            ),
            ...commits.slice(0, 6).map((c) =>
              el("div", { class: "outcome-row", style: "padding: 6px 8px;" },
                el("div", { class: "outcome-main" },
                  el("div", { class: "outcome-label" }, `#${c.rank} ${c.name} (${c.position})`),
                  el("div", { class: "outcome-note" }, `${"★".repeat(Math.max(1, c.stars || 3))} · ${c.offers_count} offers · ${c.hometown}`)
                ),
                el("span", { class: "outcome-value" }, `${c.score.toFixed(2)} pts`)
              )
            )
          )
        );
      }
      if (rankings.length) {
        splitSec.append(
          el("section", { class: "ladder-section" },
            el("div", { class: "section-head", style: "margin: 0 0 6px 0;" },
              el("div", { class: "section-title" }, `National Top 10 Leaderboard`),
              el("span", { class: "hint" }, "Click any program to inspect")
            ),
            ...rankings.slice(0, 8).map((r) =>
              el("div", {
                class: "outcome-row",
                style: "padding: 6px 8px; cursor: pointer;",
                onclick: () => {
                  updateTomlScalar("team", r.team, "string");
                  renderFriendlyInputs();
                },
              },
                el("div", { class: "outcome-main" },
                  el("div", { class: "outcome-label" }, `#${r.rank} ${r.team}`),
                  el("div", { class: "outcome-note" }, `Offer Elo: ${r.elo} · ${r.commits} commits`)
                ),
                el("span", { class: "outcome-value" }, `${r.score.toFixed(1)} pts`)
              )
            )
          )
        );
      }
      container.append(splitSec);
    }
  }

  // 11. RANKED-CHOICE RE-COUNTS (published ballots x voting methods)
  else if (modelName === "ranked_choice") {
    renderRankedChoiceExplorer(pred, container);
  }

  // 10. GAME REPLAY (vertical short-video player)
  else if (modelName === "cfb_replay") {
    renderReplayExplorer(pred, container);
  }

  // 9. COLLEGE BASEBALL & SOFTBALL (season + NCAA tournament projections)
  else if (modelName === "college_diamond") {
    renderDiamondExplorer(pred, container);
  }

  // 8. DAD RATINGS / RANKINGS (Deviations Above Default)
  else if (modelName === "dad") {
    const signed = (v, d = 2) => `${v >= 0 ? "+" : ""}${Number(v).toFixed(d)}`;
    const record = (t) => `${t.wins}-${t.losses}${t.draws ? `-${t.draws}` : ""}`;

    if (extras.total_dad !== undefined) {
      const unit = extras.sigma ? "per game" : "";
      const cards = [
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Strength vs Default (DAD per game)"),
          el("div", { class: "stat-card-value" }, `${signed(extras.dad_per_game ?? 0)}σ`),
          el("div", { class: "stat-card-sub" },
            extras.strength_vs_default !== undefined
              ? `${signed(extras.strength_vs_default, 1)} pts ${unit} better than the default · ` +
                `${Math.round((extras.win_prob_vs_default ?? 0.5) * 100)}% to beat it (neutral)`
              : `${extras.games_count ?? 0} games`)
        ),
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Season Résumé (Total DAD)"),
          el("div", { class: "stat-card-value" }, `${signed(extras.total_dad)}σ`),
          el("div", { class: "stat-card-sub" }, `Margins vs the default team's expected spread · ${extras.games_count ?? 0} games`)
        ),
        el("div", { class: "stat-card" },
          el("div", { class: "stat-card-title" }, "Wins Above Default (WAD)"),
          el("div", { class: "stat-card-value" }, `${signed(extras.total_wad ?? 0, 1)}`),
          el("div", { class: "stat-card-sub" }, `Record ${record(extras)} vs what the default team would win`)
        ),
      ];
      if (extras.has_xg) {
        cards.push(
          el("div", { class: "stat-card" },
            el("div", { class: "stat-card-title" }, "Finishing Luck (DAD − xDAD)"),
            el("div", { class: "stat-card-value" }, `${signed(extras.luck_dad ?? 0)}σ`),
            el("div", { class: "stat-card-sub" }, `xDAD: ${signed(extras.total_xdad ?? 0)}σ`)
          )
        );
      }
      container.append(el("div", { class: "explore-grid" }, ...cards));
    }

    const games = extras.game_records || [];
    if (games.length) {
      container.append(
        el("section", { class: "ladder-section" },
          el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
            el("div", { class: "section-title" }, "Game-by-Game Deviations"),
            el("span", { class: "hint" }, "σ above/below what the default baseline team would do")
          ),
          el("div", { class: "roster-grid" },
            ...games.map((g) =>
              el("div", { class: "pitcher-card" },
                el("div", { class: "pitcher-head" },
                  el("span", { class: "pitcher-name" }, `${g.loc_label || ""} ${g.opponent}`.trim()),
                  el("span", { class: `badge ${g.margin > 0 ? "calibrated" : g.margin < 0 ? "stub" : "draft"}` },
                    `${g.margin > 0 ? "W" : g.margin < 0 ? "L" : "D"} ${signed(g.margin, 0)}`)
                ),
                el("div", { class: "pitcher-metrics" },
                  el("span", {}, "DAD: ", el("strong", {}, `${signed(g.dad)}σ`)),
                  el("span", {}, `WAD: ${signed(g.wad)}${g.weight_label ? ` · ${g.weight_label}` : ""}`)
                )
              )
            )
          )
        )
      );
    }

    const board = extras.leaderboard || [];
    if (board.length) {
      container.append(
        el("section", { class: "ladder-section" },
          el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
            el("div", { class: "section-title" }, "DAD Leaderboard"),
            el("span", { class: "hint" }, "Sorted by DAD per game (strength vs default)")
          ),
          ...board.map((t, idx) =>
            el("div", { class: "outcome-row", style: "padding: 7px 10px;" },
              el("div", { class: "outcome-main" },
                el("div", { class: "outcome-label" }, `#${idx + 1} ${t.team} (${record(t)})`),
                el("div", { class: "outcome-note" }, `Résumé ${signed(t.total_dad, 1)}σ · WAD ${signed(t.total_wad, 1)}` + (t.win_prob_vs_default !== undefined ? ` · ${Math.round(t.win_prob_vs_default * 100)}% vs default` : ""))
              ),
              el("span", { class: "outcome-value" }, `${signed(t.dad_per_game)}σ/g`)
            )
          )
        )
      );
    }
  }
}

// ── Outcomes Explorer Breakdown ──────────────────────────────────────────────

function renderOutcomesBreakdown(pred, container) {
  const groups = Array.from(new Set(pred.outcomes.map((o) => o.group || "General")));

  const breakdownSec = el("section", { class: "card", style: "display: flex; flex-direction: column; gap: 12px;" });

  const filterBar = el("div", { class: "filter-bar" });
  filterBar.append(
    el("button", {
      class: `filter-chip ${state.activeFilterGroup === "all" ? "active" : ""}`,
      onclick: () => { state.activeFilterGroup = "all"; updateOutcomeList(); }
    }, `All (${pred.outcomes.length})`)
  );

  for (const g of groups) {
    const count = pred.outcomes.filter((o) => (o.group || "General") === g).length;
    filterBar.append(
      el("button", {
        class: `filter-chip ${state.activeFilterGroup === g ? "active" : ""}`,
        onclick: () => { state.activeFilterGroup = g; updateOutcomeList(); }
      }, `${g} (${count})`)
    );
  }

  const searchInput = el("input", {
    type: "search",
    class: "filter-search",
    placeholder: "Search outcomes…",
    value: state.searchQuery,
    oninput: (e) => { state.searchQuery = e.target.value.toLowerCase().trim(); updateOutcomeList(); }
  });

  const head = el("div", { class: "section-head" },
    el("div", { class: "section-title" }, "Detailed Outcomes Explorer"),
    searchInput
  );

  const listContainer = el("div", { class: "outcomes-list" });

  function updateOutcomeList() {
    filterBar.querySelectorAll(".filter-chip").forEach((btn) => {
      const g = btn.textContent.split(" (")[0];
      btn.classList.toggle("active", (state.activeFilterGroup === "all" && g === "All") || state.activeFilterGroup === g);
    });

    listContainer.replaceChildren();

    let items = pred.outcomes;
    if (state.activeFilterGroup !== "all") {
      items = items.filter((o) => (o.group || "General") === state.activeFilterGroup);
    }
    if (state.searchQuery) {
      items = items.filter((o) => o.label.toLowerCase().includes(state.searchQuery) || (o.note || "").toLowerCase().includes(state.searchQuery));
    }

    if (!items.length) {
      listContainer.append(el("div", { class: "empty-state", style: "padding: 16px;" }, "No matching outcomes found."));
      return;
    }

    for (const o of items) {
      const isProb = o.estimate === null;
      const val = isProb ? o.probability : o.estimate;
      const formatted = isProb ? formatProb(val) : formatValue(val, o.fmt);

      let visual = null;
      if (isProb && val !== null) {
        const pct = Math.round(val * 100);
        visual = el("div", { class: "prob-bar-track", style: "width: 100px;" },
          el("div", { class: `prob-bar-fill ${pct > 60 ? "high" : pct > 25 ? "medium" : "low"}`, style: `width: ${pct}%;` })
        );
      } else if (o.interval) {
        visual = el("span", { class: "hint", style: "font-variant-numeric: tabular-nums;" },
          `[${formatValue(o.interval[0], o.fmt)} — ${formatValue(o.interval[1], o.fmt)}]`
        );
      }

      listContainer.append(
        el("div", { class: "outcome-row" },
          el("div", { class: "outcome-main" },
            el("div", { class: "outcome-label" }, o.label),
            o.note ? el("div", { class: "outcome-note" }, o.note) : null
          ),
          visual,
          el("div", { class: "outcome-value-wrap" },
            el("span", { class: "outcome-value" }, formatted)
          )
        )
      );
    }
  }

  breakdownSec.append(head, filterBar, listContainer);
  container.append(breakdownSec);
  updateOutcomeList();
}

// ── Calculation Highlights & Assumptions ─────────────────────────────────────

function renderHighlightsAndAssumptions(pred, container) {
  const row = el("div", { class: "explore-grid", style: "margin-top: 4px;" });

  if (pred.steps && pred.steps.length) {
    const stepsCard = el("section", { class: "card", style: "display: flex; flex-direction: column; gap: 8px;" },
      el("div", { class: "card-head", style: "margin-bottom: 4px;" },
        el("h2", {}, "Calculation Steps"),
        el("button", { class: "ghost small", onclick: () => showTab("steps") }, `All ${pred.steps.length} Steps →`)
      ),
      el("div", { class: "trace-list" },
        ...pred.steps.slice(0, 3).map((s, idx) => el("div", { class: "trace-card", style: "padding: 8px 10px;" },
          el("span", { class: "trace-num", style: "width: 18px; height: 18px; font-size: 10px;" }, String(idx + 1)),
          el("span", { class: "trace-body", style: "font-size: 12px;" }, s)
        ))
      )
    );
    row.append(stepsCard);
  }

  if (pred.assumptions && pred.assumptions.length) {
    const assumptionsCard = el("section", { class: "card", style: "display: flex; flex-direction: column; gap: 8px;" },
      el("div", { class: "card-head", style: "margin-bottom: 4px;" },
        el("h2", {}, "Model Assumptions"),
        el("button", { class: "ghost small", onclick: () => showTab("docs") }, "Documentation →")
      ),
      el("ul", { style: "margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--text-secondary);" },
        ...pred.assumptions.map((a) => el("li", {}, a))
      )
    );
    row.append(assumptionsCard);
  }

  if (row.children.length) container.append(row);
}

// ── Stub Model View ──────────────────────────────────────────────────────────

function renderStubView(detail) {
  const container = $("#explore-view");
  container.replaceChildren();

  const bp = el("div", { class: "blueprint-card" },
    el("div", { class: "blueprint-badge" }, "Model Blueprint · Draft Specification"),
    el("h2", { class: "blueprint-title" }, detail.title),
    el("p", { class: "blueprint-question" }, `"${detail.question}"`),
    el("div", { style: "display: flex; flex-direction: column; gap: 8px; margin-top: 8px;" },
      el("h3", { style: "font-size: 13px; text-transform: uppercase; color: var(--muted); margin: 0;" }, "Planned Method & Framework"),
      el("div", { class: "docs", style: "padding: 16px; font-size: 13px;" },
        detail.doc ? markdown(detail.doc) : "See the Docs tab for design notes, backtest ideas, and mathematical definitions."
      )
    )
  );
  container.append(bp);
}

// ── 📊 TAB 2: Table View ─────────────────────────────────────────────────────

function renderTableView(pred) {
  const tbody = $("#all-outcomes-tbody");
  const groupSelect = $("#outcome-table-group");
  const searchInput = $("#outcome-table-search");

  if (!tbody || !pred || !pred.outcomes) return;

  const groups = ["All", ...Array.from(new Set(pred.outcomes.map((o) => o.group || "General")))];
  groupSelect.replaceChildren(...groups.map((g) => el("option", { value: g }, g)));

  const update = () => {
    tbody.replaceChildren();
    const grp = groupSelect.value;
    const q = (searchInput?.value || "").toLowerCase().trim();

    let items = pred.outcomes;
    if (grp && grp !== "All") items = items.filter((o) => (o.group || "General") === grp);
    if (q) items = items.filter((o) => o.label.toLowerCase().includes(q) || (o.note || "").toLowerCase().includes(q));

    for (const o of items) {
      const isProb = o.estimate === null;
      const val = isProb ? o.probability : o.estimate;
      const formatted = isProb ? formatProb(val) : formatValue(val, o.fmt);

      tbody.append(
        el("tr", {},
          el("td", { style: "font-weight: 500;" }, o.label),
          el("td", { class: "muted" }, o.group || "General"),
          el("td", { class: "num", style: "font-weight: 600;" }, formatted),
          el("td", { class: "muted" }, o.interval ? `[${formatValue(o.interval[0], o.fmt)} — ${formatValue(o.interval[1], o.fmt)}]` : "—"),
          el("td", { class: "num" }, o.probability !== null ? formatProb(o.probability) : "—"),
          el("td", { class: "muted" }, o.note || "—")
        )
      );
    }
  };

  groupSelect.onchange = update;
  if (searchInput) searchInput.oninput = update;
  update();

  $("#export-csv-btn").onclick = () => {
    const rows = [["Label", "Group", "Estimate", "Range Low", "Range High", "Probability", "Format", "Note"]];
    for (const o of pred.outcomes) {
      rows.push([
        o.label, o.group || "", o.estimate ?? "", o.interval?.[0] ?? "", o.interval?.[1] ?? "",
        o.probability ?? "", o.fmt, o.note || ""
      ]);
    }
    const csvContent = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${pred.model}_outcomes.csv`;
    link.click();
  };

  $("#copy-json-btn").onclick = () => {
    navigator.clipboard.writeText(JSON.stringify(pred.outcomes, null, 2));
    setStatus("Copied outcomes JSON to clipboard", "ok");
  };
}

// ── 🔍 TAB 3: Trace View ("Show your work") ──────────────────────────────────

function renderTraceView(pred) {
  const list = $("#trace-list");
  if (!list) return;
  list.replaceChildren();

  if (!pred.steps || !pred.steps.length) {
    list.append(el("div", { class: "empty-state" }, "No calculation steps recorded."));
    return;
  }

  for (let i = 0; i < pred.steps.length; i++) {
    const stepEl = el("div", { class: "trace-body" });
    stepEl.innerHTML = inline(pred.steps[i]);
    list.append(
      el("div", { class: "trace-card" },
        el("span", { class: "trace-num" }, String(i + 1)),
        stepEl
      )
    );
  }
}

// ── Baseline Comparison ──────────────────────────────────────────────────────

function renderBaseline() {
  const box = $("#baseline");
  const pinned = state.pinned, current = state.lastPrediction;
  if (!pinned || !current || pinned.model !== current.model) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");

  const key = (o) => `${o.group}|${o.label}`;
  const before = new Map(pinned.outcomes.map((o) => [key(o), o]));
  const rows = [
    el("tr", {},
      el("th", {}, "Outcome"),
      el("th", { class: "num" }, "Baseline"),
      el("th", { class: "num" }, "Now"),
      el("th", { class: "num" }, "Change")
    )
  ];

  let group = null;
  for (const o of current.outcomes) {
    if (o.group !== group) {
      group = o.group;
      if (group) rows.push(el("tr", { class: "group" }, el("td", { colspan: 4, style: "font-weight: 600; color: var(--muted); padding-top: 8px;" }, `▸ ${group}`)));
    }
    const b = before.get(key(o));
    const isProb = o.estimate === null;
    const now = isProb ? o.probability : o.estimate;
    const then = b ? (isProb ? b.probability : b.estimate) : null;
    const show = (v) => (isProb ? formatProb(v) : formatValue(v, o.fmt));
    const delta = then === null || then === undefined ? null : now - then;
    const deltaText = delta === null ? "new" : isProb ? formatDelta(delta, "pct") : formatDelta(delta, o.fmt);

    rows.push(
      el("tr", {},
        el("td", {}, o.label),
        el("td", { class: "num" }, then === null ? "" : show(then)),
        el("td", { class: "num" }, show(now)),
        el("td", { class: `num ${delta > 1e-9 ? "up" : delta < -1e-9 ? "down" : ""}` }, deltaText)
      )
    );
  }
  $("#baseline-table").replaceChildren(...rows);
}

// ── Saving Dialogs ───────────────────────────────────────────────────────────

function askName(title, withDescription) {
  const dialog = $("#name-dialog");
  $("#dialog-title").textContent = title;
  $("#dialog-name").value = "";
  $("#dialog-desc").value = "";
  $("#dialog-desc-wrap").classList.toggle("hidden", !withDescription);
  dialog.showModal();
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"
      ? { name: $("#dialog-name").value.trim(), description: $("#dialog-desc").value.trim() } : null), { once: true });
  });
}

async function saveVariant() {
  const answer = await askName("Save edits as a variant", true);
  if (!answer) return;
  try {
    const res = await api(`/api/models/${state.detail.name}/save-variant`, {
      name: answer.name, description: answer.description, base_variant: state.detail.variant, overrides: overrides(),
    });
    await selectModel(state.detail.name, res.variant, true);
    setStatus(`Saved ${res.saved}`, "ok");
  } catch (err) { setStatus(err.message, "error"); }
}

async function saveExample() {
  const answer = await askName("Save inputs as an example", false);
  if (!answer) return;
  try {
    const res = await api(`/api/models/${state.detail.name}/save-example`, { name: answer.name, inputs_toml: $("#inputs").value });
    state.detail.examples[res.example] = $("#inputs").value;
    state.activeExample = res.example;
    renderExamples(true);
    setStatus(`Saved ${res.saved}`, "ok");
  } catch (err) { setStatus(err.message, "error"); }
}


// ── Tabs & Markdown Parsing ──────────────────────────────────────────────────

function showTab(name) {
  $$(".tab").forEach((t) => {
    const active = t.dataset.tab === name;
    t.classList.toggle("active", active);
    t.setAttribute("aria-selected", active ? "true" : "false");
  });
  $$(".panel").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== name));
}

function inline(text) {
  return esc(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|\W)_([^_]+)_(?=\W|$)/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function markdown(src) {
  const lines = src.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith("```")) {
      const code = [];
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      i++;
    } else if (/^#{1,6} /.test(line)) {
      const level = line.match(/^#+/)[0].length;
      out.push(`<h${level}>${inline(line.slice(level + 1))}</h${level}>`);
      i++;
    } else if (line.trim().startsWith("|")) {
      const rows = [];
      for (; i < lines.length && lines[i].trim().startsWith("|"); i++) {
        rows.push(lines[i].trim().slice(1, -1).split("|").map((c) => c.trim()));
      }
      const body = rows.filter((r) => !r.every((c) => /^:?-+:?$/.test(c)));
      out.push("<div class='table-wrapper'><table class='data-table'>" + body.map((r, n) => `<tr>${r.map((c) => (n ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`)).join("")}</tr>`).join("") + "</table></div>");
    } else if (/^\s*([-*]|\d+\.) /.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      for (; i < lines.length && /^\s*([-*]|\d+\.) |^\s{2,}\S/.test(lines[i]); i++) {
        if (/^\s*([-*]|\d+\.) /.test(lines[i]) && !/^\s{2,}/.test(lines[i])) {
          items.push(lines[i].replace(/^\s*([-*]|\d+\.) /, ""));
        } else {
          items[items.length - 1] += " " + lines[i].trim().replace(/^([-*]|\d+\.) /, "— ");
        }
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`);
    } else if (line.trim() === "") {
      i++;
    } else {
      const para = [];
      for (; i < lines.length && lines[i].trim() !== "" && !/^(#|```|\||\s*([-*]|\d+\.) )/.test(lines[i]); i++) {
        para.push(lines[i]);
      }
      out.push(`<p>${inline(para.join(" "))}</p>`);
    }
  }
  return out.join("\n");
}

// ── Event Wiring ─────────────────────────────────────────────────────────────

$$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
$("#run-btn").addEventListener("click", run);
$("#inputs").addEventListener("input", () => {
  renderFriendlyInputs();
  scheduleRun();
});

$("#example-select").addEventListener("change", (e) => {
  if (!e.target.value) return;
  state.activeExample = e.target.value;
  $("#inputs").value = state.detail.examples[e.target.value];
  e.target.value = "";
  renderExamples(true);
  renderFriendlyInputs();
  scheduleRun();
});

$("#variant-select")?.addEventListener("change", (e) => selectModel(state.detail.name, e.target.value || null, true, null, false));

$("#reset-all")?.addEventListener("click", () => {
  state.values = Object.fromEntries(state.detail.params.map((p) => [p.name, structuredClone(p.default)]));
  state.exprs = Object.fromEntries(state.detail.formulas.map((f) => [f.name, f.default]));
  renderParams();
  renderFormulas();
  scheduleRun();
});

$("#save-variant")?.addEventListener("click", saveVariant);
$("#save-example")?.addEventListener("click", saveExample);

$("#pin-btn")?.addEventListener("click", () => {
  if (!state.lastPrediction) return;
  state.pinned = structuredClone(state.lastPrediction);
  renderBaseline();
  setStatus("Pinned baseline — edits will show comparative change deltas.", "ok");
});

$("#unpin-btn")?.addEventListener("click", () => {
  state.pinned = null;
  renderBaseline();
  if (state.lastPrediction) renderExploreView(state.lastPrediction);
});

$("#view-split")?.addEventListener("click", () => {
  $("#main-layout").classList.remove("focus-mode");
  $("#view-split").classList.add("active");
  $("#view-focus").classList.remove("active");
});

$("#view-focus")?.addEventListener("click", () => {
  $("#main-layout").classList.add("focus-mode");
  $("#view-focus").classList.add("active");
  $("#view-split").classList.remove("active");
});

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    run();
  }
});

init().catch((err) => setStatus(err.message, "error"));


// ── Runner Progression Curve & SVG Visualization ─────────────────────────────

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child) node.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return node;
}

function renderRunnerCurveExplorer(pred, container) {
  const extras = pred.extras || {};
  const pts = (extras.curve_points || []).map((p) => ({
    d: p.distance, label: p.distance_label,
    p025: p.p025_sec ?? p.lo_95_sec, p10: p.p10_sec ?? p.lo_80_sec, p25: p.p25_sec ?? p.lo_50_sec,
    p50: p.p50_sec ?? p.estimate_sec,
    p75: p.p75_sec ?? p.hi_50_sec, p90: p.p90_sec ?? p.hi_80_sec, p975: p.p975_sec ?? p.hi_95_sec,
  })).filter((p) => p.d && p.p50);
  const benches = (extras.benchmarks || []).map((b) => ({
    label: b.label, d: b.distance_meters, common: b.common ?? ["Mile", "5K", "10K", "Half", "Half marathon", "Marathon"].includes(b.label),
    p025: b.p025_sec ?? b.lo_95_sec, p10: b.p10_sec ?? b.interval_sec?.[0], p25: b.p25_sec, p50: b.p50_sec ?? b.estimate_sec,
    p75: b.p75_sec, p90: b.p90_sec ?? b.interval_sec?.[1], p975: b.p975_sec ?? b.hi_95_sec,
    pace: b.pace_per_mile_str, paceKm: b.pace_per_km_str,
  })).filter((b) => b.d && b.p50);
  const runs = extras.runner_points || [];
  const used = extras.races_used || [];
  const mile = 1609.344;
  // Pace on a linear axis is the default: on a finish-time axis (minutes to hours) the bands
  // shrink to a hairline. Direct labels still show finish times.
  state.runnerCurveMode = state.runnerCurveMode || "pace";
  const isPace = state.runnerCurveMode === "pace";
  const fmtRange = (lo, hi) => (lo && hi ? `${formatTime(lo)} – ${formatTime(hi)}` : "—");

  // 1. Target summary: median and the three bands
  const primary = pred.outcomes[0] || {};
  const td = extras.target_distance_m;
  const target = td
    ? (benches.find((b) => Math.abs(b.d - td) < 1) ||
       pts.reduce((best, p) => (Math.abs(Math.log(p.d / td)) < Math.abs(Math.log(best.d / td)) ? p : best), pts[0]))
    : { p50: primary.estimate, p10: primary.interval?.[0], p90: primary.interval?.[1] };
  if (target && target.p50) {
    const bandRow = (lvl, lo, hi) => el("div", { class: "band-row" },
      el("span", { class: `band-swatch band-${lvl}` }),
      el("span", { class: "band-label" }, `${lvl}% of runners like you`),
      el("strong", {}, fmtRange(lo, hi)));
    container.append(
      el("section", { class: "card band-summary" },
        el("div", { class: "band-summary-head" },
          el("div", {},
            el("div", { class: "stat-card-title" }, `${extras.target_label || primary.label || "Target"}: most likely`),
            el("div", { class: "band-median" }, formatTime(target.p50))),
          el("p", { class: "band-explainer" },
            "Race times vary from day to day. These ranges are measured from thousands of real runners' " +
            "results: the share of runners with races like yours who finished inside each range.")),
        bandRow(50, target.p25, target.p75),
        bandRow(80, target.p10, target.p90),
        bandRow(95, target.p025, target.p975),
        el("div", { class: "hint" },
          `Weighted average of Riegel predictions from ${used.length || runs.length} race${(used.length || runs.length) === 1 ? "" : "s"}` +
          (extras.exponent ? ` (exponent ${Number(extras.exponent).toFixed(3)})` : ""))
      )
    );
  }

  // 2. Chart: every distance, bands, common distances highlighted
  if (pts.length) {
    const W = 900, H = 420, m = { top: 18, right: 30, bottom: 46, left: 70 };
    const pw = W - m.left - m.right, ph = H - m.top - m.bottom;
    const dMin = Math.min(...pts.map((p) => p.d)), dMax = Math.max(...pts.map((p) => p.d));
    const xMap = (d) => m.left + (Math.log(d / dMin) / Math.log(dMax / dMin)) * pw;
    const val = (sec, d) => (isPace ? sec / (d / mile) : sec);
    const lows = pts.map((p) => val(p.p025 ?? p.p10 ?? p.p50, p.d));
    const highs = pts.map((p) => val(p.p975 ?? p.p90 ?? p.p50, p.d));
    for (const r of runs) { lows.push(val(r.time_sec, r.distance)); highs.push(val(r.time_sec, r.distance)); }
    let yLo = Math.min(...lows), yHi = Math.max(...highs);
    let yMap, ticks;
    if (isPace) {
      const pad = (yHi - yLo) * 0.06; yLo -= pad; yHi += pad;
      yMap = (v) => m.top + ((v - yLo) / (yHi - yLo)) * ph;  // faster pace at the top
      const step = [15, 30, 60, 120].find((s) => (yHi - yLo) / s <= 8) || 120;
      ticks = []; for (let t = Math.ceil(yLo / step) * step; t <= yHi; t += step) ticks.push(t);
    } else {
      yLo *= 0.92; yHi *= 1.08;
      yMap = (v) => m.top + ph - (Math.log(v / yLo) / Math.log(yHi / yLo)) * ph;
      ticks = [180, 300, 600, 900, 1200, 1800, 2700, 3600, 5400, 7200, 10800, 14400, 18000, 21600]
        .filter((t) => t >= yLo && t <= yHi);
    }
    const fmtY = (v) => (isPace ? `${formatTime(v)}/mi` : formatTime(v));

    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "curve-svg", role: "img",
      "aria-label": "Predicted finish time by distance with 50%, 80% and 95% ranges" });
    // gridlines + y labels
    for (const t of ticks) {
      const y = yMap(t);
      svg.append(svgEl("line", { x1: m.left, x2: W - m.right, y1: y, y2: y, class: "chart-grid" }),
        svgEl("text", { x: m.left - 8, y: y + 4, "text-anchor": "end", class: "chart-tick" }, fmtY(t)));
    }
    // bands (95 widest/lightest -> 50 narrowest/darkest), then the median line
    const band = (lo, hi, cls) => {
      const ok = pts.filter((p) => p[lo] && p[hi]);
      if (ok.length < 2) return;
      const top = ok.map((p) => `${xMap(p.d).toFixed(1)},${yMap(val(p[hi], p.d)).toFixed(1)}`);
      const bot = ok.slice().reverse().map((p) => `${xMap(p.d).toFixed(1)},${yMap(val(p[lo], p.d)).toFixed(1)}`);
      svg.append(svgEl("polygon", { points: top.concat(bot).join(" "), class: cls }));
    };
    band("p025", "p975", "band-fill band-95");
    band("p10", "p90", "band-fill band-80");
    band("p25", "p75", "band-fill band-50");
    svg.append(svgEl("path", { class: "median-line",
      d: pts.map((p, i) => `${i ? "L" : "M"}${xMap(p.d).toFixed(1)} ${yMap(val(p.p50, p.d)).toFixed(1)}`).join(" ") }));
    // common distances: guide, label, median marker + direct label; others: axis tick only
    const shortLabel = (l) => l.replace(/half marathon/i, "Half").replace(/^10 mile$/i, "10 mi");
    const placed = [];
    const inRange = benches.filter((b) => b.d >= dMin && b.d <= dMax);
    for (const b of inRange.filter((b) => b.common)) {
      const x = xMap(b.d), y = yMap(val(b.p50, b.d));
      svg.append(
        svgEl("line", { x1: x, x2: x, y1: m.top, y2: H - m.bottom, class: "common-guide" }),
        svgEl("circle", { cx: x, cy: y, r: 5, class: "common-marker" }),
        svgEl("text", { x: x + 8, y: y - 8, class: "common-value" }, formatTime(b.p50)));
    }
    // axis labels: common distances always, others only where they don't collide
    for (const b of [...inRange.filter((b) => b.common), ...inRange.filter((b) => !b.common)]) {
      const x = xMap(b.d);
      const text = shortLabel(b.label);
      const half = text.length * 3.6 + 6;
      if (placed.some(([px, ph]) => Math.abs(px - x) < ph + half)) continue;
      placed.push([x, half]);
      svg.append(
        svgEl("line", { x1: x, x2: x, y1: H - m.bottom, y2: H - m.bottom + 5, class: "chart-grid" }),
        svgEl("text", { x, y: H - m.bottom + 18, "text-anchor": "middle",
          class: b.common ? "chart-tick strong" : "chart-tick" }, text));
    }
    // runner's own races
    for (const r of runs) {
      if (r.distance < dMin || r.distance > dMax) continue;
      svg.append(svgEl("circle", { cx: xMap(r.distance), cy: yMap(val(r.time_sec, r.distance)), r: 5.5, class: "race-marker" }));
    }
    svg.append(svgEl("text", { x: m.left + pw / 2, y: H - 8, "text-anchor": "middle", class: "chart-axis-title" },
      "Distance (log scale)"));
    // crosshair + tooltip
    const cross = svgEl("line", { y1: m.top, y2: H - m.bottom, class: "chart-crosshair", visibility: "hidden" });
    const dot = svgEl("circle", { r: 4.5, class: "common-marker", visibility: "hidden" });
    const hit = svgEl("rect", { x: m.left, y: m.top, width: pw, height: ph, fill: "transparent" });
    svg.append(cross, dot, hit);
    const wrap = el("div", { class: "curve-svg-container" }, svg);
    const tip = el("div", { class: "chart-tooltip hidden" });
    wrap.append(tip);
    const show = (evt) => {
      const rect = svg.getBoundingClientRect();
      const sx = ((evt.clientX - rect.left) / rect.width) * W;
      const near = pts.reduce((a, p) => (Math.abs(xMap(p.d) - sx) < Math.abs(xMap(a.d) - sx) ? p : a), pts[0]);
      const x = xMap(near.d), y = yMap(val(near.p50, near.d));
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("visibility", "visible");
      const km = near.d / 1000;
      const named = benches.find((b) => Math.abs(Math.log(b.d / near.d)) < 0.015);
      const distText = named ? named.label : `${km.toFixed(km < 10 ? 2 : 1)} km · ${(near.d / mile).toFixed(km < 16 ? 2 : 1)} mi`;
      tip.replaceChildren(
        el("div", { class: "tip-value" }, formatTime(near.p50)),
        el("div", { class: "tip-label" }, `${distText} · most likely finish`),
        el("div", { class: "tip-row" }, `50%: ${fmtRange(near.p25, near.p75)}`),
        el("div", { class: "tip-row" }, `80%: ${fmtRange(near.p10, near.p90)}`),
        el("div", { class: "tip-row" }, `95%: ${fmtRange(near.p025, near.p975)}`),
        el("div", { class: "tip-row muted" }, `Pace ${formatTime(near.p50 / (near.d / mile))}/mi`));
      tip.classList.remove("hidden");
      const left = (x / W) * rect.width, flip = left > rect.width * 0.62;
      tip.style.left = `${flip ? left - tip.offsetWidth - 14 : left + 14}px`;
      tip.style.top = `${Math.max(4, (y / H) * rect.height - 40)}px`;
    };
    hit.addEventListener("pointermove", show);
    hit.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.classList.add("hidden");
    });

    const legend = el("div", { class: "chart-legend" },
      el("div", { class: "legend-item" }, el("span", { class: "legend-line median-swatch" }), el("span", {}, "Most likely (median)")),
      el("div", { class: "legend-item" }, el("span", { class: "band-swatch band-50" }), el("span", {}, "50% range")),
      el("div", { class: "legend-item" }, el("span", { class: "band-swatch band-80" }), el("span", {}, "80% range")),
      el("div", { class: "legend-item" }, el("span", { class: "band-swatch band-95" }), el("span", {}, "95% range")),
      runs.length ? el("div", { class: "legend-item" }, el("span", { class: "legend-dot race-swatch" }), el("span", {}, "Your races")) : null);
    container.append(
      el("section", { class: "runner-chart-card" },
        el("div", { class: "chart-header" },
          el("div", {},
            el("div", { class: "section-title", style: "font-size: 1.05rem;" }, "Predicted finish time at every distance"),
            el("span", { class: "hint" }, isPace ? "Pace per mile at each distance (labels show finish times); hover for the ranges" : "Finish time on a log scale; hover for the ranges")),
          el("div", { class: "view-toggle", role: "group" },
            el("button", { class: `view-btn ${isPace ? "active" : ""}`, onclick: () => { state.runnerCurveMode = "pace"; renderExploreView(pred); } }, "Pace (min/mi)"),
            el("button", { class: `view-btn ${!isPace ? "active" : ""}`, onclick: () => { state.runnerCurveMode = "time"; renderExploreView(pred); } }, "Finish time"))),
        legend, wrap));
  }

  // 3. Table view of every benchmark distance (common distances first-class)
  if (benches.length) {
    const rows = benches.map((b) => el("tr", { class: b.common ? "common-row" : "" },
      el("td", {}, b.label), el("td", { class: "num" }, formatTime(b.p50)),
      el("td", { class: "num" }, b.pace ? `${b.pace}/mi` : formatTime(b.p50 / (b.d / mile))),
      el("td", { class: "num" }, fmtRange(b.p25, b.p75)), el("td", { class: "num" }, fmtRange(b.p10, b.p90)),
      el("td", { class: "num" }, fmtRange(b.p025, b.p975))));
    container.append(el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", {}, "All distances")),
      el("div", { class: "table-wrapper" },
        el("table", { class: "data-table" },
          el("thead", {}, el("tr", {}, ...["Distance", "Most likely", "Pace", "50% range", "80% range", "95% range"]
            .map((h, i) => el("th", { class: i ? "num" : "" }, h)))),
          el("tbody", {}, ...rows)))));
  }

  // 4. How each race contributed
  if (used.length) {
    const total = used.reduce((t, r) => t + (r.weight || 0), 0) || 1;
    container.append(el("section", { class: "card" },
      el("div", { class: "card-head" }, el("h2", {}, "Your races and how much each counts")),
      el("div", { class: "table-wrapper" },
        el("table", { class: "data-table" },
          el("thead", {}, el("tr", {}, ...["Race", "Time", "Date", "Weight", `Implies (${extras.target_label || "target"})`]
            .map((h, i) => el("th", { class: i > 1 ? "num" : "" }, h)))),
          el("tbody", {}, ...used.map((r) => el("tr", {},
            el("td", {}, r.distance_label), el("td", {}, r.time_str),
            el("td", { class: "num" }, r.date || r.year || "—"),
            el("td", { class: "num" }, `${Math.round((r.weight / total) * 100)}%`),
            el("td", { class: "num" }, r.implied_target_sec ? formatTime(r.implied_target_sec) : "—"))))))));
  }
}


// ── College baseball & softball: team odds, bubble and a sortable field table ─

function renderDiamondExplorer(pred, container) {
  const e = pred.extras || {};
  const teams = e.teams || {};
  const info = e.team_info || {};
  const rating = e.rating || {};
  const rpiNow = e.rpi_rank_now || {};
  const softball = e.sport === "softball";
  const wcws = softball ? "Reach WCWS (OKC)" : "Reach CWS (Omaha)";
  const pct = (v) => (v === undefined || v === null ? "—" : formatProb(v));
  const nameOf = (k) => info[k]?.name || k;
  const rec = (s) => `${s.wins.toFixed(1)}–${s.losses.toFixed(1)}`;

  // 1. The selected team
  const me = e.team ? teams[e.team] : null;
  if (me) {
    const card = (title, value, sub) => el("div", { class: "stat-card" },
      el("div", { class: "stat-card-title" }, title), el("div", { class: "stat-card-value" }, value),
      sub ? el("div", { class: "stat-card-sub" }, sub) : null);
    container.append(el("div", { class: "explore-grid" },
      card("NCAA Bid", pct(me.bid), `Auto bid ${pct(me.auto_bid)} · seed line ${me.seed_line ? me.seed_line.toFixed(1) : "—"}`),
      card("Host a Regional", pct(me.host), `National seed ${pct(me.national_seed)}`),
      card(wcws, pct(me.super), `Win regional ${pct(me.regional)} · finals ${pct(me.finals)}`),
      card("National Title", pct(me.title), `Rating ${rating[e.team] !== undefined ? (rating[e.team] >= 0 ? "+" : "") + rating[e.team].toFixed(2) : "—"} runs vs avg`),
      card("Projected Record", rec(me), `80%: ${me.wins_iv?.[0] ?? "—"}–${me.wins_iv?.[1] ?? "—"} wins · conf ${me.conf_wins.toFixed(1)}–${me.conf_losses.toFixed(1)}`),
      card("Conference", info[e.team]?.conference || "—", `Reg. title ${pct(me.reg_title)} · tourney ${pct(me.conf_tourney)}`),
    ));
  }

  const keys = Object.keys(teams);
  if (!keys.length) return;

  // 2. Bubble: teams whose bid chance is genuinely uncertain
  const bubble = keys.filter((k) => teams[k].bid >= 0.1 && teams[k].bid <= 0.9)
    .sort((a, b) => teams[b].bid - teams[a].bid).slice(0, 16);
  if (bubble.length) {
    container.append(el("section", { class: "ladder-section" },
      el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
        el("div", { class: "section-title" }, "Bubble (10–90% to make the field)"),
        el("span", { class: "hint" }, "Click a team to make it the selected team")),
      el("div", { class: "roster-grid" }, ...bubble.map((k) => {
        const s = teams[k], pctBid = Math.round(s.bid * 100);
        return el("div", { class: "pitcher-card", style: "cursor: pointer;",
          onclick: () => { updateTomlScalar("team", nameOf(k), "string"); renderFriendlyInputs(); } },
          el("div", { class: "pitcher-head" },
            el("span", { class: "pitcher-name" }, nameOf(k)),
            el("span", { class: "badge draft" }, info[k]?.conference || "")),
          el("div", { class: "prob-bar-track" },
            el("div", { class: `prob-bar-fill ${pctBid > 65 ? "high" : pctBid > 35 ? "medium" : "low"}`, style: `width: ${pctBid}%;` })),
          el("div", { class: "pitcher-metrics" },
            el("span", {}, "Bid: ", el("strong", {}, `${pctBid}%`)),
            el("span", {}, `RPI now ${rpiNow[k] ?? "—"} · proj ${rec(s)}`)));
      }))));
  }

  // 3. Sortable, filterable table of the whole field
  const cols = [
    { key: "name", label: "Team", get: (k) => nameOf(k), text: true },
    { key: "conf", label: "Conf", get: (k) => info[k]?.conference || "", text: true },
    { key: "rating", label: "Rating", get: (k) => rating[k] ?? -99, fmt: (v) => (v === -99 ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2)) },
    { key: "rpi", label: "RPI now", get: (k) => rpiNow[k] ?? 999, fmt: (v) => (v === 999 ? "—" : String(v)), asc: true },
    { key: "record", label: "Proj W–L", get: (k) => teams[k].wins, fmt: (_, k) => rec(teams[k]) },
    { key: "bid", label: "Bid", get: (k) => teams[k].bid, fmt: pct },
    { key: "host", label: "Host", get: (k) => teams[k].host, fmt: pct },
    { key: "nseed", label: "Nat. seed", get: (k) => teams[k].national_seed, fmt: pct },
    { key: "regional", label: "Win reg.", get: (k) => teams[k].regional, fmt: pct },
    { key: "super", label: softball ? "WCWS" : "Omaha", get: (k) => teams[k].super, fmt: pct },
    { key: "title", label: "Title", get: (k) => teams[k].title, fmt: pct },
  ];
  state.diamondSort = state.diamondSort || { key: "title", desc: true };
  const search = el("input", { type: "search", class: "filter-search", placeholder: "Search teams…" });
  const confs = [...new Set(keys.map((k) => info[k]?.conference).filter(Boolean))].sort();
  const confSel = el("select", { class: "filter-select" },
    el("option", { value: "" }, "All conferences"), ...confs.map((c) => el("option", { value: c }, c)));
  const thead = el("thead");
  const tbody = el("tbody");
  const count = el("span", { class: "hint" });

  const draw = () => {
    const q = search.value.trim().toLowerCase(), conf = confSel.value;
    const col = cols.find((c) => c.key === state.diamondSort.key) || cols[10];
    let rows = keys.filter((k) => (!q || nameOf(k).toLowerCase().includes(q)) && (!conf || info[k]?.conference === conf));
    rows.sort((a, b) => {
      const va = col.get(a), vb = col.get(b);
      const c = col.text ? String(va).localeCompare(String(vb)) : va - vb;
      return state.diamondSort.desc ? -c : c;
    });
    count.textContent = `${rows.length} team${rows.length === 1 ? "" : "s"}${rows.length > 100 ? " (showing 100)" : ""}`;
    thead.replaceChildren(el("tr", {}, ...cols.map((c) => el("th", {
      class: c.text ? "sortable" : "num sortable", style: "cursor: pointer;",
      title: `Sort by ${c.label}`,
      onclick: () => {
        state.diamondSort = { key: c.key, desc: state.diamondSort.key === c.key ? !state.diamondSort.desc : !(c.text || c.asc) };
        draw();
      },
    }, c.label + (state.diamondSort.key === c.key ? (state.diamondSort.desc ? " ▾" : " ▴") : "")))));
    tbody.replaceChildren(...rows.slice(0, 100).map((k) => el("tr", {
      class: k === e.team ? "common-row" : "", style: "cursor: pointer;",
      onclick: () => { updateTomlScalar("team", nameOf(k), "string"); renderFriendlyInputs(); },
    }, ...cols.map((c) => el("td", { class: c.text ? "" : "num" }, c.fmt ? c.fmt(c.get(k), k) : String(c.get(k)))))));
  };
  search.addEventListener("input", draw);
  confSel.addEventListener("change", draw);
  draw();

  container.append(el("section", { class: "card" },
    el("div", { class: "card-head" },
      el("h2", {}, `${e.season} ${softball ? "softball" : "baseball"} field — as of ${e.as_of}`),
      el("div", { class: "table-filters" }, search, confSel, count)),
    el("div", { class: "table-wrapper" }, el("table", { class: "data-table" }, thead, tbody))));
}


// ── Game replay: the same canvas renderer the MP4 export uses ─────────────────

// Ranked-choice re-counts: pick a contest, then the place every method gives each candidate.
const RC_LABELS = {
  official: "Official", borda: "Borda", custom_points: "Custom", plurality: "Plurality", irv: "IRV",
  coombs: "Coombs", baldwin: "Baldwin", bucklin: "Bucklin", copeland: "Copeland", schulze: "Schulze",
  ranked_pairs: "Ranked pairs", minimax: "Minimax", kemeny: "Kemeny",
};
const RC_SOURCES = {
  ap_cfb: "AP Top 25 · football", ap_mbb: "AP Top 25 · men's basketball", ap_wbb: "AP Top 25 · women's basketball",
  mlb: "MLB awards (BBWAA)", nba: "NBA awards", nhl: "NHL awards (PHWA)",
};

function renderRankedChoiceExplorer(pred, container) {
  const e = pred.extras || {};
  const cands = e.candidates || {};
  const orders = e.orders || {};
  const methods = Object.keys(orders);
  if (!methods.length) return;
  const nameOf = (c) => cands[c]?.name || c;
  const official = orders.official || orders[methods[0]];
  const offPos = Object.fromEntries(official.map((c, i) => [c, i + 1]));
  const show = Math.min(e.n_places || 25, official.length);

  // 1. contest picker (live server only: the static site has just the precomputed examples)
  const index = e.index || {};
  const sources = Object.keys(index);
  if (sources.length) {
    const cur = e.contest?.contest_id || "";
    const curSource = sources.find((s) => (index[s] || []).some(([id]) => id === cur)) || sources[0];
    const contestSel = el("select", { class: "quick-select" });
    const fill = (src) => {
      contestSel.innerHTML = "";
      [...(index[src] || [])].reverse().forEach(([id, title]) =>
        contestSel.append(el("option", { value: id, ...(id === cur ? { selected: "selected" } : {}) }, title)));
    };
    const sourceSel = el("select", { class: "quick-select" },
      ...sources.map((s) => el("option", { value: s, ...(s === curSource ? { selected: "selected" } : {}) }, RC_SOURCES[s] || s)));
    fill(curSource);
    const go = () => { $("#inputs").value = `contest = "${contestSel.value}"\n`; renderFriendlyInputs(); scheduleRun(); };
    sourceSel.addEventListener("change", () => { fill(sourceSel.value); go(); });
    contestSel.addEventListener("change", go);
    if (state.isStaticMode) { sourceSel.disabled = true; contestSel.disabled = true; }
    container.append(el("section", { class: "ladder-section" },
      el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
        el("div", { class: "section-title" }, "Contest"),
        el("span", { class: "hint" }, state.isStaticMode
          ? "Run `ballmonitor serve` to pick any contest; this page shows the precomputed examples."
          : "Every published ballot since 2014 (AP), 2012 (MLB), 2018 (NHL)")),
      el("div", { style: "display: flex; gap: 8px; flex-wrap: wrap;" }, sourceSel, contestSel)));
  }

  // 2. headline cards
  const winners = methods.map((m) => orders[m][0]);
  const agree = winners.filter((w) => w === official[0]).length;
  const card = (title, value, sub) => el("div", { class: "stat-card" },
    el("div", { class: "stat-card-title" }, title), el("div", { class: "stat-card-value" }, value),
    sub ? el("div", { class: "stat-card-sub" }, sub) : null);
  container.append(el("div", { class: "explore-grid" },
    card("Official Winner", nameOf(official[0]), `${cands[official[0]]?.first ?? 0} of ${e.n_ballots} first-place votes`),
    card("Condorcet Winner", e.condorcet_winner ? nameOf(e.condorcet_winner) : "None",
      e.condorcet_winner ? "Beats every rival head to head" : `Cycle · Smith set: ${(e.smith_set || []).map(nameOf).join(", ")}`),
    card("Methods Agreeing", `${agree} / ${methods.length}`, agree === methods.length ? "Same winner under every method" :
      `Others pick ${[...new Set(winners.filter((w) => w !== official[0]))].map(nameOf).join(", ")}`),
    card("Ballots", String(e.n_ballots), `${e.n_places} places each · ${Object.keys(cands).length} candidates named`)));

  // 3. place-by-method grid (rows in official order; ▲/▼ + tint = better/worse than official)
  const rows = [];
  for (const m of methods) for (const c of orders[m].slice(0, show)) if (!rows.includes(c)) rows.push(c);
  rows.sort((a, b) => offPos[a] - offPos[b]);
  const cols = methods.filter((m) => m !== "official");
  const table = el("table", { class: "data-table rc-grid" },
    el("thead", {}, el("tr", {}, el("th", {}, "Candidate"), el("th", { class: "num" }, "Official"),
      ...cols.map((m) => el("th", { class: "num" }, RC_LABELS[m] || m)))),
    el("tbody", {}, ...rows.map((c) => el("tr", {},
      el("td", {}, nameOf(c) + (cands[c]?.team ? ` (${cands[c].team})` : "")),
      el("td", { class: "num" }, String(offPos[c])),
      ...cols.map((m) => {
        const place = orders[m].indexOf(c) + 1, diff = offPos[c] - place;
        const cls = diff > 0 ? "num rc-up" : diff < 0 ? "num rc-down" : "num rc-same";
        return el("td", { class: cls, title: `${RC_LABELS[m]}: ${place} (official ${offPos[c]})` },
          diff === 0 ? String(place) : `${place} ${diff > 0 ? "▲" : "▼"}`);
      })))));
  container.append(el("section", { class: "ladder-section" },
    el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
      el("div", { class: "section-title" }, "Place by method"),
      el("span", { class: "hint" }, "▲ better than the official place · ▼ worse")),
    el("div", { class: "table-wrapper" }, table)));

  // 4. most unusual ballots
  if ((e.unusual || []).length) {
    container.append(el("section", { class: "ladder-section" },
      el("div", { class: "section-head", style: "margin: 0 0 8px 0;" },
        el("div", { class: "section-title" }, "Most unusual ballots"),
        el("span", { class: "hint" }, "Footrule distance from the chosen method's ranking")),
      ...e.unusual.map((u) => el("div", { class: "outcome-row", style: "padding: 6px 8px;" },
        el("div", { class: "outcome-main" },
          el("div", { class: "outcome-label" }, u.voter + (u.affiliation ? ` · ${u.affiliation}` : "")),
          el("div", { class: "outcome-note" }, u.ballot.slice(0, 5).map((c, i) => `${i + 1}. ${nameOf(c)}`).join("  "))),
        el("span", { class: "outcome-value" }, String(u.distance))))));
  }
}

// Side list for the replay player: the annotated cards (chart mode) or the held plays.
function replayList(e, dur, seek) {
  const q = (p) => (p.quarter <= 4 ? `Q${p.quarter} ${String(p.clock || "").replace(/^0(\d)/, "$1")}` : p.quarter === 5 ? "OT" : `${p.quarter - 4}OT`);
  if (e.structure === "chart") {
    const notes = e.annotations || [];
    return [
      el("p", { class: "hint" }, `${notes.length} plays annotated on the win-probability chart in ${dur} s: every score, then the biggest swings. Bigger plays get a bigger card and a longer pause.`),
      el("div", { class: "section-title", style: "margin-top: 10px;" }, "Annotated plays"),
      ...notes.map((a) => el("div", { class: "replay-top", onclick: () => seek(a.t_show + 0.6) },
        el("strong", {}, a.scoring ? `${a.away_score}–${a.home_score}` : `+${Math.round(a.abs_swing * 100)}%`),
        el("span", {}, ` ${q(a)} · ${a.phrase} · ${(a.t_end - a.t_start).toFixed(1)} s`))),
    ];
  }
  const top = (e.top_plays || []).map((idx) => e.plays.find((p) => p.idx === idx)).filter(Boolean);
  return [
    el("p", { class: "hint" }, `${e.plays.length} events in ${dur} s (${e.plays.filter((x) => x.kind === "drive").length} quiet drives shown as one event each). Big win-probability swings are held on screen; small plays flash by.`),
    el("div", { class: "section-title", style: "margin-top: 10px;" }, "Held plays"),
    ...top.map((p) => el("div", { class: "replay-top", onclick: () => seek(p.t_start + 0.01) },
      el("strong", {}, `+${Math.round(p.abs_swing * 100)}%`),
      el("span", {}, ` ${p.headline || ""} · ${q(p)} · ${(p.t_end - p.t_start).toFixed(1)} s`))),
  ];
}

function renderReplayExplorer(pred, container) {
  const e = pred.extras || {};
  if (!window.ReplayRenderer || !e.plays || !e.plays.length) return;
  if (state.replayRaf) cancelAnimationFrame(state.replayRaf);
  const renderer = new ReplayRenderer(e);
  const W = ReplayRenderer.WIDTH, H = ReplayRenderer.HEIGHT;
  const canvas = el("canvas", { width: W, height: H, class: "replay-canvas" });
  const ctx = canvas.getContext("2d");
  const dur = renderer.duration;
  let t = 0, playing = false, last = 0;

  const scrub = el("input", { type: "range", min: 0, max: dur, step: 0.01, value: 0, class: "replay-scrub" });
  const time = el("span", { class: "replay-time" });
  const playBtn = el("button", { class: "primary small" }, "▶ Play");
  const draw = () => {
    renderer.draw(ctx, t);
    scrub.value = t;
    time.textContent = `${t.toFixed(1)} / ${dur.toFixed(1)} s`;
  };
  const tick = (now) => {
    if (!playing || !canvas.isConnected) { playing = false; playBtn.textContent = "▶ Play"; return; }
    t = Math.min(dur, t + (now - last) / 1000);
    last = now;
    draw();
    if (t >= dur) { playing = false; playBtn.textContent = "↺ Replay"; return; }
    state.replayRaf = requestAnimationFrame(tick);
  };
  playBtn.addEventListener("click", () => {
    if (playing) { playing = false; playBtn.textContent = "▶ Play"; return; }
    if (t >= dur) t = 0;
    playing = true; playBtn.textContent = "❚❚ Pause"; last = performance.now();
    state.replayRaf = requestAnimationFrame(tick);
  });
  scrub.addEventListener("input", () => { t = Number(scrub.value); draw(); });
  draw();

  const g = e.game || {};
  container.append(el("section", { class: "card replay-card" },
    el("div", { class: "replay-stage" }, canvas),
    el("div", { class: "replay-side" },
      el("div", { class: "section-title" }, `${g.away?.abbr ?? ""} at ${g.home?.abbr ?? ""} · ${(g.date || "").slice(0, 10)}`),
      el("div", { class: "replay-controls" }, playBtn, time),
      scrub,
      ...replayList(e, dur, (at) => { t = at; draw(); }),
      el("div", { class: "section-title", style: "margin-top: 10px;" }, "Export to video"),
      el("pre", { class: "report replay-cmd" }, `ballmonitor export-replay --game ${g.id}`),
      el("p", { class: "hint" }, "Needs pip install -e '.[video]' and ffmpeg. Writes a 1080×1920 MP4 at 30 fps."))));
}
