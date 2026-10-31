// Challenges: set situations with a goal, from one at-bat to 27 strikeouts.
//
// You are always the home team, pitching the top of the inning against the
// league's best lineup. Challenges use the default formulas (plus any the
// challenge itself sets) so star ratings mean the same for everyone.

import { Game } from './game.js';
import { createFormulas } from './formulas.js';
import { outsOn, reachedBase } from './tracker.js';
import { teamName } from './league.js';

const isK = (r) => r.play === 'K' || r.play === 'KL';
const nonKOut = (r) => r.paEnded && outsOn(r.play) > 0 && !isK(r);
const lead = (g) => g.state.score.home - g.state.score.away;

// Fixed pitchers so every attempt is the same test.
const SPECIAL_PITCHERS = {
    ace: {
        id: -1, first: 'Max', last: 'Ventura', role: 'SP', throws: 'R', velo: 72, control: 68, move: 70, stamina: 115,
        pitches: [
            { type: 'Four-Seam', velo: 74, control: 72, move: 64 },
            { type: 'Slider', velo: 68, control: 64, move: 74 },
            { type: 'Changeup', velo: 66, control: 66, move: 68 },
            { type: 'Curveball', velo: 64, control: 60, move: 72 },
        ],
    },
    knuckle: {
        id: -2, first: 'Tim', last: 'Floater', role: 'SP', throws: 'R', velo: 40, control: 62, move: 85, stamina: 140,
        pitches: [{ type: 'Knuckleball', velo: 60, control: 62, move: 88 }],
    },
    junk: {
        id: -3, first: 'Lou', last: 'Lobb', role: 'SP', throws: 'L', velo: 35, control: 70, move: 70, stamina: 120,
        pitches: [
            { type: 'Eephus', velo: 60, control: 68, move: 75 },
            { type: 'Palmball', velo: 55, control: 70, move: 70 },
        ],
    },
};

const kStars = (k) => (k >= 3 ? 3 : k >= 2 ? 2 : 1);

export const CHALLENGES = [
    // ---- Quick: one inning or less ----
    {
        id: 'side', tier: 'Quick', icon: '🔱', name: 'Strike Out the Side',
        desc: 'Get all three outs of the inning by strikeout. Baserunners are fine; any other out ends the attempt.',
        stars: ['3 strikeouts', '…in 15 pitches or fewer', '…in 12 or fewer with nobody on'],
        check(t, r) {
            if (nonKOut(r)) return fail('An out on a ball in play.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.pitches <= 12 && t.inning.baserunners === 0 ? 3 : t.inning.pitches <= 15 ? 2 : 1),
        progress: (t) => `K ${t.inning.outsK}/3 · ${t.inning.pitches} pitches`,
    },
    {
        id: 'immaculate', tier: 'Quick', icon: '✨', name: 'Immaculate Inning',
        desc: 'Nine pitches, nine strikes, three strikeouts. One ball, one ball in play, or a two-strike foul ends it.',
        stars: ['Immaculate', '5+ swinging strikes', 'All nine swinging'],
        check(t, r) {
            if (['ball', 'clock', 'hbp'].includes(r.call)) return fail('That one was a ball.');
            if (r.call === 'inplay') return fail('They put it in play.');
            if (r.call === 'foul' && r.before.strikes === 2) return fail('Fouled off with two strikes.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.swinging >= 9 ? 3 : t.inning.swinging >= 5 ? 2 : 1),
        progress: (t) => `Strikes ${t.inning.strikes}/9 · K ${t.inning.outsK}/3`,
    },
    {
        id: 'onetwothree', tier: 'Quick', icon: '🧹', name: 'Three Up, Three Down',
        desc: 'Retire the side in order against the league’s best lineup. Nobody reaches.',
        stars: ['1-2-3 inning', '12 pitches or fewer', '9 pitches or fewer'],
        check(t, r) {
            if (r.paEnded && reachedBase(r.play)) return fail('A batter reached base.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.pitches <= 9 ? 3 : t.inning.pitches <= 12 ? 2 : 1),
        progress: (t) => `Outs ${t.inning.outs}/3 · ${t.inning.pitches} pitches`,
    },
    {
        id: 'heart', tier: 'Quick', icon: '💔', name: 'Heart of the Order',
        desc: 'The 3-4-5 hitters, due up to start the inning. Retire all three.',
        start: { batIdx: 2 },
        stars: ['Retire all three', 'Two strikeouts', 'Strike out all three'],
        check(t, r) {
            if (r.paEnded && reachedBase(r.play)) return fail('A batter reached base.');
            if (t.inning.bf >= 3 && t.inning.baserunners === 0) return win();
            return null;
        },
        rate: (t) => kStars(t.inning.k),
        progress: (t) => `Retired ${t.inning.bf}/3 · K ${t.inning.k}`,
    },
    {
        id: 'houdini', tier: 'Quick', icon: '🎩', name: 'Houdini',
        desc: 'Ninth inning, up by one, bases loaded and nobody out. Get out of it without a run scoring.',
        start: { inning: 9, lead: 1, bases: [true, true, true] },
        stars: ['Escape', 'Two strikeouts', 'Strike out the side'],
        check(t, r) {
            if (t.inning.runs > 0) return fail('A run scored.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => kStars(t.inning.k),
        progress: (t) => `Outs ${t.inning.outs}/3 · runs ${t.inning.runs}`,
    },
    {
        id: 'save', tier: 'Quick', icon: '🔒', name: 'Close It Out',
        desc: 'Top of the ninth, a two-run lead. Get three outs before they tie it.',
        start: { inning: 9, lead: 2 },
        stars: ['The save', 'No runs', '1-2-3'],
        check(t, r, g) {
            if (lead(g) <= 0) return fail('Blown save.');
            if (r.halfEnded || r.gameOver) return win();
            return null;
        },
        rate: (t) => (t.inning.baserunners === 0 ? 3 : t.inning.runs === 0 ? 2 : 1),
        progress: (t, g) => `Outs ${t.inning.outs}/3 · lead ${lead(g)}`,
    },
    {
        id: 'fullcount', tier: 'Quick', icon: '😬', name: 'Full Count, Bases Loaded',
        desc: 'Tie game, ninth inning, two outs, bases loaded, 3-2 count. One out wins it.',
        start: { inning: 9, outs: 2, balls: 3, strikes: 2, bases: [true, true, true] },
        stars: ['Get the out', 'Strike him out', 'On the very next pitch'],
        check(t, r) {
            if (r.paEnded) return outsOn(r.play) > 0 ? win() : fail('Ball four or a hit: the run scores.');
            return null;
        },
        rate: (t, r) => (isK(r) && t.pa.pitches === 1 ? 3 : isK(r) ? 2 : 1),
        progress: () => 'One out to go',
    },
    {
        id: 'fumes', tier: 'Quick', icon: '🥵', name: 'Running on Fumes',
        desc: 'Your ace is out of gas in the eighth, up by two. No help is coming. Get three outs before the lead is gone.',
        start: { inning: 8, lead: 2, fatigue: 0.95 },
        stars: ['Hold the lead', 'No runs', '1-2-3'],
        check(t, r, g) {
            if (lead(g) <= 0) return fail('The lead is gone.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.baserunners === 0 ? 3 : t.inning.runs === 0 ? 2 : 1),
        progress: (t, g) => `Outs ${t.inning.outs}/3 · lead ${lead(g)}`,
    },
    {
        id: 'knuckle', tier: 'Quick', icon: '🦋', name: 'Knuckleball Only',
        desc: 'Tim Floater throws one pitch and nobody (including him) knows where it’s going. Get three outs allowing at most one run.',
        pitcher: 'knuckle',
        stars: ['At most one run', 'No runs', 'No runs and two strikeouts'],
        check(t, r) {
            if (t.inning.runs > 1) return fail('Too many runs.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.runs === 0 && t.inning.k >= 2 ? 3 : t.inning.runs === 0 ? 2 : 1),
        progress: (t) => `Outs ${t.inning.outs}/3 · runs ${t.inning.runs}`,
    },
    {
        id: 'junk', tier: 'Quick', icon: '🐌', name: 'Slow and Low',
        desc: 'Lou Lobb has an eephus and a palmball. They will hit it; make them hit it on the ground. Three outs, at most one run.',
        pitcher: 'junk',
        stars: ['At most one run', 'No runs', 'Nobody reaches'],
        check(t, r) {
            if (t.inning.runs > 1) return fail('Too many runs.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.baserunners === 0 ? 3 : t.inning.runs === 0 ? 2 : 1),
        progress: (t) => `Outs ${t.inning.outs}/3 · runs ${t.inning.runs}`,
    },
    {
        id: 'clock', tier: 'Quick', icon: '⏱️', name: 'Pitch Clock Panic',
        desc: 'The pitch clock is 3.5 seconds. Get three outs without a run.',
        formulas: { pitchClock: '3.5' },
        stars: ['No runs', 'No clock violations', 'Two strikeouts, no violations'],
        check(t, r) {
            if (t.inning.runs > 0) return fail('A run scored.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.clock === 0 && t.inning.k >= 2 ? 3 : t.inning.clock === 0 ? 2 : 1),
        progress: (t) => `Outs ${t.inning.outs}/3 · violations ${t.inning.clock}`,
    },
    {
        id: 'chaos', tier: 'Quick', icon: '🌀', name: 'Chaos Zone',
        desc: 'Maximum difficulty: the zone races and swerves all over. Get three outs without a run.',
        difficulty: 5,
        formulas: { zoneChaos: '4 + 1.5*difficulty + 3*fatigue', zoneSpeed: '12 + 7*difficulty + 15*fatigue + 2*t' },
        stars: ['No runs', 'No walks', 'Two strikeouts'],
        check(t, r) {
            if (t.inning.runs > 0) return fail('A run scored.');
            if (r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.inning.k >= 2 ? 3 : t.inning.bb + t.inning.hbp === 0 ? 2 : 1),
        progress: (t) => `Outs ${t.inning.outs}/3 · K ${t.inning.k}`,
    },

    // ---- Medium: a few innings ----
    {
        id: 'gauntlet', tier: 'Medium', icon: '🛡️', name: 'The Gauntlet',
        desc: 'Face the whole lineup once: strike out at least 5 of the first 9 batters.',
        autoOffense: true,
        stars: ['5 strikeouts', '6 strikeouts', '7 or more'],
        check(t) {
            const left = 9 - t.game.bf;
            if (t.game.k + left < 5) return fail('Not enough batters left to reach five.');
            if (t.game.bf >= 9) return win();
            return null;
        },
        rate: (t) => (t.game.k >= 7 ? 3 : t.game.k >= 6 ? 2 : 1),
        progress: (t) => `Batters ${t.game.bf}/9 · K ${t.game.k}/5`,
    },
    {
        id: 'sprint', tier: 'Medium', icon: '🏃', name: 'Strikeout Sprint',
        desc: 'Three innings, nine outs: make at least six of them strikeouts.',
        autoOffense: true,
        stars: ['6 strikeouts', '7 or 8', 'All 9'],
        check(t, r) {
            if (t.game.nonKOuts > 3) return fail('Four outs were not strikeouts.');
            if (t.game.outs >= 9 && r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.game.outsK >= 9 ? 3 : t.game.outsK >= 7 ? 2 : 1),
        progress: (t) => `Outs ${t.game.outs}/9 · K ${t.game.outsK}`,
    },
    {
        id: 'perfect3', tier: 'Medium', icon: '💎', name: 'Perfect Three',
        desc: 'Nine up, nine down: three perfect innings.',
        autoOffense: true,
        stars: ['Perfect', '4+ strikeouts', '6+ strikeouts'],
        check(t, r) {
            if (r.paEnded && reachedBase(r.play)) return fail('A batter reached base.');
            if (t.game.outs >= 9 && r.halfEnded) return win();
            return null;
        },
        rate: (t) => (t.game.k >= 6 ? 3 : t.game.k >= 4 ? 2 : 1),
        progress: (t) => `Outs ${t.game.outs}/9 · K ${t.game.k}`,
    },

    // ---- Epic ----
    {
        id: 'k27', tier: 'Epic', icon: '👑', name: '27 Strikeouts',
        desc: 'The big one. Only strikeouts make outs: a ball caught by a fielder is just another strike, even strike three. Every out is a K; win the game.',
        autoOffense: true, kOnly: true,
        stars: ['Win the game', '3 runs or fewer', 'Shutout'],
        check(t, r, g) {
            if (r.gameOver) return g.state.winner === 'home' ? win() : fail(`Lost ${g.state.score.away}–${g.state.score.home} after ${t.game.k} strikeouts.`);
            return null;
        },
        rate: (t) => (t.game.runs === 0 ? 3 : t.game.runs <= 3 ? 2 : 1),
        progress: (t, g) => `K ${t.game.k}/27 · runs allowed ${t.game.runs} · ${t.game.pitches} pitches`,
    },
];

// Rough difficulty, from test/challenges.js with a strikeout-hunting
// strategy, adjusted for the zone-only ones (the sim can't feel the zone).
const LEVELS = {
    save: 'Easy', fullcount: 'Easy', fumes: 'Easy', junk: 'Easy', clock: 'Medium', knuckle: 'Medium',
    onetwothree: 'Medium', heart: 'Medium', chaos: 'Hard', houdini: 'Hard', side: 'Hard',
    gauntlet: 'Hard', sprint: 'Hard', perfect3: 'Very hard', immaculate: 'Legendary', k27: 'Epic',
};
const ORDER = ['Easy', 'Medium', 'Hard', 'Very hard', 'Legendary', 'Epic'];
for (const c of CHALLENGES) c.level = LEVELS[c.id];
CHALLENGES.sort((a, b) => ['Quick', 'Medium', 'Epic'].indexOf(a.tier) - ['Quick', 'Medium', 'Epic'].indexOf(b.tier)
    || ORDER.indexOf(a.level) - ORDER.indexOf(b.level));

export const CHALLENGE_BY_ID = Object.fromEntries(CHALLENGES.map((c) => [c.id, c]));

function win() { return { status: 'win' }; }
function fail(reason) { return { status: 'fail', reason }; }

// After a tracked pitch: { status, reason, stars } or null if still going.
export function evaluateChallenge(ch, t, r, game) {
    let res = ch.check(t, r, game);
    if (!res && r.gameOver) res = fail('The game ended.');
    if (res && res.status === 'win') res.stars = ch.rate(t, r, game);
    return res;
}

// When the game ends without a pitch of yours (a walk-off while your team
// bats), settle the challenge from the final state.
export function evaluateChallengeAtEnd(ch, t, game) {
    const r = { gameOver: true, halfEnded: true, paEnded: false, play: null, call: null, runs: 0, before: null };
    return evaluateChallenge(ch, t, r, game) ?? fail('The game ended.');
}

// The league's best lineup, by a simple batting value.
export function strongestOffense(league, excludeId) {
    const value = (team) => team.lineup.reduce((sum, s) => {
        const b = league.players[s.id];
        return sum + b.contact + 0.6 * b.eye + 0.8 * b.power;
    }, 0);
    return league.teams.filter((t) => t.id !== excludeId).sort((a, b) => value(b) - value(a))[0];
}

// The league as a challenge sees it: the user's team with the challenge
// pitcher added (league data itself is not changed).
export function challengeLeague(league, ch, userTeamId) {
    const team = league.teams[userTeamId];
    const key = ch.pitcher ?? 'ace';
    const p = { ...SPECIAL_PITCHERS[key], type: 'pitcher' };
    return {
        ...league,
        players: { ...league.players, [p.id]: p },
        teams: league.teams.map((t) => (t.id === team.id ? { ...t, pitchers: [p.id, ...t.pitchers], rotation: [p.id] } : t)),
    };
}

export function challengeFormulas(ch) {
    return createFormulas(ch.formulas ?? {});
}

// A new game set up for the challenge.
export function startChallenge(league, ch, userTeamId, seed = Date.now() >>> 0) {
    const cl = challengeLeague(league, ch, userTeamId);
    const F = challengeFormulas(ch);
    const opp = strongestOffense(league, userTeamId);
    const pitcherId = SPECIAL_PITCHERS[ch.pitcher ?? 'ace'].id;
    const game = Game.create(cl, F, {
        homeId: userTeamId, awayId: opp.id, userTeamId,
        innings: 9, difficulty: ch.difficulty ?? 2, seed, kOnly: !!ch.kOnly,
        home: { starterId: pitcherId },
    });
    applyStart(game, ch.start ?? {});
    game.state.challengeId = ch.id;
    game.log(`Challenge: ${ch.name}. ${teamName(opp)} are batting.`, 'info');
    return { game, league: cl, F };
}

function applyStart(game, start) {
    const st = game.state;
    const inning = start.inning ?? 1;
    const userLead = start.lead ?? 0;
    // Late innings start from a 2–2 game, adjusted for the lead.
    const base = inning > 1 ? 2 : 0;
    st.inning = inning;
    st.half = 'top';
    st.outs = start.outs ?? 0;
    st.balls = start.balls ?? 0;
    st.strikes = start.strikes ?? 0;
    st.score = { home: base + Math.max(0, userLead), away: base + Math.max(0, -userLead) };
    st.line = {
        away: Array.from({ length: inning }, (_, i) => (i === 0 ? st.score.away : 0)),
        home: Array.from({ length: inning - 1 }, (_, i) => (i === 0 ? st.score.home : 0)),
    };
    if (inning === 1) st.score = { home: 0, away: 0 };
    st.hits = { away: st.score.away, home: st.score.home };

    const away = game.side('away');
    away.batIdx = start.batIdx ?? (inning > 1 ? (inning * 4) % 9 : 0);
    const pitcherId = game.side('home').pitcherId;
    const runners = start.bases ?? [false, false, false];
    // Runners are the hitters just before the current one.
    st.bases = runners.map((on, i) => (on ? { id: away.lineup[(away.batIdx + 8 - i) % 9].id, resp: pitcherId } : null));
    game.side('home').status[pitcherId].fatigue = start.fatigue ?? 0;
    st.log = [];
    st.pa = { batterId: game.batter().id, pitcherId, pitches: [] };
}
