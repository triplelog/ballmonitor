// Short scouting notes on a batter: the pitch types he handles best and
// worst, from his record when there's enough of it, else from his ratings.

import { PITCH_TYPES } from '../engine/data.js';
import { rates } from '../engine/pitchStats.js';
import { typeSkills } from '../engine/league.js';

export function bestWorst(league, b) {
    const mine = league.pitchStats?.[b.id] ?? {};
    const seen = Object.entries(mine).map(([type, s]) => [type, rates(s)]).filter(([, r]) => r.pa >= 15).map(([type, r]) => [type, r.ops]);
    if (seen.length >= 3) {
        seen.sort((x, y) => y[1] - x[1]);
        const f = (v) => v.toFixed(3).replace(/^0/, '');
        return [`${PITCH_TYPES[seen[0][0]].abbr} ${f(seen[0][1])}`, `${PITCH_TYPES[seen.at(-1)[0]].abbr} ${f(seen.at(-1)[1])}`];
    }
    if (!b.typeSkill) return [null, null];
    const skills = typeSkills(b);
    return [`likes ${PITCH_TYPES[skills[0][0]].abbr}`, `weak vs ${PITCH_TYPES[skills.at(-1)[0]].abbr}`];
}
