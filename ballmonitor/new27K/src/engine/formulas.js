// Every tunable rule in the game is a MathZetta formula. The engine never
// hard-codes a probability: it builds a scope of variables, asks the
// FormulaSet for a number, and rolls dice against it.
//
// Formulas are parsed once (text → postfix → tree) and evaluated with
// MathZetta's evaluate(), never with eval. A formula that fails at run time
// falls back to its default and the error is recorded for the formula lab.

import { parse, fromPostfix } from 'mathzetta';
import { evaluate } from 'mathzetta/evaluate';

// Every variable a formula may use. `sample` is a typical value, used to
// check new formulas and to show example results.
export const VARIABLES = {
    // The pitch
    baseVelo: { group: 'Pitch', sample: 94, desc: 'Typical mph of this pitch type' },
    velo: { group: 'Pitch', sample: 60, desc: "Pitcher's velocity rating for this pitch (20–99)" },
    move: { group: 'Pitch', sample: 60, desc: "Pitcher's movement rating for this pitch (20–99)" },
    control: { group: 'Pitch', sample: 60, desc: "Pitcher's control rating for this pitch (20–99)" },
    effort: { group: 'Pitch', sample: 50, desc: 'Velocity effort slider (0–100)' },
    moveEffort: { group: 'Pitch', sample: 50, desc: 'Movement effort slider (0–100)' },
    wobble: { group: 'Pitch', sample: 0, desc: 'Random late movement of the pitch type, inches (knuckleball 4)' },
    velocity: { group: 'Pitch', sample: 93, desc: 'Actual velocity of this pitch, mph' },
    run: { group: 'Pitch', sample: 3, desc: 'Arm-side run of this pitch, inches (negative = glove side)' },
    drop: { group: 'Pitch', sample: 2, desc: 'Downward break of this pitch, inches' },
    movement: { group: 'Pitch', sample: 4, desc: 'Total break of this pitch, inches' },
    isFast: { group: 'Pitch', sample: 1, desc: '1 for a fastball type, else 0' },
    isBreak: { group: 'Pitch', sample: 0, desc: '1 for a breaking ball, else 0' },
    isOff: { group: 'Pitch', sample: 0, desc: '1 for an off-speed pitch, else 0' },
    veloDiff: { group: 'Pitch', sample: 0, desc: 'mph faster than the previous pitch to this batter (0 on the first pitch)' },
    locDiff: { group: 'Pitch', sample: 0, desc: 'Inches from the previous pitch to this batter (0 on the first pitch)' },
    sameAsLast: { group: 'Pitch', sample: 0, desc: '1 if this is the same pitch type as the last one, else 0' },
    pitchSeen: { group: 'Pitch', sample: 0, desc: 'Times this batter has already seen this pitch type in the at-bat' },

    // The pitcher
    stamina: { group: 'Pitcher', sample: 100, desc: "Pitcher's stamina rating (starters ~100, relievers ~35)" },
    fatigue: { group: 'Pitcher', sample: 0.2, desc: 'How tired the pitcher is: 0 fresh, 1 spent' },
    pitchCount: { group: 'Pitcher', sample: 30, desc: 'Pitches thrown so far this game' },

    // Where it crossed the plate
    x: { group: 'Location', sample: 0, desc: 'Inches right of the zone centre (pitcher’s view)' },
    y: { group: 'Location', sample: 0, desc: 'Inches above the zone centre' },
    px: { group: 'Location', sample: 0, desc: 'x as a fraction of the zone half-width (±1 is the edge)' },
    py: { group: 'Location', sample: 0, desc: 'y as a fraction of the zone half-height (±1 is the edge)' },
    edge: { group: 'Location', sample: 3, desc: 'Inches inside the zone edge (negative = outside), counting the ball’s width' },
    inZone: { group: 'Location', sample: 1, desc: '1 if the pitch is a true strike, else 0' },
    inside: { group: 'Location', sample: 0, desc: 'Inches toward the batter from the middle of the plate' },

    // The batter
    contact: { group: 'Batter', sample: 50, desc: 'Contact rating' },
    power: { group: 'Batter', sample: 50, desc: 'Power rating' },
    eye: { group: 'Batter', sample: 50, desc: 'Plate discipline rating' },
    speed: { group: 'Batter', sample: 50, desc: 'Speed rating' },
    vsPitch: { group: 'Batter', sample: 50, desc: 'Rating against this kind of pitch (fastball, breaking or off-speed)' },
    heat: { group: 'Batter', sample: 0, desc: 'Batter’s heat map at this location: −1 cold to +1 hot' },
    platoon: { group: 'Batter', sample: 1, desc: '1 if pitcher and batter are the same hand (pitcher’s edge), else 0' },
    runnerSpeed: { group: 'Batter', sample: 50, desc: 'Speed of the runner being sent' },

    // The situation
    balls: { group: 'Situation', sample: 0, desc: 'Balls in the count' },
    strikes: { group: 'Situation', sample: 0, desc: 'Strikes in the count' },
    outs: { group: 'Situation', sample: 0, desc: 'Outs in the inning' },
    inning: { group: 'Situation', sample: 1, desc: 'Inning number' },
    runners: { group: 'Situation', sample: 0, desc: 'Runners on base (0–3)' },
    risp: { group: 'Situation', sample: 0, desc: '1 if a runner is on second or third, else 0' },
    scoreDiff: { group: 'Situation', sample: 0, desc: "Pitching team's lead (negative when behind)" },
    difficulty: { group: 'Situation', sample: 2, desc: 'Difficulty setting (1–5)' },
    level: { group: 'Situation', sample: 4, desc: 'Level of play: 1 youth, 2 high school, 3 college, 4 pro' },
    levelVelo: { group: 'Situation', sample: 0, desc: 'mph added to every pitch at this level (youth −26, high school −12, college −5, pro 0)' },
    t: { group: 'Situation', sample: 0, desc: 'Seconds since you pressed Pitch' },
    clockSetting: { group: 'Situation', sample: 20, desc: 'Your pitch clock setting, seconds (20 unless you change it)' },

    // Career (for the career formulas)
    age: { group: 'Career', sample: 16, desc: 'Your pitcher’s age' },
    ip: { group: 'Career', sample: 6, desc: 'Innings pitched in the outing' },
    strikeouts: { group: 'Career', sample: 6, desc: 'Strikeouts in the outing' },
    runsAllowed: { group: 'Career', sample: 2, desc: 'Runs allowed in the outing' },
    walksAllowed: { group: 'Career', sample: 2, desc: 'Walks and hit batters in the outing' },
    hitsAllowed: { group: 'Career', sample: 5, desc: 'Hits allowed in the outing' },
    win: { group: 'Career', sample: 1, desc: '1 if you got the win, else 0' },
    postseason: { group: 'Career', sample: 0, desc: '1 for a playoff or tournament knockout game, else 0' },
    current: { group: 'Career', sample: 50, desc: 'The rating being trained (on the pro scale, 20–99)' },
};

// Ranges for sliders and graphs: [min, max, step].
const RANGES = {
    baseVelo: [55, 100, 1], velo: [20, 99, 1], move: [20, 99, 1], control: [20, 99, 1],
    effort: [0, 100, 1], moveEffort: [0, 100, 1], wobble: [0, 6, 0.5], velocity: [55, 105, 0.5],
    run: [-15, 15, 0.5], drop: [0, 25, 0.5], movement: [0, 25, 0.5],
    isFast: [0, 1, 1], isBreak: [0, 1, 1], isOff: [0, 1, 1],
    veloDiff: [-30, 30, 1], locDiff: [0, 30, 1], sameAsLast: [0, 1, 1], pitchSeen: [0, 5, 1],
    stamina: [20, 130, 1], fatigue: [0, 1.2, 0.05], pitchCount: [0, 130, 1],
    x: [-25, 25, 0.5], y: [-25, 25, 0.5], px: [-3, 3, 0.05], py: [-3, 3, 0.05],
    edge: [-12, 8, 0.25], inZone: [0, 1, 1], inside: [-25, 25, 0.5],
    contact: [20, 99, 1], power: [20, 99, 1], eye: [20, 99, 1], speed: [20, 99, 1], vsPitch: [20, 99, 1],
    heat: [-1, 1, 0.05], platoon: [0, 1, 1], runnerSpeed: [20, 99, 1],
    balls: [0, 3, 1], strikes: [0, 2, 1], outs: [0, 2, 1], inning: [1, 12, 1], runners: [0, 3, 1],
    risp: [0, 1, 1], scoreDiff: [-6, 6, 1], difficulty: [1, 5, 1], t: [0, 15, 0.1], clockSetting: [5, 60, 1],
    level: [1, 4, 1], levelVelo: [-30, 0, 1],
    age: [10, 45, 1], ip: [0, 9, 1 / 3], strikeouts: [0, 20, 1], runsAllowed: [0, 12, 1], walksAllowed: [0, 10, 1],
    hitsAllowed: [0, 15, 1], win: [0, 1, 1], postseason: [0, 1, 1], current: [20, 99, 1],
};
for (const [name, r] of Object.entries(RANGES)) VARIABLES[name].range = r;

export const VARIABLE_NAMES = Object.keys(VARIABLES);

// When each variable becomes known while a pitch is resolved. A formula
// can only use variables from its stages; others hold a neutral sample value.
export const STAGES = {
    situation: ['balls', 'strikes', 'outs', 'inning', 'runners', 'risp', 'scoreDiff', 'difficulty', 'level', 'levelVelo', 'fatigue', 'pitchCount', 'stamina', 't', 'clockSetting'],
    batter: ['contact', 'power', 'eye', 'speed', 'vsPitch', 'platoon', 'runnerSpeed'],
    pitch: ['baseVelo', 'velo', 'move', 'control', 'effort', 'moveEffort', 'wobble', 'isFast', 'isBreak', 'isOff'],
    shape: ['velocity', 'run', 'drop', 'movement'],
    history: ['veloDiff', 'locDiff', 'sameAsLast', 'pitchSeen'],
    location: ['x', 'y', 'px', 'py', 'edge', 'inZone', 'inside', 'heat'],
    career: ['age', 'ip', 'strikeouts', 'runsAllowed', 'walksAllowed', 'hitsAllowed', 'win', 'postseason', 'current'],
};
const BEFORE_SHAPE = ['situation', 'batter', 'pitch'];
const ALL = Object.keys(STAGES);

export const FORMULAS = [
    // Pitch shape
    { id: 'velocity', group: 'Pitch', label: 'Pitch velocity (mph)', kind: 'value', stages: BEFORE_SHAPE,
      desc: 'How fast the pitch is thrown. Starts from the typical pro speed of the pitch type plus levelVelo (slower at lower levels), adjusted by the pitcher’s rating for it, the velocity-effort slider and fatigue.',
      expr: 'baseVelo + levelVelo + (velo - 60)/8 + (effort - 50)/12 - 4*fatigue' },
    { id: 'movementMult', group: 'Pitch', label: 'Break multiplier', kind: 'value', min: 0, stages: BEFORE_SHAPE,
      desc: 'Multiplies the pitch type’s break (run and drop). 1 = a typical pitch; 1.3 = 30% more break.',
      expr: '1 + (move - 60)/90 + (moveEffort - 50)/150 - 0.25*fatigue' },
    { id: 'scatter', group: 'Pitch', label: 'Control scatter (inches, std. dev.)', kind: 'value', min: 0, stages: [...BEFORE_SHAPE, 'shape'],
      desc: 'How far a pitch misses where you aimed: the standard deviation, in inches, of a random miss in each direction. Shown as the ring around the break guide.',
      expr: 'wobble + max(0.75, 2.4 + (60 - control)/12 + (effort - 50)/30 + (moveEffort - 50)/45 + 3*fatigue)' },
    { id: 'fatigueGain', group: 'Pitch', label: 'Fatigue added per pitch', kind: 'value', min: 0, stages: ALL,
      desc: 'Added to the pitcher’s fatigue after every pitch. Fatigue starts at 0; at 1 the pitcher is spent (energy bar empty). Location variables are 0 on a pitch-clock violation.',
      expr: '(1 + (effort - 50)/50 + (moveEffort - 50)/80 + 0.25*runners + (if balls = 3 then 0.3 else 0)) / stamina' },

    // The moving strike zone
    { id: 'zoneSpeed', group: 'Zone', label: 'Zone speed (inches/second)', kind: 'value', min: 0, stages: ['situation'],
      desc: 'How fast the strike zone moves while you aim. Re-evaluated every frame, so it can depend on t (seconds since you pressed Pitch).',
      expr: '6 + 5*difficulty + 10*fatigue + 2*runners + 0.5*t' },
    { id: 'zoneChaos', group: 'Zone', label: 'Zone chaos (how sharply it turns)', kind: 'value', min: 0, stages: ['situation'],
      desc: 'How erratically the zone changes direction: the random turn per √second, in radians. 0 = straight lines and bounces; 5+ = jittery.',
      expr: '1 + 0.8*difficulty + 2*fatigue' },
    { id: 'zoneRange', group: 'Zone', label: 'Zone drift range (inches)', kind: 'value', min: 0, stages: ['situation'],
      desc: 'How far the zone may wander from home in each direction. Set when you press Pitch.',
      expr: '6 + 2*difficulty' },
    { id: 'pitchClock', group: 'Zone', label: 'Pitch clock (seconds)', kind: 'value', min: 1, stages: ['situation'],
      desc: 'Seconds you have to throw (from pressing Pitch, or from the end of the last pitch). clockSetting is the clock you chose (20 by default). Running out is an automatic ball.',
      expr: 'clockSetting' },

    // The batter's decision
    { id: 'hbpChance', group: 'Batter', label: 'Hit-by-pitch chance', kind: 'prob', stages: ALL,
      desc: 'Chance the pitch hits the batter. inside = inches toward the batter from the middle of the plate; the plate edge is at 8.5.',
      expr: 'if inside > 19 then min(0.9, (inside - 19)/8) else 0' },
    { id: 'swingChance', group: 'Batter', label: 'Swing chance', kind: 'prob', stages: ALL,
      desc: 'Chance the batter swings. edge is inches inside the zone (negative = outside). Batters with a good eye swing more at strikes and less at balls.',
      expr: '0.03 + 0.64/(1 + 10^(-(edge + 2)/2.5)) + 0.08*strikes - 0.03*balls + (eye - 50)/250*(if edge > 0 then 1 else -1) - (if balls = 3 and strikes < 2 then 0.15 else 0)' },
    { id: 'strikeCall', group: 'Batter', label: 'Called-strike chance (umpire)', kind: 'prob', stages: ALL,
      desc: 'When the batter takes, the chance the umpire calls a strike. Try inZone for a robot umpire.',
      expr: '1/(1 + 10^(-(edge + 0.3)/0.8))' },
    { id: 'contactChance', group: 'Batter', label: 'Contact chance on a swing', kind: 'prob', stages: ALL,
      desc: 'When the batter swings, the chance of hitting it (fair or foul). Otherwise it is a swinging strike. Speed, break, location, the batter’s skill and heat map, and changing speeds all matter.',
      expr: '1/(1 + 10^(-(0.17 + (contact - 50)/70 + (vsPitch - 50)/120 - (velocity - levelVelo - 91)/14 - (movement - 8)/18 + edge/14 + heat/6 - 0.12*platoon - abs(veloDiff)/80 + 0.06*pitchSeen)))' },
    { id: 'foulChance', group: 'Batter', label: 'Foul chance on contact', kind: 'prob', stages: ALL,
      desc: 'When the batter makes contact, the chance it goes foul instead of into play.',
      expr: 'max(0.15, min(0.75, 0.6 - edge/25 + (velocity - levelVelo - 90)/60 + 0.04*strikes))' },

    // Balls in play
    { id: 'hitChance', group: 'In play', label: 'Hit chance on a fair ball', kind: 'prob', stages: ALL,
      desc: 'Chance a ball in play is a hit (batting average on balls in play; real baseball is about .290).',
      expr: '0.27 + (contact - 50)/350 + (power - 50)/500 + heat/20 + edge/120 - (movement - 8)/150 + (speed - 50)/600' },
    { id: 'extraBaseChance', group: 'In play', label: 'Extra-base share of hits', kind: 'prob', stages: ALL,
      desc: 'Of hits, the share that go for extra bases (double, triple or homer).',
      expr: '0.31 + (power - 50)/150 + heat/12' },
    { id: 'homerShare', group: 'In play', label: 'Home-run share of extra-base hits', kind: 'prob', stages: ALL,
      desc: 'Of extra-base hits, the share that leave the park. Sinking pitches (big drop) are harder to lift.',
      expr: '0.33 + (power - 50)/110 + heat/10 - drop/80' },
    { id: 'tripleShare', group: 'In play', label: 'Triple share of doubles and triples', kind: 'prob', stages: ALL,
      desc: 'Of extra-base hits that stay in the park, the share that are triples.',
      expr: '0.07 + (speed - 50)/300' },
    { id: 'errorChance', group: 'In play', label: 'Error chance on an out', kind: 'prob', stages: ALL,
      desc: 'Chance a ball that should be an out becomes an error (batter safe, runners move up, run unearned). Fielding gets better at each level.',
      expr: '0.03 + 0.035*(4 - level)' },
    { id: 'groundBallShare', group: 'In play', label: 'Ground-ball share of outs', kind: 'prob', stages: ALL,
      desc: 'Of outs in play, the share that are grounders. Low pitches and sinking pitches produce more.',
      expr: '0.44 + drop/40 - py/5' },
    { id: 'popupShare', group: 'In play', label: 'Pop-up share of air outs', kind: 'prob', stages: ALL,
      desc: 'Of air outs, the share that are pop-ups (no runner can tag up). The rest are fly balls.',
      expr: '0.18 + py/8' },

    // Running
    { id: 'doublePlayChance', group: 'Running', label: 'Double-play chance (grounder, runner on 1st)', kind: 'prob', stages: ALL,
      desc: 'On a ground out with a runner on first and fewer than two outs, the chance of turning two. speed is the batter’s.',
      expr: '0.18 - (speed - 50)/200' },
    { id: 'sacFlyChance', group: 'Running', label: 'Runner on 3rd scores on a fly out', kind: 'prob', stages: ALL,
      desc: 'With fewer than two outs, chance the runner on third tags and scores on a fly ball.',
      expr: '0.6 + (runnerSpeed - 50)/150' },
    { id: 'groundScoreChance', group: 'Running', label: 'Runner on 3rd scores on a ground out', kind: 'prob', stages: ALL,
      desc: 'With fewer than two outs, chance an unforced runner on third scores on a grounder.',
      expr: '0.45 + (runnerSpeed - 50)/150' },
    { id: 'groundAdvance', group: 'Running', label: 'Runner on 2nd takes 3rd on a ground out', kind: 'prob', stages: ALL,
      desc: 'Chance an unforced runner on second moves up to third on a ground out.',
      expr: '0.55 + (runnerSpeed - 50)/150' },
    { id: 'tagFromSecond', group: 'Running', label: 'Runner on 2nd tags to 3rd on a fly out', kind: 'prob', stages: ALL,
      desc: 'Chance the runner on second tags up and takes third on a fly out.',
      expr: '0.3 + (runnerSpeed - 50)/150' },
    { id: 'firstToThird', group: 'Running', label: 'Runner on 1st reaches 3rd on a single', kind: 'prob', stages: ALL,
      desc: 'On a single, chance the runner from first goes to third (if it is open).',
      expr: '0.28 + (runnerSpeed - 50)/150' },
    { id: 'scoreFromSecond', group: 'Running', label: 'Runner on 2nd scores on a single', kind: 'prob', stages: ALL,
      desc: 'On a single, chance the runner from second scores. With two outs runners go on contact.',
      expr: '0.55 + 0.1*outs + (runnerSpeed - 50)/150' },
    { id: 'scoreFromFirst', group: 'Running', label: 'Runner on 1st scores on a double', kind: 'prob', stages: ALL,
      desc: 'On a double, chance the runner from first scores.',
      expr: '0.35 + 0.1*outs + (runnerSpeed - 50)/150' },

    // Seasons
    { id: 'pitchLimit', group: 'Season', label: 'Pitch limit per game', kind: 'value', min: 1, stages: ['situation'],
      desc: 'Most pitches a pitcher may throw in one game; at the limit he finishes the batter and must come out. Youth 85 and high school 105, as in their real rules.',
      expr: 'if level = 1 then 85 else if level = 2 then 105 else 400' },
    { id: 'restDays', group: 'Season', label: 'Rest days after pitching', kind: 'value', min: 0, stages: ['situation'],
      desc: 'Days a pitcher must sit out after throwing pitchCount pitches in a game (youth and high school follow pitch-count rest rules; above that, roughly a five-day rotation for starters).',
      expr: 'if level <= 2 then (if pitchCount > 65 then 4 else if pitchCount > 50 then 3 else if pitchCount > 35 then 2 else if pitchCount > 20 then 1 else 0) else (if pitchCount > 75 then 4 else if pitchCount > 50 then 2 else if pitchCount > 25 then 1 else 0)' },

    // Career
    { id: 'xpForOuting', group: 'Career', label: 'XP for an outing', kind: 'value', min: 0, stages: ['career', 'situation'],
      desc: 'Experience your pitcher earns from one appearance (spent on training). level is 1 youth … 4 pro; postseason games count extra.',
      expr: 'max(1, 2 + 1.5*ip + strikeouts - runsAllowed - 0.5*walksAllowed + 3*win) * (1 + 0.5*postseason) * (1 + 0.15*(level - 1))' },
    { id: 'growth', group: 'Career', label: 'Natural growth per year', kind: 'value', stages: ['career'],
      desc: 'Rating points every rating gains (or loses) each off-season just from growing up and getting older.',
      expr: 'if age < 16 then 4 else if age < 19 then 3 else if age < 23 then 1.5 else if age < 28 then 0.5 else if age < 32 then 0 else -1.5' },
    { id: 'trainingCost', group: 'Career', label: 'XP to raise a rating by one', kind: 'value', min: 1, stages: ['career'],
      desc: 'Cost of one point of training. current is the rating on the pro scale (20–99): the higher it is, the harder the next point, and much harder past 70.',
      expr: 'max(2, (current - 20)/6) * (1 + max(0, current - 70)/6)' },
    { id: 'pitchCost', group: 'Career', label: 'XP to learn a new pitch', kind: 'value', min: 1, stages: ['career'],
      desc: 'Cost of adding a pitch to your arsenal (some pitches need a minimum age).',
      expr: '30 + 4*(age - 12)' },
    { id: 'careerHook', group: 'Career', label: 'Manager takes you out (checked between batters)', kind: 'prob', stages: ['situation', 'career'],
      desc: 'When you pitch in career mode, the chance the manager goes to the bullpen before the next batter. runsAllowed is your runs today.',
      expr: 'if fatigue > 0.95 then 1 else if fatigue > 0.7 then 0.15 + 0.1*runners + 0.05*runsAllowed else if runsAllowed >= 6 then 0.5 else 0' },

    // Computer pitchers
    { id: 'aiZoneRate', group: 'Computer', label: 'Computer aims in the zone', kind: 'prob', stages: [...BEFORE_SHAPE, 'shape'],
      desc: 'How often computer pitchers aim inside the zone rather than just off the edge.',
      expr: '0.45 + 0.08*(balls - strikes)' },
    { id: 'aiScatter', group: 'Computer', label: 'Extra scatter for computer pitchers (inches)', kind: 'value', min: 0, stages: [...BEFORE_SHAPE, 'shape'],
      desc: 'Computer pitchers don’t face the moving zone, so they get this much extra scatter instead. Raise it to make opposing pitchers wilder (more offense for your team).',
      expr: '2' },
    { id: 'aiHook', group: 'Computer', label: 'Computer pulls its pitcher', kind: 'prob', stages: ['situation'],
      desc: 'Checked before each batter: the chance the computer goes to its bullpen.',
      expr: 'if fatigue > 0.95 then 1 else (if fatigue > 0.75 then 0.25 + 0.1*runners else 0)' },
];

export const FORMULA_BY_ID = Object.fromEntries(FORMULAS.map((f) => [f.id, f]));

export const SAMPLE_SCOPE = Object.fromEntries(VARIABLE_NAMES.map((n) => [n, VARIABLES[n].sample]));

// What a variable holds before its stage is reached: samples, with the
// location neutral.
export const NEUTRAL_SCOPE = { ...SAMPLE_SCOPE, edge: 0, inZone: 0 };

// Parse a formula into a tree, checking that it evaluates to a number.
export function compileFormula(text) {
    const tree = fromPostfix(parse(text, { names: VARIABLE_NAMES }));
    const v = evaluate(tree, SAMPLE_SCOPE);
    if (typeof v !== 'number' && typeof v !== 'boolean') throw new Error('Formula must give a number');
    if (!Number.isFinite(Number(v))) throw new Error('Formula gives a non-finite value with the sample variables');
    return tree;
}

// Clamp a formula's value to its allowed range.
export function clampValue(f, v) {
    if (f.kind === 'prob') v = Math.min(1, Math.max(0, v));
    if (f.min !== undefined) v = Math.max(f.min, v);
    if (f.max !== undefined) v = Math.min(f.max, v);
    return v;
}

// Variables a formula's text uses (in order of first use).
export function usedVariables(text) {
    const tokens = parse(text, { names: VARIABLE_NAMES });
    return [...new Set(tokens.filter((t) => Object.prototype.hasOwnProperty.call(VARIABLES, t)))];
}

// Variables known when a formula runs.
export function availableVariables(id) {
    return FORMULA_BY_ID[id].stages.flatMap((st) => STAGES[st]);
}

// Ready-made rule sets. Applying one merges it over your current formulas.
export const PRESETS = [
    { id: 'default', name: 'Default rules', desc: 'Everything back to the defaults (close to real MLB rates).', formulas: null },
    { id: 'arcade', name: 'Arcade', desc: 'A slower, calmer zone, a longer clock, tighter control and more strikeouts.', formulas: {
        zoneSpeed: '4 + 3*difficulty + 6*fatigue + 0.3*t',
        zoneChaos: '0.6 + 0.5*difficulty + fatigue',
        pitchClock: 'clockSetting + 10',
        scatter: 'wobble + max(0.5, 1.6 + (60 - control)/15 + (effort - 50)/40 + (moveEffort - 50)/60 + 2*fatigue)',
        contactChance: '1/(1 + 10^(-(0 + (contact - 50)/70 + (vsPitch - 50)/120 - (velocity - levelVelo - 91)/12 - (movement - 8)/15 + edge/14 + heat/6 - 0.12*platoon - abs(veloDiff)/60 + 0.06*pitchSeen)))',
    } },
    { id: 'chaos', name: 'Chaos zone', desc: 'The zone races, swerves and drifts far, and the clock is short. For experts.', formulas: {
        zoneSpeed: '12 + 7*difficulty + 15*fatigue + 3*runners + 2*t',
        zoneChaos: '4 + 1.5*difficulty + 3*fatigue',
        zoneRange: '10 + 3*difficulty',
        pitchClock: 'min(clockSetting, 9 - difficulty)',
    } },
    { id: 'robo', name: 'Robot umpire', desc: 'Every taken pitch is called exactly by the rule book.', formulas: {
        strikeCall: 'inZone',
    } },
    { id: 'generous', name: 'Generous umpire', desc: 'Pitchers get a couple of inches off the edges.', formulas: {
        strikeCall: '1/(1 + 10^(-(edge + 1.8)/1.1))',
    } },
    { id: 'deadball', name: 'Dead-ball era', desc: 'Few home runs, more singles and slap hitting.', formulas: {
        homerShare: '0.06 + (power - 50)/300 + heat/30',
        hitChance: '0.3 + (contact - 50)/300 + heat/20 + edge/120 - (movement - 8)/150 + (speed - 50)/400',
        extraBaseChance: '0.2 + (power - 50)/200 + (speed - 50)/300',
    } },
    { id: 'ttt', name: 'Three true outcomes', desc: 'Big swings: more strikeouts, more walks, more homers.', formulas: {
        contactChance: '1/(1 + 10^(-(0.02 + (contact - 50)/70 + (vsPitch - 50)/120 - (velocity - levelVelo - 91)/14 - (movement - 8)/18 + edge/14 + heat/6 - 0.12*platoon - abs(veloDiff)/80 + 0.06*pitchSeen)))',
        homerShare: '0.5 + (power - 50)/90 + heat/8 - drop/80',
        extraBaseChance: '0.4 + (power - 50)/120 + heat/10',
        swingChance: '0.02 + 0.62/(1 + 10^(-(edge + 1)/2)) + 0.06*strikes - 0.03*balls + (eye - 50)/200*(if edge > 0 then 1 else -1)',
    } },
];

export function createFormulas(overrides = {}) {
    const defaults = {};
    const active = {};
    const texts = {};
    const errors = {};

    for (const f of FORMULAS) {
        defaults[f.id] = compileFormula(f.expr);
        active[f.id] = defaults[f.id];
        texts[f.id] = f.expr;
    }

    const set = {
        // Value of a formula, clamped to its range. Never throws.
        eval(id, scope) {
            const f = FORMULA_BY_ID[id];
            let v;
            try {
                v = Number(evaluate(active[id], scope));
                if (!Number.isFinite(v)) throw new Error('gave ' + v);
            } catch (e) {
                if (!errors[id]) errors[id] = e.message;
                v = Number(evaluate(defaults[id], scope));
            }
            return clampValue(f, v);
        },
        text: (id) => texts[id],
        isCustom: (id) => texts[id] !== FORMULA_BY_ID[id].expr,
        // Replace a formula; returns an error message, or null on success.
        setText(id, text) {
            try {
                active[id] = compileFormula(text);
                texts[id] = text;
                delete errors[id];
                return null;
            } catch (e) {
                return e.message;
            }
        },
        reset(id) {
            active[id] = defaults[id];
            texts[id] = FORMULA_BY_ID[id].expr;
            delete errors[id];
        },
        overrides() {
            const out = {};
            for (const f of FORMULAS) if (set.isCustom(f.id)) out[f.id] = texts[f.id];
            return out;
        },
        errors,
    };

    for (const [id, text] of Object.entries(overrides)) {
        if (FORMULA_BY_ID[id]) set.setText(id, text);
    }
    return set;
}
