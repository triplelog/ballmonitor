// Careers are kept in IndexedDB: a career carries a whole season (over a
// megabyte at the college level), more than localStorage comfortably holds.

const DB = 'new27k';
const STORE = 'careers';
let dbPromise = null;

function open() {
    dbPromise ??= new Promise((resolve, reject) => {
        const req = indexedDB.open(DB, 1);
        req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
    return dbPromise;
}

function run(mode, fn) {
    return open().then((db) => new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, mode);
        const req = fn(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(req?.result);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
    }));
}

export const careerStore = {
    list: () => run('readonly', (s) => s.getAll()),
    get: (id) => run('readonly', (s) => s.get(id)),
    put: (career) => run('readwrite', (s) => s.put(career)),
    remove: (id) => run('readwrite', (s) => s.delete(id)),
};

// What to tell the player when IndexedDB is blocked (private windows in some
// browsers, blocked site data, a game frame without storage).
export const CAREER_STORAGE_ERROR = 'Careers are saved in this browser’s storage (IndexedDB), and this browser won’t allow it here: private browsing or blocked site data can do that.';
