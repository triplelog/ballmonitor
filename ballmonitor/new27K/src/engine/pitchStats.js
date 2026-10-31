// How each batter has done against each pitch type, from every game played
// in a league (including the simulated history a new league starts with).
// Kept on the league as league.pitchStats[batterId][pitchType].

import { Game } from './game.js';

// Each record is stored as an array in this order (compact: a season can
// hold thousands of them); older saves used objects, which still read fine.
export const FIELDS = ['n', 'sw', 'wh', 'pa', 'ab', 'h', 'tb', 'bb', 'hbp', 'sf', 'k'];
const IX = Object.fromEntries(FIELDS.map((f, i) => [f, i]));
const blank = () => ({ n: 0, sw: 0, wh: 0, pa: 0, ab: 0, h: 0, tb: 0, bb: 0, hbp: 0, sf: 0, k: 0 });

// A record as an object, whichever way it was stored.
export function statObj(s) {
    if (!s) return blank();
    if (!Array.isArray(s)) return s;
    return Object.fromEntries(FIELDS.map((f, i) => [f, s[i] ?? 0]));
}
const TB = { '1B': 1, '2B': 2, '3B': 3, HR: 4 };
const SWINGS = ['swinging', 'foul', 'inplay', 'caught'];

// Record one pitch. A plate appearance counts for the pitch that ended it.
export function recordPitch(league, batterId, type, r) {
    const ps = (league.pitchStats ??= {});
    const byType = (ps[batterId] ??= {});
    let s = byType[type];
    if (!Array.isArray(s)) s = byType[type] = FIELDS.map((f) => s?.[f] ?? 0);
    const add = (f, v = 1) => { s[IX[f]] += v; };
    add('n');
    if (SWINGS.includes(r.call)) add('sw');
    if (r.call === 'swinging') add('wh');
    if (!r.paEnded) return;
    add('pa');
    const play = r.play;
    if (play === 'BB') add('bb');
    else if (play === 'HBP') add('hbp');
    else if (play === 'SF') add('sf');
    else {
        add('ab');
        if (play === 'K' || play === 'KL') add('k');
        if (TB[play]) { add('h'); add('tb', TB[play]); }
    }
}

export function rates(stored) {
    const s = stored ? statObj(stored) : null;
    if (!s || !s.pa) return { pa: s?.pa ?? 0, avg: NaN, obp: NaN, slg: NaN, ops: NaN, k: NaN, whiff: s?.sw ? s.wh / s.sw : NaN };
    const obpDen = s.ab + s.bb + s.hbp + s.sf;
    const obp = obpDen ? (s.h + s.bb + s.hbp) / obpDen : 0;
    const slg = s.ab ? s.tb / s.ab : 0;
    return { pa: s.pa, avg: s.ab ? s.h / s.ab : 0, obp, slg, ops: obp + slg, k: s.k / s.pa, whiff: s.sw ? s.wh / s.sw : NaN };
}

// League-wide line for each pitch type (to judge a batter against).
export function leagueByType(league) {
    const out = {};
    for (const byType of Object.values(league.pitchStats ?? {})) {
        for (const [type, stored] of Object.entries(byType)) {
            const s = statObj(stored);
            const t = (out[type] ??= blank());
            for (const k of Object.keys(t)) t[k] += s[k];
        }
    }
    return Object.fromEntries(Object.entries(out).map(([k, v]) => [k, rates(v)]));
}

// A new league gets a simulated history (about 30 games a team) so the
// numbers mean something from the first pitch.
export function seedHistory(league, F, games = league.teams.length * 15) {
    const n = league.teams.length;
    const starter = (teamId, g) => {
        const rot = league.teams[teamId].rotation;
        return rot[Math.floor(g / n) % rot.length];
    };
    for (let g = 0; g < games; g++) {
        const home = g % n;
        const away = (home + 1 + (Math.floor(g / n) % (n - 1))) % n;
        const game = Game.create(league, F, {
            homeId: home, awayId: away, seed: (league.seed ^ 0xabc) + g * 977,
            home: { starterId: starter(home, g) }, away: { starterId: starter(away, g) },
        });
        game.simToEnd();
    }
    league.historyGames = (league.historyGames ?? 0) + games;
}
