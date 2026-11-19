// Strength progress log + calculator (the strength_progress page's "app" view). The visitor keeps a
// log of sets in this browser (localStorage only; nothing is uploaded), picks a lift and a date,
// and sees the most likely weight then with 50/80/95% ranges.
//
// forecast() is a line-by-line copy of the strength_progress model's default method
// (models/strength_progress: progress.parse_log, features, band_inputs, log_quantiles,
// quantile_values; formulas rep_index, duration_index, pace, expected_gain, band_log_quantile,
// median_value, band_value in config.toml). Every number comes from the model's config, written
// into the page by site.py at build time. tests/test_strength_progress_app.py runs this file under
// node and checks it against the Python model.
//
// Stored log (localStorage key data.storage_key = "bm.log.strength_progress.v1", and the JSON export):
//   {"model": "strength_progress", "version": 1, "updated": ISO datetime,
//    "settings": {"target_date", "exercise", "training_since", "unit"},
//    "entries": [{"date": "YYYY-MM-DD", "exercise": text, "weight": number > 0, "unit": "kg"|"lb",
//                 "reps": whole number, or "seconds": number (exactly one of the two)}]}
"use strict";

(function () {
  const MEDIAN = 3;               // index of the 50% quantile in data.levels
  const DAY_MS = 86400000;
  const LIMITS = { weight: 2000, reps: 100, seconds: 3600, name: 80 };   // input validation
  const CSV_FIELDS = ["date", "exercise", "weight", "unit", "reps", "seconds"];
  const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  const SHOW_ROWS = 30;

  // ── dates ("YYYY-MM-DD" <-> whole days) ────────────────────────────────────
  const dayNum = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / DAY_MS;
  const isoDay = (n) => new Date(n * DAY_MS).toISOString().slice(0, 10);
  const validDate = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s)
    && +s.slice(0, 4) >= 1900 && +s.slice(0, 4) <= 2100 && isoDay(dayNum(s)) === s;
  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  // ── the model ──────────────────────────────────────────────────────────────
  const toUnit = (data, w, from, to) => (from === to ? w : from === "lb" ? w * data.kg_per_lb : w / data.kg_per_lb);

  // entries -> {exercise: [{day, index, weight, reps, seconds}]} (best set per day; progress.parse_log)
  function sessionsByExercise(data, entries, unit) {
    const byEx = new Map();
    for (const e of entries) {
      const w = toUnit(data, e.weight, e.unit || unit, unit);
      const index = e.reps != null ? w * (1 + e.reps / data.rep_divisor) : w;   // formulas rep_index / duration_index
      const day = dayNum(e.date);
      if (!byEx.has(e.exercise)) byEx.set(e.exercise, new Map());
      const days = byEx.get(e.exercise);
      if (!days.has(day) || index > days.get(day).index)
        days.set(day, { day, index, weight: w, reps: e.reps != null ? e.reps : null, seconds: e.reps != null ? null : e.seconds });
    }
    const out = new Map();
    for (const [name, days] of byEx) out.set(name, [...days.values()].sort((a, b) => a.day - b.day));
    return out;
  }

  // one exercise: progress.features + band_inputs + log_quantiles + quantile_values
  function forecast(data, sessions, today, target, since) {
    const past = sessions.filter((s) => s.day <= today);
    if (!past.length) return null;
    const last = past[past.length - 1];
    const start = since != null && since < past[0].day ? since : past[0].day;
    const weeks = (today - start) / 7;
    const win = data.window_weeks;
    const inWin = past.filter((s) => today - s.day < win * 7).length;
    const freq = inWin / Math.min(win, Math.max(weeks, 1));
    const days = today - last.day;
    const h = (target - today) / 7;
    const p = data.pace;
    const pace = Math.pow(Math.min(Math.max(freq / data.ref_per_week, p.min), p.max), p.exponent);   // formula pace
    const tau = data.tau_weeks;
    const gain = data.gain_max * (Math.exp(-weeks / tau) - Math.exp(-(weeks + h * pace) / tau));   // formula expected_gain
    const x = [
      1,
      Math.sqrt(Math.min(Math.max(h, 0), data.max_horizon_weeks) / 52),
      Math.exp(-weeks / tau),
      Math.min(Math.max(1 - freq / data.ref_per_week, 0), 1),
      Math.min(days, data.gap_cap_days) / data.gap_cap_days,
    ];
    const q = data.coef.map((c) => c.reduce((a, ci, i) => a + ci * x[i], 0)).sort((a, b) => a - b);   // band_log_quantile
    const median = last.index * Math.exp(gain + q[MEDIAN]);                                           // median_value
    const values = q.map((qi) => median * Math.exp(data.band_scale * (qi - q[MEDIAN])));             // band_value
    values[MEDIAN] = median;
    for (let i = 1; i < values.length; i++) values[i] = Math.max(values[i], values[i - 1]);
    const factor = last.reps != null ? 1 + last.reps / data.rep_divisor : 1;
    return {
      current: last.index, currentWeight: last.index / factor, weeks, freq, days, gain, q, values,
      weights: values.map((v) => v / factor), last, sessions: past.length, start,
      usual: last.reps != null ? `${last.reps} reps` : `${fmtNum(last.seconds)} s`,
    };
  }

  // The whole prediction, like model.predict: primary lift first, then every other lift in the log.
  function compute(data, entries, opts) {
    if (!entries.length) return { error: "Add a set to your log first." };
    const unit = opts.unit || "kg";
    const today = dayNum(opts.today);
    const target = dayNum(opts.target_date);
    const h = (target - today) / 7;
    if (!(h > 0)) return { error: "Pick a date after today." };
    if (h > data.max_horizon_weeks) return { error: `Pick a date within ${Math.floor(data.max_horizon_weeks)} weeks: the forecast was only checked that far ahead.` };
    const since = opts.training_since && validDate(opts.training_since) ? dayNum(opts.training_since) : null;
    const byEx = sessionsByExercise(data, entries, unit);
    const names = [...byEx.keys()];
    let name = opts.exercise && byEx.has(opts.exercise) ? opts.exercise : null;
    if (!name) name = names.reduce((best, n) => (byEx.get(n).length > byEx.get(best).length ? n : best), names[0]);
    const order = [name, ...names.filter((n) => n !== name)];
    const rows = [];
    for (const n of order) {
      const f = forecast(data, byEx.get(n), today, target, since);
      if (f) rows.push({ exercise: n, ...f });
    }
    if (!rows.length || rows[0].exercise !== name) return { error: `No ${name} sets on or before today.`, exercise: name };
    return { exercise: name, unit, h, primary: rows[0], others: rows.slice(1) };
  }

  // ── entries: validation, CSV, imports ──────────────────────────────────────
  function num(v) {
    if (typeof v === "number") return v;
    let s = String(v == null ? "" : v).trim();
    if (!s) return NaN;
    if (/^-?\d+,\d+$/.test(s)) s = s.replace(",", ".");   // decimal comma (European app exports)
    return /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : NaN;
  }

  // -> [entry, null] or [null, "reason"]
  function cleanEntry(raw, defaultUnit) {
    if (!raw || typeof raw !== "object") return [null, "not a row"];
    const date = String(raw.date || "").trim().slice(0, 10);
    if (!validDate(date)) return [null, `bad date "${String(raw.date || "").slice(0, 20)}"`];
    const exercise = String(raw.exercise == null ? "" : raw.exercise).replace(/\s+/g, " ").trim();
    if (!exercise) return [null, "no exercise name"];
    if (exercise.length > LIMITS.name) return [null, "exercise name too long"];
    const weight = num(raw.weight);
    if (!(weight > 0 && weight <= LIMITS.weight)) return [null, "no weight (or not a number)"];
    const unit = String(raw.unit || defaultUnit || "kg").trim().toLowerCase().replace(/^lbs$/, "lb").replace(/^kgs$/, "kg");
    if (unit !== "kg" && unit !== "lb") return [null, `unknown unit "${unit.slice(0, 10)}"`];
    const reps = raw.reps === "" || raw.reps == null ? NaN : num(raw.reps);
    const secs = raw.seconds === "" || raw.seconds == null ? NaN : num(raw.seconds);
    const e = { date, exercise, weight, unit };
    if (reps > 0) {
      if (!(Number.isInteger(reps) && reps <= LIMITS.reps)) return [null, "reps must be a whole number up to 100"];
      e.reps = reps;
    } else if (secs > 0) {
      if (!(secs <= LIMITS.seconds)) return [null, "seconds must be up to 3600"];
      e.seconds = secs;
    } else return [null, "no reps or seconds"];
    return [e, null];
  }

  const entryKey = (e) => [e.date, e.exercise.toLowerCase(), e.weight, e.unit, e.reps ?? "", e.seconds ?? ""].join("|");
  const sortEntries = (list) => list.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  function merge(existing, incoming) {
    const seen = new Set(existing.map(entryKey));
    const add = incoming.filter((e) => !seen.has(entryKey(e)) && seen.add(entryKey(e)));
    return { entries: sortEntries([...existing, ...add]), added: add.length, duplicates: incoming.length - add.length };
  }

  // RFC 4180-ish CSV (quotes, doubled quotes, newlines in quotes); delimiter , or ; or tab from the header
  function parseCSV(text) {
    text = String(text).replace(/^﻿/, "");
    const head = text.split(/\r?\n/, 1)[0];
    const delim = [",", ";", "\t"].map((d) => [d, head.split(d).length]).sort((a, b) => b[1] - a[1])[0][0];
    const rows = [];
    let row = [], field = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (c === '"') quoted = false;
        else field += c;
      } else if (c === '"') quoted = true;
      else if (c === delim) { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); rows.push(row); row = []; field = "";
      } else field += c;
    }
    if (field || row.length) { row.push(field); rows.push(row); }
    return rows.filter((r) => r.some((c) => c.trim() !== ""));
  }

  // "26 Jan 2025, 10:31" / "2025-01-26 10:31:00" / "2025-01-26T10:31" -> "2025-01-26"
  function parseAnyDate(s) {
    s = String(s || "").trim();
    let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
    m = s.match(/^(\d{1,2})\s+([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{4})/);
    if (m && MONTHS[m[2].toLowerCase()]) return `${m[3]}-${String(MONTHS[m[2].toLowerCase()]).padStart(2, "0")}-${m[1].padStart(2, "0")}`;
    m = s.match(/^([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(\d{4})/);
    if (m && MONTHS[m[1].toLowerCase()]) return `${m[3]}-${String(MONTHS[m[1].toLowerCase()]).padStart(2, "0")}-${m[2].padStart(2, "0")}`;
    return s;
  }

  // CSV text -> {format, entries, skipped: [[row number, reason]]}
  function importCSV(text, fileUnit) {
    const rows = parseCSV(text);
    if (rows.length < 2) return { format: "csv", entries: [], skipped: [[1, "no rows under the header"]] };
    const header = rows[0].map((h) => h.trim().toLowerCase());
    const col = (...names) => names.map((n) => header.indexOf(n)).find((i) => i >= 0);
    let format, toRaw;
    if (col("exercise_title") != null && col("start_time") != null) {          // Hevy
      format = "Hevy";
      const kg = col("weight_kg"), lb = col("weight_lbs", "weight_lb");
      const iDate = col("start_time"), iEx = col("exercise_title"), iReps = col("reps"), iSec = col("duration_seconds");
      toRaw = (r) => ({ date: parseAnyDate(r[iDate]), exercise: r[iEx],
        weight: kg != null ? r[kg] : lb != null ? r[lb] : "", unit: kg != null ? "kg" : "lb",
        reps: iReps != null ? r[iReps] : "", seconds: iSec != null ? r[iSec] : "" });
    } else if (col("exercise name") != null && col("date") != null) {           // Strong
      format = "Strong";
      const iDate = col("date"), iEx = col("exercise name"), iW = col("weight"), iReps = col("reps"),
        iSec = col("seconds"), iUnit = col("weight unit");
      toRaw = (r) => ({ date: parseAnyDate(r[iDate]), exercise: r[iEx], weight: r[iW],
        unit: iUnit != null && r[iUnit] ? r[iUnit] : fileUnit,
        reps: iReps != null ? r[iReps] : "", seconds: iSec != null ? r[iSec] : "" });
    } else if (col("date") != null && col("exercise") != null && col("weight") != null) {   // generic / ours
      format = "spreadsheet";
      const iDate = col("date"), iEx = col("exercise"), iW = col("weight"), iUnit = col("unit"),
        iReps = col("reps"), iSec = col("seconds", "duration");
      toRaw = (r) => ({ date: parseAnyDate(r[iDate]), exercise: r[iEx], weight: r[iW],
        unit: iUnit != null && r[iUnit] ? r[iUnit] : fileUnit,
        reps: iReps != null ? r[iReps] : "", seconds: iSec != null ? r[iSec] : "" });
    } else {
      return { format: "csv", entries: [], skipped: [[1, "unknown columns: need date, exercise, weight and reps or seconds (or a Hevy or Strong export)"]] };
    }
    const entries = [], skipped = [];
    rows.slice(1).forEach((r, i) => {
      const [e, why] = cleanEntry(toRaw(r), fileUnit);
      if (e) entries.push(e); else skipped.push([i + 2, why]);
    });
    return { format, entries, skipped };
  }

  // JSON export of this tool -> same shape as importCSV
  function importJSON(text, fileUnit) {
    let obj;
    try { obj = JSON.parse(text); } catch (err) { return { format: "JSON", entries: [], skipped: [[0, "not valid JSON"]] }; }
    const list = Array.isArray(obj) ? obj : obj && Array.isArray(obj.entries) ? obj.entries : null;
    if (!list) return { format: "JSON", entries: [], skipped: [[0, "no \"entries\" list"]] };
    if (obj && obj.model && obj.model !== "strength_progress") return { format: "JSON", entries: [], skipped: [[0, `this file is a ${String(obj.model).slice(0, 40)} log`]] };
    const entries = [], skipped = [];
    list.forEach((raw, i) => {
      const [e, why] = cleanEntry(raw, fileUnit);
      if (e) entries.push(e); else skipped.push([i + 1, why]);
    });
    const settings = obj && !Array.isArray(obj) && obj.settings && typeof obj.settings === "object" ? cleanSettings(obj.settings) : null;
    return { format: "JSON", entries, skipped, settings };
  }

  function cleanSettings(s) {
    const out = {};
    if (validDate(s.target_date)) out.target_date = s.target_date;
    if (validDate(s.training_since)) out.training_since = s.training_since;
    if (typeof s.exercise === "string" && s.exercise.length <= LIMITS.name) out.exercise = s.exercise;
    if (s.unit === "kg" || s.unit === "lb") out.unit = s.unit;
    return out;
  }

  function toCSV(entries) {
    const esc = (v) => { const s = v == null ? "" : String(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    return [CSV_FIELDS.join(","), ...entries.map((e) => CSV_FIELDS.map((k) => esc(e[k])).join(","))].join("\n") + "\n";
  }

  // ── formatting ─────────────────────────────────────────────────────────────
  function fmtNum(x) {
    const r = Math.round(x * 10) / 10;
    return Number.isInteger(r) ? String(r) : r.toFixed(1);
  }
  const pct = (x) => `${x >= 0 ? "+" : ""}${Math.round(x * 100)}%`;
  function niceDate(s) {
    const d = new Date(dayNum(s) * DAY_MS);
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  }

  // ── storage ────────────────────────────────────────────────────────────────
  function load(key) {
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) return { ok: true, log: null };
      const got = importJSON(raw, "kg");
      return { ok: true, log: { settings: got.settings || {}, entries: sortEntries(got.entries) } };
    } catch (err) { return { ok: false, log: null }; }
  }
  function save(key, state) {
    try {
      window.localStorage.setItem(key, JSON.stringify({ model: "strength_progress", version: 1,
        updated: new Date().toISOString(), settings: state.settings, entries: state.entries }));
      return true;
    } catch (err) { return false; }
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ── the tool ───────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const today = localToday();
    const stored = load(data.storage_key);
    const state = {
      entries: stored.log ? stored.log.entries : [],
      settings: Object.assign({ unit: "kg" }, stored.log ? stored.log.settings : {}),
      editing: -1, showAll: false, pending: null, message: "",
    };
    if (!validDate(state.settings.target_date) || state.settings.target_date <= today)
      state.settings.target_date = isoDay(dayNum(today) + 7 * data.default_horizon_weeks);
    let storageOk = stored.ok;

    const out = el("div", { class: "sp-out", "aria-live": "polite" });
    const status = el("p", { class: "note sp-status", role: "status" });
    const logBox = el("div", { class: "sp-log" });
    const importBox = el("div", { class: "sp-import" });

    function persist() {
      storageOk = save(data.storage_key, state);
      drawStatus();
    }
    function drawStatus() {
      status.replaceChildren(storageOk ? (state.message || "") :
        el("b", {}, "This browser isn't letting the page save (private browsing or full storage): your log will be lost when you close the page. Export it to keep it."));
    }
    function say(msg) { state.message = msg; drawStatus(); }

    // settings
    const exSelect = el("select", { "aria-label": "Lift to predict", onchange: (e) => { state.settings.exercise = e.target.value; persist(); draw(); } });
    const targetIn = el("input", { type: "date", value: state.settings.target_date, min: isoDay(dayNum(today) + 1),
      max: isoDay(dayNum(today) + Math.floor(data.max_horizon_weeks * 7)), "aria-label": "Target date",
      onchange: (e) => { if (validDate(e.target.value)) { state.settings.target_date = e.target.value; persist(); draw(); } } });
    const sinceIn = el("input", { type: "date", value: state.settings.training_since || "", max: today, "aria-label": "Training since",
      onchange: (e) => { state.settings.training_since = validDate(e.target.value) ? e.target.value : ""; persist(); draw(); } });
    const unitSel = el("select", { "aria-label": "Show weights in", onchange: (e) => { state.settings.unit = e.target.value; persist(); draw(); } },
      ["kg", "lb"].map((u) => el("option", { value: u, ...(u === state.settings.unit ? { selected: "" } : {}) }, u)));

    // the add / edit form
    const f = {
      date: el("input", { type: "date", value: today, max: today, "aria-label": "Date" }),
      exercise: el("input", { type: "text", placeholder: "Squat", list: "sp-lifts", maxlength: String(LIMITS.name), "aria-label": "Exercise" }),
      weight: el("input", { type: "text", inputmode: "decimal", placeholder: "100", size: "6", "aria-label": "Weight" }),
      unit: el("select", { "aria-label": "Unit" }, ["kg", "lb"].map((u) => el("option", { value: u }, u))),
      kind: el("select", { "aria-label": "Reps or seconds" }, el("option", { value: "reps" }, "reps"), el("option", { value: "seconds" }, "seconds")),
      amount: el("input", { type: "text", inputmode: "numeric", placeholder: "5", size: "5", "aria-label": "Reps or seconds" }),
    };
    f.unit.value = state.settings.unit;
    const lifts = el("datalist", { id: "sp-lifts" });
    const formMsg = el("p", { class: "note" });
    const addBtn = el("button", { type: "submit", class: "ss-btn" }, "Add set");
    const cancelBtn = el("button", { type: "button", class: "ss-btn", hidden: "", onclick: () => stopEdit() }, "Cancel");
    const form = el("form", { class: "sp-form", onsubmit: (ev) => {
      ev.preventDefault();
      const raw = { date: f.date.value, exercise: f.exercise.value, weight: f.weight.value, unit: f.unit.value,
        [f.kind.value]: f.amount.value };
      const [e, why] = cleanEntry(raw, f.unit.value);
      if (!e) { formMsg.textContent = `Not added: ${why}.`; return; }
      formMsg.textContent = "";
      if (state.editing >= 0) state.entries.splice(state.editing, 1, e);
      else state.entries.push(e);
      sortEntries(state.entries);
      if (!state.settings.exercise) state.settings.exercise = e.exercise;
      stopEdit(true);
      persist(); say(`Saved: ${e.exercise} ${fmtNum(e.weight)} ${e.unit} x ${e.reps != null ? `${e.reps} reps` : `${e.seconds} s`} on ${e.date}.`);
      draw();
      f.weight.focus();
    } },
      ...[["Date", f.date], ["Exercise", f.exercise], ["Weight", f.weight], ["Unit", f.unit], ["Reps or seconds", f.kind], ["How many", f.amount]]
        .map(([t, input]) => el("label", {}, el("span", { class: "rc-lbl" }, t), input)),
      addBtn, cancelBtn, lifts);

    function startEdit(i) {
      const e = state.entries[i];
      state.editing = i;
      f.date.value = e.date; f.exercise.value = e.exercise; f.weight.value = String(e.weight); f.unit.value = e.unit;
      f.kind.value = e.reps != null ? "reps" : "seconds"; f.amount.value = String(e.reps != null ? e.reps : e.seconds);
      addBtn.textContent = "Save changes"; cancelBtn.hidden = false;
      f.weight.focus();
    }
    function stopEdit(keep) {
      state.editing = -1; addBtn.textContent = "Add set"; cancelBtn.hidden = true;
      if (!keep) { f.weight.value = ""; f.amount.value = ""; }
    }

    // import / export / clear
    const fileUnit = el("select", { "aria-label": "Units in the file" }, ["kg", "lb"].map((u) => el("option", { value: u }, u)));
    fileUnit.value = state.settings.unit;
    const fileIn = el("input", { type: "file", accept: ".csv,.json,.txt,text/csv,application/json", "aria-label": "Import a file",
      onchange: (ev) => {
        const file = ev.target.files && ev.target.files[0];
        ev.target.value = "";
        if (!file) return;
        if (file.size > 20e6) { showImport({ error: "That file is over 20 MB; is it the right one?" }); return; }
        const reader = new FileReader();
        reader.onload = () => {
          const text = String(reader.result);
          const got = /^\s*[[{]/.test(text) ? importJSON(text, fileUnit.value) : importCSV(text, fileUnit.value);
          showImport(got);
        };
        reader.onerror = () => showImport({ error: "Couldn't read that file." });
        reader.readAsText(file);
      } });

    function showImport(got) {
      state.pending = got && got.entries && got.entries.length ? got : null;
      if (!got || got.error || !got.entries.length) {
        const why = got && got.error ? got.error
          : got && got.skipped.length ? `No sets found. ${got.skipped.slice(0, 3).map(([r, w]) => (r ? `Row ${r}: ${w}` : w)).join("; ")}.`
          : "No sets found in that file.";
        importBox.replaceChildren(el("p", { class: "note" }, el("b", {}, why)));
        return;
      }
      const skipped = got.skipped.length
        ? ` ${got.skipped.length} row${got.skipped.length > 1 ? "s" : ""} skipped (e.g. ${got.skipped.slice(0, 3).map(([r, w]) => `row ${r}: ${w}`).join("; ")}).` : "";
      const done = (entries, msg) => {
        state.entries = entries;
        if (got.settings) Object.assign(state.settings, got.settings);
        state.pending = null; importBox.replaceChildren();
        persist(); say(msg); draw();
      };
      importBox.replaceChildren(
        el("p", {}, `Found ${got.entries.length} set${got.entries.length > 1 ? "s" : ""} (${got.format} file).${skipped}`),
        el("div", { class: "sp-actions" },
          el("button", { type: "button", class: "ss-btn", onclick: () => {
            const m = merge(state.entries, got.entries);
            done(m.entries, `Added ${m.added} set${m.added === 1 ? "" : "s"}${m.duplicates ? ` (${m.duplicates} already in your log)` : ""}.`);
          } }, "Add to my log"),
          state.entries.length ? el("button", { type: "button", class: "ss-btn", onclick: () => {
            if (window.confirm(`Replace all ${state.entries.length} sets in your log with the ${got.entries.length} from this file?`))
              done(merge([], got.entries).entries, "Your log was replaced by the file.");
          } }, "Replace my log") : null,
          el("button", { type: "button", class: "ss-btn", onclick: () => { state.pending = null; importBox.replaceChildren(); } }, "Cancel")));
    }

    const stamp = () => today;
    const tools = el("div", { class: "sp-actions" },
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-strength_progress-log-${stamp()}.json`,
        JSON.stringify({ model: "strength_progress", version: 1, updated: new Date().toISOString(), settings: state.settings, entries: state.entries }, null, 1),
        "application/json") }, "Export (JSON)"),
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-strength_progress-log-${stamp()}.csv`,
        toCSV(state.entries), "text/csv") }, "Export (CSV)"),
      el("label", { class: "ss-btn sp-file" }, "Import a file…", fileIn),
      el("label", { class: "pick" }, "Weights in the file, if it doesn't say: ", fileUnit),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!state.entries.length) return;
        if (window.confirm(`Delete all ${state.entries.length} sets from this browser? Export first if you want to keep them.`)) {
          state.entries = []; state.settings = { unit: state.settings.unit, target_date: state.settings.target_date };
          persist(); say("Your log was cleared."); draw();
        }
      } }, "Clear my log"));

    function drawLog() {
      const shown = state.entries.map((e, i) => [e, i]).reverse();
      const rows = state.showAll ? shown : shown.slice(0, SHOW_ROWS);
      lifts.replaceChildren(...[...new Set(state.entries.map((e) => e.exercise))].map((n) => el("option", { value: n })));
      if (!state.entries.length) {
        logBox.replaceChildren(el("p", { class: "note" }, "Your log is empty. Add a set above, or import a file from Hevy, Strong or a spreadsheet."));
        return;
      }
      const table = el("table", {},
        el("thead", {}, el("tr", {}, ["Date", "Exercise", "Weight", "Reps / time", ""].map((t, i) =>
          el("th", { class: i >= 2 && i < 4 ? "num" : null, scope: "col" }, t)))),
        el("tbody", {}, rows.map(([e, i]) => el("tr", {},
          el("td", {}, e.date), el("td", {}, e.exercise),
          el("td", { class: "num" }, `${fmtNum(e.weight)} ${e.unit}`),
          el("td", { class: "num" }, e.reps != null ? `${e.reps} reps` : `${fmtNum(e.seconds)} s`),
          el("td", { class: "sp-rowbtns" },
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Edit ${e.exercise} on ${e.date}`, onclick: () => startEdit(i) }, "Edit"),
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Delete ${e.exercise} on ${e.date}`, onclick: () => {
              state.entries.splice(i, 1); if (state.editing === i) stopEdit(); persist(); say("Set deleted."); draw();
            } }, "Delete"))))));
      logBox.replaceChildren(...[
        el("p", { class: "small" }, `${state.entries.length} set${state.entries.length > 1 ? "s" : ""}, newest first.`),
        el("div", { class: "table-wrap" }, table),
        shown.length > SHOW_ROWS ? el("button", { type: "button", class: "ss-btn", onclick: () => { state.showAll = !state.showAll; drawLog(); } },
          state.showAll ? "Show fewer" : `Show all ${shown.length}`) : null].filter(Boolean));
    }

    function drawResult() {
      const names = [...new Set(state.entries.map((e) => e.exercise))];
      exSelect.replaceChildren(...names.map((n) => el("option", { value: n, ...(n === state.settings.exercise ? { selected: "" } : {}) }, n)));
      if (!names.length) { out.replaceChildren(el("p", { class: "note" }, "Add a few sets to see a forecast.")); return; }
      const res = compute(data, state.entries, { today, target_date: state.settings.target_date,
        exercise: state.settings.exercise, training_since: state.settings.training_since, unit: state.settings.unit });
      if (res.error) { out.replaceChildren(el("p", { class: "note" }, el("b", {}, res.error))); return; }
      if (!state.settings.exercise) exSelect.value = res.exercise;
      const u = res.unit, p = res.primary, w = p.weights, v = p.values;
      const kg = (x) => `${fmtNum(x)} ${u}`;
      const ranges = [["Half of people", 2, 4], ["8 in 10", 1, 5], ["19 in 20", 0, 6]];
      const table = el("table", {},
        el("thead", {}, el("tr", {}, ["", `Weight for ${p.usual}`, "Change from today"].map((t, i) => el("th", { class: i ? "num" : null, scope: "col" }, t)))),
        el("tbody", {},
          el("tr", {}, el("td", {}, el("b", {}, "Most likely")), el("td", { class: "num" }, el("b", {}, kg(w[MEDIAN]))),
            el("td", { class: "num" }, pct(w[MEDIAN] / p.currentWeight - 1))),
          ranges.map(([label, lo, hi]) => el("tr", {}, el("td", {}, label),
            el("td", { class: "num" }, `${kg(w[lo])} - ${kg(w[hi])}`),
            el("td", { class: "num" }, `${pct(w[lo] / p.currentWeight - 1)} to ${pct(w[hi] / p.currentWeight - 1)}`)))));
      const notes = [];
      if (!state.settings.training_since && p.weeks < 26)
        notes.push("Your training time counts from your first logged set. If you trained before that, set \"Training since\": beginners are expected to gain much faster.");
      if (p.days > data.gap_cap_days)
        notes.push(`Your last ${res.exercise} set was ${Math.round(p.days)} days ago, longer than anyone in the data had paused; the range may be too narrow.`);
      if (p.freq < data.ref_per_week)
        notes.push(`You've done ${res.exercise} ${fmtNum(p.freq)} times a week lately; training less than once a week makes the range wider.`);
      const others = res.others.length ? el("div", { class: "table-wrap" }, el("table", {},
        el("thead", {}, el("tr", {}, ["Other lifts", "Today", "Most likely", "8 in 10"].map((t, i) => el("th", { class: i ? "num" : null, scope: "col" }, t)))),
        el("tbody", {}, res.others.map((o) => el("tr", {}, el("td", {}, `${o.exercise} (${o.usual})`),
          el("td", { class: "num" }, kg(o.currentWeight)), el("td", { class: "num" }, kg(o.weights[MEDIAN])),
          el("td", { class: "num" }, `${kg(o.weights[1])} - ${kg(o.weights[5])}`)))))) : null;
      out.replaceChildren(...[
        el("p", { class: "rc-own" }, `On ${niceDate(state.settings.target_date)} you'll most likely lift ${kg(w[MEDIAN])} for ${p.usual} on ${res.exercise} `
          + `(today: ${kg(p.currentWeight)}, ${pct(w[MEDIAN] / p.currentWeight - 1)}).`),
        el("div", { class: "table-wrap" }, table),
        p.last.reps != null ? el("p", {}, `Estimated one-rep max: ${kg(v[MEDIAN])} (8 in 10: ${kg(v[1])} - ${kg(v[5])}); today ${kg(p.current)}.`) : null,
        ...notes.map((t) => el("p", { class: "note" }, t)),
        others,
        el("p", { class: "note" }, "Learned from one machine-training programme (fit20: one slow set to failure per machine, about once a week, 2011-2016). "
          + "For free weights or bigger programmes, treat it as a rough guide."),
      ].filter(Boolean));
    }

    function draw() { drawResult(); drawLog(); drawStatus(); }

    host.replaceChildren(
      el("div", { class: "rc-form" },
        el("div", { class: "pick-row" },
          el("label", { class: "pick" }, "Lift: ", exSelect),
          el("label", { class: "pick" }, "On: ", targetIn),
          el("label", { class: "pick" }, "Training since (optional): ", sinceIn),
          el("label", { class: "pick" }, "Show in: ", unitSel))),
      out,
      el("h3", { class: "sp-h" }, "Add a set"),
      form, formMsg,
      el("h3", { class: "sp-h" }, "Your log"),
      status, tools, importBox, logBox);   // the view's note says the log stays in this browser
    draw();
  }

  const api = { compute, forecast, sessionsByExercise, cleanEntry, parseCSV, importCSV, importJSON, toCSV, merge, parseAnyDate, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests (node)
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).strength_progress = api;
})();
