// Birthplace maps (the baseball_birthplaces page's "app" view): for each map cell and birth decade,
// a formula over the career totals of the players born within the smallest circle around the
// cell that holds data.circle_people people (values per data.people). The circles (one PNG per decade and frame) and the players
// (one JSON per decade) are built by the model's fetch.py and loaded when a decade is shown.
//
// laea(), parse()/evaluate() (Python's formula rules: core/formula.py) and compute() are copies of
// models/baseball_birthplaces/engine.py (laea, cell_values, safe). tests/test_birthplace_map_app.py
// runs this file under node and checks it against the Python model.
"use strict";

(function () {
  const R_EARTH = 6371.0088;
  const OCEAN = 0, NONE_WITHIN = 65535;

  // ── projection (engine.laea) ────────────────────────────────────────────────
  function laea(lat, lon, lat0, lon0) {
    const rad = Math.PI / 180;
    const phi = lat * rad, lam = (lon - lon0) * rad, phi0 = lat0 * rad;
    const c = 1 + Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(lam);
    const k = Math.sqrt(2 / Math.max(c, 1e-12));
    return [R_EARTH * k * Math.cos(phi) * Math.sin(lam),
      R_EARTH * k * (Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(lam))];
  }

  // ── formulas: the subset of Python that core/formula.py allows ─────────────────
  // Python's round(): uses the double's exact value (round(2.675, 2) = 2.67) and rounds exact
  // halves to even (round(2.5) = 2). toFixed also works on the exact value but rounds ties up.
  function roundHalfEven(x, n = 0) {
    n = Math.trunc(n);
    if (!Number.isFinite(x) || n < 0 || n > 20) return Math.round(x * Math.pow(10, n)) / Math.pow(10, n);
    const exact = Math.abs(x).toFixed(Math.min(100, n + 60));   // the double's exact decimal digits
    const rest = exact.slice(exact.indexOf(".") + 1 + n);
    if (/^50*$/.test(rest)) {                                   // an exact tie: to even
      const m = Math.pow(10, n), f = Math.floor(Math.abs(x) * m);
      return Math.sign(x) * (f % 2 === 0 ? f : f + 1) / m;
    }
    return Number(x.toFixed(n));
  }
  const FUNCS = {
    abs: Math.abs, min: (...a) => Math.min(...a), max: (...a) => Math.max(...a),
    round: (x, n) => roundHalfEven(x, n || 0), exp: Math.exp, log: (x, b) => (b === undefined ? Math.log(x) : Math.log(x) / Math.log(b)),
    log2: Math.log2, log10: Math.log10, sqrt: Math.sqrt, floor: Math.floor, ceil: Math.ceil,
    logistic: (x) => 1 / (1 + Math.exp(-x)), clamp: (x, lo, hi) => Math.min(Math.max(x, lo), hi),
  };
  const CONSTS = { pi: Math.PI, e: Math.E, True: 1, False: 0 };

  function tokenize(src) {
    const out = [];
    const re = /\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|([A-Za-z_]\w*)|(\*\*|\/\/|<=|>=|==|!=|[-+*\/%<>(),]))/y;
    let pos = 0;
    while (pos < src.length) {
      if (/^\s*$/.test(src.slice(pos))) break;
      re.lastIndex = pos;
      const m = re.exec(src);
      if (!m) throw new Error(`can't read "${src.slice(pos).trim().slice(0, 12)}"`);
      pos = re.lastIndex;
      if (m[1] !== undefined) out.push({ t: "num", v: parseFloat(m[1]) });
      else if (m[2] !== undefined) out.push({ t: ["and", "or", "not", "if", "else"].includes(m[2]) ? m[2] : "name", v: m[2] });
      else out.push({ t: "op", v: m[3] });
    }
    return out;
  }

  // Parse to a tree; names are checked against `known` (variables + constants).
  function parse(src, known) {
    const toks = tokenize(String(src));
    let i = 0;
    const peek = () => toks[i], next = () => toks[i++];
    const isOp = (v) => peek() && peek().t === "op" && peek().v === v;
    const expect = (v) => { if (!isOp(v)) throw new Error(`expected "${v}"`); i++; };
    const names = new Set();
    function ternary() {
      const a = orExpr();
      if (peek() && peek().t === "if") {
        i++;
        const c = orExpr();
        if (!peek() || peek().t !== "else") throw new Error('"if" needs an "else"');
        i++;
        return { k: "if", a, c, b: ternary() };
      }
      return a;
    }
    function orExpr() { let a = andExpr(); while (peek() && peek().t === "or") { i++; a = { k: "or", a, b: andExpr() }; } return a; }
    function andExpr() { let a = notExpr(); while (peek() && peek().t === "and") { i++; a = { k: "and", a, b: notExpr() }; } return a; }
    function notExpr() { if (peek() && peek().t === "not") { i++; return { k: "not", a: notExpr() }; } return comparison(); }
    function comparison() {
      const first = sum(), ops = [], rest = [];
      while (peek() && peek().t === "op" && ["<", "<=", ">", ">=", "==", "!="].includes(peek().v)) { ops.push(next().v); rest.push(sum()); }
      return ops.length ? { k: "cmp", first, ops, rest } : first;
    }
    function sum() { let a = term(); while (isOp("+") || isOp("-")) { const op = next().v; a = { k: "bin", op, a, b: term() }; } return a; }
    function term() { let a = factor(); while (isOp("*") || isOp("/") || isOp("//") || isOp("%")) { const op = next().v; a = { k: "bin", op, a, b: factor() }; } return a; }
    function factor() { if (isOp("-") || isOp("+")) { const op = next().v; return { k: "neg", op, a: factor() }; } return power(); }
    function power() { const a = atom(); if (isOp("**")) { i++; return { k: "bin", op: "**", a, b: factor() }; } return a; }
    function atom() {
      const t = next();
      if (!t) throw new Error("the formula ends too soon");
      if (t.t === "num") return { k: "num", v: t.v };
      if (t.t === "name") {
        if (isOp("(")) {
          if (!FUNCS[t.v]) throw new Error(`unknown function "${t.v}"`);
          i++;
          const args = [];
          if (!isOp(")")) { args.push(ternary()); while (isOp(",")) { i++; args.push(ternary()); } }
          expect(")");
          return { k: "call", f: t.v, args };
        }
        const ok = !known || (typeof known === "function" ? known(t.v) : known.includes(t.v));
        if (!(t.v in CONSTS) && !ok) throw new Error(`unknown name "${t.v}"`);
        names.add(t.v);
        return { k: "name", v: t.v };
      }
      if (t.t === "op" && t.v === "(") { const e = ternary(); expect(")"); return e; }
      throw new Error(`unexpected "${t.v}"`);
    }
    if (!toks.length) throw new Error("the formula is empty");
    const tree = ternary();
    if (i < toks.length) throw new Error(`unexpected "${toks[i].v}"`);
    tree.names = [...names];
    return tree;
  }

  const truthy = (v) => v !== 0 && v !== false && !Number.isNaN(v);
  function evaluate(n, env) {
    switch (n.k) {
      case "num": return n.v;
      case "name": return n.v in env ? env[n.v] : CONSTS[n.v];
      case "neg": { const a = +evaluate(n.a, env); return n.op === "-" ? -a : a; }
      case "not": return !truthy(evaluate(n.a, env));
      case "and": return truthy(evaluate(n.a, env)) && truthy(evaluate(n.b, env));   // core/formula: all(...)
      case "or": return truthy(evaluate(n.a, env)) || truthy(evaluate(n.b, env));    // any(...)
      case "if": return truthy(evaluate(n.c, env)) ? evaluate(n.a, env) : evaluate(n.b, env);
      case "call": return FUNCS[n.f](...n.args.map((x) => +evaluate(x, env)));
      case "cmp": {
        let left = +evaluate(n.first, env);
        for (let k = 0; k < n.ops.length; k++) {
          const right = +evaluate(n.rest[k], env), op = n.ops[k];
          const ok = op === "<" ? left < right : op === "<=" ? left <= right : op === ">" ? left > right
            : op === ">=" ? left >= right : op === "==" ? left === right : left !== right;
          if (!ok) return false;
          left = right;
        }
        return true;
      }
      case "bin": {
        const a = +evaluate(n.a, env), b = +evaluate(n.b, env);
        switch (n.op) {
          case "+": return a + b;
          case "-": return a - b;
          case "*": return a * b;
          case "/": if (b === 0) throw new Error("division by zero"); return a / b;
          case "//": if (b === 0) throw new Error("division by zero"); return Math.floor(a / b);
          case "%": if (b === 0) throw new Error("division by zero"); return ((a % b) + b) % b;
          case "**": return Math.pow(a, b);
        }
      }
    }
    throw new Error("bad formula");
  }

  // engine.safe: a number, or null when it can't be computed (0/0 in a cell with no players)
  function safe(tree, env) {
    try {
      const v = +evaluate(tree, env);
      return Number.isFinite(v) ? v : null;
    } catch (e) {
      return null;
    }
  }

  // engine.overlap: share of a birthplace disk (radius s, centre d km away) inside a circle of radius R
  // engine.overlap; a disk under 10 m is a point. Two circular segments (stable for small s).
  function segment(r, h) {
    h = Math.max(-r, Math.min(r, h));
    return r * r * Math.acos(h / r) - h * Math.sqrt(Math.max(0, (r - h) * (r + h)));
  }
  function overlap(d, R, s) {
    if (s < 0.01) return d <= R ? 1 : 0;
    if (d >= R + s) return 0;
    if (d <= R - s) return 1;
    if (d <= s - R) return (R * R) / (s * s);
    const h = (d * d + R * R - s * s) / (2 * d);   // from the circle's centre to the chord
    return Math.min(1, Math.max(0, (segment(R, h) + segment(s, d - h)) / (Math.PI * s * s)));
  }

  // ── the map values (engine.cell_sums / cell_values) ────────────────────────
  const DECADE_NAME = /^([A-Za-z]\w*?)_(\d{4})$/;

  // One decade: per cell the weighted count and the sums of `used` stats over the included players
  // in its circle, scaled to per `target` people by the population inside the circle (people grid,
  // units of `unit`). NaN where there is no circle.
  function cellSums(players, code, people, frame, include, used, stats, target, unit) {
    const n = players.lat.length;
    const xs = [], ys = [], ss = [], vals = used.map(() => []);
    const env = {};
    for (let p = 0; p < n; p++) {
      for (const k of stats) env[k] = players[k][p];
      if (!truthy(safe(include, env) ?? 0)) continue;
      const [x, y] = laea(players.lat[p], players.lon[p], frame.lat0, frame.lon0);
      xs.push(x); ys.push(y); ss.push(players.spread[p]);
      used.forEach((k, j) => vals[j].push(players[k][p]));
    }
    // buckets so a circle looks only near itself; the margin covers the largest circle plus a birthplace disk
    let rmax = 0;
    for (let q = 0; q < code.length; q++) if (code[q] !== NONE_WITHIN && code[q] > rmax) rmax = code[q];
    const margin = rmax / 10 + ss.reduce((a, b) => Math.max(a, b), 0) + 50;
    const B = 50, bx0 = frame.x0 - margin, by0 = frame.y0 - margin;
    const bnx = Math.ceil((frame.nx * frame.cell + 2 * margin) / B), bny = Math.ceil((frame.ny * frame.cell + 2 * margin) / B);
    const buckets = new Map();
    xs.forEach((x, p) => {
      const bi = Math.floor((x - bx0) / B), bj = Math.floor((ys[p] - by0) / B);
      if (bi < 0 || bj < 0 || bi >= bnx || bj >= bny) return;
      const key = bj * bnx + bi;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(p);
    });
    const smax = ss.reduce((a, b) => Math.max(a, b), 0);
    const size = frame.nx * frame.ny;
    const count = new Float64Array(size).fill(NaN), sums = used.map(() => new Float64Array(size).fill(NaN));
    const acc = new Float64Array(used.length);
    for (let j = 0; j < frame.ny; j++) {
      for (let i = 0; i < frame.nx; i++) {
        const q = j * frame.nx + i, c = code[q];
        if (c === OCEAN || c === NONE_WITHIN) continue;
        const r = c / 10, reach = r + smax, reach2 = reach * reach;
        const cx = frame.x0 + (i + 0.5) * frame.cell, cy = frame.y0 + (frame.ny - j - 0.5) * frame.cell;
        acc.fill(0);
        let cnt = 0;
        const i0 = Math.max(0, Math.floor((cx - reach - bx0) / B)), i1 = Math.min(bnx - 1, Math.floor((cx + reach - bx0) / B));
        const j0 = Math.max(0, Math.floor((cy - reach - by0) / B)), j1 = Math.min(bny - 1, Math.floor((cy + reach - by0) / B));
        for (let bj = j0; bj <= j1; bj++) {
          for (let bi = i0; bi <= i1; bi++) {
            const list = buckets.get(bj * bnx + bi);
            if (!list) continue;
            for (const p of list) {
              const dx = xs[p] - cx, dy = ys[p] - cy, d2 = dx * dx + dy * dy;
              if (d2 > reach2) continue;
              const w = overlap(Math.sqrt(d2), r, ss[p]);
              if (w > 0) {
                cnt += w;
                for (let k = 0; k < used.length; k++) acc[k] += w * vals[k][p];
              }
            }
          }
        }
        const scale = people ? target / (people[q] * unit) : 1;
        count[q] = cnt * scale;
        for (let k = 0; k < used.length; k++) sums[k][q] = acc[k] * scale;
      }
    }
    return { count, sums };
  }

  // Which decade and number each name in a value formula means: HR -> (current, HR), HR_1910 -> (1910, HR)
  function namesByDecade(tree, stats, current) {
    const by = new Map();
    for (const name of tree.names) {
      const m = DECADE_NAME.exec(name);
      const [d, base] = m && (stats.includes(m[1]) || m[1] === "players") ? [+m[2], m[1]] : [current, name];
      if (base !== "players" && !stats.includes(base)) continue;
      if (!by.has(d)) by.set(d, new Set());
      by.get(d).add(base);
    }
    if (!by.has(current)) by.set(current, new Set());
    return by;
  }

  // engine.cell_values: decades = {decade: {players, code, people}} for every decade the formula uses.
  // Returns Float64Array (NaN = no value / not drawn).
  function compute(decades, frame, include, value, stats, current, target, unit) {
    const by = namesByDecade(value, stats, current);
    const parts = new Map();
    for (const [d, set] of by) {
      const used = [...set].filter((k) => k !== "players");
      const dd = decades[d];
      parts.set(d, { used, ...cellSums(dd.players, dd.code, dd.people, frame, include, used, stats, target, unit) });
    }
    const out = new Float64Array(frame.nx * frame.ny).fill(NaN);
    const env = {};
    for (let q = 0; q < out.length; q++) {
      if (Number.isNaN(parts.get(current).count[q])) continue;
      let missing = false;
      for (const k of stats) env[k] = 0;
      for (const [d, part] of parts) {
        const n = part.count[q];
        if (Number.isNaN(n)) { missing = true; break; }
        const suffix = `_${d}`;
        env[`players${suffix}`] = n;
        part.used.forEach((k, idx) => { env[k + suffix] = part.sums[idx][q]; });
        if (d === current) { env.players = n; part.used.forEach((k, idx) => { env[k] = part.sums[idx][q]; }); }
      }
      if (missing) continue;
      const v = safe(value, env);
      if (v !== null) out[q] = v;
    }
    return out;
  }

  // Players born within a cell's circle, with their share (for the details box)
  function inCircle(players, frame, i, j, r) {
    const cx = frame.x0 + (i + 0.5) * frame.cell, cy = frame.y0 + (frame.ny - j - 0.5) * frame.cell;
    const out = [];
    for (let p = 0; p < players.lat.length; p++) {
      const [x, y] = laea(players.lat[p], players.lon[p], frame.lat0, frame.lon0);
      const w = overlap(Math.hypot(x - cx, y - cy), r, players.spread[p]);
      if (w > 0) out.push([p, w]);
    }
    return out;
  }

  // ── drawn regions (engine.region_stats) ────────────────────────────────────
  const POP_LOG = 4000, CELL_SAMPLES = 4;
  function diskPoints(s) {
    if (s < 0.01) return [[0, 0]];
    const pts = [[0, 0]];
    for (const [n, rr] of [[6, 0.5], [12, 0.866]]) {
      for (let k = 0; k < n; k++) {
        const a = (2 * Math.PI * k) / n;
        pts.push([s * rr * Math.cos(a), s * rr * Math.sin(a)]);
      }
    }
    return pts;
  }
  function inside(px, py, poly) {   // even-odd rule, poly = [[x, y], ...] km
    let res = false;
    for (let k = 0, n = poly.length; k < n; k++) {
      const [x1, y1] = poly[k], [x2, y2] = poly[(k + 1) % n];
      if (y1 === y2) continue;
      if ((y1 > py) !== (y2 > py) && px < x1 + ((py - y1) * (x2 - x1)) / (y2 - y1)) res = !res;
    }
    return res;
  }
  function regionPopulation(pop, frame, poly) {
    const xs = poly.map((q) => q[0]), ys = poly.map((q) => q[1]);
    const i0 = Math.max(0, Math.floor((Math.min(...xs) - frame.x0) / frame.cell));
    const i1 = Math.min(frame.nx - 1, Math.floor((Math.max(...xs) - frame.x0) / frame.cell));
    const j0 = Math.max(0, frame.ny - 1 - Math.floor((Math.max(...ys) - frame.y0) / frame.cell));
    const j1 = Math.min(frame.ny - 1, frame.ny - 1 - Math.floor((Math.min(...ys) - frame.y0) / frame.cell));
    let total = 0;
    for (let j = j0; j <= j1; j++) {
      for (let i = i0; i <= i1; i++) {
        let hit = 0;
        for (let a = 0; a < CELL_SAMPLES; a++) {
          for (let b = 0; b < CELL_SAMPLES; b++) {
            const x = frame.x0 + (i + (a + 0.5) / CELL_SAMPLES) * frame.cell;
            const y = frame.y0 + (frame.ny - j - (b + 0.5) / CELL_SAMPLES) * frame.cell;
            if (inside(x, y, poly)) hit++;
          }
        }
        if (hit) total += Math.expm1(pop[j * frame.nx + i] / POP_LOG) * (hit / (CELL_SAMPLES * CELL_SAMPLES));
      }
    }
    return total;
  }
  // byDecade = {decade: {players, pop}}; returns {decades: {d: {people, players, sums, value, names}}, total}
  function regionStats(byDecade, frame, poly, include, value, stats, target) {
    const decades = Object.keys(byDecade).map(Number).sort((a, b) => a - b);
    const rows = {};
    for (const d of decades) {
      const P = byDecade[d].players, env = {};
      const sums = Object.fromEntries(stats.map((k) => [k, 0]));
      let count = 0;
      const names = [];
      for (let p = 0; p < P.lat.length; p++) {
        for (const k of stats) env[k] = P[k][p];
        if (!truthy(safe(include, env) ?? 0)) continue;
        const [x, y] = laea(P.lat[p], P.lon[p], frame.lat0, frame.lon0);
        const pts = diskPoints(P.spread[p]);
        const w = pts.filter(([dx, dy]) => inside(x + dx, y + dy, poly)).length / pts.length;
        if (!w) continue;
        count += w;
        for (const k of stats) sums[k] += w * P[k][p];
        names.push([w, p]);
      }
      rows[d] = { people: regionPopulation(byDecade[d].pop, frame, poly), players: count, sums, names };
    }
    const scaled = (row) => (row.people > 0 ? { players: row.players * target / row.people,
      ...Object.fromEntries(stats.map((k) => [k, row.sums[k] * target / row.people])) } : null);
    const sc = {}, suffixed = {};
    for (const d of decades) {
      sc[d] = scaled(rows[d]);
      if (sc[d]) for (const [k, v] of Object.entries(sc[d])) suffixed[`${k}_${d}`] = v;
    }
    for (const d of decades) rows[d].value = sc[d] ? safe(value, { ...suffixed, ...sc[d] }) : null;
    const total = { people: decades.reduce((a, d) => a + rows[d].people, 0), players: decades.reduce((a, d) => a + rows[d].players, 0),
      sums: Object.fromEntries(stats.map((k) => [k, decades.reduce((a, d) => a + rows[d].sums[k], 0)])) };
    const st = scaled(total);
    total.value = st ? safe(value, { ...suffixed, ...st }) : null;
    return { decades: rows, total };
  }

  // ── colours ─────────────────────────────────────────────────────────────────
  const PALETTES = {
    sunset: ["#fff7bc", "#fec44f", "#fe9929", "#ec7014", "#cc4c02", "#8c2d04", "#4a1402"],
    viridis: ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"],
    magma: ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
    blues: ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    greens: ["#f7fcf5", "#c7e9c0", "#74c476", "#238b45", "#00441b"],
    "red-blue": ["#2166ac", "#67a9cf", "#d1e5f0", "#fddbc7", "#ef8a62", "#b2182b"],
  };
  const hex = (h) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
  function colorAt(stops, t) {
    if (!(t >= 0)) t = 0;
    if (t > 1) t = 1;
    const x = t * (stops.length - 1), k = Math.min(Math.floor(x), stops.length - 2), f = x - k;
    const a = hex(stops[k]), b = hex(stops[k + 1]);
    return a.map((v, q) => Math.round(v + (b[q] - v) * f));
  }

  // ── the page ────────────────────────────────────────────────────────────────
  function mount(host, data, h) {
    const { el } = h;
    const cache = {};
    const state = {
      decade: data.default_decade, include: data.include, value: data.value, palette: data.palette,
      scale: "linear", max: "", custom: ["#ffffff", "#000080"], useCustom: false, playing: null,
    };
    const fmtNum = (v) => (v === null || Number.isNaN(v) ? "–" : v === 0 ? "0" : Math.abs(v) >= 100 ? Math.round(v).toLocaleString()
      : Math.abs(v) >= 10 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(3));

    const playerCache = {}, popCache = {};
    function loadPlayers(d) {
      return playerCache[d] = playerCache[d] || retry(() => fetch(`${data.files}players/${d}.json`).then((r) => {
        if (!r.ok) throw new Error(`players ${d}`);
        return r.json();
      })).catch((e) => { delete playerCache[d]; throw e; });
    }
    function loadPop(d, fi) {
      const key = `${d}_${fi}`, f = data.frames[fi];
      return popCache[key] = popCache[key] || decodePng(`${data.files}grid/${d}_${f.name}_pop.png`, f)
        .catch((e) => { delete popCache[key]; throw e; });
    }
    async function loadDecade(d) {
      if (cache[d]) return cache[d];
      const base = data.files;
      const [players, ...grids] = await Promise.all([
        loadPlayers(d),
        ...data.frames.map((f) => decodePng(`${base}grid/${d}_${f.name}.png`, f)),
        ...data.frames.map((f) => decodePng(`${base}grid/${d}_${f.name}_people.png`, f)),
      ]);
      const k = data.frames.length;
      cache[d] = { players, codes: grids.slice(0, k), people: grids.slice(k) };
      return cache[d];
    }
    // a flaky connection: try a file up to three times before giving up
    async function retry(load) {
      for (let k = 0; ; k++) {
        try { return await load(); } catch (e) { if (k >= 2) throw e; await new Promise((r) => setTimeout(r, 400 * (k + 1))); }
      }
    }
    function decodePng(url, frame) {
      return retry(() => decodeOnce(url, frame));
    }
    function decodeOnce(url, frame) {
      return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
          const c = document.createElement("canvas");
          c.width = frame.nx; c.height = frame.ny;
          const g = c.getContext("2d", { willReadFrequently: true });
          g.drawImage(img, 0, 0);
          const px = g.getImageData(0, 0, frame.nx, frame.ny).data;
          const code = new Uint16Array(frame.nx * frame.ny);
          for (let q = 0; q < code.length; q++) code[q] = px[4 * q] * 256 + px[4 * q + 1];
          resolve(code);
        };
        img.onerror = () => reject(new Error(`could not load ${url}`));
        img.src = url;
      });
    }
    let borders = null;
    const bordersReady = fetch(`${data.files}borders.json`).then((r) => r.json()).then((b) => { borders = b; }).catch(() => {});

    // controls
    const presetSel = el("select", { "aria-label": "Map", onchange: (e) => {
      const p = data.presets[+e.target.value];
      if (!p) return;
      incIn.value = state.include = p.include;
      valIn.value = state.value = p.value;
      draw();
    } }, el("option", { value: "" }, "Choose a map…"), data.presets.map((p, k) => el("option", { value: k }, p.label)));
    const incIn = el("input", { type: "text", value: state.include, size: "18", "aria-label": "Count a player if",
      onchange: (e) => { state.include = e.target.value; presetSel.value = ""; draw(); } });
    const valIn = el("input", { type: "text", value: state.value, size: "22", "aria-label": "Map value",
      onchange: (e) => { state.value = e.target.value; presetSel.value = ""; draw(); } });
    const msg = el("p", { class: "bm-msg", "aria-live": "polite" });
    const decadeOut = el("output", { class: "bm-decade" });
    const slider = el("input", { type: "range", min: 0, max: data.decades.length - 1, step: 1,
      value: data.decades.indexOf(state.decade), "aria-label": "Birth decade",
      oninput: (e) => { state.decade = data.decades[+e.target.value]; draw(); } });
    const play = el("button", { type: "button", class: "ss-btn small", onclick: () => togglePlay() }, "▶ Play");
    const palSel = el("select", { "aria-label": "Colours", onchange: (e) => {
      state.useCustom = e.target.value === "custom";
      if (!state.useCustom) state.palette = e.target.value;
      customBox.hidden = !state.useCustom;
      paint();
    } }, Object.keys(PALETTES).map((k) => el("option", { value: k, ...(k === state.palette ? { selected: "" } : {}) }, k)),
    el("option", { value: "custom" }, "my colours"));
    const c1 = el("input", { type: "color", value: state.custom[0], "aria-label": "Low colour", oninput: (e) => { state.custom[0] = e.target.value; paint(); } });
    const c2 = el("input", { type: "color", value: state.custom[1], "aria-label": "High colour", oninput: (e) => { state.custom[1] = e.target.value; paint(); } });
    const customBox = el("span", { class: "bm-custom", hidden: true }, c1, " to ", c2);
    const scaleSel = el("select", { "aria-label": "Scale", onchange: (e) => { state.scale = e.target.value; paint(); } },
      el("option", { value: "linear" }, "even steps"), el("option", { value: "sqrt" }, "square root"),
      el("option", { value: "log" }, "log"), el("option", { value: "rank" }, "by rank"));
    const maxIn = el("input", { type: "number", min: "0", step: "any", placeholder: "auto", "aria-label": "Top of the scale",
      onchange: (e) => { state.max = e.target.value; paint(); } });
    const legend = el("div", { class: "bm-legend" });
    const canvases = data.frames.map((f) => el("canvas", { class: `bm-map bm-${f.name}`, width: f.nx * 3, height: f.ny * 3,
      "aria-label": `${f.label} map` }));
    const details = el("div", { class: "bm-details" }, el("p", { class: "small" }, "Tap the map for the players born near a place."));
    let values = [], current = null, trees = null, clipped = false;
    const REGION_COLORS = ["#1f4e9c", "#c0392b", "#18864b", "#8e44ad", "#d35400", "#008b8b", "#7f6000", "#c2185b"];
    const regions = [];          // {name, fi, pts: [[x km, y km], ...], color}
    let drawing = null;          // {fi, pts}
    const bases = [];            // each canvas's painted map, for redrawing the regions on top
    const drawBtn = el("button", { type: "button", class: "ss-btn small", onclick: () => startDrawing() }, "Draw a region");
    const finishBtn = el("button", { type: "button", class: "ss-btn small", hidden: true, onclick: () => finishDrawing() }, "Finish region");
    const cancelBtn = el("button", { type: "button", class: "ss-btn small", hidden: true, onclick: () => cancelDrawing() }, "Cancel");
    const drawHint = el("span", { class: "small bm-draw-hint" }, "Draw any area on the map and compare the players born there, decade by decade.");
    const regionsBox = el("div", { class: "bm-regions" });

    host.replaceChildren(
      el("div", { class: "bm-controls" },
        el("label", {}, el("span", {}, "Map"), presetSel),
        el("label", {}, el("span", {}, "Count a player if"), incIn),
        el("label", {}, el("span", {}, "Value (per million people)"), valIn)),
      el("div", { class: "bm-controls" },
        el("label", { class: "bm-slider" }, el("span", {}, "Born in the"), slider, decadeOut), play),
      msg,
      el("div", { class: "bm-maps" }, canvases[0], el("div", { class: "bm-insets" }, canvases.slice(1).map((c, k) =>
        el("figure", {}, c, el("figcaption", {}, data.frames[k + 1].label))))),
      legend,
      el("div", { class: "bm-controls" },
        el("label", {}, el("span", {}, "Colours"), palSel), customBox,
        el("label", {}, el("span", {}, "Scale"), scaleSel),
        el("label", {}, el("span", {}, "Top of scale"), maxIn)),
      details,
      el("div", { class: "bm-controls bm-draw" }, drawBtn, finishBtn, cancelBtn, drawHint),
      regionsBox,
      el("details", { class: "bm-help" }, el("summary", {}, "Formula names"),
        el("p", { class: "small" }, "Each name is the total per million people for the players born in a place's circle; ", el("code", {}, "players"),
          " is how many. Add a decade for another decade's numbers, each in that decade's own circle: ",
          el("code", {}, "HR_1980 / HR_1910"), ", ", el("code", {}, "players_1990 - players_1950"),
          ". Use + − * / ** ( ), comparisons, and, or, not, ", el("code", {}, "a if test else b"),
          ", and min, max, abs, round, log, sqrt."),
        el("ul", { class: "small bm-names" }, Object.entries(data.stats).map(([k, d]) => el("li", {}, el("code", {}, k), ` ${d}`)))));

    canvases.forEach((cv, fi) => {
      cv.addEventListener("click", (ev) => (drawing ? addPoint(fi, ev) : showCell(fi, ev)));
      cv.addEventListener("dblclick", (ev) => { if (drawing) { ev.preventDefault(); finishDrawing(); } });
    });
    host.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && drawing) cancelDrawing(); });

    // ── drawing regions ──
    const toKm = (fi, ev) => {
      const f = data.frames[fi], rect = canvases[fi].getBoundingClientRect();
      return [f.x0 + ((ev.clientX - rect.left) / rect.width) * f.nx * f.cell,
        f.y0 + (f.ny - ((ev.clientY - rect.top) / rect.height) * f.ny) * f.cell];
    };
    function startDrawing() {
      drawing = { fi: null, pts: [] };
      drawBtn.hidden = true; finishBtn.hidden = false; cancelBtn.hidden = false;
      drawHint.textContent = "Click the map to add corners; double-click, or click the first corner, to finish. Esc cancels.";
      canvases.forEach((c) => c.classList.add("bm-drawing"));
    }
    function stopDrawing() {
      drawing = null;
      drawBtn.hidden = false; finishBtn.hidden = true; cancelBtn.hidden = true;
      drawHint.textContent = "Draw another area to compare, or rename and remove areas below.";
      canvases.forEach((c) => c.classList.remove("bm-drawing"));
    }
    function cancelDrawing() { const fi = drawing && drawing.fi; stopDrawing(); if (fi !== null && fi !== undefined) overlay(fi); }
    function addPoint(fi, ev) {
      if (drawing.fi === null) drawing.fi = fi;
      if (drawing.fi !== fi) return;   // one region stays in one map (main, Alaska or Hawaii)
      const pt = toKm(fi, ev), f = data.frames[fi];
      if (drawing.pts.length >= 3) {
        const [x0, y0] = drawing.pts[0], rect = canvases[fi].getBoundingClientRect();
        const px = Math.hypot(pt[0] - x0, pt[1] - y0) / (f.nx * f.cell) * rect.width;
        if (px < 10) { finishDrawing(); return; }
      }
      drawing.pts.push(pt);
      overlay(fi);
    }
    function finishDrawing() {
      if (!drawing || drawing.pts.length < 3) { cancelDrawing(); return; }
      // a double-click adds the same corner twice: drop repeats
      const pts = drawing.pts.filter((q, k, a) => !k || Math.hypot(q[0] - a[k - 1][0], q[1] - a[k - 1][1]) > 1e-6);
      const n = regions.length;
      regions.push({ name: `Area ${n + 1}`, fi: drawing.fi, pts, color: REGION_COLORS[n % REGION_COLORS.length] });
      const fi = drawing.fi;
      stopDrawing();
      overlay(fi);
      updateRegions();
    }
    function overlay(fi) {
      const cv = canvases[fi], g = cv.getContext("2d"), f = data.frames[fi], s = 3;
      if (bases[fi]) g.putImageData(bases[fi], 0, 0);
      const X = (x) => ((x - f.x0) / f.cell) * s, Y = (y) => (f.ny - (y - f.y0) / f.cell) * s;
      const path = (pts, close) => { g.beginPath(); pts.forEach(([x, y], k) => (k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); if (close) g.closePath(); };
      for (const r of regions.filter((q) => q.fi === fi)) {
        path(r.pts, true);
        g.fillStyle = r.color + "33"; g.fill();
        g.lineWidth = 2.5; g.strokeStyle = r.color; g.stroke();
        const cx = r.pts.reduce((a, q) => a + q[0], 0) / r.pts.length, cy = r.pts.reduce((a, q) => a + q[1], 0) / r.pts.length;
        g.font = "bold 22px sans-serif"; g.fillStyle = r.color; g.textAlign = "center"; g.fillText(r.name, X(cx), Y(cy));
      }
      if (drawing && drawing.fi === fi && drawing.pts.length) {
        path(drawing.pts, false);
        g.lineWidth = 2; g.setLineDash([6, 4]); g.strokeStyle = "#111"; g.stroke(); g.setLineDash([]);
        for (const [x, y] of drawing.pts) { g.beginPath(); g.arc(X(x), Y(y), 4, 0, 2 * Math.PI); g.fillStyle = "#111"; g.fill(); }
      }
    }

    // ── region results ──
    let regionRun = 0;
    async function updateRegions() {
      if (!regions.length) { regionsBox.replaceChildren(); return; }
      const run = ++regionRun;
      let inc, val;
      try {
        inc = parse(state.include, data.statNames);
        val = parse(state.value, (n) => n === "players" || data.statNames.includes(n)
          || (DECADE_NAME.test(n) && data.decades.includes(+DECADE_NAME.exec(n)[2])));
      } catch (e) {
        regionsBox.replaceChildren(el("p", { class: "bm-msg" }, `Formula problem: ${e.message}.`));
        return;
      }
      regionsBox.replaceChildren(el("p", { class: "bm-msg" }, "Loading every decade (about 1 MB, once)…"));
      const frames = [...new Set(regions.map((r) => r.fi))];
      let players, pops;
      try {
        players = Object.fromEntries(await Promise.all(data.decades.map(async (d) => [d, await loadPlayers(d)])));
        pops = {};
        for (const fi of frames) pops[fi] = Object.fromEntries(await Promise.all(data.decades.map(async (d) => [d, await loadPop(d, fi)])));
      } catch (e) {
        regionsBox.replaceChildren(el("p", { class: "bm-msg" }, "The data didn't load. Try again in a moment."));
        return;
      }
      if (run !== regionRun) return;
      const results = regions.map((r) => regionStats(Object.fromEntries(data.decades.map((d) => [d, { players: players[d], pop: pops[r.fi][d] }])),
        data.frames[r.fi], r.pts, inc, val, data.statNames, data.people));
      const last = data.decades[data.decades.length - 1];
      const rows = regions.map((r, k) => {
        const t = results[k].total, all = [];
        for (const d of data.decades) for (const [w, p] of results[k].decades[d].names) all.push([w, p, d]);
        all.sort((a, b) => players[b[2]].G[b[1]] - players[a[2]].G[a[1]]);
        const top = all[0] ? players[all[0][2]].name[all[0][1]] : "–";
        return [r, k, t, all, top];
      });
      const perM = (t, key) => (t.people > 0 ? (key === "players" ? t.players : t.sums[key]) * data.people / t.people : null);
      const nameInput = (r) => el("input", { type: "text", value: r.name, size: "10", "aria-label": "Area name",
        onchange: (e) => { r.name = e.target.value || r.name; overlay(r.fi); updateRegions(); } });
      const table = el("table", { class: "bm-rtable" },
        el("thead", {}, el("tr", {}, ["Area", "People (" + data.pop_year[last] + ")", "Big-leaguers born", "Per million people*",
          state.value + "*", "Hall of Famers", "All-Star picks", "Most games", ""].map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.map(([r, k, t, all, top]) => el("tr", {},
          el("td", {}, el("i", { class: "bm-sw", style: `background:${r.color}` }), " ", nameInput(r)),
          el("td", {}, fmtNum(results[k].decades[last].people)),
          el("td", {}, fmtNum(t.players)),
          el("td", {}, fmtNum(perM(t, "players"))),
          el("td", {}, fmtNum(t.value)),
          el("td", {}, fmtNum(t.sums.HOF)),
          el("td", {}, fmtNum(t.sums.AS)),
          el("td", {}, top),
          el("td", {}, el("button", { type: "button", class: "ss-btn small", "aria-label": `Remove ${r.name}`,
            onclick: () => { regions.splice(regions.indexOf(r), 1); overlay(r.fi); updateRegions(); } }, "Remove"))))));
      const series = rows.map(([r, k]) => ({ name: r.name,
        points: data.decades.filter((d) => results[k].decades[d].value !== null).map((d) => [d, results[k].decades[d].value]) }))
        .filter((x) => x.points.length);
      const chart = series.length ? h.renderLine({ kind: "line", title: `${state.value} per million people, by birth decade`, series,
        x_label: "Born in the", y_label: state.value, x_fmt: "number", y_fmt: "number",
        x_ticks: data.decades.filter((d) => d % 20 === 0).map((d) => [d, `${d}s`]) }) : null;
      const lists = rows.map(([r, , t, all]) => el("details", { class: "bm-rplayers" },
        el("summary", {}, `${r.name}: ${fmtNum(t.players)} big-leaguers (most games first)`),
        el("ul", { class: "bm-players" }, all.slice(0, 40).map(([w, p, d]) => {
          const P = players[d];
          return el("li", {}, `${P.name[p]} (b. ${P.born[p]}, ${P.place[p].split(",")[0]}): ${P.G[p].toLocaleString()} G`
            + (w < 1 ? ` (${Math.round(w * 100)}% inside: born in a big city on the edge)` : ""));
        })),
        all.length > 40 ? el("p", { class: "small" }, `…and ${all.length - 40} more.`) : null));
      regionsBox.replaceChildren(
        el("h3", { class: "bm-h" }, "Your areas"),
        el("div", { class: "bm-rwrap" }, table),
        el("p", { class: "small" }, `* All decades together: per million people per decade (each decade's births divided by that decade's population, ${data.decades[0]}s-${last}s). The value column uses your formula on those totals; "Count a player if" applies everywhere.`),
        chart ? el("div", { class: "bm-rchart" }, chart) : null,
        chart ? el("p", { class: "small" }, "Each point: the area's births in that decade, per million people living there then.") : null,
        ...lists);
    }

    function togglePlay() {
      if (state.playing) { clearInterval(state.playing); state.playing = null; play.textContent = "▶ Play"; return; }
      play.textContent = "❚❚ Pause";
      state.playing = setInterval(() => {
        let k = data.decades.indexOf(state.decade) + 1;
        if (k >= data.decades.length) k = 0;
        state.decade = data.decades[k];
        slider.value = k;
        draw();
      }, 1400);
    }

    let lastFormula = "";
    async function draw() {
      decadeOut.textContent = `${state.decade}s`;
      const formula = `${state.include}|${state.value}`;
      if (formula !== lastFormula) { lastFormula = formula; if (regions.length) updateRegions(); }
      let inc, val;
      const known = (n) => {
        const m = DECADE_NAME.exec(n);
        if (m && (data.statNames.includes(m[1]) || m[1] === "players")) {
          if (!data.decades.includes(+m[2])) throw new Error(`no decade ${m[2]} (use ${data.decades[0]}, ${data.decades[1]}, … ${data.decades[data.decades.length - 1]})`);
          return true;
        }
        return n === "players" || data.statNames.includes(n);
      };
      try {
        inc = parse(state.include, data.statNames);
        val = parse(state.value, known);
      } catch (e) {
        msg.textContent = `Formula problem: ${e.message}.`;
        return;
      }
      msg.textContent = "Loading…";
      const want = state.decade;
      const needed = [...namesByDecade(val, data.statNames, want).keys()];
      let loaded;
      try {
        loaded = Object.fromEntries(await Promise.all(needed.map(async (dd) => [dd, await loadDecade(dd)])));
      } catch (e) {
        console.error(e);
        msg.textContent = "This decade didn't load. Try again in a moment.";
        return;
      }
      if (want !== state.decade) return;
      await bordersReady;
      trees = { inc, val };
      const d = loaded[want];
      current = d;
      values = data.frames.map((f, fi) => compute(Object.fromEntries(needed.map((dd) => [dd,
        { players: loaded[dd].players, code: loaded[dd].codes[fi], people: loaded[dd].people[fi] }])),
      f, inc, val, data.statNames, want, data.people, data.people_unit));
      const n = d.players.lat.length;
      const others = needed.filter((dd) => dd !== want);
      msg.textContent = `${n.toLocaleString()} big-leaguers born in the ${want}s, compared with the population in ${data.pop_year[want]}.`
        + (others.length ? ` The formula also uses the ${others.map((dd) => `${dd}s`).join(", ")}, each in its own decade's circles.` : "")
        + (want === data.decades[data.decades.length - 1] ? " (This decade's players are still arriving.)" : "");
      paint();
    }

    // automatic range: 0 (or the 2nd percentile when values go below 0) to the 98th percentile, so a
    // few extreme cells (a ratio over a near-empty decade) don't wash out the map
    function scaleFn(all) {
      const finite = all.filter((v) => Number.isFinite(v));
      const sorted = Float64Array.from(finite).sort();
      const pct = (q) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))] : 0);
      const lo = Math.min(0, pct(0.02));
      let hi = state.max !== "" && +state.max > 0 ? +state.max : sorted.length ? pct(0.98) : 1;
      if (!(hi > lo)) hi = sorted.length ? sorted[sorted.length - 1] : lo + 1;
      if (!(hi > lo)) hi = lo + 1;
      clipped = sorted.length > 0 && sorted[sorted.length - 1] > hi;
      if (state.scale === "rank") {
        const sorted = Float64Array.from(finite).sort();
        return { lo, hi, t: (v) => { let a = 0, b = sorted.length; while (a < b) { const m = (a + b) >> 1; if (sorted[m] < v) a = m + 1; else b = m; } return sorted.length > 1 ? a / (sorted.length - 1) : 0; } };
      }
      const f = state.scale === "log" ? (v) => Math.log1p(Math.max(v - lo, 0)) : state.scale === "sqrt" ? (v) => Math.sqrt(Math.max(v - lo, 0)) : (v) => v - lo;
      const top = f(hi);
      return { lo, hi, t: (v) => f(v) / top };
    }

    function paint() {
      if (!current) return;
      const stops = state.useCustom ? state.custom : PALETTES[state.palette];
      const all = [];
      values.forEach((vs) => vs.forEach((v) => { if (Number.isFinite(v)) all.push(v); }));
      const sc = scaleFn(all);
      data.frames.forEach((f, fi) => {
        const cv = canvases[fi], g = cv.getContext("2d"), s = 3;
        const img = g.createImageData(f.nx * s, f.ny * s);
        const code = current.codes[fi], vs = values[fi];
        for (let j = 0; j < f.ny; j++) {
          for (let i = 0; i < f.nx; i++) {
            const q = j * f.nx + i, c = code[q];
            let rgb;
            if (c === OCEAN) rgb = [214, 226, 238];
            else if (c === NONE_WITHIN || !Number.isFinite(vs[q])) rgb = [236, 236, 232];
            else rgb = colorAt(stops, sc.t(vs[q]));
            for (let dy = 0; dy < s; dy++) {
              for (let dx = 0; dx < s; dx++) {
                const o = 4 * ((j * s + dy) * f.nx * s + i * s + dx);
                img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = 255;
              }
            }
          }
        }
        g.putImageData(img, 0, 0);
        if (borders && borders[f.name]) {
          const X = (x) => ((x - f.x0) / f.cell) * s, Y = (y) => (f.ny - (y - f.y0) / f.cell) * s;
          for (const [layer, width, color] of [["states", 0.5, "rgba(40,40,40,0.45)"], ["countries", 1, "rgba(20,20,20,0.8)"]]) {
            g.lineWidth = width; g.strokeStyle = color;
            for (const path of borders[f.name][layer] || []) {
              g.beginPath();
              path.forEach(([x, y], k) => (k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))));
              g.closePath();
              g.stroke();
            }
          }
        }
        bases[fi] = g.getImageData(0, 0, cv.width, cv.height);
        overlay(fi);
      });
      const bar = el("div", { class: "bm-bar", style: `background: linear-gradient(to right, ${stops.join(", ")})` });
      legend.replaceChildren(el("span", {}, fmtNum(sc.lo)), bar,
        el("span", {}, (state.scale === "rank" ? "highest" : fmtNum(sc.hi)) + (clipped ? "+" : "")),
        el("span", { class: "bm-key" }, el("i", { class: "bm-sw none" }), ` no circle of ${data.circle_label || "a million"} people, or no value`));
    }

    function showCell(fi, ev) {
      if (!current) return;
      const f = data.frames[fi], cv = canvases[fi], rect = cv.getBoundingClientRect();
      const i = Math.floor(((ev.clientX - rect.left) / rect.width) * f.nx);
      const j = Math.floor(((ev.clientY - rect.top) / rect.height) * f.ny);
      const c = current.codes[fi][j * f.nx + i];
      if (c === OCEAN || c === undefined) { details.replaceChildren(el("p", { class: "small" }, "That's water.")); return; }
      if (c === NONE_WITHIN) {
        details.replaceChildren(el("p", { class: "small" }, `Fewer than ${data.circle_label || "a million"} people lived within ${data.max_radius_km.toLocaleString()} km of here in ${data.pop_year[state.decade]}.`));
        return;
      }
      const r = c / 10, P = current.players;
      const hits = inCircle(P, f, i, j, r).filter(([p]) => {
        const env = {};
        for (const k of data.statNames) env[k] = P[k][p];
        return truthy(safe(trees.inc, env) ?? 0);
      });
      const v = values[fi][j * f.nx + i];
      hits.sort((a, b) => (P.G[b[0]] - P.G[a[0]]));
      const ids = hits.map(([p]) => p);
      const held = current.people[fi][j * f.nx + i] * data.people_unit;
      const counted = hits.reduce((a, [, w]) => a + w, 0) * data.people / held;
      const places = {};
      hits.forEach(([p, w]) => { places[P.place[p]] = (places[P.place[p]] || 0) + w; });
      const top = Object.entries(places).sort((a, b) => b[1] - a[1])[0];
      details.replaceChildren(
        el("p", {}, el("strong", {}, fmtNum(Number.isFinite(v) ? v : null)), ` (${state.value}) · a circle of ${Math.round(r).toLocaleString()} km`
          + ` around this spot held ${held.toLocaleString()} people in ${data.pop_year[state.decade]}; ${fmtNum(counted)} big-leaguers per million born in it in the ${state.decade}s`
          + (top ? `, most in ${top[0].split(",")[0]}.` : ".")),
        ids.length ? el("ul", { class: "bm-players" }, ids.slice(0, 12).map((p) =>
          el("li", {}, `${P.name[p]} (b. ${P.born[p]}, ${P.place[p].split(",")[0]}): ${P.G[p].toLocaleString()} G`))) : null,
        ids.length > 12 ? el("p", { class: "small" }, `…and ${ids.length - 12} more.`) : null);
    }

    draw();
  }

  const api = { laea, overlap, tokenize, parse, evaluate, safe, cellSums, namesByDecade, compute, colorAt, roundHalfEven,
    diskPoints, inside, regionPopulation, regionStats, mount };
  if (typeof window !== "undefined") (window.BM_APPS = window.BM_APPS || {}).birthplace_map = api;
  if (typeof module !== "undefined") module.exports = api;
})();
