// Computer decisions: which pitch to throw, where, and when to go to the
// bullpen. The computer knows how its pitches break and aims to compensate;
// its extra scatter (the aiScatter formula) stands in for the moving zone.

import { ZONE, PITCH_TYPES } from './data.js';

export function aiChoosePitch(game, rng) {
    const st = game.state;
    const pitcher = game.pitcher();
    const { balls, strikes } = st;

    // Fastballs when behind in the count, breaking and off-speed when ahead.
    const idxs = pitcher.pitches.map((_, i) => i);
    const pitchIdx = rng.weighted(idxs, (i) => {
        const p = pitcher.pitches[i];
        const kind = PITCH_TYPES[p.type].kind;
        const quality = (p.velo + p.move + p.control) / 180;
        const base = kind === 'fast' ? 1.6 + 0.35 * (balls - strikes) : kind === 'break' ? 1 + 0.3 * strikes : 0.9 + 0.2 * strikes;
        return Math.max(0.1, base) * quality * (i === 0 ? 1.2 : 1);
    });

    const effort = 50 + (strikes === 2 ? 15 : 0) + (st.bases[1] || st.bases[2] ? 10 : 0);
    const moveEffort = 50 + (strikes === 2 ? 10 : 0);
    const efforts = { effort, moveEffort };
    const shape = game.previewPitch(pitchIdx, efforts);

    const zoneRate = game.F.eval('aiZoneRate', shape.scope);
    const w = ZONE.halfW + ZONE.ballR;
    const h = ZONE.halfH + ZONE.ballR;
    let target;
    if (rng.chance(zoneRate)) {
        target = { x: rng.range(-0.8, 0.8) * ZONE.halfW, y: rng.range(-0.8, 0.8) * ZONE.halfH };
    } else {
        // Just off the plate: breaking and off-speed pitches mostly low.
        const miss = rng.range(0.5, 5);
        const where = shape.kind === 'fast'
            ? rng.pick(['high', 'low', 'left', 'right'])
            : rng.weighted(['high', 'low', 'left', 'right'], (d) => (d === 'low' ? 3 : d === 'high' ? 0.5 : 1));
        target = {
            high: { x: rng.range(-1, 1) * ZONE.halfW, y: h + miss },
            low: { x: rng.range(-1, 1) * ZONE.halfW, y: -h - miss },
            left: { x: -w - miss, y: rng.range(-1, 1) * ZONE.halfH },
            right: { x: w + miss, y: rng.range(-1, 1) * ZONE.halfH },
        }[where];
    }

    return {
        pitchIdx, ...efforts,
        aim: { x: target.x - shape.dx, y: target.y - shape.dy },
        extraScatter: game.F.eval('aiScatter', shape.scope),
    };
}

// The freshest, best reliever left; starters only if no relievers remain.
export function aiPickReliever(game, key) {
    const pen = game.bullpen(key).map((id) => game.player(id));
    if (!pen.length) return null;
    // Relievers first; a starter only when no reliever is left.
    const value = (p) => p.velo + p.control + p.move + (p.role === 'RP' ? 1000 : 0);
    pen.sort((a, b) => value(b) - value(a));
    return pen[0].id;
}
