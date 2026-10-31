// Formula Lab: read, edit, try, graph and test every formula in the game.
//
// Edits are drafts until saved. Saved formulas apply everywhere at once
// (including a game in progress) and are kept in localStorage.

import { parse } from 'mathzetta';
import { evaluate } from 'mathzetta/evaluate';
import { toHTML, HTML_STYLES } from 'mathzetta/html';
import { toSpeech } from 'mathzetta/speech';
import {
    FORMULAS, FORMULA_BY_ID, VARIABLES, VARIABLE_NAMES, SAMPLE_SCOPE, PRESETS,
    compileFormula, clampValue, usedVariables, availableVariables, createFormulas,
} from '../engine/formulas.js';
import { createSim, summarize } from '../engine/simStats.js';
import { esc, store } from './storage.js';

const GROUP_ORDER = ['Pitch', 'Zone', 'Batter', 'In play', 'Running', 'Season', 'Career', 'Computer'];
const VAR_GROUPS = ['Pitch', 'Pitcher', 'Location', 'Batter', 'Situation', 'Career'];

// Remembered while the page is open, across visits.
const lab = {
    selected: 'swingChance',
    drafts: {},
    scope: { ...SAMPLE_SCOPE },
    graphVar: {},
    simGames: 300,
    simCache: {},
};

export function renderLab(app) {
    ensureMathStyles();
    const F = app.F;
    let simRun = null;

    app.root.innerHTML = `
    <div class="page wide lab">
        <div class="page-head">
            <button data-act="back">← Menu</button>
            <h1>Formula Lab</h1>
            <select id="preset"><option value="">Apply a preset…</option>
                ${PRESETS.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>
            <button data-act="export">Export / share</button>
            <button data-act="import">Import</button>
        </div>
        <div class="lab-grid">
            <aside class="panel lab-list"></aside>
            <section class="lab-main"></section>
        </div>
        <div id="modal"></div>
    </div>`;
    const $ = (sel) => app.root.querySelector(sel);

    // ---------- helpers ----------
    const draftText = (id) => lab.drafts[id] ?? F.text(id);
    const isDirty = (id) => lab.drafts[id] !== undefined && lab.drafts[id] !== F.text(id);

    function compileDraft(id) {
        const text = draftText(id);
        try {
            return { tree: compileFormula(text), used: usedVariables(text), error: null };
        } catch (e) {
            let used = [];
            try { used = usedVariables(text); } catch { /* unparseable */ }
            return { tree: null, used, error: e.message };
        }
    }

    const defaultTrees = {};
    const defaultTree = (id) => (defaultTrees[id] ??= compileFormula(FORMULA_BY_ID[id].expr));
    function valueOf(id, tree, scope) {
        try {
            const v = Number(evaluate(tree, scope));
            return Number.isFinite(v) ? clampValue(FORMULA_BY_ID[id], v) : NaN;
        } catch {
            return NaN;
        }
    }
    const fmt = (id, v) => {
        if (Number.isNaN(v)) return '–';
        if (FORMULA_BY_ID[id].kind === 'prob') return `${(v * 100).toFixed(1)}%`;
        return Math.abs(v) >= 100 ? v.toFixed(1) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(4);
    };

    // ---------- list ----------
    function renderList() {
        const groups = GROUP_ORDER.map((g) => {
            const items = FORMULAS.filter((f) => f.group === g).map((f) => {
                const custom = F.isCustom(f.id);
                const marks = `${isDirty(f.id) ? '<span class="mark draft" title="Unsaved changes">✎</span>' : ''}${custom ? '<span class="mark custom" title="Customised">●</span>' : ''}${F.errors[f.id] ? '<span class="mark err" title="Error during play">⚠</span>' : ''}`;
                return `<button data-f="${f.id}" class="${f.id === lab.selected ? 'sel' : ''}">${esc(f.label)}${marks}</button>`;
            }).join('');
            return `<h3>${g}</h3>${items}`;
        }).join('');
        const customCount = Object.keys(F.overrides()).length;
        $('.lab-list').innerHTML = `${groups}
            <div class="lab-list-foot">${customCount ? `${customCount} customised` : 'All defaults'}
            ${customCount ? '<button class="small" data-act="reset-all">Reset all</button>' : ''}</div>`;
    }

    // ---------- editor ----------
    function renderMain() {
        const f = FORMULA_BY_ID[lab.selected];
        $('.lab-main').innerHTML = `
            <div class="panel">
                <div class="card-head">
                    <h2>${esc(f.label)}</h2>
                    <span class="muted"><code>${f.id}</code> · ${f.kind === 'prob' ? 'probability (clamped 0–1)' : 'value'}${f.min !== undefined ? ` · min ${f.min}` : ''}</span>
                </div>
                <p class="muted lab-desc">${esc(f.desc)}</p>
                <textarea id="expr" spellcheck="false" rows="3">${esc(draftText(f.id))}</textarea>
                <div id="status" class="lab-status"></div>
                <div id="render" class="lab-render"></div>
                <div id="speech" class="lab-speech"></div>
                <div class="lab-default">
                    <span class="muted">Default:</span> <code>${esc(f.expr)}</code>
                    <button class="small" data-act="use-default">Use default</button>
                </div>
                <div class="row-actions">
                    <span class="muted" style="margin-right:auto;font-size:12px">Saved formulas apply right away, including to a game in progress. Ctrl/⌘-S saves.</span>
                    <button data-act="discard">Discard changes</button>
                    <button class="primary" data-act="save">Save formula</button>
                </div>
            </div>
            <div class="lab-cols">
                <div class="panel">
                    <h3>Try it</h3>
                    <div id="try"></div>
                </div>
                <div class="panel">
                    <div class="card-head"><h3>Graph</h3><select id="graph-var"></select></div>
                    <canvas id="graph" class="lab-graph"></canvas>
                    <div class="lab-legend"><span class="lg mine">your draft</span><span class="lg saved">saved</span><span class="lg def">default</span><span id="graph-read" class="muted"></span></div>
                </div>
            </div>
            <div class="panel">
                <div class="card-head"><h3>League impact</h3>
                    <span><select id="sim-games">${[100, 300, 1000].map((n) => `<option ${n === lab.simGames ? 'selected' : ''} value="${n}">${n} games</option>`).join('')}</select>
                    <button class="primary" data-act="sim">Simulate</button></span>
                </div>
                <p class="muted" style="margin:4px 0 8px;font-size:12px">Plays computer-vs-computer games with your saved formulas plus this draft, and compares them with the defaults and real MLB averages.</p>
                <div id="sim"></div>
            </div>
            <div class="panel">
                <h3>Variables</h3>
                <p class="muted" style="margin:0 0 8px;font-size:12px">Click to insert. Dimmed ones aren't known yet when this formula runs.</p>
                <div id="vars"></div>
            </div>
            <div class="panel lab-syntax">
                <h3>Writing formulas</h3>
                <div>Arithmetic <code>+ - * / ^</code> and brackets; functions <code>min(a, b, …)</code> <code>max</code> <code>abs</code> <code>sqrt</code> <code>exp</code> <code>ln</code> <code>log</code> <code>floor</code> <code>ceil</code> <code>round</code> <code>sin</code> <code>cos</code> <code>random()</code>;
                comparisons <code>&lt; &gt; &lt;= &gt;= =</code> joined with <code>and</code> / <code>or</code>; choices <code>if edge &gt; 0 then 1 else -1</code> (nest them for more cases).
                <a href="https://mathzetta.com/" target="_blank" rel="noopener">MathZetta</a> also reads LaTeX, so <code>\\frac{1}{1 + e^{-x}}</code> works too.</div>
                <div class="muted" style="margin-top:6px">Logistic curves are handy for chances: <code>1/(1 + 10^(-(edge + 2)/2.5))</code> rises from 0 to 1 around edge = −2, with 2.5 setting how gradual it is.</div>
            </div>`;
        renderVars();
        renderGraphSelect();
        updateLive();
        renderSim();
    }

    // Everything that depends on the draft text, without touching the textarea.
    function updateLive() {
        const id = lab.selected;
        const f = FORMULA_BY_ID[id];
        const c = compileDraft(id);
        const status = $('#status');
        if (c.error) {
            status.className = 'lab-status err';
            status.textContent = `✗ ${c.error}`;
        } else {
            const v = valueOf(id, c.tree, lab.scope);
            const raw = Number(evaluate(c.tree, lab.scope));
            const clamped = Number.isFinite(raw) && raw !== v ? ` (raw ${raw.toFixed(3)}, clamped)` : '';
            const unavailable = c.used.filter((n) => !availableVariables(id).includes(n));
            status.className = `lab-status ${unavailable.length ? 'warn' : 'ok'}`;
            status.innerHTML = `✓ Valid · at the test values below: <b>${fmt(id, v)}</b>${clamped}`
                + (unavailable.length ? `<br>⚠ ${unavailable.map((n) => `<code>${n}</code>`).join(', ')} ${unavailable.length > 1 ? "aren't" : "isn't"} known when this formula runs, so ${unavailable.length > 1 ? 'they hold' : 'it holds'} a neutral value.` : '');
        }
        try {
            const postfix = parse(draftText(id), { names: VARIABLE_NAMES });
            $('#render').innerHTML = toHTML(postfix);
            $('#speech').textContent = `Reads as: ${toSpeech(postfix)}`;
        } catch {
            $('#render').innerHTML = '';
            $('#speech').textContent = '';
        }
        renderTry(c);
        drawGraph(c);
        renderList();
        const dirty = isDirty(id);
        $('[data-act="save"]').disabled = !dirty || !!c.error;
        $('[data-act="discard"]').disabled = !dirty;
        $('[data-act="use-default"]').disabled = draftText(id) === f.expr;
    }

    function renderTry(c) {
        const id = lab.selected;
        const vars = c.used.length ? c.used : [];
        const rows = vars.map((n) => {
            const [lo, hi, step] = VARIABLES[n].range;
            return `<div class="try-row" title="${esc(VARIABLES[n].desc)}">
                <code>${n}</code>
                <input type="range" min="${lo}" max="${hi}" step="${step}" value="${lab.scope[n]}" data-var="${n}">
                <input type="number" min="${lo}" max="${hi}" step="${step}" value="${lab.scope[n]}" data-var-num="${n}">
            </div>`;
        }).join('');
        const mine = c.tree ? valueOf(id, c.tree, lab.scope) : NaN;
        const def = valueOf(id, defaultTree(id), lab.scope);
        $('#try').innerHTML = `${rows || '<div class="muted">This formula uses no variables.</div>'}
            <div class="try-result">
                <div><span class="muted">Your draft</span><b>${fmt(id, mine)}</b></div>
                <div><span class="muted">Default</span><b>${fmt(id, def)}</b></div>
            </div>
            <button class="small" data-act="reset-scope">Reset test values</button>`;
    }

    function updateTryValues() {
        const id = lab.selected;
        const c = compileDraft(id);
        const res = $('#try .try-result');
        if (!res) return;
        const mine = c.tree ? valueOf(id, c.tree, lab.scope) : NaN;
        const def = valueOf(id, defaultTree(id), lab.scope);
        res.innerHTML = `<div><span class="muted">Your draft</span><b>${fmt(id, mine)}</b></div>
            <div><span class="muted">Default</span><b>${fmt(id, def)}</b></div>`;
        if (!c.error) {
            const v = valueOf(id, c.tree, lab.scope);
            const b = $('#status b');
            if (b) b.textContent = fmt(id, v);
        }
        drawGraph(c);
    }

    function renderGraphSelect() {
        const id = lab.selected;
        const c = compileDraft(id);
        const used = c.used.length ? c.used : [];
        if (!lab.graphVar[id] || !VARIABLES[lab.graphVar[id]]) {
            lab.graphVar[id] = used.includes('edge') ? 'edge' : used[0] ?? 'edge';
        }
        const others = VARIABLE_NAMES.filter((n) => !used.includes(n));
        $('#graph-var').innerHTML = `
            ${used.length ? `<optgroup label="Used here">${used.map((n) => `<option ${n === lab.graphVar[id] ? 'selected' : ''}>${n}</option>`).join('')}</optgroup>` : ''}
            <optgroup label="Other">${others.map((n) => `<option ${n === lab.graphVar[id] ? 'selected' : ''}>${n}</option>`).join('')}</optgroup>`;
    }

    let graphHover = null;
    function drawGraph(c) {
        const canvas = $('#graph');
        if (!canvas) return;
        const id = lab.selected;
        const f = FORMULA_BY_ID[id];
        const xv = lab.graphVar[id];
        const [lo, hi] = VARIABLES[xv].range;
        const dpr = window.devicePixelRatio || 1;
        const W = canvas.clientWidth * dpr;
        const H = canvas.clientHeight * dpr;
        canvas.width = W;
        canvas.height = H;
        const ctx = canvas.getContext('2d');
        const N = 160;
        const curve = (tree) => {
            if (!tree) return null;
            const pts = [];
            for (let i = 0; i <= N; i++) {
                const x = lo + ((hi - lo) * i) / N;
                pts.push([x, valueOf(id, tree, { ...lab.scope, [xv]: x })]);
            }
            return pts;
        };
        let savedTree = null;
        try { savedTree = F.isCustom(id) ? compileFormula(F.text(id)) : null; } catch { /* none */ }
        const curves = [
            { pts: curve(defaultTree(id)), color: '#93a89b', dash: [5, 4] },
            { pts: savedTree && F.text(id) !== draftText(id) ? curve(savedTree) : null, color: '#6ea8fe', dash: [] },
            { pts: curve(c.tree), color: '#ffd166', dash: [], width: 2.5 },
        ].filter((k) => k.pts);

        let ymin;
        let ymax;
        if (f.kind === 'prob') {
            ymin = 0;
            ymax = 1;
        } else {
            const ys = curves.flatMap((k) => k.pts.map((p) => p[1])).filter(Number.isFinite);
            ymin = Math.min(...ys);
            ymax = Math.max(...ys);
            if (!ys.length) { ymin = 0; ymax = 1; }
            if (ymax - ymin < 1e-9) { ymin -= 1; ymax += 1; }
            const pad = (ymax - ymin) * 0.08;
            ymin -= pad;
            ymax += pad;
        }
        const L = 46 * dpr;
        const R = 10 * dpr;
        const T = 10 * dpr;
        const B = 26 * dpr;
        const px = (x) => L + ((x - lo) / (hi - lo)) * (W - L - R);
        const py = (y) => T + (1 - (y - ymin) / (ymax - ymin)) * (H - T - B);

        ctx.fillStyle = '#101b16';
        ctx.fillRect(0, 0, W, H);
        ctx.font = `${11 * dpr}px system-ui, sans-serif`;
        ctx.fillStyle = '#93a89b';
        ctx.strokeStyle = '#24372d';
        ctx.lineWidth = 1;
        for (let i = 0; i <= 4; i++) {
            const y = ymin + ((ymax - ymin) * i) / 4;
            ctx.beginPath();
            ctx.moveTo(L, py(y));
            ctx.lineTo(W - R, py(y));
            ctx.stroke();
            ctx.textAlign = 'right';
            ctx.textBaseline = 'middle';
            ctx.fillText(f.kind === 'prob' ? `${Math.round(y * 100)}%` : niceNum(y), L - 5 * dpr, py(y));
        }
        for (let i = 0; i <= 5; i++) {
            const x = lo + ((hi - lo) * i) / 5;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(niceNum(x), px(x), H - B + 6 * dpr);
        }
        if (lo < 0 && hi > 0) {
            ctx.strokeStyle = '#2f4a3c';
            ctx.beginPath();
            ctx.moveTo(px(0), T);
            ctx.lineTo(px(0), H - B);
            ctx.stroke();
        }
        // Current test value.
        const cur = lab.scope[xv];
        ctx.strokeStyle = 'rgba(255,255,255,0.25)';
        ctx.setLineDash([2 * dpr, 3 * dpr]);
        ctx.beginPath();
        ctx.moveTo(px(cur), T);
        ctx.lineTo(px(cur), H - B);
        ctx.stroke();
        ctx.setLineDash([]);

        for (const k of curves) {
            ctx.strokeStyle = k.color;
            ctx.lineWidth = (k.width || 1.5) * dpr;
            ctx.setLineDash(k.dash.map((d) => d * dpr));
            ctx.beginPath();
            let started = false;
            for (const [x, y] of k.pts) {
                if (!Number.isFinite(y)) { started = false; continue; }
                const yy = Math.max(T - 2, Math.min(H - B + 2, py(y)));
                if (!started) { ctx.moveTo(px(x), yy); started = true; } else ctx.lineTo(px(x), yy);
            }
            ctx.stroke();
        }
        ctx.setLineDash([]);
        ctx.fillStyle = '#93a89b';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'bottom';
        ctx.fillText(xv, W - R, H - B - 2 * dpr);

        const read = $('#graph-read');
        if (graphHover !== null) {
            const x = lo + (hi - lo) * graphHover;
            const mine = c.tree ? valueOf(id, c.tree, { ...lab.scope, [xv]: x }) : NaN;
            const def = valueOf(id, defaultTree(id), { ...lab.scope, [xv]: x });
            read.textContent = `${xv} = ${niceNum(x)}: draft ${fmt(id, mine)}, default ${fmt(id, def)}`;
            ctx.strokeStyle = 'rgba(255, 209, 102, 0.6)';
            ctx.beginPath();
            ctx.moveTo(px(x), T);
            ctx.lineTo(px(x), H - B);
            ctx.stroke();
        } else {
            read.textContent = '';
        }
        canvas._geom = { L, R, W, dpr };
    }

    function renderVars() {
        const id = lab.selected;
        const avail = new Set(availableVariables(id));
        $('#vars').innerHTML = VAR_GROUPS.map((g) => {
            const names = VARIABLE_NAMES.filter((n) => VARIABLES[n].group === g);
            return `<div class="var-group"><span class="var-group-name">${g}</span>${names.map((n) =>
                `<button class="var-chip ${avail.has(n) ? '' : 'dim'}" data-insert="${n}" title="${esc(VARIABLES[n].desc)}">${n}</button>`).join('')}</div>`;
        }).join('');
    }

    // ---------- simulation ----------
    function renderSim(progress) {
        const el = $('#sim');
        if (!el) return;
        if (progress !== undefined) {
            el.innerHTML = `<div class="sim-progress"><div style="width:${Math.round(progress * 100)}%"></div></div>`;
            return;
        }
        const res = lab.simResult;
        if (!res) {
            el.innerHTML = '';
            return;
        }
        const rows = res.mine.map((m, i) => {
            const d = res.def[i];
            const delta = m.value - d.value;
            const rel = Math.abs(delta) / (Math.abs(d.value) || 1);
            const cls = rel < 0.03 ? '' : delta > 0 ? 'up' : 'down';
            return `<tr><td>${m.label}</td><td class="r">${d.text}</td><td class="r"><b>${m.text}</b></td>
                <td class="r delta ${cls}">${Number.isFinite(delta) && rel >= 0.03 ? (delta > 0 ? '▲' : '▼') : ''}</td><td class="r muted">${m.mlbText}</td></tr>`;
        }).join('');
        el.innerHTML = `
            <div class="muted" style="font-size:12px;margin-bottom:6px">${res.games} games each · ${res.label}</div>
            <table class="grid"><tr><th>Stat</th><th class="r">Default</th><th class="r">Yours</th><th></th><th class="r">MLB</th></tr>${rows}</table>`;
    }

    function runSim() {
        if (simRun) return;
        const games = lab.simGames;
        const id = lab.selected;
        const c = compileDraft(id);
        const mineOverrides = { ...F.overrides() };
        if (!c.error) mineOverrides[id] = draftText(id);
        if (mineOverrides[id] === FORMULA_BY_ID[id].expr) delete mineOverrides[id];
        const key = `${games}`;
        const seed = 11;
        const defSim = lab.simCache[key] ? null : createSim(app.league, createFormulas({}), { games, seed });
        const mySim = createSim(app.league, createFormulas(mineOverrides), { games, seed });
        const changed = Object.keys(mineOverrides);
        simRun = true;
        $('[data-act="sim"]').disabled = true;
        const tick = () => {
            if (!$('#sim')) { simRun = null; return; }    // left the page
            const start = performance.now();
            while (performance.now() - start < 30) {
                if (defSim && !defSim.done) defSim.step(1);
                else if (!mySim.done) mySim.step(1);
                else break;
            }
            const doneGames = (defSim ? defSim.totals.games : games) + mySim.totals.games;
            if (defSim && defSim.done && !lab.simCache[key]) lab.simCache[key] = summarize(defSim.totals);
            if (!mySim.done) {
                renderSim(doneGames / (2 * games));
                setTimeout(tick, 0);
                return;
            }
            lab.simResult = {
                games,
                def: lab.simCache[key],
                mine: summarize(mySim.totals),
                label: changed.length ? `yours = ${changed.length} custom formula${changed.length > 1 ? 's' : ''} (${changed.join(', ')})` : 'yours = defaults (no changes)',
            };
            simRun = null;
            $('[data-act="sim"]').disabled = false;
            renderSim();
        };
        tick();
    }

    // ---------- save / presets / share ----------
    function saveCurrent() {
        const id = lab.selected;
        const text = draftText(id).trim();
        if (text === FORMULA_BY_ID[id].expr) {
            F.reset(id);
        } else {
            const err = F.setText(id, text);
            if (err) { alert(err); return; }
        }
        delete lab.drafts[id];
        persist();
        renderMain();
    }

    function persist() {
        store.save('formulas', F.overrides());
    }

    function applyFormulas(map, replace) {
        const errors = [];
        if (replace) for (const f of FORMULAS) F.reset(f.id);
        for (const [id, text] of Object.entries(map)) {
            if (!FORMULA_BY_ID[id]) { errors.push(`${id}: unknown formula`); continue; }
            const err = F.setText(id, text);
            if (err) errors.push(`${id}: ${err}`);
        }
        lab.drafts = {};
        persist();
        renderMain();
        return errors;
    }

    function showModal(html) {
        $('#modal').innerHTML = `<div class="overlay"><div class="panel">${html}</div></div>`;
    }

    function showExport() {
        const data = { game: '27K', version: 1, formulas: F.overrides() };
        const json = JSON.stringify(data, null, 2);
        const link = shareLink(data.formulas);
        showModal(`
            <h2>Export your rules</h2>
            <p class="muted">${Object.keys(data.formulas).length} customised formula(s). Share the link, or save the JSON.</p>
            <h3>Link</h3>
            <div style="display:flex;gap:6px"><input id="share-link" readonly value="${esc(link)}" style="flex:1"><button data-act="copy-link">Copy</button></div>
            <h3 style="margin-top:12px">JSON</h3>
            <textarea id="export-json" rows="12" readonly>${esc(json)}</textarea>
            <div class="row-actions"><button data-act="copy-json">Copy JSON</button><button class="primary" data-act="close">Close</button></div>`);
    }

    function showImport() {
        showModal(`
            <h2>Import rules</h2>
            <p class="muted">Paste exported JSON or a shared link. Imported formulas are merged over your current ones.</p>
            <textarea id="import-text" rows="10" placeholder='{"formulas": {"strikeCall": "inZone"}}'></textarea>
            <label class="toggle" style="margin-top:8px"><input type="checkbox" id="import-replace"> Reset everything else to defaults first</label>
            <div id="import-msg" class="lab-status"></div>
            <div class="row-actions"><button data-act="close">Cancel</button><button class="primary" data-act="do-import">Import</button></div>`);
    }

    // ---------- events ----------
    const onClick = (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.f) {
            lab.selected = btn.dataset.f;
            graphHover = null;
            renderMain();
            return;
        }
        if (btn.dataset.insert) {
            const ta = $('#expr');
            const { selectionStart: a, selectionEnd: b, value } = ta;
            ta.value = value.slice(0, a) + btn.dataset.insert + value.slice(b);
            ta.focus();
            ta.selectionStart = ta.selectionEnd = a + btn.dataset.insert.length;
            lab.drafts[lab.selected] = ta.value;
            renderGraphSelect();
            updateLive();
            return;
        }
        switch (btn.dataset.act) {
            case 'back': app.go('menu'); break;
            case 'save': saveCurrent(); break;
            case 'discard': delete lab.drafts[lab.selected]; renderMain(); break;
            case 'use-default':
                lab.drafts[lab.selected] = FORMULA_BY_ID[lab.selected].expr;
                $('#expr').value = lab.drafts[lab.selected];
                renderGraphSelect();
                updateLive();
                break;
            case 'reset-scope': lab.scope = { ...SAMPLE_SCOPE }; updateLive(); break;
            case 'sim': runSim(); break;
            case 'reset-all':
                if (confirm('Reset every formula to its default?')) applyFormulas({}, true);
                break;
            case 'export': showExport(); break;
            case 'import': showImport(); break;
            case 'close': $('#modal').innerHTML = ''; break;
            case 'copy-link': copy($('#share-link').value, btn); break;
            case 'copy-json': copy($('#export-json').value, btn); break;
            case 'do-import': {
                const map = readShared($('#import-text').value);
                if (!map) { $('#import-msg').className = 'lab-status err'; $('#import-msg').textContent = 'Could not read that: paste the JSON or link from Export.'; break; }
                const errors = applyFormulas(map, $('#import-replace').checked);
                if (errors.length) { $('#import-msg').className = 'lab-status err'; $('#import-msg').textContent = `Imported with problems: ${errors.join('; ')}`; } else $('#modal').innerHTML = '';
                break;
            }
        }
    };
    const onInput = (e) => {
        if (e.target.id === 'expr') {
            lab.drafts[lab.selected] = e.target.value;
            updateLive();
            // Keep the cursor's line visible; the variable list may change.
            const before = $('#graph-var').value;
            renderGraphSelect();
            if ($('#graph-var').value !== before) drawGraph(compileDraft(lab.selected));
        } else if (e.target.dataset.var || e.target.dataset.varNum) {
            const n = e.target.dataset.var || e.target.dataset.varNum;
            const v = Number(e.target.value);
            if (!Number.isFinite(v)) return;
            lab.scope[n] = v;
            const other = e.target.dataset.var ? `[data-var-num="${n}"]` : `[data-var="${n}"]`;
            const o = $(other);
            if (o) o.value = v;
            updateTryValues();
        }
    };
    const onChange = (e) => {
        if (e.target.id === 'graph-var') {
            lab.graphVar[lab.selected] = e.target.value;
            drawGraph(compileDraft(lab.selected));
        } else if (e.target.id === 'sim-games') {
            lab.simGames = Number(e.target.value);
        } else if (e.target.id === 'preset' && e.target.value) {
            const p = PRESETS.find((x) => x.id === e.target.value);
            e.target.value = '';
            if (!p.formulas) {
                if (confirm('Reset every formula to its default?')) applyFormulas({}, true);
            } else if (confirm(`Apply “${p.name}”? ${p.desc}\n\nThis changes: ${Object.keys(p.formulas).join(', ')}.`)) {
                applyFormulas(p.formulas, false);
            }
        }
    };
    const onKey = (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
            e.preventDefault();
            if (isDirty(lab.selected) && !compileDraft(lab.selected).error) saveCurrent();
        }
    };
    const onMove = (e) => {
        if (e.target.id !== 'graph') return;
        const g = e.target._geom;
        if (!g) return;
        const rect = e.target.getBoundingClientRect();
        const x = (e.clientX - rect.left) * g.dpr;
        graphHover = Math.max(0, Math.min(1, (x - g.L) / (g.W - g.L - g.R)));
        drawGraph(compileDraft(lab.selected));
    };
    const onLeave = (e) => {
        if (e.target.id !== 'graph') return;
        graphHover = null;
        drawGraph(compileDraft(lab.selected));
    };
    const onResize = () => drawGraph(compileDraft(lab.selected));

    app.root.addEventListener('click', onClick);
    app.root.addEventListener('input', onInput);
    app.root.addEventListener('change', onChange);
    app.root.addEventListener('mousemove', onMove);
    app.root.addEventListener('mouseout', onLeave);
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);

    renderList();
    renderMain();

    return () => {
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('input', onInput);
        app.root.removeEventListener('change', onChange);
        app.root.removeEventListener('mousemove', onMove);
        app.root.removeEventListener('mouseout', onLeave);
        window.removeEventListener('keydown', onKey);
        window.removeEventListener('resize', onResize);
    };
}

function ensureMathStyles() {
    if (document.getElementById('mz-styles')) return;
    const style = document.createElement('style');
    style.id = 'mz-styles';
    style.textContent = HTML_STYLES;
    document.head.appendChild(style);
}

function niceNum(v) {
    if (Math.abs(v) >= 100) return v.toFixed(0);
    if (Math.abs(v) >= 10) return v.toFixed(1).replace(/\.0$/, '');
    return v.toFixed(2).replace(/\.?0+$/, '') || '0';
}

function copy(text, btn) {
    navigator.clipboard?.writeText(text).then(() => {
        const old = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = old; }, 1200);
    });
}

// ---------- sharing ----------
export function shareLink(formulas) {
    const json = JSON.stringify(formulas);
    const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)))
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return `${location.origin}${location.pathname}#formulas=${b64}`;
}

// Read a link, a `#formulas=` hash, or JSON ({formulas: {...}} or a plain map).
export function readShared(text) {
    text = text.trim();
    const m = text.match(/formulas=([A-Za-z0-9_-]+)/);
    try {
        if (m) {
            const b64 = m[1].replace(/-/g, '+').replace(/_/g, '/');
            const bytes = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
            return JSON.parse(new TextDecoder().decode(bytes));
        }
        const data = JSON.parse(text);
        const map = data.formulas ?? data;
        if (typeof map !== 'object' || Array.isArray(map)) return null;
        return map;
    } catch {
        return null;
    }
}
