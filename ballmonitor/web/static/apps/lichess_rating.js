// Lichess rating log and forecast (the lichess_rating page's "app" view). The visitor keeps a log
// of rating snapshots in this browser and gets the model's forecast for a date they pick.
//
// predict() is a line-by-line copy of the lichess_rating model (models/lichess_rating: model.py
// predict, dist.py features / active_cdf / active_quantile / mixture_quantile / mixture_exceed,
// formula p_active in config.toml). Every number it uses comes from the model's config, written
// into the page by site.py at build time. tests/test_lichess_rating_app.py runs this file under node
// and checks it against the Python model, so a change to the model fails the tests until this copy
// is updated too.
//
// Storage (shared format of the progress-log apps): localStorage "bm.log.lichess_rating.v1" =
//   {model: "lichess_rating", version: 1, updated: ISO datetime,
//    settings: {speed, target_date, goal, keep_playing, username,
//               stats: {<speed>: {as_of, games_28, games_91, days_since, peak, rating_91, score_91, opp_avg}},
//               saved: [{made, from, speed, target, rating, median, low, high}]},
//    entries: [{date: "YYYY-MM-DD", speed, rating, games (rated games so far, or null), note}]}
// Nothing is uploaded. The one network call is the optional "Fill from my Lichess account" button,
// which asks lichess.org's public API (no login) for that username's ratings and recent games.
"use strict";

(function () {
  const SRC = { "data-src": "ballmonitor/web/static/apps/lichess_rating.js" };
  const DAY = 86400000;
  const SHOWN = [0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975];
  const BANDS = { 50: [0.25, 0.75], 80: [0.1, 0.9], 95: [0.025, 0.975] };
  const STAT_KEYS = ["games_28", "games_91", "days_since", "peak", "rating_91", "score_91", "opp_avg"];
  const CSV_COLUMNS = ["date", "speed", "rating", "games", "note"];

  // ── the model (dist.py + model.py) ─────────────────────────────────────────
  function features(data, v) {
    const caps = data.caps;
    const clip = (x, lim) => Math.max(-lim, Math.min(lim, x));
    let form = 0;
    if (v.games_91 && v.opp_avg !== null && v.opp_avg !== undefined && !Number.isNaN(v.opp_avg)) {
      const perf = v.opp_avg + 400 * (2 * v.score_91 / v.games_91 - 1);
      form = clip((perf - v.rating) / 100, caps.form);
    }
    return {
      activity: Math.log1p(v.games_28),
      experience: Math.log1p(Math.min(v.games_total, caps.games)),
      below_peak: Math.min(Math.max(v.peak - v.rating, 0) / 100, caps.below_peak),
      trend: clip((v.rating - v.rating_91) / 100, caps.trend),
      level: (v.rating - 1500) / 100,
      form,
      idle: Math.log1p(v.days_since),
      log_horizon: Math.log(v.horizon / 91),
    };
  }

  function tailScales(qs, levels) {
    const n = qs.length;
    const sLo = qs[1] > qs[0] ? (qs[1] - qs[0]) / Math.log(levels[1] / levels[0]) : 1;
    const sHi = qs[n - 1] > qs[n - 2] ? (qs[n - 1] - qs[n - 2]) / Math.log((1 - levels[n - 2]) / (1 - levels[n - 1])) : 1;
    return [sLo, sHi];
  }

  const sorted = (a) => [...a].sort((x, y) => x - y);

  function activeCdf(qValues, x, levels) {
    const qs = sorted(qValues), n = qs.length;
    const [sLo, sHi] = tailScales(qs, levels);
    if (x < qs[0]) return levels[0] * Math.exp((x - qs[0]) / sLo);
    if (x >= qs[n - 1]) return 1 - (1 - levels[n - 1]) * Math.exp(-(x - qs[n - 1]) / sHi);
    for (let i = 0; i < n - 1; i++) {
      if (qs[i] <= x && x < qs[i + 1]) return levels[i] + (levels[i + 1] - levels[i]) * (x - qs[i]) / (qs[i + 1] - qs[i]);
    }
    return levels[n - 1];
  }

  function activeQuantile(qValues, level, levels) {
    const qs = sorted(qValues), n = qs.length;
    const [sLo, sHi] = tailScales(qs, levels);
    if (level <= levels[0]) return qs[0] + sLo * Math.log(Math.max(level, 1e-12) / levels[0]);
    if (level >= levels[n - 1]) return qs[n - 1] - sHi * Math.log(Math.max(1 - level, 1e-12) / (1 - levels[n - 1]));
    for (let i = 0; i < n - 1; i++) {
      if (levels[i] <= level && level <= levels[i + 1]) return qs[i] + (qs[i + 1] - qs[i]) * (level - levels[i]) / (levels[i + 1] - levels[i]);
    }
    return qs[n - 1];
  }

  function mixtureQuantile(p, qValues, tau, levels) {
    const p0 = 1 - p;
    const below0 = p * activeCdf(qValues, -1e-9, levels);
    if (tau < below0) return activeQuantile(qValues, tau / p, levels);
    if (tau <= below0 + p0) return 0;
    return activeQuantile(qValues, (tau - p0) / p, levels);
  }

  function mixtureExceed(p, qValues, x, levels) {
    if (x < 0) throw new Error("mixtureExceed is for gains (x >= 0)");
    return p * (1 - activeCdf(qValues, x, levels));
  }

  // A number from the inputs (model.py _num): null/"" -> default; a missing required one is an error.
  function num(inp, key, label, dflt, lo = 0) {
    let v = inp[key];
    if (v === null || v === undefined || v === "") v = dflt;
    if (v === null || v === undefined || v === "") throw new Error(`${label} is needed.`);
    const x = Number(v);
    if (!Number.isFinite(x)) throw new Error(`${label} must be a number.`);
    if (lo !== null && x < lo) throw new Error(`${label} must be at least ${lo}.`);
    return x;
  }

  // inp: {rating, horizon (days), games_total, games_28, games_91?, days_since?, peak?, rating_91?,
  //       score_91?, opp_avg?, keep_playing?, goal?}. Same defaults and checks as model.py.
  function predict(data, inp) {
    const levels = data.levels;
    const rating = num(inp, "rating", "Your rating", null, 400);
    const horizon = Math.round(num(inp, "horizon", "Days ahead", null, null));
    if (horizon < 1) throw new Error("The target date must be after the date of your latest rating.");
    const gamesTotal = num(inp, "games_total", "Rated games so far", null);
    const games28 = num(inp, "games_28", "Games in the last 28 days", null);
    const games91 = num(inp, "games_91", "Games in the last 91 days", games28);
    if (games91 < games28) throw new Error("Games in the last 91 days can't be fewer than in the last 28 days.");
    const daysSince = num(inp, "days_since", "Days since your last game", games28 ? 0 : null);
    const peak = num(inp, "peak", "Highest rating", rating, 400);
    const rating91 = num(inp, "rating_91", "Rating 91 days ago", rating, 400);
    const score91 = num(inp, "score_91", "Points in the last 91 days", games91 / 2);
    if (score91 > games91) throw new Error("Points in the last 91 days can't be more than the games played.");
    const oppAvg = (inp.opp_avg === null || inp.opp_avg === undefined || inp.opp_avg === "")
      ? rating : num(inp, "opp_avg", "Average opponent", null, 400);
    const x = features(data, { rating, games_total: gamesTotal, games_28: games28, days_since: daysSince,
      peak: Math.max(peak, rating), rating_91: rating91, score_91: score91, games_91: games91, opp_avg: oppAvg, horizon });

    const a = data.active;   // formula p_active: intercept, activity, idle, experience, log_horizon
    const p = inp.keep_playing ? 1
      : 1 / (1 + Math.exp(-(a[0] + a[1] * x.activity + a[2] * x.idle + a[3] * x.experience + a[4] * x.log_horizon)));
    const terms = data.change_terms;
    const q = data.change.map((c) => c.reduce((s, coef, i) => s + coef * (terms[i] === "intercept" ? 1 : x[terms[i]]), 0));
    const med = q[levels.indexOf(0.5)];
    const qa = sorted(q.map((v) => med + data.band_scale * (v - med)));
    const quant = {};
    for (const t of SHOWN) quant[t] = mixtureQuantile(p, qa, t, levels);

    const step = data.milestone_step;
    const next = Math.floor(rating / step + 1) * step;
    const milestones = [next, next + step].map((m) => ({ rating: m, p: mixtureExceed(p, qa, m - rating, levels) }));
    let goal = null;
    if (inp.goal !== null && inp.goal !== undefined && inp.goal !== "") {
      const g = num(inp, "goal", "Goal", null, 400);
      goal = { rating: g, p: g > rating ? mixtureExceed(p, qa, g - rating, levels) : 1 - p * activeCdf(qa, g - rating - 1e-9, levels) };
    }
    const at = (t) => rating + quant[t];
    return {
      rating, horizon, features: x, p_active: p, change_if_playing: qa, quantiles: quant,
      median: at(0.5), ranges: Object.fromEntries(Object.entries(BANDS).map(([k, [lo, hi]]) => [k, [at(lo), at(hi)]])),
      p_higher: mixtureExceed(p, qa, 0, levels), milestones, goal,
    };
  }

  // ── dates ───────────────────────────────────────────────────────────────────
  const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
  function dayNumber(iso) {
    const m = ISO.exec(String(iso));
    if (!m) return null;
    const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
    const d = new Date(t);
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3] ? t / DAY : null;
  }
  const isoFromDay = (n) => new Date(n * DAY).toISOString().slice(0, 10);
  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  const niceDate = (iso) => new Date(dayNumber(iso) * DAY).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });

  // ── the log: validation, CSV, import/merge ─────────────────────────────────
  function cleanEntry(raw, speeds) {
    if (!raw || typeof raw !== "object") return [null, "not a row"];
    const date = String(raw.date ?? "").trim();
    if (dayNumber(date) === null) return [null, `date "${date.slice(0, 20)}" is not YYYY-MM-DD`];
    const speed = String(raw.speed ?? "").trim().toLowerCase();
    if (!speeds.includes(speed)) return [null, `speed must be one of ${speeds.join(", ")}`];
    const rating = Number(raw.rating);
    if (raw.rating === "" || raw.rating === null || !Number.isFinite(rating) || rating < 400 || rating > 4000) return [null, "rating must be a number from 400 to 4000"];
    let games = null;
    if (raw.games !== undefined && raw.games !== null && String(raw.games).trim() !== "") {
      games = Number(raw.games);
      if (!Number.isInteger(games) || games < 0 || games > 10000000) return [null, "games must be a whole number (0 or more)"];
    }
    const note = String(raw.note ?? "").replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 200);
    return [{ date, speed, rating: Math.round(rating), games, note }, null];
  }

  function cleanEntries(rows, speeds) {
    const entries = [], errors = [];
    rows.forEach((r, i) => {
      const [e, err] = cleanEntry(r, speeds);
      if (e) entries.push(e); else errors.push(`row ${i + 1}: ${err}`);
    });
    return { entries, errors };
  }

  const sortEntries = (entries) => entries.sort((a, b) => a.date.localeCompare(b.date) || a.speed.localeCompare(b.speed));
  const entryKey = (e) => `${e.date}|${e.speed}`;

  // merge: an imported row replaces the one with the same date and speed
  function mergeEntries(old, add) {
    const byKey = new Map(old.map((e) => [entryKey(e), e]));
    for (const e of add) byKey.set(entryKey(e), e);
    return sortEntries([...byKey.values()]);
  }

  function parseCsv(text) {
    const rows = [];
    let row = [], field = "", quoted = false, i = 0;
    text = String(text).replace(/^﻿/, "");
    while (i < text.length) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i += 2; continue; }
        if (c === '"') { quoted = false; i++; continue; }
        field += c; i++; continue;
      }
      if (c === '"' && field === "") { quoted = true; i++; continue; }
      if (c === ",") { row.push(field); field = ""; i++; continue; }
      if (c === "\n" || c === "\r") {
        row.push(field); field = "";
        if (row.some((f) => f.trim() !== "")) rows.push(row);
        row = [];
        i += c === "\r" && text[i + 1] === "\n" ? 2 : 1;
        continue;
      }
      field += c; i++;
    }
    row.push(field);
    if (row.some((f) => f.trim() !== "")) rows.push(row);
    return rows;
  }

  function csvField(v) {
    let s = v === null || v === undefined ? "" : String(v);
    if (/^[=+\-@\t\r]/.test(s) && Number.isNaN(Number(s))) s = "'" + s;   // keep spreadsheets from running it
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  function toCsv(entries) {
    return [CSV_COLUMNS.join(","), ...entries.map((e) => CSV_COLUMNS.map((k) => csvField(e[k])).join(","))].join("\n") + "\n";
  }

  function cleanStats(raw) {
    const out = {};
    if (!raw || typeof raw !== "object") return out;
    if (dayNumber(raw.as_of) !== null) out.as_of = raw.as_of;
    for (const k of STAT_KEYS) {
      const v = raw[k];
      if (v === null || v === undefined || v === "") continue;
      const x = Number(v);
      if (Number.isFinite(x) && x >= 0 && x < 1e7) out[k] = x;
    }
    return out;
  }

  function cleanSettings(raw, speeds) {
    const s = { stats: {}, saved: [] };
    if (!raw || typeof raw !== "object") return s;
    if (speeds.includes(raw.speed)) s.speed = raw.speed;
    if (dayNumber(raw.target_date) !== null) s.target_date = raw.target_date;
    const goal = Number(raw.goal);
    if (raw.goal !== null && raw.goal !== "" && Number.isFinite(goal) && goal >= 400 && goal <= 4000) s.goal = goal;
    s.keep_playing = raw.keep_playing === true;
    if (typeof raw.username === "string" && /^[A-Za-z0-9_-]{2,30}$/.test(raw.username)) s.username = raw.username;
    if (raw.stats && typeof raw.stats === "object") for (const sp of speeds) if (raw.stats[sp]) s.stats[sp] = cleanStats(raw.stats[sp]);
    if (Array.isArray(raw.saved)) {
      for (const r of raw.saved.slice(0, 500)) {
        if (!r || !speeds.includes(r.speed) || [r.made, r.from, r.target].some((d) => dayNumber(d) === null)) continue;
        const nums = ["rating", "median", "low", "high"].map((k) => Number(r[k]));
        if (nums.some((x) => !Number.isFinite(x))) continue;
        s.saved.push({ made: r.made, from: r.from, speed: r.speed, target: r.target,
          rating: nums[0], median: nums[1], low: nums[2], high: nums[3] });
      }
    }
    return s;
  }

  // A file's text -> {entries, errors, settings (JSON only)}; throws when nothing in it is usable.
  function parseImport(text, data) {
    const speeds = data.speeds;
    const t = String(text).trim();
    if (t.startsWith("{")) {
      let obj;
      try { obj = JSON.parse(t); } catch (e) { throw new Error("This JSON file can't be read."); }
      if (obj.model && obj.model !== data.model) throw new Error(`This file is a log for a different tool (${String(obj.model).slice(0, 40)}).`);
      if (!Array.isArray(obj.entries)) throw new Error("This JSON file has no entries list.");
      const { entries, errors } = cleanEntries(obj.entries, speeds);
      return { entries, errors, settings: cleanSettings(obj.settings, speeds) };
    }
    const rows = parseCsv(t);
    if (!rows.length) throw new Error("The file is empty.");
    const head = rows[0].map((h) => h.trim().toLowerCase());
    for (const need of ["date", "speed", "rating"]) {
      if (!head.includes(need)) throw new Error(`The CSV needs a header row with ${["date", "speed", "rating"].join(", ")} (and optionally games, note).`);
    }
    const objs = rows.slice(1).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
    const { entries, errors } = cleanEntries(objs, speeds);
    return { entries, errors: errors.map((e) => e.replace(/^row (\d+)/, (_, n) => `line ${+n + 1}`)), settings: null };
  }

  // ── Lichess games -> the recent stats (pure, so tests can run it) ──────────
  // games: objects from lichess.org/api/games/user/<name> (ndjson), newest first or any order.
  function summarizeGames(games, userId, nowMs, currentRating) {
    const id = String(userId).toLowerCase();
    let n = 0, n28 = 0, score = 0, oppSum = 0, oppN = 0, newest = null, oldest = null;
    for (const g of games) {
      if (!g || g.rated === false || g.status === "aborted" || g.status === "noStart" || !g.players) continue;
      const side = ["white", "black"].find((s) => g.players[s] && g.players[s].user && String(g.players[s].user.id).toLowerCase() === id);
      if (!side) continue;
      const me = g.players[side], opp = g.players[side === "white" ? "black" : "white"] || {};
      const t = Number(g.createdAt);
      if (!Number.isFinite(t)) continue;
      n++;
      if (t >= nowMs - 28 * DAY) n28++;
      score += g.winner ? (g.winner === side ? 1 : 0) : 0.5;
      if (Number.isFinite(opp.rating)) { oppSum += opp.rating; oppN++; }
      const end = Number(g.lastMoveAt) || t;
      if (newest === null || end > newest) newest = end;
      if (oldest === null || t < oldest.t) oldest = { t, rating: me.rating };
    }
    return {
      games_91: n, games_28: n28, score_91: score,
      opp_avg: oppN ? Math.round(oppSum / oppN * 10) / 10 : null,
      days_since: newest === null ? null : Math.max(0, Math.floor((nowMs - newest) / DAY)),
      rating_91: oldest && Number.isFinite(oldest.rating) ? oldest.rating : currentRating,
    };
  }

  const LICHESS = "https://lichess.org/api";

  async function lichessJson(url, signal, what) {
    let r;
    try { r = await fetch(url, { signal, headers: { Accept: "application/json" } }); }
    catch (e) { if (e.name === "AbortError") throw e; throw new Error("Couldn't reach lichess.org. Check your connection and try again."); }
    if (r.status === 404) throw Object.assign(new Error(what), { status: 404 });
    if (r.status === 429) throw new Error("Lichess asked us to slow down. Wait a minute and try again.");
    if (!r.ok) throw new Error(`lichess.org answered with an error (${r.status}). Try again later.`);
    return r.json();
  }

  // One request at a time: the account, the speed's stats page, then the speed's rated games of
  // the last 91 days (streamed, at most data.lichess_cap).
  async function fetchLichess(data, username, speed, signal, progress) {
    const name = encodeURIComponent(username);
    progress(`Asking lichess.org for ${username}'s ratings…`);
    const user = await lichessJson(`${LICHESS}/user/${name}`, signal, `There is no Lichess account named ${username}.`);
    if (user.disabled) throw new Error("That Lichess account is closed.");
    const perfs = user.perfs || {};
    const now = Date.now(), today = todayIso();
    const snapshots = data.speeds.filter((s) => perfs[s] && perfs[s].games > 0)
      .map((s) => ({ date: today, speed: s, rating: Math.round(perfs[s].rating), games: perfs[s].games, note: "from Lichess" }));
    const notes = [];
    const cur = perfs[speed];
    if (!cur || !cur.games) return { snapshots, stats: null, notes: [`No rated ${speed} games on this account.`], userId: user.id };

    let highest = null, lastDate = null;
    try {
      const perf = await lichessJson(`${LICHESS}/user/${name}/perf/${speed}`, signal, "no stats");
      const st = (perf && perf.stat) || {};
      highest = st.highest && Number.isFinite(st.highest.int) ? st.highest.int : null;
      lastDate = st.playStreak && st.playStreak.lastDate ? Date.parse(st.playStreak.lastDate) : null;
    } catch (e) {
      if (e.name === "AbortError") throw e;
      notes.push("Your highest rating couldn't be read; fill it in yourself.");
    }

    const since = now - 91 * DAY;
    const url = `${LICHESS}/games/user/${name}?since=${since}&perfType=${speed}&rated=true&moves=false&opening=false&max=${data.lichess_cap}`;
    const games = [];
    let gamesError = null;
    try {
      const r = await fetch(url, { signal, headers: { Accept: "application/x-ndjson" } });
      if (r.status === 429) throw new Error("Lichess asked us to slow down");
      if (!r.ok || !r.body) throw new Error(`error ${r.status}`);
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      const take = (line) => {
        line = line.trim();
        if (!line) return;
        try { games.push(JSON.parse(line)); } catch (e) { /* skip a broken line */ }
      };
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        lines.forEach(take);
        progress(`Reading your rated ${speed} games from the last 91 days: ${games.length} so far…`);
      }
      take(buf);
    } catch (e) {
      if (e.name === "AbortError") throw e;
      gamesError = e.message === "Failed to fetch" ? "couldn't connect" : e.message;
    }
    const peak = Math.max(highest ?? 0, Math.round(cur.rating));
    let stats;
    if (gamesError) {
      // the ratings and the peak still count; the recent-game numbers stay as the visitor typed them
      notes.push(`Your recent games couldn't be read from lichess.org (${gamesError}): fill in the recent-game numbers yourself.`);
      stats = { as_of: today, peak };
      if (lastDate) stats.days_since = Math.max(0, Math.floor((now - lastDate) / DAY));
    } else {
      const s = summarizeGames(games, user.id, now, Math.round(cur.rating));
      if (s.days_since === null && lastDate) s.days_since = Math.max(0, Math.floor((now - lastDate) / DAY));
      if (games.length >= data.lichess_cap) {
        notes.push(`You played more than ${data.lichess_cap.toLocaleString("en-US")} ${speed} games in 91 days; the stats use the latest ${data.lichess_cap.toLocaleString("en-US")}, so "rating 91 days ago" is from a more recent game.`);
      }
      stats = { as_of: today, ...s, peak };
      for (const k of Object.keys(stats)) if (stats[k] === null) delete stats[k];
    }
    return { snapshots, stats, notes, userId: user.id };
  }

  // ── storage ─────────────────────────────────────────────────────────────────
  function emptyLog(data) {
    return { model: data.model, version: 1, updated: null, settings: { speed: data.default_speed, stats: {}, saved: [] }, entries: [] };
  }

  function loadLog(data) {
    let raw = null;
    try { raw = window.localStorage.getItem(data.storage_key); }
    catch (e) { return { log: emptyLog(data), ok: false }; }
    if (!raw) return { log: emptyLog(data), ok: true };
    try {
      const obj = JSON.parse(raw);
      const log = emptyLog(data);
      log.updated = typeof obj.updated === "string" ? obj.updated : null;
      log.entries = sortEntries(cleanEntries(Array.isArray(obj.entries) ? obj.entries : [], data.speeds).entries);
      log.settings = { ...log.settings, ...cleanSettings(obj.settings, data.speeds) };
      return { log, ok: true };
    } catch (e) {
      return { log: emptyLog(data), ok: true, broken: true };
    }
  }

  function saveLog(data, log) {
    log.updated = new Date().toISOString();
    try { window.localStorage.setItem(data.storage_key, JSON.stringify(log)); return true; }
    catch (e) { return false; }
  }

  function download(name, type, text) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ── formatting ──────────────────────────────────────────────────────────────
  const int = (x) => Math.round(x).toLocaleString("en-US");
  const signed = (x) => (Math.round(x) > 0 ? "+" : Math.round(x) < 0 ? "−" : "") + Math.abs(Math.round(x)).toLocaleString("en-US");
  function pct(p) {
    if (p < 0.005) return "under 1%";
    if (p > 0.995) return "over 99%";
    return `${Math.round(p * 100)}%`;
  }

  // ── the page ────────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const loaded = loadLog(data);
    const log = loaded.log;
    let storageOk = loaded.ok;
    let editing = null;        // index in log.entries of the snapshot being edited
    let pending = null;        // a parsed import waiting for "add" or "replace"
    let fetching = null;       // AbortController of a running Lichess fill
    let last = null;           // the forecast on screen (for "Save this forecast")
    const S = () => log.settings;
    if (!S().speed) S().speed = data.default_speed;

    const status = el("p", { class: "note lr-status", "aria-live": "polite" });
    const storageNote = el("p", { class: "note", ...SRC });
    const say = (text) => { status.textContent = text || ""; };
    function persist() {
      storageOk = saveLog(data, log);
      storageNote.textContent = storageOk
        ? "Your log is saved only in this browser. Nothing is uploaded."
        : "This browser isn't letting the page save (private mode or full storage): your log will be lost when you leave. Export it to keep it.";
    }
    const statsFor = (speed) => (S().stats[speed] = S().stats[speed] || {});
    const ofSpeed = () => log.entries.filter((e) => e.speed === S().speed);
    const latest = () => { const xs = ofSpeed(); return xs.length ? xs[xs.length - 1] : null; };

    // speed + Lichess fill
    const speedSel = el("select", { "aria-label": "Speed", onchange: (e) => { S().speed = e.target.value; editing = null; resetForm(); persist(); drawStats(); drawSnapshots(); drawForecast(); } },
      data.speeds.map((s) => el("option", { value: s, ...(s === S().speed ? { selected: "" } : {}) }, s[0].toUpperCase() + s.slice(1))));
    const userIn = el("input", { type: "text", placeholder: "Lichess username", size: "16", autocomplete: "off", spellcheck: "false",
      "aria-label": "Lichess username", value: S().username || "" });
    const fillBtn = el("button", { type: "button", class: "ss-btn", onclick: () => fill() }, "Fill from my Lichess account");
    const stopBtn = el("button", { type: "button", class: "ss-btn", hidden: true, onclick: () => fetching && fetching.abort() }, "Stop");

    async function fill() {
      const name = userIn.value.trim();
      if (!/^[A-Za-z0-9_-]{2,30}$/.test(name)) { say("Type your Lichess username (letters, numbers, - and _)."); return; }
      const speed = S().speed;
      fetching = new AbortController();
      fillBtn.disabled = true; stopBtn.hidden = false;
      try {
        const res = await fetchLichess(data, name, speed, fetching.signal, say);
        S().username = name;
        const notes = new Map(log.entries.map((e) => [entryKey(e), e.note]));   // keep a note written on the same day
        log.entries = mergeEntries(log.entries, res.snapshots.map((e) => ({ ...e, note: notes.get(entryKey(e)) || e.note })));
        if (res.stats) S().stats[speed] = { ...statsFor(speed), ...res.stats };
        persist();
        const st = res.stats;
        say([`Filled from Lichess: ${res.snapshots.length} rating${res.snapshots.length === 1 ? "" : "s"} dated today`
          + (st && st.games_91 !== undefined ? ` and your ${speed} stats (${st.games_91} rated games in the last 91 days).` : "."), ...res.notes].join(" "));
        drawStats(); drawSnapshots(); drawForecast();
      } catch (e) {
        say(e.name === "AbortError" ? "Stopped. Nothing was changed." : e.message);
      } finally {
        fetching = null; fillBtn.disabled = false; stopBtn.hidden = true;
      }
    }

    // snapshots: the log itself
    const snapWrap = el("div", { class: "table-wrap" });
    const fDate = el("input", { type: "date", "aria-label": "Date", value: todayIso() });
    const fRating = el("input", { type: "number", inputmode: "numeric", min: "400", max: "4000", step: "1", "aria-label": "Rating", placeholder: "1650" });
    const fGames = el("input", { type: "number", inputmode: "numeric", min: "0", step: "1", "aria-label": "Rated games so far", placeholder: "900" });
    const fNote = el("input", { type: "text", maxlength: "200", "aria-label": "Note", placeholder: "optional" });
    const addBtn = el("button", { type: "button", class: "ss-btn", onclick: () => addEntry() }, "Add to my log");
    const cancelBtn = el("button", { type: "button", class: "ss-btn", hidden: true, onclick: () => { editing = null; resetForm(); } }, "Cancel");
    function resetForm() {
      fDate.value = todayIso(); fRating.value = ""; fGames.value = ""; fNote.value = "";
      addBtn.textContent = "Add to my log"; cancelBtn.hidden = true;
    }
    function addEntry() {
      const [e, err] = cleanEntry({ date: fDate.value, speed: S().speed, rating: fRating.value, games: fGames.value, note: fNote.value }, data.speeds);
      if (!e) { say(`Not added: ${err}.`); return; }
      if (editing !== null) log.entries.splice(editing, 1);
      editing = null;
      log.entries = mergeEntries(log.entries, [e]);
      persist(); resetForm(); say(`Saved your ${e.speed} rating ${e.rating} for ${niceDate(e.date)}.`);
      drawSnapshots(); drawForecast();
    }
    function drawSnapshots() {
      const rows = log.entries.map((e, i) => [e, i]).filter(([e]) => e.speed === S().speed).reverse();
      const others = log.entries.length - rows.length;
      if (!rows.length) {
        snapWrap.replaceChildren(el("p", { class: "note", ...SRC }, `No ${S().speed} ratings in your log yet. Add today's below, or fill them in from your Lichess account.`
          + (others ? ` (${others} in other speeds.)` : "")));
        return;
      }
      snapWrap.replaceChildren(el("table", {},
        el("thead", {}, el("tr", {}, ["Date", "Rating", "Rated games", "Note", ""].map((t, i) => el("th", { scope: "col", class: i === 1 || i === 2 ? "num" : null }, t)))),
        el("tbody", {}, rows.map(([e, i]) => el("tr", {},
          el("td", {}, niceDate(e.date)), el("td", { class: "num" }, el("b", {}, int(e.rating))),
          el("td", { class: "num" }, e.games === null ? "" : int(e.games)), el("td", {}, e.note),
          el("td", { class: "lr-actions" },
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Edit ${e.date}`, onclick: () => {
              editing = i; fDate.value = e.date; fRating.value = e.rating; fGames.value = e.games ?? ""; fNote.value = e.note;
              addBtn.textContent = "Save changes"; cancelBtn.hidden = false; fRating.focus();
            } }, "Edit"),
            el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Delete ${e.date}`, onclick: () => {
              log.entries.splice(i, 1); editing = null; resetForm(); persist(); drawSnapshots(); drawForecast();
            } }, "Delete")))))),
        ...(others ? [el("p", { class: "note" }, `${others} more in other speeds (pick the speed above to see them).`)] : []));
    }

    // recent stats for the chosen speed
    const statsBox = el("div", { class: "rc-race lr-stats" });
    const statsNote = el("p", { class: "note" });
    const FIELDS = [
      ["games_28", "Rated games, last 28 days"], ["games_91", "Rated games, last 91 days"],
      ["days_since", "Days since your last game"], ["peak", "Highest rating ever"],
      ["rating_91", "Rating 91 days ago"], ["score_91", "Points in those 91 days"],
      ["opp_avg", "Average opponent in them"],
    ];
    const statInputs = {};
    function defaults() {
      const snap = latest(), xs = ofSpeed();
      const rating = snap ? snap.rating : null;
      const peak = xs.length ? Math.max(...xs.map((e) => e.rating)) : rating;
      let r91 = rating;
      if (snap) {
        const want = dayNumber(snap.date) - 91;
        let best = null;
        for (const e of xs) {
          const gap = Math.abs(dayNumber(e.date) - want);
          if (gap <= 14 && (best === null || gap < best.gap)) best = { gap, rating: e.rating };
        }
        if (best) r91 = best.rating;
      }
      return { peak, rating_91: r91, rating };
    }
    function drawStats() {
      const st = statsFor(S().speed), d = defaults();
      const ph = {
        games_28: "needed", games_91: "same as 28 days", days_since: "0 if you played lately",
        peak: d.peak ? `${d.peak} (from your log)` : "your rating", rating_91: d.rating_91 ? `${d.rating_91}${d.rating_91 !== d.rating ? " (from your log)" : " (today's)"}` : "today's rating",
        score_91: "half the games (win 1, draw ½)", opp_avg: "your rating",
      };
      statsBox.replaceChildren(...FIELDS.map(([k, label]) => {
        const inp = el("input", { type: "number", inputmode: "decimal", min: "0", step: "any", placeholder: ph[k], "aria-label": label,
          value: st[k] ?? "", oninput: (e) => {
            const v = e.target.value.trim();
            if (v === "") delete st[k]; else st[k] = Number(v);
            st.as_of = todayIso();
            persist(); drawForecast();
          } });
        statInputs[k] = inp;
        return el("label", {}, el("span", { class: "rc-lbl" }, label), inp);
      }));
      statsNote.textContent = st.as_of ? `These ${S().speed} numbers are as of ${niceDate(st.as_of)}. Update them when you add a new rating.`
        : `All on your Lichess ${S().speed} stats and games pages, or filled in by the Lichess button. Blank fields use the grey value.`;
    }

    // forecast
    const targetIn = el("input", { type: "date", "aria-label": "Target date", value: S().target_date || "",
      onchange: (e) => { S().target_date = e.target.value || undefined; persist(); drawForecast(); } });
    const goalIn = el("input", { type: "number", inputmode: "numeric", min: "400", max: "4000", step: "1", placeholder: "optional", "aria-label": "Goal rating",
      value: S().goal ?? "", oninput: (e) => { const v = Number(e.target.value); S().goal = e.target.value && Number.isFinite(v) ? v : undefined; persist(); drawForecast(); } });
    const keepIn = el("input", { type: "checkbox", "aria-label": "Assume I keep playing", ...(S().keep_playing ? { checked: "" } : {}),
      onchange: (e) => { S().keep_playing = e.target.checked; persist(); drawForecast(); } });
    const out = el("div", { class: "rc-out", "aria-live": "polite" });
    const chartBox = el("div", { class: "rc-chart" });
    const savedBox = el("div", {});

    function inputsNow(horizon) {
      const snap = latest(), st = statsFor(S().speed), d = defaults();
      const pick = (k, dflt) => (st[k] === undefined ? dflt : st[k]);
      return {
        rating: snap.rating, horizon, games_total: snap.games, games_28: pick("games_28", null),
        games_91: pick("games_91", null), days_since: pick("days_since", null), peak: pick("peak", d.peak),
        rating_91: pick("rating_91", d.rating_91), score_91: pick("score_91", null), opp_avg: pick("opp_avg", null),
        keep_playing: !!S().keep_playing, goal: S().goal ?? null,
      };
    }

    function drawForecast() {
      last = null;
      const snap = latest();
      if (!snap) {
        out.replaceChildren(el("p", { class: "note", ...SRC }, "Add your current rating to the log to see a forecast."));
        chartBox.replaceChildren(); drawSaved(); return;
      }
      if (snap.games === null) {
        out.replaceChildren(el("p", { class: "note", ...SRC }, `Add the number of rated ${S().speed} games so far to your latest rating (${niceDate(snap.date)}): Edit it in the log.`));
        chartBox.replaceChildren(); drawSaved(); return;
      }
      const from = dayNumber(snap.date);
      // no date picked yet: default_days after the latest rating (moves with it until one is picked)
      const target = S().target_date || isoFromDay(from + data.default_days);
      targetIn.value = target;
      const horizon = dayNumber(target) - from;
      let res;
      try { res = predict(data, inputsNow(horizon)); }
      catch (e) { out.replaceChildren(el("p", { class: "note" }, e.message)); chartBox.replaceChildren(); drawSaved(); return; }
      last = { from: snap.date, target, speed: S().speed, rating: snap.rating, res };
      const [lo80, hi80] = res.ranges[80], [lo50, hi50] = res.ranges[50], [lo95, hi95] = res.ranges[95];
      const sp = S().speed;
      const rows = [
        [`Plays rated ${sp} again before then`, res.p_active],
        [`Higher than today (${int(snap.rating)})`, res.p_higher],
        ...res.milestones.map((m) => [`Reaches ${int(m.rating)}`, m.p]),
        ...(res.goal ? [[`At or above your goal (${int(res.goal.rating)})`, res.goal.p]] : []),
      ];
      const st = statsFor(sp);
      const stale = st.as_of && Math.abs(dayNumber(st.as_of) - from) > 7
        ? el("p", { class: "note" }, `Your recent stats are from ${niceDate(st.as_of)} but your latest rating is from ${niceDate(snap.date)}; update them for a better forecast.`) : null;
      out.replaceChildren(...[
        el("p", { class: "rc-own", ...SRC }, `Most likely ${sp} rating on ${niceDate(target)}: ${int(res.median)} (${signed(res.median - snap.rating)}). `
          + `8 in 10 chance it is between ${int(lo80)} and ${int(hi80)}.`),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Chance that you…"), el("th", { scope: "col", class: "num" }, "Chance"))),
          el("tbody", {}, rows.map(([label, p]) => el("tr", {}, el("td", {}, label), el("td", { class: "num" }, el("b", {}, pct(p)))))))),
        el("p", { class: "note", ...SRC }, `Half the time it ends between ${int(lo50)} and ${int(hi50)}; 95 in 100 between ${int(lo95)} and ${int(hi95)}. `
          + `Counted from your rating of ${niceDate(snap.date)}, ${horizon} days ahead. If you stop playing ${sp}, your rating stays at ${int(snap.rating)}.`),
        stale,
        el("button", { type: "button", class: "ss-btn", onclick: () => saveForecast() }, "Save this forecast to check later"),
      ].filter(Boolean));
      drawChart(snap, horizon);
      drawSaved();
    }

    function drawChart(snap, horizon) {
      const xs = ofSpeed();
      const from = dayNumber(snap.date);
      const n = Math.min(horizon, 12), fc = [], band = [];
      for (let i = 0; i <= n; i++) {
        const hh = Math.max(1, Math.round(horizon * i / n));
        if (i === 0) { fc.push([from, snap.rating]); band.push([from, snap.rating, snap.rating]); continue; }
        try {
          const r = predict(data, inputsNow(hh));
          fc.push([from + hh, r.median]); band.push([from + hh, r.ranges[80][0], r.ranges[80][1]]);
        } catch (e) { return; }
      }
      const x0 = Math.min(...xs.map((e) => dayNumber(e.date)), from), x1 = from + horizon;
      const ticks = [];
      for (let i = 0; i <= 4; i++) {
        const d = Math.round(x0 + (x1 - x0) * i / 4);
        ticks.push([d, new Date(d * DAY).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" })]);
      }
      chartBox.replaceChildren(h.renderLine({
        title: "Your rating and the forecast",
        series: [{ name: "Your log", points: xs.map((e) => [dayNumber(e.date), e.rating]) },
          { name: "Forecast (8 in 10 range shaded)", points: fc, band }],
        x_ticks: ticks, y_label: `${S().speed[0].toUpperCase()}${S().speed.slice(1)} rating`, x_fmt: "number", y_fmt: "int",
        markers: xs.map((e) => ({ x: dayNumber(e.date), y: e.rating, label: `${niceDate(e.date)}: ${e.rating}` })),
      }));
    }

    function saveForecast() {
      if (!last) return;
      const r = last.res;
      S().saved.push({ made: todayIso(), from: last.from, speed: last.speed, target: last.target, rating: last.rating,
        median: Math.round(r.median), low: Math.round(r.ranges[80][0]), high: Math.round(r.ranges[80][1]) });
      persist(); say("Saved. Log your rating on or after that date to see how it went."); drawSaved();
    }

    function drawSaved() {
      const saved = S().saved || [];
      if (!saved.length) { savedBox.replaceChildren(); return; }
      const today = dayNumber(todayIso());
      savedBox.replaceChildren(
        el("h3", { class: "lr-h", ...SRC }, "Your saved forecasts"),
        el("div", { class: "table-wrap" }, el("table", {},
          el("thead", {}, el("tr", {}, ["Speed", "From", "For", "Most likely", "8 in 10 between", "What happened", ""].map((t) => el("th", { scope: "col" }, t)))),
          el("tbody", {}, saved.map((s, i) => {
            const t = dayNumber(s.target);
            const after = log.entries.find((e) => e.speed === s.speed && dayNumber(e.date) >= t && dayNumber(e.date) - t <= 14);
            const what = after ? `${int(after.rating)} on ${niceDate(after.date)} (${after.rating >= s.low && after.rating <= s.high ? "inside" : "outside"} the range)`
              : t > today ? "not yet" : "log your rating from around that date";
            return el("tr", {}, el("td", {}, s.speed), el("td", {}, `${int(s.rating)}, ${niceDate(s.from)}`), el("td", {}, niceDate(s.target)),
              el("td", { class: "num" }, el("b", {}, int(s.median))), el("td", {}, `${int(s.low)} - ${int(s.high)}`), el("td", {}, what),
              el("td", {}, el("button", { type: "button", class: "ss-btn rc-x", "aria-label": "Delete this saved forecast",
                onclick: () => { S().saved.splice(i, 1); persist(); drawSaved(); } }, "Delete")));
          })))));
    }

    // export / import / clear
    const fileIn = el("input", { type: "file", accept: ".json,.csv,application/json,text/csv", hidden: true, onchange: (e) => readFile(e.target.files[0]) });
    const importBox = el("div", {});
    const stamp = () => todayIso();
    async function readFile(file) {
      fileIn.value = "";
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) { say("That file is too big for a rating log (over 5 MB)."); return; }
      let parsed;
      try { parsed = parseImport(await file.text(), data); }
      catch (e) { say(`Couldn't import ${file.name}: ${e.message}`); return; }
      const errs = parsed.errors.length ? `${parsed.errors.length} row${parsed.errors.length === 1 ? "" : "s"} skipped (${parsed.errors.slice(0, 3).join("; ")}${parsed.errors.length > 3 ? "; …" : ""}).` : "";
      if (!parsed.entries.length) { say(`Nothing to import from ${file.name}. ${errs}`); return; }
      pending = parsed;
      importBox.replaceChildren(el("div", { class: "rc-race" },
        el("p", { class: "lr-ask" }, `${file.name}: ${parsed.entries.length} rating${parsed.entries.length === 1 ? "" : "s"} to import. ${errs}`),
        el("button", { type: "button", class: "ss-btn", onclick: () => doImport(false) }, "Add to my log"),
        el("button", { type: "button", class: "ss-btn", onclick: () => doImport(true) }, "Replace my log"),
        el("button", { type: "button", class: "ss-btn", onclick: () => { pending = null; importBox.replaceChildren(); } }, "Cancel")));
    }
    function doImport(replace) {
      if (!pending) return;
      if (replace) {
        log.entries = sortEntries(pending.entries);
        if (pending.settings) log.settings = { speed: data.default_speed, ...pending.settings };
      } else {
        log.entries = mergeEntries(log.entries, pending.entries);
        if (pending.settings) {
          const have = new Set(S().saved.map((s) => JSON.stringify(s)));
          for (const s of pending.settings.saved) if (!have.has(JSON.stringify(s))) S().saved.push(s);
        }
      }
      say(`Imported ${pending.entries.length} rating${pending.entries.length === 1 ? "" : "s"}${replace ? " (your log was replaced)" : ""}.`);
      pending = null; importBox.replaceChildren();
      persist(); redrawAll();
    }
    const tools = el("div", { class: "lr-tools" },
      el("button", { type: "button", class: "ss-btn", onclick: () => { log.updated = new Date().toISOString();
        download(`ballmonitor-${data.model}-log-${stamp()}.json`, "application/json", JSON.stringify(log, null, 2)); } }, "Export (JSON)"),
      el("button", { type: "button", class: "ss-btn", onclick: () => download(`ballmonitor-${data.model}-log-${stamp()}.csv`, "text/csv", toCsv(log.entries)) }, "Export (CSV)"),
      el("button", { type: "button", class: "ss-btn", onclick: () => fileIn.click() }, "Import a file"),
      el("button", { type: "button", class: "ss-btn", onclick: () => {
        if (!window.confirm("Delete your whole Lichess rating log (ratings, stats and saved forecasts) from this browser? This can't be undone.")) return;
        try { window.localStorage.removeItem(data.storage_key); } catch (e) { /* storage blocked: nothing saved anyway */ }
        const fresh = emptyLog(data);
        log.entries = fresh.entries; log.settings = fresh.settings; editing = null;
        say("Your log was cleared."); redrawAll();
      } }, "Clear my log"), fileIn);

    function redrawAll() {
      speedSel.value = S().speed; userIn.value = S().username || "";
      targetIn.value = S().target_date || ""; goalIn.value = S().goal ?? ""; keepIn.checked = !!S().keep_playing;
      resetForm(); drawStats(); drawSnapshots(); drawForecast();
    }

    const band = (t) => el("h3", { class: "lr-h", ...SRC }, t);
    host.replaceChildren(
      el("div", { class: "rc-form" },
        el("div", { class: "rc-race" },
          el("label", {}, el("span", { class: "rc-lbl" }, "Speed"), speedSel),
          el("label", {}, el("span", { class: "rc-lbl" }, "Lichess username"), userIn), fillBtn, stopBtn),
        el("p", { class: "note", ...SRC }, "Optional: the button asks lichess.org (Lichess's public site, no login) for this "
          + "username's ratings and its rated games of the last 91 days in this speed, straight from your browser. Nothing goes to Ball Monitor."),
        status),
      band("Your ratings"),
      snapWrap,
      el("div", { class: "rc-race" },
        el("label", {}, el("span", { class: "rc-lbl" }, "Date"), fDate),
        el("label", {}, el("span", { class: "rc-lbl" }, "Rating"), fRating),
        el("label", {}, el("span", { class: "rc-lbl" }, "Rated games so far"), fGames),
        el("label", {}, el("span", { class: "rc-lbl" }, "Note"), fNote), addBtn, cancelBtn),
      band("Your recent games"),
      statsBox, statsNote,
      band("Forecast"),
      el("div", { class: "rc-race" },
        el("label", {}, el("span", { class: "rc-lbl" }, "On this date"), targetIn),
        el("label", {}, el("span", { class: "rc-lbl" }, "Goal rating"), goalIn),
        el("label", { class: "lr-check" }, keepIn, " Assume I keep playing")),
      out, chartBox, savedBox,
      band("Your log file"),
      tools, importBox, storageNote);
    if (loaded.broken) say("The log saved in this browser couldn't be read, so it starts empty.");
    storageNote.textContent = storageOk
      ? "Your log is saved only in this browser. Nothing is uploaded."
      : "This browser isn't letting the page save (private mode or full storage): your log will be lost when you leave. Export it to keep it.";
    resetForm(); drawStats(); drawSnapshots(); drawForecast();
  }

  const api = { predict, features, activeCdf, activeQuantile, mixtureQuantile, mixtureExceed, parseCsv, toCsv,
    parseImport, cleanEntries, mergeEntries, summarizeGames, dayNumber, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests (node)
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).lichess_rating = api;
})();
