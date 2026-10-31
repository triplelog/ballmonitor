// Career mode: one pitcher from the Youth World Tournament to the pros.
//
// The career keeps the pitcher's ratings on the pro scale ("absolute");
// each season he's put on his team at that level with the level's
// ratingShift added (a 40 is a good 12-year-old: 72 for youth). You control
// only him: the season sims until his turn in the rotation, and you choose
// which of his starts to pitch yourself. Plain JSON, saved by the app.

import { createRng } from './rng.js';
import { PITCH_TYPES, TEAMS } from './data.js';
import { LEVELS } from './levels.js';
import { STATES, COLLEGE_CONFERENCES } from './regions.js';
import { NEUTRAL_SCOPE } from './formulas.js';
import { FORMATS } from './competition.js';
import {
    createSeason, seasonLeague, makeGame, recordGame, advance, pickStarter, isUserGame, teamRecord, leaders,
} from './season.js';
import { teamName } from './league.js';

export const CAREER_VERSION = 1;
export const PID = 990001;          // the career pitcher's player id in every league

const clamp = (v, lo = 20, hi = 99) => Math.max(lo, Math.min(hi, Math.round(v)));

// Starting points on the pro scale for a 12-year-old.
export const STYLES = {
    power: { name: 'Power', desc: 'Throws hard; control comes later.', velo: 32, control: 22, move: 25, stamina: 58, pitches: ['Four-Seam', 'Changeup'] },
    finesse: { name: 'Finesse', desc: 'Paints the corners; velocity comes later.', velo: 24, control: 32, move: 25, stamina: 62, pitches: ['Four-Seam', 'Changeup'] },
    movement: { name: 'Movement', desc: 'Nothing straight: sink and bend.', velo: 25, control: 24, move: 32, stamina: 60, pitches: ['Two-Seam', 'Curveball'] },
};

// The youngest age at which a pitch can be learned.
export const PITCH_AGES = {
    'Four-Seam': 10, 'Changeup': 10, 'Eephus': 12, 'Two-Seam': 13, 'Curveball': 14, 'Slider': 15,
    'Cutter': 16, 'Sinker': 16, 'Knuckleball': 16, 'Splitter': 17, 'Palmball': 17, 'Sweeper': 18,
    'Screwball': 18, 'Gyroball': 19,
};

export const PLAY_MODES = {
    all: 'Every start',
    half: 'Every other start (and the postseason)',
    key: 'Key starts: opener, every 4th, and the postseason',
    none: 'Sim everything (just manage his development)',
};

// Which youth tournament team a hometown plays for.
const SPLITS = {
    CA: { 'Southern California': ['Los Angeles', 'San Diego', 'Long Beach', 'Anaheim', 'Riverside', 'Irvine', 'Santa Ana', 'Chula Vista'], 'Central California': ['Fresno', 'Bakersfield', 'Stockton'], default: 'Northern California' },
    TX: { 'South Texas': ['Houston', 'San Antonio', 'Austin', 'Corpus Christi', 'Laredo'], 'West Texas': ['El Paso', 'Lubbock', 'Amarillo'], default: 'North Texas' },
    FL: { 'North Florida': ['Jacksonville', 'Tallahassee', 'Gainesville', 'Orlando'], default: 'South Florida' },
    IL: { 'Northern Illinois': ['Chicago', 'Aurora', 'Joliet', 'Naperville', 'Rockford', 'Elgin', 'Waukegan', 'Cicero', 'Arlington Heights', 'Evanston', 'Schaumburg'], default: 'Southern Illinois' },
    NY: { 'Metro New York': ['Brooklyn', 'Queens', 'Manhattan', 'The Bronx', 'Staten Island', 'Yonkers', 'New Rochelle', 'Mount Vernon', 'White Plains', 'Hempstead'], default: 'Upstate New York' },
    NC: { 'Western North Carolina': ['Charlotte', 'Winston-Salem', 'High Point', 'Concord', 'Asheville', 'Gastonia', 'Greensboro'], default: 'Eastern North Carolina' },
    OH: { 'Southern Ohio': ['Columbus', 'Cincinnati', 'Dayton', 'Hamilton', 'Springfield', 'Kettering'], default: 'Northern Ohio' },
    PA: { 'Western Pennsylvania': ['Pittsburgh', 'Erie', 'Altoona', 'State College'], default: 'Eastern Pennsylvania' },
};

export function youthRegion(state, city) {
    const split = SPLITS[state];
    if (!split) return STATES[state][0];
    for (const [region, cities] of Object.entries(split)) if (region !== 'default' && cities.includes(city)) return region;
    return split.default;
}

// opts: first, last, throws, style, state, city, seed, play, difficulty
export function createCareer(opts) {
    const style = STYLES[opts.style] ?? STYLES.power;
    const seed = opts.seed ?? (Date.now() >>> 0);
    const rng = createRng(seed);
    const jitter = () => rng.int(-2, 2);
    const core = { velo: style.velo + jitter(), control: style.control + jitter(), move: style.move + jitter() };
    return {
        version: CAREER_VERSION,
        id: opts.id ?? `c${seed.toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`,
        createdAt: Date.now(),
        seed,
        first: opts.first, last: opts.last, throws: opts.throws === 'L' ? 'L' : 'R', style: opts.style ?? 'power',
        state: opts.state, city: opts.city,
        age: 12, year: opts.year ?? new Date().getFullYear(),
        stage: 'youth', levelYear: 1,
        team: null,                // team index at the current level
        pitcher: {
            ...core, stamina: style.stamina,
            pitches: style.pitches.map((type) => ({ type, velo: core.velo + jitter(), control: core.control + jitter(), move: core.move + jitter() })),
        },
        xp: 0,
        xpEarned: 0,
        settings: { play: opts.play ?? 'all', difficulty: opts.difficulty ?? 2, proGames: opts.proGames ?? 60 },
        history: [],
        log: [],                   // this season's outings
        starts: 0,                 // starts so far this season
        offers: null,
        season: null,
        retired: false,
    };
}

export const careerName = (c) => `${c.first} ${c.last}`;
export const levelOfStage = (stage) => ({ youth: 'youth', hs: 'hs', college: 'college', pro: 'pro' })[stage] ?? null;

// The pitcher as he appears at a level: ratings shifted onto that scale.
export function pitcherAt(career, level) {
    const shift = LEVELS[level].ratingShift;
    const p = career.pitcher;
    return {
        id: PID, type: 'pitcher', role: 'SP', first: career.first, last: career.last, throws: career.throws,
        velo: clamp(p.velo + shift), control: clamp(p.control + shift), move: clamp(p.move + shift),
        stamina: clamp(p.stamina, 15, 140),
        pitches: p.pitches.map((x) => ({ type: x.type, velo: clamp(x.velo + shift), control: clamp(x.control + shift), move: clamp(x.move + shift) })),
        career: true,
    };
}

// ---- seasons ----
const seasonSeed = (career) => (career.seed * 31 + career.year * 7919 + career.age) >>> 0;

// Build this year's season with the career pitcher on his team.
export function startCareerSeason(career, F) {
    const level = levelOfStage(career.stage);
    const seed = seasonSeed(career);
    const formatOpts = level === 'hs' ? { state: career.state } : level === 'pro' ? { length: career.settings.proGames } : {};
    const league = seasonLeague(level, seed, formatOpts);
    let teamId = career.team;
    if (level === 'youth') teamId = league.teams.findIndex((t) => t.city === youthRegion(career.state, career.city));
    if (level === 'hs') teamId = league.teams.findIndex((t) => t.city === `${career.city} High`);
    if (teamId < 0 || teamId == null) teamId = 0;
    career.team = teamId;
    // He takes the place of the team's first starter.
    const team = league.teams[teamId];
    const out = team.rotation[0];
    team.pitchers = team.pitchers.map((id) => (id === out ? PID : id));
    team.rotation = team.rotation.map((id) => (id === out ? PID : id));
    delete league.players[out];
    league.players[PID] = pitcherAt(career, level);
    team.nextStarter = 0;
    const season = createSeason({ level, seed, league, userTeamId: teamId, difficulty: career.settings.difficulty, formatOpts, year: career.year });
    season.careerId = career.id;
    career.season = season;
    career.log = [];
    career.starts = 0;
    void F;
    return season;
}

export const isPostseason = (g) => g.stage !== 'regular' && g.stage !== 'pools';

// Whether to hand this start to the player, by his chosen play mode.
export function shouldPlay(career, g) {
    const n = career.starts;
    switch (career.settings.play) {
        case 'all': return true;
        case 'half': return isPostseason(g) || n % 2 === 0;
        case 'key': return isPostseason(g) || n === 0 || n % 4 === 0;
        default: return false;
    }
}

// The next game of his team's, and whether he starts it.
export function upcoming(career) {
    const s = career.season;
    const g = s.schedule.filter((x) => !x.result && isUserGame(s, x)).sort((a, b) => a.day - b.day)[0] ?? null;
    if (!g) return null;
    return { g, starter: pickStarter(s, s.userTeamId, g.day) };
}

// One step of simming. until: 'start' (stop at his next start), 'playable'
// (stop at the next start he'll pitch himself), 'end' (sim the season).
// Returns { done, start (game to pitch), seasonOver }.
export function careerStep(career, F, until) {
    const s = career.season;
    if (s.phase === 'done' || !s.schedule.some((x) => !x.result)) return { done: true, seasonOver: true };
    const today = s.schedule.filter((x) => x.day === s.day && !x.result);
    if (!today.length) { advance(s); return { done: false }; }
    const others = today.find((x) => !isUserGame(s, x));
    if (others) { simTracked(career, F, others); return { done: false }; }
    const g = today[0];
    if (pickStarter(s, s.userTeamId, g.day) === PID && career.lastStart !== g.id) {
        if (until === 'start' || (until === 'playable' && shouldPlay(career, g))) return { done: true, start: g };
        markStart(career, g);
    }
    simTracked(career, F, g);
    return { done: false };
}

export function markStart(career, g) {
    if (career.lastStart === g.id) return;
    career.lastStart = g.id;
    career.starts += 1;
}

// A game for him to pitch: his side managed by the user (for the pitching).
export function careerGame(career, F, g) {
    markStart(career, g);
    return makeGame(career.season, F, g, { userTeamId: career.season.userTeamId, user: { starterId: PID }, seed: Date.now() >>> 0 });
}

function simTracked(career, F, g) {
    const game = makeGame(career.season, F, g);
    game.simToEnd();
    recordCareerGame(career, F, g, game);
}

// Fold a finished game into the season, and his outing into the career.
export function recordCareerGame(career, F, g, game) {
    recordGame(career.season, g, game, F);
    const me = career.season.userTeamId;
    const key = g.home === me ? 'home' : 'away';
    const box = game.state.box.pitch[PID];
    if (!box || !game.state.sides[key].pitchersUsed.includes(PID)) return null;
    const level = LEVELS[career.season.level];
    const outing = {
        gameId: g.id, day: g.day, label: g.label ?? 'Regular season',
        opp: g.home === me ? g.away : g.home, home: g.home === me,
        started: game.state.sides[key].pitchersUsed[0] === PID,
        outs: box.outs, h: box.h, r: box.r, er: box.er, bb: box.bb, hbp: box.hbp, k: box.k, pitches: box.pitches,
        win: g.result.wp === PID, loss: g.result.lp === PID,
        score: { us: g.home === me ? g.result.home : g.result.away, them: g.home === me ? g.result.away : g.result.home },
    };
    outing.xp = Math.round(F.eval('xpForOuting', {
        ...NEUTRAL_SCOPE, level: level.n, ip: box.outs / 3, strikeouts: box.k, runsAllowed: box.r,
        walksAllowed: box.bb + box.hbp, hitsAllowed: box.h, win: outing.win ? 1 : 0, postseason: isPostseason(g) ? 1 : 0, age: career.age,
    }));
    career.xp += outing.xp;
    career.xpEarned += outing.xp;
    career.log.push(outing);
    return outing;
}

// ---- training ----
// what: { field: 'velo' | 'control' | 'move' | 'stamina', pitch?: index }
export function trainCost(career, F, what) {
    const current = what.pitch != null ? career.pitcher.pitches[what.pitch][what.field] : career.pitcher[what.field];
    return Math.round(F.eval('trainingCost', { ...NEUTRAL_SCOPE, current: what.field === 'stamina' ? current * 0.6 + 20 : current, age: career.age }));
}

export function train(career, F, what) {
    const cost = trainCost(career, F, what);
    if (career.xp < cost) return { ok: false, cost };
    career.xp -= cost;
    const target = what.pitch != null ? career.pitcher.pitches[what.pitch] : career.pitcher;
    target[what.field] = Math.min(what.field === 'stamina' ? 130 : 99, target[what.field] + 1);
    // A pitcher's overall ratings follow his pitches.
    if (what.pitch != null) syncCore(career);
    refreshInSeason(career);
    return { ok: true, cost };
}

export function pitchCost(career, F) {
    return Math.round(F.eval('pitchCost', { ...NEUTRAL_SCOPE, age: career.age }));
}

export function learnable(career) {
    const have = new Set(career.pitcher.pitches.map((p) => p.type));
    return Object.keys(PITCH_TYPES).filter((t) => !have.has(t) && career.age >= (PITCH_AGES[t] ?? 99));
}

export function learnPitch(career, F, type) {
    const cost = pitchCost(career, F);
    if (career.xp < cost || !learnable(career).includes(type) || career.pitcher.pitches.length >= 6) return { ok: false, cost };
    career.xp -= cost;
    const p = career.pitcher;
    career.pitcher.pitches.push({ type, velo: p.velo - 6, control: p.control - 8, move: p.move - 6 });
    refreshInSeason(career);
    return { ok: true, cost };
}

function syncCore(career) {
    const ps = career.pitcher.pitches;
    const avg = (f) => Math.round(ps.reduce((a, p) => a + p[f], 0) / ps.length);
    for (const f of ['velo', 'control', 'move']) career.pitcher[f] = Math.max(career.pitcher[f], avg(f));
}

// Keep the in-season copy of him up to date after training.
function refreshInSeason(career) {
    const s = career.season;
    if (s && s.phase !== 'done') s.league.players[PID] = pitcherAt(career, s.level);
}

// ---- the end of a season ----
export function seasonLine(career) {
    const s = career.season;
    const st = s.stats.pitch[PID] ?? { g: 0, gs: 0, w: 0, l: 0, outs: 0, h: 0, r: 0, er: 0, bb: 0, k: 0, hr: 0, pitches: 0 };
    const innings = LEVELS[s.level].innings;
    const ip = st.outs / 3;
    return { ...st, ip, era: ip ? (st.er * innings) / ip : 0 };
}

// How the team's season ended, in words.
export function teamFinish(season) {
    const me = season.userTeamId;
    if (season.champion === me) return 'Champions';
    const lastStage = [...season.stages].reverse().find((st) =>
        (st.type === 'knockout' && st.matches.some((m) => m.a === me || m.b === me)) ||
        (st.type === 'pool' && st.groups.some((g) => g.teams.includes(me))));
    if (!lastStage) return 'Missed the postseason';
    if (lastStage.type === 'pool') return `Out in ${lastStage.groups.find((g) => g.teams.includes(me)).name}`;
    const m = [...lastStage.matches].reverse().find((x) => x.a === me || x.b === me);
    if (m.winner === me) return `Won the ${lastStage.roundNames[m.round]}`;
    return `Lost in the ${lastStage.roundNames[m.round]}`;
}

// Close the season: record it, grow a year, and work out what's next.
// Returns the history entry.
export function finishSeason(career, F) {
    const s = career.season;
    const line = seasonLine(career);
    const level = s.level;
    const rec = teamRecord(s, s.userTeamId);
    const awards = [];
    for (const [stat, label] of [['k', 'strikeouts'], ['era', 'ERA'], ['w', 'wins']]) {
        if (leaders(s, stat, 1)[0]?.id === PID) awards.push(`Led the ${level === 'youth' ? 'tournament' : 'league'} in ${label}`);
    }
    if (s.champion === s.userTeamId) awards.push(level === 'youth' ? 'World champion' : level === 'hs' ? 'State champion' : level === 'college' ? 'College World Series champion' : 'League champion');
    // A bonus for the season as a whole.
    const bonus = Math.round(10 + line.gs * 2 + (s.champion === s.userTeamId ? 25 : 0) + awards.length * 10);
    career.xp += bonus;
    career.xpEarned += bonus;
    const entry = {
        year: career.year, age: career.age, level, levelYear: career.levelYear,
        team: teamName(s.league.teams[s.userTeamId]), teamRecord: `${rec.w}-${rec.l}`, finish: teamFinish(s),
        line: { g: line.g, gs: line.gs, w: line.w, l: line.l, ip: Math.round(line.ip * 10) / 10, outs: line.outs, h: line.h, er: line.er, bb: line.bb, k: line.k, era: line.era, pitches: line.pitches },
        awards, xp: career.log.reduce((a, o) => a + o.xp, 0) + bonus,
        ratings: { velo: career.pitcher.velo, control: career.pitcher.control, move: career.pitcher.move, stamina: career.pitcher.stamina },
    };
    career.history.push(entry);

    // Grow: a youth season is followed by two years before high school.
    const years = level === 'youth' ? 2 : 1;
    for (let i = 0; i < years; i++) {
        const g = F.eval('growth', { ...NEUTRAL_SCOPE, age: career.age + 1 });
        grow(career, g);
        career.age += 1;
        career.year += 1;
    }
    career.season = null;
    career.log = [];

    // What's next.
    if (level === 'youth') { career.stage = 'hs'; career.levelYear = 1; career.team = null; }
    else if (level === 'hs' && career.levelYear < 4) career.levelYear += 1;
    else if (level === 'hs') { career.stage = 'decision'; career.offers = collegeOffers(career); }
    else if (level === 'college' && career.levelYear < 3) career.levelYear += 1;
    else if (level === 'college' && career.levelYear === 3) { career.stage = 'collegeDecision'; career.offers = { draft: draftProjection(career) }; }
    else if (level === 'college') { career.stage = 'draft'; career.offers = { draft: draftProjection(career) }; }
    else if (level === 'pro') {
        career.levelYear += 1;
        career.stage = career.age >= 40 ? 'retired' : 'freeAgency';
        if (career.stage === 'retired') career.retired = true;
        else career.offers = proOffers(career);
    }
    return entry;
}

function grow(career, points) {
    const p = career.pitcher;
    const add = (o, f, v) => { o[f] = Math.max(20, Math.min(99, Math.round((o[f] + v) * 10) / 10)); };
    for (const f of ['velo', 'control', 'move']) add(p, f, points);
    for (const x of p.pitches) for (const f of ['velo', 'control', 'move']) add(x, f, points);
    p.stamina = Math.max(30, Math.min(120, Math.round(p.stamina + points * 1.8)));
    for (const f of ['velo', 'control', 'move']) p[f] = Math.round(p[f]);
    for (const x of p.pitches) for (const f of ['velo', 'control', 'move']) x[f] = Math.round(x[f]);
}

// ---- offers and the draft ----
// A scout's number: how good he is now, with a nod to his record.
export function prospectScore(career) {
    const p = career.pitcher;
    const best = [...p.pitches].sort((a, b) => (b.velo + b.move + b.control) - (a.velo + a.move + a.control)).slice(0, 3);
    const stuff = best.reduce((a, x) => a + (x.velo + x.move + x.control) / 3, 0) / best.length;
    const recent = career.history.slice(-2);
    const perf = recent.reduce((a, h) => a + (h.line.k - h.line.bb) / Math.max(1, h.line.ip) * 3 - h.line.era * 0.5, 0) / Math.max(1, recent.length);
    return Math.round(stuff + Math.max(-5, Math.min(8, perf)) + (p.stamina - 80) / 10);
}

export function draftProjection(career) {
    const score = prospectScore(career);
    const round = Math.max(1, Math.min(40, Math.round(1 + (68 - score) * 1.5)));
    return { score, round };
}

// Four schools, with his home region keener.
export function collegeOffers(career) {
    const rng = createRng(seasonSeed(career) ^ 0xc011);
    const score = prospectScore(career);
    const homeRegion = { WA: 0, OR: 0, CA: 0, HI: 0, AK: 0, AZ: 1, UT: 1, CO: 1, NV: 1, NM: 1, ID: 1, MT: 1, WY: 1, KS: 2, NE: 2, OK: 2, IA: 2, MO: 2, ND: 2, SD: 2, MI: 3, OH: 3, IN: 3, IL: 3, WI: 3, MN: 3, FL: 4, GA: 4, SC: 4, AL: 4, TN: 4, KY: 4, MS: 4, TX: 5, LA: 5, AR: 5, NC: 6, VA: 6, WV: 6, MD: 6, DE: 6, PA: 6, NY: 7, NJ: 7, CT: 7, MA: 7, RI: 7, VT: 7, NH: 7, ME: 7 }[career.state];
    // Schools close to home are keener; bigger programs are choosier.
    const schools = FORMATS.college.teams().map((t, i) => ({
        team: i, name: `${t.city} ${t.name}`, conference: COLLEGE_CONFERENCES[t.group].name, group: t.group, prestige: 40 + ((i * 37) % 23),
    }));
    const ranked = schools.map((x) => ({ ...x, interest: score - x.prestige * 0.3 + (x.group === homeRegion ? 8 : 0) + rng.range(-6, 6) }));
    ranked.sort((a, b) => b.interest - a.interest);
    return { colleges: ranked.slice(0, 4).map(({ team, name, conference }) => ({ team, name, conference })), draft: draftProjection(career) };
}

// Two other teams, plus staying put.
export function proOffers(career) {
    const rng = createRng(seasonSeed(career) ^ 0xfa);
    const others = rng.shuffle(TEAMS.map((t, i) => i).filter((i) => i !== career.team)).slice(0, 2);
    return { stay: career.team, teams: others };
}

// choice: { college: teamIdx } | { draft: true } | { stay: true } | { team: idx } | { retire: true } | { returnToSchool: true }
export function choose(career, choice) {
    if (choice.retire) { career.stage = 'retired'; career.retired = true; return; }
    if (career.stage === 'decision') {
        if (choice.college != null) { career.stage = 'college'; career.levelYear = 1; career.team = choice.college; }
        else { draftTo(career); }
    } else if (career.stage === 'collegeDecision') {
        if (choice.returnToSchool) { career.stage = 'college'; career.levelYear = 4; }
        else draftTo(career);
    } else if (career.stage === 'draft') {
        draftTo(career);
    } else if (career.stage === 'freeAgency') {
        career.stage = 'pro';
        if (choice.team != null) career.team = choice.team;
    }
    career.offers = null;
}

function draftTo(career) {
    const rng = createRng(seasonSeed(career) ^ 0xd4a);
    const proj = career.offers?.draft ?? draftProjection(career);
    career.draftedIn = { round: proj.round, year: career.year };
    career.stage = 'pro';
    career.levelYear = 1;
    career.team = rng.int(0, TEAMS.length - 1);
}

// Totals across the career, by level and overall.
export function careerTotals(career) {
    const sum = (list) => list.reduce((a, h) => {
        for (const k of ['g', 'gs', 'w', 'l', 'outs', 'h', 'er', 'bb', 'k']) a[k] = (a[k] ?? 0) + (h.line[k] ?? 0);
        return a;
    }, {});
    return { all: sum(career.history), pro: sum(career.history.filter((h) => h.level === 'pro')) };
}

// A Hall of Fame score for the pro years: 100 is a lock.
export function hallOfFame(career) {
    const t = careerTotals(career).pro;
    const titles = career.history.filter((h) => h.level === 'pro' && h.awards.some((a) => a.includes('champion'))).length;
    const leads = career.history.filter((h) => h.level === 'pro').reduce((a, h) => a + h.awards.filter((x) => x.startsWith('Led')).length, 0);
    return Math.round((t.w ?? 0) * 0.35 + (t.k ?? 0) / 40 + titles * 8 + leads * 6);
}
