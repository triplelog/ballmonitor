// The 27K server: the static game files plus the multiplayer API.
//   node tools/serve.js [port=8027]
// Settings (environment variables):
//   PORT          port (default 8027)
//   HOST          address to listen on (default: every interface, so others
//                 on your network can join; use 127.0.0.1 behind a proxy)
//   MP_DATA_DIR   where multiplayer games are kept (default data/mp)
//   ADMIN_TOKEN   enables GET /api/mp/admin/games/<id>/pitches?token=…
//   TRUST_PROXY   set to 1 behind a reverse proxy (rate limits by X-Forwarded-For)
// See docs/hosting.md.

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { networkInterfaces } from 'node:os';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createMpStore, MpError } from '../server/mp.js';

const root = fileURLToPath(new URL('..', import.meta.url));
const port = Number(process.argv[2] ?? process.env.PORT ?? 8027);
const host = process.env.HOST || undefined;
const types = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
    '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
};
const mp = createMpStore({ dir: process.env.MP_DATA_DIR || join(root, 'data', 'mp') });

// A simple per-address rate limit on the API: a bucket of 60 requests
// refilling at 20 a second.
const buckets = new Map();
function allowed(req) {
    const ip = (process.env.TRUST_PROXY && req.headers['x-forwarded-for']?.split(',')[0].trim()) || req.socket.remoteAddress;
    const t = Date.now();
    const b = buckets.get(ip) ?? { tokens: 60, at: t };
    b.tokens = Math.min(60, b.tokens + ((t - b.at) / 1000) * 20);
    b.at = t;
    buckets.set(ip, b);
    if (b.tokens < 1) return false;
    b.tokens -= 1;
    return true;
}
setInterval(() => { const cut = Date.now() - 60000; for (const [ip, b] of buckets) if (b.at < cut) buckets.delete(ip); }, 60000).unref();

function sendJSON(res, status, body) {
    res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify(body));
}

async function readBody(req) {
    let size = 0;
    const chunks = [];
    for await (const chunk of req) {
        size += chunk.length;
        if (size > 4_000_000) throw new MpError(413, 'Too large.');
        chunks.push(chunk);
    }
    if (!chunks.length) return {};
    try {
        return JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch {
        throw new MpError(400, 'Bad JSON.');
    }
}

async function api(req, res, url) {
    const parts = url.pathname.split('/').filter(Boolean).slice(2);   // after /api/mp
    const method = req.method;
    try {
        if (!allowed(req)) throw new MpError(429, 'Too many requests; slow down.');
        if (parts[0] === 'ping') return sendJSON(res, 200, { ok: true });
        if (parts[0] === 'admin') {
            const token = process.env.ADMIN_TOKEN;
            if (!token || url.searchParams.get('token') !== token) throw new MpError(403, 'Forbidden.');
            if (parts[1] === 'games' && parts[3] === 'pitches') return sendJSON(res, 200, { pitches: mp.pitchLog(parts[2]) });
            throw new MpError(404, 'Not found.');
        }
        if (parts[0] !== 'games') throw new MpError(404, 'Not found.');
        const id = parts[1];
        const action = parts[2];
        // The player id is a secret: sent in a header, never in a URL.
        const player = req.headers['x-player-id'] ?? '';
        if (!id && method === 'GET') return sendJSON(res, 200, { games: mp.list(player) });
        if (!id && method === 'POST') return sendJSON(res, 200, { game: mp.create({ ...(await readBody(req)), playerId: player }) });
        if (id && !action && method === 'GET') return sendJSON(res, 200, { game: mp.get(id, player, { league: url.searchParams.has('full') }) });
        if (action === 'join' && method === 'POST') return sendJSON(res, 200, { game: mp.join(id, { ...(await readBody(req)), playerId: player }) });
        if (action === 'pitch' && method === 'POST') return sendJSON(res, 200, mp.pitch(id, { ...(await readBody(req)), playerId: player }));
        if (action === 'action' && method === 'POST') return sendJSON(res, 200, { game: mp.action(id, { ...(await readBody(req)), playerId: player }) });
        if (action === 'resign' && method === 'POST') return sendJSON(res, 200, { game: mp.resign(id, { ...(await readBody(req)), playerId: player }) });
        throw new MpError(404, 'Not found.');
    } catch (e) {
        if (e instanceof MpError) return sendJSON(res, e.status, { error: e.message, ...e.extra });
        console.error(e);
        return sendJSON(res, 500, { error: 'Server error.' });
    }
}

createServer(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    if (url.pathname.startsWith('/api/mp/')) return api(req, res, url);
    const path = decodeURIComponent(url.pathname);
    const file = normalize(join(root, path.endsWith('/') ? path + 'index.html' : path));
    if (!file.startsWith(root) || file.startsWith(join(root, 'data'))) {
        res.writeHead(403).end();
        return;
    }
    try {
        const body = await readFile(file);
        res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' });
        res.end(body);
    } catch {
        res.writeHead(404).end('Not found');
    }
}).listen(port, host, () => {
    console.log(`27K at http://localhost:${port}/`);
    for (const list of Object.values(networkInterfaces())) {
        for (const a of list ?? []) if (a.family === 'IPv4' && !a.internal) console.log(`   on your network: http://${a.address}:${port}/`);
    }
});
