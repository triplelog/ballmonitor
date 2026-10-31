// Pitch shape and location: what a pitch will do before it is thrown, and
// what the location means once it arrives.

import { ZONE, HEAT, PITCH_TYPES } from './data.js';

// Which side a batter hits from against this pitcher.
export function battingSide(batter, pitcher) {
    if (batter.bats === 'S') return pitcher.throws === 'R' ? 'L' : 'R';
    return batter.bats;
}

// Batter rating against this pitch's kind.
export function vsPitchRating(batter, kind) {
    return kind === 'fast' ? batter.vsFast : kind === 'break' ? batter.vsBreak : batter.vsOff;
}

// Velocity, break and scatter for a pitch with the given effort, before any
// location is chosen. `scope` holds the pitcher/situation variables.
export function shapePitch(F, pitcher, pitchIdx, efforts, scope) {
    const p = pitcher.pitches[pitchIdx];
    const type = PITCH_TYPES[p.type];
    const s = {
        ...scope,
        baseVelo: type.velo,
        velo: p.velo, move: p.move, control: p.control,
        effort: efforts.effort, moveEffort: efforts.moveEffort,
        wobble: type.wobble,
        isFast: type.kind === 'fast' ? 1 : 0,
        isBreak: type.kind === 'break' ? 1 : 0,
        isOff: type.kind === 'off' ? 1 : 0,
    };
    s.velocity = F.eval('velocity', s);
    const mult = F.eval('movementMult', s);
    // A right-hander's arm side is the third-base side (-x), where a
    // right-handed batter stands: his slider breaks right, away from a
    // righty; his changeup and sinker fade left, in on a righty.
    const hand = pitcher.throws === 'L' ? 1 : -1;
    s.run = type.run * mult;
    s.drop = type.drop * mult;
    s.movement = Math.hypot(type.run, type.drop) * mult;
    const scatter = F.eval('scatter', s);
    return {
        name: p.type, abbr: type.abbr, kind: type.kind, color: type.color,
        velocity: s.velocity,
        // Break as a screen offset in inches: +x right, +y up.
        dx: s.run * hand,
        dy: -s.drop,
        wobble: type.wobble,
        scatter,
        scope: s,
    };
}

// Where a pitch aimed at `aim` (zone-relative inches) ends up.
export function landPitch(shape, aim, rng, extraScatter = 0) {
    const sd = Math.hypot(shape.scatter, extraScatter);
    return {
        x: aim.x + shape.dx + rng.gauss() * sd,
        y: aim.y + shape.dy + rng.gauss() * sd,
    };
}

// Signed distance (inches) from the ball to the strike zone edge, counting
// the ball's radius: positive inside, negative outside.
export function edgeDistance(x, y) {
    const w = ZONE.halfW + ZONE.ballR;
    const h = ZONE.halfH + ZONE.ballR;
    const dx = Math.abs(x) - w;
    const dy = Math.abs(y) - h;
    if (dx <= 0 && dy <= 0) return -Math.max(dx, dy);
    return -Math.hypot(Math.max(dx, 0), Math.max(dy, 0));
}

export function heatAt(heat, x, y) {
    const c = Math.floor((x + HEAT.cellW * HEAT.cols / 2) / HEAT.cellW);
    // Row 0 is the top of the grid.
    const r = Math.floor((HEAT.cellH * HEAT.rows / 2 - y) / HEAT.cellH);
    const cc = Math.max(0, Math.min(HEAT.cols - 1, c));
    const rr = Math.max(0, Math.min(HEAT.rows - 1, r));
    return heat[rr * HEAT.cols + cc];
}

// Location variables for the formulas. `side` is the batter's side ('R'
// stands on the screen-left of the plate from the pitcher's view).
export function locationScope(loc, batter, side) {
    const edge = edgeDistance(loc.x, loc.y);
    // Heat maps are stored for a right-handed batter; mirror for lefties.
    const hx = side === 'L' ? -loc.x : loc.x;
    return {
        x: loc.x, y: loc.y,
        px: loc.x / ZONE.halfW,
        py: loc.y / ZONE.halfH,
        edge,
        inZone: edge >= 0 ? 1 : 0,
        inside: side === 'R' ? -loc.x : loc.x,
        heat: heatAt(batter.heat, hx, loc.y),
    };
}
