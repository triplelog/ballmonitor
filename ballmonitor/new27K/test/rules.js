// Baseball-rule checks: set up a situation, force a play, check the result.
//   node test/rules.js

import { generateLeague } from '../src/engine/league.js';
import { createFormulas, SAMPLE_SCOPE } from '../src/engine/formulas.js';
import { Game } from '../src/engine/game.js';

const league = generateLeague(42);
let failures = 0;

function check(name, cond, detail = '') {
    if (!cond) {
        failures += 1;
        console.error(`FAIL ${name} ${detail}`);
    } else {
        console.log(`ok   ${name}`);
    }
}

// A fresh game with some formulas pinned to fixed values.
function setup(overrides = {}, opts = {}) {
    const F = createFormulas(overrides);
    return Game.create(league, F, { homeId: 0, awayId: 1, seed: 7, innings: 9, ...opts });
}

// Put runners on (true = occupied) using the batting team's lineup.
function bases(game, on) {
    const side = game.side(game.battingKey);
    game.state.bases = on.map((occ, i) => (occ ? { id: side.lineup[(side.batIdx + 5 + i) % 9].id, resp: game.pitcher().id } : null));
}

function play(game, playCode) {
    const result = { probs: {}, text: '' };
    game.endPA(result, playCode, { ...SAMPLE_SCOPE });
    return result;
}

{
    const g = setup();
    bases(g, [true, true, true]);
    const r = play(g, 'BB');
    check('bases-loaded walk scores one', g.state.score.away === 1 && r.runs === 1);
    check('bases stay loaded after walk', g.state.bases.every(Boolean));
}
{
    const g = setup();
    bases(g, [true, true, false]);
    play(g, 'HR');
    check('three-run homer', g.state.score.away === 3 && g.state.bases.every((b) => !b));
}
{
    const g = setup({ groundScoreChance: '1' });
    g.state.outs = 2;
    bases(g, [false, false, true]);
    play(g, 'GO');
    check('no run on a third-out ground out', g.state.score.away === 0);
    check('half inning ends', g.state.half === 'bottom' && g.state.outs === 0);
}
{
    const g = setup({ doublePlayChance: '1' });
    bases(g, [true, false, true]);
    const r = play(g, 'GO');
    check('double play makes two outs', r.play === 'DP' && g.state.outs === 2);
    check('runner from third scores on a 0-out DP, no RBI', g.state.score.away === 1
        && g.state.box.bat[g.side('away').lineup[0].id].rbi === 0);
}
{
    const g = setup({ sacFlyChance: '1' });
    g.state.outs = 1;
    bases(g, [false, false, true]);
    const batterId = g.batter().id;
    const r = play(g, 'FO');
    const box = g.state.box.bat[batterId];
    check('sacrifice fly scores the runner', r.play === 'SF' && g.state.score.away === 1);
    check('sacrifice fly is not an at-bat', box.ab === 0 && box.sf === 1 && box.rbi === 1);
}
{
    const g = setup();
    Object.assign(g.state, { inning: 9, half: 'bottom', outs: 1 });
    g.state.line = { away: [0, 0, 0, 0, 0, 0, 0, 0, 2], home: [0, 0, 0, 0, 0, 0, 0, 2, 0] };
    g.state.score = { away: 2, home: 2 };
    bases(g, [false, false, true]);
    play(g, '1B');
    check('walk-off single ends the game', g.state.over && g.state.winner === 'home' && g.state.score.home === 3);
}
{
    const g = setup();
    Object.assign(g.state, { inning: 9, half: 'top', outs: 2 });
    g.state.score = { away: 1, home: 4 };
    g.state.line = { away: [0, 0, 0, 0, 0, 0, 0, 1, 0], home: [0, 0, 0, 4, 0, 0, 0, 0] };
    play(g, 'K');
    check('home team ahead after top of 9th: game over', g.state.over && g.state.winner === 'home');
}
{
    const g = setup();
    Object.assign(g.state, { inning: 9, half: 'bottom', outs: 2 });
    g.state.score = { away: 3, home: 3 };
    play(g, 'PO');
    check('tied after 9: extra innings', !g.state.over && g.state.inning === 10 && g.state.half === 'top');
}
{
    const g = setup();
    g.state.strikes = 2;
    const before = g.state.pa.pitches.length;
    const r = g.throwPitch({ pitchIdx: 0, effort: 50, moveEffort: 50, clockViolation: true });
    check('pitch clock violation is a ball', r.call === 'clock' && g.state.balls === 1 && g.state.pa.pitches.length === before + 1);
}
{
    // A pitch well outside never gets a swing or a strike call with these formulas.
    const g = setup({ swingChance: 'if edge > 0 then 1 else 0', strikeCall: 'if edge > 0 then 1 else 0', hbpChance: '0' });
    const r = g.throwPitch({ pitchIdx: 0, effort: 50, moveEffort: 50, aim: { x: 0, y: 40 } });
    check('custom formulas drive the call', r.call === 'ball', `got ${r.call}`);
}
{
    const g = setup();
    const benchId = g.bench('away')[0];
    g.pinchHit('away', benchId);
    check('pinch hitter is now batting', g.batter().id === benchId);
    check('replaced player cannot return', !g.bench('away').includes(g.side('away').removed[0]));
}
{
    const g = setup();
    const reliever = g.bullpen('home')[0];
    g.changePitcher('home', reliever);
    check('pitching change takes effect', g.pitcher().id === reliever && g.pitcherStatus().pitches === 0);
}
{
    const F = createFormulas();
    const err = F.setText('swingChance', 'edge +* 2');
    check('bad formula is rejected', typeof err === 'string' && F.text('swingChance') !== 'edge +* 2');
    check('unknown variable is rejected', typeof F.setText('swingChance', 'nonsense * 2') === 'string');
}

console.log(failures ? `\n${failures} failed` : '\nall rules checks passed');
if (failures) process.exitCode = 1;
