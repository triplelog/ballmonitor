// Sims a whole season in each format and checks it hangs together.
//   node test/season.js

import { createFormulas } from '../src/engine/formulas.js';
import { LEVELS, LEVEL_ORDER } from '../src/engine/levels.js';
import { createSeason, simAhead, leaders, LEADER_STATS, battingRates, gamesPlayed } from '../src/engine/season.js';
import { stageById, table } from '../src/engine/competition.js';
import { teamName } from '../src/engine/league.js';

const F = createFormulas();
let problems = 0;
const fail = (msg) => { problems += 1; console.error('  PROBLEM:', msg); };
const expect = (cond, msg) => { if (!cond) fail(msg); };

const OPTS = { youth: {}, hs: { state: 'TX' }, college: {}, pro: { length: 60 } };

for (const level of LEVEL_ORDER) {
    const L = LEVELS[level];
    const t0 = performance.now();
    const season = createSeason({ level, seed: 77, userTeamId: 3, formatOpts: OPTS[level] });
    const tCreate = performance.now() - t0;
    simAhead(season, F, 'end');
    const ms = performance.now() - t0;
    const teams = season.league.teams.map((t) => t.id);
    const played = gamesPlayed(season);

    expect(season.phase === 'done' && season.champion !== null, 'no champion');
    expect(season.schedule.every((g) => g.result), 'unplayed games');
    expect(season.stages.every((s) => s.status === 'done'), 'unfinished stages');
    const allRuns = season.schedule.reduce((a, g) => a + g.result.home + g.result.away, 0);
    const statRuns = Object.values(season.stats.bat).reduce((a, s) => a + s.r, 0);
    expect(statRuns === allRuns, `batting runs ${statRuns} != game runs ${allRuns}`);
    const wins = Object.values(season.stats.pitch).reduce((a, s) => a + s.w, 0);
    expect(wins === season.schedule.length, `pitcher wins ${wins} != games ${season.schedule.length}`);
    // Nobody plays twice in a day.
    const seen = new Set();
    for (const g of season.schedule) {
        for (const t of [g.home, g.away]) {
            const k = `${g.day}:${t}`;
            if (seen.has(k)) { fail(`team ${t} plays twice on day ${g.day}`); break; }
            seen.add(k);
        }
    }

    let notes = '';
    if (level === 'youth') {
        expect(teams.length === 128, 'youth needs 128 teams');
        const pools = stageById(season, 'pools');
        expect(pools.groups.length === 32 && pools.groups.every((g) => g.teams.length === 4), 'pools of four');
        expect(teams.every((t) => played[t] >= 3), 'every team plays its three pool games');
        for (const id of ['us', 'intl']) expect(stageById(season, id).matches.length === 15, `${id} bracket has 15 games`);
        const usChamp = stageById(season, 'us').winner;
        const intlChamp = stageById(season, 'intl').winner;
        expect(season.league.teams[usChamp].group === 'US' && season.league.teams[intlChamp].group === 'International', 'sides keep to their brackets');
        expect([usChamp, intlChamp].includes(season.champion), 'world champion came from the final');
        const jp = season.league.teams.find((t) => t.city === 'Japan East');
        notes = `US champ ${teamName(season.league.teams[usChamp])}, International champ ${teamName(season.league.teams[intlChamp])}; Japan East's leadoff man: ${season.league.players[jp.lineup[0].id].first} ${season.league.players[jp.lineup[0].id].last}`;
    } else if (level === 'hs') {
        expect(teams.length === 16, 'sixteen schools');
        const reg = table(season, teams, (g) => g.stage === 'regular');
        expect(reg.every((r) => r.w + r.l === 30), 'everyone plays 30');
        expect(stageById(season, 'state').matches.length === 7, 'eight-team state tournament');
        notes = `schools like ${season.league.teams.slice(0, 3).map(teamName).join(', ')}`;
    } else if (level === 'college') {
        expect(teams.length === 64 && season.divisions.length === 8, '8 conferences of 8');
        const reg = table(season, teams, (g) => g.stage === 'regular');
        expect(reg.every((r) => r.w + r.l === 50), 'everyone plays 50');
        const confGames = season.schedule.filter((g) => g.stage === 'regular' && g.conf);
        expect(confGames.every((g) => season.league.teams[g.home].group === season.league.teams[g.away].group), 'conference games stay in the conference');
        expect(teams.every((t) => confGames.filter((g) => g.home === t || g.away === t).length === 21), 'seven three-game conference series each');
        const regionals = stageById(season, 'regionals');
        const field = regionals.groups.flatMap((g) => g.teams);
        expect(new Set(field).size === 32 && season.autoBids.every((id) => field.includes(id)), '32-team field with every conference champion');
        expect(stageById(season, 'cws').groups.every((g) => g.teams.length === 4), 'CWS pools of four');
        const fin = stageById(season, 'cwsFinals').matches[0];
        expect(Math.max(...fin.wins) === 2 && fin.wins[0] + fin.wins[1] <= 3, 'best-of-three final');
        notes = `finals went ${fin.wins[0] + fin.wins[1]} games`;
    } else {
        const reg = table(season, teams, (g) => g.stage === 'regular');
        expect(reg.every((r) => r.w + r.l === 60), 'everyone plays 60');
        const po = stageById(season, 'playoffs');
        const semis = po.matches.filter((m) => m.round === 0);
        const final = po.matches.find((m) => m.round === 1);
        expect(semis.every((m) => Math.max(...m.wins) === 3), 'best-of-five semifinals');
        expect(Math.max(...final.wins) === 4, 'best-of-seven final');
        notes = `series: ${semis.map((m) => m.wins.join('-')).join(', ')}, final ${final.wins.join('-')}`;
    }

    const runsPerTeamGame = allRuns / season.schedule.length / 2;
    const tot = Object.values(season.stats.bat).reduce((a, s) => { for (const k of ['ab', 'h', 'd', 't', 'hr', 'bb', 'hbp', 'sf', 'pa', 'k']) a[k] = (a[k] ?? 0) + s[k]; return a; }, {});
    const r = battingRates(tot);
    const lead = (k) => { const x = leaders(season, k, 1)[0]; return x ? LEADER_STATS[k].fmt(x.v) : '–'; };
    const kb = (JSON.stringify(season).length / 1024).toFixed(0);
    console.log(`${L.name.padEnd(12)} ${teams.length} teams, ${season.schedule.length} games, made in ${tCreate.toFixed(0)} ms, simmed in ${ms.toFixed(0)} ms, saved size ${kb} KB`);
    console.log(`  runs/team/game ${runsPerTeamGame.toFixed(2)}  AVG/OBP/SLG ${r.avg.toFixed(3)}/${r.obp.toFixed(3)}/${r.slg.toFixed(3)}  leaders: AVG ${lead('avg')}, HR ${lead('hr')}, ERA ${lead('era')}`);
    console.log(`  champion ${teamName(season.league.teams[season.champion])} · ${notes}`);
}
if (problems) { console.error(`${problems} problems`); process.exitCode = 1; } else console.log('season checks passed');
