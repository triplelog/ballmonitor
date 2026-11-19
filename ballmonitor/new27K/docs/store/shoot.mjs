// Store material made from the game itself, in headless Chrome (no dependencies: Node 22's
// WebSocket talks to Chrome's DevTools protocol).
//
//   node docs/store/shoot.mjs career   → 07-career.png: a career three seasons into college
//   node docs/store/shoot.mjs gif      → at-bat.gif, at-bat-cover.gif (630 × 500) and at-bat.mp4: one
//                                        at-bat of three or more pitches that ends in a strikeout
//
// It starts the game's own server on a spare port (tools/serve.js, a throwaway games folder) and
// Chrome with a fresh profile, so nothing touches your saves. Needs Google Chrome; the GIF needs
// ffmpeg. CHROME=/path/to/chrome to use another browser.

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createFormulas } from '../../src/engine/formulas.js';
import { createCareer, startCareerSeason, careerStep, finishSeason, choose, train, learnable, learnPitch, trainCost, markStart } from '../../src/engine/career.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const GAME = join(HERE, '..', '..');
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const W = 1280, H = 800;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const what = process.argv[2];
if (!['career', 'gif'].includes(what)) {
    console.error('usage: node docs/store/shoot.mjs career|gif');
    process.exit(2);
}

// ── the game server and Chrome ────────────────────────────────────────────────
const tmp = mkdtempSync(join(tmpdir(), '27k-shoot-'));
const port = 8100 + Math.floor(Math.random() * 800);
const debugPort = port + 1000;
const procs = [];
async function done(code = 0) {
    for (const p of procs) p.kill();
    await sleep(500);   // let Chrome let go of its profile
    rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    process.exit(code);
}
process.on('SIGINT', () => done(130));

procs.push(spawn(process.execPath, ['tools/serve.js'], {
    cwd: GAME, stdio: 'ignore',
    env: { ...process.env, PORT: String(port), HOST: '127.0.0.1', MP_DATA_DIR: join(tmp, 'mp') },
}));
procs.push(spawn(CHROME, ['--headless=new', `--remote-debugging-port=${debugPort}`, `--user-data-dir=${join(tmp, 'profile')}`,
    `--window-size=${W},${H}`, '--hide-scrollbars', '--force-device-scale-factor=1', '--mute-audio', '--no-first-run',
    'about:blank'], { stdio: 'ignore' }));

async function waitFor(url, tries = 100) {
    for (let i = 0; i < tries; i++) {
        try { const r = await fetch(url); if (r.ok) return r; } catch { /* not up yet */ }
        await sleep(100);
    }
    throw new Error(`${url} never answered`);
}

// A tiny DevTools-protocol client: send(method, params) and on(event, fn).
async function connect() {
    await waitFor(`http://127.0.0.1:${port}/`);
    await waitFor(`http://127.0.0.1:${debugPort}/json/version`);
    const target = await (await fetch(`http://127.0.0.1:${debugPort}/json/new?about:blank`, { method: 'PUT' })).json();
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
    let id = 0;
    const pending = new Map(), handlers = new Map();
    ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.id && pending.has(msg.id)) {
            const { resolve, reject } = pending.get(msg.id);
            pending.delete(msg.id);
            msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
        } else if (msg.method) (handlers.get(msg.method) ?? []).forEach((f) => f(msg.params));
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => {
        const n = ++id;
        pending.set(n, { resolve, reject });
        ws.send(JSON.stringify({ id: n, method, params }));
    });
    const on = (event, fn) => handlers.set(event, [...(handlers.get(event) ?? []), fn]);
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
    return { send, on };
}

let cdp;
async function evaluate(expression) {
    const r = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
}
async function open(path) {
    const loaded = new Promise((r) => cdp.on('Page.loadEventFired', r));
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${port}${path}` });
    await loaded;
    await sleep(800);
}
async function until(expression, ms = 30000) {
    for (let t = 0; t < ms; t += 100) {
        if (await evaluate(expression)) return true;
        await sleep(100);
    }
    throw new Error(`timed out waiting for ${expression}`);
}
const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
async function screenshot(file) {
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(file, Buffer.from(data, 'base64'));
    console.log(`wrote ${file}`);
}
// Before the game loads: no welcome help, an easier lineup, the clock starting on Pitch.
const PREFS = { seenHelp: true, difficulty: 1, innings: 9, userHome: true, clockMode: 'press', showOdds: false, sound: false };
async function freshGame() {
    await open('/index.html');
    await evaluate(`localStorage.setItem('new27k.prefs', ${JSON.stringify(JSON.stringify(PREFS))})`);
    await open('/index.html');
}

// ── 07-career.png ────────────────────────────────────────────────────────────
// The career test's pitcher (test/career.js), simmed through high school and two college seasons,
// then eight starts into his third: a page with a record, a ranked team and a full outings list.
function simCareer() {
    const F = createFormulas();
    const career = createCareer({ first: 'Sam', last: 'Hurler', throws: 'R', style: 'power', state: 'OH', city: 'Dayton', seed: 4242, play: 'none' });
    const spend = () => {
        for (let guard = 0; guard < 400; guard++) {
            const can = learnable(career);
            if (can.length && career.pitcher.pitches.length < 4 && learnPitch(career, F, can[0]).ok) continue;
            const p = career.pitcher.pitches;
            let best = null;
            p.forEach((x, i) => ['velo', 'control', 'move'].forEach((f) => { if (!best || x[f] < p[best.pitch][best.field]) best = { pitch: i, field: f }; }));
            if (career.xp < trainCost(career, F, best)) break;
            train(career, F, best);
        }
    };
    while (career.history.filter((h) => h.level === 'college').length < 2) {
        if (['decision', 'collegeDecision', 'draft', 'freeAgency'].includes(career.stage)) {
            choose(career, career.stage === 'decision' ? { college: career.offers.colleges[0].team } : {});
            continue;
        }
        startCareerSeason(career, F);
        let steps = 0;
        while (!careerStep(career, F, 'end').done && steps++ < 50000);
        finishSeason(career, F);
        spend();
        process.stdout.write(`  simmed ${career.history.at(-1).year} (${career.history.at(-1).level})\n`);
    }
    startCareerSeason(career, F);
    for (let starts = 0; starts < 8;) {
        const r = careerStep(career, F, 'start');
        if (r.seasonOver) break;
        if (r.start) {
            if (starts === 7) break;   // leave the next start waiting on the page
            markStart(career, r.start);
            starts += 1;
        }
    }
    career.settings.play = 'all';   // the page as a player sees it: "Every start" (simmed here only to fill it)
    career.updatedAt = Date.now();
    return career;
}

async function shootCareer() {
    console.log('Simming a career (about half a minute)…');
    const career = simCareer();
    await freshGame();
    await evaluate(`new Promise((resolve, reject) => {
        const req = indexedDB.open('new27k', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('careers', { keyPath: 'id' });
        req.onerror = () => reject(req.error);
        req.onsuccess = () => {
            const tx = req.result.transaction('careers', 'readwrite');
            tx.objectStore('careers').put(${JSON.stringify(career)});
            tx.oncomplete = () => resolve(true);
            tx.onerror = () => reject(tx.error);
        };
    })`);
    await open('/index.html');
    await click('[data-go="careers"]');
    await until(`!!document.querySelector('[data-open="${career.id}"]')`);
    await click(`[data-open="${career.id}"]`);
    await sleep(1500);
    await screenshot(join(HERE, '07-career.png'));
}

// ── at-bat.gif ─────────────────────────────────────────────────────────────────
// Quick Game, pitching to batters until one strikes out; the frames of that at-bat (Chrome's
// screencast) become the GIF. The aim is the zone's position plus a spot near an edge.
const PITCH = `(async (pitchIdx, ox, oy) => {
    const s = app27k.screen;
    document.querySelector('[data-pitch="' + pitchIdx + '"]')?.click();
    await new Promise((r) => setTimeout(r, 350));
    document.querySelector('[data-act="pitch"]').click();
    await new Promise((r) => setTimeout(r, 700 + Math.random() * 500));
    const p = s.toPage(s.zone.x + ox, s.zone.y + oy);
    return p;
})`;
// k: strikeouts by the pitcher who was on the mound when the at-bat began (window.__pid)
const STATE = `(() => { const s = app27k.screen; if (!s) return null; const g = s.game;
    if (g.isUserPitching() && !window.__pid) window.__pid = g.pitcher().id;
    return { mode: s.ui.mode, mine: g.isUserPitching(), over: g.state.over, k: window.__pid ? g.pitchBox(window.__pid).k : 0,
        pa: g.state.balls + '-' + g.state.strikes, pitches: (s.ui.mode === 'ready' && g.isUserPitching()) ? document.querySelectorAll('[data-pitch]').length : 0 }; })()`;

async function shootGif() {
    await freshGame();
    await click('[data-go="quick"]');
    await sleep(400);
    await click('[data-act="next"]');
    await sleep(400);
    await click('[data-act="play"]');
    await until(`(${STATE})?.mine && (${STATE}).mode === 'ready'`);

    const frames = [];
    let recording = false;
    cdp.on('Page.screencastFrame', (f) => {
        cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId });
        if (recording) frames.push({ data: f.data, t: f.metadata.timestamp });
    });
    await cdp.send('Page.startScreencast', { format: 'png', everyNthFrame: 1, maxWidth: W, maxHeight: H });

    const corners = [[-5.5, -7], [5.5, -7], [-5.5, 7.5], [5.5, 7.5], [0, -8.5]];
    for (let pa = 1; pa <= 40; pa++) {
        frames.length = 0;
        recording = true;
        await evaluate('window.__pid = null');
        const k0 = (await evaluate(STATE)).k;
        let ended = false, thrown = 0;
        while (!ended) {
            const st = await evaluate(STATE);
            const [ox, oy] = corners[Math.floor(Math.random() * corners.length)];
            const pick = Math.floor(Math.random() * Math.max(1, st.pitches));
            const at = await evaluate(`${PITCH}(${pick}, ${ox}, ${oy})`);
            // ease the aim marker toward the spot, then throw
            for (let i = 1; i <= 6; i++) {
                await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: at.x + (6 - i) * 9, y: at.y - (6 - i) * 6 });
                await sleep(60);
            }
            const now = await evaluate(`(() => { const s = app27k.screen; const p = s.toPage(s.zone.x + ${ox}, s.zone.y + ${oy}); return p; })()`);
            await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: now.x, y: now.y, button: 'left', clickCount: 1 });
            await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: now.x, y: now.y, button: 'left', clickCount: 1 });
            // wait for the pitch to play out, noting when it landed (its call's banner shows from then)
            let landedAt = null;
            for (let t = 0; t < 60000; t += 50) {
                const w = await evaluate(`(() => { const s = ${STATE}; const c = app27k.screen.ui.current;
                    return { landed: !!(c && c.landed), done: !!(s && (s.over || (s.mine && s.mode === 'ready') || !s.mine)) }; })()`);
                if (w.landed && landedAt === null) landedAt = Date.now() / 1000;
                if (w.done) break;
                await sleep(50);
            }
            thrown += 1;
            const after = await evaluate(STATE);
            ended = after.pa === '0-0' || after.over || !after.mine;
            if (ended && after.k > k0 && thrown >= 3) {   // a strikeout worth watching: three pitches or more
                recording = false;
                await cdp.send('Page.stopScreencast');
                // end on the strikeout banner (not the next batter walking up)
                const end = (landedAt ?? Date.now() / 1000) + 2.4;
                const kept = frames.filter((f) => f.t <= end);
                console.log(`strikeout on batter ${pa}: ${kept.length} frames`);
                return makeGif(kept);
            }
            if (ended && (after.over || !after.mine)) {
                await until(`(${STATE})?.mine && (${STATE}).mode === 'ready'`, 120000);
            }
        }
        console.log(`  batter ${pa}: no strikeout in 3+ pitches, next`);
    }
    throw new Error('no strikeout in 40 batters');
}

async function makeGif(frames) {
    const dir = join(tmp, 'frames');
    mkdirSync(dir);
    // frames come when the page paints: give each its real duration (concat list), 15 fps out
    const list = [];
    frames.forEach((f, i) => {
        const name = `f${String(i).padStart(5, '0')}.png`;
        writeFileSync(join(dir, name), Buffer.from(f.data, 'base64'));
        const dur = i + 1 < frames.length ? Math.max(0.01, frames[i + 1].t - f.t) : 1.5;
        list.push(`file '${name}'`, `duration ${dur.toFixed(3)}`);
    });
    list.push(`file 'f${String(frames.length - 1).padStart(5, '0')}.png'`);
    writeFileSync(join(dir, 'list.txt'), list.join('\n'));
    const run = (args) => new Promise((resolve, reject) => {
        const p = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { cwd: dir, stdio: 'inherit' });
        p.on('exit', (c) => (c ? reject(new Error(`ffmpeg exited ${c}`)) : resolve()));
    });
    const gif = join(HERE, 'at-bat.gif'), cover = join(HERE, 'at-bat-cover.gif'), mp4 = join(HERE, 'at-bat.mp4');
    const palette = 'split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle';
    // the whole screen (for the page body), and the pitch panel + field at itch's cover size, 630 × 500
    await run(['-f', 'concat', '-i', 'list.txt', '-vf', `fps=15,scale=800:-1:flags=lanczos,${palette}`, '-loop', '0', gif]);
    await run(['-f', 'concat', '-i', 'list.txt', '-vf', `fps=15,crop=916:727:8:0,scale=630:500:flags=lanczos,${palette}`, '-loop', '0', cover]);
    await run(['-f', 'concat', '-i', 'list.txt', '-vf', 'fps=30,scale=1280:-2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', mp4]);
    console.log(`wrote ${gif}, ${cover} and ${mp4} (${readdirSync(dir).length - 1} frames)`);
}

try {
    cdp = await connect();
    await (what === 'career' ? shootCareer() : shootGif());
    done(0);
} catch (e) {
    console.error(e);
    done(1);
}
