// Pitch movement directions and the catcher's mound-visit advice.
//   node test/advice.js

import { generateLeague } from '../src/engine/league.js';
import { createFormulas, NEUTRAL_SCOPE } from '../src/engine/formulas.js';
import { Game } from '../src/engine/game.js';
import { shapePitch } from '../src/engine/pitch.js';
import { catcherAdvice, evaluatePitches, describeSpot, callPitch } from '../src/engine/advice.js';
import { createRng } from '../src/engine/rng.js';
import { ZONE } from '../src/engine/data.js';

const league = generateLeague(42);
const F = createFormulas({});
let failures = 0;

function check(name, cond, detail = '') {
    if (!cond) {
        failures += 1;
        console.error(`FAIL ${name} ${detail}`);
    } else {
        console.log(`ok   ${name}`);
    }
}

// How a pitch type breaks for a pitcher throwing with this hand.
function breakOf(type, throws) {
    const pitcher = { throws, pitches: [{ type, velo: 60, move: 60, control: 60 }] };
    return shapePitch(F, pitcher, 0, { effort: 50, moveEffort: 50 }, { ...NEUTRAL_SCOPE, fatigue: 0, levelVelo: 0 });
}

// Screen +x is the first-base side; a right-handed batter stands at -x.
check('RHP slider breaks right (away from a righty)', breakOf('Slider', 'R').dx > 0);
check('RHP sweeper breaks right', breakOf('Sweeper', 'R').dx > 0);
check('RHP cutter breaks right', breakOf('Cutter', 'R').dx > 0);
check('RHP curveball breaks right and down', breakOf('Curveball', 'R').dx > 0 && breakOf('Curveball', 'R').dy < 0);
check('RHP changeup fades left (in on a righty)', breakOf('Changeup', 'R').dx < 0);
check('RHP sinker runs left and sinks', breakOf('Sinker', 'R').dx < 0 && breakOf('Sinker', 'R').dy < 0);
check('LHP slider breaks left', breakOf('Slider', 'L').dx < 0);
check('LHP changeup fades right', breakOf('Changeup', 'L').dx > 0);

check('spot words: down and away from a righty', describeSpot(7, -8, 'R') === 'down and away');
check('spot words: up and in on a lefty', describeSpot(7, 8, 'L') === 'up and in');
check('spot words: in the dirt', describeSpot(0, -20, 'R').startsWith('in the dirt'));

function gameAt(balls, strikes, opts = {}) {
    const g = Game.create(league, F, { homeId: 0, awayId: 1, userTeamId: 0, seed: 11, ...opts });
    g.state.balls = balls;
    g.state.strikes = strikes;
    return g;
}

{
    const g = gameAt(0, 0);
    const evals = evaluatePitches(g);
    check('every pitch is scored', evals.length === g.pitcher().pitches.length && evals.every((e) => e.spots.length > 50));
    check('scores are finite', evals.every((e) => e.spots.every((s) => Number.isFinite(s.rv))));
    const best = evals.map((e) => e.spots[0].rv);
    const middle = evals.map((e) => e.spots.find((s) => s.target.x === 0 && s.target.y === 0).rv);
    check('the best spot beats the middle of the plate', best.every((b, i) => b <= middle[i]));
}

{
    const a30 = catcherAdvice(gameAt(3, 0));
    const a02 = catcherAdvice(gameAt(0, 2));
    check('3-0: the plan throws a strike', a30.options[0].ball < 0.35, `ball ${a30.options[0].ball}`);
    check('0-2: the plan is more willing to miss than at 3-0', a02.options[0].ball > a30.options[0].ball);
    check('advice has a headline, options, notes', a30.headline && a30.options.length >= 1 && a30.notes.length >= 1);
    check('options say where and why', a02.options.every((o) => o.where && o.aimNote && Array.isArray(o.reasons)));
    const av = a30.avoid;
    check('the mistake to avoid is a strike', av && Math.abs(av.target.x) <= ZONE.halfW && Math.abs(av.target.y) <= ZONE.halfH);
    check('the aim allows for the break', a02.options.every((o) => {
        const e = evaluatePitches(gameAt(0, 2))[o.pitchIdx];
        return Math.abs(o.aim.x + e.shape.dx - o.target.x) < 1e-9 && Math.abs(o.aim.y + e.shape.dy - o.target.y) < 1e-9;
    }));
}

{
    const a = catcherAdvice(gameAt(1, 1, { kOnly: true }));
    check('strikeouts-only rules work too', a.options.length >= 1 && Number.isFinite(a.options[0].rv));
}

{
    // The catcher calling pitches.
    const g = gameAt(1, 1);
    const rng = createRng(3);
    const efforts = { effort: 50, moveEffort: 50 };
    const n = g.pitcher().pitches.length;
    const calls = Array.from({ length: 40 }, () => callPitch(g, efforts, rng));
    check('a call names a pitch he has and a spot', calls.every((c) => c.pitchIdx >= 0 && c.pitchIdx < n && Number.isFinite(c.target.x) && c.where));
    check('he mixes his calls', new Set(calls.map((c) => `${c.pitchIdx}:${c.target.x},${c.target.y}`)).size > 1);
    const best = Math.min(...evaluatePitches(g, efforts).map((e) => e.spots[0].rv));
    check('calls stay close to the best plan', calls.every((c) => c.rv <= best + 0.06), `best ${best}`);
    const shook = callPitch(g, efforts, rng, { exclude: [0] });
    check('shaking off gives another pitch', n < 2 || shook.pitchIdx !== 0);
    const mine = callPitch(g, efforts, rng, { pitchIdx: n - 1 });
    check('picking a pitch gets a spot for that pitch', mine.pitchIdx === n - 1);
    check('the aim allows for the break of the called pitch', Math.abs(mine.aim.x - (mine.target.x - g.previewPitch(n - 1, efforts, { t: 1.5 }).dx)) < 1e-9);
}

console.log(failures ? `\n${failures} advice check(s) failed` : '\nall advice checks passed');
process.exit(failures ? 1 : 0);
