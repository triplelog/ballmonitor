// Lineup: nine real player-seasons, one per position; put them in the batting order that scores
// the most runs. Graded on expected runs (chain.js, exact), against every one of the 9! = 362,880
// orders (best, worst and percentiles come with the puzzle, built by
// `python -m ballmonitor.games.lineup.build`). Progress is kept in localStorage.
(function () {
  "use strict";

  const C = window.LineupChain;
  const $ = (s) => document.querySelector(s);
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(k));
    return n;
  };
  const f3 = (x) => x.toFixed(3).replace(/^0/, "");
  const pct = (x) => `${(100 * x).toFixed(1)}%`;

  const state = { index: null, puzzle: null, order: [], sel: null, done: false };

  // ── storage ──────────────────────────────────────────────────────────────
  const key = (date) => `lineup:daily:${date}`;
  const save = () => localStorage.setItem(key(state.puzzle.date), JSON.stringify({ order: state.order, done: state.done }));
  const loadSaved = (date) => { try { return JSON.parse(localStorage.getItem(key(date)) || "null"); } catch { return null; } };

  // ── data ─────────────────────────────────────────────────────────────────
  const todayISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const available = () => state.index.puzzles.filter((p) => p.date <= todayISO());
  const months = {};
  async function monthOf(date) {
    const m = date.slice(0, 7);
    if (!months[m]) months[m] = await (await fetch(`puzzles/daily/${m}.json`)).json();
    return months[m];
  }
  async function loadPuzzle(date) {
    const p = (await monthOf(date)).find((q) => q.date === date);
    if (!p) throw new Error(`no puzzle for ${date}`);
    state.puzzle = p;
    const saved = loadSaved(date);
    state.order = saved?.order?.length === 9 ? saved.order : p.players.map((_, i) => i);
    state.done = !!saved?.done;
    state.sel = null;
    render();
  }

  // ── scoring ──────────────────────────────────────────────────────────────
  const rates = () => state.puzzle.players.map((c) => c.rates);
  function grade(order) {
    const p = state.puzzle;
    const { runs, pa } = C.expectedRuns(order, rates(), p.rules);
    const best = p.best.runs, worst = p.worst.runs;
    const share = Math.max(0, Math.min(1, (runs - worst) / (best - worst)));
    // share of all orders that score less (interpolated between stored percentiles)
    const q = p.percentiles;
    let below = 0;
    if (runs >= q[100]) below = 1;
    else if (runs > q[0]) {
      let i = 0;
      while (q[i + 1] < runs) i++;
      below = (i + (runs - q[i]) / Math.max(q[i + 1] - q[i], 1e-12)) / 100;
    }
    return { runs, pa, share, below, perfect: best - runs < 5e-7 };
  }
  const seasonRuns = (r) => r * state.puzzle.rules.game.season_games;
  const verdict = (g) => g.perfect ? "Perfect! The best order there is. 🏆" : g.share >= 0.95 ? "Excellent" :
    g.share >= 0.85 ? "Very good" : g.share >= 0.7 ? "Solid" : g.share >= 0.5 ? "Not bad" : "Tough one";

  // ── render ───────────────────────────────────────────────────────────────
  function render() {
    const p = state.puzzle;
    const d = new Date(p.date + "T12:00:00");
    $("#meta").replaceChildren(...[
      el("strong", {}, `#${p.number}`),
      el("span", {}, d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })),
      p.date !== available().at(-1)?.date ? el("span", {}, "· from the archive") : null,
    ].filter(Boolean));
    drawLineup();
    drawResult();
  }

  function playerLine(c) {
    return el("div", { class: "who" },
      el("div", { class: "name" }, c.name, " ", el("span", { class: "pos" }, c.pos), c.type ? el("span", { class: "type" }, c.type) : null),
      el("div", { class: "sub" }, `${c.year} ${c.team}` + (c.plays ? ` · played ${c.plays}` : "")),
      el("div", { class: "stats" },
        el("span", { title: "Batting average / on-base percentage / slugging" }, `${f3(c.avg)} / ${f3(c.obp)} / ${f3(c.slg)}`),
        el("span", {}, `${c.hr} HR`), el("span", {}, `${c.bb} BB`), el("span", {}, `${c.so} SO`),
        el("span", { class: "hint" }, `${c.pa} PA`)));
  }

  function drawLineup() {
    const list = $("#lineup");
    list.replaceChildren();
    const p = state.puzzle;
    state.order.forEach((idx, slot) => {
      const c = p.players[idx];
      const up = el("button", { class: "arrow", title: "Move up", "aria-label": `Move ${c.name} up`,
        onclick: (e) => { e.stopPropagation(); move(slot, -1); } }, "▲");
      const down = el("button", { class: "arrow", title: "Move down", "aria-label": `Move ${c.name} down`,
        onclick: (e) => { e.stopPropagation(); move(slot, 1); } }, "▼");
      if (slot === 0) up.disabled = true;
      if (slot === 8) down.disabled = true;
      const row = el("li", { class: "slot" + (state.sel === slot ? " sel" : ""), tabindex: state.done ? "-1" : "0",
        onclick: () => tap(slot), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); tap(slot); } } },
        el("span", { class: "num" }, String(slot + 1)), playerLine(c),
        state.done ? null : el("span", { class: "arrows" }, up, down));
      list.append(row);
    });
    $("#btn-play").disabled = state.done;
    $("#btn-play").textContent = state.done ? "Played" : "Play ball (one try)";
    $("#btn-reset").disabled = state.done;
    $("#lineup-hint").classList.toggle("hidden", state.done);
  }

  function tap(slot) {
    if (state.done) return;
    if (state.sel === null) state.sel = slot;
    else if (state.sel === slot) state.sel = null;
    else {
      [state.order[state.sel], state.order[slot]] = [state.order[slot], state.order[state.sel]];
      state.sel = null;
      save();
    }
    drawLineup();
  }

  function move(slot, dir) {
    if (state.done) return;
    const to = slot + dir;
    if (to < 0 || to > 8) return;
    [state.order[slot], state.order[to]] = [state.order[to], state.order[slot]];
    state.sel = null;
    save();
    drawLineup();
  }

  function drawResult() {
    const box = $("#result");
    if (!state.done) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const p = state.puzzle, g = grade(state.order);
    const bestPa = C.expectedRuns(p.best.order, rates(), p.rules).pa;
    const lost = seasonRuns(p.best.runs - g.runs);
    const rows = p.best.order.map((idx, slot) => {
      const mine = state.order.indexOf(idx);
      return el("tr", { class: mine === slot ? "same" : "" },
        el("td", { class: "n" }, String(slot + 1)), el("td", {}, p.players[idx].name),
        el("td", { class: "n" }, mine === slot ? "✓" : String(mine + 1)),
        el("td", { class: "n" }, Math.round(bestPa[slot] * p.rules.game.season_games).toString()));
    });
    box.replaceChildren(
      el("div", { class: "score" },
        el("span", { class: "big" }, g.perfect ? "100%" : pct(g.share)),
        el("span", {}, verdict(g))),
      el("p", { class: "explain" },
        `Your order scores ${g.runs.toFixed(3)} runs a game (${Math.round(seasonRuns(g.runs))} a season). `,
        `The best of all ${p.orders.toLocaleString()} orders scores ${p.best.runs.toFixed(3)} (${Math.round(seasonRuns(p.best.runs))}), the worst ${p.worst.runs.toFixed(3)} (${Math.round(seasonRuns(p.worst.runs))}). `,
        g.perfect ? "" : `You left about ${lost < 1 ? "less than 1 run" : `${Math.round(lost)} runs`} a season on the table; your order beats ${pct(g.below)} of all orders.`),
      el("p", { class: "hint" }, "Score = how far your order got from the worst order to the best one, in expected runs."),
      el("h3", {}, "The best order"),
      el("table", { class: "best" },
        el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, "Hitter"), el("th", {}, "You had"), el("th", { title: "Expected plate appearances in a season in this slot" }, "PA"))),
        el("tbody", {}, ...rows)),
      el("p", { class: "hint" }, "PA = expected plate appearances over a season from that slot: each step down the order loses about 17."),
      el("div", { class: "result-actions" },
        el("button", { class: "ghost", onclick: playSeason }, "Play out a season"),
        el("button", { class: "primary", onclick: share }, "Share")),
      el("div", { id: "season" }));
  }

  function playSeason() {
    const p = state.puzzle;
    const seed = Number(p.date.replaceAll("-", "")) + Math.floor(Math.random() * 1e6);
    const mine = C.simulateSeason(state.order, rates(), p.rules, seed);
    const best = C.simulateSeason(p.best.order, rates(), p.rules, seed + 1);
    const g = grade(state.order);
    $("#season").replaceChildren(
      el("h3", {}, "One season, played out"),
      el("p", {}, `Your lineup scored ${mine.runs} runs in ${p.rules.game.season_games} games (expected ${Math.round(seasonRuns(g.runs))}). `,
        `The best order scored ${best.runs} (expected ${Math.round(seasonRuns(p.best.runs))}).`),
      el("p", { class: "hint" }, mine.runs >= best.runs
        ? "Your lineup won this season — one season is mostly luck, which is why the score uses expected runs. Press again for another season."
        : "One season swings by dozens of runs either way, which is why the score uses expected runs. Press again for another season."));
  }

  function share() {
    const p = state.puzzle, g = grade(state.order);
    const blocks = Math.round(g.share * 10);
    const text = [`Lineup #${p.number} — ${g.perfect ? "100% 🏆" : pct(g.share)}`,
      "🟩".repeat(blocks) + "⬜".repeat(10 - blocks),
      `${Math.round(seasonRuns(g.runs))} runs a season (best ${Math.round(seasonRuns(p.best.runs))})`,
      location.href.split("#")[0]].join("\n");
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
      () => toast("Result copied — paste it anywhere"), () => prompt("Copy your result:", text));
  }

  function play() {
    if (state.done) return;
    state.done = true;
    state.sel = null;
    save();
    render();
    if (window.innerWidth < 860) $("#result").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.remove("hidden");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => t.classList.add("hidden"), 2200);
  }

  // ── modals ───────────────────────────────────────────────────────────────
  function modal(...content) {
    $("#modal-body").replaceChildren(...content);
    $("#modal").classList.remove("hidden");
  }
  function showHelp() {
    const a = state.puzzle?.rules.advance;
    modal(el("h2", {}, "How to play"),
      el("p", {}, "Nine real hitters, each from one season in baseball history, one at every position. Put them in the batting order that scores the most runs."),
      el("p", {}, "Tap a hitter and then another to swap them, or use the arrows. When you're happy, press Play ball. You get one try."),
      el("p", {}, "Every plate appearance is played with the hitter's real rates that season: strikeouts, walks (and hit by pitch), singles, doubles, triples, home runs and other outs. Runners move up at league-average rates" +
        (a ? ` (a runner on 2nd scores on a single ${Math.round(100 * a.second_scores_on_single)}% of the time, a runner on 1st reaches 3rd ${Math.round(100 * a.first_to_third_on_single)}%, an out in play with a runner on 1st is a double play ${Math.round(100 * a.double_play)}%).` : ".")),
      el("p", {}, "Your score is worked out exactly, not from one lucky season: the expected runs of your order, compared with the best and the worst of all 362,880 possible orders."),
      el("p", {}, "Things to think about: the top of the order bats about 17 more times a season per step than the next slot; walks are worth most in front of power; outs are worth least with nobody on."),
      el("p", { class: "hint" }, "No steals, errors, bunts or pinch hitters, so every lineup scores a little less than a real team would. A new puzzle every day."),
      el("p", { class: "hint" }, `Data: ${state.index?.source || "Lahman Baseball Database"}.`));
  }
  async function showArchive() {
    const list = [...available()].reverse();
    const items = [];
    for (const q of list) {
      const saved = loadSaved(q.date);
      let s = "not played";
      if (saved?.done) {
        s = "played";
        const m = months[q.date.slice(0, 7)];
        const pz = m && m.find((x) => x.date === q.date);
        if (pz) {
          const runs = C.expectedRuns(saved.order, pz.players.map((c) => c.rates), pz.rules).runs;
          s = pct(Math.max(0, (runs - pz.worst.runs) / (pz.best.runs - pz.worst.runs)));
        }
      } else if (saved) s = "in progress";
      const d = new Date(q.date + "T12:00:00");
      items.push(el("button", { class: saved?.done ? "done" : "", onclick: () => { $("#modal").classList.add("hidden"); location.hash = q.date; } },
        `#${q.number} · ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`, el("span", { class: "s" }, s)));
    }
    modal(el("h2", {}, "Archive"), el("div", { class: "arch" }, ...items));
  }

  // ── boot ─────────────────────────────────────────────────────────────────
  async function boot() {
    state.index = await (await fetch("puzzles/daily/index.json")).json();
    const go = () => {
      const want = location.hash.slice(1);
      const list = available();
      const pickP = list.find((q) => q.date === want) || list.at(-1) || state.index.puzzles[0];
      loadPuzzle(pickP.date);
    };
    window.addEventListener("hashchange", go);
    $("#btn-play").addEventListener("click", play);
    $("#btn-reset").addEventListener("click", () => { state.order = state.puzzle.players.map((_, i) => i); state.sel = null; save(); drawLineup(); });
    $("#btn-help").addEventListener("click", showHelp);
    $("#btn-archive").addEventListener("click", showArchive);
    $("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });
    go();
    if (!localStorage.getItem("lineup:seen-help")) {
      localStorage.setItem("lineup:seen-help", "1");
      const wait = setInterval(() => { if (state.puzzle) { clearInterval(wait); showHelp(); } }, 50);
    }
  }
  boot().catch((err) => { document.body.prepend(el("p", { style: "color:#b91c1c;padding:12px" }, `Could not load the puzzle: ${err.message}`)); });
})();
