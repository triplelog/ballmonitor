// Lineup: expected runs for a batting order, the same steps as chain.py `expected_runs`
// (a Markov chain over bases and outs), plus a random season for the "play it out" view.
// Rates per plate appearance, in OUTCOMES order; rules come from the puzzle file.
(function () {
  "use strict";

  const OUTCOMES = ["K", "BB", "1B", "2B", "3B", "HR", "OUT"];
  const N = 24;                                  // outs * 8 + bases (1 = 1st, 2 = 2nd, 4 = 3rd)
  const ones = (b) => (b & 1) + ((b >> 1) & 1) + ((b >> 2) & 1);

  function walk(bases) {
    if (!(bases & 1)) return [bases | 1, 0];
    if (!(bases & 2)) return [bases | 3, 0];
    if (!(bases & 4)) return [7, 0];
    return [7, 1];
  }

  // (outs, bases, outcome) -> [[probability, new outs, new bases, runs]]; new outs 3 = inning over
  function transitions(adv) {
    const out = {};
    for (let outs = 0; outs < 3; outs++) {
      for (let bases = 0; bases < 8; bases++) {
        const on1 = bases & 1, on2 = bases & 2, on3 = bases & 4;
        for (const o of OUTCOMES) {
          let res = [];
          if (o === "K") res = [[1, outs + 1, bases, 0]];
          else if (o === "BB") { const [nb, r] = walk(bases); res = [[1, outs, nb, r]]; }
          else if (o === "HR") res = [[1, outs, 0, 1 + ones(bases)]];
          else if (o === "3B") res = [[1, outs, 4, ones(bases)]];
          else if (o === "2B") {
            const runs = (on2 ? 1 : 0) + (on3 ? 1 : 0);
            if (on1) { const p = adv.first_scores_on_double; res = [[p, outs, 2, runs + 1], [1 - p, outs, 6, runs]]; }
            else res = [[1, outs, 2, runs]];
          } else if (o === "1B") {
            const runs = on3 ? 1 : 0;
            const opts2 = on2 ? [[adv.second_scores_on_single, true], [1 - adv.second_scores_on_single, false]] : [[1, null]];
            for (const [p2, scored2] of opts2) {
              const thirdOpen = !(on2 && !scored2);
              const r = runs + (scored2 ? 1 : 0);
              const nb = 1 | (on2 && !scored2 ? 4 : 0);
              if (on1) {
                const p13 = thirdOpen ? adv.first_to_third_on_single : 0;
                if (p13) res.push([p2 * p13, outs, nb | 4, r]);
                res.push([p2 * (1 - p13), outs, nb | 2, r]);
              } else res.push([p2, outs, nb, r]);
            }
          } else {                                     // OUT in play
            if (outs === 2) res = [[1, 3, bases, 0]];
            else {
              const dp = on1 ? adv.double_play : 0;
              if (dp) res.push([dp, outs + 2, bases & ~1, 0]);
              const rest = 1 - dp;
              const p3 = on3 ? adv.third_scores_on_out : 0;
              for (const [a3, scored3] of on3 ? [[p3, true], [1 - p3, false]] : [[1, false]]) {
                const thirdFree = !on3 || scored3;
                const p2 = on2 && thirdFree ? adv.second_to_third_on_out : 0;
                for (const [a2, moved2] of p2 ? [[p2, true], [1 - p2, false]] : [[1, false]]) {
                  const nb = ((on3 && !scored3) || moved2 ? 4 : 0) | (on2 && !moved2 ? 2 : 0);
                  const p1 = on1 && !(nb & 2) ? adv.first_to_second_on_out : 0;
                  for (const [a1, moved1] of p1 ? [[p1, true], [1 - p1, false]] : [[1, false]]) {
                    const b = nb | (moved1 ? 2 : (on1 ? 1 : 0));
                    res.push([rest * a3 * a2 * a1, outs + 1, b, scored3 ? 1 : 0]);
                  }
                }
              }
            }
          }
          out[`${outs},${bases},${o}`] = res.filter((t) => t[0] > 0);
        }
      }
    }
    return out;
  }

  function batterTables(rates, trans) {
    const T = Array.from({ length: N }, () => new Array(N).fill(0));
    const R = new Array(N).fill(0), X = new Array(N).fill(0);
    for (let outs = 0; outs < 3; outs++) {
      for (let bases = 0; bases < 8; bases++) {
        const s = outs * 8 + bases;
        OUTCOMES.forEach((o, i) => {
          for (const [q, no, nb, runs] of trans[`${outs},${bases},${o}`]) {
            const pq = rates[i] * q;
            R[s] += pq * runs;
            if (no >= 3) X[s] += pq; else T[s][no * 8 + nb] += pq;
          }
        });
      }
    }
    return { T, R, X };
  }

  // Expected runs per game and expected plate appearances per game for each lineup slot.
  function expectedRuns(order, ratesList, rules) {
    const trans = transitions(rules.advance);
    const tables = ratesList.map((r) => batterTables(r, trans));
    const n = order.length, depth = rules.game.max_batters_per_inning;
    const inning = [];
    for (let s = 0; s < n; s++) {
      let v = new Array(N).fill(0); v[0] = 1;
      let runs = 0;
      const nxt = new Array(n).fill(0), pa = new Array(n).fill(0);
      for (let k = 0; k < depth; k++) {
        const slot = (s + k) % n;
        const { T, R, X } = tables[order[slot]];
        let r = 0, x = 0, mass = 0;
        for (let i = 0; i < N; i++) { r += v[i] * R[i]; x += v[i] * X[i]; mass += v[i]; }
        runs += r; nxt[(s + k + 1) % n] += x; pa[slot] += mass;
        const w = new Array(N).fill(0);
        for (let i = 0; i < N; i++) { if (v[i]) for (let j = 0; j < N; j++) w[j] += v[i] * T[i][j]; }
        v = w;
      }
      inning.push({ runs, nxt, pa });
    }
    let lead = new Array(n).fill(0); lead[0] = 1;
    let total = 0;
    const pa = new Array(n).fill(0);
    for (let g = 0; g < rules.game.innings; g++) {
      const next = new Array(n).fill(0);
      for (let s = 0; s < n; s++) {
        total += lead[s] * inning[s].runs;
        for (let j = 0; j < n; j++) { next[j] += lead[s] * inning[s].nxt[j]; pa[j] += lead[s] * inning[s].pa[j]; }
      }
      lead = next;
    }
    return { runs: total, pa };
  }

  // A random season (seeded): runs and plate appearances per slot. For show: one season is mostly luck.
  function rng(seed) {
    let a = seed >>> 0;
    return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  const pick = (r, weights) => { let u = r(), i = 0; for (; i < weights.length - 1; i++) { u -= weights[i]; if (u < 0) return i; } return i; };

  function simulateSeason(order, ratesList, rules, seed) {
    const trans = transitions(rules.advance);
    const r = rng(seed);
    const n = order.length;
    const pa = new Array(n).fill(0), byGame = [];
    let runs = 0;
    for (let g = 0; g < rules.game.season_games; g++) {
      let slot = 0, gameRuns = 0;
      for (let inn = 0; inn < rules.game.innings; inn++) {
        let outs = 0, bases = 0;
        while (outs < 3) {
          const o = OUTCOMES[pick(r, ratesList[order[slot]])];
          const opts = trans[`${outs},${bases},${o}`];
          const [, no, nb, ru] = opts[pick(r, opts.map((t) => t[0]))];
          pa[slot]++; gameRuns += ru; outs = no; bases = nb;
          slot = (slot + 1) % n;
        }
      }
      runs += gameRuns; byGame.push(gameRuns);
    }
    return { runs, pa, byGame };
  }

  window.LineupChain = { OUTCOMES, transitions, expectedRuns, simulateSeason };
})();
