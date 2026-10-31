// Seedable random numbers. Every engine function takes an rng so games and
// headless sims can be replayed from a seed.

export function createRng(seed = Date.now()) {
    let s = seed >>> 0;
    const next = () => {
        // mulberry32
        s = (s + 0x6d2b79f5) >>> 0;
        let t = s;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const rng = {
        next,
        chance: (p) => next() < p,
        int: (lo, hi) => lo + Math.floor(next() * (hi - lo + 1)),
        range: (lo, hi) => lo + next() * (hi - lo),
        pick: (arr) => arr[Math.floor(next() * arr.length)],
        gauss: () => {
            let u = 0;
            while (u === 0) u = next();
            return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * next());
        },
        weighted: (items, weightOf) => {
            const total = items.reduce((sum, it) => sum + Math.max(0, weightOf(it)), 0);
            let r = next() * total;
            for (const it of items) {
                r -= Math.max(0, weightOf(it));
                if (r < 0) return it;
            }
            return items[items.length - 1];
        },
        shuffle: (arr) => {
            const a = arr.slice();
            for (let i = a.length - 1; i > 0; i--) {
                const j = Math.floor(next() * (i + 1));
                [a[i], a[j]] = [a[j], a[i]];
            }
            return a;
        },
        get seed() { return s; },
    };
    return rng;
}
