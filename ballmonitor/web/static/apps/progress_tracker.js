// Progress tracker (the progress_tracker page's "app" view). The visitor keeps a log of any measures
// they are improving (a lift, a pace, a race time, a chess rating, body weight, body fat %, or their
// own) in this browser, sets a goal, a goal date and a plan shape (even / faster early / faster late,
// like a race pacing strategy), and sees whether they are ahead of or behind the plan and the result
// their current rate leads to.
//
// compute() is a line-by-line copy of the progress_tracker model (models/progress_tracker/model.py
// predict; formulas share_*, planned, recency_weight, adherence, predicted, spread in config.toml).
// Every number comes from the model's config, written into the page by site.py at build time.
// tests/test_progress_tracker_app.py runs this file under node and checks it against the Python model.
//
// Storage (shared format of the progress-log apps): localStorage "bm.log.progress_tracker.v1" =
//   {model: "progress_tracker", version: 1, updated: ISO datetime,
//    settings: {selected: measure name,
//               measures: {<name>: {type: preset key, unit, direction: "higher"|"lower",
//                                   scale: "log"|"linear" (custom only),
//                                   shape: "even"|"faster_early"|"faster_late",
//                                   start_date: "YYYY-MM-DD" or "" (= first entry), start_value: number or null,
//                                   goal_value: number or null, goal_date: "YYYY-MM-DD" or ""}}},
//    entries: [{date: "YYYY-MM-DD", metric: measure name, value: number (seconds for times)}]}
// Older v1 logs of this page (with window_weeks and settings.target_date) load as they are: those
// fields are dropped and the plan shape starts as "faster early". One entry per measure per day.
// Nothing is uploaded.
"use strict";

(function () {
  const SRC = { "data-src": "ballmonitor/web/static/apps/progress_tracker.js" };
  const DAY_MS = 86400000;
  const LIMITS = { name: 40, unit: 16, value: 1e9 };
  const CSV_FIELDS = ["date", "metric", "value"];
  const SHOW_ROWS = 20;

  // ── dates ("YYYY-MM-DD" <-> whole days) ────────────────────────────────────
  const dayNum = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / DAY_MS;
  const isoDay = (n) => new Date(Math.round(n) * DAY_MS).toISOString().slice(0, 10);
  const validDate = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s)
    && +s.slice(0, 4) >= 1900 && +s.slice(0, 4) <= 2100 && isoDay(dayNum(s)) === s;
  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // ── values ─────────────────────────────────────────────────────────────────
  // a number, or a time "m:ss" / "h:mm:ss" -> seconds (model.parse_value)
  function parseValue(v) {
    if (typeof v === "number") return Number.isFinite(v) ? v : null;
    const s = String(v == null ? "" : v).trim();
    if (!s) return null;
    if (s.includes(":")) {
      const parts = s.split(":");
      if (parts.length > 3 || !parts.every((p) => /^\d+(\.\d+)?$/.test(p.trim()))) return null;
      return parts.reduce((acc, p) => acc * 60 + parseFloat(p), 0);
    }
    if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return null;
    const x = parseFloat(s);
    return Number.isFinite(x) ? x : null;
  }
  function fmtTime(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const pad = (x) => String(x).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }


  // ── the model ──────────────────────────────────────────────────────────────
  // a measure's definition -> kind, scale, display (model.measure)
  function measureOf(data, def) {
    const preset = data.presets.find((p) => p.key === def.type) || data.presets.find((p) => p.key === "custom");
    const scale = preset.key === "custom" ? (def.scale === "linear" ? "linear" : "log") : data.scales[preset.kind];
    return { type: preset.key, kind: preset.kind, scale, direction: def.direction || preset.direction,
      unit: def.unit != null ? def.unit : preset.unit, time: preset.time, fmt: preset.fmt };
  }

  // share of the planned progress due at time share t (formulas share_even / share_faster_early / share_faster_late)
  function share(data, shape, t) {
    t = Math.min(Math.max(t, 0), 1);
    const k = data.split_strength;
    return shape === "faster_early" ? 1 - Math.pow(1 - t, k) : shape === "faster_late" ? Math.pow(t, k) : t;
  }
  const recencyWeight = (data, ageWeeks) => (data.recency_half_life_weeks <= 0 ? 1 : Math.pow(0.5, ageWeeks / data.recency_half_life_weeks));

  // entries [{date, value}] of one measure; opts {def: measure settings, today}  (model.predict)
  function compute(data, entries, opts) {
    const def = opts.def || {};
    const m = measureOf(data, def);
    const log = m.scale === "log";
    const fwd = log ? Math.log : (v) => v;
    const back = log ? Math.exp : (y) => y;
    const shape = data.shapes.includes(def.shape) ? def.shape : data.default_shape;
    const list = entries.map((e, i) => ({ day: dayNum(e.date), value: e.value, i })).sort((a, b) => a.day - b.day || a.i - b.i);
    if (log && list.some((e) => !(e.value > 0))) return { error: "On a % scale every value must be above 0." };
    if (def.goal_value == null || def.goal_value === "" || !def.goal_date) return { error: "Set a goal and a goal date to make your plan.", needsGoal: true };
    const startDay = def.start_date ? dayNum(def.start_date) : list.length ? list[0].day : null;
    if (startDay == null) return { error: "Add your first entry (or a start value and date) to start the plan.", needsStart: true };
    let startValue;
    if (def.start_value != null && def.start_value !== "") startValue = +def.start_value;
    else {
      const later = list.filter((e) => e.day >= startDay);
      if (!later.length) return { error: "Give a start value (no entry on or after the start date).", needsStart: true };
      startValue = later[0].value;
    }
    const goalValue = +def.goal_value, goalDay = dayNum(def.goal_date);
    if (log && (startValue <= 0 || goalValue <= 0)) return { error: "Start and goal must be above 0." };
    const planWeeks = (goalDay - startDay) / 7;
    if (!(planWeeks > 0 && planWeeks <= data.max_plan_weeks)) return { error: `The goal date must be after the start date and within ${data.max_plan_weeks} weeks of it.` };
    if (goalValue === startValue) return { error: "The goal must differ from the start value." };
    const today = opts.today ? dayNum(opts.today) : list.length ? list[list.length - 1].day : startDay;
    const S = fwd(startValue), G = fwd(goalValue);
    const planned = (d) => S + share(data, shape, (d - startDay) / 7 / planWeeks) * (G - S);   // formula planned

    const used = list.filter((e) => startDay < e.day && e.day <= today);
    const xs = used.map((e) => planned(e.day) - S), ys = used.map((e) => fwd(e.value) - S);
    const rawW = used.map((e) => recencyWeight(data, (today - e.day) / 7));
    const n = used.length;
    const sumW = rawW.reduce((a, b) => a + b, 0);
    const w = rawW.map((wi) => wi * n / sumW);
    let sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) { sxx += w[i] * xs[i] * xs[i]; sxy += w[i] * xs[i] * ys[i]; }
    const mPrior = (share(data, shape, 0.5) * (G - S)) ** 2;
    const lam = data.prior_weight;
    const f = sxx + lam * mPrior > 0
      ? Math.min(Math.max((sxy + lam * mPrior) / (sxx + lam * mPrior), -data.max_adherence), data.max_adherence)   // formula adherence
      : 1;
    let residVar = null, fVar = null;
    if (n >= 2) {
      let rss = 0;
      for (let i = 0; i < n; i++) rss += w[i] * (ys[i] - f * xs[i]) ** 2;
      residVar = rss / (n - 1);
      if (sxx + lam * mPrior > 0) fVar = residVar / (sxx + lam * mPrior);
    }
    const past = list.filter((e) => e.day <= today);
    const latest = past.length ? past[past.length - 1] : null;
    const wrongWay = f <= 0;
    const predY = wrongWay ? (latest ? fwd(latest.value) : S) : S + f * (G - S);   // formula predicted
    let interval = null;
    if (fVar != null && !wrongWay) {
      const sd = Math.sqrt(residVar + (G - S) ** 2 * fVar);   // formula spread
      interval = [back(predY - data.z * sd), back(predY + data.z * sd)];
    }
    const sign = G > S ? 1 : -1;
    const asChange = (d) => (log ? Math.exp(d) - 1 : d);
    let track = null;
    if (latest) {
      const gap = fwd(latest.value) - planned(latest.day);
      track = { date: isoDay(latest.day), value: latest.value, planned: back(planned(latest.day)), gap, gap_change: asChange(gap), ahead: sign * gap >= 0 };
    }
    const rpDay = latest ? latest.day : startDay, rpY = latest ? fwd(latest.value) : S;
    const remWeeks = (goalDay - rpDay) / 7;
    const replan = remWeeks > 0 ? { from: isoDay(rpDay), weeks: remWeeks, per_week: asChange((G - rpY) / remWeeks), done: sign * (rpY - G) >= 0 } : null;
    const replanned = (d) => rpY + share(data, shape, (d - rpDay) / 7 / remWeeks) * (G - rpY);
    // next week's goal (model.predict "next week's goal")
    let nextGoal = null;
    if (latest) {
      const ld = latest.day, y = fwd(latest.value);
      const base = Math.max(ld, today);   // a stale entry: measure from today
      if (base >= goalDay) nextGoal = { reason: "past_goal_date" };
      else if (sign * (y - G) >= 0) nextGoal = { reason: "reached" };
      else {
        const nd = Math.min(base + 7, goalDay);
        const step = planned(nd) - planned(base);
        const gap = planned(base) - y;
        let target, reason;
        if (sign * gap <= data.on_track_tolerance * Math.abs(step)) {
          const keep = y + step;
          target = sign * keep > sign * planned(nd) ? keep : planned(nd);
          reason = sign * gap < 0 && target === keep ? "ahead" : "on_plan";
        } else {
          target = y + step + data.catch_up_share * gap;   // formula next_goal_behind
          reason = "catch_up";
          if (sign * target > sign * planned(nd)) { target = planned(nd); reason = "waypoint"; }
          const floor = y + share(data, shape, (nd - base) / (goalDay - base)) * (G - y);   // re-plan from the base date
          if (sign * target < sign * floor) { target = floor; reason = "minimum"; }
        }
        nextGoal = { reason, date: isoDay(nd), value: back(target), change: asChange(target - y), gap: asChange(sign * gap),
          step: asChange(step), latest: latest.value };
      }
    }
    const trackAt = (d) => (wrongWay ? predY : S + f * (planned(d) - S));
    const rows = [];
    if (remWeeks > 0) {
      for (let k = 1; ; k++) {
        const d = Math.min(today + 7 * k, goalDay);
        if (d <= today) break;
        rows.push({ week: k, date: isoDay(d), plan: back(planned(d)), replan: back(replanned(d)), track: back(trackAt(d)) });
        if (d >= goalDay) break;
      }
    }
    return {
      measure: m, shape, today: isoDay(today), start_date: isoDay(startDay), start_value: startValue, goal_value: goalValue,
      goal_date: isoDay(goalDay), plan_weeks: planWeeks, f, n, sxx, sxy, resid_var: residVar, f_var: fVar, wrong_way: wrongWay,
      predicted: back(predY), interval, planned_today: back(planned(today)), track, replan, weeks_table: rows, next_goal: nextGoal,
      planAt: (d) => back(planned(d)), trackAt: (d) => back(trackAt(d)),
    };
  }

  // ── log validation, import, export ─────────────────────────────────────────
  function cleanName(s) {
    const t = String(s == null ? "" : s).replace(/[\u0000-\u001f]/g, "").trim();
    return t && t.length <= LIMITS.name ? t : null;
  }
  // one raw entry -> [entry, null] or [null, reason]
  function cleanEntry(raw, fallbackMetric) {
    if (!raw || typeof raw !== "object") return [null, "not an entry"];
    const date = String(raw.date == null ? "" : raw.date).trim().slice(0, 10);
    if (!validDate(date)) return [null, `bad date "${String(raw.date).slice(0, 20)}" (use YYYY-MM-DD)`];
    const metric = cleanName(raw.metric != null && raw.metric !== "" ? raw.metric : fallbackMetric);
    if (!metric) return [null, "no measure name (or longer than 40 characters)"];
    const value = parseValue(raw.value);
    if (value == null || Math.abs(value) > LIMITS.value) return [null, `bad value "${String(raw.value).slice(0, 20)}"`];
    return [{ date, metric, value }, null];
  }
  // a measure's definition (also reads an older v1 log: window_weeks is dropped, target_date ignored)
  function cleanMeasure(data, raw) {
    if (!raw || typeof raw !== "object") return null;
    const preset = data.presets.find((p) => p.key === raw.type);
    if (!preset) return null;
    const out = { type: preset.key, unit: preset.unit, direction: preset.direction, shape: data.default_shape,
      start_date: "", start_value: null, goal_value: null, goal_date: "" };
    if (typeof raw.unit === "string" && raw.unit.length <= LIMITS.unit) out.unit = raw.unit.replace(/[\u0000-\u001f]/g, "");
    if (raw.direction === "higher" || raw.direction === "lower") out.direction = raw.direction;
    if (preset.key === "custom") out.scale = raw.scale === "linear" ? "linear" : "log";
    if (data.shapes.includes(raw.shape)) out.shape = raw.shape;
    for (const k of ["start_value", "goal_value"]) {
      const v = raw[k] == null || raw[k] === "" ? null : parseValue(raw[k]);
      if (v != null && Math.abs(v) <= LIMITS.value) out[k] = v;
    }
    for (const k of ["start_date", "goal_date"]) if (validDate(raw[k])) out[k] = raw[k];
    return out;
  }
  function cleanSettings(data, s) {
    const out = { measures: {} };
    if (!s || typeof s !== "object") return out;
    const ms = s.measures && typeof s.measures === "object" ? s.measures : {};
    for (const [name, def] of Object.entries(ms).slice(0, 50)) {
      const n = cleanName(name), d = cleanMeasure(data, def);
      if (n && d) out.measures[n] = d;
    }
    if (typeof s.selected === "string" && out.measures[s.selected]) out.selected = s.selected;
    return out;
  }

  // a measure name with no definition: a preset whose label or key it matches, else custom
  function guessMeasure(data, name) {
    const low = name.toLowerCase();
    const preset = data.presets.find((p) => p.key === low || p.label.toLowerCase() === low) || data.presets.find((p) => p.key === "custom");
    return cleanMeasure(data, { type: preset.key });
  }

  function parseCSV(text) {
    const rows = [];
    let row = [], cell = "", q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; }
        else cell += c;
      } else if (c === '"') q = true;
      else if (c === "," || c === ";" || c === "\t") { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); cell = "";
        if (row.some((x) => x.trim() !== "")) rows.push(row);
        row = [];
      } else cell += c;
    }
    row.push(cell);
    if (row.some((x) => x.trim() !== "")) rows.push(row);
    return rows;
  }

  // CSV: date, metric (or measure), value; or just date, value (for the selected measure)
  function importCSV(text, selected) {
    const rows = parseCSV(String(text).replace(/^﻿/, ""));
    if (!rows.length) return { format: "CSV", entries: [], skipped: [[0, "the file is empty"]] };
    const head = rows[0].map((x) => x.trim().toLowerCase());
    const col = (...names) => { for (const n of names) { const i = head.indexOf(n); if (i >= 0) return i; } return null; };
    const iDate = col("date", "day"), iMetric = col("metric", "measure", "name"), iValue = col("value", "result", "score");
    if (iDate == null || iValue == null)
      return { format: "CSV", entries: [], skipped: [[1, "need columns date and value (and metric, unless the file is for the measure you have open)"]] };
    if (iMetric == null && !selected) return { format: "CSV", entries: [], skipped: [[1, "no metric column: open a measure first, then import"]] };
    const entries = [], skipped = [];
    rows.slice(1).forEach((r, i) => {
      const [e, why] = cleanEntry({ date: r[iDate], metric: iMetric != null ? r[iMetric] : selected, value: r[iValue] }, selected);
      if (e) entries.push(e); else skipped.push([i + 2, why]);
    });
    return { format: "CSV", entries, skipped };
  }

  function importJSON(data, text) {
    let obj;
    try { obj = JSON.parse(text); } catch (err) { return { format: "JSON", entries: [], skipped: [[0, "not valid JSON"]] }; }
    const list = Array.isArray(obj) ? obj : obj && Array.isArray(obj.entries) ? obj.entries : null;
    if (!list) return { format: "JSON", entries: [], skipped: [[0, "no \"entries\" list"]] };
    if (obj && obj.model && obj.model !== "progress_tracker") return { format: "JSON", entries: [], skipped: [[0, `this file is a ${String(obj.model).slice(0, 40)} log`]] };
    const entries = [], skipped = [];
    list.slice(0, 100000).forEach((raw, i) => {
      const [e, why] = cleanEntry(raw, null);
      if (e) entries.push(e); else skipped.push([i + 1, why]);
    });
    const settings = obj && !Array.isArray(obj) ? cleanSettings(data, obj.settings) : null;
    return { format: "JSON", entries, skipped, settings };
  }

  // merge by date + measure: the file's value wins
  function merge(current, incoming) {
    const key = (e) => `${e.date}|${e.metric}`;
    const map = new Map(current.map((e) => [key(e), e]));
    let added = 0, updated = 0, same = 0;
    for (const e of incoming) {
      const k = key(e), old = map.get(k);
      if (!old) { added++; map.set(k, e); }
      else if (old.value !== e.value) { updated++; map.set(k, e); }
      else same++;
    }
    return { entries: sortEntries([...map.values()]), added, updated, same };
  }
  const sortEntries = (list) => list.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : a.metric < b.metric ? -1 : a.metric > b.metric ? 1 : 0));

  function toCSV(entries) {
    const esc = (v) => { const s = v == null ? "" : String(v); return /[",;\n\r\t]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    return [CSV_FIELDS.join(","), ...entries.map((e) => CSV_FIELDS.map((k) => esc(e[k])).join(","))].join("\n") + "\n";
  }

  // ── storage ────────────────────────────────────────────────────────────────
  function load(data) {
    try {
      const raw = window.localStorage.getItem(data.storage_key);
      if (!raw) return { ok: true, log: null };
      const got = importJSON(data, raw);
      return { ok: true, log: { settings: got.settings || { measures: {} }, entries: sortEntries(got.entries) } };
    } catch (err) { return { ok: false, log: null }; }
  }
  const snapshot = (state) => ({ model: "progress_tracker", version: 1, updated: new Date().toISOString(),
    settings: state.settings, entries: state.entries });
  function save(data, state) {
    try { window.localStorage.setItem(data.storage_key, JSON.stringify(snapshot(state))); return true; }
    catch (err) { return false; }
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ── formatting ─────────────────────────────────────────────────────────────
  function fmtValue(v, m) {
    if (v == null || !Number.isFinite(v)) return "–";
    if (m.time) return fmtTime(v);
    if (m.fmt === "int") return Math.round(v).toLocaleString("en-US");
    const r = Math.round(v * 10) / 10;
    const suffix = m.unit === "%" ? "%" : m.unit && m.unit !== "points" ? ` ${m.unit}` : "";
    return (Number.isInteger(r) ? r.toFixed(0) : r.toFixed(1)) + suffix;
  }
  // a change: % on log scales, units on linear ones (body fat %: points)
  function fmtChange(x, m) {
    if (m.scale === "log") return `${Math.abs(x * 100).toFixed(1)}%`;
    const d = Math.abs(x) >= 10 ? 0 : Math.abs(x) >= 1 ? 1 : 2;
    const unit = m.unit === "%" ? "points" : m.unit && m.unit !== "h:mm:ss" ? m.unit : "";
    return `${Math.abs(x).toFixed(d)}${unit ? ` ${unit}` : ""}`;
  }
  function niceDate(s) {
    return new Date(dayNum(s) * DAY_MS).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  }
  const shortDate = (s) => new Date(dayNum(s) * DAY_MS).toLocaleDateString(undefined, { year: "numeric", month: "short", timeZone: "UTC" });
  const SHAPE_WORDS = { even: "Even", faster_early: "Faster early", faster_late: "Faster late" };
  const SHAPE_HINTS = {
    even: "the same progress every week (in % for lifts, pace and times)",
    faster_early: "most of the progress in the first weeks, like going out fast in a race",
    faster_late: "slow at first, most of the progress near the goal date, like a negative split",
  };

  // ── the tool ───────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const today = localToday();
    const stored = load(data);
    const state = {
      entries: stored.log ? stored.log.entries : [],
      settings: stored.log ? stored.log.settings : { measures: {} },
      editing: null, showAll: false, message: "",
    };
    for (const e of state.entries) if (!state.settings.measures[e.metric]) state.settings.measures[e.metric] = guessMeasure(data, e.metric);
    if (!state.settings.selected || !state.settings.measures[state.settings.selected])
      state.settings.selected = Object.keys(state.settings.measures)[0] || null;
    let storageOk = stored.ok;

    const out = el("div", { class: "pt-out", "aria-live": "polite" });
    const status = el("p", { class: "note pt-status", role: "status" });
    const logBox = el("div", {});
    const importBox = el("div", {});
    const planBox = el("div", { class: "pt-settings" });
    const addMeasureBox = el("div", { class: "pt-addmeasure", hidden: "" });

    function persist() { storageOk = save(data, state); drawStatus(); }
    function drawStatus() {
      status.replaceChildren(storageOk ? (state.message || "") :
        el("b", {}, "This browser isn't letting the page save (private browsing or full storage): your log will be lost when you close the page. Export it to keep it."));
    }
    function say(msg) { state.message = msg; drawStatus(); }
    const sel = () => state.settings.selected;
    const def = () => state.settings.measures[sel()];
    const meas = () => measureOf(data, def());
    const entriesOf = (name) => state.entries.filter((e) => e.metric === name);

    // ── measure picker + "add a measure" ──
    const measureSel = el("select", { "aria-label": "Measure", onchange: (e) => {
      state.settings.selected = e.target.value; stopEdit(); persist(); draw();
    } });
    const presetSel = el("select", { "aria-label": "Kind of measure" }, data.presets.map((p) => el("option", { value: p.key }, p.label)));
    const nameIn = el("input", { type: "text", maxlength: String(LIMITS.name), "aria-label": "Name" });
    const unitSel = el("select", { "aria-label": "Unit" });
    const unitIn = el("input", { type: "text", maxlength: String(LIMITS.unit), placeholder: "reps", size: "6", "aria-label": "Unit" });
    const scaleSel = el("select", { "aria-label": "Progress counted in" },
      el("option", { value: "log" }, "% (lifts, times, counts)"), el("option", { value: "linear" }, "units (ratings, weights)"));
    const scaleLbl = el("label", {}, el("span", { class: "rc-lbl" }, "Progress counted in"), scaleSel);
    const addMsg = el("p", { class: "note" });
    function syncPresetForm() {
      const p = data.presets.find((x) => x.key === presetSel.value);
      nameIn.placeholder = p.key === "custom" ? "e.g. Push-ups in one set" : p.label;
      unitSel.replaceChildren(...p.units.map((u) => el("option", { value: u }, u)));
      unitSel.hidden = !p.units.length; unitIn.hidden = !!p.units.length;
      scaleLbl.hidden = p.key !== "custom";
    }
    presetSel.addEventListener("change", syncPresetForm);
    addMeasureBox.append(el("form", { class: "pt-form", onsubmit: (ev) => {
      ev.preventDefault();
      const p = data.presets.find((x) => x.key === presetSel.value);
      const name = cleanName(nameIn.value || p.label);
      if (!name) { addMsg.textContent = "Give it a name (up to 40 characters)."; return; }
      if (state.settings.measures[name]) { addMsg.textContent = `You already have "${name}". Pick another name.`; return; }
      state.settings.measures[name] = cleanMeasure(data, { type: p.key, unit: p.units.length ? unitSel.value : unitIn.value, scale: scaleSel.value });
      state.settings.selected = name;
      addMsg.textContent = ""; nameIn.value = ""; addMeasureBox.hidden = true;
      persist(); say(`Added "${name}". Set your goal and plan, then log where you are today.`); draw();
    } },
      el("label", {}, el("span", { class: "rc-lbl" }, "What"), presetSel),
      el("label", {}, el("span", { class: "rc-lbl" }, "Name"), nameIn),
      el("label", {}, el("span", { class: "rc-lbl" }, "Unit"), unitSel, unitIn), scaleLbl,
      el("button", { type: "submit", class: "ss-btn" }, "Add measure"),
      el("button", { type: "button", class: "ss-btn", onclick: () => { addMeasureBox.hidden = true; } }, "Cancel")), addMsg);
    syncPresetForm();

    // ── the plan: start, goal, goal date, shape ──
    function valueInput(d, key, m, label, placeholder) {
      return el("input", { type: "text", inputmode: m.time ? "text" : "decimal", class: "pt-num", placeholder,
        value: d[key] == null ? "" : (m.time ? fmtTime(d[key]) : String(d[key])), "aria-label": label, onchange: (e) => {
          const raw = e.target.value.trim();
          if (!raw) { d[key] = null; persist(); drawResult(); return; }
          const v = m.time && !raw.includes(":") ? null : parseValue(raw);
          if (v == null) { say(m.time ? `Write the ${label.toLowerCase()} as m:ss (or h:mm:ss).` : `The ${label.toLowerCase()} isn't a number.`); return; }
          d[key] = v; persist(); say(""); drawResult();
        } });
    }
    function drawPlan() {
      const d = def();
      if (!d) { planBox.replaceChildren(); return; }
      const m = meas();
      const first = entriesOf(sel())[0];
      const dateIn = (key, label) => el("input", { type: "date", value: d[key] || "", "aria-label": label,
        onchange: (e) => { d[key] = validDate(e.target.value) ? e.target.value : ""; persist(); drawResult(); } });
      const shapeSel = el("select", { "aria-label": "Plan", onchange: (e) => { d.shape = e.target.value; persist(); drawPlan(); drawResult(); } },
        data.shapes.map((s) => el("option", { value: s, ...(s === d.shape ? { selected: "" } : {}) }, SHAPE_WORDS[s])));
      const unit = m.unit && !m.time ? ` (${m.unit})` : "";
      const ex = m.time ? (m.type === "race_time" ? "1:45:00" : "4:45") : "";
      const fs = data.front_share;
      planBox.replaceChildren(
        el("div", { class: "pick-row" },
          el("label", { class: "pick" }, `Goal${unit}: `, valueInput(d, "goal_value", m, "Goal", ex)),
          el("label", { class: "pick" }, "by ", dateIn("goal_date", "Goal date")),
          el("label", { class: "pick" }, "Plan: ", shapeSel)),
        el("div", { class: "pick-row" },
          el("label", { class: "pick" }, `Start${unit}: `, valueInput(d, "start_value", m, "Start value",
            first ? (m.time ? fmtTime(first.value) : String(first.value)) : ex)),
          el("label", { class: "pick" }, "on ", dateIn("start_date", "Start date")),
          el("button", { type: "button", class: "ss-btn rc-x", onclick: () => {
            const name = sel(), k = entriesOf(name).length;
            if (!window.confirm(`Remove "${name}"${k ? ` and its ${k} entr${k === 1 ? "y" : "ies"}` : ""} from this browser?`)) return;
            state.entries = state.entries.filter((e) => e.metric !== name);
            delete state.settings.measures[name];
            state.settings.selected = Object.keys(state.settings.measures)[0] || null;
            persist(); say(`Removed "${name}".`); draw();
          } }, "Remove this measure")),
        el("p", { class: "small", ...SRC }, `${SHAPE_WORDS[d.shape]}: ${SHAPE_HINTS[d.shape]}. Start blank = your first entry. `
          + `In real logs, newcomers made about ${Math.round(fs.strength * 100)}% of a year's strength gain and `
          + `${Math.round(fs.chess * 100)}% of a year's chess-rating gain in the first six months, so "faster early" is the realistic plan.`));
    }

    // ── result ──
    function drawResult() {
      const name = sel();
      if (!name) {
        out.replaceChildren(el("p", { class: "note", ...SRC }, "Start by adding something you track: a lift, your running pace, a race time, "
          + "your chess rating, your body weight or anything you count."));
        return;
      }
      const m = meas(), entries = entriesOf(name);
      const res = compute(data, entries, { def: def(), today });
      if (res.error) { out.replaceChildren(el("p", { class: "note" }, el("b", {}, res.error))); return; }
      const v = (x) => fmtValue(x, m);
      const goalBy = `${v(res.goal_value)} by ${niceDate(res.goal_date)}`;
      const beat = res.f >= 1;
      let big, sub;
      if (res.n === 0) {
        big = `Your plan: ${goalBy}`;
        sub = "Log your progress to see where you're heading.";
      } else if (res.wrong_way) {
        big = `For now: ${v(res.predicted)}`;
        sub = `So far your numbers have moved away from your goal of ${goalBy}. That happens: a few good weeks turn it around, and the plan below shows what each week needs.`;
      } else {
        big = `${beat ? "On course to beat your goal: " : "Heading for "}${v(res.predicted)} by ${niceDate(res.goal_date)}`;
        sub = `Goal: ${v(res.goal_value)}. You've made ${Math.round(res.f * 100)}% of the progress your plan asked for so far`
          + (res.n < 3 ? " (with only a few entries, this is pulled toward 100%)." : ".");
      }
      const parts = [el("div", { class: "pt-headline" }, el("p", { class: "pt-big" }, big), el("p", {}, sub), drawNext(res, m))];
      const lines = [];
      if (res.track) {
        const t = res.track, diff = fmtChange(res.track.gap_change, m);
        lines.push(`Your plan for ${niceDate(t.date)}: ${v(t.planned)}. You logged ${v(t.value)}: `
          + (Math.abs(t.gap) < 1e-12 ? "right on plan." : `${t.ahead ? "ahead" : "behind"} by ${diff}.`));
      }
      if (!res.track || res.track.date !== res.today) lines.push(`Planned for today: ${v(res.planned_today)}.`);
      if (res.replan && !res.replan.done)
        lines.push(`To still reach your goal from here: ${fmtChange(res.replan.per_week, m)} a week on average (${SHAPE_WORDS[res.shape].toLowerCase()} plan from your latest entry; the week-by-week table has the targets).`);
      else if (res.replan && res.replan.done) lines.push("Your latest entry is already at or past your goal.");
      if (res.interval) lines.push(`Range if your entries keep scattering as they have (8 in 10, untested): ${v(Math.min(...res.interval))} to ${v(Math.max(...res.interval))}.`);
      parts.push(...lines.map((t) => el("p", {}, t)));
      const rows = res.weeks_table;
      if (rows.length) parts.push(el("details", { class: "pt-weeks" },
        el("summary", {}, `Week-by-week targets to ${niceDate(res.goal_date)} (${rows.length} week${rows.length === 1 ? "" : "s"})`),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ["Week", "Date", "Your plan", "Re-plan from here", "At your current rate"].map((t, i) => el("th", { class: i >= 2 ? "num" : null, scope: "col" }, t)))),
          el("tbody", {}, rows.map((r) => el("tr", {}, el("td", {}, String(r.week)), el("td", {}, r.date),
            el("td", { class: "num" }, v(r.plan)), el("td", { class: "num" }, el("b", {}, v(r.replan))), el("td", { class: "num" }, v(r.track)))))))));
      parts.push(drawChart(res, m, entries));
      parts.push(el("p", { class: "note", ...SRC }, "The prediction scales your plan by the share of it you've kept so far. It's a motivating guide, "
        + "not a tested forecast: we'll use logs like yours (if you choose to share them later) to test and improve it."));
      out.replaceChildren(...parts);
    }

    // next week's goal, with a one-line why
    function drawNext(res, m) {
      const g = res.next_goal;
      if (!g) return null;
      if (g.reason === "reached") return el("p", { class: "pt-next", ...SRC }, "You've reached your goal. Set a new one to keep going!");
      if (g.reason === "past_goal_date") return el("p", { class: "pt-next", ...SRC }, "Your goal date has passed: set a new goal date (or a new goal) for next week's target.");
      const ch = g.change, chg = Math.abs(ch) < 1e-12 ? "" : ` (${ch > 0 ? "+" : "−"}${fmtChange(ch, m)})`;
      const why = {
        on_plan: "You're on plan: this is your plan's next step.",
        ahead: "You're ahead of your plan: keep up your own pace.",
        catch_up: `You're ${fmtChange(g.gap, m)} behind your plan: this is a normal week's step plus ${data.catch_up_share === 0.25 ? "a quarter" : `${Math.round(data.catch_up_share * 100)}%`} of the gap.`,
        waypoint: `You're ${fmtChange(g.gap, m)} behind your plan: this gets you back to it.`,
        minimum: `You're ${fmtChange(g.gap, m)} behind your plan: this is the minimum to still reach your goal on time.`,
      }[g.reason];
      return el("div", { class: "pt-next" },
        el("p", {}, el("b", {}, `Next week's goal: ${fmtValue(g.value, m)} by ${niceDate(g.date)}${chg}`)),
        el("p", { class: "small", ...SRC }, why));
    }

    function drawChart(res, m, entries) {
      const s0 = dayNum(res.start_date), g0 = dayNum(res.goal_date), t0 = dayNum(res.today);
      const x = (d) => (d - t0) / 7;
      const lo = Math.min(s0, t0), steps = 40;
      const plan = [], track = [];
      for (let i = 0; i <= steps; i++) {
        const d = s0 + (g0 - s0) * i / steps;
        plan.push([x(d), res.planAt(d)]);
        if (!res.wrong_way) track.push([x(d), res.trackAt(d)]);
      }
      const pts = entries.map((e) => ({ x: x(dayNum(e.date)), y: e.value, date: e.date })).filter((p) => dayNum(p.date) >= lo - 7 * 26);
      const series = [{ name: "Your plan", points: plan }];
      if (!res.wrong_way && res.n) series.push({ name: "At your current rate", points: track });
      const ticks = [[x(s0), shortDate(res.start_date)], [x(g0), shortDate(res.goal_date)]];
      if (t0 > s0 + 14 && t0 < g0 - 14) ticks.splice(1, 0, [0, "Today"]);
      const ys = [...plan.map((p) => p[1]), ...track.map((p) => p[1]), ...pts.map((p) => p.y)];
      const pad = (Math.max(...ys) - Math.min(...ys)) * 0.08 || 1;
      return el("div", { class: "pt-chart" }, h.renderLine({ kind: "line", title: `${state.settings.selected}: plan and progress`, series,
        markers: [...pts.map((p) => ({ x: p.x, y: p.y, label: `${p.date}: ${fmtValue(p.y, m)}` })),
          { x: x(g0), y: res.goal_value, label: `Goal: ${fmtValue(res.goal_value, m)} on ${res.goal_date}` }],
        x_fmt: "number", y_fmt: m.time ? "time" : "number", x_ticks: ticks,
        y_min: Math.min(...ys) - pad, y_max: Math.max(...ys) + pad, x_label: "", y_label: "" }));
    }

    // ── add / edit entries ──
    const f = {
      date: el("input", { type: "date", value: today, max: today, "aria-label": "Date" }),
      value: el("input", { type: "text", inputmode: "decimal", size: "9", "aria-label": "Value" }),
    };
    const formMsg = el("p", { class: "note" });
    const addBtn = el("button", { type: "submit", class: "ss-btn" }, "Add entry");
    const cancelBtn = el("button", { type: "button", class: "ss-btn", hidden: "", onclick: () => stopEdit() }, "Cancel");
    const valueLbl = el("span", { class: "rc-lbl" }, "Value");
    const entryForm = el("form", { class: "pt-form pt-entry", onsubmit: (ev) => {
      ev.preventDefault();
      const name = sel();
      if (!name) { formMsg.textContent = "Add a measure first."; return; }
      const m = meas();
      const raw = f.value.value.trim();
      if (m.time && raw && !raw.includes(":")) { formMsg.textContent = `Not added: write it as ${m.type === "race_time" ? "h:mm:ss or mm:ss" : "m:ss"}.`; return; }
      const [e, why] = cleanEntry({ date: f.date.value, metric: name, value: raw }, name);
      if (!e) { formMsg.textContent = `Not added: ${why}.`; return; }
      if (m.scale === "log" && !(e.value > 0)) { formMsg.textContent = "Not added: the value must be above 0."; return; }
      formMsg.textContent = "";
      if (state.editing) state.entries = state.entries.filter((x) => !(x.date === state.editing.date && x.metric === state.editing.metric));
      const replaced = state.entries.some((x) => x.date === e.date && x.metric === e.metric);
      state.entries = merge(state.entries, [e]).entries;
      stopEdit();
      persist(); say(`${replaced ? "Replaced" : "Saved"}: ${name} ${fmtValue(e.value, m)} on ${e.date}.`); draw();
      f.value.focus();
    } },
      el("label", {}, el("span", { class: "rc-lbl" }, "Date"), f.date),
      el("label", {}, valueLbl, f.value), addBtn, cancelBtn);
    function startEdit(e) {
      state.editing = { date: e.date, metric: e.metric };
      f.date.value = e.date; f.value.value = meas().time ? fmtTime(e.value) : String(e.value);
      addBtn.textContent = "Save changes"; cancelBtn.hidden = false; f.value.focus();
    }
    function stopEdit() { state.editing = null; addBtn.textContent = "Add entry"; cancelBtn.hidden = true; f.value.value = ""; }

    // ── import / export / clear ──
    const fileIn = el("input", { type: "file", accept: ".csv,.json,.txt,text/csv,application/json", "aria-label": "Import a file",
      onchange: (ev) => {
        const file = ev.target.files && ev.target.files[0];
        ev.target.value = "";
        if (!file) return;
        if (file.size > 20e6) { showImport({ error: "That file is over 20 MB; is it the right one?" }); return; }
        const reader = new FileReader();
        reader.onload = () => {
          const text = String(reader.result);
          showImport(/^\s*[[{]/.test(text) ? importJSON(data, text) : importCSV(text, sel()));
        };
        reader.onerror = () => showImport({ error: "Couldn't read that file." });
        reader.readAsText(file);
      } });
    function showImport(got) {
      if (!got || got.error || !got.entries.length) {
        const why = got && got.error ? got.error
          : got && got.skipped.length ? `No entries found. ${got.skipped.slice(0, 3).map(([r, w]) => (r ? `Row ${r}: ${w}` : w)).join("; ")}.`
          : "No entries found in that file.";
        importBox.replaceChildren(el("p", { class: "note" }, el("b", {}, why)));
        return;
      }
      const skipped = got.skipped.length
        ? ` ${got.skipped.length} row${got.skipped.length > 1 ? "s" : ""} skipped (e.g. ${got.skipped.slice(0, 3).map(([r, w]) => `row ${r}: ${w}`).join("; ")}).` : "";
      const names = [...new Set(got.entries.map((e) => e.metric))];
      const done = (entries, msg) => {
        if (got.settings) for (const [n, d] of Object.entries(got.settings.measures)) state.settings.measures[n] = d;
        state.entries = entries;
        for (const e of entries) if (!state.settings.measures[e.metric]) state.settings.measures[e.metric] = guessMeasure(data, e.metric);
        if (!state.settings.selected || !state.settings.measures[state.settings.selected]) state.settings.selected = names[0];
        importBox.replaceChildren();
        persist(); say(msg); draw();
      };
      importBox.replaceChildren(
        el("p", {}, `Found ${got.entries.length} entr${got.entries.length > 1 ? "ies" : "y"} for ${names.slice(0, 5).join(", ")}${names.length > 5 ? "…" : ""} (${got.format} file).${skipped}`),
        el("div", { class: "pt-actions" },
          el("button", { type: "button", class: "ss-btn", onclick: () => {
            const r = merge(state.entries, got.entries);
            done(r.entries, `Added ${r.added}, updated ${r.updated}${r.same ? `, ${r.same} already in your log` : ""}.`);
          } }, "Add to my log"),
          state.entries.length ? el("button", { type: "button", class: "ss-btn", onclick: () => {
            if (window.confirm(`Replace all ${state.entries.length} entries in your log with the ${got.entries.length} from this file?`)) {
              state.settings.measures = {};
              done(merge([], got.entries).entries, "Your log was replaced by the file.");
            }
          } }, "Replace my log") : null,
          el("button", { type: "button", class: "ss-btn", onclick: () => importBox.replaceChildren() }, "Cancel")));
    }
    const tools = el("div", { class: "pt-actions" },
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-progress_tracker-log-${today}.json`,
        JSON.stringify(snapshot(state), null, 1), "application/json") }, "Export (JSON)"),
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-progress_tracker-log-${today}.csv`,
        toCSV(state.entries), "text/csv") }, "Export (CSV)"),
      el("label", { class: "ss-btn pt-file" }, "Import a file…", fileIn),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!state.entries.length && !Object.keys(state.settings.measures).length) return;
        if (window.confirm(`Delete your whole log (${state.entries.length} entries, every measure and plan) from this browser? Export first if you want to keep it.`)) {
          state.entries = []; state.settings = { measures: {}, selected: null };
          stopEdit(); persist(); say("Your log was cleared."); draw();
        }
      } }, "Clear my log"));

    function drawLog() {
      const name = sel();
      if (!name) { logBox.replaceChildren(); return; }
      const m = meas();
      valueLbl.textContent = m.time ? `Value (${m.type === "race_time" ? "h:mm:ss" : `m:ss ${m.unit}`})` : `Value${m.unit ? ` (${m.unit})` : ""}`;
      f.value.placeholder = m.time ? (m.type === "race_time" ? "1:52:30" : "5:10") : m.kind === "chess" ? "1500" : "";
      const shown = entriesOf(name).reverse();
      if (!shown.length) { logBox.replaceChildren(el("p", { class: "note" }, `No entries for ${name} yet: log where you are today.`)); return; }
      const res = compute(data, entriesOf(name), { def: def(), today });
      const rows = state.showAll ? shown : shown.slice(0, SHOW_ROWS);
      const vsPlan = (e) => {
        if (res.error || dayNum(e.date) < dayNum(res.start_date)) return "";
        const gap = (m.scale === "log" ? Math.log(e.value) : e.value) - (m.scale === "log" ? Math.log(res.planAt(dayNum(e.date))) : res.planAt(dayNum(e.date)));
        const sign = res.goal_value > res.start_value ? 1 : -1;
        if (Math.abs(gap) < 1e-12) return "on plan";
        return `${sign * gap > 0 ? "ahead" : "behind"} ${fmtChange(m.scale === "log" ? Math.exp(gap) - 1 : gap, m)}`;
      };
      logBox.replaceChildren(...[
        el("p", { class: "small" }, `${shown.length} entr${shown.length > 1 ? "ies" : "y"} for ${name}, newest first.`),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ["Date", "Value", "Vs your plan", ""].map((t, i) => el("th", { class: i === 1 || i === 2 ? "num" : null, scope: "col" }, t)))),
          el("tbody", {}, rows.map((e) => el("tr", {}, el("td", {}, e.date), el("td", { class: "num" }, fmtValue(e.value, m)),
            el("td", { class: "num" }, vsPlan(e)),
            el("td", { class: "pt-rowbtns" },
              el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Edit ${e.date}`, onclick: () => startEdit(e) }, "Edit"),
              el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Delete ${e.date}`, onclick: () => {
                state.entries = state.entries.filter((x) => x !== e); stopEdit(); persist(); say("Entry deleted."); draw();
              } }, "Delete"))))))),
        shown.length > SHOW_ROWS ? el("button", { type: "button", class: "ss-btn", onclick: () => { state.showAll = !state.showAll; drawLog(); } },
          state.showAll ? "Show fewer" : `Show all ${shown.length}`) : null].filter(Boolean));
    }

    function drawPicker() {
      const names = Object.keys(state.settings.measures);
      measureSel.replaceChildren(...names.map((n) => el("option", { value: n, ...(n === sel() ? { selected: "" } : {}) }, n)));
      measureSel.hidden = !names.length;
      if (!names.length) addMeasureBox.hidden = false;
    }
    function draw() { drawPicker(); drawPlan(); drawResult(); drawLog(); drawStatus(); }

    host.replaceChildren(
      out,
      el("div", { class: "rc-form" },
        el("div", { class: "pick-row" },
          el("label", { class: "pick" }, "Measure: ", measureSel),
          el("button", { type: "button", class: "ss-btn", onclick: () => { addMeasureBox.hidden = !addMeasureBox.hidden; } }, "+ Add a measure")),
        addMeasureBox, el("h3", { class: "pt-h" }, "Your goal and plan"), planBox),
      el("h3", { class: "pt-h" }, "Add an entry"),
      entryForm, formMsg,
      el("h3", { class: "pt-h" }, "Your log"),
      status, tools, importBox, logBox);
    draw();
  }

  const api = { compute, share, measureOf, parseValue, cleanEntry, cleanMeasure, cleanSettings, parseCSV, importCSV, importJSON, toCSV, merge, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests (node)
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).progress_tracker = api;
})();
