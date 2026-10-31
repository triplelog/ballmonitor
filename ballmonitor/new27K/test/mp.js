// Multiplayer rules, without a browser: turns alternate pitching and
// managing, the server decides every pitch, moves are checked, secrets stay
// secret, the time limit hands an expired turn to the computer, and
// resigning ends the game.
//   node test/mp.js

import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createMpStore } from '../server/mp.js';
import { createFormulas } from '../src/engine/formulas.js';
import { Game } from '../src/engine/game.js';
import { aiChoosePitch } from '../src/engine/ai.js';
import { createRng } from '../src/engine/rng.js';

let failures = 0;
const check = (name, cond, detail = '') => {
    if (cond) console.log(`ok   ${name}`);
    else { failures += 1; console.error(`FAIL ${name} ${detail}`); }
};
const errorStatus = (fn) => {
    try { fn(); return null; } catch (e) { return e.status ?? 'thrown'; }
};

const dir = mkdtempSync(join(tmpdir(), '27k-mp-'));
let clock = 1_000_000;
const store = createMpStore({ dir, now: () => clock });
const rng = createRng(5);

// A player's browser pitching its half: it only sends inputs (here, the
// computer's choice of pitch and aim); the server answers with the result.
function pitchHalf(view, playerId, league) {
    let v = view;
    const startHalf = `${v.state.inning}${v.state.half}`;
    while (v.status === 'active' && v.turn.phase === 'pitch' && `${v.state.inning}${v.state.half}` === startHalf) {
        const key = v.turn.key;
        const local = new Game(league, createFormulas(v.settings.formulas), { ...structuredClone(v.state), userTeamId: v.state.sides[key].teamId });
        if (local.mustChangePitcher(key)) {
            v = store.action(v.id, { playerId, version: v.version, action: { type: 'changePitcher', pitcherId: local.bullpen(key)[0] } });
            continue;
        }
        const c = aiChoosePitch(local, rng);
        const out = store.pitch(v.id, { playerId, version: v.version, pitchIdx: c.pitchIdx, effort: c.effort, moveEffort: c.moveEffort, aim: c.aim, t: 1 });
        v = out.game;
    }
    return v;
}
const done = (v, playerId) => store.action(v.id, { playerId, version: v.version, action: { type: 'done' } });

const a = 'player-ann-0001';
const b = 'player-ben-0002';
let v = store.create({ playerId: a, name: 'Ann', level: 'hs', innings: 3, side: 'home', timeLimit: 600 });
const league = v.league;
check('new game waits for an opponent', v.status === 'waiting' && v.seats.home.name === 'Ann' && v.seats.home.mine && !v.seats.away);
check('league trimmed to two teams', league.teams.length === 2 && Object.keys(league.pitchStats).length > 0);
check('views hide player ids and the random state', !JSON.stringify(v).includes(a) && v.state.rngState === undefined);

v = store.join(v.code.toLowerCase(), { playerId: b, name: 'Ben' });
check('joins by code', v.status === 'active' && v.seats.away.name === 'Ben' && v.seats.away.mine && !v.seats.home.mine);
check('away manages first (sets his lineup)', v.turn.key === 'away' && v.turn.phase === 'manage');
check('list hides ids too', !JSON.stringify(store.list(a)).includes(b) && store.list(b)[0].myTurn && !store.list(a)[0].myTurn);
check('the full game refuses a third player', errorStatus(() => store.join(v.id, { playerId: 'player-cat-0003' })) === 409);
check('home cannot pitch yet', errorStatus(() => store.pitch(v.id, { playerId: a, version: v.version, pitchIdx: 0, aim: { x: 0, y: 0 } })) === 403);

// Ben's lineup card: flip his first two hitters.
const awayLineup = v.state.sides.away.lineup;
const flipped = [awayLineup[1], awayLineup[0], ...awayLineup.slice(2)];
check('a bad lineup is refused', errorStatus(() => store.action(v.id, { playerId: b, version: v.version, action: { type: 'setLineup', lineup: [awayLineup[0], ...awayLineup.slice(0, 8)] } })) === 400);
v = store.action(v.id, { playerId: b, version: v.version, action: { type: 'setLineup', lineup: flipped } });
check('lineup set and the leadoff man is up', v.state.sides.away.lineup[0].id === flipped[0].id && v.state.pa.batterId === flipped[0].id);
v = done(v, b);
check('then home pitches the top', v.turn.key === 'home' && v.turn.phase === 'pitch');
check('managing moves are refused while pitching', errorStatus(() => done(v, a)) === 409);
check('stale version is refused', errorStatus(() => store.pitch(v.id, { playerId: a, version: v.version - 1, pitchIdx: 0, aim: { x: 0, y: 0 } })) === 409);
check('nonsense pitch refused', errorStatus(() => store.pitch(v.id, { playerId: a, version: v.version, pitchIdx: 99, aim: { x: 0, y: 0 } })) === 400);

v = pitchHalf(v, a, league);
check('after pitching the top, home manages before batting', v.turn.key === 'home' && v.turn.phase === 'manage' && v.state.half === 'bottom');
v = store.action(v.id, { playerId: a, version: v.version, action: { type: 'setLineup', lineup: v.state.sides.home.lineup } });
v = done(v, a);
check('then away pitches the bottom', v.turn.key === 'away' && v.turn.phase === 'pitch');
v = pitchHalf(v, b, league);
check('away manages before the top of the 2nd', v.turn.key === 'away' && v.turn.phase === 'manage');
check('can’t redo the lineup after batting', errorStatus(() => store.action(v.id, { playerId: b, version: v.version, action: { type: 'setLineup', lineup: flipped } })) === 400);
const benchId = league.teams[1].batters.find((id) => !v.state.sides.away.lineup.some((l) => l.id === id));
v = store.action(v.id, { playerId: b, version: v.version, action: { type: 'sub', slot: 4, benchId } });
check('a substitution goes in', v.state.sides.away.lineup[4].id === benchId && v.state.sides.away.removed.length === 1);
check('a removed player can’t come back', errorStatus(() => store.action(v.id, { playerId: b, version: v.version, action: { type: 'sub', slot: 5, benchId: v.state.sides.away.removed[0] } })) === 400);

// Ben dawdles over his substitutions: managing ends with no changes.
clock += 601_000;
v = store.get(v.id, b);
check('expired manage turn passes to pitching', v.turn.key === 'home' && v.turn.phase === 'pitch' && v.timeouts.away === 1);
// Ann dawdles over her pitching: the computer finishes, and she skips managing.
clock += 601_000;
v = store.get(v.id, a);
check('expired half finished by the computer', v.state.half === 'bottom' && v.turn.key === 'away' && v.turn.phase === 'pitch');
check('timeouts noted in the log', v.state.log.filter((l) => l.text.includes('Time ran out')).length === 2);

// Play it out.
let guard = 0;
while (v.status === 'active' && guard++ < 60) {
    const pid = v.turn.key === 'home' ? a : b;
    v = v.turn.phase === 'manage' ? done(v, pid) : pitchHalf(v, pid, league);
}
check('game finishes', v.status === 'done' && v.result && ['home', 'away'].includes(v.result.winner));
check('final score matches the state', v.result.score.home === v.state.score.home && v.result.score.away === v.state.score.away);
check('every pitch was logged with its inputs', store.pitchLog(v.id).length > 20 && store.pitchLog(v.id).every((p) => p.call && 'effort' in p));

const again = createMpStore({ dir, now: () => clock });
check('games persist on disk', again.get(v.id, a).version === v.version);

// Both seats on one device, and resigning.
let solo = store.create({ playerId: a, name: 'Ann', level: 'youth', both: true, manage: false });
check('both seats on one device starts at once (no managing turns)', solo.status === 'active' && solo.turn.phase === 'pitch' && solo.seats.home.mine && solo.seats.away.mine);
solo = pitchHalf(solo, a, solo.league);
check('same player pitches the next half', store.list(a).find((g) => g.id === solo.id).myTurn && solo.turn.phase === 'pitch');
const duel = store.join(store.create({ playerId: a, name: 'Ann' }).id, { playerId: b, name: 'Ben' });
const resigned = store.resign(duel.id, { playerId: b });
check('resigning gives the game to the other side', resigned.status === 'done' && resigned.result.winner === (duel.seats.home.mine ? 'away' : 'home'));

rmSync(dir, { recursive: true, force: true });
console.log(failures ? `\n${failures} failed` : '\nall multiplayer checks passed');
if (failures) process.exitCode = 1;
