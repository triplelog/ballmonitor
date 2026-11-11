// Race time calculator (the race_time page's "app" view). Enter one or more races; get the most
// likely time and the 8-in-10 range at every distance.
//
// compute() is a line-by-line copy of the race_time model's default method (models/race_time:
// bands.weighted_riegel, log_quantiles, quantile_times; formulas exponent, predict, race_weight,
// band_log_quantile, median_time, band_time in config.toml). Every number it uses comes from the
// model's config, written into the page by site.py at build time. tests/test_race_calc.py runs
// this file under node and checks it against the Python model, so a change to the model's
// formulas fails the build until this copy is updated too.
"use strict";

(function () {
  const MEDIAN = 3;   // index of the 50% quantile in data.levels

  // ── the model ──────────────────────────────────────────────────────────────
  function exponent(data, gender) {
    const e = data.exponent;
    return e.base + (gender === "M" ? e.male : 0) + (gender === "F" ? e.female : 0);
  }

  // races: [{d: meters, t: seconds, years: years before now}] -> 7 quantile times (s) at distance D
  function quantiles(data, races, D, b) {
    const implied = [], raw = [], xs = [];
    for (const r of races) {
      const x = Math.log(D / r.d);
      implied.push(r.t * Math.pow(D / r.d, b));                                  // formula predict
      raw.push(Math.exp(-Math.abs(x) / data.weights.distance_scale)
        * Math.pow(0.5, r.years / data.weights.half_life_years));               // formula race_weight
      xs.push(x);
    }
    const total = raw.reduce((a, w) => a + w, 0);
    const w = raw.map((x) => x / total);
    const point = data.combination === "arithmetic"
      ? w.reduce((a, wi, i) => a + wi * implied[i], 0)
      : Math.exp(w.reduce((a, wi, i) => a + wi * Math.log(implied[i]), 0));
    const gap = w.reduce((a, wi, i) => a + wi * Math.abs(xs[i]), 0);
    const lastYears = Math.min(...races.map((r) => r.years));
    const years = Math.min(Math.max(lastYears, 0), data.bands.max_years);
    const n = Math.max(1, Math.min(races.length, data.bands.max_races));
    const q = data.bands.coef.map((c) => c[0] + c[1] * gap + c[2] * years + c[3] / n).sort((a, z) => a - z);
    const median = point * Math.exp(q[MEDIAN]);                                  // formula median_time
    const times = q.map((qi) => median * Math.exp(data.bands.scale * (qi - q[MEDIAN])));   // formula band_time
    times[MEDIAN] = median;
    for (let i = 1; i < times.length; i++) times[i] = Math.max(times[i], times[i - 1]);
    return times;
  }

  // Everything the page shows: per distance the quantile times, plus the runner's own curve
  // (a straight line through their races in log time vs log distance) when they gave two or
  // more distances. The own curve is only described, never used for the times: fitting one to a
  // runner's races was less accurate than this method (race_time RESEARCH_SIMPLE.md, method D).
  function compute(data, gender, races) {
    const b = exponent(data, gender);
    const rows = data.distances.map((dist) => ({ ...dist, times: quantiles(data, races, dist.meters, b) }));
    const ds = [...new Set(races.map((r) => r.d))];
    let own = null;
    if (ds.length >= 2) {
      const lx = races.map((r) => Math.log(r.d)), ly = races.map((r) => Math.log(r.t));
      const mx = lx.reduce((a, x) => a + x, 0) / lx.length, my = ly.reduce((a, y) => a + y, 0) / ly.length;
      let sxy = 0, sxx = 0;
      lx.forEach((x, i) => { sxy += (x - mx) * (ly[i] - my); sxx += (x - mx) * (x - mx); });
      own = sxy / sxx;
    }
    return { exponent: b, rows, own };
  }

  // ── reading and writing times ──────────────────────────────────────────────
  function parseTime(text) {
    const parts = String(text).trim().split(":");
    if (!parts[0] || parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null;
    const n = parts.map(Number);
    const sec = n.length === 3 ? n[0] * 3600 + n[1] * 60 + n[2] : n.length === 2 ? n[0] * 60 + n[1] : n[0] * 60;
    return sec > 0 ? sec : null;   // a bare number is minutes
  }

  function clock(sec) {
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const pad = (x) => String(x).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  // ── the form ───────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const raceDistances = data.distances.filter((d) => d.input);
    const state = { gender: data.default_gender, races: data.example.map((r) => ({ ...r })) };
    const list = el("div", { class: "rc-races" });
    const out = el("div", { class: "rc-out", "aria-live": "polite" });
    const gender = el("select", { "aria-label": "Runner", onchange: (e) => { state.gender = e.target.value; draw(); } },
      data.genders.map(([v, label]) => el("option", { value: v, ...(v === state.gender ? { selected: "" } : {}) }, label)));
    const add = el("button", { type: "button", class: "ss-btn", onclick: () => {
      const used = new Set(state.races.map((r) => r.distance));
      const next = data.add_order.map((k) => raceDistances.find((d) => d.key === k)).find((d) => d && !used.has(d.key))
        || raceDistances[0];
      state.races.push({ distance: next.key, time: "", when: data.whens[0][0] });
      drawRaces(); draw();
      list.querySelectorAll("input")[state.races.length - 1]?.focus();
    } }, "Add another race");

    function drawRaces() {
      list.replaceChildren(...state.races.map((r, i) => el("div", { class: "rc-race" },
        el("label", {}, el("span", { class: "rc-lbl" }, "Race"),
          el("select", { "aria-label": `Race ${i + 1} distance`, onchange: (e) => { r.distance = e.target.value; draw(); } },
            raceDistances.map((d) => el("option", { value: d.key, ...(d.key === r.distance ? { selected: "" } : {}) }, d.label)))),
        el("label", {}, el("span", { class: "rc-lbl" }, "Time"),
          el("input", { type: "text", inputmode: "numeric", value: r.time, placeholder: "25:00 or 1:52:30", size: "10",
            "aria-label": `Race ${i + 1} time`, oninput: (e) => { r.time = e.target.value; draw(); } })),
        el("label", {}, el("span", { class: "rc-lbl" }, "When"),
          el("select", { "aria-label": `Race ${i + 1} when`, onchange: (e) => { r.when = +e.target.value; draw(); } },
            data.whens.map(([v, label]) => el("option", { value: v, ...(v === r.when ? { selected: "" } : {}) }, label)))),
        state.races.length > 1 ? el("button", { type: "button", class: "ss-btn rc-x", "aria-label": `Remove race ${i + 1}`,
          onclick: () => { state.races.splice(i, 1); drawRaces(); draw(); } }, "Remove") : null)));
      add.hidden = state.races.length >= data.max_races;
    }

    function draw() {
      const byKey = Object.fromEntries(raceDistances.map((d) => [d.key, d]));
      const races = [], bad = [], odd = [];
      const [fastest, slowest] = data.pace_limits;
      state.races.forEach((r, i) => {
        const t = parseTime(r.time), dist = byKey[r.distance];
        if (r.time.trim() && !t) bad.push(i + 1);
        if (!t) return;
        const pace = t / (dist.meters / data.meters_per_mile);
        // a typo (a 44:30 mile, a 2:15 half): left out rather than stretched to every distance
        if (pace < fastest || pace > slowest) odd.push(`Race ${i + 1} (${dist.label} in ${clock(t)}) is ${clock(pace)} per mile`);
        else races.push({ d: dist.meters, t, years: r.when, label: dist.label });
      });
      const warn = [
        bad.length ? `Race ${bad.join(", ")}: write the time like 25:00 or 1:52:30.` : "",
        odd.length ? `${odd.join("; ")}: check the distance and time (left out).` : "",
      ].filter(Boolean).map((t) => el("p", { class: "note" }, t));
      if (!races.length) {
        out.replaceChildren(...(warn.length ? warn : [el("p", { class: "note" }, "Enter a time for at least one race.")]));
        return;
      }
      const res = compute(data, state.gender, races);
      const table = el("table", {},
        el("thead", {}, el("tr", {}, ["Distance", "Most likely", "Pace / mile", "8 in 10 finish between"].map((t, i) =>
          el("th", { class: i ? "num" : null, scope: "col" }, t)))),
        el("tbody", {}, res.rows.map((row) => {
          const mid = row.times[MEDIAN], pace = mid / (row.meters / data.meters_per_mile);
          return el("tr", {}, el("td", {}, row.label), el("td", { class: "num" }, el("b", {}, clock(mid))),
            el("td", { class: "num" }, clock(pace)),
            el("td", { class: "num" }, `${clock(row.times[1])} - ${clock(row.times[5])}`));
        })));
      // the chart: pace per mile at each distance (log scale across), the 8-in-10 band, your races
      const pts = data.curve.map((m) => {
        const t = quantiles(data, races, m, res.exponent), mi = m / data.meters_per_mile;
        return [Math.log(m), t[MEDIAN] / mi, t[1] / mi, t[5] / mi];
      });
      const chart = h.renderLine({
        title: "Your pace at each distance",
        series: [{ name: "Most likely pace", points: pts.map((p) => [p[0], p[1]]), band: pts.map((p) => [p[0], p[2], p[3]]) }],
        x_ticks: data.ticks.map(([m, label]) => [Math.log(m), label]),
        y_label: "Pace per mile", y_fmt: "time", x_fmt: "number",
        markers: races.map((r) => ({ x: Math.log(r.d), y: r.t / (r.d / data.meters_per_mile), label: `Your ${r.label}: ${clock(r.t)}` })),
      });
      const typical = data.typical[state.gender] || data.typical[""];
      let curveNote = null;
      if (res.own !== null) {
        const diff = res.own - typical;
        const how = diff < -data.own_curve_margin ? "you slow down less than most runners as races get longer: your endurance is a strength"
          : diff > data.own_curve_margin ? "you slow down more than most runners as races get longer: your speed is the strength"
          : "you slow down about as much as most runners as races get longer";
        curveNote = el("p", { class: "rc-own" }, `A curve through your races has an exponent of ${res.own.toFixed(2)} `
          + `(typical: ${typical.toFixed(2)}). That means ${how}.`);
      }
      out.replaceChildren(...[
        ...warn,
        curveNote,
        el("div", { class: "table-wrap" }, table),
        el("div", { class: "rc-chart" }, chart),
        el("p", { class: "note" }, `Your ${races.length > 1 ? "races are" : "race is"} on the chart as dots. `
          + "Races closer to each distance, and more recent races, count for more."),
      ].filter(Boolean));
    }

    host.replaceChildren(
      el("div", { class: "rc-form" },
        el("label", { class: "pick" }, "Runner: ", gender),
        list, add),
      out);
    drawRaces();
    draw();
  }

  const api = { compute, quantiles, exponent, parseTime, mount };
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // tests (node)
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).race_time = api;
})();
