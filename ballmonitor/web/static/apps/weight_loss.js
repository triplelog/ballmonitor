// Weight loss planner (the weight_loss page's "app" view): a weigh-in log kept in this browser
// plus a projection of the visitor's weight to a target date.
//
// compute() is a line-by-line copy of models/weight_loss/model.py (method hall2011): _person,
// _plan, _simulate_hall (RK4), _fit (1-D Gauss-Newton adherence fit), the bands, _goal_intake,
// _maintenance_change and _linear_terms, plus the config formulas rmr, initial_fat,
// energy_partition and activity_coefficient (site.COPIED_FORMULAS stops the build if they
// change). Every number comes from the model's config, written into the page by site.py.
// tests/test_weight_loss_app.py runs this file under node against model.predict.
//
// The log is stored only in this browser (localStorage, key data.storage_key); this file makes no
// network requests. Storage format (shared by the progress-model apps, for a future upload):
//   {"model": "weight_loss", "version": 1, "updated": ISO datetime, "settings": {...},
//    "entries": [{"date": "YYYY-MM-DD", "weight": number, "unit": "kg" | "lb"}]}
// settings: units ("kg"|"lb", for start_weight, goal_weight and the display), sex ("M"|"F"), age,
// height_cm, start_weight, body_fat_pct (or null), activity ("sedentary"|"active"|"vigorous"),
// intake_change (kcal/day), activity_change_pct, start_date, target_date, goal_weight (or null).
"use strict";

(function () {
  const DAY_MS = 86400000;
  const SEXES = { m: true, male: true, man: true, f: false, female: false, woman: false };

  class InputError extends Error {}
  function fail(msg) { throw new InputError(msg); }

  // ── dates (UTC calendar days) ────────────────────────────────────────────────
  function parseISO(s) {
    if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
    const t = Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
    return new Date(t).toISOString().slice(0, 10) === s ? t : null;
  }
  function dateOf(inputs, key) {
    if (!(key in inputs) || inputs[key] === null || inputs[key] === undefined || inputs[key] === "") fail(`missing ${key.replace("_", " ")}`);
    const t = parseISO(String(inputs[key]).trim());
    if (t === null) fail(`${key.replace("_", " ")} must be a date YYYY-MM-DD`);
    return t;
  }
  function addDays(iso, n) { return new Date(parseISO(iso) + n * DAY_MS).toISOString().slice(0, 10); }
  function todayISO() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function num(inputs, key, dflt) {
    const v = inputs[key];
    if (v === undefined || v === null || v === "") {
      if (dflt === undefined) fail(`missing ${key.replace(/_/g, " ")}`);
      return dflt;
    }
    if (typeof v === "boolean") fail(`${key} must be a number`);
    const out = Number(v);
    if (!Number.isFinite(out)) fail(`${key.replace(/_/g, " ")} must be a number`);
    return out;
  }

  // ── the model (model.py) ─────────────────────────────────────────────────────
  function person(P, inputs, toKg) {
    const sex = String(inputs.sex ?? "").trim().toLowerCase();
    if (!(sex in SEXES)) fail("sex must be M or F");
    const male = SEXES[sex] ? 1 : 0;
    const age = num(inputs, "age");
    if (age < P.min_age) fail(`age must be at least ${P.min_age}`);
    let heightCm;
    if (inputs.height_cm !== undefined && inputs.height_cm !== null && inputs.height_cm !== "") heightCm = num(inputs, "height_cm");
    else if (inputs.height_in !== undefined && inputs.height_in !== null && inputs.height_in !== "") heightCm = num(inputs, "height_in") * CM_PER_INCH;
    else fail("give your height");
    if (heightCm <= 0) fail("height must be positive");
    const weight0 = num(inputs, "weight") * toKg;
    if (weight0 <= 0) fail("weight must be positive");
    const heightM = heightCm / 100;
    let fat0, fatSource;
    if (inputs.body_fat_pct !== undefined && inputs.body_fat_pct !== null && inputs.body_fat_pct !== "") {
      const pct = num(inputs, "body_fat_pct");
      if (!(pct > 0 && pct < 100)) fail("body fat % must be between 0 and 100");
      fat0 = weight0 * pct / 100;
      fatSource = "measured";
    } else {   // formula initial_fat (Jackson et al., Hall 2011 appendix eq. 4)
      fat0 = weight0 / 100 * (0.14 * age + (male ? 37.31 * Math.log(weight0 / heightM ** 2) - 103.94
        : 39.96 * Math.log(weight0 / heightM ** 2) - 102.01));
      fatSource = "estimated";
    }
    const leanFixed = (1 + P.glycogen_water_ratio) * P.glycogen_init_kg;
    if (!(fat0 > 0 && fat0 < weight0 - leanFixed)) fail("the estimated body fat is impossible for this height and weight: check them or enter a body fat %");
    const key = `pal_${String(inputs.activity ?? "sedentary").trim().toLowerCase()}`;
    if (!(key in P)) fail("activity must be sedentary, active or vigorous");
    const pal = P[key];
    const rmr = 9.99 * weight0 + 6.25 * heightCm - 4.92 * age + (male ? 5 : -161);   // formula rmr (Mifflin-St Jeor)
    const ei0 = pal * rmr;
    const delta0 = ((1 - P.beta_tef) * pal - 1) * rmr / weight0;                       // formula activity_coefficient
    return { male, age, heightCm, weight0, fat0, pal, rmr, ei0, delta0, fatSource };
  }

  function plan(P, inputs, ps) {
    const intakeChange = num(inputs, "intake_change", 0);
    const activityPct = num(inputs, "activity_change_pct", 0);
    const exercise = num(inputs, "exercise_kcal", 0);
    const delta1 = ps.delta0 * (1 + activityPct / 100) + exercise / ps.weight0;
    if (delta1 < 0) fail("the activity change makes physical activity negative");
    if (ps.ei0 + intakeChange <= 0) fail(`that intake change leaves no food: you maintain on about ${Math.round(ps.ei0)} calories a day`);
    let carb = P.baseline_carb_fraction;
    if (inputs.carb_pct_after !== undefined && inputs.carb_pct_after !== null && inputs.carb_pct_after !== "") {
      carb = num(inputs, "carb_pct_after") / 100;
      if (!(carb > 0 && carb <= 1)) fail("carb % must be between 0 and 100");
    }
    const sodium = num(inputs, "sodium_change_mg", 0);
    return { delta1, carb, sodium, intakeChange };
  }

  // (weight kg, fat kg) for day 0..days with a constant intake change dEI (model._simulate_hall)
  function simulate(P, ps, pl, dEI, days) {
    const rhoF = P.rho_fat, rhoL = P.rho_lean, rhoG = P.rho_glycogen, etaF = P.eta_fat, etaL = P.eta_lean;
    const g0 = P.glycogen_init_kg, hyd = 1 + P.glycogen_water_ratio;
    const ei = ps.ei0 + dEI;
    const ciB = P.baseline_carb_fraction * ps.ei0;
    const ci = pl.carb * ei;
    const kG = ciB / g0 ** 2;
    const tef = P.beta_tef * dEI, atTarget = P.beta_at * dEI;
    const w0 = ps.weight0, f0 = ps.fat0;
    const C = P.forbes_c_kg * P.rho_lean / P.rho_fat;
    function deriv(s) {
      const [fat, dLean, gly, dEcf, at] = s;
      if (fat <= 0) fail("the plan drives body fat to zero before the target date; the model does not apply");
      const bw = w0 + (fat - f0) + dLean + hyd * (gly - g0) + dEcf;
      const share = C / (C + fat);                                                   // formula energy_partition
      const dg = (ci - kG * gly ** 2) / rhoG;
      const decf = (pl.sodium - P.xi_na * dEcf - P.xi_ci * (1 - ci / ciB)) / P.sodium_conc;
      const x = share * etaL / rhoL + (1 - share) * etaF / rhoF;
      const ee = (ps.ei0 + P.gamma_fat * (fat - f0) + P.gamma_lean * dLean
        + pl.delta1 * bw - ps.delta0 * w0 + tef + at + (ei - rhoG * dg) * x) / (1 + x);
      const imbalance = ei - ee - rhoG * dg;
      return [(1 - share) * imbalance / rhoF, share * imbalance / rhoL, dg, decf, (atTarget - at) / P.tau_at_days];
    }
    const h = 1 / P.steps_per_day;
    let state = [f0, 0, g0, 0, 0];
    const out = [[w0, f0]];
    for (let d = 0; d < days; d++) {
      for (let k = 0; k < P.steps_per_day; k++) {
        const k1 = deriv(state);
        const k2 = deriv(state.map((a, i) => a + h / 2 * k1[i]));
        const k3 = deriv(state.map((a, i) => a + h / 2 * k2[i]));
        const k4 = deriv(state.map((a, i) => a + h * k3[i]));
        state = state.map((a, i) => a + h / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]));
      }
      out.push([w0 + (state[0] - f0) + state[1] + hyd * (state[2] - g0) + state[3], state[0]]);
    }
    return out;
  }

  function linearTerms(P, ps, pl, dEI) {   // model._linear_terms (appendix eqs. 10-17)
    const alpha = P.forbes_c_kg / ps.fat0;
    const beta = P.beta_tef + P.beta_at;
    const dDelta = pl.delta1 - ps.delta0;
    const density = (P.eta_fat + P.rho_fat + alpha * (P.eta_lean + P.rho_lean)) / (1 + alpha);
    const slope = (P.gamma_fat + alpha * P.gamma_lean) / (1 + alpha) + pl.delta1;
    return { alpha, tau: density / slope, dbw_ss: ((1 - beta) * dEI - dDelta * ps.weight0) / slope };
  }

  function fit(P, ps, pl, priorMean, priorSd, obs, days) {   // model._fit
    const varW = P.weighin_sd_kg ** 2;
    let x = priorMean, precision = 1 / priorSd ** 2;
    for (let it = 1; it <= P.fit_iterations; it++) {
      const base = simulate(P, ps, pl, x, days), bumped = simulate(P, ps, pl, x + P.fit_step_kcal, days);
      let grad = -(x - priorMean) / priorSd ** 2;
      precision = 1 / priorSd ** 2;
      for (const [t, w] of obs) {
        const j = (bumped[t][0] - base[t][0]) / P.fit_step_kcal;
        grad += j * (w - base[t][0]) / varW;
        precision += j * j / varW;
      }
      const step = grad / precision;
      x += step;
      if (Math.abs(step) < P.fit_step_kcal / 100) break;
    }
    return [x, 1 / Math.sqrt(precision)];
  }

  function goalIntake(P, ps, pl, goal, days) {   // model._goal_intake (secant)
    let a = 0, b = -ps.ei0 / 4;
    let fa = simulate(P, ps, pl, a, days)[days][0] - goal;
    let fb = simulate(P, ps, pl, b, days)[days][0] - goal;
    for (let i = 0; i < P.goal_iterations; i++) {
      if (Math.abs(fb) < P.goal_tolerance_kg || fb === fa) break;
      const next = b - fb * (b - a) / (fb - fa);
      a = b; fa = fb; b = Math.max(next, -ps.ei0);
      fb = simulate(P, ps, pl, b, days)[days][0] - goal;
    }
    return b;
  }

  function maintenanceChange(P, ps, pl, weight, fat) {   // model._maintenance_change
    const dFfm = weight - fat - (ps.weight0 - ps.fat0);
    const beta = P.beta_tef + P.beta_at;
    return (P.gamma_fat * (fat - ps.fat0) + P.gamma_lean * dFfm + pl.delta1 * weight - ps.delta0 * ps.weight0) / (1 - beta);
  }

  let CM_PER_INCH = 2.54;   // replaced by data.cm_per_inch in compute()

  // inputs: the same dict model.predict takes (sex, age, height_cm|height_in, weight, units,
  // body_fat_pct, activity, intake_change, activity_change_pct, exercise_kcal, start_date,
  // target_date, goal_weight, weighins [{date, weight}]). Returns model.predict's extras (kg,
  // kcal/day) plus weekly rows, or {error}.
  function compute(data, inputs) {
    try { return run(data, inputs); } catch (e) {
      if (e instanceof InputError) return { error: e.message };
      throw e;
    }
  }

  function run(data, inputs) {
    const P = data.params;
    CM_PER_INCH = data.cm_per_inch;
    const unit = String(inputs.units ?? "kg").trim().toLowerCase();
    if (unit !== "kg" && unit !== "lb") fail("units must be kg or lb");
    const toKg = unit === "lb" ? data.kg_per_lb : 1;
    const start = dateOf(inputs, "start_date"), target = dateOf(inputs, "target_date");
    const days = Math.round((target - start) / DAY_MS);
    if (days <= 0) fail("the target date must be after the start date");
    if (days > P.max_horizon_days) fail(`the target date is more than ${P.max_horizon_days} days after the start date`);
    const ps = person(P, inputs, toKg);
    const pl = plan(P, inputs, ps);
    const planned = pl.intakeChange;

    const activityKcal = (pl.delta1 - ps.delta0) * ps.weight0;
    const plannedTotal = planned - activityKcal;
    const priorMean = P.adherence_mean * plannedTotal + activityKcal;
    const priorSd = Math.hypot(P.adherence_sd * plannedTotal, P.intake_sd_floor);
    if (priorSd <= 0) fail("no uncertainty to work with");

    const obs = [];
    for (const row of inputs.weighins || []) {
      const when = dateOf(row, "date");
      const t = Math.round((when - start) / DAY_MS);
      if (t < 0) fail(`a weigh-in (${row.date}) is before the start date`);
      const w = num(row, "weight") * toKg;
      if (w <= 0) fail("weigh-in weights must be positive");
      obs.push([t, w]);
    }
    const horizon = Math.max(days, ...obs.map((o) => o[0]));
    let mean = priorMean, sd = priorSd;
    if (obs.length) [mean, sd] = fit(P, ps, pl, priorMean, priorSd, obs, horizon);

    const median = simulate(P, ps, pl, mean, horizon);
    const runs = {};
    for (const level of data.levels) {
      const z = data.z[String(level)];
      runs[level] = [simulate(P, ps, pl, mean - z * sd, days), simulate(P, ps, pl, mean + z * sd, days)];
    }
    function band(day, level) {
      const z = data.z[String(level)];
      const med = median[day][0], low = runs[level][0][day][0], high = runs[level][1][day][0];
      const noise = day > 0 ? z * P.weighin_sd_kg : 0;
      return [med - Math.hypot(med - low, noise), med + Math.hypot(high - med, noise)];
    }
    const [wT, fatT] = median[days];
    const bands = {};
    for (const level of data.levels) bands[String(level)] = band(days, level);
    const lin = linearTerms(P, ps, pl, mean);
    const adherence = obs.length && Math.abs(plannedTotal) > 0 ? (mean - activityKcal) / plannedTotal : null;

    const out = {
      weight_kg: wT, fat_kg: fatT, bands_kg: bands, maintenance_kcal: ps.ei0, planned_kcal: ps.ei0 + planned,
      effective_change_kcal: mean, effective_change_sd: sd, prior_change_kcal: priorMean, adherence,
      tau_days: lin.tau, eventual_change_kg: lin.dbw_ss, fat0_kg: ps.fat0, weight0_kg: ps.weight0, days,
      trajectory_kg: median.slice(0, days + 1).map((r) => r[0]), fat_source: ps.fatSource, n_weighins: obs.length,
    };
    if (inputs.goal_weight !== undefined && inputs.goal_weight !== null && inputs.goal_weight !== "") {
      const goal = num(inputs, "goal_weight") * toKg;
      if (goal <= 0) fail("the goal weight must be positive");
      const dGoal = goalIntake(P, ps, pl, goal, days);
      const [reached, reachedFat] = simulate(P, ps, pl, dGoal, days)[days];
      out.goal_intake = ps.ei0 + dGoal;
      out.goal_maintenance_intake = ps.ei0 + maintenanceChange(P, ps, pl, reached, reachedFat);
      out.goal_reached_kg = reached;
      out.goal_ok = Math.abs(reached - goal) < Math.max(P.goal_tolerance_kg * 10, 0.1);
    }
    // weekly rows, as the model's trajectory table
    const weeks = [];
    for (let d = 0; d <= days; d += data.days_per_week) weeks.push(d);
    const stride = Math.max(1, Math.ceil(weeks.length / P.trajectory_max_rows));
    const rowDays = weeks.filter((_, i) => i % stride === 0);
    if (rowDays[rowDays.length - 1] !== days) rowDays.push(days);
    out.rows = rowDays.map((d) => {
      const [lo, hi] = band(d, data.headline_level);
      return { day: d, weight: median[d][0], low: lo, high: hi, fat: median[d][1] };
    });
    out.chart = [];
    const step = Math.max(1, Math.ceil(days / 150));
    for (let d = 0; d <= days; d += step) out.chart.push([d, median[d][0], ...band(d, data.headline_level)]);
    if (out.chart[out.chart.length - 1][0] !== days) out.chart.push([days, median[days][0], ...band(days, data.headline_level)]);
    return out;
  }

  // ── the log: storage, import, export ─────────────────────────────────────────
  const SETTING_KEYS = ["units", "sex", "age", "height_cm", "start_weight", "body_fat_pct", "activity",
    "intake_change", "activity_change_pct", "start_date", "target_date", "goal_weight"];

  function toKgOf(unit, data) { return unit === "lb" ? data.kg_per_lb : 1; }

  // One weigh-in from untrusted input -> {date, weight, unit} or an error string.
  function cleanEntry(data, raw, fallbackUnit) {
    if (!raw || typeof raw !== "object") return "not a weigh-in";
    const date = parseDate(raw.date);
    if (!date) return `date ${JSON.stringify(String(raw.date ?? "")).slice(0, 40)} is not a date (use YYYY-MM-DD)`;
    const unit = raw.unit === undefined || raw.unit === null || raw.unit === "" ? fallbackUnit : parseUnit(raw.unit);
    if (!unit) return `unit ${JSON.stringify(String(raw.unit)).slice(0, 20)} must be kg or lb`;
    const weight = parseNumber(raw.weight);
    if (weight === null) return `weight ${JSON.stringify(String(raw.weight ?? "")).slice(0, 20)} is not a number`;
    const kg = weight * toKgOf(unit, data);
    if (kg < data.params.site_min_weight_kg || kg > data.params.site_max_weight_kg) return `weight ${weight} ${unit} is out of range`;
    return { date, weight, unit };
  }

  function parseUnit(u) {
    const s = String(u).trim().toLowerCase();
    if (/^(kg|kgs|kilo|kilos|kilograms?)$/.test(s)) return "kg";
    if (/^(lb|lbs|pounds?)$/.test(s)) return "lb";
    return null;
  }

  function parseNumber(v) {
    if (typeof v === "number") return Number.isFinite(v) ? v : null;
    const s = String(v ?? "").trim().replace(/^(\d+),(\d+)$/, "$1.$2");
    if (!/^\d+(\.\d+)?$/.test(s)) return null;
    return Number(s);
  }

  // ISO (optionally with a time after it), YYYY/MM/DD or M/D/YYYY (US order) -> YYYY-MM-DD
  function parseDate(v) {
    const s = String(v ?? "").trim();
    let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$/);
    if (m) return isoOrNull(m[1], m[2], m[3]);
    m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?: .*)?$/);
    if (m) return isoOrNull(m[3], m[1], m[2]);
    return null;
  }
  function isoOrNull(y, mo, d) {
    const iso = `${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    return parseISO(iso) === null ? null : iso;
  }

  function cleanSettings(data, raw) {
    const s = {};
    if (!raw || typeof raw !== "object") return s;
    for (const k of SETTING_KEYS) {
      const v = raw[k];
      if (v === undefined) continue;
      if (k === "units") { if (v === "kg" || v === "lb") s[k] = v; }
      else if (k === "sex") { if (v === "M" || v === "F") s[k] = v; }
      else if (k === "activity") { if (["sedentary", "active", "vigorous"].includes(v)) s[k] = v; }
      else if (k === "start_date" || k === "target_date") { if (parseISO(v) !== null) s[k] = v; }
      else if (v === null || v === "") { if (k === "body_fat_pct" || k === "goal_weight") s[k] = null; }
      else if (typeof v === "number" && Number.isFinite(v)) s[k] = v;
    }
    return s;
  }

  // CSV text -> rows of cells (quotes, commas or semicolons)
  function parseCSV(text) {
    const first = text.split(/\r?\n/, 1)[0] || "";
    const sep = first.includes(";") && !first.includes(",") ? ";" : first.includes("\t") && !first.includes(",") ? "\t" : ",";
    const rows = [];
    let row = [], cell = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (c === '"') quoted = false;
        else cell += c;
      } else if (c === '"') quoted = true;
      else if (c === sep) { row.push(cell); cell = ""; }
      else if (c === "\n" || c === "\r") {
        if (c === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); rows.push(row); row = []; cell = "";
      } else cell += c;
    }
    if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
    return rows.filter((r) => r.some((x) => x.trim() !== ""));
  }

  // Any file -> {entries, settings, errors}. JSON: the shared log object or a bare list of
  // weigh-ins. CSV: a header row with a date column and a weight column (unit from a unit column,
  // the weight header ("Weight (lb)") or the page's current unit).
  function parseImport(data, text, fallbackUnit) {
    const errors = [], entries = [];
    let settings = {};
    const trimmed = text.replace(/^﻿/, "").trim();
    if (!trimmed) return { entries, settings, errors: ["the file is empty"] };
    if (trimmed[0] === "{" || trimmed[0] === "[") {
      let obj;
      try { obj = JSON.parse(trimmed); } catch (e) { return { entries, settings, errors: ["the file is not valid JSON"] }; }
      let list = obj;
      if (!Array.isArray(obj)) {
        if (obj.model !== undefined && obj.model !== data.model) return { entries, settings, errors: [`this is a log for another page (${String(obj.model).slice(0, 40)})`] };
        if (obj.version !== undefined && obj.version !== 1) return { entries, settings, errors: [`unknown log version ${String(obj.version).slice(0, 10)}`] };
        list = Array.isArray(obj.entries) ? obj.entries : [];
        settings = cleanSettings(data, obj.settings);
      }
      list.forEach((raw, i) => {
        const e = cleanEntry(data, raw, settings.units || fallbackUnit);
        if (typeof e === "string") errors.push(`Entry ${i + 1}: ${e}`); else entries.push(e);
      });
      return { entries, settings, errors };
    }
    const rows = parseCSV(trimmed);
    const head = (rows.shift() || []).map((h) => h.trim().toLowerCase());
    const di = head.findIndex((h) => /date|day|time/.test(h));
    const wi = head.findIndex((h) => /weight|mass/.test(h) || /^(kg|lb|lbs)$/.test(h));
    const ui = head.findIndex((h) => /^unit/.test(h));
    if (di < 0 || wi < 0) return { entries, settings, errors: ["the CSV needs a header row with a date column and a weight column"] };
    const headUnit = /\b(lb|lbs|pounds?)\b/.test(head[wi]) ? "lb" : /\b(kg|kgs|kilograms?)\b/.test(head[wi]) ? "kg" : null;
    rows.forEach((r, i) => {
      const e = cleanEntry(data, { date: r[di], weight: r[wi], unit: ui >= 0 ? r[ui] : headUnit }, headUnit || fallbackUnit);
      if (typeof e === "string") errors.push(`Row ${i + 2}: ${e}`); else entries.push(e);
    });
    return { entries, settings, errors };
  }

  // merge by date: an imported weigh-in replaces the log's weigh-in on the same date
  function mergeEntries(old, add) {
    const byDate = new Map(old.map((e) => [e.date, e]));
    for (const e of add) byDate.set(e.date, e);
    return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  }

  function toCSV(entries) {
    return ["date,weight,unit", ...entries.map((e) => `${e.date},${e.weight},${e.unit}`)].join("\n") + "\n";
  }

  // settings + entries -> model inputs (weigh-ins before the start date are kept in the log, not used)
  function inputsFrom(data, settings, entries) {
    const u = settings.units, inU = (e) => e.weight * toKgOf(e.unit, data) / toKgOf(u, data);
    const used = entries.filter((e) => settings.start_date && e.date >= settings.start_date);
    return {
      sex: settings.sex, age: settings.age, height_cm: settings.height_cm, weight: settings.start_weight, units: u,
      body_fat_pct: settings.body_fat_pct, activity: settings.activity, intake_change: settings.intake_change,
      activity_change_pct: settings.activity_change_pct, start_date: settings.start_date, target_date: settings.target_date,
      goal_weight: settings.goal_weight, weighins: used.map((e) => ({ date: e.date, weight: inU(e) })),
    };
  }

  // ── the page ─────────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const P = data.params;
    let storageOk = true;
    const state = load();

    function blankLog() {
      const start = todayISO();
      return { settings: { ...data.example, start_date: start, target_date: addDays(start, P.site_default_weeks * data.days_per_week) },
        entries: [] };
    }
    function load() {
      let raw = null;
      try { raw = localStorage.getItem(data.storage_key); } catch (e) { storageOk = false; }
      const log = blankLog();
      if (!raw) return log;
      try {
        const obj = JSON.parse(raw);
        Object.assign(log.settings, cleanSettings(data, obj.settings));
        log.entries = mergeEntries([], (Array.isArray(obj.entries) ? obj.entries : [])
          .map((e) => cleanEntry(data, e, log.settings.units)).filter((e) => typeof e !== "string"));
      } catch (e) { /* unreadable: start fresh, keep the old value until the next save */ }
      return log;
    }
    function snapshot() {
      return { model: data.model, version: 1, updated: new Date().toISOString(), settings: state.settings, entries: state.entries };
    }
    function save() {
      try { localStorage.setItem(data.storage_key, JSON.stringify(snapshot())); storageOk = true; } catch (e) { storageOk = false; }
      storageNote.hidden = storageOk;
    }

    const S = state.settings;
    const unitLabel = () => S.units;
    const fromKg = (kg) => kg / toKgOf(S.units, data);
    const w1 = (kg) => fromKg(kg).toFixed(1);
    const kcal = (x) => Math.round(x).toLocaleString("en-US");

    // settings form
    function field(label, input, hint) {
      return el("label", { class: "wl-field" }, el("span", { class: "rc-lbl" }, label), input, hint ? el("small", {}, hint) : null);
    }
    function numberInput(key, attrs, conv) {
      const c = conv || { show: (v) => v, keep: (v) => v };
      return el("input", { type: "number", inputmode: "decimal", value: S[key] === null || S[key] === undefined ? "" : String(round(c.show(S[key]))), ...attrs,
        oninput: (e) => { const v = e.target.value.trim(); S[key] = v === "" ? null : c.keep(Number(v)); changed(); } });
    }
    function round(v) { return typeof v === "number" ? Math.round(v * 10) / 10 : v; }
    function select(key, options) {
      return el("select", { onchange: (e) => { S[key] = e.target.value; changed(); } },
        options.map(([v, label]) => el("option", { value: v, ...(v === S[key] ? { selected: "" } : {}) }, label)));
    }
    function dateInput(key) {
      return el("input", { type: "date", value: S[key] || "", onchange: (e) => { S[key] = e.target.value; changed(); } });
    }
    function heightInputs() {
      if (S.units === "lb") {
        const totalIn = (S.height_cm || 0) / data.cm_per_inch;
        const ft = el("input", { type: "number", min: "3", max: "8", value: S.height_cm ? String(Math.floor(totalIn / 12)) : "", "aria-label": "Height, feet", class: "wl-short" });
        const inch = el("input", { type: "number", min: "0", max: "11.9", step: "0.5", value: S.height_cm ? String(Math.round((totalIn % 12) * 2) / 2) : "", "aria-label": "Height, inches", class: "wl-short" });
        const upd = () => { const f = Number(ft.value), i = Number(inch.value || 0); S.height_cm = ft.value === "" ? null : (f * 12 + i) * data.cm_per_inch; changed(); };
        ft.oninput = upd; inch.oninput = upd;
        return el("span", { class: "wl-pair" }, ft, " ft ", inch, " in");
      }
      return el("span", {}, numberInput("height_cm", { min: "100", max: "250", "aria-label": "Height, cm", class: "wl-short" }), " cm");
    }

    const form = el("div", { class: "wl-form" });
    function drawForm() {
      form.replaceChildren(
        field("Units", unitSelect()),
        field("Sex", select("sex", [["F", "Female"], ["M", "Male"]])),
        field("Age", numberInput("age", { min: String(P.min_age), max: "100", class: "wl-short" })),
        field("Height", heightInputs()),
        field(`Weight on start date (${unitLabel()})`, numberInput("start_weight", { min: "1", step: "0.1", class: "wl-short" })),
        field("Body fat % (optional)", numberInput("body_fat_pct", { min: "1", max: "80", step: "0.1", class: "wl-short", placeholder: "estimated" })),
        field("Activity now", select("activity", [["sedentary", "Mostly sitting"], ["active", "Active"], ["vigorous", "Very active"]])),
        field("Calories a day: change", numberInput("intake_change", { step: "50", class: "wl-short" }), "−500 = eat 500 fewer"),
        field("Activity: change %", numberInput("activity_change_pct", { step: "5", class: "wl-short" }), "+20 = 20% more"),
        field("Start date", dateInput("start_date")),
        field("Target date", dateInput("target_date")),
        field(`Goal weight (${unitLabel()}, optional)`, numberInput("goal_weight", { min: "1", step: "0.1", class: "wl-short" })),
      );
    }
    function unitSelect() {   // switching units converts the weights typed in settings (the log keeps each entry's unit)
      return el("select", { onchange: (e) => {
        const k = toKgOf(S.units, data) / toKgOf(e.target.value, data);
        for (const key of ["start_weight", "goal_weight"]) if (typeof S[key] === "number") S[key] = Math.round(S[key] * k * 10) / 10;
        S.units = e.target.value;
        drawForm(); changed();
      } }, [["lb", "Pounds"], ["kg", "Kilograms"]].map(([v, label]) => el("option", { value: v, ...(v === S.units ? { selected: "" } : {}) }, label)));
    }

    // the log
    const logBox = el("div", { class: "wl-log" });
    let editing = null;
    function drawLog() {
      const today = todayISO();
      const dIn = el("input", { type: "date", value: today, "aria-label": "Weigh-in date" });
      const wIn = el("input", { type: "number", inputmode: "decimal", step: "0.1", placeholder: unitLabel(), "aria-label": `Weight (${unitLabel()})`, class: "wl-short" });
      const msg = el("span", { class: "wl-msg", role: "status" });
      const add = () => {
        const e = cleanEntry(data, { date: dIn.value, weight: wIn.value, unit: S.units }, S.units);
        if (typeof e === "string") { msg.textContent = `Not added: ${e}.`; return; }
        state.entries = mergeEntries(state.entries, [e]);
        changed(); drawLog();
      };
      wIn.onkeydown = (ev) => { if (ev.key === "Enter") add(); };
      const rows = [...state.entries].reverse().map((e) => {
        if (editing === e.date) {
          const d2 = el("input", { type: "date", value: e.date, "aria-label": "Date" });
          const w2 = el("input", { type: "number", step: "0.1", value: String(e.weight), class: "wl-short", "aria-label": `Weight (${e.unit})` });
          const m2 = el("span", { class: "wl-msg" });
          return el("tr", {}, el("td", {}, d2), el("td", { class: "num" }, w2, ` ${e.unit}`),
            el("td", {}, el("button", { type: "button", class: "ss-btn rc-x", onclick: () => {
              const n = cleanEntry(data, { date: d2.value, weight: w2.value, unit: e.unit }, e.unit);
              if (typeof n === "string") { m2.textContent = n; return; }
              state.entries = mergeEntries(state.entries.filter((x) => x !== e), [n]);
              editing = null; changed(); drawLog();
            } }, "Save"), " ", el("button", { type: "button", class: "ss-btn rc-x", onclick: () => { editing = null; drawLog(); } }, "Cancel"), m2));
        }
        const before = S.start_date && e.date < S.start_date;
        return el("tr", { class: before ? "wl-unused" : null },
          el("td", {}, e.date, before ? el("small", {}, " (before start)") : null),
          el("td", { class: "num" }, `${e.weight} ${e.unit}`),
          el("td", {}, el("button", { type: "button", class: "ss-btn rc-x", onclick: () => { editing = e.date; drawLog(); } }, "Edit"), " ",
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Delete ${e.date}`, onclick: () => {
              state.entries = state.entries.filter((x) => x !== e); changed(); drawLog();
            } }, "Delete")));
      });
      logBox.replaceChildren(
        el("div", { class: "wl-add" }, field("Date", dIn), field(`Weight (${unitLabel()})`, wIn),
          el("button", { type: "button", class: "ss-btn", onclick: add }, "Add weigh-in"), msg),
        state.entries.length
          ? el("div", { class: "table-wrap wl-logtable" }, el("table", {},
            el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Date"), el("th", { scope: "col", class: "num" }, "Weight"), el("th", { scope: "col" }, ""))),
            el("tbody", {}, rows)))
          : el("p", { class: "note" }, "No weigh-ins yet. Add one each week or so (same time of day, same scale) and the planner learns how your plan is really going."));
    }

    // export / import / clear
    const importBox = el("div", { class: "wl-import", "aria-live": "polite" });
    const fileIn = el("input", { type: "file", accept: ".json,.csv,.txt,application/json,text/csv", hidden: "" });
    function download(name, text, type) {
      const url = URL.createObjectURL(new Blob([text], { type }));
      const a = el("a", { href: url, download: name });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    const stamp = () => todayISO();
    fileIn.onchange = () => {
      const f = fileIn.files && fileIn.files[0];
      fileIn.value = "";
      if (!f) return;
      if (f.size > 5e6) { importBox.replaceChildren(el("p", { class: "note" }, "That file is too big for a weigh-in log (over 5 MB).")); return; }
      const reader = new FileReader();
      reader.onload = () => offerImport(parseImport(data, String(reader.result), S.units));
      reader.onerror = () => importBox.replaceChildren(el("p", { class: "note" }, "Could not read that file."));
      reader.readAsText(f);
    };
    function offerImport(res) {
      const errs = res.errors.slice(0, 6).map((e) => el("li", {}, e));
      if (res.errors.length > 6) errs.push(el("li", {}, `…and ${res.errors.length - 6} more.`));
      const errBox = res.errors.length ? el("div", {}, el("p", {}, `${res.errors.length} row(s) could not be read and will be skipped:`), el("ul", {}, errs)) : null;
      if (!res.entries.length && !Object.keys(res.settings).length) {
        importBox.replaceChildren(...[el("p", {}, "Nothing to import."), errBox].filter(Boolean));
        return;
      }
      const apply = (replace) => {
        if (replace) { state.entries = mergeEntries([], res.entries); Object.assign(S, res.settings); }
        else state.entries = mergeEntries(state.entries, res.entries);
        importBox.replaceChildren(el("p", {}, `Imported ${res.entries.length} weigh-in(s).`));
        drawForm(); changed(); drawLog();
      };
      importBox.replaceChildren(...[
        el("p", {}, `Found ${res.entries.length} weigh-in(s)${Object.keys(res.settings).length ? " and your settings" : ""}.`),
        errBox,
        el("div", { class: "wl-tools" },
          state.entries.length ? el("button", { type: "button", class: "ss-btn", onclick: () => apply(false) }, "Add to my log") : null,
          el("button", { type: "button", class: "ss-btn", onclick: () => apply(true) }, state.entries.length ? "Replace my log" : "Import"),
          el("button", { type: "button", class: "ss-btn", onclick: () => importBox.replaceChildren() }, "Cancel"))].filter(Boolean));
    }
    const tools = el("div", { class: "wl-tools" },
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-${data.model}-log-${stamp()}.json`, JSON.stringify(snapshot(), null, 2), "application/json") }, "Export (JSON)"),
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-${data.model}-log-${stamp()}.csv`, toCSV(state.entries), "text/csv") }, "Export (CSV)"),
      el("button", { type: "button", class: "ss-btn", onclick: () => fileIn.click() }, "Import a file"),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!confirm("Delete your weigh-ins and settings from this browser? This cannot be undone (export first to keep a copy).")) return;
        try { localStorage.removeItem(data.storage_key); } catch (e) { storageOk = false; }
        const fresh = blankLog();
        state.entries = fresh.entries;
        for (const k of Object.keys(S)) delete S[k];
        Object.assign(S, fresh.settings);
        importBox.replaceChildren(el("p", {}, "Your log was cleared."));
        drawForm(); drawLog(); draw();
      } }, "Clear my log"),
      fileIn);

    // results
    const out = el("div", { class: "rc-out", "aria-live": "polite" });
    function draw() {
      if (!S.target_date && S.start_date) S.target_date = addDays(S.start_date, P.site_default_weeks * data.days_per_week);
      const inputs = inputsFrom(data, S, state.entries);
      for (const w of [S.start_weight, S.goal_weight]) {
        if (typeof w === "number") {
          const kg = w * toKgOf(S.units, data);
          if (kg < P.site_min_weight_kg || kg > P.site_max_weight_kg) { out.replaceChildren(el("p", { class: "note" }, "Check the weights: one is outside the range this page accepts.")); return; }
        }
      }
      const r = compute(data, inputs);
      if (r.error) { out.replaceChildren(el("p", { class: "note" }, `To see your projection: ${r.error}.`)); return; }
      const [lo, hi] = r.bands_kg[String(data.headline_level)];
      const [lo50, hi50] = r.bands_kg["0.5"], [lo95, hi95] = r.bands_kg["0.95"];
      const u = unitLabel();
      const change = fromKg(r.weight_kg - r.weight0_kg);
      const head = el("p", { class: "wl-head" }, `On ${S.target_date}: most likely `, el("b", {}, `${w1(r.weight_kg)} ${u}`),
        ` (${change <= 0 ? "down" : "up"} ${Math.abs(change).toFixed(1)} ${u}). 8 in 10 chance between ${w1(lo)} and ${w1(hi)} ${u}.`);
      const rows = [
        ["Middle half of the range", `${w1(lo50)} – ${w1(hi50)} ${u}`],
        ["Almost surely between (95%)", `${w1(lo95)} – ${w1(hi95)} ${u}`],
        ["Body fat on the target date", `${w1(r.fat_kg)} ${u} (${Math.round(100 * r.fat_kg / r.weight_kg)}% of weight; ${r.fat_source} today: ${w1(r.fat0_kg)} ${u})`],
        ["Calories a day that keep your weight steady now", kcal(r.maintenance_kcal)],
        ["Calories a day in your plan", kcal(r.planned_kcal)],
      ];
      if (r.n_weighins) rows.push(["Calories a day your weigh-ins point to", kcal(r.maintenance_kcal + r.effective_change_kcal)]);
      if (r.adherence !== null) rows.push(["Share of your planned change you are making", `${Math.round(100 * r.adherence)}%`]);
      rows.push(["If you kept this up for good", `${r.eventual_change_kg <= 0 ? "down" : "up"} about ${Math.abs(fromKg(r.eventual_change_kg)).toFixed(0)} ${u} in the long run (half of it in about ${Math.round(r.tau_days * Math.LN2 / 30.4)} months)`]);
      if (r.goal_intake !== undefined) {
        rows.push([`Calories a day to reach ${S.goal_weight} ${u} by ${S.target_date}`, r.goal_ok ? kcal(r.goal_intake) : "not reachable by that date"]);
        if (r.goal_ok) rows.push(["…and then to stay there", kcal(r.goal_maintenance_intake)]);
        if (r.goal_ok && r.goal_intake < 1200) rows.push(["Careful", "that is a very low intake: ask a doctor first"]);
      }
      const keyTable = el("div", { class: "table-wrap" }, el("table", {}, el("tbody", {}, rows.map(([a, b]) =>
        el("tr", {}, el("td", { class: "wl-k" }, a), el("td", { class: "num" }, b))))));
      const days = r.days;
      const chart = h.renderLine({
        title: "Your weight, most likely and 8-in-10 range",
        series: [{ name: "Most likely", points: r.chart.map((c) => [c[0] / data.days_per_week, fromKg(c[1])]),
          band: r.chart.map((c) => [c[0] / data.days_per_week, fromKg(c[2]), fromKg(c[3])]) }],
        x_label: "Weeks from the start date", y_label: `Weight (${u})`, x_fmt: "number", y_fmt: "number",
        markers: inputs.weighins.filter((w) => {
          const t = Math.round((parseISO(w.date) - parseISO(S.start_date)) / DAY_MS);
          return t <= days;
        }).map((w) => ({ x: Math.round((parseISO(w.date) - parseISO(S.start_date)) / DAY_MS) / data.days_per_week,
          y: w.weight, label: `${w.date}: ${w.weight} ${u}` })),
      });
      const weekly = el("details", { class: "wl-weekly" }, el("summary", {}, "Week by week"),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ["Week", "Date", "Most likely", "8 in 10 from", "to", "Body fat"].map((t, i) =>
            el("th", { scope: "col", class: i > 1 ? "num" : null }, t)))),
          el("tbody", {}, r.rows.map((row) => el("tr", {},
            el("td", {}, row.day % data.days_per_week ? (row.day / data.days_per_week).toFixed(1) : String(row.day / data.days_per_week)),
            el("td", {}, addDays(S.start_date, row.day)),
            el("td", { class: "num" }, el("b", {}, w1(row.weight))), el("td", { class: "num" }, w1(row.low)),
            el("td", { class: "num" }, w1(row.high)), el("td", { class: "num" }, w1(row.fat))))))));
      out.replaceChildren(...[head, keyTable, el("div", { class: "rc-chart" }, chart), weekly,
        r.n_weighins ? null : el("p", { class: "note" }, "The range allows for how well people stick to a plan. Log your weigh-ins and it narrows to how you are actually doing.")].filter(Boolean));
    }

    let timer = null;
    function changed() {
      save();
      clearTimeout(timer);
      timer = setTimeout(() => { drawLog(); draw(); }, 150);
    }

    const storageNote = el("p", { class: "note wl-warn", hidden: "" }, "This browser is not letting the page save (private mode or full storage): your log will be lost when you leave. Export it to keep a copy.");
    host.replaceChildren(
      el("h3", { class: "wl-h" }, "You and your plan"),
      el("p", { class: "note" }, "The values below start as an example: replace them with yours."),
      form,
      el("h3", { class: "wl-h" }, "Your weigh-ins"),
      logBox, tools, importBox,
      el("h3", { class: "wl-h" }, "Where your weight is heading"),
      out,
      storageNote,
      el("p", { class: "small wl-private" }, "Your log is saved only in this browser. Nothing is uploaded."),
      el("p", { class: "small" }, "Import: this page's own JSON or CSV export, or any CSV with a date column and a weight column. "
        + "Exports from Apple Health and smart scales are not supported yet."));
    drawForm(); drawLog(); draw();
    if (!storageOk) storageNote.hidden = false;
  }

  const api = { compute, simulate, parseImport, parseCSV, parseDate, mergeEntries, toCSV, inputsFrom, cleanSettings, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests (node)
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).weight_loss = api;
})();
