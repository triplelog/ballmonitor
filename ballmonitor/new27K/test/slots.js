// Saved games: one slot per mode, so a new Quick Game (or challenge) never
// replaces an unfinished Season game or Career start, and old saves (one
// shared `game` slot) still load, moved into their own slot.
//   node test/slots.js

import { createSaveSlots, SLOT_KEYS } from '../src/ui/saveSlots.js';

let failures = 0;
const check = (name, cond, detail = '') => {
    if (cond) console.log(`ok   ${name}`);
    else { failures += 1; console.error(`FAIL ${name} ${detail}`); }
};

// The storage.js interface over a Map (JSON round trip, like localStorage).
function fakeStore(initial = {}) {
    const m = new Map(Object.entries(initial).map(([k, v]) => [k, JSON.stringify(v)]));
    return {
        m,
        load: (k, fallback = null) => (m.has(k) ? JSON.parse(m.get(k)) : fallback),
        save: (k, v) => { m.set(k, JSON.stringify(v)); return true; },
        remove: (k) => { m.delete(k); },
    };
}
const state = (inning, over = false) => ({ inning, half: 'top', over });

// Each mode keeps its own game.
{
    const store = fakeStore();
    const slots = createSaveSlots(store);
    slots.save(state(3), { seasonGameId: 0 });
    slots.save(state(5), { careerId: 'c1', seasonGameId: 7 });
    slots.save(state(1), { tracker: {} });
    check('a quick game doesn’t replace the season game or the career start',
        slots.load('season')?.state.inning === 3 && slots.load('career')?.state.inning === 5 && slots.load('quick')?.state.inning === 1);
    check('season game id 0 counts as a season game', slots.load('season')?.seasonGameId === 0);
    check('all() lists every unfinished game in menu order', slots.all().map((s) => s.kind).join() === 'quick,season,career');
    slots.clear('quick');
    check('clearing one slot leaves the others', !slots.load('quick') && slots.load('season') && slots.load('career'));
    slots.save(state(9, true), { seasonGameId: 4 });
    check('a finished game isn’t offered to continue', slots.load('season') === null);
}

// Old saves: everything was in `game`.
for (const [kind, extra] of [['season', { seasonGameId: 2 }], ['career', { careerId: 'abc', seasonGameId: 11 }], ['quick', { tracker: {} }]]) {
    const store = fakeStore({ game: { state: state(6), ...extra } });
    const slots = createSaveSlots(store);
    slots.migrate();
    check(`an old ${kind} save loads from its own slot`, slots.load(kind)?.state.inning === 6 && slots.all().length === 1, JSON.stringify([...store.m.keys()]));
    slots.migrate();
    check(`...and migrating twice changes nothing (${kind})`, slots.all().length === 1 && store.m.has(SLOT_KEYS[kind]));
}

// An old season save never overwrites a newer one already in the season slot.
{
    const store = fakeStore({ game: { state: state(2), seasonGameId: 1 }, 'game.season': { state: state(8), seasonGameId: 5 } });
    const slots = createSaveSlots(store);
    slots.migrate();
    check('a newer season save wins over the old shared one', slots.load('season')?.state.inning === 8 && !store.m.has('game'));
}

console.log(failures ? `\n${failures} failed` : '\nall save slot checks passed');
if (failures) process.exitCode = 1;
