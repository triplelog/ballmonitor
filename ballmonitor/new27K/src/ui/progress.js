// The player's records: achievements earned and challenge results.

import { store } from './storage.js';

export function achievements() {
    return store.load('achievements', {});
}

// Count an achievement; returns true the first time it is earned.
export function recordAchievement(id) {
    const all = achievements();
    const now = new Date().toISOString();
    const first = !all[id];
    all[id] = { count: (all[id]?.count ?? 0) + 1, first: all[id]?.first ?? now, last: now };
    store.save('achievements', all);
    return first;
}

export function challengeRecords() {
    return store.load('challenges', {});
}

// res: { status, stars } from the challenge, or null for a started attempt.
export function recordChallenge(id, res) {
    const all = challengeRecords();
    const rec = all[id] ?? { attempts: 0, wins: 0, stars: 0 };
    if (!res) rec.attempts += 1;
    else if (res.status === 'win') {
        rec.wins += 1;
        rec.stars = Math.max(rec.stars, res.stars);
    }
    all[id] = rec;
    store.save('challenges', all);
    return rec;
}
