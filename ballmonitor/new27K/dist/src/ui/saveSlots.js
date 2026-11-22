// Games in progress: one save slot per mode, so starting a Quick Game (or a
// challenge) never wipes an unfinished Season game or Career start, and the
// other way round. Older versions kept every kind in the one `game` slot;
// `migrate()` moves a season or career game found there into its own slot.
// Takes the localStorage wrapper (storage.js), so tests can pass a fake one.

export const SLOT_KEYS = { quick: 'game', season: 'game.season', career: 'game.career' };
export const SLOT_ORDER = ['quick', 'season', 'career'];

// Which slot a save belongs to, from what is kept with it.
export const slotOf = (saved) => (saved?.careerId ? 'career' : saved?.seasonGameId !== undefined ? 'season' : 'quick');

export function createSaveSlots(store) {
    const slots = {
        migrate() {
            const old = store.load(SLOT_KEYS.quick);
            if (!old) return;
            const kind = slotOf(old);
            if (kind === 'quick') return;
            // A newer game of that kind wins over the old one.
            if (!store.load(SLOT_KEYS[kind]) && !store.save(SLOT_KEYS[kind], old)) return;
            store.remove(SLOT_KEYS.quick);
        },
        // The unfinished game in a slot, or null.
        load(kind = 'quick') {
            const saved = store.load(SLOT_KEYS[kind]);
            if (!saved || !saved.state || saved.state.over) return null;
            return saved;
        },
        // Every unfinished game: [{ kind, saved }].
        all() {
            return SLOT_ORDER.map((kind) => ({ kind, saved: slots.load(kind) })).filter((s) => s.saved);
        },
        save(state, extra = {}) {
            return store.save(SLOT_KEYS[slotOf(extra)], { state, ...extra });
        },
        clear(kind) { store.remove(SLOT_KEYS[kind]); },
    };
    return slots;
}
