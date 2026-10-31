// Talking to the multiplayer server, and who this browser is.

export class MpRequestError extends Error {
    constructor(status, message, record) {
        super(message);
        this.status = status;
        this.record = record;
    }
}

let currentPlayer = '';
export const setMpPlayer = (id) => { currentPlayer = id; };

// Requests carry this browser's player id in a header (it's a secret, so
// never in a URL).
async function call(method, path, body) {
    let res;
    try {
        res = await fetch(`/api/mp${path}`, {
            method,
            headers: { 'X-Player-Id': currentPlayer, ...(body ? { 'Content-Type': 'application/json' } : {}) },
            body: body ? JSON.stringify(body) : undefined,
        });
    } catch {
        throw new MpRequestError(0, 'Can’t reach the 27K server.');
    }
    let data = {};
    try { data = await res.json(); } catch { /* not JSON: no API here */ }
    if (!res.ok) throw new MpRequestError(res.status, data.error ?? 'Multiplayer needs the 27K server (npm run serve).', data.game);
    return data;
}

export const mpApi = {
    ping: () => call('GET', '/ping'),
    list: () => call('GET', '/games').then((d) => d.games),
    create: (body) => call('POST', '/games', body).then((d) => d.game),
    join: (code, body) => call('POST', `/games/${encodeURIComponent(code)}/join`, body).then((d) => d.game),
    get: (id, { full = false } = {}) => call('GET', `/games/${encodeURIComponent(id)}${full ? '?full' : ''}`).then((d) => d.game),
    // The server decides the pitch: returns { result, game }.
    pitch: (id, body) => call('POST', `/games/${encodeURIComponent(id)}/pitch`, body),
    action: (id, body) => call('POST', `/games/${encodeURIComponent(id)}/action`, body).then((d) => d.game),
    resign: (id) => call('POST', `/games/${encodeURIComponent(id)}/resign`, {}).then((d) => d.game),
};

// A player id made up once per browser, and a display name.
export function mpIdentity(app) {
    if (!app.prefs.mpPlayerId) {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        app.prefs.mpPlayerId = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
        app.savePrefs();
    }
    setMpPlayer(app.prefs.mpPlayerId);
    return { playerId: app.prefs.mpPlayerId, name: app.prefs.mpName ?? '' };
}

export function inviteLink(code) {
    return `${location.origin}${location.pathname}#join=${code}`;
}

export function timeLeft(deadline, now = Date.now()) {
    if (!deadline) return null;
    const s = Math.max(0, Math.round((deadline - now) / 1000));
    if (s >= 86400) return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
    if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// Which seats in a game view are this player's.
export function mySeats(view) {
    return ['home', 'away'].filter((k) => view.seats[k]?.mine);
}
