// League, team and player generation. A league is plain JSON so it can be
// saved to localStorage as-is.

import { createRng } from './rng.js';
import {
    FIRST_NAMES, LAST_NAMES, FIELD_POSITIONS, PITCH_TYPES, ARSENAL_WEIGHTS, HEAT,
} from './data.js';
import { LEVELS, teamIdentity } from './levels.js';
import { NAME_POOLS } from './regions.js';

const clampRating = (v) => Math.max(20, Math.min(99, Math.round(v)));

// opts.level: 'youth' | 'hs' | 'college' | 'pro' (default). Ratings are
// relative to the level; see levels.js. opts.teams: the teams to make, as
// [{ city, name, abbr, color, namePool, group }] (default: the level's own).
export function generateLeague(seed = Date.now(), opts = {}) {
    const L = LEVELS[opts.level ?? 'pro'];
    const identities = opts.teams ?? null;
    const teamCount = identities ? identities.length : opts.teamCount ?? L.teamCount;
    const rng = createRng(seed);
    const league = { seed, level: L.id, players: {}, teams: [], nextId: 1 };
    const usedNames = new Set();
    const usedAbbr = new Set();

    for (let i = 0; i < teamCount; i++) {
        const base = identities ? { ...identities[i] } : teamIdentity(L.id, i);
        if (usedAbbr.has(base.abbr)) base.abbr = (base.name.slice(0, 2) + base.city[0]).toUpperCase();
        usedAbbr.add(base.abbr);
        const team = {
            id: i, city: base.city, name: base.name, abbr: base.abbr, color: base.color,
            batters: [], pitchers: [], lineup: [], rotation: [], nextStarter: 0,
            ...(base.group !== undefined ? { group: base.group } : {}),
        };
        const pool = NAME_POOLS[base.namePool] ?? null;
        // A team's overall strength varies a little (more at lower levels).
        const swing = Math.round(L.spread / 2);
        const offense = 50 + rng.int(-swing, swing);
        const pitching = 58 + rng.int(-swing, swing);

        // Nine starters at their positions, then the bench.
        for (const pos of [...FIELD_POSITIONS, ...L.bench]) {
            const isStarter = team.batters.length < 9;
            const b = makeBatter(rng, league, usedNames, pos, offense + (isStarter ? 0 : -6), L.spread, pool);
            team.batters.push(b.id);
        }
        const staff = L.starters + L.relievers;
        for (let p = 0; p < staff; p++) {
            const role = p < L.starters ? 'SP' : 'RP';
            const closerBonus = role === 'RP' && p >= staff - 2 ? 5 : 0;
            const pitcher = makePitcher(rng, league, usedNames, role, pitching + closerBonus, L, pool);
            team.pitchers.push(pitcher.id);
        }
        team.lineup = defaultLineup(league, team);
        team.rotation = team.pitchers.filter((id) => league.players[id].role === 'SP');
        league.teams.push(team);
    }
    return league;
}

function newPerson(rng, league, usedNames, pool = null) {
    const firsts = pool?.first ?? FIRST_NAMES;
    const lasts = pool?.last ?? LAST_NAMES;
    let first, last;
    let tries = 0;
    do {
        first = rng.pick(firsts);
        last = rng.pick(lasts);
    } while (usedNames.has(first + last) && ++tries < 50);
    usedNames.add(first + last);
    return { id: league.nextId++, first, last };
}

function makeBatter(rng, league, usedNames, pos, level, spread = 9, pool = null) {
    const p = newPerson(rng, league, usedNames, pool);
    // Position shapes the profile: catchers and middle infielders hit less,
    // corners and DH hit for power, centre fielders run.
    const shape = {
        C: { contact: -3, power: 0, speed: -10, eye: 0 },
        '1B': { contact: 0, power: 8, speed: -8, eye: 2 },
        '2B': { contact: 3, power: -5, speed: 4, eye: 0 },
        '3B': { contact: 0, power: 5, speed: -2, eye: 0 },
        SS: { contact: 2, power: -4, speed: 6, eye: -2 },
        LF: { contact: 0, power: 5, speed: 0, eye: 0 },
        CF: { contact: 2, power: -2, speed: 10, eye: 0 },
        RF: { contact: -1, power: 6, speed: 0, eye: 0 },
        DH: { contact: 0, power: 10, speed: -8, eye: 3 },
        IF: { contact: 0, power: -4, speed: 2, eye: 0 },
        OF: { contact: 0, power: 0, speed: 4, eye: 0 },
        UT: { contact: 0, power: -2, speed: 3, eye: 0 },
    }[pos];
    const rating = (adj) => clampRating(level + adj + rng.gauss() * spread);
    const contact = rating(shape.contact);
    const bats = pos === 'C' || pos === 'SS' || pos === '2B' || pos === '3B'
        ? (rng.chance(0.15) ? 'S' : 'R')
        : rng.weighted(['R', 'L', 'S'], (h) => ({ R: 0.5, L: 0.38, S: 0.12 })[h]);
    const batter = {
        ...p, type: 'batter', pos, bats,
        contact,
        power: rating(shape.power),
        eye: rating(shape.eye),
        speed: rating(shape.speed),
        vsFast: clampRating(contact + rng.gauss() * 8),
        vsBreak: clampRating(contact + rng.gauss() * 10 - 3),
        vsOff: clampRating(contact + rng.gauss() * 10 - 2),
        heat: makeHeatMap(rng),
        typeSkill: makeTypeSkill(rng),
    };
    league.players[batter.id] = batter;
    return batter;
}

// Rating points better (or worse) against particular pitches, on top of the
// fastball / breaking / off-speed ratings: one batter sits on sliders,
// another can't touch a changeup.
// Stored as an array in PITCH_ORDER (older saves: an object by type).
export const PITCH_ORDER = Object.keys(PITCH_TYPES);
export function makeTypeSkill(rng) {
    return PITCH_ORDER.map(() => Math.round(rng.gauss() * 7));
}

// A batter's extra skill against one pitch type.
export function skillVs(batter, type) {
    const ts = batter.typeSkill;
    if (!ts) return 0;
    return (Array.isArray(ts) ? ts[PITCH_ORDER.indexOf(type)] : ts[type]) ?? 0;
}

// [type, skill] pairs, best first.
export function typeSkills(batter) {
    return PITCH_ORDER.map((t) => [t, skillVs(batter, t)]).sort((a, b) => b[1] - a[1]);
}

// Leagues made before typeSkill existed get one, the same every time.
export function ensureTypeSkills(league) {
    for (const p of Object.values(league.players)) {
        if (p.type === 'batter' && !p.typeSkill) p.typeSkill = makeTypeSkill(createRng(p.id * 7919 + league.seed));
    }
}

// A heat map: a hot spot and a cold spot, smoothly blended, values −1…1.
export function makeHeatMap(rng) {
    const { cols, rows } = HEAT;
    const hot = { c: rng.range(0.5, 3.5), r: rng.range(0.5, 3.5), s: rng.range(0.6, 1) };
    let cold;
    do {
        cold = { c: rng.range(0, 4), r: rng.range(0, 4), s: rng.range(0.5, 1) };
    } while (Math.hypot(cold.c - hot.c, cold.r - hot.r) < 1.8);
    const cells = [];
    for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
            const dh = Math.hypot(c - hot.c, r - hot.r);
            const dc = Math.hypot(c - cold.c, r - cold.r);
            // Pitches well off the plate are harder to hit for everyone.
            const ring = r === 0 || c === 0 || r === rows - 1 || c === cols - 1 ? -0.2 : 0;
            const v = hot.s * Math.exp(-dh * dh / 2) - cold.s * Math.exp(-dc * dc / 2) + ring + rng.gauss() * 0.08;
            cells.push(Math.round(Math.max(-1, Math.min(1, v)) * 100) / 100);
        }
    }
    return cells;
}

function makePitcher(rng, league, usedNames, role, level, L = LEVELS.pro, pool = null) {
    const p = newPerson(rng, league, usedNames, pool);
    const throws = rng.chance(0.3) ? 'L' : 'R';
    const sd = L.spread;
    const velo = clampRating(level + rng.gauss() * sd + (role === 'RP' ? 4 : 0));
    const control = clampRating(level + rng.gauss() * sd - (role === 'RP' ? 3 : 0));
    const move = clampRating(level + rng.gauss() * sd);
    const [stamMean, stamSd] = L.stamina[role];
    const stamina = Math.max(15, Math.round(stamMean + rng.gauss() * stamSd));
    const A = L.arsenal ?? {
        primary: ARSENAL_WEIGHTS.primary, secondary: ARSENAL_WEIGHTS.secondary, sp: [2, 3], rp: [1, 2], secondFastball: 0.35,
    };

    // One or two fastballs, then secondary pitches: starters carry more.
    const pitches = [];
    const take = (pool) => {
        const options = Object.keys(pool).filter((t) => !pitches.some((x) => x.type === t));
        const type = rng.weighted(options, (t) => pool[t]);
        const kind = PITCH_TYPES[type].kind;
        pitches.push({
            type,
            velo: clampRating(velo + rng.gauss() * 6),
            control: clampRating(control + rng.gauss() * 7 - (kind === 'fast' ? -3 : 2)),
            move: clampRating(move + rng.gauss() * 8),
        });
    };
    take(A.primary);
    if (Object.keys(A.primary).length > 1 && rng.chance(A.secondFastball)) take(A.primary);
    const [lo, hi] = role === 'SP' ? A.sp : A.rp;
    const secondaries = rng.int(lo, hi);
    for (let i = 0; i < secondaries; i++) take(A.secondary);

    const pitcher = { ...p, type: 'pitcher', role, throws, velo, control, move, stamina, pitches };
    league.players[pitcher.id] = pitcher;
    return pitcher;
}

// Best nine by a simple batting value, ordered the traditional way:
// on-base types first, power in the middle.
export function defaultLineup(league, team) {
    const starters = team.batters.slice(0, 9).map((id) => league.players[id]);
    const value = (b) => b.contact + b.eye * 0.6 + b.power * 0.8;
    const byValue = starters.slice().sort((a, b) => value(b) - value(a));
    const leadoff = starters.slice().sort((a, b) => (b.speed + b.eye + b.contact) - (a.speed + a.eye + a.contact))[0];
    const rest = byValue.filter((b) => b !== leadoff);
    // Slots 2–5 get the best hitters, then the rest in order.
    const order = [leadoff, rest[1], rest[0], rest[2], rest[3], ...rest.slice(4)];
    return order.map((b) => ({ id: b.id, pos: b.pos }));
}

export const playerName = (p) => `${p.first} ${p.last}`;
export const shortName = (p) => `${p.first[0]}. ${p.last}`;
export const teamName = (t) => [t.city, t.name].filter(Boolean).join(' ');
