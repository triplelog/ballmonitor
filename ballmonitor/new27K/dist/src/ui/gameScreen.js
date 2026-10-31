// The game screen. When you are in the field you pitch on the moving
// zone; when your team bats you manage (pinch hit, sim a batter or the
// inning) and watch the computer pitch.

import { createRng } from '../engine/rng.js';
import { ZoneMover } from '../engine/zone.js';
import { PITCH_TYPES, pitchKeys } from '../engine/data.js';
import { rates, leagueByType } from '../engine/pitchStats.js';
import { bestWorst } from './scouting.js';
import { battingSide, edgeDistance } from '../engine/pitch.js';
import { playerName, shortName } from '../engine/league.js';
import { ordinal } from '../engine/game.js';
import { PlateView, drawHeatThumb } from './plate.js';
import { esc } from './storage.js';
import { rating, pitchChip, CLOCK_SECONDS, guideModeOf, clockSecondsOf } from './screens.js';
import { createTracker, track } from '../engine/tracker.js';
import { checkAchievements, ACHIEVEMENT_BY_ID } from '../engine/achievements.js';
import { evaluateChallenge, evaluateChallengeAtEnd } from '../engine/challenges.js';
import { recordAchievement, recordChallenge, challengeRecords } from './progress.js';
import { starsHTML, playChallenge } from './challengesScreen.js';
import { mpApi, timeLeft } from './mpClient.js';
import { PID } from '../engine/career.js';
import { aiPickReliever } from '../engine/ai.js';
import { catcherAdvice, callPitch } from '../engine/advice.js';
import { ZONE } from '../engine/data.js';

const PLAY_BANNERS = {
    K: ['STRIKEOUT!', '#3dd68c'], KL: ['STRIKEOUT LOOKING!', '#3dd68c'],
    BB: ['WALK', '#ff6b6b'], HBP: ['HIT BY PITCH', '#ff6b6b'],
    '1B': ['SINGLE', '#ff6b6b'], '2B': ['DOUBLE', '#ff6b6b'], '3B': ['TRIPLE', '#ff6b6b'], HR: ['HOME RUN', '#ff6b6b'],
    E: ['ERROR', '#ff6b6b'], GO: ['GROUND OUT', '#3dd68c'], FO: ['FLY OUT', '#3dd68c'], PO: ['POP OUT', '#3dd68c'],
    DP: ['DOUBLE PLAY!', '#3dd68c'], SF: ['SACRIFICE FLY', '#ffd166'],
};
const CALL_BANNERS = {
    ball: ['BALL', '#e8efe9'], called: ['CALLED STRIKE', '#ffd166'], swinging: ['SWINGING STRIKE', '#3dd68c'],
    foul: ['FOUL', '#ffd166'], clock: ['PITCH CLOCK: BALL', '#ff6b6b'], caught: ['CAUGHT: STRIKE', '#3dd68c'],
};

const pct = (v) => `${Math.round(v * 100)}%`;

// args: { game, challenge?, tracker?, earned?, seasonGameId? }. tracker and
// earned carry the user's pitching stats and this game's achievements across
// reloads; seasonGameId ties the game to the season schedule.
export function renderGame(app, args) {
    const { game, challenge = null, seasonGameId } = args;
    // Career: { career }. You pitch only while your pitcher is in the game.
    const career = args.career ?? null;
    const inSeason = seasonGameId !== undefined && !career;
    // Multiplayer: { record, playerId, myTurn, seats }. This browser pitches
    // only its own half-innings; otherwise it watches.
    const mp = args.mp ?? null;
    const mpHalf = `${game.state.inning}${game.state.half}`;
    let mpPending = Promise.resolve();
    let mpPoll = 0;
    const tracker = args.tracker ?? createTracker();
    const earned = args.earned ?? [];
    const { prefs } = app;
    // A challenge brings its own league view and formulas.
    const league = game.league;
    const F = game.F;
    const uiRng = createRng(Date.now() >>> 0);
    const zone = new ZoneMover(F, uiRng);
    const userKey = game.userKey();
    const guideMode = () => guideModeOf(prefs);
    const clockSeconds = () => clockSecondsOf(prefs);
    const autoBat = () => prefs.autoBat ?? true;
    const catcherCalls = () => !!prefs.catcherCalls && !mp;

    const ui = {
        mode: 'ready',          // ready | aiming | playback
        pitchIdx: 0,
        effort: 50,
        moveEffort: 50,
        mouse: null,
        clock: null,            // { left, total } while the pitch clock runs
        scoutId: null,          // batter shown in the Batter tab instead of the one up
        queue: [],              // results waiting to be shown
        current: null,          // { result, t, dur, hold }
        markers: null,          // pitches to draw while playing back
        lastResult: null,
        tab: 'batter',
        side: null, heat: null,
        challengeResult: null,  // { status, reason, stars } once a challenge is settled
        toasts: [],             // achievements to announce when their pitch lands
        plan: null,             // { target, color, label } the spot to hit, until the next pitch
        call: null,             // the catcher's call for the next pitch (catcher-calls mode)
    };

    app.root.innerHTML = `
    <div class="game">
        <div class="g-top"></div>
        <div class="g-left"></div>
        <div class="g-center">
            <div class="plate-wrap"><canvas id="plate"></canvas></div>
            <div class="plate-bar">
                <label class="toggle">Break guide <select id="t-guide">
                    <option value="show" ${guideMode() === 'show' ? 'selected' : ''}>always shown</option>
                    <option value="hidden" ${guideMode() === 'hidden' ? 'selected' : ''}>hidden once the zone moves</option>
                </select></label>
                <label class="toggle"><input type="checkbox" id="t-heat" ${prefs.showHeat ? 'checked' : ''}> Heat map</label>
                <label class="toggle"><input type="checkbox" id="t-odds" ${prefs.showOdds ? 'checked' : ''}> Odds</label>
                <label class="toggle"><input type="checkbox" id="t-calls" ${prefs.catcherCalls ? 'checked' : ''}> Catcher calls pitches</label>
                <label class="toggle">Pitch clock <select id="t-clock">
                    <option value="press" ${(prefs.clockMode ?? 'press') === 'press' ? 'selected' : ''}>starts at Pitch</option>
                    <option value="continuous" ${prefs.clockMode === 'continuous' ? 'selected' : ''}>runs between pitches</option>
                    <option value="off" ${prefs.clockMode === 'off' ? 'selected' : ''}>off</option>
                </select> <select id="t-clock-secs" title="Seconds on the pitch clock">
                    ${CLOCK_SECONDS.map((n) => `<option value="${n}" ${n === clockSeconds() ? 'selected' : ''}>${n} s</option>`).join('')}
                </select></label>
                <span class="spacer"></span>
                <span class="muted" id="hint"></span>
            </div>
            <div class="odds panel" id="odds" hidden></div>
        </div>
        <div class="g-right"></div>
        <div class="g-log panel"><h3>Play-by-play</h3><div class="log"></div></div>
        <div id="overlay"></div>
        <div class="toasts"></div>
    </div>`;

    const $ = (sel) => app.root.querySelector(sel);
    const canvas = $('#plate');
    const plate = new PlateView(canvas);

    // ---------- panels ----------
    // view: a scoreboard snapshot (result.after) while results play back;
    // otherwise the game as it stands.
    function renderTop(view = null) {
        const st = view ? { ...game.state, ...view } : game.state;
        const battingNow = st.half === 'top' ? 'away' : 'home';
        const away = game.team('away');
        const home = game.team('home');
        const cols = Math.max(st.settings.innings, st.line.away.length);
        const cell = (key, i) => {
            const v = st.line[key][i];
            const now = !st.over && i === st.inning - 1 && key === battingNow;
            return `<td class="inn ${now ? 'now' : ''}">${v === undefined ? '' : v}</td>`;
        };
        const row = (key, t) => `<tr><td class="team" style="color:${t.color === '#111827' ? '#cbd5e1' : t.color}">${t.abbr}${game.userKey() === key ? ' ★' : ''}</td>
            ${Array.from({ length: cols }, (_, i) => cell(key, i)).join('')}
            <td class="rhe">${st.score[key]}</td><td class="rhe">${st.hits[key]}</td><td class="rhe">${st.errors[key]}</td></tr>`;
        const dots = (n, max, cls) => Array.from({ length: max }, (_, i) => `<span class="dot ${i < n ? cls : ''}"></span>`).join('');
        const b = st.over ? [null, null, null] : st.bases;
        const [balls, strikes, outs] = st.over ? [0, 0, 0] : [st.balls, st.strikes, st.outs];
        $('.g-top').innerHTML = `
            <button class="menu-btn" data-act="menu" title="Menu">☰<span class="lbl"> Menu</span></button>
            <div class="panel linescore"><table>
                <tr><th></th>${Array.from({ length: cols }, (_, i) => `<th class="inn">${i + 1}</th>`).join('')}<th class="rhe">R</th><th class="rhe">H</th><th class="rhe">E</th></tr>
                ${row('away', away)}${row('home', home)}
            </table></div>
            <div class="panel situation">
                <div class="inning-label">${st.over ? 'Final' : `${st.half === 'top' ? '▲' : '▼'} ${ordinal(st.inning)}`}</div>
                <div class="count">
                    <span class="muted">B</span><span class="dots">${dots(balls, 3, 'b')}</span>
                    <span class="muted">S</span><span class="dots">${dots(strikes, 2, 's')}</span>
                    <span class="muted">O</span><span class="dots">${dots(outs, 2, 'o')}</span>
                </div>
                <div class="bases">
                    <div class="base second ${b[1] ? 'on' : ''}"></div>
                    <div class="base third ${b[2] ? 'on' : ''}"></div>
                    <div class="base first ${b[0] ? 'on' : ''}"></div>
                </div>
            </div>`;
    }

    function renderPitcherPanel() {
        const pitcher = game.pitcher();
        const status = game.pitcherStatus();
        const box = game.pitchBox(pitcher.id);
        if (ui.pitchIdx >= pitcher.pitches.length) ui.pitchIdx = 0;
        const energy = Math.max(0, 1 - status.fatigue);
        const preview = game.previewPitch(ui.pitchIdx, ui);
        const breakIn = Math.hypot(preview.dx, preview.dy);
        const busy = ui.mode !== 'ready';
        const keys = pitchKeys(pitcher.pitches);
        $('.g-left').innerHTML = `${hudHTML()}
            <div class="panel pitcher-card">
                <div class="card-head"><span class="name">${esc(playerName(pitcher))}</span><span class="muted">${pitcher.throws}HP · ${pitcher.role}</span></div>
                <div class="energy ${energy < 0.25 ? 'low' : energy < 0.5 ? 'mid' : ''}"><div style="width:${Math.round(energy * 100)}%"></div></div>
                <div class="muted num" style="font-size:12px">Energy ${Math.round(energy * 100)}% · ${status.pitches} pitches · ${ipText(box.outs)} IP, ${box.h} H, ${box.r} R, ${box.bb} BB, ${box.k} K</div>
            </div>
            <div class="panel pitch-panel">
                ${callCard()}
                <h3>Pitch</h3>
                <div class="arsenal">
                    ${pitcher.pitches.map((p, i) => {
                        const t = PITCH_TYPES[p.type];
                        return `<button data-pitch="${i}" class="${i === ui.pitchIdx ? 'sel' : ''}">
                            <span class="key" title="Press ${keys[i]} or ${i + 1}">${keys[i]}</span>
                            <span><span class="swatch" style="background:${t.color}"></span><span class="pname">${esc(p.type)}</span></span>
                            <span class="pr">V${p.velo} M${p.move} C${p.control}</span>
                        </button>`;
                    }).join('')}
                </div>
                <div class="slider">
                    <label><span>Velocity effort</span><span id="v-eff">${ui.effort}</span></label>
                    <input type="range" min="0" max="100" value="${ui.effort}" data-slider="effort">
                </div>
                <div class="slider">
                    <label><span>Movement effort</span><span id="m-eff">${ui.moveEffort}</span></label>
                    <input type="range" min="0" max="100" value="${ui.moveEffort}" data-slider="moveEffort">
                </div>
                <div class="preview">
                    <div><b id="pv-velo">${preview.velocity.toFixed(1)}</b><span>mph</span></div>
                    <div><b id="pv-break">${breakIn.toFixed(1)}"</b><span>break</span></div>
                    <div><b id="pv-scatter">±${preview.scatter.toFixed(1)}"</b><span>scatter</span></div>
                </div>
            </div>
            <button class="primary pitch-btn" data-act="pitch" ${busy ? 'disabled' : ''}>${ui.mode === 'aiming' ? '<span class="no-touch">Click the zone to throw</span><span class="touch-only">Touch the zone to throw</span>' : 'Pitch<span class="no-touch"> (Space)</span>'}</button>
            ${visitButton()}`;
    }

    function updatePreview() {
        const preview = game.previewPitch(ui.pitchIdx, ui);
        const set = (id, text) => { const el = $(id); if (el) el.textContent = text; };
        set('#v-eff', ui.effort);
        set('#m-eff', ui.moveEffort);
        set('#pv-velo', preview.velocity.toFixed(1));
        set('#pv-break', Math.hypot(preview.dx, preview.dy).toFixed(1) + '"');
        set('#pv-scatter', '±' + preview.scatter.toFixed(1) + '"');
    }

    function renderOffensePanel() {
        const key = game.battingKey;
        const side = game.side(key);
        const pitcher = game.pitcher();
        const status = game.pitcherStatus();
        const due = [0, 1, 2].map((k) => {
            const slot = (side.batIdx + k) % 9;
            const b = league.players[side.lineup[slot].id];
            return `<tr class="${k === 0 ? 'current' : ''}"><td>${slot + 1}</td><td><span class="pos">${side.lineup[slot].pos}</span></td>
                <td>${esc(shortName(b))}</td><td>${battingSide(b, pitcher)}</td><td class="r">${rating(b.contact)}</td><td class="r">${rating(b.power)}</td><td class="r">${rating(b.eye)}</td><td class="r">${todayLine(b.id)}</td></tr>`;
        }).join('');
        const bench = game.bench(key).map((id) => league.players[id]);
        const busy = ui.mode !== 'ready';
        $('.g-left').innerHTML = `${hudHTML()}
            <div class="panel offense">
                <h3>Your turn at bat</h3>
                <div>Facing <b>${esc(playerName(pitcher))}</b> <span class="muted">${pitcher.throws}HP · ${status.pitches} pitches</span></div>
                <table class="grid">
                    <tr><th>#</th><th></th><th>Due up</th><th>B</th><th class="r">CON</th><th class="r">POW</th><th class="r">EYE</th><th class="r">Today</th></tr>
                    ${due}
                </table>
                <div>
                    <div class="muted" style="font-size:12px;margin-bottom:4px">Pinch hit for ${esc(shortName(game.batter()))}</div>
                    ${bench.length ? `<div style="display:flex;gap:6px">
                        <select id="ph-pick" style="flex:1">${bench.map((b) => `<option value="${b.id}">${b.pos} ${esc(shortName(b))} (${b.bats}) C${b.contact} P${b.power} E${b.eye}</option>`).join('')}</select>
                        <button data-act="pinch" ${busy || game.state.balls + game.state.strikes > 0 ? 'disabled' : ''}>Send up</button>
                    </div>` : '<div class="muted">Bench is empty.</div>'}
                </div>
                <div class="actions">
                    <button class="primary" data-act="sim-pa" ${busy ? 'disabled' : ''}>Sim batter</button>
                    <button data-act="sim-half" ${busy ? 'disabled' : ''}>Sim rest of inning</button>
                </div>
                <label class="toggle"><input type="checkbox" id="t-autobat" ${autoBat() ? 'checked' : ''}> Sim our half-innings automatically</label>
            </div>`;
    }

    function renderRight() {
        const tabs = [['batter', 'Batter'], ['lineup', 'Lineup'], ['pen', 'Bullpen'], ['box', 'Box']];
        let body = '';
        if (ui.tab === 'batter') body = batterCard();
        if (ui.tab === 'lineup') body = lineupTable(game.battingKey);
        if (ui.tab === 'pen') body = bullpenTable();
        if (ui.tab === 'box') body = boxScore();
        $('.g-right').innerHTML = `
            <div class="panel">
                <div class="tabs">${tabs.map(([k, label]) => `<button data-tab="${k}" class="${ui.tab === k ? 'sel' : ''}">${label}</button>`).join('')}</div>
                <div class="tab-body">${body}</div>
            </div>`;
        const thumb = $('.heat-thumb');
        if (thumb) {
            const b = shownBatter();
            drawHeatThumb(thumb, b.heat, battingSide(b, game.pitcher()) === 'L');
        }
    }

    // The batter up, or one picked from the Lineup tab (ui.scoutId).
    function shownBatter() {
        return ui.scoutId ? league.players[ui.scoutId] : game.batter();
    }

    function batterCard() {
        const b = shownBatter();
        const up = !ui.scoutId || ui.scoutId === game.batter().id;
        const pitcher = game.pitcher();
        const side = battingSide(b, pitcher);
        const pitches = up ? game.state.pa.pitches : [];
        const slot = game.side(game.battingKey).lineup.find((s) => s.id === b.id);
        return `
            ${up ? '' : `<div class="scout-note">Scouting report <button class="small" data-act="unscout">Back to the batter up</button></div>`}
            <div class="card-head"><span class="name">${esc(playerName(b))}</span><span class="muted">${slot?.pos ?? b.pos} · bats ${side}${b.bats === 'S' ? ' (S)' : ''}</span></div>
            <div class="muted" style="font-size:12px">Today: ${todayLine(b.id)}</div>
            <div class="batter-ratings">
                <div><b>${rating(b.contact)}</b><span>CONTACT</span></div>
                <div><b>${rating(b.power)}</b><span>POWER</span></div>
                <div><b>${rating(b.eye)}</b><span>EYE</span></div>
                <div><b>${rating(b.speed)}</b><span>SPEED</span></div>
                <div><b>${rating(b.vsFast)}</b><span>VS FAST</span></div>
                <div><b>${rating(b.vsBreak)}</b><span>VS BREAK</span></div>
                <div><b>${rating(b.vsOff)}</b><span>VS OFF</span></div>
                <div><b>${b.bats}</b><span>BATS</span></div>
            </div>
            <div class="batter-body">
                <div><canvas class="heat-thumb"></canvas><div class="muted" style="font-size:11px;margin-top:3px">Heat map (red = hot)</div></div>
                <div class="pa-pitches">
                    ${pitches.length ? pitches.map((p, i) => `<div><span class="swatch" style="background:${p.color}"></span>${i + 1}. ${p.abbr} ${p.velocity.toFixed(0)} · ${callWord(p.call)}</div>`).join('') : `<span class="muted">${up ? 'No pitches yet this at-bat.' : ''}</span>`}
                </div>
            </div>
            ${scoutingTable(b, pitcher)}`;
    }

    // How this batter has hit each pitch type (the pitcher's own pitches
    // first), judged against the league.
    function scoutingTable(b, pitcher) {
        const leagueTypeCache = leagueByType(league);
        const mine = league.pitchStats?.[b.id] ?? {};
        const arsenal = pitcher.pitches.map((p) => p.type);
        const keys = game.isUserPitching() ? pitchKeys(pitcher.pitches) : [];
        const others = Object.keys(mine).filter((t) => !arsenal.includes(t) && rates(mine[t]).pa >= 5)
            .sort((x, y) => rates(mine[y]).pa - rates(mine[x]).pa);
        const fmt3 = (v) => (Number.isNaN(v) ? '–' : v.toFixed(3).replace(/^0/, ''));
        const pct = (v) => (Number.isNaN(v) ? '–' : `${Math.round(v * 100)}%`);
        const row = (type, i) => {
            const r = rates(mine[type]);
            const lg = leagueTypeCache[type];
            const small = r.pa < 10;
            const diff = r.ops - (lg?.ops ?? 0.7);
            const cls = small || Number.isNaN(r.ops) ? '' : diff > 0.12 ? 'hot' : diff < -0.12 ? 'cold' : '';
            const wcls = Number.isNaN(r.whiff) || !lg ? '' : r.whiff - lg.whiff > 0.07 ? 'cold' : r.whiff - lg.whiff < -0.07 ? 'hot' : '';
            const t = PITCH_TYPES[type];
            return `<tr class="${small ? 'small' : ''} ${i !== undefined ? 'theirs' : ''}">
                <td>${i !== undefined && keys[i] ? `<span class="kbd">${keys[i]}</span>` : ''}<span class="swatch" style="background:${t.color}"></span>${esc(type)}</td>
                <td class="r">${r.pa}</td><td class="r">${fmt3(r.avg)}</td><td class="r ${cls}"><b>${fmt3(r.ops)}</b></td>
                <td class="r">${pct(r.k)}</td><td class="r ${wcls}">${pct(r.whiff)}</td></tr>`;
        };
        return `<h3 style="margin-top:12px">Vs pitch types</h3>
            <table class="grid scout">
                <tr><th>Pitch</th><th class="r">PA</th><th class="r">AVG</th><th class="r">OPS</th><th class="r">K%</th><th class="r">Whiff</th></tr>
                ${arsenal.map((type, i) => row(type, i)).join('')}
                ${others.length ? `<tr><td colspan="6" class="muted" style="font-size:11px">Other pitches</td></tr>${others.map((type) => row(type)).join('')}` : ''}
            </table>
            <div class="muted" style="font-size:11px;margin-top:4px">All games in this league, by the pitch that ended each plate appearance (Whiff = misses per swing, every pitch). <span class="hot">Red</span> = he hits it well, <span class="cold">blue</span> = he struggles; faded rows are small samples.</div>`;
    }

    function lineupTable(key) {
        const side = game.side(key);
        const t = game.team(key);
        const pitcher = game.pitcher();
        return `<h3>${esc(t.city)} ${esc(t.name)}</h3>
            <div class="lineup-cards">
            ${side.lineup.map((s, i) => {
                const b = league.players[s.id];
                const [best, worst] = bestWorst(league, b);
                return `<button class="lineup-card ${i === side.batIdx && key === game.battingKey ? 'current' : ''}" data-scout="${b.id}">
                    <div class="lc-top"><span>${i + 1}. <span class="pos">${s.pos}</span> <b>${esc(shortName(b))}</b> <span class="muted">${battingSide(b, pitcher)}</span></span><span class="muted">${todayLine(b.id)}</span></div>
                    <div class="lc-ratings">CON ${rating(b.contact)} POW ${rating(b.power)} EYE ${rating(b.eye)} SPD ${rating(b.speed)}</div>
                    <div class="lc-ratings">vs FB ${rating(b.vsFast)} BRK ${rating(b.vsBreak)} OFF ${rating(b.vsOff)}${best ? ` · <span class="hot">${best}</span>` : ''}${worst ? ` · <span class="cold">${worst}</span>` : ''}</div>
                </button>`;
            }).join('')}
            </div>
            <div class="muted" style="font-size:11px;margin-top:4px">Click a batter for his scouting report.</div>`;
    }

    function bullpenTable() {
        if (!userKey) return '';
        const side = game.side(userKey);
        const canChange = game.isUserPitching() && ui.mode === 'ready' && !career;
        const rows = game.team(userKey).pitchers.map((id) => {
            const p = league.players[id];
            const resting = (side.unavailable ?? []).includes(id);
            const used = side.pitchersUsed.includes(id) || resting;
            const current = id === side.pitcherId;
            const st = side.status[id];
            const status = current ? `${Math.round(100 * Math.max(0, 1 - st.fatigue))}% · ${st.pitches}p` : resting ? 'resting' : used ? 'used' : '';
            return `<tr class="${current ? 'current' : used ? 'out' : ''}">
                <td>${esc(shortName(p))}<div class="muted" style="font-size:11px">${p.role} ${p.throws} · ${p.pitches.map((x) => PITCH_TYPES[x.type].abbr).join(' ')}</div></td>
                <td class="r num">${p.velo}/${p.move}/${p.control}</td>
                <td class="r">${used ? `<span class="muted">${status}</span>` : `<button class="small" data-relieve="${id}" ${canChange ? '' : 'disabled'}>Bring in</button>`}</td>
            </tr>`;
        }).join('');
        return `<h3>Your staff</h3><table class="grid"><tr><th>Pitcher</th><th class="r">V/M/C</th><th></th></tr>${rows}</table>
            <div class="muted" style="font-size:11px;margin-top:6px">${game.isUserPitching() ? 'Changes happen between pitches.' : 'You can change pitchers when you are in the field.'}</div>`;
    }

    function boxScore() {
        const pitchRows = (key) => game.side(key).pitchersUsed.map((id) => {
            const b = game.pitchBox(id);
            return `<tr><td>${esc(shortName(league.players[id]))}</td><td class="r">${ipText(b.outs)}</td><td class="r">${b.h}</td><td class="r">${b.r}</td><td class="r">${b.er}</td><td class="r">${b.bb}</td><td class="r">${b.k}</td><td class="r">${b.pitches}</td></tr>`;
        }).join('');
        const head = '<tr><th>Pitcher</th><th class="r">IP</th><th class="r">H</th><th class="r">R</th><th class="r">ER</th><th class="r">BB</th><th class="r">K</th><th class="r">P</th></tr>';
        return ['away', 'home'].map((key) => `<h3>${game.team(key).abbr} pitching</h3><table class="grid">${head}${pitchRows(key)}</table>`).join('<br>');
    }

    function renderLog() {
        const log = game.state.log.slice(-80).reverse();
        $('.log').innerHTML = log.map((l) => `<div class="${l.kind}"><span class="inn">${l.half === 'top' ? '▲' : '▼'}${l.inning}</span>${esc(l.text)}</div>`).join('');
    }

    function renderOdds(result) {
        const el = $('#odds');
        if (!prefs.showOdds || !result || !result.loc) { el.hidden = true; return; }
        const p = result.probs;
        const parts = [];
        const edge = edgeDistance(result.loc.x, result.loc.y);
        parts.push(`<b>${result.pitch.velocity.toFixed(1)} mph ${esc(result.pitch.name)}</b>, ${edge >= 0 ? `${edge.toFixed(1)}" inside the zone` : `${(-edge).toFixed(1)}" off the zone`}`);
        if (p.hbp > 0) parts.push(`HBP <b>${pct(p.hbp)}</b>`);
        if (p.swing !== undefined) parts.push(`swing <b>${pct(p.swing)}</b>`);
        if (p.strike !== undefined) parts.push(`called strike <b>${pct(p.strike)}</b>`);
        if (p.contact !== undefined) parts.push(`contact <b>${pct(p.contact)}</b>`);
        if (p.foul !== undefined) parts.push(`foul <b>${pct(p.foul)}</b>`);
        if (p.hit !== undefined) parts.push(`hit <b>${pct(p.hit)}</b>`);
        if (p.extraBase !== undefined) parts.push(`extra bases <b>${pct(p.extraBase)}</b>`);
        if (p.homer !== undefined) parts.push(`homer <b>${pct(p.homer)}</b>`);
        el.innerHTML = parts.join(' · ');
        el.hidden = false;
    }

    function renderHint() {
        let text = '';
        if (ui.mode === 'playback') text = ui.touch ? 'Tap the field to continue' : 'Click or press Space to continue';
        else if (ui.mode === 'sending') text = 'Sending the pitch…';
        else if (mp && !mp.myTurn && !game.state.over) text = 'Waiting for your opponent to pitch';
        else if (game.state.over) text = 'Game over';
        else if (game.isUserPitching()) {
            text = ui.mode === 'aiming' && ui.touch
                ? `Touch the field to aim, drag to adjust, lift to throw${guideMode() === 'hidden' ? ' (guide hidden: remember the break)' : ''}.`
                : ui.mode === 'aiming'
                ? `Click to release. The ball breaks from where you click${guideMode() === 'hidden' ? ' (guide hidden: remember the break)' : ''}.`
                : 'The dashed line shows how this pitch will break. Press Space or Pitch to start.';
        } else text = 'Your team is batting';
        $('#hint').textContent = text;
    }

    function refreshAll() {
        $('.g-left').classList.remove('busy');
        if (ui.scoutId === game.state.pa?.batterId) ui.scoutId = null;
        renderTop();
        if (game.state.over || ui.challengeResult) {
            $('.g-left').innerHTML = hudHTML();
        } else if (mp && !mp.myTurn) {
            renderMpWaiting();
            startMpPolling();
        } else if (game.isUserPitching()) {
            renderPitcherPanel();
        } else {
            renderOffensePanel();
        }
        renderRight();
        renderLog();
        renderHint();
        if (ui.challengeResult) showChallengeEnd();
        else if (game.state.over) showFinal();
        else if (career && !game.state.over && ui.mode === 'ready' && game.isUserPitching() && careerOut()) careerSimRest();
        else if (career) careerHookCheck();
        else if (ui.mode === 'ready' && game.isUserPitching() && game.mustChangePitcher(userKey)) showForcedChange();
        maybeStartClock();
        maybeCall();
    }

    function showFinal() {
        const st = game.state;
        const winner = game.team(st.winner);
        const userWon = userKey === st.winner;
        const pitching = boxScore();
        $('#overlay').innerHTML = `
            <div class="overlay"><div class="panel">
                <h2>${userWon ? 'You win!' : 'Tough loss.'}</h2>
                <div class="final-score">${game.team('away').abbr} ${st.score.away}, ${game.team('home').abbr} ${st.score.home}</div>
                <div class="muted" style="margin-bottom:12px">${esc(winner.city)} ${esc(winner.name)} win${st.inning > st.settings.innings ? ` in ${st.inning}` : ''}.</div>
                ${pitching}
                <div class="row-actions">
                    <button data-act="menu">Main menu</button>
                    ${career ? '<button class="primary" data-act="career">Back to the career</button>' : mp ? '<button class="primary" data-act="lobby">Back to multiplayer</button>' : inSeason ? '<button class="primary" data-act="season">Back to the season</button>' : '<button class="primary" data-act="again">Play again</button>'}
                </div>
            </div></div>`;
    }

    // ---------- stats, achievements, challenge ----------
    const userPitched = (r) => userKey && game.team(userKey).pitchers.includes(r.pitcherId);

    function processResults(results) {
        for (const r of results) {
            if (!userPitched(r)) continue;
            track(tracker, r);
            for (const id of checkAchievements(tracker, r, game, earned)) {
                earned.push(id);
                ui.toasts.push({ id, first: recordAchievement(id), result: r });
            }
            if (challenge && !ui.challengeResult) {
                const res = evaluateChallenge(challenge, tracker, r, game);
                if (res) settleChallenge(res);
            }
        }
        // The game can also end while your team bats (a walk-off).
        if (challenge && !ui.challengeResult && game.state.over) settleChallenge(evaluateChallengeAtEnd(challenge, tracker, game));
    }

    function settleChallenge(res) {
        ui.challengeResult = res;
        recordChallenge(challenge.id, res);
        game.log(res.status === 'win' ? `Challenge complete! ${'★'.repeat(res.stars)}` : `Challenge failed: ${res.reason}`, 'info');
    }

    // The league (with batters' records by pitch type) is saved with the
    // season, or on its own for quick games and challenges.
    function saveLeagueData() {
        if (career) app.saveCareer();
        else if (inSeason) app.saveSeason();
        else app.saveLeague();
    }

    function saveNow() {
        if (mp) return;   // the server keeps multiplayer games
        if (career) {
            if (game.state.over) {
                app.finishCareerGame(game, seasonGameId);
                app.clearGame();
            } else {
                app.saveGame(game, { careerId: career.id, seasonGameId, tracker, earned });
            }
            return;
        }
        if (game.state.over) saveLeagueData();
        if (game.state.over && inSeason) app.finishSeasonGame(game, seasonGameId);
        if (ui.challengeResult || game.state.over) app.clearGame();
        else app.saveGame(game, { tracker, earned, ...(inSeason ? { seasonGameId } : {}) });
    }

    // ---------- career ----------
    const careerOut = () => career && game.side(userKey).pitcherId !== PID;

    function careerHudHTML() {
        const b = game.pitchBox(PID);
        return `<div class="panel challenge-hud">
            <div class="card-head"><b>⭐ ${esc(career.first)} ${esc(career.last)}</b><button class="small" data-act="career">Career</button></div>
            <div class="goal">${careerOut() ? 'Out of the game.' : 'You’re on the mound until the manager comes to get you.'}</div>
            <div class="progress">${ipText(b.outs)} IP · ${b.h} H · ${b.r} R · ${b.bb} BB · ${b.k} K · ${b.pitches} pitches</div>
        </div>`;
    }

    // Before each batter, the manager may take the ball.
    function careerHookCheck() {
        if (!career || game.state.over || careerOut() || !game.isUserPitching() || ui.mode !== 'ready') return;
        const st = game.state;
        const b = game.pitchBox(PID);
        if (!b.pitches || st.pa.pitches.length) return;
        const key = `${st.inning}${st.half}${st.outs}${game.side(game.battingKey).batIdx}${b.pitches}`;
        if (ui.hookKey === key) return;
        ui.hookKey = key;
        const v = game.mustChangePitcher(userKey) ? 1 : F.eval('careerHook', { ...game.situationScope(), runsAllowed: b.r });
        if (uiRng.chance(v)) {
            const id = aiPickReliever(game, userKey);
            if (id) game.changePitcher(userKey, id);
            renderPitcherPanel();
            const line = game.pitchBox(PID);
            $('#overlay').innerHTML = `
                <div class="overlay"><div class="panel" style="max-width:480px;text-align:center">
                    <h2>The manager’s coming to get the ball</h2>
                    <p>${ipText(line.outs)} IP, ${line.h} H, ${line.r} R, ${line.bb} BB, ${line.k} K on ${line.pitches} pitches.</p>
                    <p class="muted">The bullpen takes it from here.</p>
                    <div class="row-actions" style="justify-content:center"><button class="primary" data-act="career-sim">Sim the rest of the game</button></div>
                </div></div>`;
        }
    }

    // He's out: the computer plays the rest.
    function careerSimRest() {
        $('#overlay').innerHTML = '';
        game.state.userTeamId = null;
        game.simToEnd();
        saveNow();
        refreshAll();
    }

    // ---------- multiplayer ----------
    // The server decides each pitch: send the inputs, then show its result.
    async function mpThrow(opts) {
        ui.mode = 'sending';
        renderHint();
        const before = game.state.pa.pitches.slice();
        const zonePos = { x: zone.x, y: zone.y };
        try {
            const { result, game: view } = await mpApi.pitch(mp.record.id, { version: mp.record.version, ...opts });
            adoptView(view);
            result.zone = zonePos;
            play([result], 'user', before);
        } catch (e) {
            ui.mode = 'ready';
            ui.mpStale = e;
            showMpStale(e);
        }
    }

    // Take the server's copy of the game (keeping this browser's side).
    function adoptView(view) {
        const userTeamId = game.state.userTeamId;
        mp.record = { ...mp.record, ...view };
        game.state = view.state;
        game.state.userTeamId = userTeamId;
    }

    async function mpChangePitcher(id) {
        try {
            adoptView(await mpApi.action(mp.record.id, { version: mp.record.version, action: { type: 'changePitcher', pitcherId: id } }));
            ui.pitchIdx = 0;
            $('#overlay').innerHTML = '';
            refreshAll();
        } catch (e) {
            ui.mpStale = e;
            showMpStale(e);
        }
    }

    function showMpStale(e) {
        const timedOut = /time ran out/i.test(e.message);
        if (e.status === 400 || e.status === 409 && /pitch limit/i.test(e.message)) {
            // A move the server refused: say why and carry on.
            ui.mpStale = null;
            alert(e.message);
            return;
        }
        $('#overlay').innerHTML = `
            <div class="overlay"><div class="panel" style="max-width:480px;text-align:center">
                <h2>${timedOut ? '⏰ Time’s up' : 'The game has moved on'}</h2>
                <p class="muted">${timedOut ? 'Your time for this half ran out, so the computer finished it for you.' : esc(e.message)}</p>
                <div class="row-actions" style="justify-content:center"><button class="primary" data-act="mp-reload">Continue</button></div>
            </div></div>`;
    }

    // Once your half is over (and saved), reload: it's either your turn
    // again (both players on this device) or time to wait.
    function mpHalfDone() {
        return mp?.myTurn && (game.state.over || `${game.state.inning}${game.state.half}` !== mpHalf);
    }

    function mpHudHTML() {
        if (!mp) return '';
        const rec = mp.record;
        const opp = ['home', 'away'].filter((k) => !mp.seats.includes(k)).map((k) => rec.seats[k]?.name ?? 'waiting').join('');
        const doing = rec.turn?.phase === 'manage' ? 'is setting up their hitters' : 'is pitching';
        const deadline = rec.turn?.deadline;
        const turnName = rec.turn ? rec.seats[rec.turn.key]?.name : null;
        return `<div class="panel challenge-hud mp-hud">
            <div class="card-head"><b>👥 ${mp.seats.length === 2 ? 'Two players, one device' : `vs ${esc(opp)}`}</b><button class="small" data-act="lobby">Lobby</button></div>
            <div class="goal">${rec.status === 'done' ? 'Final.' : mp.myTurn ? `Your half: pitch the ${game.state.half} of the ${ordinal(game.state.inning)}.` : `${esc(turnName ?? 'Your opponent')} ${doing}.`}</div>
            ${deadline && rec.status === 'active' ? `<div class="progress">⏱ <span id="mp-left" data-deadline="${deadline}">${timeLeft(deadline)}</span> left${mp.myTurn ? '' : ' for them'}</div>` : ''}
        </div>`;
    }

    function renderMpWaiting() {
        const rec = mp.record;
        const turnName = rec.turn ? rec.seats[rec.turn.key]?.name ?? 'Your opponent' : null;
        $('.g-left').innerHTML = `${mpHudHTML()}
            <div class="panel">
                <h3>${rec.status === 'waiting' ? 'Waiting for an opponent' : 'Their turn'}</h3>
                <p>${rec.status === 'waiting' ? `Share the code <b class="mp-code">${rec.code}</b> to invite someone.`
                    : rec.turn?.phase === 'manage' && mp.seats.includes(rec.turn.key) ? 'Your hitters are up next: set them up.'
                    : rec.turn?.phase === 'manage' ? `${esc(turnName)} is setting up their hitters before they bat. Then it’s your turn to pitch.`
                    : `${esc(turnName)} is pitching to your hitters. This page updates as they go; you’ll be up next.`}</p>
                <button data-act="lobby">Back to the lobby</button>
            </div>`;
    }

    // While waiting, check for their progress.
    function startMpPolling() {
        if (!mp || mp.myTurn || mpPoll || game.state.over) return;
        mpPoll = setInterval(async () => {
            try {
                const rec = await mpApi.get(mp.record.id);
                if (rec.version !== mp.record.version) app.go('mpGame', { id: rec.id });
            } catch { /* try again next time */ }
        }, 3000);
    }

    // At the pitch limit you must make a change before the next batter.
    function showForcedChange() {
        const pen = game.bullpen(userKey);
        const p = game.pitcher();
        $('#overlay').innerHTML = `
            <div class="overlay"><div class="panel" style="max-width:520px">
                <h2>Pitch limit reached</h2>
                <p class="muted">${esc(playerName(p))} has thrown ${game.pitcherStatus().pitches} pitches, the limit at this level. Bring in a reliever.</p>
                <table class="grid">${pen.map((id) => {
                    const r = league.players[id];
                    return `<tr><td>${esc(playerName(r))} <span class="muted" style="font-size:11px">${r.role} ${r.throws} · ${r.pitches.map((x) => PITCH_TYPES[x.type].abbr).join(' ')}</span></td>
                        <td class="r num">${r.velo}/${r.move}/${r.control}</td><td class="r"><button class="small" data-relieve="${id}">Bring in</button></td></tr>`;
                }).join('')}</table>
            </div></div>`;
    }

    // ---------- the catcher calls the pitches ----------
    // With the setting on, before each pitch the catcher picks the pitch and
    // the spot (engine/advice.js callPitch): the pitch is selected and the
    // spot is ringed on the zone. Shake him off for another pitch, or pick a
    // pitch yourself and he sets the spot for it.
    function maybeCall() {
        if (!catcherCalls() || ui.call || ui.mode !== 'ready' || !game.isUserPitching() || ui.challengeResult || $('#overlay').innerHTML) return;
        makeCall({});
        renderPitcherPanel();
    }
    function makeCall(opts) {
        const shaken = opts.shaken ?? [];
        const call = callPitch(game, { effort: ui.effort, moveEffort: ui.moveEffort }, uiRng, { exclude: shaken, pitchIdx: opts.pitchIdx ?? null });
        if (!call) return;
        ui.call = { ...call, shaken, mine: opts.pitchIdx != null };
        ui.pitchIdx = call.pitchIdx;
        ui.plan = { target: call.target, color: call.color, label: PITCH_TYPES[call.type].abbr };
    }
    function shakeOff() {
        if (!ui.call || ui.mode === 'playback') return;
        const n = game.pitcher().pitches.length;
        let shaken = [...ui.call.shaken, ui.call.pitchIdx];
        if (shaken.length >= n) shaken = [ui.call.pitchIdx];   // he goes back through them
        makeCall({ shaken });
        renderPitcherPanel();
    }
    function selectPitch(i) {
        if (catcherCalls() && ui.mode !== 'playback' && (!ui.call || ui.call.pitchIdx !== i)) makeCall({ pitchIdx: i });
        else ui.pitchIdx = i;
        renderPitcherPanel();
    }
    function callCard() {
        const c = ui.call;
        if (!catcherCalls() || !c) return '';
        return `<div class="call-card" style="border-color:${c.color}">
            <div class="call-sign"><span class="muted">${c.mine ? 'Your pitch; he sets up' : 'The catcher calls'}</span>
                <b>${pitchChip(c.type)} ${esc(c.type)}</b>, ${esc(c.where)}</div>
            ${c.reason && !c.mine ? `<div class="call-why">${esc(c.reason)}</div>` : ''}
            <button class="small" data-act="shake" ${ui.mode === 'playback' ? 'disabled' : ''} title="Ask for a different pitch">Shake off</button>
        </div>`;
    }
    // How close the pitch came to the spot it was called for.
    function spotText(r) {
        if (!r.spot || !r.loc) return '';
        const miss = Math.hypot(r.loc.x - r.spot.x, r.loc.y - r.spot.y);
        return miss <= 1.5 ? 'right on the spot' : `${miss.toFixed(1)}" off the spot`;
    }

    // ---------- the catcher's visit ----------
    // Once an inning you can call time: the clock stops, the zone resets,
    // and the catcher comes out with a plan for this batter (from the
    // formulas, see engine/advice.js).
    const visitKey = () => `${game.state.inning}${game.state.half}`;
    const visitUsed = () => (game.state.catcherVisits ?? []).includes(visitKey());

    function visitButton() {
        if (mp || !game.isUserPitching()) return '';
        const used = visitUsed();
        return `<button class="visit-btn" data-act="visit" ${used || ui.mode === 'playback' ? 'disabled' : ''}
            title="Stops the clock and resets it. One visit an inning.">🧢 Catcher’s visit <span class="muted">${used ? 'used this inning' : '1 left this inning'}</span></button>`;
    }

    function startVisit() {
        if (mp || !game.isUserPitching() || !['ready', 'aiming'].includes(ui.mode) || visitUsed() || $('#overlay').innerHTML) return;
        (game.state.catcherVisits ??= []).push(visitKey());
        const catcher = game.side(userKey).lineup.find((s) => s.pos === 'C');
        const catcherName = catcher ? shortName(league.players[catcher.id]) : 'The catcher';
        game.log(`Mound visit: ${catcherName} goes out to talk to ${shortName(game.pitcher())}.`, 'info');
        // Time is called: the clock and the zone start over afterwards.
        ui.clock = null;
        ui.mode = 'ready';
        const advice = catcherAdvice(game, { effort: ui.effort, moveEffort: ui.moveEffort });
        ui.visit = { advice };
        $('#overlay').innerHTML = visitHTML(advice, catcherName);
        saveNow();
        renderPitcherPanel();
        renderLog();
        renderHint();
    }

    // plan: the option chosen ({ pitchIdx, target, color }), or nothing.
    function endVisit(plan) {
        if (!ui.visit) return;
        ui.visit = null;
        $('#overlay').innerHTML = '';
        if (plan) {
            ui.pitchIdx = plan.pitchIdx;
            ui.plan = { target: plan.target, color: plan.color, label: PITCH_TYPES[plan.type].abbr };
            if (catcherCalls()) ui.call = { ...plan, reason: plan.reasons?.[0] ?? null, shaken: [] };
        }
        ui.clock = null;
        renderPitcherPanel();
        renderHint();
        maybeStartClock();
    }

    function visitHTML(a, catcherName) {
        const batter = game.batter();
        // A small picture of the plan, laid out like the field.
        // Plans on the same spot sit side by side.
        const spots = a.options.map((o, i) => {
            const near = a.options.slice(0, i).some((p) => Math.hypot(p.target.x - o.target.x, p.target.y - o.target.y) < 3);
            return { x: o.target.x + (near ? 2.4 : 0), y: -o.target.y + (near ? 2.4 : 0) };
        });
        const dot = (o, i) => `<g><circle cx="${spots[i].x}" cy="${spots[i].y}" r="2.3" fill="${o.color}" stroke="#fff" stroke-width="0.35"/>
            <text x="${spots[i].x}" y="${spots[i].y + 0.9}" text-anchor="middle" font-size="2.6" font-weight="700" fill="#fff">${i + 1}</text></g>`;
        const av = a.avoid;
        const svg = `<svg class="visit-zone" viewBox="-17 -21 34 42" aria-label="Where to throw">
            <rect x="-17" y="-21" width="34" height="42" fill="#123a28"/>
            ${av ? `<g stroke="#ff6b6b" stroke-width="0.5"><circle cx="${av.target.x}" cy="${-av.target.y}" r="2.6" fill="rgba(229,72,77,0.25)"/>
                <path d="M${av.target.x - 1.4} ${-av.target.y - 1.4}l2.8 2.8M${av.target.x + 1.4} ${-av.target.y - 1.4}l-2.8 2.8"/></g>` : ''}
            <g stroke="rgba(255,255,255,0.25)" stroke-width="0.2">
                <path d="M${-ZONE.halfW / 3} ${-ZONE.halfH}v${2 * ZONE.halfH}M${ZONE.halfW / 3} ${-ZONE.halfH}v${2 * ZONE.halfH}M${-ZONE.halfW} ${-ZONE.halfH / 3}h${2 * ZONE.halfW}M${-ZONE.halfW} ${ZONE.halfH / 3}h${2 * ZONE.halfW}"/>
            </g>
            <rect x="${-ZONE.halfW}" y="${-ZONE.halfH}" width="${2 * ZONE.halfW}" height="${2 * ZONE.halfH}" fill="none" stroke="#fff" stroke-width="0.4"/>
            <text x="${a.side === 'R' ? -14.5 : 14.5}" y="1" text-anchor="middle" font-size="2.6" fill="#cfd8d3">${a.side}HB</text>
            ${a.options.map(dot).reverse().join('')}
        </svg>`;
        const opt = (o, i) => `<div class="visit-opt">
            <div class="card-head"><span><b>${i + 1}.</b> ${pitchChip(o.type)} <b>${esc(o.type)}</b>, ${esc(o.where)}</span>
                <button class="primary small" data-act="visit-plan" data-opt="${i}">Throw it</button></div>
            <div class="muted num">${pct(o.strike)} strike · ${pct(o.whiff)} whiff · ${pct(o.ball)} ball · ${pct(o.inPlay)} in play · ${pct(o.hit)} hit</div>
            ${o.reasons.length ? `<ul>${o.reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>` : ''}
            <div class="aim-note">${esc(o.aimNote)}</div>
        </div>`;
        return `<div class="overlay"><div class="panel visit">
            <h2>🧢 ${esc(catcherName)} comes out <span class="muted" style="font-size:14px;font-weight:400">count ${a.count} · ${esc(playerName(batter))} bats ${a.side === 'R' ? 'right' : 'left'}</span></h2>
            <p class="visit-quote">“${esc(a.headline)}”</p>
            <div class="visit-body">
                <div class="visit-opts">${a.options.map(opt).join('')}
                    ${av ? `<div class="visit-avoid">✕ Don’t leave a ${esc(av.type.toLowerCase())} ${esc(av.where)}: that’s his best shot at you (${pct(av.hit)} hit, ${pct(av.xbh)} extra bases).</div>` : ''}
                </div>
                ${svg}
            </div>
            <h3>On ${esc(shortName(batter))}</h3>
            <ul class="visit-notes">${a.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>
            <div class="row-actions">
                <span class="muted" style="font-size:12px">The clock starts over when he goes back. Pick a plan to mark its spot on the zone.</span>
                <button data-act="visit-done">Back to work</button>
            </div>
        </div></div>`;
    }

    function showToast(t) {
        const a = ACHIEVEMENT_BY_ID[t.id];
        const el = document.createElement('div');
        el.className = 'toast';
        el.innerHTML = `<div class="icon">${a.icon}</div><div><div class="t-title">${t.first ? 'Achievement unlocked' : 'Achievement'}</div><div class="t-name">${esc(a.name)}</div><div class="muted" style="font-size:12px">${esc(a.desc)}</div></div>`;
        $('.toasts').appendChild(el);
        setTimeout(() => el.remove(), 5000);
    }

    // Challenges with autoOffense sim your team's turn at bat straight away.
    // When your team bats: challenges and careers sim the half-inning in one
    // go; otherwise, with the auto setting (the default), it is simmed and
    // each batter's last pitch is played back. Returns 'played' if that
    // playback has started.
    function autoOffense() {
        if (ui.challengeResult || !game.isUserBatting() || ui.mode !== 'ready') return false;
        if (!(challenge?.autoOffense || career)) {
            if (mp || !autoBat()) return false;
            refreshAll();
            const rs = game.simHalfInning();
            play(rs.filter((r) => r.paEnded), 'fast', [], rs);
            renderOffensePanel();
            $('.g-left').classList.add('busy');
            return 'played';
        }
        const before = game.state.score[userKey];
        game.simHalfInning();
        const runs = game.state.score[userKey] - before;
        processResults([]);
        saveNow();
        const el = document.createElement('div');
        el.className = 'toast';
        el.innerHTML = `<div class="icon">🏏</div><div><div class="t-title">Your offense</div><div class="t-name">${runs ? `${runs} run${runs > 1 ? 's' : ''} scored` : 'Held scoreless'}</div></div>`;
        $('.toasts').appendChild(el);
        setTimeout(() => el.remove(), 3000);
        return true;
    }

    function hudHTML() {
        if (mp) return mpHudHTML();
        if (career) return careerHudHTML();
        if (!challenge) return '';
        const rec = challengeRecords()[challenge.id];
        return `<div class="panel challenge-hud">
            <div class="card-head"><b>${challenge.icon} ${esc(challenge.name)}</b>${starsHTML(rec?.stars ?? 0)}</div>
            <div class="goal">${esc(challenge.desc)}</div>
            <div class="progress">${esc(challenge.progress(tracker.inning ? tracker : { ...tracker, inning: blankInning() }, game))}</div>
        </div>`;
    }
    const blankInning = () => ({ pitches: 0, strikes: 0, swinging: 0, bf: 0, outs: 0, k: 0, outsK: 0, runs: 0, baserunners: 0, bb: 0, hbp: 0, clock: 0 });

    function showChallengeEnd() {
        const res = ui.challengeResult;
        const rec = challengeRecords()[challenge.id];
        const g = tracker.game;
        $('#overlay').innerHTML = `
            <div class="overlay"><div class="panel" style="max-width:560px;text-align:center">
                <div style="font-size:48px">${res.status === 'win' ? challenge.icon : '😖'}</div>
                <h2>${res.status === 'win' ? 'Challenge complete!' : 'Challenge failed'}</h2>
                <div style="font-size:30px;margin:6px 0">${starsHTML(res.status === 'win' ? res.stars : 0)}</div>
                <div class="muted" style="margin-bottom:10px">${res.status === 'win' ? esc(challenge.stars[res.stars - 1]) : esc(res.reason)}</div>
                <div class="muted" style="font-size:13px">${g.pitches} pitches · ${g.k} K · ${g.hits} H · ${g.bb} BB · ${g.runs} R</div>
                <div class="muted" style="font-size:12px;margin-top:6px">Best: ${starsHTML(rec?.stars ?? 0)} · ${plural(rec?.wins ?? 0, 'win')} in ${plural(rec?.attempts ?? 0, 'try', 'tries')}</div>
                <div class="row-actions" style="justify-content:center">
                    <button data-act="menu">Menu</button>
                    <button data-act="challenges">All challenges</button>
                    <button class="primary" data-act="retry">Try again</button>
                </div>
            </div></div>`;
    }

    // ---------- actions ----------
    function startAiming() {
        if (ui.mode !== 'ready' || !game.isUserPitching() || ui.challengeResult || ui.mpStale) return;
        if (mp && !mp.myTurn) return;
        if (ui.visit) return;
        if (career && (careerOut() || $('#overlay').innerHTML)) return;
        if (!career && game.mustChangePitcher(userKey)) { showForcedChange(); return; }
        const scope = game.situationScope();
        zone.start(scope);
        if (clockMode() === 'press') ui.clock = startClock();
        ui.mode = 'aiming';
        ui.markers = null;
        renderPitcherPanel();
        renderHint();
    }

    // Pitch clock: 'press' starts it when you press Pitch, 'continuous'
    // runs it from the end of the last pitch, 'off' has none. The Pitch
    // Clock Panic challenge always has one.
    function clockMode() {
        const mode = prefs.clockMode ?? 'press';
        return challenge?.id === 'clock' && mode === 'off' ? 'press' : mode;
    }
    function startClock() {
        const total = F.eval('pitchClock', { ...game.situationScope(), clockSetting: clockSeconds() });
        return { total, left: total };
    }
    // Between pitches with the continuous clock, start it once you're up.
    function maybeStartClock() {
        if (clockMode() === 'continuous' && !ui.clock && ui.mode === 'ready' && game.isUserPitching() && !ui.challengeResult) ui.clock = startClock();
    }
    const clockPaused = () => !!$('#overlay').innerHTML || !game.isUserPitching() || ui.challengeResult;

    function release(pt) {
        if (ui.mode !== 'aiming' && !(ui.mode === 'ready' && !pt)) return;
        const opts = { pitchIdx: ui.pitchIdx, effort: ui.effort, moveEffort: ui.moveEffort, t: zone.t, clockLeft: ui.clock?.left ?? null };
        ui.clock = null;
        const spot = ui.plan?.target ?? null;
        ui.plan = null;
        ui.call = null;
        if (pt) opts.aim = { x: pt.x - zone.x, y: pt.y - zone.y };
        else opts.clockViolation = true;
        if (mp) { mpThrow(opts); return; }
        const before = game.state.pa.pitches.slice();
        const result = game.throwPitch(opts);
        result.zone = { x: zone.x, y: zone.y };
        result.spot = spot;
        play([result], 'user', before);
    }

    // Show results one by one (a pitch in flight, then a banner).
    // `before` is the at-bat's earlier pitches, drawn as markers meanwhile.
    // `all` is every pitch thrown (for stats) when only some are shown.
    function play(results, speed, before = [], all = results) {
        processResults(all);
        saveNow();
        if (!results.length) { refreshAll(); return; }
        ui.markers = before;
        ui.queue = results.map((r) => ({ result: r, speed }));
        ui.current = null;
        ui.mode = 'playback';
        $('.g-left').classList.add('busy');
        renderHint();
    }

    function nextInQueue() {
        const item = ui.queue.shift();
        if (!item) {
            ui.current = null;
            ui.mode = 'ready';
            ui.markers = null;
            if (mpHalfDone()) {
                mpPending.then(() => { if (!ui.mpStale) app.go('mpGame', { id: mp.record.id }); });
                return;
            }
            if (!ui.challengeResult && autoOffense() === 'played') return;
            refreshAll();
            return;
        }
        const r = item.result;
        const fast = item.speed === 'fast';
        const batter = league.players[r.batterId];
        ui.side = battingSide(batter, league.players[r.pitcherId]);
        ui.heat = batter.heat;
        const z = r.zone || { x: 0, y: 0 };
        const dur = r.loc ? (fast ? 0.32 : 0.55) * Math.pow(95 / r.pitch.velocity, 1.5) : 0;
        ui.current = {
            result: r, t: 0, dur,
            hold: fast ? (r.paEnded ? 1.0 : 0.45) : (r.paEnded ? 1.6 : 0.9),
            from: r.aim ? { x: z.x + r.aim.x, y: z.y + r.aim.y } : null,
            to: r.loc ? { x: z.x + r.loc.x, y: z.y + r.loc.y } : null,
            zone: z,
            landed: false,
        };
        ui.lastResult = r;
    }

    function landCurrent() {
        const c = ui.current;
        c.landed = true;
        const r = c.result;
        ui.markers = ui.markers || [];
        if (r.loc) ui.markers.push({ x: r.loc.x, y: r.loc.y, color: r.pitch.color, call: r.call });
        if (r.after) renderTop(r.after);
        renderOdds(r);
        for (const t of ui.toasts.filter((x) => x.result === r)) showToast(t);
        ui.toasts = ui.toasts.filter((x) => x.result !== r);
    }

    function bannerFor(r) {
        const spot = spotText(r);
        const sub = `${r.pitch.velocity.toFixed(1)} mph ${r.pitch.name}${spot ? ` · ${spot}` : ''}`;
        if (r.play) {
            const [text, color] = PLAY_BANNERS[r.play] || [r.play, '#fff'];
            // Colours are from the pitcher's side: green is good for the user
            // when pitching, so flip them when the user bats.
            const flip = userKey && !game.team(userKey).pitchers.includes(r.pitcherId);
            return { text: r.runs ? `${text} · ${r.runs} RUN${r.runs > 1 ? 'S' : ''}` : text, sub: spot ? `${r.text} · ${spot}` : r.text, color: flip ? swapColor(color) : color };
        }
        const [text, color] = CALL_BANNERS[r.call] || [r.text, '#fff'];
        return { text, sub, color };
    }

    // ---------- loop ----------
    let raf = 0;
    let last = performance.now();
    function frame(now) {
        const dt = Math.min(0.05, (now - last) / 1000);
        last = now;

        if (ui.clock && (ui.mode === 'aiming' || ui.mode === 'ready') && !clockPaused()) {
            ui.clock.left -= dt;
            if (ui.clock.left <= 0) release(null);
        }
        if (ui.mode === 'aiming') {
            zone.update(dt);
        } else if (ui.mode === 'playback') {
            if (!ui.current) nextInQueue();
            const c = ui.current;
            if (c) {
                c.t += dt;
                if (!c.landed && c.t >= c.dur) landCurrent();
                if (c.t >= c.dur + c.hold) {
                    if (c.result.paEnded) ui.markers = [];
                    // Refresh panels after each pitch so the count keeps up.
                    if (ui.queue.length) { renderTop(); renderLog(); }
                    ui.current = null;
                    if (!ui.queue.length) nextInQueue();
                }
            }
        }
        draw();
        raf = requestAnimationFrame(frame);
    }

    function guideFor() {
        const pv = game.previewPitch(ui.pitchIdx, ui);
        return { dx: pv.dx, dy: pv.dy, scatter: pv.scatter, color: pv.color, label: `${pv.abbr} ${pv.velocity.toFixed(0)}` };
    }

    function draw() {
        const userPitching = game.isUserPitching();
        const c = ui.current;
        const zonePos = c ? c.zone : userPitching ? { x: zone.x, y: zone.y } : { x: 0, y: 0 };

        const batter = game.state.over ? null : game.batter();
        const side = ui.mode === 'playback' && ui.side ? ui.side : batter ? battingSide(batter, game.pitcher()) : null;
        const shownId = c ? c.result.batterId : batter?.id;
        let swing = null;
        if (c && SWING_CALLS.includes(c.result.call) && c.from) {
            // Timed so the bat meets the ball as it arrives.
            swing = Math.max(0, Math.min(1, (c.t - (c.dur - 0.15)) / 0.3));
        }
        const batterPic = side && shownId ? {
            side, swing, time: performance.now() / 1000,
            color: batterLook(shownId).color, number: batterLook(shownId).number, skin: batterLook(shownId).skin,
        } : null;
        const heat = ui.mode === 'playback' && ui.heat ? ui.heat : batter?.heat;

        // The break guide: before you press Pitch it always shows how the
        // pitch will move (from the pointer, or the middle of the zone); once
        // the zone moves it stays only if the guide is set to always shown.
        let guide = null;
        let aim = null;
        const previewing = ui.mode === 'ready' && userPitching && !$('#overlay').innerHTML && !(mp && !mp.myTurn);
        if (ui.mode === 'aiming') {
            aim = ui.mouse;
            if (guideMode() === 'show') guide = guideFor();
        } else if (previewing) {
            aim = ui.mouse ?? { x: zonePos.x, y: zonePos.y };
            guide = guideFor();
        }
        let flight = null;
        if (c && c.from && c.to && !c.landed) flight = { from: c.from, to: c.to, p: Math.min(1, c.t / c.dur), color: c.result.pitch.color };
        const markers = ui.markers ?? (game.state.pa ? game.state.pa.pitches : []);

        plate.draw({
            zone: zonePos,
            side, heat, showHeat: prefs.showHeat, batter: batterPic,
            pitches: markers,
            aim,
            guide,
            plan: ui.plan && userPitching && ui.mode !== 'playback' ? { x: zonePos.x + ui.plan.target.x, y: zonePos.y + ui.plan.target.y, color: ui.plan.color, label: ui.plan.label } : null,
            flight,
            // Like a stadium clock, it only shows for the last ten seconds.
            clock: ui.clock && game.isUserPitching() && ui.mode !== 'playback' && ui.clock.left <= 10 ? { left: Math.max(0, ui.clock.left), total: Math.min(10, ui.clock.total) } : null,
            banner: c && c.landed ? bannerFor(c.result) : null,
            zoneColor: ui.mode === 'aiming' ? '#ffffff' : '#cfd8d3',
        });
    }

    // ---------- events ----------
    const onClick = (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.pitch !== undefined) {
            selectPitch(Number(btn.dataset.pitch));
        } else if (btn.dataset.tab) {
            ui.tab = btn.dataset.tab;
            renderRight();
        } else if (btn.dataset.scout) {
            ui.scoutId = Number(btn.dataset.scout);
            ui.tab = 'batter';
            renderRight();
        } else if (btn.dataset.relieve && mp) {
            mpChangePitcher(Number(btn.dataset.relieve));
        } else if (btn.dataset.relieve) {
            game.changePitcher(userKey, Number(btn.dataset.relieve));
            ui.pitchIdx = 0;
            ui.call = null;
            ui.plan = null;
            $('#overlay').innerHTML = '';
            saveNow();
            refreshAll();
        } else {
            switch (btn.dataset.act) {
                case 'menu': app.go('menu'); break;
                case 'again': app.go('lineup'); break;
                case 'retry': playChallenge(app, challenge.id); break;
                case 'challenges': app.go('challenges'); break;
                case 'season': app.go('season'); break;
                case 'lobby': app.go('multiplayer'); break;
                case 'career': app.go('careerHub', { id: career.id }); break;
                case 'career-sim': careerSimRest(); break;
                case 'mp-reload': app.go('mpGame', { id: mp.record.id }); break;
                case 'unscout': ui.scoutId = null; renderRight(); break;
                case 'pitch': startAiming(); break;
                case 'visit': startVisit(); break;
                case 'shake': shakeOff(); break;
                case 'visit-done': endVisit(); break;
                case 'visit-plan': endVisit(ui.visit.advice.options[Number(btn.dataset.opt)]); break;
                case 'sim-pa':
                    if (ui.mode === 'ready') {
                        const before = game.state.pa.pitches.slice();
                        play(game.simPlateAppearance(), 'fast', before);
                    }
                    break;
                case 'sim-half':
                    if (ui.mode === 'ready') {
                        const rs = game.simHalfInning();
                        // Show only the final pitch of each at-bat.
                        play(rs.filter((r) => r.paEnded), 'fast', [], rs);
                    }
                    break;
                case 'pinch': {
                    const id = Number($('#ph-pick').value);
                    game.pinchHit(game.battingKey, id);
                    saveNow();
                    refreshAll();
                    break;
                }
            }
        }
    };
    const onInput = (e) => {
        const s = e.target.dataset.slider;
        if (s) {
            ui[s] = Number(e.target.value);
            updatePreview();
        }
    };
    const onChange = (e) => {
        const map = { 't-heat': 'showHeat', 't-odds': 'showOdds' };
        if (e.target.id === 't-calls') {
            prefs.catcherCalls = e.target.checked;
            app.savePrefs();
            e.target.blur();
            if (!prefs.catcherCalls) { ui.call = null; ui.plan = null; }
            if (ui.mode === 'ready') { maybeCall(); renderPitcherPanel(); }
        } else if (e.target.id === 't-autobat') {
            prefs.autoBat = e.target.checked;
            app.savePrefs();
            e.target.blur();
            if (prefs.autoBat && ui.mode === 'ready') autoOffense();
        } else if (e.target.id === 't-guide') {
            prefs.guideMode = e.target.value;
            app.savePrefs();
            e.target.blur();
        } else if (e.target.id === 't-clock-secs') {
            prefs.clockSeconds = Number(e.target.value);
            app.savePrefs();
            e.target.blur();
            if (ui.mode === 'ready') { ui.clock = null; maybeStartClock(); }
        } else if (map[e.target.id]) {
            prefs[map[e.target.id]] = e.target.checked;
            app.savePrefs();
            if (e.target.id === 't-odds') renderOdds(ui.lastResult);
        } else if (e.target.id === 't-clock') {
            prefs.clockMode = e.target.value;
            app.savePrefs();
            e.target.blur();
            if (ui.mode === 'ready') { ui.clock = null; maybeStartClock(); }
        }
    };
    // Mouse: click to throw. Touch: put a finger down to aim, drag to adjust
    // (the break guide follows), lift to throw.
    const onPointerMove = (e) => { ui.mouse = plate.toInches(e); };
    const onPointerLeave = () => { if (ui.mode !== 'aiming') ui.mouse = null; };
    const onPointerUp = (e) => {
        if (!ui.touchAim) return;
        ui.touchAim = false;
        ui.mouse = plate.toInches(e);
        if (ui.mode === 'aiming') release(ui.mouse);
    };
    const onPointerCancel = () => { ui.touchAim = false; };
    const onPointerDown = (e) => {
        ui.mouse = plate.toInches(e);
        if (e.pointerType === 'touch' && !ui.touch) { ui.touch = true; renderHint(); }
        if (ui.mode === 'aiming' && e.pointerType === 'touch') {
            ui.touchAim = true;
            canvas.setPointerCapture?.(e.pointerId);
        } else if (ui.mode === 'aiming') release(ui.mouse);
        else if (ui.mode === 'playback') skip();
        else if (ui.mode === 'ready' && game.isUserPitching()) startAiming();
    };
    const skip = () => {
        const c = ui.current;
        if (c && c.landed) c.t = c.dur + c.hold;
        else if (c) c.t = c.dur;
    };
    const onKey = (e) => {
        if (e.target.tagName === 'SELECT' || (e.target.tagName === 'INPUT' && !['range', 'checkbox'].includes(e.target.type))) return;
        if (ui.visit) {
            if (e.code === 'Escape' || e.code === 'Space') { e.preventDefault(); endVisit(); }
            return;
        }
        if (e.code === 'Space') {
            // Space always pitches, even if a button or checkbox has focus.
            e.preventDefault();
            if (e.target.blur) e.target.blur();
            if (ui.mode === 'ready') startAiming();
            else if (ui.mode === 'playback') skip();
        } else if (ui.mode !== 'playback' && game.isUserPitching() && !e.metaKey && !e.ctrlKey && !e.altKey) {
            // Each pitch has a letter (shown on its button) and a number.
            const pitches = game.pitcher().pitches;
            let i = -1;
            if (/^Digit[1-9]$/.test(e.code)) i = Number(e.code.slice(5)) - 1;
            else if (/^Key[A-Z]$/.test(e.code)) i = pitchKeys(pitches).indexOf(e.code.slice(3));
            if (i >= 0 && i < pitches.length) {
                e.preventDefault();
                selectPitch(i);
            }
        }
    };
    const onResize = () => plate.resize();

    app.root.addEventListener('click', onClick);
    app.root.addEventListener('input', onInput);
    app.root.addEventListener('change', onChange);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerleave', onPointerLeave);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerCancel);
    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);

    plate.resize();
    if (autoOffense() !== 'played') refreshAll();
    raf = requestAnimationFrame(frame);

    // The turn clock: count down, and when it runs out on your turn, let the
    // server finish the half.
    const mpTicker = mp ? setInterval(() => {
        const el = $('#mp-left');
        if (!el) return;
        const deadline = Number(el.dataset.deadline);
        el.textContent = timeLeft(deadline);
        el.classList.toggle('low', deadline - Date.now() < 30000);
        if (mp.myTurn && Date.now() > deadline + 1000 && !ui.mpStale) {
            ui.mpStale = new Error('Time ran out for this half.');
            mpPending.then(() => mpApi.get(mp.record.id)).finally(() => showMpStale(ui.mpStale));
        }
    }, 1000) : 0;

    return () => {
        cancelAnimationFrame(raf);
        clearInterval(mpPoll);
        clearInterval(mpTicker);
        if (!mp) saveLeagueData();
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('input', onInput);
        app.root.removeEventListener('change', onChange);
        window.removeEventListener('keydown', onKey);
        window.removeEventListener('resize', onResize);
    };

    // ---------- helpers ----------
    // Team colours, a jersey number and a look for each batter.
    function batterLook(id) {
        const team = league.teams.find((t) => t.batters.includes(id));
        return { color: team?.color ?? '#2a4b8d', number: (id * 37) % 98 + 1, skin: SKINS[(id * 13) % SKINS.length] };
    }

    function todayLine(id) {
        const b = game.state.box.bat[id];
        if (!b || !b.pa) return '<span class="muted">—</span>';
        const extras = [];
        if (b.hr) extras.push(b.hr > 1 ? `${b.hr} HR` : 'HR');
        if (b.d) extras.push(b.d > 1 ? `${b.d} 2B` : '2B');
        if (b.t) extras.push('3B');
        if (b.bb) extras.push(b.bb > 1 ? `${b.bb} BB` : 'BB');
        if (b.k) extras.push(b.k > 1 ? `${b.k} K` : 'K');
        return `${b.h}-${b.ab}${extras.length ? ', ' + extras.join(', ') : ''}`;
    }
}

const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;

const SWING_CALLS = ['swinging', 'foul', 'inplay', 'caught'];
const SKINS = ['#f1c7a3', '#e0ac85', '#c68b59', '#a8704a', '#8d5a3b', '#6b4430'];

function ipText(outs) {
    return `${Math.floor(outs / 3)}.${outs % 3}`;
}

function callWord(call) {
    return { ball: 'ball', called: 'called strike', swinging: 'swinging strike', foul: 'foul', inplay: 'in play', hbp: 'HBP', clock: 'clock violation', caught: 'caught (strike)' }[call] || call;
}

function swapColor(color) {
    if (color === '#3dd68c') return '#ff6b6b';
    if (color === '#ff6b6b') return '#3dd68c';
    return color;
}

export { pitchChip };
