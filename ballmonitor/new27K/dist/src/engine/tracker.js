// Running stats for the user's pitching, per game, per inning and per
// at-bat. Achievements and challenges read them. Plain JSON, so a game in
// progress can be saved with its tracker.

const OUTS = { K: 1, KL: 1, GO: 1, FO: 1, PO: 1, SF: 1, DP: 2 };
const HITS = ['1B', '2B', '3B', 'HR'];
const ON_BASE = ['1B', '2B', '3B', 'HR', 'BB', 'HBP', 'E'];
const STRIKES = ['called', 'swinging', 'foul', 'inplay', 'caught'];

const blank = () => ({
    pitches: 0, strikes: 0, swinging: 0, bf: 0, outs: 0, k: 0, kLooking: 0,
    hits: 0, bb: 0, hbp: 0, runs: 0, baserunners: 0, outsK: 0, nonKOuts: 0, clock: 0,
});

export function createTracker() {
    return {
        game: { ...blank(), fromStart: null },
        inning: null,
        innKey: null,
        pa: null,
        batterKs: {},
        kStreak: 0,
        bestKStreak: 0,
        heart: 0,           // strikeouts in a row of the 3-4-5 hitters
        first: null,        // situation at the first tracked pitch
    };
}

export const outsOn = (play) => OUTS[play] ?? 0;
export const isHit = (play) => HITS.includes(play);
export const reachedBase = (play) => ON_BASE.includes(play);

// Record one pitch thrown by the user's pitcher.
export function track(t, r) {
    const b = r.before;
    if (!t.first) {
        t.first = { inning: b.inning, half: b.half, outs: b.outs };
        t.game.fromStart = b.inning === 1 && b.outs === 0;
    }
    const key = `${b.inning}${b.half}`;
    if (t.innKey !== key) {
        t.innKey = key;
        t.inning = { ...blank(), startOuts: b.outs, startBases: b.bases, loadedNoOuts: false };
    }
    if (!t.pa || t.pa.done || t.pa.batterId !== r.batterId) {
        t.pa = { batterId: r.batterId, slot: b.batIdx, pitches: 0, types: [], wasThreeOh: false, done: false };
    }
    const inn = t.inning;
    if (b.bases.every(Boolean) && b.outs === 0) inn.loadedNoOuts = true;
    if (b.balls === 3 && b.strikes === 0) t.pa.wasThreeOh = true;
    t.pa.pitches += 1;
    if (!t.pa.types.includes(r.pitch.name)) t.pa.types.push(r.pitch.name);

    for (const agg of [t.game, inn]) {
        agg.pitches += 1;
        if (STRIKES.includes(r.call)) agg.strikes += 1;
        if (r.call === 'swinging') agg.swinging += 1;
        if (r.call === 'clock') agg.clock += 1;
    }
    if (!r.paEnded) return;

    t.pa.done = true;
    const play = r.play;
    const outs = outsOn(play);
    const k = play === 'K' || play === 'KL';
    for (const agg of [t.game, inn]) {
        agg.bf += 1;
        agg.outs += outs;
        agg.runs += r.runs;
        if (k) { agg.k += 1; agg.outsK += 1; }
        else agg.nonKOuts += outs;
        if (play === 'KL') agg.kLooking += 1;
        if (isHit(play)) agg.hits += 1;
        if (play === 'BB') agg.bb += 1;
        if (play === 'HBP') agg.hbp += 1;
        if (reachedBase(play)) agg.baserunners += 1;
    }
    if (k) {
        t.batterKs[r.batterId] = (t.batterKs[r.batterId] ?? 0) + 1;
        t.kStreak += 1;
        t.bestKStreak = Math.max(t.bestKStreak, t.kStreak);
        // Slots 2, 3, 4 are the 3-4-5 hitters.
        if (b.batIdx === 2) t.heart = 1;
        else if (t.heart > 0 && b.batIdx === 2 + t.heart) t.heart += 1;
        else t.heart = 0;
    } else {
        t.kStreak = 0;
        t.heart = 0;
    }
}
