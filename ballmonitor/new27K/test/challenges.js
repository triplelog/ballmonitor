// Plays every challenge with the computer pitching for you, to check they
// all finish and to see roughly how hard each is.
//   node test/challenges.js [attempts=300]

import { generateLeague } from '../src/engine/league.js';
import { ZONE, PITCH_TYPES } from '../src/engine/data.js';
import { CHALLENGES, startChallenge, evaluateChallenge, evaluateChallengeAtEnd } from '../src/engine/challenges.js';
import { aiPickReliever } from '../src/engine/ai.js';
import { createTracker, track } from '../src/engine/tracker.js';
import { checkAchievements } from '../src/engine/achievements.js';

const attempts = Number(process.argv[2] ?? 300);
// 'hunter' aims like a skilled player chasing strikeouts; 'ai' is the normal computer.
const style = process.argv[3] ?? 'hunter';
const league = generateLeague(3);
let problems = 0;
const achievementsSeen = new Set();

for (const ch of CHALLENGES) {
    let wins = 0;
    const stars = [0, 0, 0, 0];
    const reasons = {};
    let pitches = 0;
    for (let a = 0; a < attempts; a++) {
        const { game } = startChallenge(league, ch, 0, 1000 + a);
        const t = createTracker();
        const userPitchers = game.team('home').pitchers;
        let res = null;
        let guard = 0;
        while (!res) {
            if (++guard > 20000) { problems += 1; console.error(`${ch.id}: never finished`); break; }
            if (game.isUserBatting()) {
                game.simHalfInning();
                if (game.state.over) res = evaluateChallengeAtEnd(ch, t, game);
                continue;
            }
            // A sensible manager: go to the bullpen when the pitcher is spent.
            if (game.pitcherStatus().fatigue > 0.9 && game.state.balls + game.state.strikes === 0) {
                const id = aiPickReliever(game, 'home');
                if (id) game.changePitcher('home', id);
            }
            const r = style === 'hunter' ? game.throwPitch(hunterPitch(game)) : game.aiPitch();
            if (!userPitchers.includes(r.pitcherId)) { problems += 1; console.error(`${ch.id}: wrong pitcher`); break; }
            track(t, r);
            for (const id of checkAchievements(t, r, game)) achievementsSeen.add(id);
            res = evaluateChallenge(ch, t, r, game);
        }
        pitches += t.game.pitches;
        if (res?.status === 'win') { wins += 1; stars[res.stars] += 1; }
        else if (res) reasons[res.reason] = (reasons[res.reason] ?? 0) + 1;
    }
    const top = Object.entries(reasons).sort((x, y) => y[1] - x[1])[0];
    console.log(
        `${ch.name.padEnd(26)} win ${(100 * wins / attempts).toFixed(1).padStart(5)}%  ★${stars[1]} ★★${stars[2]} ★★★${stars[3]}`.padEnd(70),
        `avg ${(pitches / attempts).toFixed(0)} pitches`, top ? `· most common fail: ${top[0]}` : '',
    );
}
console.log(`\nAchievements seen while playing: ${[...achievementsSeen].join(', ')}`);
if (problems) { console.error(`${problems} problems`); process.exitCode = 1; }

// Hunting strikeouts: hard stuff on the edges early, then a breaking or
// off-speed pitch just below the zone with two strikes. Aims with the
// break in mind and a little human error, but no zone motion.
function hunterPitch(game) {
    const st = game.state;
    const p = game.pitcher();
    const idx = (kinds) => {
        const i = p.pitches.findIndex((x) => kinds.includes(PITCH_TYPES[x.type].kind));
        return i < 0 ? 0 : i;
    };
    const twoStrikes = st.strikes === 2;
    const pitchIdx = twoStrikes ? idx(['break', 'off']) : st.balls >= 2 ? idx(['fast']) : (Math.random() < 0.6 ? idx(['fast']) : idx(['break', 'off']));
    const efforts = { effort: twoStrikes ? 85 : 65, moveEffort: twoStrikes ? 85 : 60 };
    const shape = game.previewPitch(pitchIdx, efforts);
    const h = ZONE.halfH + ZONE.ballR;
    const w = ZONE.halfW + ZONE.ballR;
    let target;
    if (twoStrikes && st.balls < 3) target = { x: (Math.random() - 0.5) * 10, y: -h - 2 };
    else if (st.balls >= 3) target = { x: (Math.random() - 0.5) * 8, y: (Math.random() - 0.5) * 10 };
    else target = { x: (Math.random() < 0.5 ? -1 : 1) * (w - 2.5), y: (Math.random() - 0.3) * h * 1.2 };
    const human = 1.5;   // inches of extra aiming error
    return { pitchIdx, ...efforts, aim: { x: target.x - shape.dx + (Math.random() - 0.5) * 2 * human, y: target.y - shape.dy + (Math.random() - 0.5) * 2 * human } };
}
