// A whole career, simmed: youth to retirement, spending XP along the way.
//   node test/career.js [seasons=40]   (9 reaches the first pro season)

import { createFormulas } from '../src/engine/formulas.js';
import {
    createCareer, startCareerSeason, careerStep, finishSeason, choose, train, learnable, learnPitch, trainCost,
    seasonLine, careerTotals, hallOfFame, PID, prospectScore,
} from '../src/engine/career.js';
import { teamName } from '../src/engine/league.js';

const F = createFormulas();
const maxSeasons = Number(process.argv[2] ?? 40);
let problems = 0;
const fail = (m) => { problems += 1; console.error('  PROBLEM:', m); };

const career = createCareer({ first: 'Sam', last: 'Hurler', throws: 'R', style: 'power', state: 'OH', city: 'Dayton', seed: 4242, play: 'none' });
const t0 = performance.now();
let seasons = 0;
while (!career.retired && seasons < maxSeasons) {
    if (['decision', 'collegeDecision', 'draft', 'freeAgency'].includes(career.stage)) {
        const o = career.offers;
        if (career.stage === 'decision') {
            console.log(`  offers: ${o.colleges.map((c) => `${c.name} (${c.conference})`).join(', ')}; draft projection round ${o.draft.round}`);
            choose(career, { college: o.colleges[0].team });
        } else if (career.stage === 'freeAgency') {
            choose(career, career.age >= 33 ? { retire: true } : { stay: true });
            if (career.retired) break;
        } else choose(career, {});
        continue;
    }
    const season = startCareerSeason(career, F);
    if (season.league.players[PID]?.id !== PID) fail('pitcher not in the league');
    if (!season.league.teams[season.userTeamId].rotation.includes(PID)) fail('pitcher not in the rotation');
    const team = teamName(season.league.teams[season.userTeamId]);
    let steps = 0;
    while (!careerStep(career, F, 'end').done && steps++ < 50000);
    const line = seasonLine(career);
    if (line.gs < 1) fail(`${career.year} ${season.level}: no starts`);
    const entry = finishSeason(career, F);
    seasons += 1;
    // Spend XP: the best pitch's weakest rating, and new pitches when possible.
    let spent = 0;
    for (let guard = 0; guard < 400; guard++) {
        const canLearn = learnable(career);
        if (canLearn.length && career.pitcher.pitches.length < 4 && learnPitch(career, F, canLearn[0]).ok) { spent++; continue; }
        const p = career.pitcher.pitches;
        let best = null;
        p.forEach((x, i) => ['velo', 'control', 'move'].forEach((f) => { if (!best || x[f] < p[best.pitch][best.field]) best = { pitch: i, field: f }; }));
        if (career.xp < trainCost(career, F, best)) break;
        train(career, F, best);
        spent++;
    }
    console.log(`${entry.year} age ${String(entry.age).padStart(2)} ${entry.level.padEnd(7)} ${team.padEnd(30)} ${entry.teamRecord.padStart(6)} ${entry.finish.padEnd(36)} ${entry.line.gs} GS ${entry.line.w}-${entry.line.l} ${entry.line.era.toFixed(2)} ERA ${entry.line.ip} IP ${entry.line.k} K · +${entry.xp} XP, ${spent} upgrades · velo ${career.pitcher.velo} ctl ${career.pitcher.control} mov ${career.pitcher.move} · ${career.pitcher.pitches.map((x) => x.type).join('/')}${entry.awards.length ? ' · ' + entry.awards.join(', ') : ''}`);
}
const ms = performance.now() - t0;
const tot = careerTotals(career);
console.log(`\n${career.retired ? 'retired' : 'stopped'} at ${career.age} after ${seasons} seasons (${(ms / 1000).toFixed(1)} s simmed). Drafted: ${career.draftedIn ? `round ${career.draftedIn.round}, ${career.draftedIn.year}` : '–'}. Pro: ${tot.pro.w ?? 0}-${tot.pro.l ?? 0}, ${tot.pro.k ?? 0} K. Hall of Fame score ${hallOfFame(career)}. Last prospect score ${prospectScore(career)}. Saved size ${(JSON.stringify(career).length / 1024).toFixed(0)} KB`);
for (const level of ['youth', 'hs', 'college', 'pro']) if (seasons >= 9 && !career.history.some((h) => h.level === level)) fail(`never played at the ${level} level`);
console.log(problems ? `${problems} problems` : 'career checks passed');
if (problems) process.exitCode = 1;
