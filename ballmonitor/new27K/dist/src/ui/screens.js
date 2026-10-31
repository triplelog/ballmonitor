// Menu, quick-game setup and the lineup card.

import { Game } from '../engine/game.js';
import { PITCH_TYPES } from '../engine/data.js';
import { defaultLineup, playerName, teamName } from '../engine/league.js';
import { esc } from './storage.js';
import { bestWorst } from './scouting.js';
import { CHALLENGE_BY_ID } from '../engine/challenges.js';

export const rating = (v) => `<span class="rating ${v >= 65 ? 'hi' : v <= 40 ? 'lo' : ''}">${v}</span>`;

export const pitchChip = (type) => {
    const t = PITCH_TYPES[type];
    return `<span class="chip" style="background:${t.color}" title="${esc(type)}">${t.abbr}</span>`;
};

// Pitch clock lengths you can pick (seconds), and the default.
export const CLOCK_SECONDS = [5, 10, 15, 20, 25, 30, 45, 60];
export const clockSecondsOf = (prefs) => prefs.clockSeconds ?? 20;
// The break guide is always shown before you press Pitch; 'show' keeps it
// while the zone moves, 'hidden' takes it away. (Older saves had showGuide.)
export const guideModeOf = (prefs) => prefs.guideMode ?? (prefs.showGuide === false ? 'hidden' : 'show');

export function renderMenu(app) {
    const saved = app.savedGame();
    let savedLabel = '';
    if (saved) {
        // Career and season games use their own leagues, so name the kind of
        // game rather than looking up teams in the quick-game league.
        const st = saved.state;
        const where = `${st.half === 'top' ? 'top' : 'bottom'} ${st.inning}`;
        if (saved.careerId) savedLabel = `Career start, ${where}`;
        else if (saved.seasonGameId !== undefined) savedLabel = `Season game, ${where}`;
        else {
            const a = app.league.teams[st.sides.away.teamId];
            const h = app.league.teams[st.sides.home.teamId];
            savedLabel = `${st.challengeId ? `${CHALLENGE_BY_ID[st.challengeId]?.name}: ` : ''}${a?.abbr ?? 'Away'} ${st.score.away} – ${h?.abbr ?? 'Home'} ${st.score.home}, ${where}`;
        }
    }
    app.root.innerHTML = `
    <div class="menu">
        <div class="logo">27K</div>
        <p class="tag">Pick a pitch, read the moving zone, and paint the corners.</p>
        <div class="menu-buttons">
            ${saved ? `<button class="primary" data-go="continue">Continue game <span class="soon">${esc(savedLabel)}</span></button>` : ''}
            <button class="${saved ? '' : 'primary'}" data-go="quick">Quick Game</button>
            <button data-go="challenges">Challenges & Achievements</button>
            <button data-go="lab">Formula Lab</button>
            <button disabled title="Coming later">Season <span class="soon">coming later</span></button>
            <button disabled title="Coming later">Career <span class="soon">coming later</span></button>
            <button disabled title="Coming later">Multiplayer <span class="soon">coming later</span></button>
        </div>
        <div class="panel howto">
            <h3>How to pitch</h3>
            <ol>
                <li>Choose a pitch and set your velocity and movement effort. More effort means more speed or break, but less control and more fatigue. The dashed line shows how the pitch will break.</li>
                <li>Press <b>Pitch</b> (or Space). The strike zone jumps to a new spot and starts to wander. In hidden-guide mode the break line disappears now, so remember it.</li>
                <li>Click where to aim. The ball breaks from there and scatters by your control.</li>
                <li>Beat the pitch clock (20 seconds unless you change it; it appears for the last 10). Run out of time and it's a ball.</li>
                <li>Stuck? Once an inning, call a <b>catcher’s visit</b>: it stops and resets the clock, and he’ll tell you what to throw this hitter.</li>
            </ol>
        </div>
        <p class="credit">Every rule of the game is a formula, read by <a href="https://mathzetta.com/" target="_blank" rel="noopener">MathZetta</a> — change them in the Formula Lab.</p>
    </div>`;
    app.root.querySelector('.menu').addEventListener('click', (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.go) app.go(btn.dataset.go);
        // (No button for this right now; kept for later.)
        if (btn.dataset.act === 'new-league') {
            if (confirm('Generate a new league? Your current teams and any game in progress will be replaced.')) {
                app.newLeague();
                app.go('menu');
            }
        }
    });
}

export function renderQuickSetup(app) {
    const p = app.prefs;
    const teamOptions = (sel) => app.league.teams
        .map((t) => `<option value="${t.id}" ${t.id === sel ? 'selected' : ''}>${esc(teamName(t))}</option>`).join('');
    const diffNames = ['', 'Rookie', 'Pro', 'All-Star', 'MVP', 'Chaos'];
    app.root.innerHTML = `
    <div class="page">
        <div class="page-head"><button data-act="back">← Menu</button><h1>Quick Game</h1></div>
        <div class="panel">
            <div class="form-grid">
                <label for="q-team">Your team</label>
                <select id="q-team">${teamOptions(p.userTeamId)}</select>
                <label for="q-opp">Opponent</label>
                <select id="q-opp">${teamOptions(p.oppTeamId)}</select>
                <label for="q-home">You are</label>
                <select id="q-home">
                    <option value="home" ${p.userHome ? 'selected' : ''}>Home (you pitch the top of each inning)</option>
                    <option value="away" ${p.userHome ? '' : 'selected'}>Away (you bat first)</option>
                </select>
                <label for="q-inn">Innings</label>
                <select id="q-inn">${[1, 3, 5, 7, 9].map((n) => `<option ${n === p.innings ? 'selected' : ''}>${n}</option>`).join('')}</select>
                <label for="q-diff">Difficulty</label>
                <div><input id="q-diff" type="range" min="1" max="5" step="1" value="${p.difficulty}"> <b id="q-diff-name">${diffNames[p.difficulty]}</b></div>
                <div class="hint">Higher difficulty makes the zone faster and more erratic (see the Zone formulas).</div>
                <label for="q-clock">Pitch clock</label>
                <select id="q-clock">
                    <option value="press" ${(p.clockMode ?? 'press') === 'press' ? 'selected' : ''}>Starts when you press Pitch</option>
                    <option value="continuous" ${p.clockMode === 'continuous' ? 'selected' : ''}>Runs from the end of the last pitch</option>
                    <option value="off" ${p.clockMode === 'off' ? 'selected' : ''}>Off</option>
                </select>
                <label for="q-clock-secs">Clock length</label>
                <select id="q-clock-secs">${CLOCK_SECONDS.map((n) => `<option value="${n}" ${n === clockSecondsOf(p) ? 'selected' : ''}>${n} seconds</option>`).join('')}</select>
                <div class="hint">The clock shows on the field only for its last 10 seconds. You can change both during a game, under the field.</div>
                <label for="q-guide">Break guide</label>
                <select id="q-guide">
                    <option value="show" ${guideModeOf(p) === 'show' ? 'selected' : ''}>Always shown</option>
                    <option value="hidden" ${guideModeOf(p) === 'hidden' ? 'selected' : ''}>Hidden once the zone moves (shown before you press Pitch)</option>
                </select>
                <label for="q-calls">Pitch calling</label>
                <select id="q-calls">
                    <option value="me" ${p.catcherCalls ? '' : 'selected'}>You pick every pitch</option>
                    <option value="catcher" ${p.catcherCalls ? 'selected' : ''}>The catcher calls them (pitch and spot; shake him off any time)</option>
                </select>
                <label for="q-autobat">When you bat</label>
                <select id="q-autobat">
                    <option value="auto" ${(p.autoBat ?? true) ? 'selected' : ''}>Sim the whole half-inning automatically</option>
                    <option value="manage" ${(p.autoBat ?? true) ? '' : 'selected'}>Manage each batter (pinch hit, sim one at a time)</option>
                </select>
                <label>Aiming help</label>
                <div>
                    <label class="toggle"><input type="checkbox" id="q-odds" ${p.showOdds ? 'checked' : ''}> Show odds after each pitch</label>
                </div>
            </div>
            <div class="row-actions"><button class="primary big" data-act="next">Set lineup →</button></div>
        </div>
    </div>`;
    const $ = (id) => app.root.querySelector('#' + id);
    $('q-diff').addEventListener('input', () => { $('q-diff-name').textContent = diffNames[$('q-diff').value]; });
    app.root.querySelector('.page').addEventListener('click', (e) => {
        const act = e.target.closest('button')?.dataset.act;
        if (act === 'back') app.go('menu');
        if (act === 'next') {
            const userTeamId = Number($('q-team').value);
            const oppTeamId = Number($('q-opp').value);
            if (userTeamId === oppTeamId) {
                alert('Pick two different teams.');
                return;
            }
            Object.assign(app.prefs, {
                userTeamId, oppTeamId,
                userHome: $('q-home').value === 'home',
                innings: Number($('q-inn').value),
                difficulty: Number($('q-diff').value),
                guideMode: $('q-guide').value,
                showOdds: $('q-odds').checked,
                clockMode: $('q-clock').value,
                clockSeconds: Number($('q-clock-secs').value),
                autoBat: $('q-autobat').value === 'auto',
                catcherCalls: $('q-calls').value === 'catcher',
            });
            app.savePrefs();
            app.go('lineup');
        }
    });
}

// The user's lineup card: batting order, bench swaps and the starter.
// ctx (optional, for seasons): { league, teamId, title, playLabel,
//   pitchers: [{ id, note, available }], starterId, onBack(), onPlay(lineup, starterId) }
// With no starter list (pitchers: null) only the lineup is edited.
export function renderLineup(app, ctx = null) {
    ctx = ctx ?? quickGameLineup(app);
    const { league } = ctx;
    const team = league.teams[ctx.teamId];
    let lineup = team.lineup.map((s) => ({ ...s }));
    let starterId = ctx.starterId;

    const draw = () => {
        const inLineup = new Set(lineup.map((s) => s.id));
        const bench = team.batters.filter((id) => !inLineup.has(id));
        const batterRow = (b, extra) => {
            const [best, worst] = bestWorst(league, b);
            return `
            <td class="pname">${esc(playerName(b))}<div class="muted" style="font-size:11px">${best ? `<span class="hot">${best}</span>` : ''}${worst ? ` · <span class="cold">${worst}</span>` : ''}</div></td><td>${b.bats}</td>
            <td class="r">${rating(b.contact)}</td><td class="r">${rating(b.power)}</td>
            <td class="r">${rating(b.eye)}</td><td class="r opt">${rating(b.speed)}</td>
            <td class="r opt">${rating(b.vsFast)}</td><td class="r opt">${rating(b.vsBreak)}</td><td class="r opt">${rating(b.vsOff)}</td>${extra}`;
        };
        const head = '<th>Name</th><th>B</th><th class="r">CON</th><th class="r">POW</th><th class="r">EYE</th><th class="r opt">SPD</th><th class="r opt" title="vs fastballs">vFB</th><th class="r opt" title="vs breaking balls">vBRK</th><th class="r opt" title="vs off-speed">vOFF</th>';
        const starters = ctx.pitchers ?? [];

        app.root.innerHTML = `
        <div class="page">
            <div class="page-head"><button data-act="back">← Back</button><h1>${esc(ctx.title ?? `${teamName(team)}: lineup card`)}</h1></div>
            <div class="cols-2">
                <div class="panel">
                    <h3>Batting order</h3>
                    <table class="grid">
                        <tr><th>#</th><th>Pos</th>${head}<th></th></tr>
                        ${lineup.map((s, i) => {
                            const b = league.players[s.id];
                            return `<tr><td>${i + 1}</td><td><span class="pos">${s.pos}</span></td>${batterRow(b, `
                                <td class="r order"><button class="small" data-up="${i}" ${i === 0 ? 'disabled' : ''}>▲</button>
                                <button class="small" data-down="${i}" ${i === 8 ? 'disabled' : ''}>▼</button></td>`)}</tr>`;
                        }).join('')}
                    </table>
                    <h3 style="margin-top:16px">Bench</h3>
                    <table class="grid">
                        <tr><th>Pos</th>${head}<th>Start in place of</th></tr>
                        ${bench.map((id) => {
                            const b = league.players[id];
                            return `<tr><td><span class="pos">${b.pos}</span></td>${batterRow(b, `
                                <td><select data-swap="${id}"><option value="">—</option>
                                ${lineup.map((s, i) => `<option value="${i}">${s.pos} ${esc(league.players[s.id].last)}</option>`).join('')}
                                </select></td>`)}</tr>`;
                        }).join('')}
                    </table>
                    <div class="row-actions" style="justify-content:flex-start">
                        <button data-act="auto">Automatic lineup</button>
                    </div>
                </div>
                <div class="panel">
                    ${ctx.pitchers ? `<h3>Starting pitcher</h3>
                    <div class="pitcher-pick">
                        ${starters.map(({ id, note, available }) => {
                            const sp = league.players[id];
                            return `<label style="${available ? '' : 'opacity:0.45'}"><input type="radio" name="sp" value="${sp.id}" ${sp.id === starterId ? 'checked' : ''} ${available ? '' : 'disabled'}>
                            <div style="flex:1">
                                <div><b>${esc(playerName(sp))}</b> <span class="muted">${sp.throws}HP · ${sp.role}</span>${note ? ` <span class="muted" style="float:right;font-size:12px">${esc(note)}</span>` : ''}</div>
                                <div class="muted" style="font-size:12px">VEL ${rating(sp.velo)} · MOV ${rating(sp.move)} · CTL ${rating(sp.control)} · STA ${sp.stamina}</div>
                                <div style="margin-top:3px">${sp.pitches.map((x) => pitchChip(x.type)).join('')}</div>
                            </div>
                        </label>`;
                        }).join('')}
                    </div>` : ''}
                    <div class="row-actions"><button class="primary big" data-act="play">${esc(ctx.playLabel ?? 'Play ball!')}</button></div>
                </div>
            </div>
        </div>`;
    };

    const onClick = (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.up !== undefined) {
            const i = Number(btn.dataset.up);
            [lineup[i - 1], lineup[i]] = [lineup[i], lineup[i - 1]];
            draw();
        } else if (btn.dataset.down !== undefined) {
            const i = Number(btn.dataset.down);
            [lineup[i + 1], lineup[i]] = [lineup[i], lineup[i + 1]];
            draw();
        } else if (btn.dataset.act === 'back') {
            ctx.onBack();
        } else if (btn.dataset.act === 'auto') {
            lineup = defaultLineup(league, team);
            draw();
        } else if (btn.dataset.act === 'play') {
            team.lineup = lineup.map((s) => ({ ...s }));
            ctx.onPlay(lineup, starterId);
        }
    };
    const onChange = (e) => {
        if (e.target.name === 'sp') starterId = Number(e.target.value);
        if (e.target.dataset.swap && e.target.value !== '') {
            const slot = Number(e.target.value);
            lineup[slot] = { id: Number(e.target.dataset.swap), pos: lineup[slot].pos };
            draw();
        }
    };

    app.root.addEventListener('click', onClick);
    app.root.addEventListener('change', onChange);
    draw();
    return () => {
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('change', onChange);
    };
}

function quickGameLineup(app) {
    const { league } = app;
    const p = app.prefs;
    const team = league.teams[p.userTeamId];
    return {
        league,
        teamId: team.id,
        pitchers: team.pitchers.filter((id) => league.players[id].role === 'SP').map((id) => ({ id, available: true })),
        starterId: team.rotation[team.nextStarter % team.rotation.length],
        onBack: () => app.go('quick'),
        onPlay: (lineup, starterId) => startQuickGame(app, team, lineup, starterId),
    };
}

function startQuickGame(app, team, lineup, starterId) {
    const { league } = app;
    const p = app.prefs;
    const opp = league.teams[p.oppTeamId];
    const game = Game.create(league, app.F, {
        homeId: p.userHome ? team.id : opp.id,
        awayId: p.userHome ? opp.id : team.id,
        userTeamId: team.id,
        innings: p.innings,
        difficulty: p.difficulty,
        seed: Date.now() >>> 0,
        [p.userHome ? 'home' : 'away']: { lineup, starterId },
    });
    // Rotate both teams' starters.
    const idx = team.rotation.indexOf(starterId);
    team.nextStarter = (idx + 1) % team.rotation.length;
    opp.nextStarter = (opp.nextStarter + 1) % opp.rotation.length;
    app.saveLeague();
    app.saveGame(game);
    app.go('game', { game });
}
