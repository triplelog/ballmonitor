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
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
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
  const f1 = (x) => (x <= -9 ? "–" : (Math.round(x * 10) / 10).toFixed(1));

  const data = E.prepare(await (await fetch("data/game.json")).json());
  const ix = E.index(data);
  const SAVE = "bm.hometurf.v1", PREFS = "bm.hometurf.prefs.v1", SLOTS = "bm.hometurf.saves.v1";
  const prefs = Object.assign({ defend: "auto", defendStrategy: "smart", attackPick: "ask", attackStrategy: "smart", speed: 450 },
    JSON.parse(localStorage.getItem(PREFS) || "{}"));
  let state = null;
  try { state = JSON.parse(localStorage.getItem(SAVE) || "null"); } catch (e) { state = null; }
  const ui = { sel: null, from: null, mode: null, busy: false, flash: null };
  const save = () => { localStorage.setItem(SAVE, JSON.stringify(state)); localStorage.setItem(PREFS, JSON.stringify(prefs)); };
  const human = (seat) => seat !== null && seat !== undefined && !state.seats[seat].ai;
  const myTurn = () => state && state.phase !== "over" && human(state.turn);
  const tname = (t) => ix.byId[t].name;

  // ── map ───────────────────────────────────────────────────────────────────
  function drawMap() {
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
    const drawn = new Set();
    for (const t of data.territories) {
      for (const [kind, list] of [["land", t.land], ["sea", t.sea]]) {
        for (const n of list) {
          const key = [t.id, n].sort().join("|");
          if (drawn.has(key)) continue;
          drawn.add(key);
          const o = ix.byId[n];
          svg.append(sv("line", { x1: t.x, y1: t.y, x2: o.x, y2: o.y, class: `edge ${kind}` }));
        }
      }
    }
    const targets = new Set();
    if (state && ui.from && state.phase === "turn" && myTurn()) {
      for (const n of E.neighbours(data, ui.from)) {
        if (ui.mode === "attack" && E.canAttack(state, data, ui.from, n)) targets.add(n);
        if (ui.mode === "fortify" && n !== ui.from) for (const t of E.owned(state, state.turn)) if (t !== ui.from && E.connected(state, data, ui.from, t)) targets.add(t);
      }
    }
    for (const t of data.territories) {
      const owner = state ? state.owner[t.id] : null;
      const n = state ? state.stacks[t.id].length : 0;
      const g = sv("g", { class: `terr${ui.flash && ui.flash.includes(t.id) ? " flash" : ""}`, transform: `translate(${t.x},${t.y})`, tabindex: "0",
        role: "button", "aria-label": `${t.name}${owner !== null ? `, ${state.seats[owner].name}, ${n} soldiers` : ", open"}` });
      g.append(sv("circle", { r: 24, class: "body", fill: owner !== null ? state.seats[owner].color : "#f9fafb", stroke: data.regions[t.region].color }));
      if (ui.sel === t.id || ui.from === t.id) g.append(sv("circle", { r: 31, class: "ring" }));
      if (targets.has(t.id)) g.append(sv("circle", { r: 31, class: "target" }));
      g.append(sv("text", { class: `count${owner === null ? " dark" : ""}` }, owner === null ? "+" : String(n)));
      g.append(sv("text", { class: "label", y: 40 }, t.name));
      g.addEventListener("click", () => onTerritory(t.id));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onTerritory(t.id); } });
      svg.append(g);
    }
    const legend = $("#legend");
    legend.replaceChildren(...Object.entries(data.regions).map(([rid, r]) => {
      const holder = state && state.phase !== "draft" ? state.seats.findIndex((_, k) => E.regionsHeld(state, data, k).includes(rid)) : -1;
      return el("span", { class: "chip" }, el("i", { class: "sw", style: `border-color:${r.color};${holder >= 0 ? `background:${state.seats[holder].color}` : ""}` }),
        `${r.name} +${r.bonus}`, holder >= 0 ? ` (${state.seats[holder].name})` : "");
    }), el("span", { class: "chip small" }, "— land border  - - sea lane"));
  }

  // ── panels ────────────────────────────────────────────────────────────────
  function seatsList() {
    return el("div", { class: "seats" }, state.seats.map((s, k) => {
      const sc = E.score(state, data, k);
      return el("div", { class: `seat${k === state.turn && state.phase !== "over" ? " now" : ""}${s.alive ? "" : " out"}` },
        el("i", { class: "dot", style: `background:${s.color}` }), s.name,
        ` · ${sc.territories} territories${sc.regions ? ` + ${sc.regions} region pts` : ""} · `
          + `${E.owned(state, k).reduce((a, t) => a + state.stacks[t].length, 0)} players`);
    }));
  }
  function status() {
    if (!state) return "Start a new game.";
    const who = state.seats[state.turn];
    if (state.phase === "over") return `Game over: ${state.seats[state.winner].name} win${state.winner === 0 ? "" : "s"}.`;
    if (state.phase === "draft") return `Draft: pick ${state.draftAt + 1} of ${state.draftOrder.length} · ${who.name}${who.ai ? " are" : " are"} picking`;
    if (state.phase === "deploy") return `Opening call-ups · ${who.name}: ${state.pending} to place`;
    const maxR = E.R(state, data).max_rounds, unit = state.length === "innings" ? "Inning" : "Round";
    return `${unit} ${state.round}${maxR ? ` of ${maxR}` : ""} · ${who.name}: ${state.step === "callups" ? `call-ups (${state.pending} left)` : ui.mode === "fortify" ? "move soldiers" : "battles"}`;
  }
  function renderPanel() {
    const p = $("#panel");
    if (!state) {
      p.replaceChildren(el("h2", {}, "Home Turf"), el("p", {}, "Claim territories, call up the big-leaguers born there, and battle your neighbors with their real seasons."),
        el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => chooseLength() }, "Start a game against 3 AI managers")));
      return;
    }
    const kids = [el("h2", {}, status()), seatsList()];
    if (state.phase === "over") {
      kids.push(el("table", { class: "roster" }, el("tr", {}, ["Manager", "Territories", "Region pts", "Total"].map((h) => el("th", {}, h))),
        state.standings.map((s) => el("tr", {}, el("td", {}, state.seats[s.seat].name), el("td", {}, s.territories), el("td", {}, s.regions), el("td", {}, s.total)))),
      el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => chooseLength() }, "Play again")));
    } else if (!myTurn()) {
      kids.push(el("p", { class: "small" }, ui.busy ? "The AI managers are playing…" : ""));
    } else if (state.phase === "draft") {
      kids.push(el("p", {}, "Your pick: click an open territory (+). Deep benches mean better call-ups all game; whole regions earn bonus call-ups every turn."));
    } else if (state.phase === "deploy" || state.step === "callups") {
      kids.push(el("p", {}, `Click one of your territories to call up its best remaining native (${state.pending} left).`),
        el("div", { class: "actions" }, el("button", { onclick: () => autoPlace() }, "Place them for me")));
    } else if (ui.mode === "fortify") {
      kids.push(el("p", {}, ui.from ? `Move from ${tname(ui.from)}: click one of your connected territories.` : "One move: click a territory to move soldiers from, then where to."),
        el("div", { class: "actions" }, el("button", { onclick: () => { ui.mode = "attack"; ui.from = null; render(); } }, "Back to battles"),
          el("button", { class: "primary", onclick: () => endTurn() }, "End turn")));
    } else {
      kids.push(el("p", {}, ui.from ? `Attack from ${tname(ui.from)}: click a highlighted neighbor.` : "Battle: click your territory (2+ soldiers), then an enemy neighbor. Or move soldiers and end your turn."),
        state.lastBattle && state.lastBattle.round === state.round ? battleCard(state.lastBattle) : null,
        el("div", { class: "actions" },
          el("button", { onclick: () => { ui.mode = "fortify"; ui.from = null; render(); } }, state.fortified ? "Moved this turn" : "Move soldiers"),
          el("button", { onclick: () => autoTurn() }, "Play my turn for me"),
          el("button", { class: "primary", onclick: () => endTurn() }, "End turn")),
        el("div", { class: "actions" },
          el("button", { onclick: () => saveSlot() }, "Save a copy"),
          el("button", { onclick: () => { if (confirm("End the game now and score it?")) { E.finish(state, data); save(); render(); } } }, "End game now")));
    }
    p.replaceChildren(...kids);
  }
  function battleCard(b) {
    const mine = human(state.owner[b.attackerWins ? b.to : b.from]) || (b.attackerWins && human(state.owner[b.to]));
    const A = state.soldiers[b.attacker], D = state.soldiers[b.defender];
    return el("div", { class: `result ${mine ? "win" : "loss"}` },
      el("strong", {}, `${A.name} ${b.aSeason[0]}: ${f1(b.aSeason[1])}`), " vs ", el("strong", {}, `${D.name} ${b.dSeason[0]}: ${f1(b.dSeason[1])} + ${data.rules.home_field}`),
      el("br"), `${b.attackerWins ? A.name : D.name} wins (the attacker had a ${pct(b.p)} chance)${b.captured ? ` · ${tname(b.to)} captured` : ""}.`);
  }
  function soldierRows(tid, opts = {}) {
    const rows = state.stacks[tid].map((sid) => {
      const s = state.soldiers[sid];
      return { sid, s, st: E.seasonStats(s.seasons), mean: E.mean(s) };
    }).sort((a, b) => b.mean - a.mean);
    return el("table", { class: "roster" },
      el("tr", {}, ["Player", "Seasons", "Median", "Total", "Best", "Worst", opts.vs ? "Win %" : "", ""].map((h) => el("th", {}, h))),
      rows.map(({ sid, s, st }) => el("tr", { class: opts.pick ? "pick" : "", onclick: opts.pick ? () => opts.pick(sid) : null },
        el("td", {}, s.name, s.home !== tid ? el("span", { class: "small" }, ` (${tname(s.home)})`) : ""),
        el("td", {}, st.n), el("td", {}, f1(st.median ?? -9)), el("td", {}, f1(st.total)), el("td", {}, f1(st.best ?? -9)), el("td", {}, f1(st.worst ?? -9)),
        el("td", { class: "pct" }, opts.vs ? pct(opts.vs(s)) : ""),
        el("td", {}, opts.release && E.canRelease(state, data, tid, sid) && myTurn() && state.step === "attack"
          ? el("button", { onclick: (e) => { e.stopPropagation(); E.release(state, data, tid, sid); save(); render(); } }, "Release") : ""))));
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
      bench.length ? el("table", { class: "roster" }, el("tr", {}, ["Player", "Born", "Seasons", "Median", "Total", "Best", "Worst"].map((h) => el("th", {}, h))),
        bench.map((p) => { const st = E.seasonStats(p.seasons); return el("tr", {}, el("td", {}, p.name), el("td", {}, p.born), el("td", {}, st.n),
          el("td", {}, f1(st.median)), el("td", {}, f1(st.total)), el("td", {}, f1(st.best)), el("td", {}, f1(st.worst))); }))
        : el("p", { class: "small" }, "The bench is empty."));
  }
  function renderLog() {
    $("#log").replaceChildren(...state ? state.log.slice(-60).reverse().map((l) => el("li", { class: l.battle ? "battle" : "" }, l.text)) : []);
  }
  function render() { $("#status").textContent = status(); drawMap(); renderPanel(); renderInfo(); renderLog(); }

  // ── modal helpers ─────────────────────────────────────────────────────────
  function modal(...kids) { $("#modal-box").replaceChildren(...kids); $("#modal").classList.remove("hidden"); }
  function closeModal() { $("#modal").classList.add("hidden"); }

  // ── human actions ─────────────────────────────────────────────────────────
  async function onTerritory(tid) {
    ui.sel = tid;
    if (!state || ui.busy || !myTurn()) { render(); return; }
    try {
      if (state.phase === "draft") {
        if (state.owner[tid] === null) { E.draft(state, data, tid); save(); render(); await advance(); return; }
      } else if (state.phase === "deploy" || state.step === "callups") {
        if (state.owner[tid] === state.turn) { E.place(state, data, tid); save(); render(); await advance(); return; }
      } else if (ui.mode === "fortify") {
        if (!state.fortified && ui.from && state.owner[tid] === state.turn && tid !== ui.from && E.connected(state, data, ui.from, tid)) { askFortify(ui.from, tid); return; }
        if (state.owner[tid] === state.turn && state.stacks[tid].length > 1) ui.from = tid;
      } else {
        if (ui.from && E.canAttack(state, data, ui.from, tid)) { await attack(ui.from, tid); return; }
        ui.mode = "attack";
        ui.from = state.owner[tid] === state.turn && state.stacks[tid].length >= 2 ? tid : null;
      }
    } catch (e) { alert(e.message); }
    render();
  }
  function autoPlace() { if (!myTurn()) return; E.aiPlace(state, data); save(); render(); advance(); }

  async function attack(from, to) {
    // the defender's pick is made before (and without seeing) yours
    const theirs = state.stacks[to];
    const defenderPick = (sa) => E.pickSoldier(state, data, theirs, state.stacks[from], "defend", state.seats[state.owner[to]].strategy);
    const go = (sa) => {
      closeModal();
      const sd = defenderPick(sa);
      const r = E.battle(state, data, from, to, sa, sd);
      save();
      if (state.capture) return askMoveIn();
      if (state.stacks[from].length < 2) ui.from = null;
      render();
      if (state.phase === "over") render();
    };
    if (prefs.attackPick === "auto") return go(E.pickSoldier(state, data, state.stacks[from], theirs, "attack", prefs.attackStrategy));
    const vs = (s) => theirs.reduce((a, o) => a + E.winProb(s, state.soldiers[o], data.rules.home_field), 0) / theirs.length;
    modal(el("h2", {}, `${tname(from)} attacks ${tname(to)}`),
      el("p", { class: "small" }, `Pick your hitter or pitcher. ${state.seats[state.owner[to]].name} picks a defender at the same time without seeing yours. Each plays one random remaining season (it's used up); the defender adds ${data.rules.home_field}. Win %: your chance against their average soldier.`),
      el("h3", {}, "Their soldiers"), soldierRows(to),
      el("h3", {}, "Yours: click one"), soldierRows(from, { pick: go, vs }),
      el("div", { class: "actions" },
        el("button", { onclick: () => go(E.pickSoldier(state, data, state.stacks[from], theirs, "attack", prefs.attackStrategy)) }, "Pick for me"),
        el("button", { onclick: () => closeModal() }, "Cancel")));
  }
  function askMoveIn() {
    const c = state.capture, max = state.stacks[c.from].length - 1;
    const choose = (n) => { closeModal(); E.moveIn(state, data, n); ui.from = null; save(); render(); };
    if (max <= 1) return choose(1);
    modal(el("h2", {}, `You captured ${tname(c.to)}!`), el("p", {}, `Move how many soldiers in from ${tname(c.from)}? (strongest first)`),
      el("div", { class: "actions" }, [...new Set([1, Math.ceil(max / 2), max])].map((n) => el("button", { onclick: () => choose(n) }, `${n}`))));
  }
  function askFortify(from, to) {
    const picked = new Set();
    const rows = state.stacks[from].map((sid) => {
      const s = state.soldiers[sid];
      return el("label", {}, el("input", { type: "checkbox", onchange: (e) => { e.target.checked ? picked.add(sid) : picked.delete(sid); } }),
        ` ${s.name}: ${s.seasons.length} seasons left, median ${f1(E.seasonStats(s.seasons).median ?? -9)}, total ${f1(E.seasonStats(s.seasons).total)}`);
    });
    modal(el("h2", {}, `Move from ${tname(from)} to ${tname(to)}`), el("p", { class: "small" }, "One move per turn. Leave at least one soldier."), ...rows,
      el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => {
        try { E.fortify(state, data, from, to, [...picked]); closeModal(); ui.from = null; save(); render(); } catch (e) { alert(e.message); }
      } }, "Move"), el("button", { onclick: () => closeModal() }, "Cancel")));
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
    if (!myTurn()) return;
    ui.busy = true;
    await playAI(true);
    ui.busy = false;
    if (state.phase !== "over" && myTurn()) endTurn();
  }

  // ── the AI managers ───────────────────────────────────────────────────────
  // a human defender: ask (if prefs.defend === "ask") or autorank
  function humanDefend(to, from) {
    if (prefs.defend !== "ask") return Promise.resolve(E.pickSoldier(state, data, state.stacks[to], state.stacks[from], "defend", prefs.defendStrategy));
    return new Promise((resolve) => {
      const vs = (s) => state.stacks[from].reduce((a, o) => a + (1 - E.winProb(state.soldiers[o], s, data.rules.home_field)), 0) / state.stacks[from].length;
      modal(el("h2", {}, `${state.seats[state.turn].name} attack ${tname(to)} from ${tname(from)}`),
        el("p", { class: "small" }, `Pick your defender (you get +${data.rules.home_field}). They have already picked their attacker.`),
        el("h3", {}, "Their soldiers"), soldierRows(from),
        el("h3", {}, "Yours: click one"), soldierRows(to, { pick: (sid) => { closeModal(); resolve(sid); }, vs }),
        el("div", { class: "actions" }, el("button", { onclick: () => { closeModal(); resolve(E.pickSoldier(state, data, state.stacks[to], state.stacks[from], "defend", prefs.defendStrategy)); } }, "Pick for me")));
    });
  }
  async function playAI(forHuman = false) {
    const seat = state.turn;
    E.aiStart(state, data);
    render();
    let a;
    while (state.phase === "turn" && state.turn === seat && (a = E.aiNextAttack(state, data))) {
      ui.flash = [a.from, a.to];
      const sd = human(state.owner[a.to]) && !forHuman ? await humanDefend(a.to, a.from)
        : E.pickSoldier(state, data, state.stacks[a.to], state.stacks[a.from], "defend", state.seats[state.owner[a.to]].strategy);
      E.battle(state, data, a.from, a.to, a.attacker, sd);
      E.aiAfterBattle(state, data);
      save();
      render();
      await sleep(prefs.speed);
    }
    ui.flash = null;
    if (state.phase === "turn" && state.turn === seat) E.aiFortify(state, data);
  }
  async function advance() {
    if (ui.busy) return;
    ui.busy = true;
    try {
      while (state && state.phase !== "over" && !myTurn()) {
        if (state.phase === "draft") { E.aiDraft(state, data); await sleep(prefs.speed / 3); }
        else if (state.phase === "deploy") { E.aiPlace(state, data); }
        else { await playAI(); if (state.phase !== "over") E.endTurn(state, data); }
        save();
        render();
      }
      if (state && myTurn() && state.phase === "turn" && state.step === "callups" && !E.canPlace(state, data)) E.skipPlacement(state, data);
    } finally {
      ui.busy = false;
      render();
    }
  }
  function chooseLength() {
    const lengths = data.rules.lengths || { standard: { label: `${data.rules.max_rounds} rounds` } };
    modal(el("h2", {}, "New game"), el("p", {}, "You against three AI managers. How long a game?"),
      ...Object.entries(lengths).map(([id, L]) => el("div", { class: "actions" },
        el("button", { class: id === "innings" ? "primary" : "", onclick: () => { closeModal(); startGame(id); } }, L.label),
        el("span", { class: "small" }, L.note || ""))),
      el("p", { class: "small" }, "Every game is saved in this browser as you play; come back any time to carry on. Use \"Save a copy\" to keep several."),
      el("div", { class: "actions" }, el("button", { onclick: () => closeModal() }, "Cancel")));
  }
  // named copies of games (the current game is always saved on its own)
  const slots = () => JSON.parse(localStorage.getItem(SLOTS) || "[]");
  function saveSlot() {
    const unit = state.length === "innings" ? "inning" : "round";
    const name = prompt("Name this save:", `${E.R(state, data).max_rounds ? "" : "No limit, "}${unit} ${state.round}, ${new Date().toLocaleDateString()}`);
    if (!name) return;
    const list = slots().filter((s) => s.name !== name);
    list.unshift({ name, saved: new Date().toISOString(), state });
    localStorage.setItem(SLOTS, JSON.stringify(list.slice(0, 8)));
    alert("Saved.");
  }
  function showSlots() {
    const list = slots();
    modal(el("h2", {}, "Saved games"),
      list.length ? el("table", { class: "roster" }, list.map((s, k) => el("tr", {},
        el("td", {}, s.name), el("td", { class: "small" }, new Date(s.saved).toLocaleString()),
        el("td", {}, el("button", { onclick: () => { if (state && state.phase !== "over" && !confirm("Load it? Your current game is replaced (save a copy first if you want it).")) return;
          state = s.state; ui.sel = null; ui.from = null; ui.mode = null; closeModal(); save(); render(); advance(); } }, "Load")),
        el("td", {}, el("button", { onclick: () => { const l = slots(); l.splice(k, 1); localStorage.setItem(SLOTS, JSON.stringify(l)); showSlots(); } }, "Delete")))))
        : el("p", { class: "small" }, "No saved copies yet. During your turn, use \"Save a copy\"."),
      el("div", { class: "actions" }, state && state.phase !== "over" ? el("button", { onclick: () => { closeModal(); saveSlot(); } }, "Save the current game") : null,
        el("button", { class: "primary", onclick: () => closeModal() }, "Close")));
  }
  function startGame(length = "standard") {
    const seed = `${new Date().toISOString()}-${Math.random()}`;
    state = E.newGame(data, { seed, name: "You", length });
    ui.sel = null; ui.from = null; ui.mode = null;
    save();
    render();
    advance();
  }

  // ── settings and help ─────────────────────────────────────────────────────
  $("#btn-new").addEventListener("click", () => { if (!state || state.phase === "over" || confirm("Start a new game? This one will be replaced (use Saves to keep a copy).")) chooseLength(); });
  $("#btn-saves").addEventListener("click", () => showSlots());
  $("#btn-settings").addEventListener("click", () => {
    const sel = (key, options) => el("select", { onchange: (e) => { prefs[key] = isNaN(+e.target.value) ? e.target.value : +e.target.value; save(); } },
      options.map(([v, label]) => el("option", { value: v, selected: String(prefs[key]) === String(v) }, label)));
    const strategies = [["smart", "Smart: the cheapest player who is at least even"], ["best", "Best: my strongest"], ["weakest", "Weakest: save my stars"]];
    modal(el("h2", {}, "Settings"),
      el("label", {}, "When I'm attacked: ", sel("defend", [["auto", "pick my defender automatically"], ["ask", "ask me every time"]])),
      el("label", {}, "Automatic defender: ", sel("defendStrategy", strategies)),
      el("label", {}, "When I attack: ", sel("attackPick", [["ask", "let me pick my player"], ["auto", "pick automatically"]])),
      el("label", {}, "Automatic attacker: ", sel("attackStrategy", strategies)),
      el("label", {}, "AI speed: ", sel("speed", [[150, "fast"], [450, "normal"], [900, "slow"]])),
      el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => { closeModal(); render(); } }, "Done")));
  });
  $("#btn-help").addEventListener("click", () => modal(el("h2", {}, "How to play"),
    el("p", {}, `Four managers (you and three AIs) snake-draft the ${data.territories.length} territories, grouped in ${Object.keys(data.regions).length} regions (the shaded areas). Every territory's soldiers are real big-leaguers born there, called up best first (by career Open WAR).`),
    el("p", {}, `After the draft each manager places ${data.rules.start_callups} call-ups. Each turn: call-ups (one per ${data.rules.territories_per_callup} territories, at least ${data.rules.callups_min}, plus the bonus of every region you hold whole), then battles, then one move of soldiers between your connected territories.`),
    el("p", {}, `A battle: you pick one of your soldiers, the defender picks one at the same time. Each plays one of his real seasons at random, and that season is used up. The defender adds ${data.rules.home_field} WAR for home field; the higher season wins and the loser is out of the game. Take a territory's last soldier and it's yours, with its bench of natives.`),
    el("p", {}, `A soldier who runs out of seasons retires and his territory calls up a replacement; one whose best remaining season is under ${data.rules.release_below} WAR can be released for a call-up.`),
    el("p", {}, `Choose the length when you start: ${Object.values(data.rules.lengths || {}).map((L) => L.label).join(", ")}. At the end: 1 point per territory plus the bonus of every region you hold (or hold every territory to win outright). "End game now" scores it at any time. Settings let the game pick your players for you.`),
    el("p", { class: "small" }, `Seasons: ${data.source}.`),
    el("div", { class: "actions" }, el("button", { class: "primary", onclick: () => closeModal() }, "Got it"))));

  render();
  if (state && state.phase !== "over") advance();
})();
