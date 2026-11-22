// Home Turf rules engine: pure functions over a plain state object (no page code), so the page,
// the AI and the node tests (tests/test_home_turf.py) run the same rules.
//
// A soldier is a real big-leaguer called up from a territory's bench (its natives, best career
// Open WAR first). In a battle each side sends one soldier (picked secretly); each plays one of
// his remaining real seasons, drawn at random and used up; the defender adds the home-field edge;
// the higher season wins (ties to the defender) and the loser is out of the game. A soldier with
// no seasons left retires and his territory calls up a replacement; one whose best remaining
// season is weak can be released for a call-up the same way.
"use strict";

(function () {
  // ── random numbers (seeded, resumable: the state carries the generator) ─────────
  function rand(state) {
    let t = (state.rng = (state.rng + 0x6d2b79f5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  function seedOf(text) {
    let h = 2166136261;
    for (const c of String(text)) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
    return h;
  }

  // the rules in force: rules.toml plus the chosen game length's overrides (state.lengthRules)
  function R(state, data) {
    if (!state || !state.lengthRules) return data.rules;
    const ai = Object.assign({}, data.rules.ai, state.lengthRules.ai || {});
    return Object.assign({}, data.rules, state.lengthRules, { ai });
  }

  // game.json stores rosters compactly (build.py compact()); expand them once after loading:
  // {name, born, seasons: [[year, WAR], ...], war: career} plus an id per roster place
  function prepare(data) {
    if (data._prepared || data.version < 2) return data;
    for (const [tid, roster] of Object.entries(data.rosters)) {
      data.rosters[tid] = roster.map((p, k) => {
        const s = p.s, seasons = [[s[0], s[1] / 10]];
        for (let j = 2; j < s.length; j += 2) seasons.push([seasons[seasons.length - 1][0] + s[j], s[j + 1] / 10]);
        const war = Math.round(seasons.reduce((a, x) => a + x[1] * 10, 0)) / 10;
        return { id: `${tid}-${k}`, name: p.n, born: p.b || "", seasons, war };
      });
    }
    data._prepared = true;
    return data;
  }

  // ── map helpers ─────────────────────────────────────────────────────────────
  function index(data) {
    if (data._ix) return data._ix;
    const byId = {}, regionOf = {}, members = {};
    for (const t of data.territories) {
      byId[t.id] = t;
      regionOf[t.id] = t.region;
      (members[t.region] = members[t.region] || []).push(t.id);
    }
    return (data._ix = { byId, regionOf, members });
  }
  const neighbours = (data, tid) => { const t = index(data).byId[tid]; return [...t.land, ...t.sea]; };
  const adjacent = (data, a, b) => neighbours(data, a).includes(b);
  const owned = (state, seat) => Object.keys(state.owner).filter((t) => state.owner[t] === seat);

  // ── soldiers ────────────────────────────────────────────────────────────────
  const mean = (s) => (s.seasons.length ? s.seasons.reduce((a, x) => a + x[1], 0) / s.seasons.length : -9);
  const best = (s) => (s.seasons.length ? Math.max(...s.seasons.map((x) => x[1])) : -9);
  function benchNext(state, data, tid) {
    const roster = data.rosters[tid] || [];
    return state.bench[tid] < roster.length ? roster[state.bench[tid]] : null;
  }
  // call up the best remaining native of `tid` into its stack (null when the bench is empty)
  function callup(state, data, tid) {
    const p = benchNext(state, data, tid);
    if (!p) return null;
    state.bench[tid]++;
    const sid = `s${state.nextSid++}`;
    state.soldiers[sid] = { pid: p.id, name: p.name, home: tid, war: p.war, seasons: p.seasons.map((x) => x.slice()), used: [] };
    state.stacks[tid].push(sid);
    return sid;
  }
  function removeSoldier(state, tid, sid) {
    state.stacks[tid] = state.stacks[tid].filter((x) => x !== sid);
    state.soldiers[sid].out = true;
  }

  // P(attacker's drawn season > defender's drawn season + home), every pair of remaining seasons equally likely
  function winProb(a, d, home) {
    if (!a.seasons.length || !d.seasons.length) return a.seasons.length ? 1 : 0;
    let wins = 0;
    for (const x of a.seasons) for (const y of d.seasons) if (x[1] > y[1] + home) wins++;
    return wins / (a.seasons.length * d.seasons.length);
  }

  // ── a new game ──────────────────────────────────────────────────────────────
  const COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2"];
  const AI_NAMES = ["The Scout", "The Skipper", "The GM", "The Owner", "The Commissioner"];
  function newGame(data, opts = {}) {
    const n = opts.players || data.rules.players;
    const state = {
      rng: seedOf(opts.seed ?? "home-turf"), seed: String(opts.seed ?? "home-turf"),
      round: 1, phase: "draft", turn: 0, step: null, pending: 0, fortified: false, capture: null,
      seats: [], owner: {}, stacks: {}, bench: {}, soldiers: {}, nextSid: 1, log: [], draftOrder: [], draftAt: 0,
      lastBattle: null, winner: null, length: opts.length || "standard", lengthRules: null,
    };
    const L = (data.rules.lengths || {})[state.length];
    if (L) { const { label, note, ...over } = L; state.lengthRules = over; }
    for (let k = 0; k < n; k++) {
      const human = opts.humanSeats ? opts.humanSeats.includes(k) : k === 0;
      state.seats.push({ name: human ? (opts.name || "You") : AI_NAMES[(k - 1 + AI_NAMES.length) % AI_NAMES.length],
        color: COLORS[k], ai: !human, alive: true, strategy: opts.strategies?.[k] || "smart" });
    }
    for (const t of data.territories) { state.owner[t.id] = null; state.stacks[t.id] = []; state.bench[t.id] = 0; }
    // snake draft in a random seat order: 1 2 3 4 4 3 2 1 ...
    const order = [...Array(n).keys()];
    for (let k = n - 1; k > 0; k--) { const j = Math.floor(rand(state) * (k + 1)); [order[k], order[j]] = [order[j], order[k]]; }
    for (let r = 0; state.draftOrder.length < data.territories.length; r++) {
      state.draftOrder.push(...(r % 2 ? [...order].reverse() : order));
    }
    state.draftOrder.length = data.territories.length;
    state.turn = state.draftOrder[0];
    log(state, `Draft order: ${order.map((k) => state.seats[k].name).join(", ")} (snake).`);
    return state;
  }
  function log(state, text, extra = {}) { state.log.push({ round: state.round, text, ...extra }); }

  // ── draft and deployment ────────────────────────────────────────────────────
  function draft(state, data, tid) {
    if (state.phase !== "draft" || state.owner[tid] !== null) throw new Error("that territory is taken");
    const seat = state.draftOrder[state.draftAt];
    state.owner[tid] = seat;
    const sid = callup(state, data, tid);
    log(state, `${state.seats[seat].name} drafts ${index(data).byId[tid].name}` + (sid ? ` (${state.soldiers[sid].name})` : ""));
    state.draftAt++;
    if (state.draftAt >= state.draftOrder.length) {
      state.phase = "deploy";
      state.deployLeft = Object.fromEntries(state.seats.map((_, k) => [k, R(state, data).start_callups]));
      state.turn = state.draftOrder[0];
      state.pending = R(state, data).start_callups;
    } else {
      state.turn = state.draftOrder[state.draftAt];
    }
  }
  function regionsHeld(state, data, seat) {
    const { members } = index(data);
    return Object.keys(members).filter((r) => members[r].every((t) => state.owner[t] === seat));
  }
  function callupsFor(state, data, seat) {
    const n = owned(state, seat).length;
    const bonus = regionsHeld(state, data, seat).reduce((a, r) => a + data.regions[r].bonus, 0);
    return Math.max(R(state, data).callups_min, Math.floor(n / R(state, data).territories_per_callup)) + bonus;
  }
  // place one call-up (deploy phase or the turn's call-ups) in an owned territory
  function place(state, data, tid) {
    if (state.owner[tid] !== state.turn) throw new Error("not your territory");
    if (state.pending <= 0) throw new Error("no call-ups left");
    const sid = callup(state, data, tid);
    if (!sid) throw new Error(`${index(data).byId[tid].name} has no players left`);
    state.pending--;
    log(state, `${state.seats[state.turn].name} calls up ${state.soldiers[sid].name} in ${index(data).byId[tid].name}`);
    if (state.phase === "deploy" && state.pending === 0) {
      state.deployLeft[state.turn] = 0;
      const next = state.seats.findIndex((_, k) => state.deployLeft[k] > 0);
      if (next === -1) startTurn(state, data, state.draftOrder[0]);
      else { state.turn = next; state.pending = state.deployLeft[next]; }
    } else if (state.phase === "turn" && state.pending === 0) {
      state.step = "attack";
    }
    return sid;
  }
  // a call-up nobody can place (every owned bench empty) is lost
  function canPlace(state, data) { return owned(state, state.turn).some((t) => benchNext(state, data, t)); }
  function skipPlacement(state, data) {
    state.pending = 0;
    if (state.phase === "deploy") {
      state.deployLeft[state.turn] = 0;
      const next = state.seats.findIndex((_, k) => state.deployLeft[k] > 0);
      if (next === -1) startTurn(state, data, state.draftOrder[0]); else { state.turn = next; state.pending = state.deployLeft[next]; }
    } else state.step = "attack";
  }

  // ── turns ───────────────────────────────────────────────────────────────────
  function startTurn(state, data, seat) {
    state.phase = "turn";
    state.turn = seat;
    state.step = "callups";
    state.fortified = false;
    state.pending = callupsFor(state, data, seat);
    if (!canPlace(state, data)) { state.pending = 0; state.step = "attack"; }
  }
  function endTurn(state, data) {
    if (state.capture) throw new Error("move into the captured territory first");
    const n = state.seats.length;
    let k = state.turn;
    for (let step = 0; step < n; step++) {
      k = (k + 1) % n;
      if (k === state.draftOrder[0]) state.round++;
      if (state.seats[k].alive) break;
    }
    const maxR = R(state, data).max_rounds;
    if (maxR > 0 && state.round > maxR) return finish(state, data);
    startTurn(state, data, k);
  }

  // ── battles ─────────────────────────────────────────────────────────────────
  function canAttack(state, data, from, to) {
    return state.phase === "turn" && !state.capture && state.owner[from] === state.turn && state.owner[to] !== state.turn
      && adjacent(data, from, to) && state.stacks[from].length >= 2 && state.stacks[to].length >= 1;
  }
  function drawSeason(state, s) {
    const k = Math.floor(rand(state) * s.seasons.length);
    const season = s.seasons.splice(k, 1)[0];
    s.used.push(season);
    return season;
  }
  // a soldier with no seasons left retires; his territory's owner calls up a replacement there
  function retireIfDone(state, data, tid, sid) {
    const s = state.soldiers[sid];
    if (s.seasons.length) return null;
    removeSoldier(state, tid, sid);
    const rep = callup(state, data, tid);
    log(state, `${s.name} retires (no seasons left)` + (rep ? `; ${state.soldiers[rep].name} is called up in ${index(data).byId[tid].name}` : ""));
    return rep;
  }
  function battle(state, data, from, to, sa, sd) {
    if (!canAttack(state, data, from, to)) throw new Error("can't attack there");
    if (!state.stacks[from].includes(sa) || !state.stacks[to].includes(sd)) throw new Error("pick soldiers from the two stacks");
    const A = state.soldiers[sa], D = state.soldiers[sd], home = R(state, data).home_field;
    const p = winProb(A, D, home);
    const a = drawSeason(state, A), d = drawSeason(state, D);
    const attackerWins = a[1] > d[1] + home;
    const [wTid, wSid, lTid, lSid] = attackerWins ? [from, sa, to, sd] : [to, sd, from, sa];
    removeSoldier(state, lTid, lSid);
    const att = state.seats[state.turn].name, def = state.seats[state.owner[to]].name;
    const result = { from, to, attacker: sa, defender: sd, aSeason: a, dSeason: d, attackerWins, p, round: state.round,
      text: `${A.name} (${a[0]}, ${fmt(a[1])} WAR) ${attackerWins ? "beats" : "loses to"} ${D.name} (${d[0]}, ${fmt(d[1])} + ${home} home)` };
    log(state, `${att} attacks ${index(data).byId[to].name} from ${index(data).byId[from].name}: ${result.text}; ${state.soldiers[lSid].name} is out`, { battle: true });
    retireIfDone(state, data, wTid, wSid);
    state.lastBattle = result;
    if (!state.stacks[to].length) {   // captured
      const loser = state.owner[to];
      state.owner[to] = state.turn;
      state.capture = { from, to };
      log(state, `${att} captures ${index(data).byId[to].name} from ${def}`);
      checkOut(state, data, loser);
      result.captured = true;
      if (state.stacks[from].length < 2) {   // nobody can move in: the territory's own bench sends a call-up
        const sid = callup(state, data, to);
        state.capture = null;
        if (sid) log(state, `${state.soldiers[sid].name} is called up to hold ${index(data).byId[to].name}`);
      }
      if (owned(state, state.turn).length === data.territories.length) finish(state, data);
    }
    return result;
  }
  function moveIn(state, data, count) {
    const c = state.capture;
    if (!c) throw new Error("nothing to move");
    const stack = state.stacks[c.from];
    count = Math.max(1, Math.min(count, stack.length - 1));
    const moving = [...stack].sort((x, y) => mean(state.soldiers[y]) - mean(state.soldiers[x])).slice(0, count);
    state.stacks[c.from] = stack.filter((s) => !moving.includes(s));
    state.stacks[c.to].push(...moving);
    state.capture = null;
    return moving;
  }
  function checkOut(state, data, seat) {
    if (seat === null || owned(state, seat).length) return;
    state.seats[seat].alive = false;
    log(state, `${state.seats[seat].name} is out of the game`);
    if (state.seats.filter((s) => s.alive).length === 1) finish(state, data);
  }

  // ── releases and fortifying ─────────────────────────────────────────────────
  function canRelease(state, data, tid, sid) {
    const s = state.soldiers[sid];
    return state.phase === "turn" && state.owner[tid] === state.turn && state.stacks[tid].includes(sid)
      && best(s) < R(state, data).release_below && !!benchNext(state, data, tid);
  }
  function release(state, data, tid, sid) {
    if (!canRelease(state, data, tid, sid)) throw new Error("can't release him");
    const name = state.soldiers[sid].name;
    removeSoldier(state, tid, sid);
    const rep = callup(state, data, tid);
    log(state, `${state.seats[state.turn].name} releases ${name}; ${state.soldiers[rep].name} is called up in ${index(data).byId[tid].name}`);
    return rep;
  }
  function connected(state, data, from, to) {   // through territories the mover owns
    const seat = state.owner[from], seen = new Set([from]), queue = [from];
    while (queue.length) {
      const t = queue.shift();
      if (t === to) return true;
      for (const n of neighbours(data, t)) if (!seen.has(n) && state.owner[n] === seat) { seen.add(n); queue.push(n); }
    }
    return false;
  }
  function fortify(state, data, from, to, sids) {
    if (state.phase !== "turn" || state.fortified || state.capture) throw new Error("one move per turn, after battles");
    if (state.owner[from] !== state.turn || state.owner[to] !== state.turn || from === to || !connected(state, data, from, to)) throw new Error("not connected");
    if (!sids.length || sids.length >= state.stacks[from].length) throw new Error("leave at least one soldier");
    state.stacks[from] = state.stacks[from].filter((s) => !sids.includes(s));
    state.stacks[to].push(...sids);
    state.fortified = true;
    log(state, `${state.seats[state.turn].name} moves ${sids.length} from ${index(data).byId[from].name} to ${index(data).byId[to].name}`);
  }

  // ── the end ─────────────────────────────────────────────────────────────────
  function score(state, data, seat) {
    const s = R(state, data).score;
    const terr = owned(state, seat).length;
    const regions = s.region_bonus ? regionsHeld(state, data, seat).reduce((a, r) => a + data.regions[r].bonus, 0) : 0;
    const war = owned(state, seat).reduce((a, t) => a + state.stacks[t].reduce((b, sid) => b + Math.max(0, mean(state.soldiers[sid])), 0), 0);
    return { territories: terr, regions, total: terr * s.per_territory + regions, war };
  }
  function finish(state, data) {
    state.phase = "over";
    state.capture = null;
    const ranked = state.seats.map((_, k) => [k, score(state, data, k)])
      .sort((a, b) => b[1].total - a[1].total || b[1].war - a[1].war);
    state.winner = ranked[0][0];
    state.standings = ranked.map(([k, sc]) => ({ seat: k, ...sc }));
    log(state, `Game over: ${state.seats[state.winner].name} wins with ${ranked[0][1].total} points`);
  }

  // ── picking soldiers (the AI and "autorank") ─────────────────────────────────
  // best: strongest by average remaining season; weakest: send the weakest; smart: the cheapest
  // soldier who is at least even against the opponent's stack on average, else the strongest.
  function pickSoldier(state, data, mine, theirs, role, strategy) {
    const home = R(state, data).home_field;
    const S = mine.map((sid) => state.soldiers[sid]);
    if (strategy === "weakest") return mine[S.reduce((k, s, j) => (mean(s) < mean(S[k]) ? j : k), 0)];
    const byStrength = mine.map((sid, j) => [sid, mean(S[j])]).sort((a, b) => b[1] - a[1]);
    if (strategy === "best" || !theirs.length) return byStrength[0][0];
    const vsAll = (s) => theirs.reduce((a, o) => a + (role === "attack" ? winProb(s, state.soldiers[o], home) : 1 - winProb(state.soldiers[o], s, home)), 0) / theirs.length;
    const ok = byStrength.filter(([sid]) => vsAll(state.soldiers[sid]) >= 0.5);
    return ok.length ? ok[ok.length - 1][0] : byStrength[0][0];
  }

  // ── AI managers ─────────────────────────────────────────────────────────────
  const strength = (state, tid) => state.stacks[tid].reduce((a, sid) => a + 0.6 + Math.max(0, mean(state.soldiers[sid])), 0);
  function threat(state, data, tid) {
    const me = state.owner[tid];
    return neighbours(data, tid).filter((n) => state.owner[n] !== me && state.owner[n] !== null)
      .reduce((a, n) => a + strength(state, n), 0);
  }
  function depth(data, tid) { return (data.rosters[tid] || []).slice(0, 10).reduce((a, p) => a + p.war, 0); }
  function aiDraft(state, data) {
    const seat = state.draftOrder[state.draftAt], { members, regionOf } = index(data);
    let bestT = null, bestV = -Infinity;
    for (const t of data.territories) {
      if (state.owner[t.id] !== null) continue;
      const reg = members[regionOf[t.id]];
      const mine = reg.filter((x) => state.owner[x] === seat).length, theirs = reg.filter((x) => state.owner[x] !== null && state.owner[x] !== seat).length;
      const near = neighbours(data, t.id).filter((n) => state.owner[n] === seat).length;
      const v = depth(data, t.id) / 100 + (theirs ? 0 : 2.5 * (mine + 1) / reg.length * data.regions[regionOf[t.id]].bonus)
        + 0.8 * near + rand(state) * 0.8;
      if (v > bestV) { bestV = v; bestT = t.id; }
    }
    draft(state, data, bestT);
  }
  function aiPlace(state, data) {
    while (state.pending > 0 && (state.phase === "deploy" || state.step === "callups")) {
      const seat = state.turn;
      const options = owned(state, seat).filter((t) => benchNext(state, data, t));
      if (!options.length) { skipPlacement(state, data); return; }
      let bestT = options[0], bestV = -Infinity;
      for (const t of options) {
        const nxt = benchNext(state, data, t);
        const v = threat(state, data, t) - 0.7 * strength(state, t) + 0.15 * nxt.war / Math.max(nxt.seasons.length, 1) * 3 + rand(state) * 0.3;
        if (v > bestV) { bestV = v; bestT = t; }
      }
      place(state, data, bestT);
      if (state.turn !== seat) return;   // deployment moved on to the next manager
    }
  }
  // An AI turn in steps, so a person defending can pick between them: aiStart (call-ups, releases),
  // then aiNextAttack until it returns null (each: {from, to, attacker sid}; the caller picks the
  // defender and calls battle, then aiAfterBattle), then aiFortify. aiTurn runs them all.
  function aiStart(state, data) {
    const seat = state.turn;
    state.aiAttacks = 0;
    aiPlace(state, data);
    if (state.phase !== "turn" || state.turn !== seat) return;
    for (const t of owned(state, seat)) for (const sid of [...state.stacks[t]]) {
      if (canRelease(state, data, t, sid) && state.stacks[t].length > 1) release(state, data, t, sid);
    }
  }
  function aiNextAttack(state, data) {
    const seat = state.turn;
    if (state.phase !== "turn" || state.aiAttacks >= R(state, data).ai.max_attacks) return null;
    let pick = null, bestR = R(state, data).ai.aggression;
    for (const from of owned(state, seat)) {
      if (state.stacks[from].length < 2) continue;
      for (const to of neighbours(data, from)) {
        if (!canAttack(state, data, from, to)) continue;
        const r = (strength(state, from) - 0.6) / (strength(state, to) + R(state, data).home_field);
        if (r > bestR) { bestR = r; pick = [from, to]; }
      }
    }
    if (!pick) return null;
    const [from, to] = pick;
    const strat = rand(state) < 0.25 ? "best" : state.seats[seat].strategy;
    state.aiAttacks++;
    return { from, to, attacker: pickSoldier(state, data, state.stacks[from], state.stacks[to], "attack", strat) };
  }
  function aiAfterBattle(state, data) {
    const c = state.capture;
    if (c) moveIn(state, data, Math.max(1, Math.ceil((state.stacks[c.from].length - 1) * 0.6)));
  }
  function aiTurn(state, data, opts = {}) {
    const events = [];
    aiStart(state, data);
    let a;
    while ((a = aiNextAttack(state, data))) {
      const sd = opts.defend ? opts.defend(state, data, a.to, a.from, a.attacker)
        : pickSoldier(state, data, state.stacks[a.to], state.stacks[a.from], "defend", state.seats[state.owner[a.to]].strategy);
      events.push(battle(state, data, a.from, a.to, a.attacker, sd));
      aiAfterBattle(state, data);
    }
    if (state.phase === "turn") aiFortify(state, data);
    return events;
  }
  function aiFortify(state, data) {
    const seat = state.turn, mine = owned(state, seat);
    const interior = mine.filter((t) => threat(state, data, t) === 0 && state.stacks[t].length > 1)
      .sort((a, b) => state.stacks[b].length - state.stacks[a].length);
    const border = mine.filter((t) => threat(state, data, t) > 0).sort((a, b) => (threat(state, data, b) - strength(state, b)) - (threat(state, data, a) - strength(state, a)));
    for (const from of interior) {
      const to = border.find((b) => connected(state, data, from, b));
      if (to) { fortify(state, data, from, to, state.stacks[from].slice(1)); return; }
    }
  }

  const fmt = (x) => (Math.round(x * 10) / 10).toFixed(1);
  const api = { prepare, R, rand, seedOf, index, neighbours, adjacent, owned, mean, best, benchNext, callup, winProb, newGame, draft, regionsHeld,
    callupsFor, place, canPlace, skipPlacement, startTurn, endTurn, canAttack, battle, moveIn, canRelease, release, connected,
    fortify, score, finish, pickSoldier, strength, threat, aiDraft, aiPlace, aiStart, aiNextAttack, aiAfterBattle, aiTurn, aiFortify, fmt };
  if (typeof window !== "undefined") window.HomeTurf = api;
  if (typeof module !== "undefined") module.exports = api;
})();
