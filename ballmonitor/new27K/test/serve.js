// The server itself, over real HTTP: which files it serves, that a bad
// address can't crash it, and which other sites may use its multiplayer.
//   node test/serve.js

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const dir = mkdtempSync(join(tmpdir(), '27k-serve-'));
const port = 18000 + Math.floor(Math.random() * 2000);
const base = `http://127.0.0.1:${port}`;
const GOOD = 'https://ballmonitor.com';
const server = spawn(process.execPath, [join(root, 'tools/serve.js')], {
    env: { ...process.env, PORT: String(port), HOST: '127.0.0.1', MP_DATA_DIR: dir, ALLOW_ORIGINS: `${GOOD}, https://html-classic.itch.zone/` },
    stdio: ['ignore', 'pipe', 'inherit'],
});
await new Promise((resolve) => server.stdout.once('data', resolve));

let failures = 0;
const check = (name, cond, detail = '') => {
    if (cond) console.log(`ok   ${name}`);
    else { failures += 1; console.error(`FAIL ${name} ${detail}`); }
};
const status = async (path, opts) => (await fetch(base + path, opts)).status;

try {
    check('the page and its files are served', await status('/') === 200 && await status('/src/ui/app.js') === 200 && await status('/css/style.css') === 200 && await status('/favicon.svg') === 200);
    check('the formula library is served', await status('/node_modules/mathzetta/build/esm/core.js') === 200);
    const hidden = ['/server/mp.js', '/tools/serve.js', '/package.json', '/data/mp/x.json', '/Data/mp/x.json', '/.git-27k-history/HEAD', '/..%2f..%2fpyproject.toml', '/test/rules.js'];
    const got = await Promise.all(hidden.map((p) => status(p)));
    check('nothing else in the folder is served', got.every((s) => s === 404), got.join(' '));
    check('a malformed address gets 400', await status('/%') === 400);
    check('...and the server is still up', await status('/api/mp/ping') === 200);

    const pre = await fetch(`${base}/api/mp/games`, { method: 'OPTIONS', headers: { Origin: GOOD, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type,x-player-id' } });
    check('a listed site may call the API (preflight)', pre.status === 204 && pre.headers.get('access-control-allow-origin') === GOOD && /x-player-id/i.test(pre.headers.get('access-control-allow-headers') ?? ''));
    const itch = await fetch(`${base}/api/mp/ping`, { headers: { Origin: 'https://html-classic.itch.zone' } });
    check('a listed site written with a trailing slash still matches', itch.headers.get('access-control-allow-origin') === 'https://html-classic.itch.zone');
    const other = await fetch(`${base}/api/mp/ping`, { headers: { Origin: 'https://example.com' } });
    check('an unlisted site gets no permission', other.headers.get('access-control-allow-origin') === null);

    // A whole request as another site's page would make it.
    const player = 'a'.repeat(32);
    const made = await fetch(`${base}/api/mp/games`, { method: 'POST', headers: { Origin: GOOD, 'Content-Type': 'application/json', 'X-Player-Id': player }, body: JSON.stringify({ name: 'Ann', level: 'youth' }) });
    const body = await made.json();
    check('a game can be created from a listed site', made.status === 200 && /^[A-Z2-9]{6}$/.test(body.game?.code ?? ''), JSON.stringify(body).slice(0, 120));
} finally {
    server.kill();
    rmSync(dir, { recursive: true, force: true });
}
console.log(failures ? `\n${failures} failed` : '\nall server checks passed');
if (failures) process.exitCode = 1;
