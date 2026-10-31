// Triple Play: place 17 cards (25 on Sunday) in a three-circle Venn diagram. One check, one point per card.
// Puzzles come from puzzles/<pack>/index.json + one file per month (built by
// `python -m ballmonitor.games.triple_play.build`). Progress is kept in localStorage.
(function () {
  "use strict";

  const PACKS = { baseball: "⚾ Baseball", places: "🏙️ Cities & States" };
  const NEED_17 = { ABC: 1, AB: 2, AC: 2, BC: 2, A: 3, B: 3, C: 3, "": 1 };
  let NEED = NEED_17;                // set per puzzle (Sunday's big puzzle has 25 cards)
  const REGIONS = ["ABC", "AB", "AC", "BC", "A", "B", "C", ""];
  // geometry (svg viewBox 0 0 720 690)
  const R = 215;
  const CIRCLES = { A: [255, 250], B: [465, 250], C: [360, 430] };
  const COLORS = { A: "var(--a)", B: "var(--b)", C: "var(--c)" };
  let CHIP_W = 124, CHIP_H = 28;     // 108 x 24 on the 25-card board
  const OUTSIDE_SLOT = [86, 652];
  const total = () => Object.values(NEED).reduce((a, b) => a + b, 0);
  const SVGNS = "http://www.w3.org/2000/svg";

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
  const sv = (tag, attrs = {}) => {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };

  const state = { index: null, puzzle: null, place: {}, sel: null, checked: false, showAnswers: false };

  // ── geometry ─────────────────────────────────────────────────────────────
  function regionAt(x, y) {
    let code = "";
    for (const k of ["A", "B", "C"]) {
      const [cx, cy] = CIRCLES[k];
      if ((x - cx) ** 2 + (y - cy) ** 2 <= R * R) code += k;
    }
    return code;
  }

  // chip slots: grid points whose whole chip rectangle lies in the region, picked greedily
  // nearest the region's middle without overlapping (cached per board size)
  const slotCache = {};
  function computeSlots() {
    const keyS = JSON.stringify(NEED) + CHIP_W;
    if (slotCache[keyS]) return slotCache[keyS];
    const outside = Array.from({ length: NEED[""] }, (_, i) => [OUTSIDE_SLOT[0], OUTSIDE_SLOT[1] - (NEED[""] - 1 - i) * (CHIP_H + 4)]);
    const out = { "": outside };
    const pts = {};
    for (let y = 20; y < 670; y += 3) {
      for (let x = 20; x < 700; x += 3) {
        const hw = CHIP_W / 2, hh = CHIP_H / 2;
        const code = regionAt(x, y);
        if (!code) continue;
        const probes = [[-hw, -hh], [hw, -hh], [-hw, hh], [hw, hh], [0, -hh], [0, hh], [-hw, 0], [hw, 0]];
        if (probes.every(([dx, dy]) => regionAt(x + dx, y + dy) === code)) (pts[code] = pts[code] || []).push([x, y]);
      }
    }
    for (const code of REGIONS.filter(Boolean)) {
      const p = pts[code] || [];
      const mx = p.reduce((s, q) => s + q[0], 0) / p.length, my = p.reduce((s, q) => s + q[1], 0) / p.length;
      const chosen = [];
      const sorted = [...p].sort((a, b) => Math.hypot(a[0] - mx, a[1] - my) - Math.hypot(b[0] - mx, b[1] - my));
      for (const q of sorted) {
        if (chosen.length >= NEED[code]) break;
        if (chosen.every((c) => Math.abs(c[0] - q[0]) > CHIP_W + 3 || Math.abs(c[1] - q[1]) > CHIP_H + 3)) chosen.push(q);
      }
      out[code] = chosen;
    }
    return (slotCache[keyS] = out);
  }
  let SLOTS = computeSlots();

  // ── storage ──────────────────────────────────────────────────────────────
  const key = (date) => `triple-play:daily:${date}`;
  const save = () => localStorage.setItem(key(state.puzzle.date), JSON.stringify({ place: state.place, checked: state.checked }));
  const loadSaved = (date) => { try { return JSON.parse(localStorage.getItem(key(date)) || "null"); } catch { return null; } };

  // ── data ─────────────────────────────────────────────────────────────────
  const todayISO = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  const available = () => state.index.puzzles.filter((p) => p.date <= todayISO());
  const months = {};
  async function loadPuzzle(date) {
    const m = date.slice(0, 7);
    if (!months[m]) months[m] = await (await fetch(`puzzles/daily/${m}.json`)).json();
    const p = months[m].find((q) => q.date === date);
    if (!p) throw new Error(`no puzzle for ${date}`);
    state.puzzle = p;
    NEED = p.need || NEED_17;
    [CHIP_W, CHIP_H] = total() > 17 ? [108, 24] : [124, 28];
    SLOTS = computeSlots();
    const saved = loadSaved(date);
    state.place = saved?.place || {};
    state.checked = !!saved?.checked;
    state.sel = null;
    state.showAnswers = false;
    render();
  }

  // ── render ───────────────────────────────────────────────────────────────
  function render() {
    const p = state.puzzle;
    const d = new Date(p.date + "T12:00:00");
    $("#meta").replaceChildren(...[
      el("strong", {}, `#${p.number}`),
      el("span", {}, d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })),
      el("span", { class: `level pack-${p.pack}` }, PACKS[p.pack] || p.pack),
      p.pack === "places" ? null : el("span", { class: "level" }, p.level === "big" ? "Big Sunday · 25 cards" : p.level[0].toUpperCase() + p.level.slice(1)),
      p.date !== available().at(-1)?.date ? el("span", {}, "· from the archive") : null,
    ].filter(Boolean));
    drawBoard();
    drawTray();
    drawResult();
  }

  function drawBoard() {
    const svg = $("#venn");
    svg.replaceChildren();
    const p = state.puzzle;
    const cats = { A: p.categories[0], B: p.categories[1], C: p.categories[2] };
    for (const k of ["A", "B", "C"]) {
      const [cx, cy] = CIRCLES[k];
      svg.append(sv("circle", { cx, cy, r: R, class: "circle", fill: COLORS[k], "fill-opacity": 0.09, stroke: COLORS[k] }));
    }
    // labels: A top-left, B top-right, C bottom
    const small = svg.getBoundingClientRect().width < 560;
    const labelPos = { A: [16, 30, "start", 340], B: [704, 30, "end", 340], C: [360, 672, "middle", 560] };
    for (const k of ["A", "B", "C"]) {
      const [x, y, anchor, maxW] = labelPos[k];
      const t = sv("text", { x, y, "text-anchor": anchor, class: "circle-label" });
      t.textContent = cats[k].label;
      if (small) t.style.fontSize = "25px";
      requestAnimationFrame(() => {
        if (t.getComputedTextLength() > maxW) { t.setAttribute("textLength", maxW); t.setAttribute("lengthAdjust", "spacingAndGlyphs"); }
      });
      t.style.fill = COLORS[k];
      const rule = sv("title");
      rule.textContent = cats[k].rule;
      t.append(rule);
      t.style.cursor = "help";
      t.addEventListener("click", () => showRules());
      svg.append(t);
    }
    const ol = sv("text", { x: OUTSIDE_SLOT[0], y: SLOTS[""][0][1] - CHIP_H / 2 - 8, "text-anchor": "middle", class: "outside-label" });
    ol.textContent = "None of the three";
    if (small) ol.style.fontSize = "19px";
    svg.append(ol);
    // click targets per region: a transparent full-board rect resolves the region from the point
    const hit = sv("rect", { x: 0, y: 0, width: 720, height: 690, class: "region-hit" });
    hit.addEventListener("click", (e) => { if (state.sel != null) placeAt(svgPoint(e), state.sel); });
    svg.append(hit);
    // empty slots + counts
    const byRegion = groupPlaced();
    for (const code of REGIONS) {
      SLOTS[code].forEach(([x, y], i) => {
        if (!byRegion[code][i]) svg.append(sv("rect", { x: x - CHIP_W / 2, y: y - CHIP_H / 2, width: CHIP_W, height: CHIP_H, rx: CHIP_H / 2, class: "slot", "pointer-events": "none" }));
      });
    }
    // placed chips
    for (const code of REGIONS) {
      byRegion[code].forEach((idx, i) => {
        const [x, y] = SLOTS[code][i];
        svg.append(placedChip(idx, x, y));
      });
    }
  }

  function groupPlaced() {
    const by = Object.fromEntries(REGIONS.map((r) => [r, []]));
    const cards = state.puzzle.cards;
    if (state.checked && state.showAnswers) {
      cards.forEach((c, i) => by[c.region].push(i));
    } else {
      for (const [idx, code] of Object.entries(state.place)) by[code].push(Number(idx));
    }
    return by;
  }

  function placedChip(idx, x, y) {
    const c = state.puzzle.cards[idx];
    const g = sv("g", { class: "pchip", transform: `translate(${x - CHIP_W / 2},${y - CHIP_H / 2})` });
    if (state.sel === idx) g.classList.add("sel");
    if (state.checked) g.classList.add(state.place[idx] === c.region ? "ok" : "bad");
    g.append(sv("rect", { width: CHIP_W, height: CHIP_H, rx: CHIP_H / 2 }));
    const small = $("#venn").getBoundingClientRect().width < 560;   // phone: last names, bigger text
    const t = sv("text", { x: CHIP_W / 2, y: CHIP_H / 2 + (small ? 6 : 4), "text-anchor": "middle" });
    t.textContent = small && state.puzzle.pack === "baseball" ? shortName(idx) : c.name;
    if (small) t.style.fontSize = total() > 17 ? "17px" : "20px";
    else if (total() > 17) t.style.fontSize = "11.5px";
    g.append(t);
    const tip = sv("title");
    tip.textContent = `${c.name} (${c.sub})`;
    g.append(tip);
    requestAnimationFrame(() => {
      if (t.getComputedTextLength && t.getComputedTextLength() > CHIP_W - 10) {
        t.setAttribute("textLength", CHIP_W - 10);
        t.setAttribute("lengthAdjust", "spacingAndGlyphs");
      }
    });
    if (!state.checked) {
      g.addEventListener("pointerdown", (e) => startDrag(e, idx));
    }
    return g;
  }

  // "deGrom"; "M. Ramirez" when two players in the puzzle share a last name
  function shortName(idx) {
    const cards = state.puzzle.cards;
    const last = (n) => n.split(" ").slice(1).join(" ") || n;
    const l = last(cards[idx].name);
    const dup = cards.filter((c) => last(c.name) === l).length > 1;
    return dup ? `${cards[idx].name[0]}. ${l}` : l;
  }

  function drawTray() {
    const tray = $("#tray");
    tray.replaceChildren();
    const cards = state.puzzle.cards;
    const unplaced = cards.map((c, i) => i).filter((i) => state.place[i] === undefined);
    for (const i of unplaced) {
      const c = cards[i];
      const chip = el("div", { class: "chip" + (state.sel === i ? " sel" : ""), title: `${c.name} (${c.sub})` },
        c.name, el("small", {}, c.sub));
      if (!state.checked) chip.addEventListener("pointerdown", (e) => startDrag(e, i));
      tray.append(chip);
    }
    if (!unplaced.length) tray.append(el("div", { class: "hint" }, state.checked ? "" : `All ${total()} placed — check when you're ready.`));
    const n = Object.keys(state.place).length;
    $("#placed-count").textContent = `${n} / ${total()} placed`;
    $("#btn-check").disabled = state.checked || n !== total();
    $("#btn-check").textContent = state.checked ? "Checked" : "Check (one try)";
    $("#btn-clear").disabled = state.checked;
    $("#tray-hint").classList.toggle("hidden", state.checked);
  }

  function drawResult() {
    const box = $("#result");
    $(".tray-wrap").classList.toggle("hidden", state.checked);
    if (!state.checked) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const p = state.puzzle;
    const score = p.cards.filter((c, i) => state.place[i] === c.region).length;
    const name = (code) => code === "" ? "None of the three" :
      code.split("").map((k) => p.categories["ABC".indexOf(k)].label).join(" + ") + (code.length === 1 ? " only" : "");
    const order = (c, i) => (state.place[i] === c.region ? 100 : 0) + REGIONS.indexOf(c.region);   // misses first
    const toggle = el("button", { class: "ghost", onclick: () => { state.showAnswers = !state.showAnswers; drawBoard(); toggle.textContent = state.showAnswers ? "Show my board" : "Show correct spots"; } },
      state.showAnswers ? "Show my board" : "Show correct spots");
    box.replaceChildren(
      el("div", { class: "score" },
        el("span", { class: "big" }, String(score)), el("span", { class: "of" }, `/ ${total()}`),
        el("span", {}, verdict(score / total())),
        el("div", { class: "result-actions" }, toggle, el("button", { class: "primary", onclick: share }, "Share"))),
      el("div", { class: "answers" }, ...p.cards.map((c, i) => [c, i]).sort((a, b) => order(a[0], a[1]) - order(b[0], b[1])).map(([c, i]) => {
        const ok = state.place[i] === c.region;
        return el("div", { class: `ans ${ok ? "ok" : "bad"}` },
          el("div", { class: "who" }, `${ok ? "✓" : "✗"} ${c.name} `, el("span", { class: "hint" }, c.sub)),
          el("div", { class: "where" }, ok ? name(c.region) : `${name(c.region)} — you had: ${name(state.place[i])}`),
          el("ul", {}, ...c.facts.map((f, k) => el("li", {}, `${"ABC"[k]}: ${f}`))));
      })));
  }

  const verdict = (f) => f === 1 ? "Perfect! 🏆" : f >= 0.88 ? "Excellent" : f >= 0.7 ? "Solid" : f >= 0.47 ? "Not bad" : "Tough one";

  // ── interaction ──────────────────────────────────────────────────────────
  function svgPoint(e) {
    const svg = $("#venn");
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return [p.x, p.y];
  }

  function placeAt([x, y], idx) {
    if (x < 0 || y < 0 || x > 720 || y > 690) return false;
    const code = regionAt(x, y);
    const inRegion = Object.entries(state.place).filter(([i, c]) => c === code && Number(i) !== idx).length;
    if (inRegion >= NEED[code]) {
      toast(code === "" ? "Only one player goes outside all three circles" : `That part only holds ${NEED[code]}`);
      return false;
    }
    state.place[idx] = code;
    state.sel = null;
    save();
    drawBoard(); drawTray();
    return true;
  }

  function unplace(idx) {
    delete state.place[idx];
    state.sel = null;
    save();
    drawBoard(); drawTray();
  }

  let drag = null;
  function startDrag(e, idx) {
    if (state.checked) return;
    e.preventDefault();
    const c = state.puzzle.cards[idx];
    drag = { idx, x0: e.clientX, y0: e.clientY, moved: false, ghost: null, fromBoard: state.place[idx] !== undefined };
    const move = (ev) => {
      if (!drag) return;
      if (!drag.moved && Math.hypot(ev.clientX - drag.x0, ev.clientY - drag.y0) < 6) return;
      if (!drag.moved) {
        drag.moved = true;
        drag.ghost = el("div", { class: "chip ghost-drag" }, c.name);
        document.body.append(drag.ghost);
      }
      drag.ghost.style.left = `${ev.clientX - 50}px`;
      drag.ghost.style.top = `${ev.clientY - 18}px`;
    };
    const up = (ev) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const d = drag;
      drag = null;
      if (d.ghost) d.ghost.remove();
      if (!d.moved) {          // a tap: select / deselect, or send a placed chip back
        if (d.fromBoard && state.sel === d.idx) return unplace(d.idx);
        // another player is selected and this one is on the board: put the selected player here
        if (d.fromBoard && state.sel != null && state.sel !== d.idx) return placeAt(svgPoint(ev), state.sel);
        state.sel = state.sel === d.idx ? null : d.idx;
        drawBoard(); drawTray();
        return;
      }
      const svgRect = $("#venn").getBoundingClientRect();
      const inside = ev.clientX >= svgRect.left && ev.clientX <= svgRect.right && ev.clientY >= svgRect.top && ev.clientY <= svgRect.bottom;
      if (inside) placeAt(svgPoint(ev), d.idx);
      else if (d.fromBoard) unplace(d.idx);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function check() {
    if (Object.keys(state.place).length !== total() || state.checked) return;
    state.checked = true;
    state.sel = null;
    save();
    render();
    if (window.innerWidth < 860) $("#result").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function share() {
    const p = state.puzzle;
    const sq = (i) => (state.place[i] === p.cards[i].region ? "🟩" : "🟥");
    const by = Object.fromEntries(REGIONS.map((r) => [r, []]));
    p.cards.forEach((c, i) => by[c.region].push(sq(i)));
    const score = p.cards.filter((c, i) => state.place[i] === c.region).length;
    const text = [`Triple Play ${PACKS[p.pack] || ""} #${p.number} — ${score}/${total()}`,
      `◎ ${by.ABC.join("")}  ⧉ ${by.AB.join("")} ${by.AC.join("")} ${by.BC.join("")}`,
      `○ ${by.A.join("")} ${by.B.join("")} ${by.C.join("")}  ✕ ${by[""].join("")}`,
      location.href.split("#")[0]].join("\n");
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
      () => toast("Result copied — paste it anywhere"), () => prompt("Copy your result:", text));
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
    modal(el("h2", {}, "How to play"),
      el("p", {}, "Three circles, 17 cards. Put every card in the one part of the diagram that fits it:"),
      el("ul", {},
        el("li", {}, "1 in the middle (all three circles)"),
        el("li", {}, "2 in each overlap of exactly two circles"),
        el("li", {}, "3 in each part that belongs to only one circle"),
        el("li", {}, "1 outside all three")),
      el("p", {}, "Sunday is the big one: 25 cards (2 in the middle, 3 in each overlap, 4 in each single circle, 2 outside)."),
      el("p", {}, "Tap a card and then a part of the diagram, or drag it there. Tap a placed card twice to send it back."),
      el("p", {}, "You get one check. Your score is how many cards are in the right place."),
      el("p", {}, "A new puzzle every day: cities & states on Monday (MLB's traditional off day), baseball players the rest of the week — Tuesday easiest, Friday and Saturday hardest (more players close to a circle's line), and the big puzzle on Sunday."),
      el("p", { class: "hint" }, "Tap a circle's label for its exact rule (e.g. what counts as \"played shortstop\")."),
      el("p", { class: "hint" }, `Data: ${state.index?.source || "Lahman Baseball Database"}.`));
  }
  function showRules() {
    const p = state.puzzle;
    modal(el("h2", {}, "Today's rules"),
      el("ul", { class: "rule-list" }, ...p.categories.map((c, i) =>
        el("li", {}, el("strong", { style: `color:${COLORS["ABC"[i]]}` }, c.label), " — ", c.rule))),
      el("p", { class: "hint" }, p.pack === "places"
        ? "Teams and facts are for the 2026 season; a metro counts teams in its suburbs (the Giants and Jets are New York). A state counts every team and school inside it."
        : "Stats are regular-season totals from the Lahman Baseball Database. A player only appears in a puzzle if he isn't a borderline case for its circles (e.g. a handful of games for a team)."));
  }
  function showArchive() {
    const list = [...available()].reverse();
    modal(el("h2", {}, "Archive"),
      el("div", { class: "arch" }, ...list.map((q) => {
        const saved = loadSaved(q.date);
        let s = "not played";
        if (saved?.checked) {
          // score needs the puzzle; show it when its month is loaded
          s = "played";
          const m = months[q.date.slice(0, 7)];
          const pz = m && m.find((x) => x.date === q.date);
          if (pz) s = `${pz.cards.filter((c, i) => saved.place[i] === c.region).length}/${pz.cards.length}`;
        } else if (saved && Object.keys(saved.place || {}).length) s = "in progress";
        const d = new Date(q.date + "T12:00:00");
        return el("button", { class: saved?.checked ? "done" : "", onclick: () => { $("#modal").classList.add("hidden"); location.hash = q.date; } },
          `#${q.number} · ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`,
          el("span", { class: "s" }, `${q.pack === "places" ? "cities & states" : q.level === "big" ? "big Sunday" : q.level} · ${s}`));
      })));
  }

  // ── boot ─────────────────────────────────────────────────────────────────
  async function boot() {
    $("#packs").replaceChildren();
    state.index = await (await fetch("puzzles/daily/index.json")).json();
    const go = () => {
      const want = location.hash.slice(1);
      const list = available();
      const pick = list.find((q) => q.date === want) || list.at(-1) || state.index.puzzles[0];
      loadPuzzle(pick.date);
    };
    window.addEventListener("hashchange", go);
    let rz;
    window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => state.puzzle && drawBoard(), 150); });
    $("#btn-check").addEventListener("click", check);
    $("#btn-clear").addEventListener("click", () => { state.place = {}; state.sel = null; save(); drawBoard(); drawTray(); });
    $("#btn-help").addEventListener("click", showHelp);
    $("#btn-archive").addEventListener("click", showArchive);
    $("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
    $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });
    go();
    if (!localStorage.getItem("triple-play:seen-help")) { localStorage.setItem("triple-play:seen-help", "1"); showHelp(); }
  }
  boot().catch((err) => { document.body.prepend(el("p", { style: "color:#b91c1c;padding:12px" }, `Could not load the puzzle: ${err.message}`)); });
})();
