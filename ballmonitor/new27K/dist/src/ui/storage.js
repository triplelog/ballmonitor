// localStorage with JSON and namespaced keys.

const PREFIX = 'new27k.';

export const store = {
    load(key, fallback = null) {
        try {
            const raw = localStorage.getItem(PREFIX + key);
            return raw ? JSON.parse(raw) : fallback;
        } catch {
            return fallback;
        }
    },
    // Returns false if the browser refused (usually: storage is full).
    save(key, value) {
        try {
            localStorage.setItem(PREFIX + key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.warn('Could not save', key, e);
            return false;
        }
    },
    remove(key) {
        localStorage.removeItem(PREFIX + key);
    },
};

// Escape text for innerHTML.
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
