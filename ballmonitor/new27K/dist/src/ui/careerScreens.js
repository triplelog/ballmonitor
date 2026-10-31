// Career mode screens: your careers, a new pitcher, the career hub (his
// ratings and training, this season and his starts), the off-season
// decisions, and the end of a career.

import { LEVELS } from '../engine/levels.js';
import { PITCH_TYPES, FIRST_NAMES, LAST_NAMES, TEAMS } from '../engine/data.js';
import { STATES } from '../engine/regions.js';
import { teamName } from '../engine/league.js';
import { createRng } from '../engine/rng.js';
import { isUserGame, teamRecord, gameLabel, makeGame } from '../engine/season.js';
import {
    createCareer, careerName, startCareerSeason, careerStep, careerGame, markStart, recordCareerGame, finishSeason,
    seasonLine, trainCost, train, learnable, learnPitch, pitchCost, choose, careerTotals, hallOfFame, upcoming,
    pitcherAt, STYLES, PLAY_MODES, PID, youthRegion, prospectScore,
} from '../engine/career.js';
import { careerStore } from './idb.js';
import { esc } from './storage.js';

const LEVEL_NAMES = { youth: 'Youth', hs: 'High school', college: 'College', pro: 'Pro' };
const DIFF_NAMES = ['', 'Rookie', 'Pro', 'All-Star', 'MVP', 'Chaos'];
const ipText = (outs) => `${Math.floor(outs / 3)}.${outs % 3}`;
const era = (v) => (Number.isFinite(v) ? v.toFixed(2) : '–');

// ---------- the list, and a new career ----------
export function renderCareers(app) {
    let careers = null;
    const rng = createRng(Date.now() >>> 0);
    const form = {
        first: rng.pick(FIRST_NAMES), last: rng.pick(LAST_NAMES), throws: 'R', style: 'power',
        state: app.prefs.hsState ?? 'TX', city: null, play: 'all', difficulty: app.prefs.difficulty ?? 2, proGames: 60,
    };
    form.city = STATES[form.state][1].split(', ')[0];

    const draw = () => {
        const cities = STATES[form.state][1].split(', ');
        const list = careers === null ? '<div class="muted">Loading…</div>' : careers.length ? careers.map((c) => `
            <div class="career-row">
                <div><b>${esc(careerName(c))}</b> <span class="muted">${c.throws}HP · ${STYLES[c.style]?.name ?? ''} · from ${esc(c.city)}, ${esc(STATES[c.state][0])}</span>
                <div class="muted" style="font-size:12px">${c.retired ? `Retired at ${c.age} · Hall of Fame score ${hallOfFame(c)}` : `Age ${c.age} · ${stageText(c)}`} · ${c.history.length} season${c.history.length === 1 ? '' : 's'}</div></div>
                <div class="mp-actions"><button class="primary" data-open="${c.id}">${c.retired ? 'View' : 'Continue'}</button><button class="small" data-delete="${c.id}">Delete</button></div>
            </div>`).join('') : '<div class="muted">No careers yet.</div>';
        app.root.innerHTML = `
        <div class="page wide">
            <div class="page-head"><button data-act="back">← Menu</button><h1>Career</h1></div>
            <div class="cols-2">
                <div class="panel"><h3>Your careers</h3><div class="career-list">${list}</div></div>
                <div class="panel">
                    <h3>A new pitcher</h3>
                    <div class="form-grid" style="grid-template-columns: 110px 1fr">
                        <label>Name</label>
                        <div style="display:flex;gap:6px"><input id="c-first" value="${esc(form.first)}" style="flex:1"><input id="c-last" value="${esc(form.last)}" style="flex:1"></div>
                        <label>Throws</label>
                        <select id="c-throws"><option value="R" ${form.throws === 'R' ? 'selected' : ''}>Right</option><option value="L" ${form.throws === 'L' ? 'selected' : ''}>Left</option></select>
                        <label>Style</label>
                        <div class="style-pick">${Object.entries(STYLES).map(([k, s]) => `<label class="team-pick ${form.style === k ? 'sel' : ''}"><input type="radio" name="style" value="${k}" ${form.style === k ? 'checked' : ''}>
                            <span><b>${s.name}</b> <span class="muted" style="font-size:12px">${esc(s.desc)} Starts with ${s.pitches.join(' and ')}.</span></span></label>`).join('')}</div>
                        <label>Hometown</label>
                        <div style="display:flex;gap:6px">
                            <select id="c-state">${Object.entries(STATES).sort((a, b) => a[1][0].localeCompare(b[1][0])).map(([abbr, [name]]) => `<option value="${abbr}" ${abbr === form.state ? 'selected' : ''}>${name}</option>`).join('')}</select>
                            <select id="c-city" style="flex:1">${cities.map((c) => `<option ${c === form.city ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
                        </div>
                        <div class="hint">At 12 he pitches for ${esc(youthRegion(form.state, form.city))} in the Youth World Tournament, then for ${esc(form.city)} High.</div>
                        <label>Your starts</label>
                        <select id="c-play">${Object.entries(PLAY_MODES).map(([k, v]) => `<option value="${k}" ${k === form.play ? 'selected' : ''}>${v}</option>`).join('')}</select>
                        <div class="hint">The rest are simmed. You can change this any time.</div>
                        <label>Pro seasons</label>
                        <select id="c-pro">${[30, 60, 162].map((n) => `<option ${n === form.proGames ? 'selected' : ''}>${n}</option>`).join('')}</select>
                        <label>Difficulty</label>
                        <select id="c-diff">${[1, 2, 3, 4, 5].map((d) => `<option value="${d}" ${d === form.difficulty ? 'selected' : ''}>${DIFF_NAMES[d]}</option>`).join('')}</select>
                    </div>
                    <div class="row-actions"><button class="primary big" data-act="create">Start his career</button></div>
                </div>
            </div>
        </div>`;
    };
    const read = () => {
        const $ = (id) => app.root.querySelector('#' + id);
        form.first = $('c-first').value.trim() || form.first;
        form.last = $('c-last').value.trim() || form.last;
        form.throws = $('c-throws').value;
        form.play = $('c-play').value;
        form.proGames = Number($('c-pro').value);
        form.difficulty = Number($('c-diff').value);
    };
    const onClick = async (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.act === 'back') return app.go('menu');
        if (btn.dataset.open) return app.go('careerHub', { id: btn.dataset.open });
        if (btn.dataset.delete) {
            if (!confirm('Delete this career for good?')) return;
            await careerStore.remove(btn.dataset.delete);
            if (app.career?.id === btn.dataset.delete) app.career = null;
            careers = await careerStore.list();
            draw();
            return;
        }
        if (btn.dataset.act === 'create') {
            read();
            const career = createCareer({ ...form, seed: Date.now() >>> 0 });
            app.career = career;
            await app.saveCareer();
            app.go('careerHub', { id: career.id });
        }
    };
    const onChange = (e) => {
        if (e.target.name === 'style') { read(); form.style = e.target.value; draw(); }
        if (e.target.id === 'c-state') { read(); form.state = e.target.value; form.city = STATES[form.state][1].split(', ')[0]; draw(); }
        if (e.target.id === 'c-city') { read(); form.city = e.target.value; draw(); }
    };
    app.root.addEventListener('click', onClick);
    app.root.addEventListener('change', onChange);
    draw();
    // When the list arrives, keep whatever has been typed into the form.
    const redraw = () => { if (app.root.querySelector('#c-first')) read(); draw(); };
    careerStore.list().then((list) => { careers = list.sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0)); redraw(); })
        .catch(() => { careers = []; redraw(); });
    return () => {
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('change', onChange);
    };
}

function stageText(c) {
    switch (c.stage) {
        case 'youth': return 'Youth World Tournament';
        case 'hs': return `High school, year ${c.levelYear}`;
        case 'college': return `College, year ${c.levelYear}`;
        case 'pro': return `Pro, year ${c.levelYear}`;
        case 'decision': return 'Choosing: college or the draft';
        case 'collegeDecision': return 'Choosing: the draft or a senior year';
        case 'draft': return 'Entering the draft';
        case 'freeAgency': return 'Free agent';
        default: return 'Retired';
    }
}

// ---------- the hub ----------
export function renderCareerHub(app, args) {
    let cleanup = null;
    let cancelled = false;
    app.root.innerHTML = '<div class="page"><p class="muted">Loading career…</p></div>';
    app.loadCareer(args.id).then((career) => {
        if (cancelled) return;
        if (!career) { app.go('careers'); return; }
        cleanup = hub(app, career, args);
    });
    return () => { cancelled = true; if (cleanup) cleanup(); };
}

function hub(app, career, args) {
    const F = app.F;
    let simming = null;
    let cancelled = false;
    let summary = args.summary ?? null;

    if (['youth', 'hs', 'college', 'pro'].includes(career.stage) && !career.season && !career.retired) {
        startCareerSeason(career, F);
        app.saveCareer();
    }

    const s = () => career.season;
    const team = (id) => s().league.teams[id];

    function pitcherPanel() {
        const p = career.pitcher;
        const level = s()?.level ?? 'pro';
        const here = pitcherAt(career, level);
        const bar = (label, v, rel, field) => `<div class="c-rating">
            <span>${label}</span><div class="c-bar"><div style="width:${Math.max(0, Math.min(100, ((v - 20) / 79) * 100))}%"></div></div>
            <b>${Math.round(v)}</b><span class="muted" title="As rated at the ${LEVEL_NAMES[level]} level">${rel}</span>
            ${field ? `<button class="small" data-train='${JSON.stringify({ field })}' ${career.xp < trainCost(career, F, { field }) ? 'disabled' : ''}>+1 · ${trainCost(career, F, { field })}</button>` : ''}</div>`;
        const learn = learnable(career);
        const cost = pitchCost(career, F);
        return `<div class="panel">
            <div class="card-head"><h2>${esc(careerName(career))}</h2><span class="muted">${career.throws}HP · age ${career.age} · ${STYLES[career.style].name}</span></div>
            <div class="muted" style="font-size:12px;margin-bottom:8px">Ratings on the pro scale (the smaller number is how he rates at the ${LEVEL_NAMES[level].toLowerCase()} level).</div>
            ${bar('Velocity', p.velo, here.velo)}${bar('Control', p.control, here.control)}${bar('Movement', p.move, here.move)}${bar('Stamina', p.stamina, '', 'stamina')}
            <div class="xp"><b>${career.xp}</b> XP to spend <span class="muted">(${career.xpEarned} earned)</span></div>
            <h3 style="margin-top:10px">Pitches</h3>
            <table class="grid c-pitches"><tr><th>Pitch</th><th class="r">Velo</th><th class="r">Move</th><th class="r">Ctrl</th></tr>
            ${p.pitches.map((x, i) => `<tr><td><span class="swatch" style="background:${PITCH_TYPES[x.type].color}"></span>${esc(x.type)}</td>
                ${['velo', 'move', 'control'].map((f) => { const c = trainCost(career, F, { field: f, pitch: i }); return `<td class="r">${x[f]} <button class="small" data-train='${JSON.stringify({ field: f, pitch: i })}' ${career.xp < c ? 'disabled' : ''} title="${c} XP">+</button></td>`; }).join('')}</tr>`).join('')}
            </table>
            <div class="muted" style="font-size:11px">Each + costs ${trainCost(career, F, { field: 'velo', pitch: 0 })}–ish XP (more for higher ratings; see the Career formulas).</div>
            <div style="display:flex;gap:6px;margin-top:8px;align-items:center">
                ${learn.length && p.pitches.length < 6 ? `<select id="c-learn">${learn.map((t) => `<option>${t}</option>`).join('')}</select>
                <button data-act="learn" ${career.xp < cost ? 'disabled' : ''}>Learn it · ${cost} XP</button>` : `<span class="muted" style="font-size:12px">${p.pitches.length >= 6 ? 'Six pitches is plenty.' : 'No new pitches until he’s older.'}</span>`}
            </div>
        </div>`;
    }

    function seasonPanel() {
        const season = s();
        if (!season) return '';
        const me = season.userTeamId;
        const rec = teamRecord(season, me);
        const line = seasonLine(career);
        const pending = career.pendingStart != null ? season.schedule[career.pendingStart] : null;
        const up = pending && !pending.result ? { g: pending, starter: PID } : upcoming(career);
        const over = season.phase === 'done';
        const myGamesLeft = season.schedule.some((g) => !g.result && isUserGame(season, g));
        let next;
        if (simming) {
            next = `<div class="next-game"><h3>${esc(simming.label)}</h3><div class="sim-progress"><div style="width:${Math.round(100 * simming.done / Math.max(1, simming.total))}%"></div></div>
                <div class="row-actions"><button data-act="stop">Stop</button></div></div>`;
        } else if (over) {
            next = `<div class="next-game"><h3>The season is over</h3><p>${esc(teamName(team(me)))}: ${rec.w}-${rec.l}${season.champion === me ? ' · champions!' : ''}</p>
                <div class="row-actions" style="justify-content:flex-start"><button class="primary big" data-act="finish">On to the off-season</button></div></div>`;
        } else if (pending && !pending.result) {
            const g = pending;
            const opp = team(g.home === me ? g.away : g.home);
            next = `<div class="next-game"><div class="muted"><b class="playoff-tag">${esc(gameLabel(g))}</b> · Day ${g.day + 1}</div>
                <h2>Your start: ${g.home === me ? 'vs' : 'at'} <span style="color:${opp.color}">${esc(teamName(opp))}</span> <span class="muted" style="font-size:14px">(${teamRecord(season, opp.id).w}-${teamRecord(season, opp.id).l})</span></h2>
                <div class="row-actions" style="justify-content:flex-start;flex-wrap:wrap">
                    <button class="primary big" data-act="pitch">${app.savedGame()?.careerId === career.id ? 'Resume the game' : 'Pitch it'}</button>
                    <button data-act="sim-start">Sim this start</button>
                    <button data-act="sim-end">Sim the rest of the season</button>
                </div></div>`;
        } else if (!myGamesLeft) {
            next = `<div class="next-game"><h3>${esc(teamName(team(me)))} are done (${rec.w}-${rec.l})</h3><p class="muted">The rest of the season goes on without you.</p>
                <div class="row-actions" style="justify-content:flex-start"><button class="primary" data-act="sim-end">Sim to the end of the season</button></div></div>`;
        } else {
            const turn = up && up.starter === PID ? 'He’s lined up to start the next game.' : 'He’s resting; his turn in the rotation is coming.';
            next = `<div class="next-game"><h3>Between starts</h3><p class="muted">${turn}</p>
                <div class="row-actions" style="justify-content:flex-start;flex-wrap:wrap">
                    <button class="primary" data-act="to-start">Sim to his next start</button>
                    ${career.settings.play !== 'all' ? '<button data-act="to-playable">Sim to the next start you pitch</button>' : ''}
                    <button data-act="sim-end">Sim the rest of the season</button>
                </div></div>`;
        }
        return `<div class="panel">
            <div class="card-head"><h2>${LEVELS[season.level].icon} ${career.year} · ${esc(teamName(team(me)))}</h2><button class="small" data-act="season">Standings & leaders</button></div>
            <div class="muted">${esc(season.title)}${career.stage === 'youth' ? '' : ` · ${esc(stageText(career))}`} · team ${rec.w}-${rec.l}</div>
            <div class="c-line">${[['GS', line.gs], ['W-L', `${line.w}-${line.l}`], ['ERA', era(line.era)], ['IP', ipText(line.outs)], ['K', line.k], ['BB', line.bb]].map(([k, v]) => `<div><b>${v}</b><span>${k}</span></div>`).join('')}</div>
            ${next}
            <div class="form-grid" style="grid-template-columns: 100px 1fr;margin-top:10px">
                <label>Your starts</label><select id="c-play">${Object.entries(PLAY_MODES).map(([k, v]) => `<option value="${k}" ${k === career.settings.play ? 'selected' : ''}>${v}</option>`).join('')}</select>
                <label>Difficulty</label><select id="c-diff">${[1, 2, 3, 4, 5].map((d) => `<option value="${d}" ${d === career.settings.difficulty ? 'selected' : ''}>${DIFF_NAMES[d]}</option>`).join('')}</select>
            </div>
            ${career.log.length ? `<h3 style="margin-top:12px">This season’s outings</h3><table class="grid">
                <tr><th>Day</th><th>Game</th><th class="r">Line</th><th class="r">Result</th><th class="r">XP</th></tr>
                ${[...career.log].reverse().map((o) => `<tr><td>${o.day + 1}</td><td>${o.home ? 'vs' : 'at'} ${esc(team(o.opp).abbr)} <span class="muted" style="font-size:11px">${esc(o.label)}${o.started ? '' : ' · relief'}</span></td>
                    <td class="r num">${ipText(o.outs)} IP, ${o.h} H, ${o.er} ER, ${o.bb} BB, ${o.k} K</td>
                    <td class="r"><b class="${o.score.us > o.score.them ? 'win' : 'loss'}">${o.score.us > o.score.them ? 'W' : 'L'} ${o.score.us}–${o.score.them}</b>${o.win ? ' (W)' : o.loss ? ' (L)' : ''}</td><td class="r">+${o.xp}</td></tr>`).join('')}
            </table>` : ''}
        </div>`;
    }

    function historyPanel() {
        if (!career.history.length) return '';
        return `<div class="panel"><h3>Career</h3><table class="grid">
            <tr><th>Year</th><th>Age</th><th>Team</th><th class="r">GS</th><th class="r">W-L</th><th class="r">ERA</th><th class="r">IP</th><th class="r">K</th><th>Team result</th></tr>
            ${career.history.map((h) => `<tr><td>${h.year}</td><td>${h.age}</td><td>${esc(h.team)} <span class="muted" style="font-size:11px">${LEVEL_NAMES[h.level]}</span></td>
                <td class="r">${h.line.gs}</td><td class="r">${h.line.w}-${h.line.l}</td><td class="r">${era(h.line.era)}</td><td class="r">${h.line.ip}</td><td class="r">${h.line.k}</td>
                <td>${esc(h.finish)}${h.awards.length ? `<div class="muted" style="font-size:11px">🏅 ${esc(h.awards.join(' · '))}</div>` : ''}</td></tr>`).join('')}
        </table></div>`;
    }

    function summaryPanel() {
        if (!summary) return '';
        return `<div class="panel c-summary"><h2>${summary.year} season: ${esc(summary.team)}</h2>
            <p>${summary.line.gs} starts, ${summary.line.w}-${summary.line.l}, ${era(summary.line.era)} ERA, ${summary.line.ip} IP, ${summary.line.k} K. Team: ${summary.teamRecord}, ${esc(summary.finish)}.</p>
            ${summary.awards.length ? `<p>🏅 ${esc(summary.awards.join(' · '))}</p>` : ''}
            <p class="muted">+${summary.xp} XP this season. He’s now ${career.age}${summary.level === 'youth' ? ' (two years on, ready for high school)' : ''}, and a year older means ${career.age < 28 ? 'a bit stronger' : career.age < 32 ? 'about the same' : 'a step slower'}.</p>
            <div class="row-actions"><button class="small" data-act="dismiss">OK</button></div></div>`;
    }

    function decisionPanel() {
        const o = career.offers ?? {};
        const draft = o.draft ? `round ${o.draft.round}` : '';
        if (career.stage === 'decision') {
            return `<div class="panel"><h2>High school is done. What next?</h2>
                <p class="muted">Scouts rate him ${prospectScore(career)}. Pro scouts project him to go in ${draft} of the draft.</p>
                <div class="offers">${o.colleges.map((c) => `<div class="offer"><b>${esc(c.name)}</b><div class="muted">${esc(c.conference)} Conference</div><button class="primary" data-college="${c.team}">Accept the scholarship</button></div>`).join('')}
                <div class="offer"><b>The pro draft</b><div class="muted">Projected ${draft}. Straight to the majors, ready or not.</div><button data-draft="1">Enter the draft</button></div></div></div>`;
        }
        if (career.stage === 'collegeDecision') {
            return `<div class="panel"><h2>Three college seasons done</h2><p class="muted">Projected to go in ${draft} of the draft.</p>
                <div class="offers"><div class="offer"><b>Declare for the draft</b><button class="primary" data-draft="1">Go pro</button></div>
                <div class="offer"><b>Stay for senior year</b><div class="muted">One more college season, then the draft.</div><button data-return="1">Stay</button></div></div></div>`;
        }
        if (career.stage === 'draft') {
            return `<div class="panel"><h2>Draft day</h2><p class="muted">Projected ${draft}.</p><div class="row-actions" style="justify-content:flex-start"><button class="primary" data-draft="1">Enter the draft</button></div></div>`;
        }
        if (career.stage === 'freeAgency') {
            const cur = TEAMS[o.stay];
            return `<div class="panel"><h2>Free agency</h2><p class="muted">Teams are calling.</p>
                <div class="offers"><div class="offer"><b>Stay with the ${esc(cur.city)} ${esc(cur.name)}</b><button class="primary" data-stay="1">Re-sign</button></div>
                ${o.teams.map((i) => `<div class="offer"><b>Sign with the ${esc(TEAMS[i].city)} ${esc(TEAMS[i].name)}</b><button data-team="${i}">Sign</button></div>`).join('')}
                <div class="offer"><b>Retire</b><div class="muted">Hang up the spikes at ${career.age}.</div><button data-retire="1">Retire</button></div></div></div>`;
        }
        return '';
    }

    function retiredPanel() {
        const t = careerTotals(career);
        const hof = hallOfFame(career);
        const all = t.all;
        return `<div class="panel c-summary"><h2>${esc(careerName(career))} retired at ${career.age}</h2>
            <p>Career: ${all.w ?? 0}-${all.l ?? 0}, ${ipText(all.outs ?? 0)} IP, ${all.k ?? 0} K across ${career.history.length} seasons${career.draftedIn ? `; drafted in round ${career.draftedIn.round} (${career.draftedIn.year})` : ''}.</p>
            <p>Pro: ${t.pro.w ?? 0}-${t.pro.l ?? 0}, ${t.pro.k ?? 0} K.</p>
            <p>Hall of Fame score: <b>${hof}</b> ${hof >= 100 ? '🏛️ First ballot.' : hof >= 60 ? '— a real shot at the Hall.' : ''}</p></div>`;
    }

    function draw() {
        const body = career.retired ? retiredPanel() + historyPanel()
            : ['decision', 'collegeDecision', 'draft', 'freeAgency'].includes(career.stage)
                ? summaryPanel() + decisionPanel() + `<div class="c-grid"><div>${pitcherPanel()}</div><div>${historyPanel()}</div></div>`
                : summaryPanel() + `<div class="c-grid"><div>${pitcherPanel()}</div><div>${seasonPanel()}${historyPanel()}</div></div>`;
        app.root.innerHTML = `<div class="page wide">
            <div class="page-head"><button data-act="back">← Careers</button><h1>${esc(careerName(career))}</h1>
                <span class="muted">${esc(stageText(career))}</span>
                ${career.stage === 'pro' && !career.retired ? '<button class="small" data-retire="1">Retire</button>' : ''}</div>
            ${body}</div>`;
    }

    const save = () => app.saveCareer();

    // Sim in small chunks so the page stays responsive.
    function runSim(until, label) {
        const season = s();
        const total = Math.max(1, season.schedule.filter((g) => !g.result).length);
        simming = { label, done: 0, total };
        cancelled = false;
        draw();
        const tick = () => {
            const t0 = performance.now();
            let res = { done: false };
            while (performance.now() - t0 < 25 && !res.done && !cancelled) res = careerStep(career, F, until);
            simming.done = total - season.schedule.filter((g) => !g.result).length;
            if (res.done || cancelled) {
                simming = null;
                if (res.start) career.pendingStart = res.start.id;
                save();
                draw();
                return;
            }
            draw();
            setTimeout(tick, 0);
        };
        tick();
    }

    const onClick = async (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        const d = btn.dataset;
        if (d.train) {
            train(career, F, JSON.parse(d.train));
            save();
            return draw();
        }
        if (d.college) { choose(career, { college: Number(d.college) }); summary = null; startCareerSeason(career, F); save(); return draw(); }
        if (d.draft) {
            choose(career, { draft: true });
            summary = null;
            alert(`Drafted in round ${career.draftedIn.round} by the ${TEAMS[career.team].city} ${TEAMS[career.team].name}!`);
            startCareerSeason(career, F);
            save();
            return draw();
        }
        if (d.return) { choose(career, { returnToSchool: true }); summary = null; startCareerSeason(career, F); save(); return draw(); }
        if (d.stay) { choose(career, { stay: true }); summary = null; startCareerSeason(career, F); save(); return draw(); }
        if (d.team) { choose(career, { team: Number(d.team) }); summary = null; startCareerSeason(career, F); save(); return draw(); }
        if (d.retire) {
            if (!confirm(`Retire ${careerName(career)} now?`)) return;
            choose(career, { retire: true });
            career.season = null;
            save();
            return draw();
        }
        switch (d.act) {
            case 'back': app.go('careers'); break;
            case 'dismiss': summary = null; draw(); break;
            case 'stop': cancelled = true; break;
            case 'learn': learnPitch(career, F, app.root.querySelector('#c-learn').value); save(); draw(); break;
            case 'to-start': runSim('start', 'Simming to his next start…'); break;
            case 'to-playable': runSim('playable', 'Simming to the next start you pitch…'); break;
            case 'sim-end': career.pendingStart = null; runSim('end', 'Simming the rest of the season…'); break;
            case 'sim-start': {
                const g = s().schedule[career.pendingStart];
                markStart(career, g);
                const game = makeGame(s(), F, g);
                game.simToEnd();
                recordCareerGame(career, F, g, game);
                career.pendingStart = null;
                save();
                draw();
                break;
            }
            case 'pitch': {
                const saved = app.savedGame();
                if (saved?.careerId === career.id) return app.go('continue');
                const g = s().schedule[career.pendingStart];
                const game = careerGame(career, F, g);
                app.saveGame(game, { careerId: career.id, seasonGameId: g.id });
                save();
                app.go('game', { game, career, seasonGameId: g.id });
                break;
            }
            case 'finish': {
                summary = finishSeason(career, F);
                career.pendingStart = null;
                if (['youth', 'hs', 'college', 'pro'].includes(career.stage) && !career.retired) startCareerSeason(career, F);
                save();
                draw();
                break;
            }
            case 'season': app.go('season', { season: s(), readOnly: true, back: () => app.go('careerHub', { id: career.id }) }); break;
        }
    };
    const onChange = (e) => {
        if (e.target.id === 'c-play') { career.settings.play = e.target.value; save(); draw(); }
        if (e.target.id === 'c-diff') { career.settings.difficulty = Number(e.target.value); if (s()) s().difficulty = career.settings.difficulty; save(); }
    };
    app.root.addEventListener('click', onClick);
    app.root.addEventListener('change', onChange);
    draw();
    return () => {
        cancelled = true;
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('change', onChange);
    };
}
