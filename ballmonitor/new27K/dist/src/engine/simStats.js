// Computer-vs-computer simulation and league-wide stats, used by the
// command-line sim and the formula lab.

import { Game } from './game.js';
import { edgeDistance } from './pitch.js';

// Runs games a few at a time: call step() until it returns true.
export function createSim(league, F, { games = 200, seed = 1 } = {}) {
    const t = {
        games: 0, pa: 0, ab: 0, h: 0, d: 0, t: 0, hr: 0, bb: 0, k: 0, hbp: 0, sf: 0, runs: 0, pitches: 0,
        zone: 0, outside: 0, swings: 0, chases: 0, whiffs: 0, fouls: 0, contacts: 0,
        extra: 0, homeWins: 0, dp: 0, e: 0, problems: [],
    };
    const n = league.teams.length;
    let g = 0;

    function playOne() {
        const home = g % n;
        const away = (home + 1 + (Math.floor(g / n) % (n - 1))) % n;
        const game = Game.create(league, F, { homeId: home, awayId: away, seed: seed * 100003 + g });
        while (!game.state.over) {
            for (const r of game.simPlateAppearance()) {
                t.pitches += 1;
                if (r.play === 'DP') t.dp += 1;
                if (r.play === 'E') t.e += 1;
                if (!r.loc || r.call === 'hbp') continue;
                const inZone = edgeDistance(r.loc.x, r.loc.y) >= 0;
                if (inZone) t.zone += 1; else t.outside += 1;
                if (['swinging', 'foul', 'inplay'].includes(r.call)) {
                    t.swings += 1;
                    if (!inZone) t.chases += 1;
                    if (r.call === 'swinging') t.whiffs += 1; else t.contacts += 1;
                    if (r.call === 'foul') t.fouls += 1;
                }
            }
        }
        const st = game.state;
        for (const b of Object.values(st.box.bat)) {
            for (const k of ['pa', 'ab', 'h', 'd', 't', 'hr', 'bb', 'k', 'hbp', 'sf']) t[k] += b[k];
        }
        t.runs += st.score.home + st.score.away;
        if (st.inning > st.settings.innings) t.extra += 1;
        if (st.winner === 'home') t.homeWins += 1;

        // Consistency checks.
        for (const key of ['home', 'away']) {
            const lineSum = st.line[key].reduce((a, b) => a + b, 0);
            if (lineSum !== st.score[key]) t.problems.push(`game ${g}: ${key} linescore ${lineSum} != score ${st.score[key]}`);
        }
        const total = st.score.home + st.score.away;
        const batRuns = Object.values(st.box.bat).reduce((a, b) => a + b.r, 0);
        const pitchRuns = Object.values(st.box.pitch).reduce((a, b) => a + b.r, 0);
        if (batRuns !== total) t.problems.push(`game ${g}: batting runs ${batRuns} != score ${total}`);
        if (pitchRuns !== total) t.problems.push(`game ${g}: pitching runs ${pitchRuns} != score ${total}`);
        if (st.score.home === st.score.away) t.problems.push(`game ${g}: ended tied`);
        g += 1;
        t.games = g;
    }

    return {
        totals: t,
        get done() { return g >= games; },
        step(count = 10) {
            for (let i = 0; i < count && g < games; i++) playOne();
            return g >= games;
        },
        runAll() {
            while (g < games) playOne();
            return t;
        },
    };
}

// League stats as rows: { key, label, value (number), text, mlb }.
export function summarize(t) {
    const div = (a, b) => (b ? a / b : NaN);
    const tb = t.h + t.d + 2 * t.t + 3 * t.hr;
    const avg = div(t.h, t.ab);
    const obp = div(t.h + t.bb + t.hbp, t.ab + t.bb + t.hbp + t.sf);
    const slg = div(tb, t.ab);
    const pct = (v) => (Number.isNaN(v) ? '–' : (100 * v).toFixed(1) + '%');
    const rate = (v) => (Number.isNaN(v) ? '–' : v.toFixed(3).replace(/^0/, ''));
    const num = (d) => (v) => (Number.isNaN(v) ? '–' : v.toFixed(d));
    const rows = [
        ['runs', 'Runs / team / game', div(t.runs, 2 * t.games), num(2), 4.4],
        ['avg', 'Batting average', avg, rate, 0.245],
        ['obp', 'On-base %', obp, rate, 0.315],
        ['slg', 'Slugging %', slg, rate, 0.405],
        ['k', 'Strikeout %', div(t.k, t.pa), pct, 0.225],
        ['bb', 'Walk %', div(t.bb, t.pa), pct, 0.083],
        ['hbp', 'Hit-by-pitch %', div(t.hbp, t.pa), pct, 0.011],
        ['hr', 'Home runs / PA', div(t.hr, t.pa), pct, 0.03],
        ['babip', 'BABIP', div(t.h - t.hr, t.ab - t.k - t.hr + t.sf), rate, 0.29],
        ['xbh', 'Hits that are extra-base', div(t.d + t.t + t.hr, t.h), pct, 0.34],
        ['ppa', 'Pitches / PA', div(t.pitches, t.pa), num(2), 3.9],
        ['zone', 'Zone %', div(t.zone, t.zone + t.outside), pct, 0.49],
        ['swing', 'Swing %', div(t.swings, t.zone + t.outside), pct, 0.47],
        ['chase', 'Chase % (swings outside)', div(t.chases, t.outside), pct, 0.29],
        ['contact', 'Contact % on swings', div(t.contacts, t.swings), pct, 0.76],
        ['foul', 'Foul share of contact', div(t.fouls, t.contacts), pct, 0.47],
        ['dp', 'Double plays / game', div(t.dp, t.games), num(2), 0.7],
        ['err', 'Errors / game', div(t.e, t.games), num(2), 1.1],
        ['extra', 'Extra-inning games', div(t.extra, t.games), pct, 0.09],
    ];
    return rows.map(([key, label, value, fmt, mlb]) => ({ key, label, value, text: fmt(value), mlb, mlbText: fmt(mlb) }));
}
