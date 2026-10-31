// What the catcher tells you on a mound visit. For every pitch you have, he
// works out the best spot to throw it to this batter in this count, using
// the same formulas that decide the pitch (swing, umpire, contact, hits)
// averaged over where it might really end up (your scatter plus a little
// aiming error), and scores each spot in runs. Then he adds what he knows
// about the hitter: hot and cold zones, the pitch types he handles, his eye
// and power, and what he has seen this at-bat.

import { ZONE, HEAT, PITCH_TYPES } from './data.js';
import { battingSide, locationScope, edgeDistance } from './pitch.js';
import { rates, leagueByType } from './pitchStats.js';

// Run values, about MLB: each count compared with 0-0 ([balls][strikes]),
// and how an at-bat ends.
const COUNT_RV = [
    [0, -0.037, -0.083],
    [0.032, -0.010, -0.064],
    [0.084, 0.037, -0.030],
    [0.153, 0.114, 0.059],
];
const END_RV = { BB: 0.31, HBP: 0.33, K: -0.28, out: -0.26, E: 0.45, '1B': 0.45, '2B': 0.75, '3B': 1.03, HR: 1.4 };

// Inches of aiming error on top of the pitch's scatter (the zone moves).
const AIM_ERROR = 1.5;
// Three-point Gauss–Hermite rule in each direction (nodes in standard
// deviations, weights summing to 1).
const GH = [[-Math.sqrt(3), 1 / 6], [0, 2 / 3], [Math.sqrt(3), 1 / 6]];
// Spots considered, as where the ball should cross (zone inches).
const TARGET_X = [-12.5, -10, -7.5, -5, -2.5, 0, 2.5, 5, 7.5, 10, 12.5];
const TARGET_Y = [-17.5, -15, -12.5, -10, -7.5, -5, -2.5, 0, 2.5, 5, 7.5, 10, 12.5, 15];

const inZoneTarget = (t) => Math.abs(t.x) <= ZONE.halfW - 1 && Math.abs(t.y) <= ZONE.halfH - 1;

// Expected outcome of one pitch landing where `s` says (a full formula
// scope with the location filled in).
function outcomeAt(F, s, balls, strikes, kOnly) {
    const hbp = F.eval('hbpChance', s);
    const swing = F.eval('swingChance', s);
    const call = F.eval('strikeCall', s);
    const contact = F.eval('contactChance', s);
    const foul = F.eval('foulChance', s);
    const hit = F.eval('hitChance', s);
    const xb = F.eval('extraBaseChance', s);
    const hr = F.eval('homerShare', s);
    const triple = F.eval('tripleShare', s);
    const err = F.eval('errorChance', s);

    const live = 1 - hbp;
    const pBall = live * (1 - swing) * (1 - call);
    const pCalled = live * (1 - swing) * call;
    const pWhiff = live * swing * (1 - contact);
    const pFoul = live * swing * contact * foul;
    const pInPlay = live * swing * contact * (1 - foul);

    const vBall = balls >= 3 ? END_RV.BB : COUNT_RV[balls + 1][strikes];
    const vStrike = strikes >= 2 ? END_RV.K : COUNT_RV[balls][strikes + 1];
    const vFoul = strikes >= 2 ? COUNT_RV[balls][strikes] : COUNT_RV[balls][strikes + 1];
    const vHit = (1 - xb) * END_RV['1B'] + xb * (hr * END_RV.HR + (1 - hr) * (triple * END_RV['3B'] + (1 - triple) * END_RV['2B']));
    // Strikeouts-only rules: a ball caught for an out is a strike instead.
    const vNoHit = kOnly ? vStrike : err * END_RV.E + (1 - err) * END_RV.out;
    const rv = hbp * END_RV.HBP + pBall * vBall + (pCalled + pWhiff) * vStrike + pFoul * vFoul
        + pInPlay * (hit * vHit + (1 - hit) * vNoHit);
    return {
        rv, strike: pCalled + pWhiff + pFoul, whiff: pWhiff, swing: live * swing,
        ball: pBall + hbp, inPlay: pInPlay, hit: pInPlay * hit, xbh: pInPlay * hit * xb, hr: pInPlay * hit * xb * hr,
    };
}

// Every pitch in the arsenal at every spot: [{ pitchIdx, shape, spots:
// [{ target, aim, ...outcome }] }], spots sorted best (lowest rv) first.
export function evaluatePitches(game, efforts = { effort: 50, moveEffort: 50 }) {
    const st = game.state;
    const F = game.F;
    const pitcher = game.pitcher();
    const batter = game.batter();
    const side = battingSide(batter, pitcher);
    const seen = st.pa?.pitches ?? [];
    const last = seen[seen.length - 1];
    const kOnly = !!st.settings.kOnly;
    const base = COUNT_RV[st.balls][st.strikes];

    return pitcher.pitches.map((p, pitchIdx) => {
        // A second or so on the moving zone, as when you really throw it.
        const shape = game.previewPitch(pitchIdx, efforts, { t: 1.5 });
        const s0 = {
            ...shape.scope,
            pitchSeen: seen.filter((q) => q.type === shape.name).length,
            sameAsLast: last && last.type === shape.name ? 1 : 0,
            veloDiff: last ? shape.velocity - last.velocity : 0,
        };
        const sd = Math.hypot(shape.scatter, AIM_ERROR);
        const spots = [];
        for (const tx of TARGET_X) {
            for (const ty of TARGET_Y) {
                const acc = { rv: 0, strike: 0, whiff: 0, swing: 0, ball: 0, inPlay: 0, hit: 0, xbh: 0, hr: 0 };
                for (const [u, wu] of GH) {
                    for (const [v, wv] of GH) {
                        const loc = { x: tx + u * sd, y: ty + v * sd };
                        const s = { ...s0, ...locationScope(loc, batter, side) };
                        s.locDiff = last && last.x !== undefined ? Math.hypot(loc.x - last.x, loc.y - last.y) : 0;
                        const o = outcomeAt(F, s, st.balls, st.strikes, kOnly);
                        const w = wu * wv;
                        for (const k of Object.keys(acc)) acc[k] += w * o[k];
                    }
                }
                acc.rv -= base;
                spots.push({ target: { x: tx, y: ty }, aim: { x: tx - shape.dx, y: ty - shape.dy }, ...acc });
            }
        }
        spots.sort((a, b) => a.rv - b.rv);
        return { pitchIdx, type: p.type, shape, spots };
    });
}

// Words for a spot, from the batter's point of view ("down and away",
// "up and in, off the plate", "below the zone").
export function describeSpot(x, y, side) {
    const ins = side === 'R' ? -x : x;          // inches toward the batter
    const edgeX = ZONE.halfW + ZONE.ballR;
    const edgeY = ZONE.halfH + ZONE.ballR;
    const h = ins >= 4 ? 'in' : ins <= -4 ? 'away' : '';
    const v = y >= 6 ? 'up' : y <= -6 ? 'down' : '';
    let words;
    if (h && v) words = `${v} and ${h}`;
    else if (h) words = `${h} at the belt`;
    else if (v) words = v === 'up' ? 'up in the middle' : 'down in the middle';
    else words = 'right down the middle';
    if (y < -edgeY - 4) return `in the dirt${h ? `, ${h}` : ''}`;
    if (y > edgeY + 4) return `well up, above the zone${h ? `, ${h}` : ''}`;
    const offX = Math.abs(x) > edgeX;
    const offY = Math.abs(y) > edgeY;
    if (offX && offY) return `${words}, off the corner`;
    if (offX) return `${words}, just off the plate`;
    if (offY) return `${words}, just ${y > 0 ? 'above' : 'below'} the zone`;
    return words;
}

// Screen directions ("4 inches left and 6 up") for moving the aim.
function aimWords(dx, dy) {
    const parts = [];
    if (Math.abs(dx) >= 1) parts.push(`${Math.round(Math.abs(dx))}" ${dx > 0 ? 'right' : 'left'}`);
    if (Math.abs(dy) >= 1) parts.push(`${Math.round(Math.abs(dy))}" ${dy > 0 ? 'up' : 'down'}`);
    return parts.join(' and ');
}

const pct = (v) => `${Math.round(v * 100)}%`;
const avg3 = (v) => v.toFixed(3).replace(/^0/, '');
const kindWord = { fast: 'fastballs', break: 'breaking balls', off: 'off-speed stuff' };

// The batter's heat map cells in the zone itself, named for him.
function zoneCells(batter, side) {
    const cells = [];
    for (let r = 1; r <= 3; r++) {
        for (let col = 1; col <= 3; col++) {
            // Stored for a right-handed batter; mirror for a lefty.
            const src = side === 'L' ? HEAT.cols - 1 - col : col;
            const x = (col - 2) * HEAT.cellW;
            const y = (2 - r) * HEAT.cellH;
            cells.push({ x, y, heat: batter.heat[r * HEAT.cols + src] });
        }
    }
    return cells.sort((a, b) => b.heat - a.heat);
}

// Reasons a pitch at a spot works against the batter up now:
// reasonsFor(evaluation, spot) → [sentences].
function reasoner(game) {
    const st = game.state;
    const pitcher = game.pitcher();
    const batter = game.batter();
    const side = battingSide(batter, pitcher);
    const record = game.league.pitchStats?.[batter.id] ?? {};
    const leagueLine = leagueByType(game.league);
    const seen = st.pa?.pitches ?? [];
    const last = seen[seen.length - 1];
    // How the batter rates against a pitch: his rating for its kind plus his
    // skill against that particular pitch (vsPitch in the formulas).
    const vsPitch = (type) => game.batterScope(batter, pitcher, type).vsPitch;

    // Why a pitch at a spot works.
    const reasonsFor = (e, spot) => {
        const why = [];
        const shape = e.shape;
        const type = e.type;
        const towardHim = side === 'R' ? -shape.dx : shape.dx;
        const r = rates(record[type]);
        const lg = leagueLine[type];
        const vp = vsPitch(type);
        if (r.pa >= 8 && lg && Number.isFinite(r.ops) && r.ops < lg.ops - 0.08) {
            why.push(`He has a ${avg3(r.ops)} OPS against ${type.toLowerCase()}s (${r.pa} PA; the league is at ${avg3(lg.ops)}).`);
        } else if (vp <= 44) {
            why.push(`${type}s are a weak spot for him (rated ${Math.round(vp)} against them).`);
        }
        if (Number.isFinite(r.whiff) && r.whiff >= 0.3 && record[type]) {
            why.push(`He whiffs on ${pct(r.whiff)} of his swings at it.`);
        }
        const heat = locationScope(spot.target, batter, side).heat;
        if (heat <= -0.25) why.push('That’s one of his cold spots.');
        if (Math.abs(towardHim) >= 4 && Math.abs(shape.dx) >= Math.abs(shape.dy) * 0.6) {
            why.push(towardHim < 0
                ? `It breaks ${Math.round(-towardHim)}" away from him.`
                : `It runs ${Math.round(towardHim)}" in on his hands.`);
        } else if (shape.dy <= -8) {
            why.push(`It drops ${Math.round(-shape.dy)}", so it’s hard to lift.`);
        }
        if (last && Math.abs(shape.velocity - last.velocity) >= 7) {
            why.push(`It’s ${Math.round(Math.abs(shape.velocity - last.velocity))} mph ${shape.velocity < last.velocity ? 'slower' : 'faster'} than the last one, which messes with his timing.`);
        }
        const inZone = edgeDistance(spot.target.x, spot.target.y) >= 0;
        if (!inZone && spot.swing >= 0.25) why.push(`Aimed off the plate, he still swings at it about ${pct(spot.swing)} of the time.`);
        return why;
    };
    return reasonsFor;
}

// The catcher's advice for the batter up now.
// Returns { count, headline, options: [...], avoid, notes: [...] }.
export function catcherAdvice(game, efforts = { effort: 50, moveEffort: 50 }) {
    const st = game.state;
    const pitcher = game.pitcher();
    const batter = game.batter();
    const side = battingSide(batter, pitcher);
    const evals = evaluatePitches(game, efforts);
    const status = game.pitcherStatus();
    const league = game.league;
    const record = league.pitchStats?.[batter.id] ?? {};
    const leagueLine = leagueByType(league);
    const { balls, strikes } = st;
    const seen = st.pa?.pitches ?? [];
    const last = seen[seen.length - 1];

    const reasonsFor = reasoner(game);

    const option = (e, spot) => {
        const shape = e.shape;
        const breakWords = aimWords(-shape.dx, -shape.dy);
        return {
            pitchIdx: e.pitchIdx, type: e.type, color: shape.color, velocity: shape.velocity,
            target: spot.target, aim: spot.aim,
            where: describeSpot(spot.target.x, spot.target.y, side),
            aimNote: breakWords ? `Aim about ${breakWords} of the spot; it breaks back into it.` : 'Aim right at the spot; it barely moves.',
            rv: spot.rv, strike: spot.strike, whiff: spot.whiff, ball: spot.ball, inPlay: spot.inPlay, hit: spot.hit, hr: spot.hr,
            reasons: reasonsFor(e, spot),
        };
    };

    // Best spot for each pitch, best pitch first.
    const best = evals.map((e) => ({ e, spot: e.spots[0] })).sort((a, b) => a.spot.rv - b.spot.rv);
    const options = best.slice(0, 2).map(({ e, spot }) => option(e, spot));

    // The mistake to avoid: the worst strike he could leave over the plate.
    let worst = null;
    for (const e of evals) {
        for (const spot of e.spots) {
            if (!inZoneTarget(spot.target)) continue;
            if (!worst || spot.rv > worst.spot.rv) worst = { e, spot };
        }
    }
    const avoid = worst && {
        pitchIdx: worst.e.pitchIdx, type: worst.e.type, color: worst.e.shape.color,
        target: worst.spot.target,
        where: describeSpot(worst.spot.target.x, worst.spot.target.y, side),
        hit: worst.spot.hit, hr: worst.spot.hr, xbh: worst.spot.xbh,
    };

    // The count.
    const count = `${balls}-${strikes}`;
    let headline;
    if (balls === 3 && strikes < 2) headline = 'We can’t give him ball four. Throw a strike, but not a cookie.';
    else if (balls === 3) headline = 'Full count. He’ll be swinging, so make it a tough strike.';
    else if (strikes === 2 && balls <= 1) headline = 'We’re ahead. Nothing too good here: make him chase.';
    else if (strikes === 2) headline = 'Two strikes. Put him away, but don’t hang one.';
    else if (balls === 0 && strikes === 0) headline = 'Let’s get ahead of him with strike one.';
    else if (balls > strikes) headline = 'We’re behind. He’s looking for something to drive, so get back in the count.';
    else headline = 'Even count. This pitch decides who’s in charge.';

    // Scouting notes.
    const notes = [];
    const cells = zoneCells(batter, side);
    if (cells[0].heat >= 0.25) notes.push(`He’s hot ${describeSpot(cells[0].x, cells[0].y, side)}.`);
    if (cells.at(-1).heat <= -0.25) notes.push(`He’s cold ${describeSpot(cells.at(-1).x, cells.at(-1).y, side)}.`);
    const kinds = ['fast', 'break', 'off'].map((k) => [k, k === 'fast' ? batter.vsFast : k === 'break' ? batter.vsBreak : batter.vsOff]);
    kinds.sort((a, b) => a[1] - b[1]);
    if (kinds[0][1] <= 44) notes.push(`He struggles with ${kindWord[kinds[0][0]]} (rated ${kinds[0][1]}).`);
    if (kinds[2][1] >= 62) notes.push(`He handles ${kindWord[kinds[2][0]]} well (rated ${kinds[2][1]}).`);
    if (batter.eye >= 62) notes.push('He’s patient. He won’t chase much, so we’ll have to throw strikes.');
    else if (batter.eye <= 40) notes.push('He’s a free swinger. He’ll chase off the plate, especially with two strikes.');
    if (batter.power >= 65) notes.push('Big power: a mistake over the middle leaves the park.');
    if (batter.contact >= 65) notes.push('He puts the bat on the ball. Strikeouts won’t come easy.');
    else if (batter.contact <= 40) notes.push('There’s swing-and-miss in his game.');
    const sameHand = side === pitcher.throws;
    notes.push(sameHand
        ? 'Same side as you: breaking balls run away from him.'
        : 'He’s on the other side: changeups and sinkers fade away from him; breaking balls come in.');
    const repeats = Object.entries(seen.reduce((m, p) => ({ ...m, [p.type]: (m[p.type] ?? 0) + 1 }), {}))
        .filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1]);
    if (repeats.length) notes.push(`He’s seen ${repeats[0][1]} ${repeats[0][0].toLowerCase()}s this at-bat; he’s timing it better each time.`);
    if (status.fatigue >= 0.6) {
        const sc = evals[0].shape.scatter;
        notes.push(`You’re tiring: your control has slipped to ±${sc.toFixed(1)}". Stay away from the middle.`);
    }

    return { count, side, headline, options, avoid, notes };
}

// The catcher calls the next pitch: a pitch type and a spot, from the same
// scores as the mound visit. He doesn't always call the single best one
// (hitters would sit on it): pitches within a few hundredths of a run of
// the best get a share of the calls, and so do the best few spots for the
// pitch he picks.
//   rng: from createRng (uses weighted). exclude: pitch indexes shaken off.
//   pitchIdx: call this pitch (you picked it), only choosing the spot.
// Returns { pitchIdx, type, color, target, aim, where, reason, rv } or null.
export function callPitch(game, efforts, rng, { exclude = [], pitchIdx = null } = {}) {
    const pitcher = game.pitcher();
    const side = battingSide(game.batter(), pitcher);
    let evals = evaluatePitches(game, efforts);
    if (pitchIdx !== null) evals = evals.filter((e) => e.pitchIdx === pitchIdx);
    else if (exclude.length < evals.length) evals = evals.filter((e) => !exclude.includes(e.pitchIdx));
    if (!evals.length) return null;

    const weighted = (items, rvOf, temp) => {
        const best = Math.min(...items.map(rvOf));
        return rng.weighted(items, (x) => Math.exp(-(rvOf(x) - best) / temp));
    };
    const e = weighted(evals, (x) => x.spots[0].rv, 0.012);
    const spot = weighted(e.spots.slice(0, 6), (s) => s.rv, 0.004);
    const reasons = reasoner(game)(e, spot);
    return {
        pitchIdx: e.pitchIdx, type: e.type, color: e.shape.color,
        target: spot.target, aim: spot.aim, rv: spot.rv,
        where: describeSpot(spot.target.x, spot.target.y, side),
        reason: reasons[0] ?? null,
    };
}
