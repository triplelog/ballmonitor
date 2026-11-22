// Lineup: nine real player-seasons, one per position; put them in the batting order that scores
// the most runs. Graded on expected runs (chain.js, exact), against every one of the 9! = 362,880
// orders (best, worst and percentiles come with the puzzle, built by
// `python -m ballmonitor.games.lineup.build`). Progress is kept in localStorage.
// After playing, the order can still be changed: the runs, the chance of each score and the
// gaps to the played and best orders update as you go (chain.js, in the browser). The near-best
// orders and the hitter-by-slot grid need all 9! orders, so they come prebuilt with the puzzle.
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

  const state = { index: null, puzzle: null, order: [], work: [], sel: null, done: false };
  // The order on screen: before playing, the one being built (saved); after, a copy to try
  // changes on (not saved; the played order stays as it was).
  const cur = () => (state.done ? state.work : state.order);
  const lastName = (c) => c.name.split(" ").slice(1).join(" ") || c.name;
  const ordinal = (n) => n + (n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th");
  const sameOrder = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
  const decode = (code) => [...code].map(Number);
  const signed = (x, d) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d);

  // ── storage ──────────────────────────────────────────────────────────────
  const key = (date) => `lineup:daily:${date}`;
  // Storage can be blocked (Safari private mode, strict settings): then even reading
  // `localStorage` throws, and the puzzle still works, just without saving.
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* not saved */ } },
  };
  const save = () => store.set(key(state.puzzle.date), JSON.stringify({ order: state.order, done: state.done }));
  const loadSaved = (date) => { try { return JSON.parse(store.get(key(date)) || "null"); } catch { return null; } };

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
    state.work = state.order.slice();
    state.sel = null;
    render();
  }

  // ── scoring ──────────────────────────────────────────────────────────────
  const rates = () => state.puzzle.players.map((c) => c.rates);
  function grade(order, p = state.puzzle) {
    const { runs, pa } = C.expectedRuns(order, p.players.map((c) => c.rates), p.rules);
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
    const ops = c.ops ?? c.obp + c.slg;
    const clones = c.clones ?? C.cloneRuns(c.rates, state.puzzle.rules);
    return el("div", { class: "who" },
      el("div", { class: "name" }, c.name, " ", el("span", { class: "pos" }, c.pos), c.type ? el("span", { class: "type" }, c.type) : null),
      el("div", { class: "sub" }, `${c.year} ${c.team}` + (c.plays ? ` · played ${c.plays}` : "")),
      el("div", { class: "stats" },
        el("span", { title: "Batting average / on-base percentage / slugging" }, `${f3(c.avg)} / ${f3(c.obp)} / ${f3(c.slg)}`),
        el("span", { title: "On-base percentage plus slugging" }, el("b", {}, `${f3(ops)} OPS`)),
        el("span", {}, `${c.hr} HR`), el("span", {}, `${c.bb} BB`), el("span", {}, `${c.so} SO`),
        el("span", { class: "clones", title: `A team of nine ${c.name}s would score ${clones.toFixed(2)} runs a game with this game's rules` },
          `Nine of him: ${clones.toFixed(2)} runs a game`)));
  }

  function drawLineup() {
    const list = $("#lineup");
    list.replaceChildren();
    const p = state.puzzle, order = cur();
    order.forEach((idx, slot) => {
      const c = p.players[idx];
      const up = el("button", { class: "arrow", "data-dir": "-1", title: "Move up", "aria-label": `Move ${c.name} up`,
        onclick: (e) => { e.stopPropagation(); move(slot, -1); } }, "▲");
      const down = el("button", { class: "arrow", "data-dir": "1", title: "Move down", "aria-label": `Move ${c.name} down`,
        onclick: (e) => { e.stopPropagation(); move(slot, 1); } }, "▼");
      if (slot === 0) up.disabled = true;
      if (slot === 8) down.disabled = true;
      const row = el("li", { class: "slot" + (state.sel === slot ? " sel" : ""), tabindex: "0",
        "aria-label": `${ordinal(slot + 1)}: ${c.name}`,
        onclick: () => { if (drag.justDropped) return; tap(slot); },
        onkeydown: (e) => {
          if (e.target !== row) return;
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); tap(slot); }
          else if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); move(slot, e.key === "ArrowUp" ? -1 : 1, true); }
        },
        onpointerdown: (e) => dragStart(e, slot, row) },
        el("span", { class: "num" }, String(slot + 1)),
        el("span", { class: "grip", title: "Drag to move", "aria-hidden": "true" }, "⠿"),
        playerLine(c),
        el("span", { class: "arrows" }, up, down));
      list.append(row);
    });
    $("#btn-play").classList.toggle("hidden", state.done);
    $("#btn-play").disabled = state.done;
    $("#btn-reset").textContent = state.done ? "Back to my order" : "Reset";
    $("#btn-best").classList.toggle("hidden", !state.done);
    $("#lineup-title").textContent = state.done ? "Try other orders" : "Batting order";
    $("#lineup-hint").textContent = state.done
      ? "Your score is kept. Move hitters to see how the runs change."
      : "Drag a hitter to a new spot, tap two hitters to swap them, or use the arrows.";
    drawLive();
  }

  function announce(msg) { $("#announce").textContent = msg; }

  function tap(slot) {
    const order = cur();
    if (state.sel === null) state.sel = slot;
    else if (state.sel === slot) state.sel = null;
    else {
      const a = state.sel;
      [order[a], order[slot]] = [order[slot], order[a]];
      state.sel = null;
      announce(`Swapped ${state.puzzle.players[order[slot]].name} and ${state.puzzle.players[order[a]].name}`);
      changed();
      return;
    }
    drawLineup();
  }

  function move(slot, dir, fromRow = false) {
    const to = slot + dir;
    if (to < 0 || to > 8) return;
    const order = cur();
    [order[slot], order[to]] = [order[to], order[slot]];
    state.sel = null;
    announce(`${state.puzzle.players[order[to]].name} now bats ${ordinal(to + 1)}`);
    changed();
    // keep the keyboard where it was: on the moved hitter's row (or the same arrow, if it still works)
    const row = $("#lineup").children[to];
    const btn = row && row.querySelector(`.arrow[data-dir="${dir}"]`);
    (fromRow || !btn || btn.disabled ? row : btn)?.focus();
  }

  function moveTo(from, to) {
    if (from === to) return;
    const order = cur();
    const [x] = order.splice(from, 1);
    order.splice(to, 0, x);
    state.sel = null;
    announce(`${state.puzzle.players[x].name} now bats ${ordinal(to + 1)}`);
    changed();
  }

  function changed() {
    if (!state.done) save();
    drawLineup();
  }

  function setWork(order) {
    state.work = order.slice();
    state.sel = null;
    drawLineup();
    $("#lineup").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ── drag and drop (mouse: the whole row; touch and pen: the ⠿ handle, so the page still scrolls) ──
  const drag = { on: false, justDropped: false };
  function dragStart(e, slot, row) {
    if (e.button !== 0 || e.target.closest("button")) return;
    if (e.pointerType !== "mouse" && !e.target.closest(".grip")) return;
    const rows = [...$("#lineup").children];
    const rects = rows.map((r) => r.getBoundingClientRect());
    Object.assign(drag, { on: false, pending: true, id: e.pointerId, from: slot, to: slot, row, rows,
      mids: rects.map((r) => r.top + window.scrollY + r.height / 2),
      step: rects[slot].height + (rects.length > 1 ? rects[1].top - rects[0].bottom : 6),
      y0: e.clientY + window.scrollY, y: e.clientY });
    row.setPointerCapture(e.pointerId);
    if (e.pointerType !== "mouse") { e.preventDefault(); begin(); }
    row.addEventListener("pointermove", dragMove);
    row.addEventListener("pointerup", dragEnd);
    row.addEventListener("pointercancel", dragEnd);
  }
  function begin() {
    drag.on = true;
    drag.row.classList.add("dragging");
    $("#lineup").classList.add("drag-on");
    const tick = () => {                       // scroll the page when the hitter is held near an edge
      if (!drag.on) return;
      const edge = 60, y = drag.y;
      if (y < edge) window.scrollBy(0, -Math.ceil((edge - y) / 6));
      else if (y > window.innerHeight - edge) window.scrollBy(0, Math.ceil((y - window.innerHeight + edge) / 6));
      place();
      drag.raf = requestAnimationFrame(tick);
    };
    drag.raf = requestAnimationFrame(tick);
  }
  function place() {
    const dy = drag.y + window.scrollY - drag.y0, from = drag.from;
    const c = drag.mids[from] + dy;
    const near = drag.step / 4;                 // a row takes the spot a little before its middle is reached
    let to = from;
    for (let i = from + 1; i < drag.mids.length; i++) if (c > drag.mids[i] - near) to = i;
    for (let i = from - 1; i >= 0; i--) if (c < drag.mids[i] + near) to = i;
    drag.to = to;
    drag.row.style.transform = `translateY(${dy}px)`;
    drag.rows.forEach((r, i) => {
      if (i === from) return;
      const shift = from < to && i > from && i <= to ? -drag.step : from > to && i >= to && i < from ? drag.step : 0;
      r.style.transform = shift ? `translateY(${shift}px)` : "";
    });
  }
  function dragMove(e) {
    if (e.pointerId !== drag.id) return;
    drag.y = e.clientY;
    if (!drag.on && Math.abs(e.clientY + window.scrollY - drag.y0) > 5) begin();
    if (drag.on) { e.preventDefault(); place(); }
  }
  function dragEnd(e) {
    if (e.pointerId !== drag.id) return;
    const row = drag.row;
    row.removeEventListener("pointermove", dragMove);
    row.removeEventListener("pointerup", dragEnd);
    row.removeEventListener("pointercancel", dragEnd);
    cancelAnimationFrame(drag.raf);
    const was = drag.on;
    drag.on = false;
    drag.pending = false;
    drag.rows.forEach((r) => { r.style.transform = ""; });
    row.classList.remove("dragging");
    $("#lineup").classList.remove("drag-on");
    if (!was) return;
    drag.justDropped = true;                   // the click that follows a drop is not a tap
    setTimeout(() => { drag.justDropped = false; }, 0);
    if (e.type === "pointerup") moveTo(drag.from, drag.to);
  }

  // ── after playing: the order on screen, scored live ──────────────────────
  function drawLive() {
    const box = $("#live");
    if (!state.done) { box.classList.add("hidden"); box.replaceChildren(); return; }
    box.classList.remove("hidden");
    const p = state.puzzle, order = cur(), games = p.rules.game.season_games;
    const g = grade(order), mine = grade(state.order).runs;
    const dist = C.runDistribution(order, rates(), p.rules);
    const vs = (x, what) => Math.abs(x) < 5e-7 ? null
      : el("span", { class: x >= 0 ? "up" : "down" }, `${signed(x, 3)} a game vs ${what} (` +
        (Math.round(Math.abs(x) * games) ? `${signed(x * games, 0)} a season)` : "less than 1 a season)"));
    const isMine = sameOrder(order, state.order), isBest = g.perfect;
    box.replaceChildren(
      el("div", { class: "live-runs" },
        el("strong", {}, `${g.runs.toFixed(3)} runs a game`),
        el("span", {}, ` · ${Math.round(seasonRuns(g.runs))} a season · ${g.perfect ? "the best order" : `beats ${pct(g.below)} of all orders`}`)),
      el("div", { class: "live-vs" },
        isMine ? el("span", {}, "This is the order you played.") : vs(g.runs - mine, "your order"),
        isBest ? el("span", { class: "up" }, "This is the best order.") : vs(g.runs - p.best.runs, "the best")),
      distChart(dist, g.runs));
  }

  function distChart(dist, mean) {
    const SHOW = 15;                            // bars for 0 .. SHOW-1 runs, then "SHOW+"
    const bars = dist.slice(0, SHOW).concat([dist.slice(SHOW).reduce((a, b) => a + b, 0)]);
    const top = Math.max(...bars);
    const label = (i) => (i === SHOW ? `${SHOW}+` : String(i));
    const tenPlus = dist.slice(10).reduce((a, b) => a + b, 0);
    let half = 0, median = 0;
    for (; median < dist.length; median++) { half += dist[median]; if (half >= 0.5) break; }
    return el("figure", { class: "dist" },
      el("figcaption", {}, "Runs in a game with this order"),
      el("div", { class: "bars", role: "img",
        "aria-label": `Chance of each score: ${bars.map((b, i) => `${label(i)} runs ${(100 * b).toFixed(1)}%`).join(", ")}` },
        ...bars.map((b, i) => el("div", { class: "bar", title: `${label(i)} run${i === 1 ? "" : "s"}: ${(100 * b).toFixed(1)}% of games` },
          el("span", { class: "fill", style: `height:${(100 * b / top).toFixed(1)}%` }),
          el("span", { class: "x" }, label(i))))),
      el("p", { class: "hint" },
        `Shut out in ${pct(dist[0])} of games, 10 or more runs in ${pct(tenPlus)}; half the games score ${median} or fewer. ` +
        `Average ${mean.toFixed(2)}. Worked out exactly from the same rules, not from random games.`));
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
        el("button", { class: "ghost", onclick: playSeason, title: "A random 162-game season with the order now in the lineup, next to the best order" }, "Play out a season with this order"),
        el("button", { class: "primary", onclick: share }, "Share")),
      el("div", { id: "season" }),
      p.top ? nearBest(p) : null,
      p.grid ? fitGrid(p) : null);
  }

  // How an order differs from the best one, in words.
  function differs(order, best) {
    const p = state.puzzle;
    const moved = order.map((idx, slot) => (idx === best[slot] ? null : slot)).filter((x) => x !== null);
    if (!moved.length) return "The best order";
    if (moved.length === 2) return `Swap ${lastName(p.players[best[moved[0]]])} and ${lastName(p.players[best[moved[1]]])}`;
    return moved.map((slot) => `${lastName(p.players[order[slot]])} ${ordinal(slot + 1)}`).join(", ");
  }

  function nearBest(p) {
    const games = p.rules.game.season_games;
    const rows = p.top.map(([code, runs], i) => {
      const order = decode(code);
      return el("tr", {},
        el("td", { class: "n" }, String(i + 1)),
        el("td", {}, differs(order, p.best.order)),
        el("td", { class: "n" }, runs.toFixed(3)),
        el("td", { class: "n" }, i === 0 ? "" : signed((runs - p.best.runs) * games, 1)),
        el("td", {}, el("button", { class: "mini", title: "Put this order in the lineup", onclick: () => setWork(order) }, "Try")));
    });
    return el("details", { class: "more" },
      el("summary", {}, `The ${p.top.length} best orders`),
      el("p", { class: "hint" }, "How each differs from the best order, its runs a game, and the runs a season it gives up."),
      el("div", { class: "scroll" }, el("table", { class: "best top" },
        el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, "Change from the best"), el("th", {}, "Runs"), el("th", { title: "Runs a season fewer than the best order" }, "Season"), el("th", {}, ""))),
        el("tbody", {}, ...rows))));
  }

  function fitGrid(p) {
    const games = p.rules.game.season_games;
    const worstGap = Math.max(...p.grid.flat().map(([runs]) => p.best.runs - runs), 1e-9);
    const head = el("tr", {}, el("th", {}, "Hitter"), ...p.best.order.map((_, s) => el("th", { class: "n" }, String(s + 1))));
    const rows = p.best.order.map((h) => {
      const row = p.grid[h], bestHere = Math.max(...row.map(([runs]) => runs));
      const yours = state.order.indexOf(h);
      return el("tr", {},
        el("th", { scope: "row" }, lastName(p.players[h])),
        ...row.map(([runs, code], slot) => {
          const gap = p.best.runs - runs, lost = Math.round(gap * games);
          const top = runs === bestHere;
          const words = top ? "the best order" : lost ? `${lost} run${lost === 1 ? "" : "s"} a season worse than the best`
            : "less than 1 run a season worse than the best";
          return el("td", {
            class: "n cell" + (top ? " top" : "") + (slot === yours ? " yours" : ""),
            style: top ? "" : `--heat:${(0.08 + 0.6 * gap / worstGap).toFixed(3)}`},
            el("button", { type: "button", class: "cellbtn",
              "aria-label": `${lastName(p.players[h])} batting ${ordinal(slot + 1)}: ${words}` + (slot === yours ? " (where you had him)" : "") + ". Try this order",
              title: `${p.players[h].name} batting ${ordinal(slot + 1)}: the best order like that scores ${runs.toFixed(3)} a game (${words}). Click to try it.`,
              onclick: () => setWork(decode(code)) }, top ? "★" : lost ? `−${lost}` : "0"));
        }));
    });
    return el("details", { class: "more" },
      el("summary", {}, "Where each hitter fits"),
      el("p", { class: "hint" }, "Each square: put that hitter in that spot and set the other eight as well as they can be. " +
        "The number is how many runs a season that gives up against the best order; ★ is his spot in the best order. " +
        "A box marks where you had him. Tap a square to try that order."),
      el("div", { class: "scroll" }, el("table", { class: "grid" }, el("thead", {}, head), el("tbody", {}, ...rows))));
  }

  function playSeason() {
    const p = state.puzzle;
    const seed = Number(p.date.replaceAll("-", "")) + Math.floor(Math.random() * 1e6);
    const order = cur().slice();                 // the order now in the lineup (your played one unless you moved hitters)
    const mine = C.simulateSeason(order, rates(), p.rules, seed);
    const best = C.simulateSeason(p.best.order, rates(), p.rules, seed + 1);
    const g = grade(order);
    const who = sameOrder(order, state.order) ? "The order you played" : "The order in the lineup now (not the one you played)";
    $("#season").replaceChildren(
      el("h3", {}, "One season, played out"),
      el("p", {}, `${who} scored ${mine.runs} runs in ${p.rules.game.season_games} games (expected ${Math.round(seasonRuns(g.runs))}). `,
        `The best order scored ${best.runs} (expected ${Math.round(seasonRuns(p.best.runs))}).`),
      el("p", { class: "hint" }, mine.runs >= best.runs
        ? "This order won this season — one season is mostly luck, which is why the score uses expected runs. Press again for another season."
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
    state.work = state.order.slice();
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
  let modalReturn = null;   // what had focus before the modal opened
  function modal(...content) {
    $("#modal-body").replaceChildren(...content);
    if ($("#modal").classList.contains("hidden")) modalReturn = document.activeElement;
    $("#modal").classList.remove("hidden");
    $("#modal-close").focus();
  }
  function closeModal(refocus = true) {
    if ($("#modal").classList.contains("hidden")) return;
    $("#modal").classList.add("hidden");
    const back = modalReturn;
    modalReturn = null;
    if (refocus && back && back !== document.body && document.contains(back)) back.focus();
  }
  function showHelp() {
    const a = state.puzzle?.rules.advance;
    modal(el("h2", {}, "How to play"),
      el("p", {}, "Nine real hitters, each from one season in baseball history, one at every position. Put them in the batting order that scores the most runs."),
      el("p", {}, "Drag a hitter to a new spot (on a phone, by the ⠿ handle), tap a hitter and then another to swap them, or use the arrows. When you're happy, press Play ball. You get one try."),
      el("p", {}, "Under each hitter: his real batting line that season (average / on-base / slugging, OPS, home runs, walks, strikeouts) and how many runs a team of nine of him would score a game with these rules."),
      el("p", {}, "After you play, you can keep moving hitters to see how the runs change, the chance of each score, the best orders and where each hitter fits best."),
      el("p", {}, "Every plate appearance is played with the hitter's real rates that season: strikeouts, walks (and hit by pitch), singles, doubles, triples, home runs and other outs. Runners move up at league-average rates" +
        (a ? ` (a runner on 2nd scores on a single ${Math.round(100 * a.second_scores_on_single)}% of the time, a runner on 1st reaches 3rd ${Math.round(100 * a.first_to_third_on_single)}%, an out in play with a runner on 1st is a double play ${Math.round(100 * a.double_play)}%).` : ".")),
      el("p", {}, "Your score is worked out exactly, not from one lucky season: the expected runs of your order, compared with the best and the worst of all 362,880 possible orders."),
      el("p", {}, "Things to think about: the top of the order bats about 17 more times a season per step than the next slot; walks are worth most in front of power; outs are worth least with nobody on."),
      el("p", { class: "hint" }, "No steals, errors, bunts or pinch hitters, so every lineup scores a little less than a real team would. A new puzzle every day."),
      el("p", { class: "hint" }, `Data: ${state.index?.source || "Lahman Baseball Database"}.`));
  }
  async function showArchive() {
    const list = [...available()].reverse();
    const saves = new Map(list.map((q) => [q.date, loadSaved(q.date)]));
    // the months of played days, to score them (from what's already saved; nothing new is stored)
    const need = new Set(list.filter((q) => saves.get(q.date)?.done).map((q) => q.date.slice(0, 7)));
    await Promise.all([...need].map((m) => monthOf(`${m}-01`).catch(() => null)));
    const items = [], played = [];
    for (const q of list) {
      const saved = saves.get(q.date);
      let s = "not played";
      if (saved?.done) {
        s = "played";
        const m = months[q.date.slice(0, 7)];
        const pz = m && m.find((x) => x.date === q.date);
        if (pz && saved.order?.length === 9) {
          const g = grade(saved.order, pz);
          played.push(g);
          s = g.perfect ? "100%" : pct(g.share);
        }
      } else if (saved) s = "in progress";
      const d = new Date(q.date + "T12:00:00");
      items.push(el("button", { class: saved?.done ? "done" : "", onclick: () => { closeModal(false); location.hash = q.date; } },
        `#${q.number} · ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`, el("span", { class: "s" }, s)));
    }
    const avg = (f) => played.reduce((a, g) => a + f(g), 0) / played.length;
    const summary = played.length
      ? `${played.length} played · average score ${pct(avg((g) => g.share))} (beats ${pct(avg((g) => g.below))} of orders) · best ${played.some((g) => g.perfect) ? "100%" : pct(Math.max(...played.map((g) => g.share)))}` +
        (played.some((g) => g.perfect) ? ` · ${played.filter((g) => g.perfect).length} perfect` : "")
      : "None played yet on this device.";
    modal(el("h2", {}, "Archive"), el("p", { class: "arch-sum" }, summary), el("div", { class: "arch" }, ...items));
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
    $("#btn-reset").addEventListener("click", () => {
      if (state.done) { setWork(state.order); return; }
      state.order = state.puzzle.players.map((_, i) => i); state.sel = null; save(); drawLineup();
    });
    $("#btn-best").addEventListener("click", () => setWork(state.puzzle.best.order));
    $("#btn-help").addEventListener("click", showHelp);
    $("#btn-archive").addEventListener("click", showArchive);
    $("#modal-close").addEventListener("click", () => closeModal());
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) { e.preventDefault(); closeModal(); } });
    go();
    if (!store.get("lineup:seen-help")) {
      store.set("lineup:seen-help", "1");
      const wait = setInterval(() => { if (state.puzzle) { clearInterval(wait); showHelp(); } }, 50);
    }
  }
  boot().catch((err) => { document.body.prepend(el("p", { style: "color:#b91c1c;padding:12px" }, `Could not load the puzzle: ${err.message}`)); });
})();
