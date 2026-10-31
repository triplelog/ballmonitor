// A season: a league at one level, a round-robin schedule, pitcher rest,
// season stats, standings and a four-team playoff. Plain JSON so it can be
// saved; the career mode will string seasons together.

import { createRng } from './rng.js';
import { generateLeague } from './league.js';
import { FORMATS, progress, table } from './competition.js';
import { LEVELS, levelGameOptions } from './levels.js';
import { Game } from './game.js';
import { NEUTRAL_SCOPE } from './formulas.js';

const BAT_FIELDS = ['pa', 'ab', 'r', 'h', 'd', 't', 'hr', 'rbi', 'bb', 'k', 'hbp', 'sf'];
const PITCH_FIELDS = ['bf', 'outs', 'h', 'r', 'er', 'bb', 'k', 'hr', 'hbp', 'pitches'];

// opts: level, seed, userTeamId, difficulty, league (already generated),
// formatOpts ({ state } for high school, { length } for pro).
export function createSeason(opts = {}) {
    const level = opts.level ?? 'pro';
    const L = LEVELS[level];
    const format = FORMATS[level];
    const seed = opts.seed ?? (Date.now() >>> 0);
    const formatOpts = { length: L.defaultLength, ...(opts.formatOpts ?? {}), seed };
    const league = opts.league ?? seasonLeague(level, seed, formatOpts);
    const season = {
        version: SEASON_VERSION, seed, level,
        year: opts.year ?? new Date().getFullYear(),
        league,
        formatOpts,
        title: '',
        userTeamId: opts.userTeamId ?? 0,
        difficulty: opts.difficulty ?? 2,
        gap: L.gap,                // days from one game to the next
        day: 0,
        stages: [],
        divisions: [],             // conferences / standings groups for display
        schedule: [],
        phase: 'running',          // running | done
        champion: null,
        stats: { bat: {}, pitch: {} },
        rest: {},                  // pitcher id -> first day he can pitch again
    };
    season.title = format.title(season);
    format.start(season, createRng(seed ^ 0x5eed));
    return season;
}

export const SEASON_VERSION = 2;

// The league for a season at this level.
export function seasonLeague(level, seed, formatOpts = {}) {
    return generateLeague(seed, { level, teams: FORMATS[level].teams({ ...formatOpts, seed }) });
}

export const levelOf = (season) => LEVELS[season.level];
export const gamesOn = (season, day) => season.schedule.filter((g) => g.day === day);
export const isUserGame = (season, g) => g.home === season.userTeamId || g.away === season.userTeamId;
export const isRested = (season, id, day = season.day) => (season.rest[id] ?? 0) <= day;
export const restLeft = (season, id, day = season.day) => Math.max(0, (season.rest[id] ?? 0) - day);

export function userGameToday(season) {
    return gamesOn(season, season.day).find((g) => isUserGame(season, g) && !g.result) ?? null;
}

// The next starter in the rotation who is rested; otherwise the most rested
// arm with the most stamina.
export function pickStarter(season, teamId, day = season.day) {
    const team = season.league.teams[teamId];
    const rot = team.rotation;
    for (let k = 0; k < rot.length; k++) {
        const id = rot[(team.nextStarter + k) % rot.length];
        if (isRested(season, id, day)) return id;
    }
    const players = season.league.players;
    const rested = team.pitchers.filter((id) => isRested(season, id, day));
    const pool = rested.length ? rested : team.pitchers.slice().sort((a, b) => (season.rest[a] ?? 0) - (season.rest[b] ?? 0)).slice(0, 3);
    return pool.sort((a, b) => players[b].stamina - players[a].stamina)[0];
}

// A Game for this schedule entry. user: { lineup, starterId } for the user's side.
export function makeGame(season, F, g, { userTeamId = null, user = {}, seed } = {}) {
    const lg = season.league;
    const opts = {
        ...levelGameOptions(season.level),
        homeId: g.home, awayId: g.away, userTeamId,
        difficulty: season.difficulty,
        seed: seed ?? ((season.seed * 31 + g.id * 7919) >>> 0),
    };
    for (const key of ['home', 'away']) {
        const teamId = g[key];
        const team = lg.teams[teamId];
        const mine = userTeamId === teamId;
        const starterId = (mine && user.starterId) || pickStarter(season, teamId, g.day);
        opts[key] = {
            lineup: (mine && user.lineup) || team.lineup,
            starterId,
            unavailable: team.pitchers.filter((id) => id !== starterId && !isRested(season, id, g.day)),
        };
    }
    return Game.create(lg, F, opts);
}

// Fold a finished game into the season: result, stats, decisions, rest.
export function recordGame(season, g, game, F) {
    const st = game.state;
    const L = levelOf(season);
    const winKey = st.winner;
    const loseKey = winKey === 'home' ? 'away' : 'home';
    const box = st.box;

    for (const [id, b] of Object.entries(box.bat)) {
        const s = (season.stats.bat[id] ??= { g: 0, ...Object.fromEntries(BAT_FIELDS.map((f) => [f, 0])) });
        s.g += 1;
        for (const f of BAT_FIELDS) s[f] += b[f];
    }
    for (const key of ['home', 'away']) {
        const side = st.sides[key];
        side.pitchersUsed.forEach((id, i) => {
            const b = box.pitch[id] ?? { pitches: 0 };
            const s = (season.stats.pitch[id] ??= { g: 0, gs: 0, w: 0, l: 0, ...Object.fromEntries(PITCH_FIELDS.map((f) => [f, 0])) });
            s.g += 1;
            if (i === 0) s.gs += 1;
            for (const f of PITCH_FIELDS) s[f] += b[f] ?? 0;
            const days = F.eval('restDays', { ...NEUTRAL_SCOPE, level: L.n, levelVelo: L.levelVelo, pitchCount: b.pitches ?? 0 });
            season.rest[id] = Math.max(season.rest[id] ?? 0, g.day + 1 + Math.round(days));
        });
        // The rotation moves on past whoever started.
        const team = season.league.teams[side.teamId];
        const idx = team.rotation.indexOf(side.pitchersUsed[0]);
        if (idx >= 0) team.nextStarter = (idx + 1) % team.rotation.length;
    }

    // Decisions, simplified: the win to the winning pitcher who got the
    // most outs, the loss to the losing pitcher who gave up the most runs.
    const pick = (key, score) => st.sides[key].pitchersUsed.slice().sort((a, b) => score(b) - score(a))[0];
    const wp = pick(winKey, (id) => box.pitch[id]?.outs ?? 0);
    const lp = pick(loseKey, (id) => (box.pitch[id]?.r ?? 0) * 100 + (box.pitch[id]?.outs ?? 0));
    season.stats.pitch[wp].w += 1;
    season.stats.pitch[lp].l += 1;

    g.result = {
        home: st.score.home, away: st.score.away, innings: st.inning,
        endedBy: st.endedBy ?? null, wp, lp,
        hits: { ...st.hits },
    };
    progress(season, g, FORMATS[season.level]);
    advance(season);
}

export function simGame(season, F, g) {
    const game = makeGame(season, F, g);
    game.simToEnd();
    recordGame(season, g, game, F);
    return game;
}

// Move on to the first day with a game still to play.
export function advance(season) {
    const next = season.schedule.reduce((d, g) => (g.result ? d : Math.min(d, g.day)), Infinity);
    if (Number.isFinite(next)) season.day = next;
    else if (season.phase !== 'done') season.phase = 'done';
}

// Sim every game today except the user's (if it isn't played yet).
export function simOthersToday(season, F) {
    for (const g of gamesOn(season, season.day)) {
        if (!g.result && !isUserGame(season, g)) {
            const game = makeGame(season, F, g);
            game.simToEnd();
            recordGame(season, g, game, F);
        }
    }
}

// Sim day by day. stop: 'userGame' (stop when the user's next game is up),
// a number of days, or 'end'. The user's own games are simmed too unless
// stopping at them. simStep does one game, for a UI that wants progress.
export function simStep(season, F, stop, startDay) {
    if (season.phase === 'done') return true;
    if (typeof stop === 'number' && season.day >= startDay + stop) return true;
    if (stop === 'userGame' && userGameToday(season)) {
        simOthersToday(season, F);
        return true;
    }
    const g = season.schedule.find((x) => x.day === season.day && !x.result);
    if (!g) {
        advance(season);
        if (!season.schedule.some((x) => !x.result)) return true;
    } else simGame(season, F, g);
    return season.phase === 'done';
}

export function simAhead(season, F, stop) {
    const startDay = season.day;
    for (let guard = 0; guard < 100000; guard++) if (simStep(season, F, stop, startDay)) return;
}

// The user's next unplayed game (null when their season is over).
export function nextUserGame(season) {
    return season.schedule.find((g) => !g.result && isUserGame(season, g)) ?? null;
}

// ---- tables ----
// Regular-season standings for a set of teams (default: everyone).
export function standings(season, teamIds = season.league.teams.map((t) => t.id), filter = (g) => g.stage === 'regular') {
    return table(season, teamIds, filter);
}

// A team's record in every game this season.
export function teamRecord(season, teamId) {
    return table(season, [teamId])[0];
}

export function gamesPlayed(season) {
    const n = {};
    for (const g of season.schedule) {
        if (!g.result) continue;
        n[g.home] = (n[g.home] ?? 0) + 1;
        n[g.away] = (n[g.away] ?? 0) + 1;
    }
    return n;
}

export function teamOf(season, playerId) {
    return season.league.teams.find((t) => t.batters.includes(Number(playerId)) || t.pitchers.includes(Number(playerId)));
}

// Rate stats for a player's season line.
export function battingRates(s) {
    const tb = s.h + s.d + 2 * s.t + 3 * s.hr;
    const avg = s.ab ? s.h / s.ab : 0;
    const obp = s.ab + s.bb + s.hbp + s.sf ? (s.h + s.bb + s.hbp) / (s.ab + s.bb + s.hbp + s.sf) : 0;
    const slg = s.ab ? tb / s.ab : 0;
    return { avg, obp, slg, ops: obp + slg };
}

export function pitchingRates(s, innings) {
    const ip = s.outs / 3;
    return {
        ip,
        era: ip ? (s.er * innings) / ip : 0,
        whip: ip ? (s.h + s.bb) / ip : 0,
        k9: ip ? (s.k * innings) / ip : 0,
    };
}

// League leaders for one stat. Rate stats need enough playing time.
export const LEADER_STATS = {
    avg: { label: 'Batting average', kind: 'bat', rate: true, fmt: (v) => v.toFixed(3).replace(/^0/, ''), dir: -1 },
    hr: { label: 'Home runs', kind: 'bat', fmt: String, dir: -1 },
    rbi: { label: 'RBI', kind: 'bat', fmt: String, dir: -1 },
    ops: { label: 'OPS', kind: 'bat', rate: true, fmt: (v) => v.toFixed(3).replace(/^0/, ''), dir: -1 },
    era: { label: 'ERA', kind: 'pitch', rate: true, fmt: (v) => v.toFixed(2), dir: 1 },
    k: { label: 'Strikeouts', kind: 'pitch', fmt: String, dir: -1 },
    w: { label: 'Wins', kind: 'pitch', fmt: String, dir: -1 },
    whip: { label: 'WHIP', kind: 'pitch', rate: true, fmt: (v) => v.toFixed(2), dir: 1 },
};

export function leaders(season, stat, count = 5) {
    const def = LEADER_STATS[stat];
    const innings = levelOf(season).innings;
    const played = gamesPlayed(season);
    const teamOfPlayer = {};
    for (const t of season.league.teams) for (const id of [...t.batters, ...t.pitchers]) teamOfPlayer[id] = t.id;
    const rows = [];
    for (const [id, s] of Object.entries(season.stats[def.kind])) {
        // Rate stats need enough playing time for the player's team's games.
        const teamGames = Math.max(1, played[teamOfPlayer[id]] ?? 1);
        let v;
        if (def.kind === 'bat') {
            if (def.rate && s.pa < teamGames * 2.5) continue;
            v = def.rate ? battingRates(s)[stat] : s[stat];
        } else {
            // Qualifying: about 0.8 innings per team game.
            if (def.rate && s.outs < teamGames * 3 * 0.8) continue;
            v = def.rate ? pitchingRates(s, innings)[stat] : s[stat];
        }
        rows.push({ id: Number(id), v });
    }
    rows.sort((a, b) => (a.v - b.v) * def.dir);
    return rows.slice(0, count);
}

// A game's place in the season ("Regular season", "US Pool C", "Semifinals · Game 2").
export const gameLabel = (g) => g.label ?? (g.stage === 'regular' ? 'Regular season' : '');
export const isPostseason = (g) => g.stage !== 'regular';
