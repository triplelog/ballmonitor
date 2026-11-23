// Home Turf page: draws the map and panels and drives the rules engine (engine.js). The game is
// saved in the browser (localStorage) after every move.
"use strict";

(async function () {
  const E = window.HomeTurf;
  const $ = (s) => document.querySelector(s);
  const SVGNS = "http://www.w3.org/2000/svg";
  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return n;
  }
  function sv(tag, attrs = {}, ...kids) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
    for (const kid of kids) if (kid) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return n;
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const pct = (p) => `${Math.round(p * 100)}%`;
  const f1 = (x) => (x === null || x === undefined || x <= -9 ? "–" : (Math.round(x * 10) / 10).toFixed(1));
  const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;

  const data = E.prepare(await (await fetch("data/game.json")).json());
  const ix = E.index(data);
  const SAVE = "bm.hometurf.v1", PREFS = "bm.hometurf.prefs.v1", SLOTS = "bm.hometurf.saves.v1";
  // browser storage can be off (private windows) or full: the game still plays, it just isn't saved
  let storageOk = true;
  function lsGet(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
  }
  function lsSet(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { storageOk = false; return false; }
  }
  const prefs = Object.assign({ defend: "auto", defendStrategy: "smart", attackPick: "ask", attackStrategy: "smart", speed: 450 }, lsGet(PREFS, {}));
  let state = lsGet(SAVE, null);
  // ui.run changes whenever a different game starts or loads: an AI loop from the old game stops
  const ui = { sel: null, from: null, mode: null, busy: false, flash: null, run: 0 };
  const save = () => { lsSet(SAVE, state); lsSet(PREFS, prefs); };
  const human = (seat) => seat !== null && seat !== undefined && !state.seats[seat].ai;
  const myTurn = () => state && state.phase !== "over" && human(state.turn);
  const tname = (t) => ix.byId[t].name;
  const rules = () => (state ? E.R(state, data) : data.rules);
  const strengthOf = (tid) => state.stacks[tid].reduce((a, sid) => a + Math.max(0, E.seasonStats(state.soldiers[sid].seasons).median ?? 0), 0);

  // ── map: built once, then updated in place ────────────────────────────────
  const map = { built: false, terr: {} };
  function edgePath(t, o, bend) {
    if (!bend) return null;
    const mx = (t.x + o.x) / 2, my = (t.y + o.y) / 2, dx = o.x - t.x, dy = o.y - t.y, len = Math.hypot(dx, dy) || 1;
    let nx = -dy / len, ny = dx / len;
    if (ny < 0) { nx = -nx; ny = -ny; }   // positive bend = below the straight line
    return `M${t.x},${t.y} Q${mx + nx * bend},${my + ny * bend} ${o.x},${o.y}`;
  }
  function buildMap() {
    const svg = $("#map");
    svg.replaceChildren();
    // each region's area: its territories and the links between them as one soft shape (the group's
    // opacity keeps overlaps from darkening)
    for (const [rid, r] of Object.entries(data.regions)) {
      const mem = data.territories.filter((t) => t.region === rid), ids = new Set(mem.map((t) => t.id));
      const g = sv("g", { class: "region", opacity: 0.2, fill: r.color, stroke: r.color });
      for (const t of mem) {
        for (const n of [...t.land, ...t.sea]) {
          if (ids.has(n) && t.id < n) { const o = ix.byId[n]; g.append(sv("line", { x1: t.x, y1: t.y, x2: o.x, y2: o.y, "stroke-width": 64, "stroke-linecap": "round" })); }
        }
        g.append(sv("circle", { cx: t.x, cy: t.y, r: 46, stroke: "none" }));
      }
      svg.append(g);
    }
    const drawn = new Set(), edges = sv("g", { class: "edges" });
    for (const t of data.territories) {
      for (const [kind, list] of [["land", t.land], ["sea", t.sea]]) {
        for (const n of list) {
          const key = [t.id, n].sort().join("|");
          if (drawn.has(key)) continue;
          drawn.add(key);
          const o = ix.byId[n], bend = (t.bend || {})[n] || (o.bend || {})[t.id];
          const d = edgePath(t, o, bend);
          edges.append(d ? sv("path", { d, class: `edge ${kind}`, fill: "none" }) : sv("line", { x1: t.x, y1: t.y, x2: o.x, y2: o.y, class: `edge ${kind}` }));
        }
      }
    }
    svg.append(edges);
    const nodes = sv("g", { class: "nodes" }), labels = sv("g", { class: "labels" });
    for (const t of data.territories) {
      const g = sv("g", { class: "terr", transform: `translate(${t.x},${t.y})`, tabindex: "0", role: "button" });
      const title = sv("title");
      const ring = sv("circle", { r: 31, class: "ring", visibility: "hidden" });
      const target = sv("circle", { r: 31, class: "target", visibility: "hidden" });
      const body = sv("circle", { r: 24, class: "body", stroke: data.regions[t.region].color });
      const count = sv("text", { class: "count" });
      const badge = sv("text", { class: "badge", x: 21, y: -20 });
      g.append(title, body, ring, target, count, badge);
      g.addEventListener("click", () => onTerritory(t.id));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onTerritory(t.id); } });
      nodes.append(g);
      labels.append(sv("text", { class: "label", x: t.x, y: t.y + 40 }, t.name));
      map.terr[t.id] = { g, title, ring, target, body, count, badge };
    }
    svg.append(nodes, labels);   // labels on top of every line and circle
    map.built = true;
  }
  function drawMap() {
    if (!map.built) buildMap();
    const targets = new Set();
    if (state && ui.from && state.phase === "turn" && myTurn()) {
      if (ui.mode === "fortify") for (const t of E.reachable(state, data, ui.from)) targets.add(t);
      else for (const n of E.neighbours(data, ui.from)) if (E.canAttack(state, data, ui.from, n) || E.canOccupy(state, data, ui.from, n)) targets.add(n);
    }
    for (const t of data.territories) {
      const m = map.terr[t.id], owner = state ? state.owner[t.id] : null, n = state ? state.stacks[t.id].length : 0;
      m.body.setAttribute("fill", owner !== null ? state.seats[owner].color : "#f9fafb");
      m.count.textContent = owner === null ? "+" : String(n);
      m.count.setAttribute("class", `count${owner === null ? " dark" : ""}`);
      const str = state && n ? strengthOf(t.id) : 0;
      m.badge.textContent = str ? f1(str) : "";
      m.ring.setAttribute("visibility", ui.sel === t.id || ui.from === t.id ? "visible" : "hidden");
      m.target.setAttribute("visibility", targets.has(t.id) ? "visible" : "hidden");
      m.g.setAttribute("class", `terr${ui.flash && ui.flash.includes(t.id) ? " flash" : ""}`);
      const who = owner !== null ? state.seats[owner].name : "open";
      m.g.setAttribute("aria-label", `${t.name}, ${who}${owner !== null ? `, ${plural(n, "soldier")}` : ""}`);
      m.title.textContent = `${t.name} (${who})` + (n ? "\n" + state.stacks[t.id].map((sid) => {
        const s = state.soldiers[sid], st = E.seasonStats(s.seasons);
        return `${s.name}: ${plural(st.n, "season")} left, median ${f1(st.median)}`;
      }).join("\n") : "");
    }
    const holders = {};
    if (state && state.phase !== "draft") state.seats.forEach((_, k) => { for (const r of E.regionsHeld(state, data, k)) holders[r] = k; });
    $("#legend").replaceChildren(...Object.entries(data.regions).map(([rid, r]) => {
      const holder = holders[rid];
      return el("span", { class: "chip" }, el("i", { class: "sw", style: `border-color:${r.color};${holder !== undefined ? `background:${state.seats[holder].color}` : ""}` }),
        `${r.name} +${r.bonus}`, holder !== undefined ? ` (${state.seats[holder].name})` : "");
    }), el("span", { class: "chip small" }, "— land border  - - sea lane · small number: the soldiers' combined median WAR"));
  }

  // ── panels ────────────────────────────────────────────────────────────────
  function seatsList() {
    return el("div", { class: "seats" }, state.seats.map((s, k) => {
      const sc = E.score(state, data, k);
      const players = E.owned(state, k).reduce((a, t) => a + state.stacks[t].length, 0);
      return el("div", { class: `seat${k === state.turn && state.phase !== "over" ? " now" : ""}${s.alive ? "" : " out"}` },
        el("i", { class: "dot", style: `background:${s.color}` }), s.name,
        ` · ${plural(sc.territories, "territory", "territories")}${sc.regions ? ` + ${sc.regions} region pts` : ""} · ${plural(players, "player")}`);
    }));
  }
  // a game whose length is counted in innings (9 innings, doubleheader)
  const inningsUnit = () => state.length === "innings" || state.length === "doubleheader";
  const levelLabel = () => { const L = (data.rules.levels || {})[state.level]; return L ? ` · AI: ${L.label}` : ""; };
  function status() {
    if (!state) return "Start a new game.";
    if (state.phase === "over") return `Game over: ${E.act(state, state.winner, "wins")}.`;
    if (state.phase === "draft") return `Draft: pick ${state.draftAt + 1} of ${state.draftOrder.length} · ${E.act(state, state.turn, "is picking")}`;
    const who = state.seats[state.turn];
    if (state.phase === "deploy") return `Opening call-ups · ${who.name}: ${state.pending} to place`;
    const maxR = rules().max_rounds, unit = inningsUnit() ? "Inning" : "Round";
    return `${unit} ${state.round}${maxR ? ` of ${maxR}` : ""} · ${who.name}: ${state.step === "callups" ? `call-ups (${state.pending} left)` : ui.mode === "fortify" ? "move soldiers" : "battles"}${levelLabel()}`;
  }
  function renderPanel() {
    const p = $("#panel");
    if (!state) {
      p.replaceChildren(el("h2", {}, "Home Turf"), el("p", {}, "Claim territories, call up the big-leaguers born there, and battle your neighbors with their real seasons."),
        el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => chooseLength() }, "Start a game against 3 AI managers")));
      return;
    }
    const kids = [el("h2", {}, status()), seatsList()];
    if (!storageOk) kids.push(el("p", { class: "small" }, "This browser isn't saving the game (storage is off or full)."));
    const sel = ui.sel;
    if (state.phase === "over") {
      kids.push(wrap(el("table", { class: "roster" }, el("tr", {}, ["Manager", "Territories", "Region pts", "Total"].map((h) => el("th", {}, h))),
        state.standings.map((s) => el("tr", {}, el("td", {}, state.seats[s.seat].name), el("td", {}, s.territories), el("td", {}, s.regions), el("td", {}, s.total))))),
      el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => chooseLength() }, "Play again")));
    } else if (!myTurn()) {
      kids.push(el("p", { class: "small" }, ui.busy ? "The AI managers are playing…" : ""));
    } else if (state.capture) {
      kids.push(el("p", {}, `You captured ${tname(state.capture.to)}: choose who moves in.`),
        el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => askMoveIn() }, `Move into ${tname(state.capture.to)}`)));
    } else if (state.phase === "draft") {
      const open = sel && state.owner[sel] === null;
      kids.push(el("p", {}, "Your pick: click an open territory (+) to see its bench, then draft it (or click it again). Deep benches mean better call-ups all game; whole regions earn bonus call-ups every turn."),
        open ? el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => draftSel() }, `Draft ${tname(sel)}`)) : null);
    } else if (state.phase === "deploy" || state.step === "callups") {
      const mine = sel && state.owner[sel] === state.turn, next = mine ? E.benchNext(state, data, sel) : null;
      kids.push(el("p", {}, `Click one of your territories to see who's next on its bench, then call him up (or click it again). ${state.pending} left.`),
        el("div", { class: "actions" },
          mine ? el("button", { class: "primary", disabled: !next, onclick: () => placeSel() }, next ? `Call up ${next.name} in ${tname(sel)}` : `${tname(sel)}'s bench is empty`) : null,
          el("button", { onclick: () => autoPlace() }, "Place them for me")));
    } else if (ui.mode === "fortify") {
      kids.push(el("p", {}, ui.from ? `Move from ${tname(ui.from)}: click one of your connected territories.` : "One move: click a territory to move soldiers from, then where to."),
        el("div", { class: "actions" }, el("button", { onclick: () => { ui.mode = "attack"; ui.from = null; render(); } }, "Back to battles"),
          el("button", { class: "primary", onclick: () => endTurn() }, "End turn")));
    } else {
      kids.push(el("p", {}, ui.from ? `Attack from ${tname(ui.from)}: click a highlighted neighbor.` : "Battle: click your territory (2+ soldiers), then an enemy neighbor. Or move soldiers and end your turn."),
        state.lastBattle && state.lastBattle.round === state.round ? battleCard(state.lastBattle) : null,
        el("div", { class: "actions" },
          el("button", { disabled: state.fortified, onclick: () => { ui.mode = "fortify"; ui.from = null; render(); } }, state.fortified ? "Moved this turn" : "Move soldiers"),
          el("button", { onclick: () => autoTurn() }, "Play my turn for me"),
          el("button", { class: "primary", onclick: () => endTurn() }, "End turn")),
        el("div", { class: "actions" },
          el("button", { onclick: () => saveSlot() }, "Save a copy"),
          el("button", { onclick: () => { if (confirm("End the game now and score it?")) { E.finish(state, data); save(); render(); } } }, "End game now")));
    }
    p.replaceChildren(...kids);
  }
  function battleCard(b) {
    const winnerSeat = b.attackerWins ? b.attackerSeat : b.defenderSeat;
    const mine = winnerSeat !== undefined ? human(winnerSeat) : false;
    const A = state.soldiers[b.attacker], D = state.soldiers[b.defender];
    return el("div", { class: `result ${mine ? "win" : "loss"}` },
      el("strong", {}, `${A.name} ${b.aSeason[0]}: ${f1(b.aSeason[1])}`), " vs ", el("strong", {}, `${D.name} ${b.dSeason[0]}: ${f1(b.dSeason[1])} + ${rules().home_field}`),
      el("br"), `${b.attackerWins ? A.name : D.name} wins (the attacker had a ${pct(b.p)} chance)${b.captured ? ` · ${tname(b.to)} captured` : ""}.`);
  }
  const wrap = (table) => el("div", { class: "tw" }, table);
  function soldierRows(tid, opts = {}) {
    const rows = state.stacks[tid].map((sid) => {
      const s = state.soldiers[sid];
      return { sid, s, st: E.seasonStats(s.seasons), mean: E.mean(s) };
    }).sort((a, b) => b.mean - a.mean);
    const head = [["Player"], ["Seasons"], ["Median"], ["Total", "opt"], ["Best", "opt"], ["Worst", "opt"]];
    if (opts.vs) head.push(["Win %"]);
    if (opts.release) head.push([""]);
    return wrap(el("table", { class: "roster" },
      el("tr", {}, head.map(([h, c]) => el("th", { class: c }, h))),
      rows.map(({ sid, s, st }) => el("tr", { class: opts.pick ? "pick" : "", onclick: opts.pick ? () => opts.pick(sid) : null },
        el("td", {}, s.name, s.home !== tid ? el("span", { class: "small" }, ` (${tname(s.home)})`) : ""),
        el("td", {}, st.n), el("td", {}, f1(st.median)), el("td", { class: "opt" }, f1(st.total)), el("td", { class: "opt" }, f1(st.best)),
        el("td", { class: "opt" }, f1(st.worst)),
        opts.vs ? el("td", { class: "pct" }, pct(opts.vs(s))) : null,
        opts.release ? el("td", {}, E.canRelease(state, data, tid, sid) && myTurn() && state.step === "attack"
          ? el("button", { onclick: (e) => { e.stopPropagation(); E.release(state, data, tid, sid); save(); render(); } }, "Release") : "") : null))));
  }
  function renderInfo() {
    const box = $("#info");
    const tid = ui.sel;
    if (!state || !tid) { box.replaceChildren(el("p", { class: "small" }, "Click any territory to see its soldiers and its bench.")); return; }
    const t = ix.byId[tid], owner = state.owner[tid];
    const bench = (data.rosters[tid] || []).slice(state.bench[tid], state.bench[tid] + 5);
    box.replaceChildren(
      el("h2", {}, t.name),
      el("p", { class: "small" }, `${data.regions[t.region].name} · ${owner === null ? "open" : state.seats[owner].name} · born here: ${t.members.join(", ")}`),
      state.stacks[tid].length ? soldierRows(tid, { release: true }) : el("p", { class: "small" }, "No soldiers."),
      el("h3", {}, "Next call-ups here"),
      bench.length ? wrap(el("table", { class: "roster" }, el("tr", {}, [["Player"], ["Born", "opt"], ["Seasons"], ["Median"], ["Total", "opt"], ["Best", "opt"], ["Worst", "opt"]].map(([h, c]) => el("th", { class: c }, h))),
        bench.map((p) => { const st = E.seasonStats(p.seasons); return el("tr", {}, el("td", {}, p.name), el("td", { class: "opt" }, p.born), el("td", {}, st.n),
          el("td", {}, f1(st.median)), el("td", { class: "opt" }, f1(st.total)), el("td", { class: "opt" }, f1(st.best)), el("td", { class: "opt" }, f1(st.worst))); })))
        : el("p", { class: "small" }, "The bench is empty."));
  }
  function renderLog() {
    $("#log").replaceChildren(...state ? state.log.slice(-60).reverse().map((l) => el("li", { class: l.battle ? "battle" : "" }, l.text)) : []);
  }
  function render() { $("#status").textContent = status(); drawMap(); renderPanel(); renderInfo(); renderLog(); }

  // ── dialogs: optional ones close with Esc or a click outside; required ones (moving in after a
  // capture, picking a defender) only by choosing ─────────────────────────────
  let dismissible = true;
  function modal(kids, opts = {}) {
    dismissible = opts.dismiss !== false;
    $("#modal-box").replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
    $("#modal").classList.remove("hidden");
    const first = $("#modal-box").querySelector("button, input, select");
    if (first) first.focus();
  }
  function closeModal() { $("#modal").classList.add("hidden"); }
  $("#modal").addEventListener("click", (e) => { if (e.target === $("#modal") && dismissible) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && dismissible && !$("#modal").classList.contains("hidden")) closeModal(); });

  // ── human actions ─────────────────────────────────────────────────────────
  async function onTerritory(tid) {
    const again = ui.sel === tid;
    ui.sel = tid;
    if (!state || ui.busy || !myTurn() || state.capture) { render(); return; }
    try {
      if (state.phase === "draft") {
        if (again && state.owner[tid] === null) return draftSel();
      } else if (state.phase === "deploy" || state.step === "callups") {
        if (again && state.owner[tid] === state.turn && E.benchNext(state, data, tid)) return placeSel();
      } else if (ui.mode === "fortify") {
        if (!state.fortified && ui.from && state.owner[tid] === state.turn && tid !== ui.from && E.connected(state, data, ui.from, tid)) { askFortify(ui.from, tid); return; }
        if (state.owner[tid] === state.turn && state.stacks[tid].length > 1) ui.from = tid;
      } else {
        if (ui.from && E.canOccupy(state, data, ui.from, tid)) { E.occupy(state, data, ui.from, tid); save(); if (state.capture) askMoveIn(); render(); return; }
        if (ui.from && E.canAttack(state, data, ui.from, tid)) { await attack(ui.from, tid); return; }
        ui.mode = "attack";
        ui.from = state.owner[tid] === state.turn && state.stacks[tid].length >= 2 ? tid : null;
      }
    } catch (e) { alert(e.message); }
    render();
  }
  async function draftSel() {
    if (!myTurn() || state.phase !== "draft" || state.owner[ui.sel] !== null) return;
    E.draft(state, data, ui.sel);
    save(); render(); await advance();
  }
  async function placeSel() {
    if (!myTurn() || state.owner[ui.sel] !== state.turn) return;
    try { E.place(state, data, ui.sel); } catch (e) { alert(e.message); return; }
    save(); render(); await advance();
  }
  function autoPlace() { if (!myTurn()) return; E.aiPlace(state, data); save(); render(); advance(); }

  async function attack(from, to) {
    // the defender's pick is made before (and without seeing) yours
    const theirs = state.stacks[to];
    const sd = E.pickSoldier(state, data, theirs, state.stacks[from], "defend", state.seats[state.owner[to]].strategy);
    const go = (sa) => {
      closeModal();
      E.battle(state, data, from, to, sa, sd);
      save();
      if (state.capture) { render(); return askMoveIn(); }
      if (state.stacks[from].length < 2) ui.from = null;
      render();
    };
    if (prefs.attackPick === "auto") return go(E.pickSoldier(state, data, state.stacks[from], theirs, "attack", prefs.attackStrategy));
    const home = rules().home_field;
    const vs = (s) => theirs.reduce((a, o) => a + E.winProb(s, state.soldiers[o], home), 0) / theirs.length;
    modal([el("h2", {}, `${tname(from)} attacks ${tname(to)}`),
      el("p", { class: "small" }, `Pick your hitter or pitcher. ${state.seats[state.owner[to]].name} picks a defender at the same time without seeing yours. Each plays one random remaining season (it's used up); the defender adds ${home}. Win %: your chance against their average soldier.`),
      el("h3", {}, "Their soldiers"), soldierRows(to),
      el("h3", {}, "Yours: click one"), soldierRows(from, { pick: go, vs }),
      el("div", { class: "actions sticky" },
        el("button", { onclick: () => go(E.pickSoldier(state, data, state.stacks[from], theirs, "attack", prefs.attackStrategy)) }, "Pick for me"),
        el("button", { onclick: () => closeModal() }, "Cancel"))]);
  }
  // after a capture: choose exactly who moves in (at least one goes, at least one stays)
  function askMoveIn() {
    const c = state.capture;
    if (!c) return;
    const from = state.stacks[c.from];
    const ordered = [...from].sort((x, y) => E.mean(state.soldiers[y]) - E.mean(state.soldiers[x]));
    if (ordered.length === 2) { E.moveIn(state, data, [ordered[0]]); ui.from = null; save(); render(); return; }
    const picked = new Set([ordered[0]]);
    const boxes = ordered.map((sid) => {
      const s = state.soldiers[sid], st = E.seasonStats(s.seasons);
      const box = el("input", { type: "checkbox", checked: picked.has(sid), onchange: (e) => { e.target.checked ? picked.add(sid) : picked.delete(sid); note(); } });
      box.dataset.sid = sid;
      return el("label", {}, box, ` ${s.name}: ${plural(st.n, "season")} left, median ${f1(st.median)}, total ${f1(st.total)}`);
    });
    const msg = el("p", { class: "small" });
    const note = () => { msg.textContent = `${picked.size} moving, ${ordered.length - picked.size} staying in ${tname(c.from)}.`; };
    const set = (list) => { picked.clear(); list.forEach((s) => picked.add(s)); boxes.forEach((b) => { const i = b.querySelector("input"); i.checked = picked.has(i.dataset.sid); }); note(); };
    note();
    modal([el("h2", {}, `You captured ${tname(c.to)}!`), el("p", {}, `Who moves in from ${tname(c.from)}?`),
      el("div", { class: "actions" },
        el("button", { onclick: () => set([ordered[0]]) }, "Strongest"),
        el("button", { onclick: () => set([ordered[ordered.length - 1]]) }, "Weakest"),
        el("button", { onclick: () => set(ordered.slice(0, Math.ceil((ordered.length - 1) / 2))) }, "Half"),
        el("button", { onclick: () => set(ordered.slice(0, ordered.length - 1)) }, "All but one")),
      ...boxes, msg,
      el("div", { class: "actions sticky" }, el("button", { class: "primary", onclick: () => {
        try { E.moveIn(state, data, [...picked]); closeModal(); ui.from = null; save(); render(); } catch (e) { alert(e.message); }
      } }, "Move in"))], { dismiss: false });
  }
  function askFortify(from, to) {
    const picked = new Set();
    const rows = state.stacks[from].map((sid) => {
      const s = state.soldiers[sid], st = E.seasonStats(s.seasons);
      return el("label", {}, el("input", { type: "checkbox", onchange: (e) => { e.target.checked ? picked.add(sid) : picked.delete(sid); } }),
        ` ${s.name}: ${plural(st.n, "season")} left, median ${f1(st.median)}, total ${f1(st.total)}`);
    });
    modal([el("h2", {}, `Move from ${tname(from)} to ${tname(to)}`), el("p", { class: "small" }, "One move per turn. Leave at least one soldier."), ...rows,
      el("div", { class: "actions sticky" }, el("button", { class: "primary", onclick: () => {
        try { E.fortify(state, data, from, to, [...picked]); closeModal(); ui.from = null; save(); render(); } catch (e) { alert(e.message); }
      } }, "Move"), el("button", { onclick: () => closeModal() }, "Cancel"))]);
  }
  function endTurn() {
    if (!myTurn() || state.capture) return;
    ui.mode = null; ui.from = null;
    E.endTurn(state, data);
    save();
    render();
    advance();
  }
  async function autoTurn() {
    if (!myTurn() || ui.busy) return;
    const run = ui.run;
    ui.busy = true;
    await playAI(run, true);
    if (run !== ui.run) return;
    ui.busy = false;
    if (state.phase !== "over" && myTurn()) endTurn();
  }

  // ── the AI managers ───────────────────────────────────────────────────────
  // a human defender: ask (if prefs.defend === "ask", and there is a choice) or autorank
  function humanDefend(to, from) {
    const mine = state.stacks[to];
    if (prefs.defend !== "ask" || mine.length === 1) return Promise.resolve(mine.length === 1 ? mine[0] : E.pickSoldier(state, data, mine, state.stacks[from], "defend", prefs.defendStrategy));
    return new Promise((resolve) => {
      const home = rules().home_field;
      const vs = (s) => state.stacks[from].reduce((a, o) => a + (1 - E.winProb(state.soldiers[o], s, home)), 0) / state.stacks[from].length;
      modal([el("h2", {}, `${E.act(state, state.turn, "attacks")} ${tname(to)} from ${tname(from)}`),
        el("p", { class: "small" }, `Pick your defender (you get +${home}). They have already picked their attacker.`),
        el("h3", {}, "Their soldiers"), soldierRows(from),
        el("h3", {}, "Yours: click one"), soldierRows(to, { pick: (sid) => { closeModal(); resolve(sid); }, vs }),
        el("div", { class: "actions sticky" }, el("button", { onclick: () => { closeModal(); resolve(E.pickSoldier(state, data, mine, state.stacks[from], "defend", prefs.defendStrategy)); } }, "Pick for me"))],
      { dismiss: false });
    });
  }
  async function playAI(run, forHuman = false) {
    const seat = state.turn;
    E.aiStart(state, data);
    render();
    let a;
    while (run === ui.run && state.phase === "turn" && state.turn === seat && (a = E.aiNextAttack(state, data))) {
      ui.flash = [a.from, a.to];
      const sd = human(state.owner[a.to]) && !forHuman ? await humanDefend(a.to, a.from)
        : E.pickSoldier(state, data, state.stacks[a.to], state.stacks[a.from], "defend", state.seats[state.owner[a.to]].strategy);
      if (run !== ui.run) return;
      E.battle(state, data, a.from, a.to, a.attacker, sd);
      E.aiAfterBattle(state, data);
      save();
      render();
      await sleep(prefs.speed);
    }
    ui.flash = null;
    if (run === ui.run && state.phase === "turn" && state.turn === seat) E.aiFortify(state, data);
  }
  async function advance() {
    if (ui.busy) return;
    const run = ui.run;
    ui.busy = true;
    try {
      while (run === ui.run && state && state.phase !== "over" && !myTurn()) {
        if (state.phase === "draft") { E.aiDraft(state, data); await sleep(prefs.speed / 3); }
        else if (state.phase === "deploy") { E.aiPlace(state, data); }
        else { await playAI(run); if (run !== ui.run) return; if (state.phase !== "over") E.endTurn(state, data); }
        if (run !== ui.run) return;
        save();
        render();
      }
      if (state && myTurn() && state.phase === "turn" && state.step === "callups" && !E.canPlace(state, data)) E.skipPlacement(state, data);
    } finally {
      if (run === ui.run) { ui.busy = false; render(); }
    }
  }
  // a different game takes over: stop any AI loop from the old one
  function switchTo(newState) {
    ui.run++;
    ui.busy = false;
    ui.sel = null; ui.from = null; ui.mode = null; ui.flash = null;
    state = newState;
    closeModal();
    save();
    render();
    if (myTurn() && state.capture) askMoveIn();
    advance();
  }
  function chooseLength() {
    const lengths = data.rules.lengths || {}, levels = data.rules.levels || {};
    let length = lengths[prefs.length] ? prefs.length : data.rules.default_length;
    let level = levels[prefs.level] ? prefs.level : data.rules.default_level;
    const group = (name, items, get, set) => el("div", { class: "lengths", role: "radiogroup", "aria-label": name }, Object.entries(items).map(([id, L]) => {
      const b = el("button", { class: id === get() ? "primary" : "", "aria-pressed": String(id === get()), onclick: () => {
        set(id); for (const o of b.parentNode.querySelectorAll("button")) { o.classList.toggle("primary", o === b); o.setAttribute("aria-pressed", String(o === b)); } } }, L.label);
      return [b, el("span", { class: "small" }, L.note || "")];
    }).flat());
    modal([el("h2", {}, "New game"), el("p", {}, "You against three AI managers."),
      el("h3", {}, "How long?"), group("Game length", lengths, () => length, (v) => { length = v; }),
      Object.keys(levels).length ? [el("h3", {}, "How good are the AI managers?"), group("AI ability", levels, () => level, (v) => { level = v; })] : null,
      el("p", { class: "small" }, "Every game is saved in this browser as you play; come back any time to carry on. Use \"Save a copy\" to keep several."),
      el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => { prefs.length = length; prefs.level = level; closeModal(); startGame(length, level); } }, "Start"),
        el("button", { onclick: () => closeModal() }, "Cancel"))]);
  }
  // named copies of games (the current game is always saved on its own)
  const slots = () => lsGet(SLOTS, []);
  function saveSlot() {
    const unit = inningsUnit() ? "inning" : "round";
    const name = prompt("Name this save:", `${rules().max_rounds ? "" : "No limit, "}${unit} ${state.round}, ${new Date().toLocaleDateString()}`);
    if (!name) return;
    const list = slots().filter((s) => s.name !== name);
    list.unshift({ name, saved: new Date().toISOString(), state });
    alert(lsSet(SLOTS, list.slice(0, 8)) ? "Saved." : "Couldn't save: this browser's storage is off or full.");
  }
  function showSlots() {
    const list = slots();
    modal([el("h2", {}, "Saved games"),
      list.length ? wrap(el("table", { class: "roster" }, list.map((s, k) => el("tr", {},
        el("td", {}, s.name), el("td", { class: "small" }, new Date(s.saved).toLocaleString()),
        el("td", {}, el("button", { onclick: () => { if (state && state.phase !== "over" && !confirm("Load it? Your current game is replaced (save a copy first if you want it).")) return;
          switchTo(s.state); } }, "Load")),
        el("td", {}, el("button", { onclick: () => { const l = slots(); l.splice(k, 1); lsSet(SLOTS, l); showSlots(); } }, "Delete"))))))
        : el("p", { class: "small" }, "No saved copies yet. During your turn, use \"Save a copy\"."),
      el("div", { class: "actions" }, state && state.phase !== "over" ? el("button", { onclick: () => { closeModal(); saveSlot(); } }, "Save the current game") : null,
        el("button", { class: "primary", onclick: () => closeModal() }, "Close"))]);
  }
  function startGame(length, level) {
    switchTo(E.newGame(data, { seed: `${new Date().toISOString()}-${Math.random()}`, name: "You", length, level }));
  }

  // ── settings and help ─────────────────────────────────────────────────────
  $("#btn-new").addEventListener("click", () => { if (!state || state.phase === "over" || confirm("Start a new game? This one will be replaced (use Saves to keep a copy).")) chooseLength(); });
  $("#btn-saves").addEventListener("click", () => showSlots());
  $("#btn-settings").addEventListener("click", () => {
    const sel = (key, options) => el("select", { onchange: (e) => { prefs[key] = isNaN(+e.target.value) ? e.target.value : +e.target.value; save(); } },
      options.map(([v, label]) => el("option", { value: v, selected: String(prefs[key]) === String(v) }, label)));
    const strategies = [["smart", "Smart: the cheapest player who is at least even"], ["best", "Best: my strongest"], ["weakest", "Weakest: save my stars"]];
    modal([el("h2", {}, "Settings"),
      el("label", {}, "When I'm attacked: ", sel("defend", [["auto", "pick my defender automatically"], ["ask", "ask me (if I have a choice)"]])),
      el("label", {}, "Automatic defender: ", sel("defendStrategy", strategies)),
      el("label", {}, "When I attack: ", sel("attackPick", [["ask", "let me pick my player"], ["auto", "pick automatically"]])),
      el("label", {}, "Automatic attacker: ", sel("attackStrategy", strategies)),
      el("label", {}, "AI speed: ", sel("speed", [[150, "fast"], [450, "normal"], [900, "slow"]])),
      el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => { closeModal(); render(); } }, "Done"))]);
  });
  $("#btn-help").addEventListener("click", () => {
    const r = rules();
    modal([el("h2", {}, "How to play"),
      el("p", {}, `Four managers (you and three AIs) snake-draft the ${data.territories.length} territories, grouped in ${Object.keys(data.regions).length} regions (the shaded areas). Every territory's soldiers are real big-leaguers born there, called up best first (by career Open WAR). Click a territory to see its soldiers and bench before you draft or call up.`),
      el("p", {}, `After the draft each manager places ${r.start_callups} call-ups. Each turn: call-ups (one per ${r.territories_per_callup} territories, at least ${r.callups_min}, plus the bonus of every region you hold whole), then battles, then one move of soldiers between your connected territories.`),
      el("p", {}, `A battle: you pick one of your soldiers, the defender picks one at the same time. Each plays one of his real seasons at random, and that season is used up. The defender adds ${r.home_field} WAR for home field; the higher season wins (a tie goes to the defender) and the loser is out of the game. Take a territory's last soldier and it's yours, with its bench of natives; you choose who moves in.`),
      el("p", {}, `A soldier who runs out of seasons retires and his territory calls up a replacement; one whose best remaining season is under ${r.release_below} WAR can be released for a call-up. A territory left with no soldiers can be walked into from next door.`),
      el("p", {}, `Choose the length when you start (${Object.values(data.rules.lengths || {}).map((L) => L.label).join(", ")}) and how good the AI managers are (${Object.values(data.rules.levels || {}).map((L) => L.label).join(", ")}). At the end: 1 point per territory plus the bonus of every region you hold (or hold every territory to win outright). "End game now" scores it at any time. Settings let the game pick your players for you.`),
      el("p", { class: "small" }, `Seasons: ${data.source}.`),
      el("div", { class: "actions sticky" }, el("button", { class: "primary", onclick: () => closeModal() }, "Got it"))]);
  });

  render();
  if (state && state.phase !== "over") {
    if (myTurn() && state.capture) askMoveIn();   // reloaded in the middle of moving into a capture
    advance();
  }
})();
