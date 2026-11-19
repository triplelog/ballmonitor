// Running progress: a training log kept in the visitor's browser, and a forecast from it (the
// running_progress page's "app" view).
//
// compute() is a line-by-line copy of the running_progress model (models/running_progress:
// features.weekly_totals, clean, window, summarise, season_value; model.predict with the formulas
// pace_location, pace_scale, pace_quantile, km_location, km_scale, km_quantile, p_running and
// tanda_marathon in config.toml). Every number it uses comes from the model's config, written
// into the page by site.py at build time. tests/test_running_progress_app.py runs this file under
// node and checks it against the Python model.
//
// The log is stored only in this browser (localStorage key data.storage_key) as
//   {model, version: 1, updated, settings: {weeks_ahead, hemisphere, units, from}, entries: [...]}
// with entries {date: "YYYY-MM-DD", km, minutes, type: "run" | "week", note}. Nothing is uploaded:
// this file makes no network requests. Imports (Strava activities.csv, Garmin Connect
// Activities.csv, any CSV with date/distance/time, or this tool's own JSON/CSV) are read locally.
"use strict";

(function () {
  const DAY = 86400000;
  const MAX_ENTRY_KM = 300;          // one entry: a run or a week (the model's max_week_km is 300 too)
  const MAX_ENTRY_MIN = 100 * 60;    // 100 hours
  const NOTE_MAX = 200;

  // ── dates (whole days since 1970-01-01, UTC, so no time zones or DST) ──────
  function dayOf(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || "").trim());
    if (!m) return null;
    const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
    const d = new Date(t);
    if (d.getUTCFullYear() !== +m[1] || d.getUTCMonth() !== +m[2] - 1 || d.getUTCDate() !== +m[3]) return null;
    return Math.round(t / DAY);
  }
  const isoOf = (day) => new Date(day * DAY).toISOString().slice(0, 10);
  const monthOf = (day) => new Date(day * DAY).getUTCMonth() + 1;
  function localToday() {
    const n = new Date();
    return Math.round(Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()) / DAY);
  }

  // ── the model (features.py + model.py) ─────────────────────────────────────
  // entries: [{date, km, minutes}]; today: day number. Returns rows [[km, minutes]] oldest first.
  function weeklyTotals(entries, today, lookback) {
    const totals = new Map();
    let ignored = 0;
    for (const e of entries) {
      const days = today - dayOf(e.date);
      if (days < 1) { ignored++; continue; }               // on or after today: not known yet
      const k = Math.floor((days - 1) / 7);
      if (k >= lookback) { ignored++; continue; }          // older than the lookback
      const t = totals.get(k) || [0, 0];
      t[0] += e.km;
      t[1] += e.minutes;
      totals.set(k, t);
    }
    if (!totals.size) throw new Error(`No runs in the ${lookback} weeks before the forecast date.`);
    const span = Math.max(...totals.keys()) + 1;
    const rows = [];
    for (let k = span - 1; k >= 0; k--) rows.push(totals.get(k) || [0, 0]);
    return { rows, ignored };
  }

  function clean(rows, d) {
    return rows.map(([km, mins]) => {
      if (km > 0) {
        const pace = mins / km;
        if (pace < d.min_pace_min_per_km || pace > d.max_pace_min_per_km || km > d.max_week_km) return [null, null];
      }
      return [km, km > 0 ? mins : 0];
    });
  }

  function window_(weekly, n) {
    const ok = weekly.slice(-n).filter(([k]) => k !== null);
    const w = {
      weeks: ok.length, run_weeks: ok.filter(([k]) => k > 0).length,
      km: ok.reduce((a, [k]) => a + k, 0), minutes: ok.reduce((a, [, m]) => a + m, 0),
    };
    w.kmw = w.weeks ? w.km / w.weeks : 0;
    w.pace = w.km > 0 ? w.minutes * 60 / w.km : null;
    return w;
  }

  const weekMid = (today, k) => today - (7 * k + 4);
  const targetMids = (today, h, n) => Array.from({ length: n }, (_, j) => today + 7 * (h - n + j) + 3);

  function seasonValue(days, curve, southern) {
    const vals = days.map((day) => {
      let m = monthOf(day);
      if (southern) m = (m + 5) % 12 + 1;
      return curve[m - 1];
    });
    return vals.reduce((a, v) => a + v, 0) / vals.length;
  }

  function summarise(rows, today, d) {
    const weekly = clean(rows, d);
    const recent = window_(weekly, d.recent_weeks), base = window_(weekly, d.base_weeks);
    const long = window_(weekly, d.lookback_weeks), tanda = window_(weekly, d.tanda_weeks);
    if (base.run_weeks < d.min_run_weeks) {
      throw new Error(`Your last ${d.base_weeks} weeks have ${base.run_weeks} week${base.run_weeks === 1 ? "" : "s"} `
        + `with running; the forecast needs at least ${d.min_run_weeks} to know your current pace.`);
    }
    let last = -1;
    weekly.forEach(([k], i) => { if (k) last = i; });
    const off = d.km_offset;
    const lpBase = Math.log(base.pace);
    const lkBase = Math.log(base.kmw + off);
    const n = weekly.length;
    const mids = [];
    for (let k = Math.min(n, d.base_weeks) - 1; k >= 0; k--) mids.push(weekMid(today, k));
    return {
      weekly, recent, base, long, tanda, n, missing: weekly.filter(([k]) => k === null).length,
      share: base.run_weeks / base.weeks, since: Math.min(n - 1 - last, d.base_weeks),
      lp_base: lpBase, tr_recent: recent.pace ? Math.log(recent.pace / base.pace) : 0,
      tr_long: Math.log(base.pace / long.pace), lk_base: lkBase,
      ktr_recent: Math.log(recent.kmw + off) - lkBase, ktr_long: lkBase - Math.log(long.kmw + off), mids,
    };
  }

  // inputs: {entries, today: "YYYY-MM-DD" (the day the forecast is made; entries on/after it are
  // not used), target: "YYYY-MM-DD" (or weeks_ahead), southern: bool}. Returns the forecast or
  // {error}.
  function compute(d, inputs) {
    try {
      const today = dayOf(inputs.today);
      const h = inputs.target !== undefined ? (dayOf(inputs.target) - today) / 7 : Number(inputs.weeks_ahead);
      if (!(h >= d.min_horizon_weeks && h <= d.max_horizon_weeks)) {
        throw new Error(`Pick a date ${d.min_horizon_weeks}-${d.max_horizon_weeks} weeks ahead.`);
      }
      const southern = !!inputs.southern;
      const { rows, ignored } = weeklyTotals(inputs.entries, today, d.lookback_weeks);
      const f = summarise(rows, today, d);
      const hr = Math.round(h);
      const tm = targetMids(today, hr, d.target_weeks);
      const sp = seasonValue(tm, d.season_pace, southern) - seasonValue(f.mids, d.season_pace, southern);
      const sk = seasonValue(tm, d.season_km, southern) - seasonValue(f.mids, d.season_km, southern);
      const lh = Math.log(h / d.min_horizon_weeks);
      const relP = f.lp_base - Math.log(d.ref_pace);
      const relK = f.lk_base - Math.log(d.ref_km + d.km_offset);
      const pl = d.pace_loc, ps = d.pace_scale, kl = d.km_loc, ks = d.km_scale, r = d.run;
      const loc = f.lp_base + pl.a + pl.recent * f.tr_recent + pl.long * f.tr_long + pl.season * sp + pl.rel * relP;
      const scale = Math.exp(ps.a + ps.h * lh + ps.share * f.share + ps.rel * relP + ps.trend * Math.abs(f.tr_recent));
      const kloc = f.lk_base + kl.a + kl.recent * f.ktr_recent + kl.long * f.ktr_long + kl.season * sk
        + kl.share * f.share + kl.rel * relK;
      const kscale = Math.exp(ks.a + ks.h * lh + ks.share * f.share + ks.rel * relK + ks.trend * Math.abs(f.ktr_recent));
      const sorted = (z) => [...z].sort((a, b) => a - b);
      const pace = sorted(d.pace_z).map((z) => Math.exp(loc + scale * z));
      const km = sorted(d.km_z).map((z) => Math.max(Math.exp(kloc + kscale * z) - d.km_offset, 0));
      const pRun = 1 / (1 + Math.exp(-(r.a + r.share * f.share + r.since * f.since + r.level * relK + r.h * lh)));
      const tanda = (K, P) => d.marathon_km * (d.tanda_a + d.tanda_b * Math.exp(-d.tanda_k * K) + d.tanda_c * P);
      const tandaPace = f.tanda.pace || f.base.pace;
      return {
        h, today: isoOf(today), target_end: isoOf(today + Math.round(7 * h)), ignored, southern,
        season_pace: sp, season_km: sk, pace_location: loc, pace_scale: scale, km_location: kloc, km_scale: kscale,
        pace, km, p_running: pRun,
        tanda_now: tanda(f.tanda.kmw, tandaPace), tanda_target: tanda(km[d.median], pace[d.median]),
        pace_now: f.recent.pace || f.base.pace, km_now: f.recent.kmw, share: f.share,
        features: f,
      };
    } catch (e) {
      return { error: e.message };
    }
  }

  // ── reading numbers, times, dates ──────────────────────────────────────────
  function parseNumber(text) {
    let s = String(text ?? "").trim().replace(/\s/g, "");
    if (!s) return null;
    if (/^\d+,\d+$/.test(s)) s = s.replace(",", ".");                 // decimal comma: 10,5
    else if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) s = s.replace(/,/g, "");   // thousands: 1,234.5
    if (!/^-?\d*\.?\d+$/.test(s)) return null;
    return Number(s);
  }

  // "1:02:30" / "45:30" / "45:30.4" -> minutes; a bare number -> minutes
  function parseMinutes(text) {
    const s = String(text ?? "").trim();
    if (!s) return null;
    const parts = s.split(":");
    if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null;
    const n = parts.map(Number);
    return n.length === 3 ? n[0] * 60 + n[1] + n[2] / 60 : n.length === 2 ? n[0] + n[1] / 60 : n[0];
  }

  function clock(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const pad = (x) => String(x).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  // A date in an export: ISO ("2024-01-05", "2024-01-05 06:30:12", "2024-01-05T06:30:12Z") or Strava's
  // English "Jan 5, 2024, 6:30:12 AM". Returns "YYYY-MM-DD" or null. The calendar day as written is
  // used (Strava writes UTC; a run just after midnight UTC may land on the next day).
  function parseDate(text) {
    const s = String(text ?? "").trim();
    let m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$/.exec(s);
    if (m) {
      const iso = `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
      return dayOf(iso) === null ? null : iso;
    }
    m = /^([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4})/.exec(s);
    if (m && MONTHS[m[1].toLowerCase()]) {
      const iso = `${m[3]}-${String(MONTHS[m[1].toLowerCase()]).padStart(2, "0")}-${m[2].padStart(2, "0")}`;
      return dayOf(iso) === null ? null : iso;
    }
    m = /^(\d{1,2}) ([A-Za-z]{3})[a-z]*\.? (\d{4})/.exec(s);                // "5 Jan 2024"
    if (m && MONTHS[m[2].toLowerCase()]) {
      const iso = `${m[3]}-${String(MONTHS[m[2].toLowerCase()]).padStart(2, "0")}-${m[1].padStart(2, "0")}`;
      return dayOf(iso) === null ? null : iso;
    }
    return null;
  }

  // ── CSV ────────────────────────────────────────────────────────────────────
  function parseCSV(text) {
    const rows = [];
    let row = [], field = "", quoted = false;
    text = String(text).replace(/^﻿/, "");
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false;
        } else field += c;
      } else if (c === '"') quoted = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(field); field = "";
        if (row.length > 1 || row[0] !== "") rows.push(row);
        row = [];
      } else field += c;
    }
    row.push(field);
    if (row.length > 1 || row[0] !== "") rows.push(row);
    return rows;
  }

  const csvCell = (v) => {
    const s = String(v ?? "");
    return /[",\n\r]/.test(s) || /^[=+\-@]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };

  // Check and tidy one entry; returns [entry, null] or [null, "reason"].
  function validEntry(raw) {
    const date = parseDate(raw.date);
    if (!date) return [null, "no valid date"];
    const km = typeof raw.km === "number" ? raw.km : parseNumber(raw.km);
    const minutes = typeof raw.minutes === "number" ? raw.minutes : parseMinutes(raw.minutes);
    if (!(km > 0) || !Number.isFinite(km) || km > MAX_ENTRY_KM) return [null, "distance missing or not between 0 and 300 km"];
    if (!(minutes > 0) || !Number.isFinite(minutes) || minutes > MAX_ENTRY_MIN) return [null, "time missing or too long"];
    const type = raw.type === "week" ? "week" : "run";
    const note = String(raw.note ?? "").replace(/[\u0000-\u001f]/g, " ").slice(0, NOTE_MAX);
    return [{ date, km: Math.round(km * 1000) / 1000, minutes: Math.round(minutes * 100) / 100, type, note }, null];
  }

  const findCol = (header, names) => {
    const lower = header.map((h) => h.trim().toLowerCase());
    for (const n of names) { const i = lower.indexOf(n); if (i >= 0) return i; }
    return -1;
  };
  const findAll = (header, name) => header.map((h, i) => (h.trim().toLowerCase() === name ? i : -1)).filter((i) => i >= 0);

  // Which export is it? "strava" | "garmin" | "generic" | null
  function detectCSV(header) {
    const has = (n) => findCol(header, [n]) >= 0;
    if (has("activity date") && has("activity type")) return "strava";
    if (has("activity type") && has("date") && has("time") && has("distance")) return "garmin";
    if (has("date") && (has("km") || has("miles") || has("distance") || has("distance_km") || has("distance_mi"))) return "generic";
    return null;
  }

  // rows: parsed CSV (first row = header). unit: "km" | "mi" for files whose distances carry no unit.
  // Returns {kind, entries, skipped, errors: ["line 4: ..."], notRuns}
  function importCSV(rows, unit, kmPerMile) {
    if (!rows.length) return { kind: null, entries: [], skipped: 0, errors: ["The file is empty."], notRuns: 0 };
    const header = rows[0];
    const kind = detectCSV(header);
    const out = { kind, entries: [], skipped: 0, errors: [], notRuns: 0 };
    if (!kind) {
      out.errors.push("Couldn't recognise this file: it needs a header row with date, distance and time "
        + "(or be a Strava activities.csv or a Garmin Connect activities export).");
      return out;
    }
    const toKm = (v, u) => (v === null ? null : u === "mi" ? v * kmPerMile : v);
    let get;
    if (kind === "strava") {
      // Strava's bulk export repeats some headers: the first Distance is in km (or miles, by the
      // account's setting), the later one in meters; Moving Time and the later Elapsed Time are seconds.
      const iDate = findCol(header, ["activity date"]), iType = findCol(header, ["activity type"]);
      const dist = findAll(header, "distance"), moving = findCol(header, ["moving time"]), elapsed = findAll(header, "elapsed time");
      const iName = findCol(header, ["activity name"]);
      get = (r) => {
        if (!/run/i.test(r[iType] || "")) return "notrun";
        let km = dist.length > 1 ? parseNumber(r[dist[dist.length - 1]]) : null;
        km = km !== null && km > 0 ? km / 1000 : toKm(parseNumber(r[dist[0]]), unit);
        let sec = moving >= 0 ? parseNumber(r[moving]) : null;
        if (!(sec > 0)) sec = elapsed.length ? parseNumber(r[elapsed[elapsed.length - 1]]) : null;
        if (!(sec > 0) && elapsed.length) sec = parseNumber(r[elapsed[0]]);
        return { date: r[iDate], km, minutes: sec > 0 ? sec / 60 : null, type: "run", note: iName >= 0 ? r[iName] : "" };
      };
    } else if (kind === "garmin") {
      const iType = findCol(header, ["activity type"]), iDate = findCol(header, ["date"]);
      const iDist = findCol(header, ["distance"]), iTime = findCol(header, ["time", "moving time", "elapsed time"]);
      const iTitle = findCol(header, ["title"]);
      get = (r) => {
        if (!/run/i.test(r[iType] || "")) return "notrun";
        return { date: r[iDate], km: toKm(parseNumber(r[iDist]), unit), minutes: parseMinutes(r[iTime]), type: "run",
          note: iTitle >= 0 ? r[iTitle] : "" };
      };
    } else {
      const iDate = findCol(header, ["date"]);
      const iKm = findCol(header, ["km", "distance_km", "distance (km)", "kilometers", "kilometres"]);
      const iMi = findCol(header, ["miles", "mi", "distance_mi", "distance (mi)"]);
      const iDist = findCol(header, ["distance"]);
      const iMin = findCol(header, ["minutes", "duration_min"]);
      const iTime = findCol(header, ["time", "duration", "moving time", "elapsed time"]);
      const iType = findCol(header, ["type"]), iNote = findCol(header, ["note", "notes", "title", "name"]);
      get = (r) => {
        const km = iKm >= 0 ? parseNumber(r[iKm]) : iMi >= 0 ? toKm(parseNumber(r[iMi]), "mi")
          : toKm(parseNumber(r[iDist]), unit);
        const minutes = iMin >= 0 ? parseNumber(r[iMin]) : iTime >= 0 ? parseMinutes(r[iTime]) : null;
        return { date: r[iDate], km, minutes, type: iType >= 0 && /week/i.test(r[iType]) ? "week" : "run",
          note: iNote >= 0 ? r[iNote] : "" };
      };
    }
    rows.slice(1).forEach((r, i) => {
      const raw = get(r);
      if (raw === "notrun") { out.notRuns++; return; }
      const [entry, why] = validEntry(raw);
      if (entry) out.entries.push(entry);
      else { out.skipped++; if (out.errors.length < 5) out.errors.push(`Line ${i + 2}: ${why}.`); }
    });
    return out;
  }

  // This tool's own JSON export (or a plain array of entries).
  function importJSON(text) {
    const out = { kind: "json", entries: [], skipped: 0, errors: [], notRuns: 0, settings: null };
    let obj;
    try { obj = JSON.parse(text); } catch (e) { out.errors.push("This isn't a valid JSON file."); return out; }
    const list = Array.isArray(obj) ? obj : obj && Array.isArray(obj.entries) ? obj.entries : null;
    if (!list) { out.errors.push("The JSON file has no list of entries."); return out; }
    if (obj && !Array.isArray(obj) && obj.model && obj.model !== "running_progress") {
      out.errors.push(`This log is for another Ball Monitor tool (${String(obj.model).slice(0, 40)}).`);
      return out;
    }
    list.forEach((raw, i) => {
      const [entry, why] = raw && typeof raw === "object" ? validEntry(raw) : [null, "not an entry"];
      if (entry) out.entries.push(entry);
      else { out.skipped++; if (out.errors.length < 5) out.errors.push(`Entry ${i + 1}: ${why}.`); }
    });
    if (obj && obj.settings && typeof obj.settings === "object") out.settings = obj.settings;
    return out;
  }

  const entryKey = (e) => `${e.date}|${e.km.toFixed(2)}|${e.minutes.toFixed(1)}`;
  function mergeEntries(old, add) {
    const seen = new Set(old.map(entryKey));
    const merged = [...old];
    let added = 0;
    for (const e of add) {
      const k = entryKey(e);
      if (!seen.has(k)) { seen.add(k); merged.push(e); added++; }
    }
    return { entries: sortEntries(merged), added };
  }
  const sortEntries = (list) => [...list].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));

  function exportCSV(entries) {
    const lines = [["date", "km", "minutes", "type", "note"].join(",")];
    for (const e of sortEntries(entries).reverse()) lines.push([e.date, e.km, e.minutes, e.type, e.note].map(csvCell).join(","));
    return lines.join("\n") + "\n";
  }

  // ── storage (this browser only) ────────────────────────────────────────────
  function loadStore(key) {
    let raw;
    try {
      raw = window.localStorage.getItem(key);
    } catch (e) {
      return { ok: false, value: null };
    }
    if (!raw) return { ok: true, value: null };
    const parsed = importJSON(raw);   // validated like an import; a damaged value starts an empty log
    const settings = parsed.settings && typeof parsed.settings === "object" ? parsed.settings : {};
    return { ok: true, value: { settings, entries: parsed.entries } };
  }
  function saveStore(key, model, settings, entries) {
    try {
      window.localStorage.setItem(key, JSON.stringify(
        { model, version: 1, updated: new Date().toISOString(), settings, entries }));
      return true;
    } catch (e) {
      return false;
    }
  }
  function removeStore(key) {
    try { window.localStorage.removeItem(key); return true; } catch (e) { return false; }
  }

  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ── the page ───────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const KMI = data.km_per_mile;
    const stored = loadStore(data.storage_key);
    const state = {
      entries: stored.value ? sortEntries(stored.value.entries) : [],
      settings: Object.assign({ weeks_ahead: data.default_weeks_ahead, hemisphere: "north", units: "km", from: "" },
        stored.value ? stored.value.settings : {}),
      editing: null, showAll: false, pending: null, storageOk: stored.ok,
    };
    const s = state.settings;
    if (!["km", "mi"].includes(s.units)) s.units = "km";
    if (!["north", "south"].includes(s.hemisphere)) s.hemisphere = "north";
    s.weeks_ahead = Math.min(Math.max(Math.round(Number(s.weeks_ahead) || data.default_weeks_ahead),
      data.min_horizon_weeks), data.max_horizon_weeks);

    const unitName = () => (s.units === "mi" ? "mi" : "km");
    const dist = (km) => (s.units === "mi" ? km / KMI : km);
    const paceIn = (secPerKm) => (s.units === "mi" ? secPerKm * KMI : secPerKm);
    const fmtPace = (secPerKm) => `${clock(paceIn(secPerKm))} per ${unitName()}`;
    const fmtDist = (km, digits = 1) => `${dist(km).toFixed(digits)} ${unitName()}`;
    const longDate = (iso) => new Date(dayOf(iso) * DAY).toLocaleDateString(undefined,
      { timeZone: "UTC", day: "numeric", month: "short", year: "numeric" });
    const fromDay = () => (s.from && dayOf(s.from) !== null ? dayOf(s.from) : localToday() + 1);

    function persist() {
      state.storageOk = saveStore(data.storage_key, data.model, s, state.entries);
    }

    // form
    const fDate = el("input", { type: "date", "aria-label": "Date", required: "" });
    const fDist = el("input", { type: "text", inputmode: "decimal", size: "7", placeholder: "10.0", "aria-label": "Distance" });
    const fTime = el("input", { type: "text", inputmode: "numeric", size: "9", placeholder: "52:30", "aria-label": "Time" });
    const fType = el("select", { "aria-label": "Entry type" },
      el("option", { value: "run" }, "One run"), el("option", { value: "week" }, "Week total"));
    const fNote = el("input", { type: "text", size: "16", maxlength: String(NOTE_MAX), placeholder: "optional", "aria-label": "Note" });
    const distLabel = el("span", { class: "rc-lbl" });
    const formMsg = el("p", { class: "note", "aria-live": "polite" });
    const saveBtn = el("button", { type: "submit", class: "ss-btn" }, "Add to log");
    const cancelBtn = el("button", { type: "button", class: "ss-btn", hidden: "", onclick: () => resetForm() }, "Cancel");

    function resetForm() {
      state.editing = null;
      fDate.value = isoOf(localToday());
      fDist.value = ""; fTime.value = ""; fNote.value = ""; fType.value = "run";
      saveBtn.textContent = "Add to log";
      cancelBtn.hidden = true;
    }

    const form = el("form", { class: "rc-race", onsubmit: (e) => {
      e.preventDefault();
      const d = parseNumber(fDist.value);
      const raw = { date: fDate.value, km: d === null ? null : s.units === "mi" ? d * KMI : d,
        minutes: parseMinutes(fTime.value), type: fType.value, note: fNote.value };
      const [entry, why] = validEntry(raw);
      if (!entry) { formMsg.textContent = `Not added: ${why}. Time is like 52:30 or 1:05:00.`; return; }
      if (state.editing !== null) state.entries[state.editing] = entry;
      else state.entries.push(entry);
      state.entries = sortEntries(state.entries);
      formMsg.textContent = state.editing !== null ? "Saved." : `Added ${fmtDist(entry.km)} on ${longDate(entry.date)}.`;
      resetForm();
      persist();
      drawAll();
    } },
    el("label", {}, el("span", { class: "rc-lbl" }, "Date"), fDate),
    el("label", {}, el("span", { class: "rc-lbl" }, "What"), fType),
    el("label", {}, distLabel, fDist),
    el("label", {}, el("span", { class: "rc-lbl" }, "Time"), fTime),
    el("label", {}, el("span", { class: "rc-lbl" }, "Note"), fNote),
    saveBtn, cancelBtn);

    // settings
    const weeksSel = el("select", { "aria-label": "Weeks ahead", onchange: (e) => { s.weeks_ahead = +e.target.value; persist(); drawForecast(); } },
      Array.from({ length: data.max_horizon_weeks - data.min_horizon_weeks + 1 }, (_, i) => data.min_horizon_weeks + i)
        .map((w) => el("option", { value: w, ...(w === s.weeks_ahead ? { selected: "" } : {}) }, `${w} weeks`)));
    const unitSel = el("select", { "aria-label": "Units", onchange: (e) => { s.units = e.target.value; persist(); drawAll(); } },
      [["km", "Kilometres"], ["mi", "Miles"]].map(([v, t]) => el("option", { value: v, ...(v === s.units ? { selected: "" } : {}) }, t)));
    const hemiSel = el("select", { "aria-label": "Hemisphere", onchange: (e) => { s.hemisphere = e.target.value; persist(); drawForecast(); } },
      [["north", "Northern"], ["south", "Southern"]].map(([v, t]) => el("option", { value: v, ...(v === s.hemisphere ? { selected: "" } : {}) }, t)));
    const settings = el("div", { class: "rc-race" },
      el("label", {}, el("span", { class: "rc-lbl" }, "Forecast for"), weeksSel),
      el("label", {}, el("span", { class: "rc-lbl" }, "Units"), unitSel),
      el("label", {}, el("span", { class: "rc-lbl" }, "Hemisphere"), hemiSel));

    // import / export
    const fileIn = el("input", { type: "file", accept: ".csv,.json,text/csv,application/json", "aria-label": "Import a file",
      onchange: (e) => readFile(e.target.files[0]) });
    const impUnit = el("select", { "aria-label": "Distances in the file are in" },
      [["km", "km"], ["mi", "miles"]].map(([v, t]) => el("option", { value: v, ...(v === s.units ? { selected: "" } : {}) }, t)));
    const impBox = el("div", { "aria-live": "polite" });
    const tools = el("div", { class: "rc-race" },
      el("label", {}, el("span", { class: "rc-lbl" }, "Import (Strava, Garmin, CSV, JSON)"), fileIn),
      el("label", {}, el("span", { class: "rc-lbl" }, "Distances without a unit are in"), impUnit),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!state.entries.length) { impBox.replaceChildren(el("p", { class: "note" }, "Your log is empty: nothing to export.")); return; }
        download(`ballmonitor-${data.model}-log-${isoOf(localToday())}.json`,
          JSON.stringify({ model: data.model, version: 1, updated: new Date().toISOString(), settings: s, entries: state.entries }, null, 1),
          "application/json");
      } }, "Export JSON"),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!state.entries.length) { impBox.replaceChildren(el("p", { class: "note" }, "Your log is empty: nothing to export.")); return; }
        download(`ballmonitor-${data.model}-log-${isoOf(localToday())}.csv`, exportCSV(state.entries), "text/csv");
      } }, "Export CSV"),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!state.entries.length) return;
        if (!window.confirm("Delete every entry in your log from this browser? This can't be undone (export it first to keep a copy).")) return;
        state.entries = [];
        state.storageOk = removeStore(data.storage_key);
        impBox.replaceChildren(el("p", { class: "note" }, "Your log was cleared."));
        drawAll();
      } }, "Clear my log"));

    const FILE_MAX = 30 * 1024 * 1024;
    function readFile(file) {
      if (!file) return;
      if (file.size > FILE_MAX) { impBox.replaceChildren(el("p", { class: "note" }, "That file is too big (over 30 MB).")); return; }
      const reader = new FileReader();
      reader.onload = () => {
        const text = String(reader.result);
        const res = /\.json$/i.test(file.name) || /^\s*[[{]/.test(text) ? importJSON(text)
          : importCSV(parseCSV(text), impUnit.value, KMI);
        fileIn.value = "";
        showImport(res);
      };
      reader.onerror = () => impBox.replaceChildren(el("p", { class: "note" }, "Couldn't read that file."));
      reader.readAsText(file);
    }

    function showImport(res) {
      const name = { strava: "a Strava export", garmin: "a Garmin Connect export", generic: "a CSV file", json: "a Ball Monitor log" }[res.kind] || "the file";
      const lines = [];
      if (res.entries.length) {
        lines.push(el("p", {}, `Found ${res.entries.length} entr${res.entries.length === 1 ? "y" : "ies"} in ${name}`
          + (res.notRuns ? ` (${res.notRuns} other activit${res.notRuns === 1 ? "y" : "ies"} left out: not runs)` : "")
          + (res.skipped ? `; ${res.skipped} row${res.skipped === 1 ? "" : "s"} couldn't be read` : "") + "."));
      }
      for (const e of res.errors) lines.push(el("p", { class: "note" }, e));
      if (!res.entries.length) {
        if (!res.errors.length) lines.push(el("p", { class: "note" }, `No runs found in ${name}.`));
        impBox.replaceChildren(...lines);
        return;
      }
      const apply = (replace) => {
        if (replace) { state.entries = sortEntries(res.entries); }
        else { state.entries = mergeEntries(state.entries, res.entries).entries; }
        if (res.settings && replace) {
          for (const k of ["weeks_ahead", "hemisphere", "units"]) if (res.settings[k] !== undefined) s[k] = res.settings[k];
        }
        persist();
        impBox.replaceChildren(el("p", { class: "note" }, replace ? "Your log was replaced." : "Added to your log (entries already in it were skipped)."));
        drawAll();
      };
      lines.push(el("div", { class: "rc-race" },
        el("button", { type: "button", class: "ss-btn", onclick: () => apply(false) }, "Add to my log"),
        state.entries.length ? el("button", { type: "button", class: "ss-btn", onclick: () => {
          if (window.confirm("Replace your whole log with this file?")) apply(true);
        } }, "Replace my log") : null,
        el("button", { type: "button", class: "ss-btn", onclick: () => impBox.replaceChildren() }, "Cancel")));
      impBox.replaceChildren(...lines);
    }

    const out = el("div", { class: "rc-out", "aria-live": "polite" });
    const logBox = el("div");
    const storageMsg = el("p", { class: "note" });

    function drawForecast() {
      if (!state.entries.length) {
        out.replaceChildren(el("p", {}, "Add your runs from the last few months (at least three weeks with a run in "
          + "the last twelve), or import them, to see your forecast."),
        el("button", { type: "button", class: "ss-btn", onclick: () => {
          const today = localToday();
          state.entries = sortEntries(data.example.weeks.map((w) => ({
            date: isoOf(today + 1 - w.days_before), km: w.km, minutes: w.minutes, type: "week", note: "example" })));
          persist();
          drawAll();
        } }, "Try an example log"),
        el("p", { class: "note" }, `The example is ${data.example.label}, with the dates moved to end this week.`));
        return;
      }
      const today = fromDay();
      const res = compute(data, { entries: state.entries, today: isoOf(today), weeks_ahead: s.weeks_ahead,
        southern: s.hemisphere === "south" });
      if (res.error) { out.replaceChildren(el("p", { class: "note" }, res.error)); return; }
      const [lo50, hi50] = data.bands["0.5"], [lo80, hi80] = data.bands["0.8"], [lo95, hi95] = data.bands["0.95"];
      const M = data.median, p = res.pace, k = res.km;
      const range = (q, a, b, f) => `${f(q[a])} - ${f(q[b])}`;
      const pf = (x) => clock(paceIn(x)), kf = (x) => dist(x).toFixed(1);
      const table = el("table", {},
        el("thead", {}, el("tr", {}, ["", "Most likely", "Middle half", "8 in 10", "19 in 20"].map((t, i) =>
          el("th", { class: i ? "num" : null, scope: "col" }, t)))),
        el("tbody", {},
          el("tr", {}, el("td", {}, `Average pace (per ${unitName()})`), el("td", { class: "num" }, el("b", {}, pf(p[M]))),
            el("td", { class: "num" }, range(p, lo50, hi50, pf)), el("td", { class: "num" }, range(p, lo80, hi80, pf)),
            el("td", { class: "num" }, range(p, lo95, hi95, pf))),
          el("tr", {}, el("td", {}, `${unitName()} a week, if still running`), el("td", { class: "num" }, el("b", {}, kf(k[M]))),
            el("td", { class: "num" }, range(k, lo50, hi50, kf)), el("td", { class: "num" }, range(k, lo80, hi80, kf)),
            el("td", { class: "num" }, range(k, lo95, hi95, kf)))));
      const f = res.features;
      const inRange = (sec) => sec / 60 >= data.tanda_valid_lo && sec / 60 <= data.tanda_valid_hi;
      out.replaceChildren(...[
        el("p", { class: "rc-own" }, `In the ${data.target_weeks} weeks to ${longDate(res.target_end)}: most likely `
          + `${fmtPace(p[M])} on average and ${fmtDist(k[M])} a week. Chance you're still running then: `
          + `${Math.round(res.p_running * 100)}%.`),
        el("div", { class: "table-wrap" }, table),
        el("p", {}, `Now (last ${data.recent_weeks} weeks): ${fmtDist(res.km_now)} a week at ${fmtPace(res.pace_now)}; `
          + `you ran in ${f.base.run_weeks} of the last ${f.base.weeks} weeks.`
          + (f.n < data.base_weeks ? ` Your log covers only ${f.n} weeks, so the ranges are probably too narrow.` : "")
          + (f.missing ? ` ${f.missing} week${f.missing === 1 ? " was" : "s were"} left out: the pace or distance doesn't look like running.` : "")
          + (res.ignored ? ` ${res.ignored} entr${res.ignored === 1 ? "y is" : "ies are"} older than ${data.lookback_weeks} weeks or after today and not used.` : "")),
        el("p", { class: "note" }, `Marathon time from your training (Tanda's 2011 formula): ${clock(res.tanda_now)} now, `
          + `${clock(res.tanda_target)} at the forecast. From a published formula fitted on 22 marathoners; we could not `
          + "check it on our data (it has no race results)"
          + (inRange(res.tanda_now) ? "." : ", and your time is outside the 2:47-3:36 range it was made for, so treat it as a rough guess.")),
        recentWeeks(f, today),
      ]);
    }

    function recentWeeks(f, today) {
      const n = Math.min(f.weekly.length, data.base_weeks);
      const rows = [];
      for (let i = 0; i < n; i++) {
        const kBack = i, [km, mins] = f.weekly[f.weekly.length - 1 - i];
        const end = today - 1 - 7 * kBack;
        rows.push(el("tr", {}, el("td", {}, `${longDate(isoOf(end - 6))} - ${longDate(isoOf(end))}`),
          el("td", { class: "num" }, km === null ? "left out" : dist(km).toFixed(1)),
          el("td", { class: "num" }, km ? clock(paceIn(mins * 60 / km)) : "")));
      }
      return el("details", {}, el("summary", {}, `Your last ${n} weeks, as the forecast sees them`),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ["Week", unitName(), `Pace per ${unitName()}`].map((t, i) =>
            el("th", { class: i ? "num" : null, scope: "col" }, t)))),
          el("tbody", {}, rows))));
    }

    const PAGE = 15;
    function drawLog() {
      distLabel.textContent = `Distance (${unitName()})`;
      const list = state.showAll ? state.entries : state.entries.slice(0, PAGE);
      if (!state.entries.length) { logBox.replaceChildren(el("p", { class: "note" }, "Your log is empty.")); return; }
      const rows = list.map((e) => {
        const i = state.entries.indexOf(e);
        return el("tr", {}, el("td", {}, e.date), el("td", {}, e.type === "week" ? "Week total" : "Run"),
          el("td", { class: "num" }, dist(e.km).toFixed(2)), el("td", { class: "num" }, clock(e.minutes * 60)),
          el("td", { class: "num" }, clock(paceIn(e.minutes * 60 / e.km))), el("td", {}, e.note),
          el("td", {},
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Edit ${e.date}`, onclick: () => {
              state.editing = i;
              fDate.value = e.date; fDist.value = dist(e.km).toFixed(2); fTime.value = clock(e.minutes * 60);
              fType.value = e.type; fNote.value = e.note;
              saveBtn.textContent = "Save changes"; cancelBtn.hidden = false;
              fDist.focus();
            } }, "Edit"), " ",
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Delete ${e.date}`, onclick: () => {
              state.entries.splice(i, 1);
              if (state.editing !== null) resetForm();
              persist();
              drawAll();
            } }, "Delete")));
      });
      logBox.replaceChildren(
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ["Date", "What", unitName(), "Time", `Pace / ${unitName()}`, "Note", ""].map((t, i) =>
            el("th", { class: i >= 2 && i <= 4 ? "num" : null, scope: "col" }, t)))),
          el("tbody", {}, rows))),
        state.entries.length > PAGE ? el("button", { type: "button", class: "ss-btn", onclick: () => { state.showAll = !state.showAll; drawLog(); } },
          state.showAll ? "Show fewer" : `Show all ${state.entries.length}`) : null);
    }

    function drawAll() {
      storageMsg.textContent = state.storageOk ? "" : "This browser isn't letting the page save (private mode or full storage): "
        + "your log will be lost when you close the page. Export it to keep a copy.";
      drawLog();
      drawForecast();
    }

    resetForm();
    host.replaceChildren(
      el("div", { class: "rc-form" }, settings),
      out,
      el("h3", {}, "Your log"),
      el("div", { class: "rc-form" }, form, formMsg, tools, impBox),
      storageMsg,
      logBox);   // the view's note under the tool says the log stays in this browser
    drawAll();
  }

  const api = {
    compute, weeklyTotals, summarise, parseCSV, parseNumber, parseMinutes, parseDate, importCSV, importJSON,
    detectCSV, mergeEntries, exportCSV, validEntry, dayOf, isoOf, mount,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests (node)
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).running_progress = api;
})();
