// Multiplayer lobby: start or join a game, and see every game you're in,
// with whose turn it is and how long is left.

import { LEVELS, LEVEL_ORDER } from '../engine/levels.js';
import { createFormulas } from '../engine/formulas.js';
import { Game, ordinal } from '../engine/game.js';
import { mpApi, mpIdentity, inviteLink, timeLeft, mySeats } from './mpClient.js';
import { renderGame } from './gameScreen.js';
import { renderLineup, rating } from './screens.js';
import { battingSide } from '../engine/pitch.js';
import { PITCH_TYPES } from '../engine/data.js';
import { playerName, shortName, teamName } from '../engine/league.js';
import { rates, statObj } from '../engine/pitchStats.js';
import { esc } from './storage.js';

const TIME_LIMITS = [
    [0, 'No limit'], [120, '2 minutes'], [300, '5 minutes'], [900, '15 minutes'],
    [3600, '1 hour'], [8 * 3600, '8 hours'], [86400, '1 day'], [3 * 86400, '3 days'],
];

let lastMyTurn = new Set();   // for "your turn" notifications across visits

export function renderMultiplayer(app, args = {}) {
    mpIdentity(app);   // makes sure this browser has a player id
    let games = null;
    let error = null;
    let busy = false;
    let level = app.prefs.mpLevel ?? 'pro';
    let timer = 0;
    let ticker = 0;

    const draw = () => {
        const name = app.prefs.mpName ?? '';
        const L = LEVELS[level];
        const customCount = Object.keys(app.F.overrides()).length;
        app.root.innerHTML = `
        <div class="page wide mp">
            <div class="page-head"><button data-act="back">← Menu</button><h1>Multiplayer</h1>
                ${'Notification' in window && Notification.permission === 'default' ? '<button class="small" data-act="notify">Notify me when it’s my turn</button>' : ''}</div>
            ${error ? `<div class="panel mp-error">${esc(error)}</div>` : ''}
            <div class="cols-2">
                <div>
                    <div class="panel">
                        <div class="card-head"><h3>Your games</h3><span class="muted" style="font-size:12px">updates every few seconds</span></div>
                        <div class="mp-games">${games === null ? '<div class="muted">Loading…</div>' : games.length ? games.map(gameCard).join('') : '<div class="muted">No games yet. Start one, or join with a code.</div>'}</div>
                    </div>
                </div>
                <div>
                    <div class="panel">
                        <h3>Your name</h3>
                        <input id="mp-name" value="${esc(name)}" placeholder="Shown to your opponent" maxlength="24" style="width:100%">
                    </div>
                    <div class="panel" style="margin-top:10px">
                        <h3>Join a game</h3>
                        <div style="display:flex;gap:6px"><input id="mp-code" placeholder="Code, e.g. K7Q2XM" value="${esc(args.code ?? '')}" style="flex:1;text-transform:uppercase"><button class="primary" data-act="join">Join</button></div>
                    </div>
                    <div class="panel" style="margin-top:10px">
                        <h3>New game</h3>
                        <div class="form-grid" style="grid-template-columns: 120px 1fr">
                            <label>Level</label>
                            <select id="mp-level">${LEVEL_ORDER.map((id) => `<option value="${id}" ${id === level ? 'selected' : ''}>${LEVELS[id].icon} ${LEVELS[id].name}</option>`).join('')}</select>
                            <label>Innings</label>
                            <select id="mp-inn">${[1, 2, 3, 4, 5, 6, 7, 9].map((n) => `<option ${n === L.innings ? 'selected' : ''}>${n}</option>`).join('')}</select>
                            <label>Time per half</label>
                            <select id="mp-time">${TIME_LIMITS.map(([s, label]) => `<option value="${s}" ${s === (app.prefs.mpTime ?? 0) ? 'selected' : ''}>${label}</option>`).join('')}</select>
                            <div class="hint">Run out of time and the computer pitches the rest of your half.</div>
                            <label>You are</label>
                            <select id="mp-side"><option value="random">Random</option><option value="home">Home (pitch the tops)</option><option value="away">Away (pitch the bottoms)</option></select>
                            <label>Rules</label>
                            <select id="mp-rules"><option value="default">Standard formulas</option>${customCount ? `<option value="mine">My custom formulas (${customCount})</option>` : ''}</select>
                            <label></label>
                            <label class="toggle"><input type="checkbox" id="mp-manage" checked> Lineups and pinch hitters: before your team bats, set your lineup card or make substitutions</label>
                            <label></label>
                            <label class="toggle"><input type="checkbox" id="mp-both"> Both players on this device (take turns at one screen)</label>
                        </div>
                        <div class="row-actions"><button class="primary big" data-act="create" ${busy ? 'disabled' : ''}>${busy ? 'Setting up…' : 'Create game'}</button></div>
                    </div>
                    <p class="muted" style="font-size:12px;line-height:1.5">Both players need to reach this same 27K server: on your network, share the address the server prints when it starts (not “localhost”). The home player pitches the top of every inning and the away player the bottom; each side's hitters bat against the other player's pitching.</p>
                </div>
            </div>
        </div>`;
    };

    function gameCard(g) {
        const opp = (k) => g.seats[k] ?? 'waiting…';
        const both = g.mine.length === 2;
        const half = `${g.half === 'top' ? 'top' : 'bottom'} of the ${ordinal(g.inning)}`;
        let status;
        let actions = '';
        if (g.status === 'waiting') {
            status = `Waiting for an opponent. Code <b class="mp-code">${g.code}</b>`;
            actions = `<button class="small" data-copy="${g.code}">Copy invite link</button><button class="small" data-resign="${g.id}">Cancel</button>`;
        } else if (g.status === 'done') {
            const won = g.mine.includes(g.result.winner);
            status = both ? `Final${g.resigned ? ' (resigned)' : ''}` : `<b class="${won ? 'win' : 'loss'}">${won ? 'You won' : 'You lost'}</b>${g.resigned ? ` (${g.mine.includes(g.resigned) ? 'you resigned' : 'they resigned'})` : ''}`;
            actions = `<button class="small" data-open="${g.id}">Box score</button>`;
        } else if (g.myTurn && g.turn.phase === 'manage') {
            status = `<b class="mp-turn">Your turn</b>: set up your hitters before they bat in the ${half}${g.turn.deadline ? ` · <span class="mp-clock" data-deadline="${g.turn.deadline}">${timeLeft(g.turn.deadline)}</span> left` : ''}`;
            actions = `<button class="primary" data-open="${g.id}">Set lineup</button><button class="small" data-resign="${g.id}">Resign</button>`;
        } else if (g.myTurn) {
            status = `<b class="mp-turn">Your turn</b>: pitch the ${half}${g.turn.deadline ? ` · <span class="mp-clock" data-deadline="${g.turn.deadline}">${timeLeft(g.turn.deadline)}</span> left` : ''}`;
            actions = `<button class="primary" data-open="${g.id}">Pitch</button><button class="small" data-resign="${g.id}">Resign</button>`;
        } else {
            status = `${esc(g.seats[g.turn.key] ?? 'Opponent')} ${g.turn.phase === 'manage' ? 'is setting up their hitters for the' : 'is pitching the'} ${half}${g.turn.deadline ? ` · <span class="mp-clock" data-deadline="${g.turn.deadline}">${timeLeft(g.turn.deadline)}</span> left` : ''}`;
            actions = `<button data-open="${g.id}">Watch</button><button class="small" data-resign="${g.id}">Resign</button>`;
        }
        const t = g.teams;
        return `<div class="mp-game ${g.myTurn ? 'mine' : ''}">
            <div class="mp-score">
                <div><span class="swatch" style="background:${t.away.color}"></span>${esc(t.away.abbr)} <b>${g.score.away}</b> <span class="muted">${esc(opp('away'))}${g.mine.includes('away') && !both ? ' (you)' : ''}</span></div>
                <div><span class="swatch" style="background:${t.home.color}"></span>${esc(t.home.abbr)} <b>${g.score.home}</b> <span class="muted">${esc(opp('home'))}${g.mine.includes('home') && !both ? ' (you)' : ''}</span></div>
            </div>
            <div class="mp-status">${status}<div class="muted" style="font-size:11px">${LEVELS[g.level].name} · ${g.innings} inn${g.timeLimit ? ` · ${TIME_LIMITS.find(([s]) => s === g.timeLimit)?.[1] ?? `${g.timeLimit}s`} per half` : ''}${both ? ' · both players here' : ''}${Object.values(g.timeouts).some(Boolean) ? ` · ${Object.values(g.timeouts).reduce((a, b) => a + b, 0)} timed-out half` : ''}</div></div>
            <div class="mp-actions">${actions}</div>
        </div>`;
    }

    async function refresh() {
        try {
            games = await mpApi.list();
            error = null;
            const nowMine = new Set(games.filter((g) => g.myTurn).map((g) => g.id));
            for (const id of nowMine) {
                if (!lastMyTurn.has(id) && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
                    new Notification('27K: your turn to pitch', { body: 'Your opponent finished their half.' });
                }
            }
            lastMyTurn = nowMine;
            document.title = nowMine.size ? `(${nowMine.size}) Your turn · 27K` : '27K: a pitching game';
        } catch (e) {
            error = e.message;
            games = games ?? [];
        }
        const focus = document.activeElement?.id;
        const vals = Object.fromEntries(['mp-name', 'mp-code'].map((id) => [id, app.root.querySelector('#' + id)?.value]));
        draw();
        for (const [id, v] of Object.entries(vals)) if (v !== undefined) app.root.querySelector('#' + id).value = v;
        if (focus) app.root.querySelector('#' + focus)?.focus();
        timer = setTimeout(refresh, 4000);
    }

    const needName = () => {
        const name = app.root.querySelector('#mp-name').value.trim();
        if (!name) {
            alert('Enter your name first.');
            app.root.querySelector('#mp-name').focus();
            return null;
        }
        app.prefs.mpName = name;
        app.savePrefs();
        return name;
    };

    const onClick = async (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.open) return app.go('mpGame', { id: btn.dataset.open });
        if (btn.dataset.copy) {
            navigator.clipboard?.writeText(inviteLink(btn.dataset.copy));
            btn.textContent = 'Copied!';
            return;
        }
        if (btn.dataset.resign) {
            if (!confirm('Resign (or cancel) this game? Your opponent gets the win.')) return;
            try { await mpApi.resign(btn.dataset.resign); } catch (err) { alert(err.message); }
            return refreshNow();
        }
        switch (btn.dataset.act) {
            case 'back': app.go('menu'); break;
            case 'notify': Notification.requestPermission().then(draw); break;
            case 'join': {
                const name = needName();
                const code = app.root.querySelector('#mp-code').value.trim();
                if (!name || !code) return;
                try {
                    const rec = await mpApi.join(code, { name });
                    app.go('mpGame', { id: rec.id });
                } catch (err) { alert(err.message); }
                break;
            }
            case 'create': {
                const name = needName();
                if (!name) return;
                const $ = (id) => app.root.querySelector('#' + id);
                app.prefs.mpLevel = level;
                app.prefs.mpTime = Number($('mp-time').value);
                app.savePrefs();
                busy = true;
                btn.disabled = true;
                btn.textContent = 'Setting up…';
                try {
                    const rec = await mpApi.create({
                        name, level,
                        manage: $('mp-manage').checked,
                        innings: Number($('mp-inn').value),
                        timeLimit: Number($('mp-time').value) || null,
                        side: $('mp-side').value,
                        both: $('mp-both').checked,
                        formulas: $('mp-rules').value === 'mine' ? app.F.overrides() : {},
                        difficulty: app.prefs.difficulty,
                    });
                    busy = false;
                    if (rec.status === 'active') app.go('mpGame', { id: rec.id });
                    else {
                        navigator.clipboard?.writeText(inviteLink(rec.code)).catch(() => {});
                        refreshNow();
                    }
                } catch (err) {
                    busy = false;
                    alert(err.message);
                    draw();
                }
                break;
            }
        }
    };
    const onChange = (e) => {
        if (e.target.id === 'mp-level') {
            level = e.target.value;
            const inn = app.root.querySelector('#mp-inn');
            inn.value = String(LEVELS[level].innings);
        }
        if (e.target.id === 'mp-name') {
            app.prefs.mpName = e.target.value.trim();
            app.savePrefs();
        }
    };
    const refreshNow = () => { clearTimeout(timer); refresh(); };

    app.root.addEventListener('click', onClick);
    app.root.addEventListener('change', onChange);
    // Count the clocks down between refreshes.
    ticker = setInterval(() => {
        for (const el of app.root.querySelectorAll('.mp-clock')) el.textContent = timeLeft(Number(el.dataset.deadline));
    }, 1000);
    draw();
    refresh();
    return () => {
        clearTimeout(timer);
        clearInterval(ticker);
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('change', onChange);
    };
}

// Open a multiplayer game: manage your hitters, pitch your half, or watch.
export function renderMpGame(app, args) {
    mpIdentity(app);
    let cleanup = null;
    let cancelled = false;
    app.root.innerHTML = '<div class="page"><p class="muted">Loading game…</p></div>';
    mpApi.get(args.id, { full: true }).then((rec) => {
        if (cancelled) return;
        const seats = mySeats(rec);
        const state = rec.state;
        const mine = rec.status === 'active' && rec.turn && seats.includes(rec.turn.key);
        if (mine && rec.turn.phase === 'manage') {
            cleanup = renderMpManage(app, rec);
            return;
        }
        const F = createFormulas(rec.settings.formulas ?? {});
        const fielding = state.half === 'top' ? 'home' : 'away';
        const batting = state.half === 'top' ? 'away' : 'home';
        const myTurn = mine && rec.turn.phase === 'pitch';
        // The engine's "user" is the side this browser is pitching for (or,
        // while watching, the side whose hitters are batting).
        const key = myTurn ? fielding : seats.includes(batting) ? batting : seats[0] ?? null;
        state.userTeamId = key ? state.sides[key].teamId : null;
        const game = new Game(rec.league, F, state);
        cleanup = renderGame(app, { game, mp: { record: rec, myTurn, seats } });
    }).catch((e) => {
        if (cancelled) return;
        app.root.innerHTML = `<div class="page"><div class="panel"><p>${esc(e.message)}</p><button data-act="lobby">Back to multiplayer</button></div></div>`;
        app.root.querySelector('[data-act="lobby"]').onclick = () => app.go('multiplayer');
    });
    return () => {
        cancelled = true;
        if (cleanup) cleanup();
    };
}

// How a batter has hit the pitch types this pitcher throws.
function vsArsenal(league, batterId, pitcher) {
    const mine = league.pitchStats?.[batterId] ?? {};
    const sum = { n: 0, sw: 0, wh: 0, pa: 0, ab: 0, h: 0, tb: 0, bb: 0, hbp: 0, sf: 0, k: 0 };
    for (const p of pitcher.pitches) {
        const s = statObj(mine[p.type]);
        for (const k of Object.keys(sum)) sum[k] += s[k] ?? 0;
    }
    return rates(sum);
}

// Before your team bats: the lineup card (before its first at-bat), then
// substitutions. Moves go to the server, which checks them.
function renderMpManage(app, rec) {
    const key = rec.turn.key;
    const F = createFormulas(rec.settings.formulas ?? {});
    const state = rec.state;
    state.userTeamId = state.sides[key].teamId;
    const game = new Game(rec.league, F, state);
    const league = rec.league;
    const team = game.team(key);
    const oppKey = key === 'home' ? 'away' : 'home';
    const opp = game.team(oppKey);
    const half = `${state.half} of the ${ordinal(state.inning)}`;
    let version = rec.version;
    const send = async (action) => {
        const v = await mpApi.action(rec.id, { version, action });
        version = v.version;
        return v;
    };
    const finish = async () => {
        await send({ type: 'done' });
        app.go('mpGame', { id: rec.id });
    };

    if (!game.hasBatted(key)) {
        // The whole lineup card, starting from the team's current one.
        const t = league.teams[state.sides[key].teamId];
        t.lineup = state.sides[key].lineup.map((l) => ({ ...l }));
        return renderLineup(app, {
            league,
            teamId: t.id,
            title: `${teamName(t)}: lineup card vs the ${opp.name}`,
            playLabel: 'Lineup set: let them pitch',
            pitchers: null,
            onBack: () => app.go('multiplayer'),
            onPlay: async (lineup) => {
                try {
                    await send({ type: 'setLineup', lineup });
                    await finish();
                } catch (e) { alert(e.message); }
            },
        });
    }

    // Substitutions.
    const side = game.side(key);
    const pitcher = game.player(game.side(oppKey).pitcherId);
    const status = game.side(oppKey).status[pitcher.id];
    const subs = {};
    const fmt3 = (v) => (Number.isNaN(v) ? '–' : v.toFixed(3).replace(/^0/, ''));
    const today = (id) => {
        const b = state.box.bat[id];
        return b && b.pa ? `${b.h}-${b.ab}${b.hr ? ', HR' : ''}${b.bb ? `, ${b.bb} BB` : ''}${b.k ? `, ${b.k} K` : ''}` : '—';
    };
    const draw = () => {
        const bench = game.bench(key);
        const chosen = new Set(Object.values(subs).map(Number));
        const rows = side.lineup.map((s, i) => {
            const b = league.players[s.id];
            const r = vsArsenal(league, b.id, pitcher);
            const due = (i - side.batIdx + 9) % 9;
            return `<tr class="${due < 3 ? 'current' : ''}">
                <td>${i + 1}</td><td><span class="pos">${s.pos}</span></td>
                <td>${esc(playerName(b))} <span class="muted">${battingSide(b, pitcher)}</span>${due < 3 ? ` <span class="muted" style="font-size:11px">${['up first', 'on deck', 'in the hole'][due]}</span>` : ''}</td>
                <td class="r">${rating(b.contact)}</td><td class="r">${rating(b.power)}</td><td class="r">${rating(b.eye)}</td>
                <td class="r">${fmt3(r.ops)} <span class="muted" style="font-size:11px">${r.pa}</span></td><td class="r">${today(b.id)}</td>
                <td><select data-slot="${i}"><option value="">—</option>${bench.map((id) => {
                    const p = league.players[id];
                    const pr = vsArsenal(league, id, pitcher);
                    const taken = chosen.has(id) && Number(subs[i]) !== id;
                    return `<option value="${id}" ${Number(subs[i]) === id ? 'selected' : ''} ${taken ? 'disabled' : ''}>${p.pos} ${esc(shortName(p))} (${battingSide(p, pitcher)}) C${p.contact} P${p.power} · ${fmt3(pr.ops)}</option>`;
                }).join('')}</select></td>
            </tr>`;
        }).join('');
        const removed = side.removed.map((id) => esc(shortName(league.players[id]))).join(', ');
        app.root.innerHTML = `
        <div class="page wide">
            <div class="page-head"><button data-act="lobby">← Lobby</button><h1>Your hitters are up</h1>
                ${rec.turn.deadline ? `<span class="muted">⏱ <span id="mp-left" data-deadline="${rec.turn.deadline}">${timeLeft(rec.turn.deadline)}</span> left</span>` : ''}</div>
            <div class="panel" style="margin-bottom:10px">
                <b>${esc(teamName(team))}</b> bat in the ${half}, ${state.score[key]}–${state.score[oppKey]}.
                They’ll face <b>${esc(playerName(pitcher))}</b> <span class="muted">${pitcher.throws}HP · ${status.pitches} pitches · ${Math.round(100 * Math.max(0, 1 - status.fatigue))}% energy</span>
                ${pitcher.pitches.map((p) => `<span class="chip" style="background:${PITCH_TYPES[p.type].color}">${PITCH_TYPES[p.type].abbr}</span>`).join('')}
                <span class="muted" style="font-size:12px">(unless ${esc(rec.seats[oppKey]?.name ?? 'they')} makes a pitching change)</span>
            </div>
            <div class="panel">
                <h3>Batting order and pinch hitters</h3>
                <table class="grid">
                    <tr><th>#</th><th></th><th>Batter</th><th class="r">CON</th><th class="r">POW</th><th class="r">EYE</th><th class="r" title="OPS against the pitch types this pitcher throws, with plate appearances">vs his pitches</th><th class="r">Today</th><th>Substitute</th></tr>
                    ${rows}
                </table>
                <p class="muted" style="font-size:12px">A substitute takes over that spot in the order for the rest of the game; the player he replaces can’t return.${removed ? ` Out of the game: ${removed}.` : ''} ${bench.length ? '' : 'Your bench is empty.'}</p>
                <div class="row-actions">
                    <button data-act="none">No changes</button>
                    <button class="primary" data-act="apply">${Object.values(subs).some(Boolean) ? 'Make the changes and let them pitch' : 'Let them pitch'}</button>
                </div>
            </div>
        </div>`;
    };
    const onClick = async (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.act === 'lobby') return app.go('multiplayer');
        if (btn.dataset.act === 'none' || btn.dataset.act === 'apply') {
            btn.disabled = true;
            try {
                if (btn.dataset.act === 'apply') {
                    for (const [slot, benchId] of Object.entries(subs)) if (benchId) await send({ type: 'sub', slot: Number(slot), benchId: Number(benchId) });
                }
                await finish();
            } catch (err) {
                alert(err.message);
                app.go('mpGame', { id: rec.id });
            }
        }
    };
    const onChange = (e) => {
        if (e.target.dataset.slot !== undefined) {
            subs[e.target.dataset.slot] = e.target.value;
            draw();
        }
    };
    const ticker = setInterval(() => {
        const el = app.root.querySelector('#mp-left');
        if (el) el.textContent = timeLeft(Number(el.dataset.deadline));
        if (rec.turn.deadline && Date.now() > rec.turn.deadline + 1000) app.go('mpGame', { id: rec.id });
    }, 1000);
    app.root.addEventListener('click', onClick);
    app.root.addEventListener('change', onChange);
    draw();
    return () => {
        clearInterval(ticker);
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('change', onChange);
    };
}
