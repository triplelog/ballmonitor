// How each level's season is organised, as a chain of stages:
//   league:   a fixed schedule (regular season), standings by group
//   pool:     round robin inside groups; the top of each group goes on
//   knockout: a seeded bracket, single games or best-of series
// A format builds its teams, starts its first stage, and decides what
// comes next when a stage finishes. The season (season.js) runs the games.

import { createRng } from './rng.js';
import { TEAMS } from './data.js';
import { YOUTH_US, YOUTH_INTL, STATES, HS_MASCOTS, COLLEGE_CONFERENCES, paletteColor, abbreviate } from './regions.js';

const POOL_LETTERS = 'ABCDEFGHIJKLMNOP';

// ---- the four formats ----
export const FORMATS = {
    youth: {
        title: () => 'Youth World Tournament',
        describe: '128 teams: 64 from the US and 64 from around the world. Pools of four play a round robin; the 16 US pool winners and 16 international pool winners play down to a US champion and an international champion, who meet for the World Championship.',
        teams: () => [
            ...YOUTH_US.map(([city, abbr, pool], i) => ({ city, name: '', abbr, namePool: pool, color: paletteColor(i), group: 'US' })),
            ...YOUTH_INTL.map(([city, abbr, pool], i) => ({ city, name: '', abbr, namePool: pool, color: paletteColor(i + 5), group: 'International' })),
        ],
        start(season, rng) {
            const us = rng.shuffle(teamsIn(season, 'US'));
            // Keep teams from the same country (Japan East and West, Canada's
            // regions…) in different pools.
            const country = (id) => {
                const c = season.league.teams[id].city;
                if (['Canada West', 'Ontario', 'Quebec', 'Atlantic Canada', 'Canadian Prairies'].includes(c)) return 'Canada';
                return c.replace(/ (East|West|North|South)$/, '');
            };
            let intl;
            for (let tries = 0; tries < 500; tries++) {
                intl = rng.shuffle(teamsIn(season, 'International'));
                let ok = true;
                for (let i = 0; i < 16 && ok; i++) ok = new Set(intl.slice(i * 4, i * 4 + 4).map(country)).size === 4;
                if (ok) break;
            }
            const groups = [];
            for (let i = 0; i < 16; i++) groups.push({ name: `US Pool ${POOL_LETTERS[i]}`, teams: us.slice(i * 4, i * 4 + 4) });
            for (let i = 0; i < 16; i++) groups.push({ name: `International Pool ${POOL_LETTERS[i]}`, teams: intl.slice(i * 4, i * 4 + 4) });
            startPool(season, { id: 'pools', name: 'Pool play', groups, advance: 1, day: 0 });
        },
        next(season, stage) {
            if (stage.id === 'pools') {
                const day = nextStageDay(season);
                for (const [id, side, label] of [['us', 'US', 'US'], ['intl', 'International', 'International']]) {
                    const winners = stage.groups.filter((g) => g.name.startsWith(side)).map((g) => groupTable(season, stage, g)[0].teamId);
                    startKnockout(season, {
                        id, name: `${label} bracket`, seeds: seedBy(season, winners, (g) => g.stage === 'pools'), day,
                        roundNames: [`${label} Round of 16`, `${label} Quarterfinals`, `${label} Semifinals`, `${label} Championship`],
                    });
                }
            } else if (stage.id === 'us' || stage.id === 'intl') {
                const us = stageById(season, 'us');
                const intl = stageById(season, 'intl');
                if (us.status === 'done' && intl.status === 'done') {
                    startKnockout(season, { id: 'world', name: 'World Championship', seeds: [us.winner, intl.winner], day: nextStageDay(season), roundNames: ['World Championship'], final: true });
                }
            }
        },
    },

    hs: {
        title: (season) => `${STATES[season.formatOpts.state]?.[0] ?? ''} High School`,
        describe: 'The 16 biggest cities in your state each send a school. Everyone plays everyone twice, home and away (30 games), then the top eight play a single-elimination state tournament.',
        teams: ({ state = 'TX', seed = 1 } = {}) => {
            const cities = STATES[state][1].split(', ');
            const rng = createRng(seed ^ 0x45);
            const mascots = rng.shuffle(HS_MASCOTS);
            const used = new Set();
            return cities.map((city, i) => ({ city: `${city} High`, name: mascots[i], abbr: abbreviate(city, used), color: paletteColor(i), group: state }));
        },
        start(season, rng) {
            const ids = season.league.teams.map((t) => t.id);
            const games = [];
            const rounds = roundRobin(rng.shuffle(ids));
            const all = [...rounds, ...rounds.map((r) => r.map(([a, b]) => [b, a]))];
            all.forEach((pairs, r) => pairs.forEach(([home, away]) => games.push({ day: r * season.gap, home, away })));
            season.divisions = [{ name: season.title, teams: ids }];
            startLeague(season, { id: 'regular', name: 'Regular season', games });
        },
        next(season, stage) {
            if (stage.id === 'regular') {
                const seeds = table(season, season.league.teams.map((t) => t.id), (g) => g.stage === 'regular').slice(0, 8).map((r) => r.teamId);
                startKnockout(season, { id: 'state', name: 'State tournament', seeds, day: nextStageDay(season), roundNames: ['Quarterfinals', 'Semifinals', 'State Championship'], final: true });
            }
        },
    },

    college: {
        title: () => 'College Baseball',
        describe: 'Eight regional conferences of eight. A 50-game season: 29 non-conference games, then a three-game series against each conference rival. Conference champions and the 24 best other records make 8 four-team regionals; the regional winners go to the College World Series (two pools of four, then a best-of-three final).',
        teams: () => COLLEGE_CONFERENCES.flatMap((conf, c) => conf.teams.map(([city, abbr, name], i) => ({ city, name, abbr, color: paletteColor(c * 2 + (i % 2)), group: c }))),
        start(season, rng) {
            const confs = COLLEGE_CONFERENCES.map((c, i) => ({ name: c.name, abbr: c.abbr, teams: teamsIn(season, i) }));
            season.divisions = confs.map((c) => ({ name: `${c.name} Conference`, teams: c.teams, conference: true }));
            const games = [];
            const all = season.league.teams.map((t) => t.id);
            const confOf = Object.fromEntries(season.league.teams.map((t) => [t.id, t.group]));
            // Non-conference: 29 days of cross-conference pairings.
            let day = 0;
            for (let d = 0; d < 29; d++, day++) {
                let pairs;
                for (let tries = 0; tries < 200; tries++) {
                    const order = rng.shuffle(all);
                    pairs = [];
                    for (let i = 0; i < order.length; i += 2) pairs.push([order[i], order[i + 1]]);
                    if (pairs.every(([a, b]) => confOf[a] !== confOf[b])) break;
                }
                for (const [a, b] of pairs) games.push(rng.chance(0.5) ? { day, home: a, away: b } : { day, home: b, away: a });
            }
            // Conference: a three-game series against each rival.
            const confRounds = confs.map((c) => roundRobin(rng.shuffle(c.teams)));
            for (let r = 0; r < 7; r++) {
                for (const rounds of confRounds) {
                    for (const [a, b] of rounds[r]) {
                        for (let k = 0; k < 3; k++) games.push({ day: day + k, home: r % 2 ? b : a, away: r % 2 ? a : b, conf: true });
                    }
                }
                day += 3;
            }
            startLeague(season, { id: 'regular', name: 'Regular season', games });
        },
        next(season, stage) {
            if (stage.id === 'regular') {
                const regular = (g) => g.stage === 'regular';
                const champs = season.divisions.map((d) => table(season, d.teams, (g) => regular(g) && g.conf)[0].teamId);
                const atLarge = table(season, season.league.teams.map((t) => t.id).filter((id) => !champs.includes(id)), regular).slice(0, 24).map((r) => r.teamId);
                const seeds = seedBy(season, [...champs, ...atLarge], regular);
                season.autoBids = champs;
                const groups = [];
                for (let i = 0; i < 8; i++) {
                    const teams = [seeds[i], seeds[15 - i], seeds[16 + i], seeds[31 - i]];
                    groups.push({ name: `${season.league.teams[seeds[i]].city} Regional`, teams });
                }
                startPool(season, { id: 'regionals', name: 'Regionals', groups, advance: 1, day: nextStageDay(season) });
            } else if (stage.id === 'regionals') {
                const winners = seedBy(season, stage.groups.map((g) => groupTable(season, stage, g)[0].teamId), (g) => g.stage === 'regular');
                startPool(season, {
                    id: 'cws', name: 'College World Series', advance: 1, day: nextStageDay(season),
                    groups: [
                        { name: 'CWS Bracket 1', teams: [winners[0], winners[3], winners[4], winners[7]] },
                        { name: 'CWS Bracket 2', teams: [winners[1], winners[2], winners[5], winners[6]] },
                    ],
                });
            } else if (stage.id === 'cws') {
                const finalists = seedBy(season, stage.groups.map((g) => groupTable(season, stage, g)[0].teamId), (g) => g.stage === 'regular');
                startKnockout(season, { id: 'cwsFinals', name: 'College World Series Finals', seeds: finalists, day: nextStageDay(season), bestOf: [3], roundNames: ['College World Series Finals'], final: true });
            }
        },
    },

    pro: {
        title: () => 'Pro League',
        describe: 'Twelve teams play a balanced schedule; the top four make the playoffs: best-of-five semifinals and a best-of-seven Championship Series.',
        teams: () => TEAMS.map((t) => ({ ...t })),
        start(season, rng) {
            const ids = season.league.teams.map((t) => t.id);
            const rounds = roundRobin(ids);
            const games = [];
            let order = [];
            const n = rounds.length;
            for (let k = 0; k < season.formatOpts.length; k++) {
                const cycle = Math.floor(k / n);
                if (k % n === 0) order = rng.shuffle([...rounds.keys()]);
                const r = order[k % n];
                rounds[r].forEach(([a, b], i) => {
                    const flip = (i + r + cycle) % 2 === 1;
                    games.push({ day: k * season.gap, home: flip ? b : a, away: flip ? a : b });
                });
            }
            season.divisions = [{ name: 'Standings', teams: ids }];
            startLeague(season, { id: 'regular', name: 'Regular season', games });
        },
        next(season, stage) {
            if (stage.id === 'regular') {
                const seeds = table(season, season.league.teams.map((t) => t.id), (g) => g.stage === 'regular').slice(0, 4).map((r) => r.teamId);
                startKnockout(season, { id: 'playoffs', name: 'Playoffs', seeds, day: nextStageDay(season), bestOf: [5, 7], roundNames: ['Semifinals', 'Championship Series'], final: true });
            }
        },
    },
};

// ---- stages ----
export const stageById = (season, id) => season.stages.find((s) => s.id === id);
const teamsIn = (season, group) => season.league.teams.filter((t) => t.group === group).map((t) => t.id);

function addGame(season, g) {
    season.schedule.push({ id: season.schedule.length, result: null, ...g });
}

// A day off after everything scheduled so far.
function nextStageDay(season) {
    const last = Math.max(-1, ...season.schedule.map((g) => g.day));
    return last + season.gap + 1;
}

function startLeague(season, { id, name, games }) {
    season.stages.push({ id, name, type: 'league', status: 'active' });
    for (const g of games) addGame(season, { ...g, stage: id });
}

function startPool(season, { id, name, groups, advance = 1, day }) {
    season.stages.push({ id, name, type: 'pool', status: 'active', groups, advance });
    groups.forEach((group, gi) => {
        roundRobin(group.teams).forEach((pairs, r) => {
            for (const [a, b] of pairs) addGame(season, { day: day + r * season.gap, home: a, away: b, stage: id, group: gi, label: group.name });
        });
    });
}

// seeds: teams best first; bestOf: per round (default single games).
function startKnockout(season, { id, name, seeds, day, bestOf = [], roundNames, final = false }) {
    const stage = { id, name, type: 'knockout', status: 'active', seeds, bestOf, roundNames, final, round: 0, matches: [] };
    season.stages.push(stage);
    const order = bracketOrder(seeds.length).map((s) => seeds[s - 1]);
    const pairs = [];
    for (let i = 0; i < order.length; i += 2) pairs.push([order[i], order[i + 1]]);
    startRound(season, stage, pairs, day);
}

function startRound(season, stage, pairs, day) {
    const best = stage.bestOf[stage.round] ?? 1;
    for (const [a, b] of pairs) {
        // The better seed is "a" (home in the odd games of a series).
        const [hi, lo] = stage.seeds.indexOf(a) <= stage.seeds.indexOf(b) ? [a, b] : [b, a];
        const match = { id: stage.matches.length, round: stage.round, a: hi, b: lo, wins: [0, 0], bestOf: best, winner: null };
        stage.matches.push(match);
        scheduleMatchGame(season, stage, match, day);
    }
}

function scheduleMatchGame(season, stage, match, day) {
    const k = match.wins[0] + match.wins[1] + 1;
    const home = k % 2 === 1 ? match.a : match.b;
    const roundName = stage.roundNames[match.round] ?? stage.name;
    addGame(season, {
        day, home, away: home === match.a ? match.b : match.a, stage: stage.id, match: match.id,
        label: match.bestOf > 1 ? `${roundName} · Game ${k}` : roundName,
    });
}

// After each game: series, rounds and stages move on.
export function progress(season, g, format) {
    const stage = stageById(season, g.stage);
    if (!stage || stage.status !== 'active') return;
    if (stage.type === 'knockout') {
        const m = stage.matches[g.match];
        const winner = g.result.home > g.result.away ? g.home : g.away;
        m.wins[winner === m.a ? 0 : 1] += 1;
        const need = Math.floor(m.bestOf / 2) + 1;
        if (m.wins[0] >= need || m.wins[1] >= need) m.winner = winner;
        else scheduleMatchGame(season, stage, m, g.day + season.gap);
        const round = stage.matches.filter((x) => x.round === stage.round);
        if (round.every((x) => x.winner !== null)) {
            if (round.length === 1) {
                stage.status = 'done';
                stage.winner = round[0].winner;
            } else {
                const winners = round.map((x) => x.winner);
                const pairs = [];
                for (let i = 0; i < winners.length; i += 2) pairs.push([winners[i], winners[i + 1]]);
                const lastDay = Math.max(...season.schedule.filter((x) => x.stage === stage.id).map((x) => x.day));
                stage.round += 1;
                startRound(season, stage, pairs, lastDay + season.gap);
            }
        }
    } else if (season.schedule.every((x) => x.stage !== stage.id || x.result)) {
        stage.status = 'done';
    }
    if (stage.status === 'done') {
        if (stage.final) {
            season.champion = stage.winner;
            season.phase = 'done';
        } else {
            format.next(season, stage);
        }
    }
}

// ---- tables and seeding ----
// Standings for some teams over the games that pass `filter`.
export function table(season, teamIds, filter = () => true) {
    const rows = new Map(teamIds.map((id) => [id, { teamId: id, w: 0, l: 0, rs: 0, ra: 0, results: [] }]));
    for (const g of season.schedule) {
        if (!g.result || !filter(g)) continue;
        const h = rows.get(g.home);
        const a = rows.get(g.away);
        const hw = g.result.home > g.result.away;
        if (h) { h.rs += g.result.home; h.ra += g.result.away; if (hw) h.w++; else h.l++; h.results.push(hw ? 'W' : 'L'); }
        if (a) { a.rs += g.result.away; a.ra += g.result.home; if (hw) a.l++; else a.w++; a.results.push(hw ? 'L' : 'W'); }
    }
    const list = [...rows.values()];
    for (const r of list) {
        const gp = r.w + r.l;
        r.pct = gp ? r.w / gp : 0;
        const last = r.results.at(-1);
        let k = 0;
        for (let i = r.results.length - 1; i >= 0 && r.results[i] === last; i--) k++;
        r.streak = last ? `${last}${k}` : '';
    }
    // Ties: run difference, then fewer runs allowed, then the team id
    // (a stand-in for a coin flip that stays the same on every screen).
    list.sort((a, b) => b.pct - a.pct || (b.rs - b.ra) - (a.rs - a.ra) || a.ra - b.ra || a.teamId - b.teamId);
    const top = list[0];
    for (const r of list) r.gb = top ? ((top.w - r.w) + (r.l - top.l)) / 2 : 0;
    return list;
}

export const groupTable = (season, stage, group) =>
    table(season, group.teams, (g) => g.stage === stage.id && g.group === stage.groups.indexOf(group));

// Order teams best first by their record in the games that pass `filter`.
export const seedBy = (season, teamIds, filter) => table(season, teamIds, filter).map((r) => r.teamId);

// Round robin by the circle method: rounds of [home, away] pairs (a bye
// for an odd team out).
export function roundRobin(teams) {
    const list = teams.length % 2 ? [...teams, null] : [...teams];
    const n = list.length;
    const rounds = [];
    let arr = list;
    for (let r = 0; r < n - 1; r++) {
        const pairs = [];
        for (let i = 0; i < n / 2; i++) {
            const [a, b] = [arr[i], arr[n - 1 - i]];
            if (a !== null && b !== null) pairs.push((i + r) % 2 ? [b, a] : [a, b]);
        }
        rounds.push(pairs);
        arr = [arr[0], arr[n - 1], ...arr.slice(1, n - 1)];
    }
    return rounds;
}

// Bracket positions so the top seeds meet last: 1v16, 8v9, 5v12, 4v13 …
function bracketOrder(n) {
    let order = [1];
    while (order.length < n) {
        const size = order.length * 2;
        order = order.flatMap((s) => [s, size + 1 - s]);
    }
    return order;
}

