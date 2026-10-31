// Season mode: pick a level and a team, then play or sim a schedule,
// with standings, leaders, your roster and pitcher rest, and playoffs.

import { LEVELS, LEVEL_ORDER } from '../engine/levels.js';
import { playerName, shortName, teamName } from '../engine/league.js';
import {
    createSeason, seasonLeague, leaders, LEADER_STATS, simStep, simOthersToday, nextUserGame, userGameToday,
    isRested, restLeft, pickStarter, makeGame, battingRates, pitchingRates, isUserGame, teamRecord, gameLabel,
} from '../engine/season.js';
import { FORMATS, table, groupTable, stageById } from '../engine/competition.js';
import { STATES, COLLEGE_CONFERENCES } from '../engine/regions.js';
import { PITCH_TYPES } from '../engine/data.js';
import { renderLineup, rating } from './screens.js';
import { seedHistory } from '../engine/pitchStats.js';
import { esc } from './storage.js';

const DIFF_NAMES = ['', 'Rookie', 'Pro', 'All-Star', 'MVP', 'Chaos'];

// ---------- setup ----------
export function renderSeasonSetup(app) {
    const st = {
        level: app.prefs.seasonLevel ?? 'hs', seed: Date.now() >>> 0, team: 0,
        state: app.prefs.hsState ?? 'TX', length: null, difficulty: app.prefs.difficulty,
    };
    const formatOpts = () => (st.level === 'hs' ? { state: st.state } : st.level === 'pro' ? { length: st.length ?? LEVELS.pro.defaultLength } : {});
    let league = seasonLeague(st.level, st.seed, formatOpts());

    const strength = (t) => {
        const bats = t.lineup.map((x) => league.players[x.id]);
        const off = Math.round(bats.reduce((a, b) => a + b.contact + b.power + b.eye, 0) / bats.length / 3);
        const sps = t.rotation.map((id) => league.players[id]);
        const pit = Math.round(sps.reduce((a, p) => a + p.velo + p.move + p.control, 0) / sps.length / 3);
        return `Hitting ${rating(off)} · Pitching ${rating(pit)}`;
    };
    const pick = (t) => `<label class="team-pick ${t.id === st.team ? 'sel' : ''}">
        <input type="radio" name="team" value="${t.id}" ${t.id === st.team ? 'checked' : ''}>
        <span class="swatch" style="background:${t.color}"></span><b>${esc(teamName(t))}</b>
        <span class="muted" style="margin-left:auto;font-size:12px">${strength(t)}</span></label>`;

    function teamChooser() {
        if (st.level === 'youth') {
            // 128 teams: a list grouped US / International.
            const opts = (group) => league.teams.filter((t) => t.group === group)
                .map((t) => `<option value="${t.id}" ${t.id === st.team ? 'selected' : ''}>${esc(t.city)}</option>`).join('');
            const t = league.teams[st.team];
            return `<select id="s-team" size="14" style="width:100%">
                    <optgroup label="United States">${opts('US')}</optgroup>
                    <optgroup label="International">${opts('International')}</optgroup></select>
                <div class="muted" style="margin-top:6px;font-size:12px"><span class="swatch" style="background:${t.color}"></span><b>${esc(teamName(t))}</b> · ${strength(t)}</div>`;
        }
        if (st.level === 'college') {
            return `<div class="conf-grid">${conferencePicker()}</div>`;
        }
        const stateSel = st.level === 'hs' ? `<div style="margin-bottom:8px">State <select id="s-state">${Object.entries(STATES)
            .sort((a, b) => a[1][0].localeCompare(b[1][0]))
            .map(([abbr, [name]]) => `<option value="${abbr}" ${abbr === st.state ? 'selected' : ''}>${name}</option>`).join('')}</select></div>` : '';
        return `${stateSel}<div class="pitcher-pick">${league.teams.map(pick).join('')}</div>`;
    }
    function conferencePicker() {
        const confs = [...new Set(league.teams.map((t) => t.group))];
        return confs.map((c) => {
            const teams = league.teams.filter((t) => t.group === c);
            return `<div><h3>${esc(COLLEGE_CONFERENCES[c].name)} Conference</h3>${teams.map((t) => `<label class="team-pick small ${t.id === st.team ? 'sel' : ''}">
                <input type="radio" name="team" value="${t.id}" ${t.id === st.team ? 'checked' : ''}>
                <span class="swatch" style="background:${t.color}"></span>${esc(teamName(t))}</label>`).join('')}</div>`;
        }).join('');
    }

    const draw = () => {
        const L = LEVELS[st.level];
        app.root.innerHTML = `
        <div class="page wide">
            <div class="page-head"><button data-act="back">← Menu</button><h1>New season</h1></div>
            <div class="level-grid">
                ${LEVEL_ORDER.map((id) => {
                    const lv = LEVELS[id];
                    return `<button class="panel level-card ${id === st.level ? 'sel' : ''}" data-level="${id}">
                        <div class="lv-icon">${lv.icon}</div><div class="lv-name">${lv.name}</div>
                        <div class="lv-facts">${lv.innings} innings${lv.mercy ? ` · mercy ${lv.mercy.runs} after ${lv.mercy.after}` : ''}</div>
                        <div class="lv-desc">${esc(FORMATS[id].describe)}</div>
                    </button>`;
                }).join('')}
            </div>
            <div class="cols-2" style="margin-top:12px">
                <div class="panel">
                    <div class="card-head"><h3>Choose your team</h3><button class="small" data-act="reroll">New rosters</button></div>
                    ${teamChooser()}
                </div>
                <div class="panel">
                    <h3>${esc(FORMATS[st.level].title({ formatOpts: formatOpts() }))}</h3>
                    <div class="form-grid" style="grid-template-columns: 110px 1fr">
                        ${st.level === 'pro' ? `<label>Games</label>
                        <select id="s-len">${L.lengths.map((n) => `<option ${n === (st.length ?? L.defaultLength) ? 'selected' : ''}>${n}</option>`).join('')}</select>` : ''}
                        <label>Difficulty</label>
                        <div><input id="s-diff" type="range" min="1" max="5" value="${st.difficulty}"> <b id="s-diff-name">${DIFF_NAMES[st.difficulty]}</b></div>
                    </div>
                    <p class="muted" style="font-size:12px;line-height:1.5">${esc(FORMATS[st.level].describe)}
                    Play any of your games on the mound or sim them. Pitchers need rest after they throw${L.n <= 2 ? `, and there’s a ${L.n === 1 ? 85 : 105}-pitch limit` : ''}.</p>
                    <div class="row-actions"><button class="primary big" data-act="start">Start season</button></div>
                </div>
            </div>
        </div>`;
    };
    const regen = () => {
        league = seasonLeague(st.level, st.seed, formatOpts());
        if (st.team >= league.teams.length) st.team = 0;
        draw();
    };

    const onClick = (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.level) {
            st.level = btn.dataset.level;
            st.length = null;
            st.team = 0;
            regen();
        }
        if (btn.dataset.act === 'back') app.go('menu');
        if (btn.dataset.act === 'reroll') {
            st.seed = (st.seed * 1103515245 + 12345) >>> 0;
            regen();
        }
        if (btn.dataset.act === 'start') {
            if (app.season && app.season.phase !== 'done' && !confirm('Replace the season in progress?')) return;
            app.prefs.seasonLevel = st.level;
            app.prefs.difficulty = st.difficulty;
            if (st.level === 'hs') app.prefs.hsState = st.state;
            app.savePrefs();
            // Smaller leagues get a simulated past for the scouting reports.
            if (league.teams.length <= 16) seedHistory(league, app.F, league.teams.length * 10);
            app.season = createSeason({ level: st.level, seed: st.seed, league, userTeamId: st.team, difficulty: st.difficulty, formatOpts: formatOpts() });
            app.clearGame();
            app.saveSeason();
            app.go('season');
        }
    };
    const onChange = (e) => {
        if (e.target.name === 'team' || e.target.id === 's-team') { st.team = Number(e.target.value); draw(); }
        if (e.target.id === 's-len') st.length = Number(e.target.value);
        if (e.target.id === 's-state') { st.state = e.target.value; st.team = 0; regen(); }
    };
    const onInput = (e) => {
        if (e.target.id === 's-diff') {
            st.difficulty = Number(e.target.value);
            app.root.querySelector('#s-diff-name').textContent = DIFF_NAMES[st.difficulty];
        }
    };
    app.root.addEventListener('click', onClick);
    app.root.addEventListener('change', onChange);
    app.root.addEventListener('input', onInput);
    draw();
    return () => {
        app.root.removeEventListener('click', onClick);
        app.root.removeEventListener('change', onChange);
        app.root.removeEventListener('input', onInput);
    };
}

// ---------- the season hub ----------
// args.season / readOnly / back: view another season (a career's) without
// the play and sim buttons.
export function renderSeason(app, args = {}) {
    const season = args.season ?? app.season;
    const readOnly = !!args.readOnly;
    if (!season) return renderSeasonSetup(app);
    const L = LEVELS[season.level];
    const lg = season.league;
    const me = season.userTeamId;
    let tab = args.tab ?? 'schedule';
    let simming = null;      // { label, done, total } while a sim runs
    let cancelled = false;

    const team = (id) => lg.teams[id];
    const record = (id) => {
        const r = teamRecord(season, id);
        return `${r.w}-${r.l}`;
    };
    // "Series tied 1-1" for a game in a best-of series.
    const seriesNote = (g) => {
        const stage = stageById(season, g.stage);
        const m = stage?.type === 'knockout' ? stage.matches[g.match] : null;
        if (!m || m.bestOf === 1) return '';
        const [wa, wb] = m.wins;
        if (wa === wb) return `Series tied ${wa}-${wb}`;
        return `${team(wa > wb ? m.a : m.b).abbr} leads the series ${Math.max(wa, wb)}-${Math.min(wa, wb)}`;
    };
    const savedHere = () => {
        const saved = app.savedGame();
        return saved && saved.seasonGameId !== undefined ? saved : null;
    };

    function nextPanel() {
        if (readOnly) return '';
        if (season.phase === 'done') {
            const champ = team(season.champion);
            return `<div class="panel next-game champ">
                <div style="font-size:42px">🏆</div>
                <h2>${esc(teamName(champ))} are champions!</h2>
                <p class="muted">${season.champion === me ? 'That’s your team. What a season.' : `Your ${esc(teamName(team(me)))} went ${record(me)}.`}</p>
                <div class="row-actions" style="justify-content:center"><button class="primary" data-act="new">New season</button></div>
            </div>`;
        }
        if (simming) {
            return `<div class="panel next-game"><h3>${esc(simming.label)}</h3>
                <div class="sim-progress"><div style="width:${Math.round((100 * simming.done) / Math.max(1, simming.total))}%"></div></div>
                <div class="muted" style="margin-top:6px">Day ${season.day + 1}</div>
                <div class="row-actions"><button data-act="stop">Stop</button></div></div>`;
        }
        const g = nextUserGame(season);
        const saved = savedHere();
        if (!g) {
            return `<div class="panel next-game"><h3>${esc(season.title)}</h3>
                <p>Your ${esc(teamName(team(me)))} are out (${record(me)}). The rest of the ${season.level === 'youth' ? 'tournament' : 'postseason'} goes on without you.</p>
                <div class="row-actions"><button class="primary" data-act="sim-end">Sim to the end</button></div></div>`;
        }
        const home = g.home === me;
        const opp = team(home ? g.away : g.home);
        const today = g.day === season.day;
        const label = gameLabel(g);
        const series = seriesNote(g);
        const mySp = lg.players[pickStarter(season, me, g.day)];
        const theirSp = lg.players[pickStarter(season, opp.id, g.day)];
        const resume = saved && saved.seasonGameId === g.id;
        return `<div class="panel next-game">
            <div class="muted"><b class="playoff-tag">${esc(label)}</b>${series ? ` · ${esc(series)}` : ''} · ${today ? 'Today' : `Day ${g.day + 1}`}</div>
            <h2>${home ? 'vs' : 'at'} <span style="color:${opp.color}">${esc(teamName(opp))}</span> <span class="muted" style="font-size:14px">(${record(opp.id)})</span></h2>
            <div class="muted" style="font-size:13px">Probable starters: ${esc(shortName(mySp))} vs ${esc(shortName(theirSp))}</div>
            <div class="row-actions" style="justify-content:flex-start;flex-wrap:wrap">
                ${today ? `<button class="primary big" data-act="${resume ? 'resume' : 'play'}">${resume ? 'Resume game' : 'Play this game'}</button>
                <button data-act="sim-game">Sim this game</button>` : `<button class="primary" data-act="sim-to-game">Sim to this game</button>`}
                <button data-act="sim-week">Sim 7 days</button>
                <button data-act="sim-end">Sim to the end</button>
            </div>
        </div>`;
    }

    function scheduleTab() {
        const mine = season.schedule.filter((g) => isUserGame(season, g));
        const rows = mine.map((g) => {
            const home = g.home === me;
            const opp = team(home ? g.away : g.home);
            let res = '';
            if (g.result) {
                const ours = home ? g.result.home : g.result.away;
                const theirs = home ? g.result.away : g.result.home;
                const extra = g.result.endedBy === 'mercy' ? ` (${g.result.innings}, mercy)` : g.result.innings > L.innings ? ` (${g.result.innings})` : '';
                res = `<b class="${ours > theirs ? 'win' : 'loss'}">${ours > theirs ? 'W' : 'L'} ${ours}–${theirs}</b>${extra}`;
            }
            return `<tr class="${g.day === season.day && !g.result ? 'current' : ''}"><td>${g.day + 1}</td><td>${g.stage !== 'regular' ? `<b class="playoff-tag">${esc(gameLabel(g))}</b> ` : ''}${home ? 'vs' : 'at'} ${esc(teamName(opp))}</td><td class="r">${res}</td></tr>`;
        }).join('');
        // Latest results around the league.
        const lastDay = Math.max(-1, ...season.schedule.filter((g) => g.result).map((g) => g.day));
        const around = season.schedule.filter((g) => g.day === lastDay && g.result).map((g) =>
            `<div>${esc(team(g.away).abbr)} ${g.result.away}, ${esc(team(g.home).abbr)} ${g.result.home}${g.result.endedBy === 'mercy' ? ' <span class="muted">(mercy)</span>' : ''}</div>`).join('');
        return `<div class="cols-2"><div><table class="grid"><tr><th>Day</th><th>Game</th><th class="r">Result</th></tr>${rows}</table></div>
            <div><h3>${lastDay >= 0 ? `Day ${lastDay + 1} scores` : 'No games yet'}</h3><div class="scores">${around}</div></div></div>`;
    }

    // Every stage so far, newest first: brackets, pools, standings.
    function standingsTab() {
        return [...season.stages].reverse().map((stage) => {
            if (stage.type === 'knockout') return bracketHTML(stage);
            if (stage.type === 'pool') return poolsHTML(stage);
            return leagueHTML(stage);
        }).join('<hr class="soft">');
    }

    const teamCell = (id) => `<span class="swatch" style="background:${team(id).color}"></span>${esc(teamName(team(id)))}`;

    function leagueHTML(stage) {
        const regular = (g) => g.stage === stage.id;
        return `<h2>${esc(stage.name)}</h2><div class="${season.divisions.length > 1 ? 'conf-tables' : ''}">${season.divisions.map((d) => {
            const conf = d.conference;
            const rows = table(season, d.teams, conf ? (g) => regular(g) && g.conf : regular);
            const overall = conf ? Object.fromEntries(table(season, d.teams, regular).map((r) => [r.teamId, r])) : null;
            return `<div><h3>${esc(d.name)}</h3><table class="grid">
                <tr><th></th><th>Team</th>${conf ? '<th class="r">Conf</th><th class="r">Overall</th>' : '<th class="r">W</th><th class="r">L</th><th class="r">Pct</th>'}<th class="r">GB</th><th class="r">Diff</th><th class="r">Strk</th></tr>
                ${rows.map((r, i) => {
                    const o = overall?.[r.teamId];
                    return `<tr class="${r.teamId === me ? 'current' : ''}"><td>${i + 1}</td><td>${teamCell(r.teamId)}</td>
                    ${conf ? `<td class="r">${r.w}-${r.l}</td><td class="r">${o.w}-${o.l}</td>` : `<td class="r">${r.w}</td><td class="r">${r.l}</td><td class="r">${r.pct.toFixed(3).replace(/^0/, '')}</td>`}
                    <td class="r">${r.gb ? r.gb.toFixed(1).replace('.0', '') : '–'}</td><td class="r">${r.rs - r.ra > 0 ? '+' : ''}${r.rs - r.ra}</td><td class="r">${(conf ? o : r).streak}</td></tr>`;
                }).join('')}</table></div>`;
        }).join('')}</div>${stage.status === 'active' ? `<p class="muted" style="font-size:12px">${esc(postseasonNote())}</p>` : ''}`;
    }

    function postseasonNote() {
        return { hs: 'The top eight go to the state tournament.', college: 'Conference champions (best conference record) and the 24 best other records make the regionals.', pro: 'The top four make the playoffs.' }[season.level] ?? '';
    }

    function poolsHTML(stage) {
        const mineFirst = [...stage.groups].sort((a, b) => (b.teams.includes(me) ? 1 : 0) - (a.teams.includes(me) ? 1 : 0));
        return `<h2>${esc(stage.name)}</h2><div class="pool-grid">${mineFirst.map((group) => {
            const rows = groupTable(season, stage, group);
            return `<div class="pool ${group.teams.includes(me) ? 'mine' : ''}"><h3>${esc(group.name)}</h3><table class="grid">
                ${rows.map((r, i) => `<tr class="${r.teamId === me ? 'current' : ''} ${i < stage.advance && stage.status === 'done' ? 'adv' : ''}">
                    <td>${teamCell(r.teamId)}</td><td class="r">${r.w}-${r.l}</td><td class="r">${r.rs - r.ra > 0 ? '+' : ''}${r.rs - r.ra}</td></tr>`).join('')}
            </table></div>`;
        }).join('')}</div><p class="muted" style="font-size:12px">Each pool plays a round robin; the winner advances (ties: run difference, then fewest runs allowed).</p>`;
    }

    function bracketHTML(stage) {
        const rounds = Math.max(...stage.matches.map((m) => m.round)) + 1;
        const total = Math.log2(stage.seeds.length);
        const cols = [];
        for (let r = 0; r < total; r++) {
            const ms = stage.matches.filter((m) => m.round === r);
            cols.push(`<div class="br-col"><h3>${esc(stage.roundNames[r] ?? '')}</h3>${r < rounds ? ms.map((m) => {
                const side = (id, w) => `<div class="br-team ${m.winner === id ? 'win' : m.winner !== null ? 'lose' : ''} ${id === me ? 'me' : ''}">
                    <span>${stage.seeds.indexOf(id) + 1}</span>${esc(team(id).abbr)} <span class="muted br-name">${esc(teamName(team(id)))}</span>${m.bestOf > 1 || m.winner !== null ? `<b>${w}</b>` : ''}</div>`;
                return `<div class="br-match">${side(m.a, m.wins[0])}${side(m.b, m.wins[1])}${m.bestOf > 1 ? `<div class="muted br-note">best of ${m.bestOf}</div>` : ''}</div>`;
            }).join('') : '<div class="muted">to come</div>'}</div>`);
        }
        const champ = stage.status === 'done' ? `<div class="br-col"><h3>${stage.final ? 'Champion' : 'Winner'}</h3><div class="br-match"><div class="br-team win ${stage.winner === me ? 'me' : ''}">🏆 ${esc(teamName(team(stage.winner)))}</div></div></div>` : '';
        return `<h2>${esc(stage.name)}</h2><div class="bracket">${cols.join('')}${champ}</div>`;
    }

    function teamTab() {
        const t = team(me);
        const bat = (id) => season.stats.bat[id];
        const lineupRows = t.lineup.map((s, i) => {
            const b = lg.players[s.id];
            const st = bat(s.id);
            const r = st ? battingRates(st) : null;
            return `<tr><td>${i + 1}</td><td><span class="pos">${s.pos}</span></td><td>${esc(playerName(b))}</td><td>${b.bats}</td>
                <td class="r">${rating(b.contact)}</td><td class="r">${rating(b.power)}</td><td class="r">${rating(b.eye)}</td>
                <td class="r">${st ? r.avg.toFixed(3).replace(/^0/, '') : '–'}</td><td class="r">${st ? r.ops.toFixed(3).replace(/^0/, '') : '–'}</td><td class="r">${st?.hr ?? 0}</td><td class="r">${st?.rbi ?? 0}</td></tr>`;
        }).join('');
        const staffRows = t.pitchers.map((id) => {
            const p = lg.players[id];
            const st = season.stats.pitch[id];
            const r = st ? pitchingRates(st, L.innings) : null;
            const rest = isRested(season, id) ? '<span class="ok">Ready</span>' : `<span class="muted">Rest ${restLeft(season, id)}d</span>`;
            return `<tr><td>${esc(playerName(p))} <span class="muted" style="font-size:11px">${p.role} ${p.throws}</span><div class="muted" style="font-size:11px">${p.pitches.map((x) => PITCH_TYPES[x.type].abbr).join(' ')}</div></td>
                <td class="r num">${p.velo}/${p.move}/${p.control}</td><td class="r">${p.stamina}</td>
                <td class="r">${st ? `${st.w}-${st.l}` : '–'}</td><td class="r">${st ? r.era.toFixed(2) : '–'}</td><td class="r">${st ? `${Math.floor(st.outs / 3)}.${st.outs % 3}` : '–'}</td><td class="r">${st?.k ?? 0}</td><td class="r">${rest}</td></tr>`;
        }).join('');
        return `<div class="card-head"><h3>Lineup</h3>${readOnly ? '' : '<button class="small" data-act="edit-lineup">Edit lineup card</button>'}</div>
            <table class="grid"><tr><th>#</th><th></th><th>Batter</th><th>B</th><th class="r">CON</th><th class="r">POW</th><th class="r">EYE</th><th class="r">AVG</th><th class="r">OPS</th><th class="r">HR</th><th class="r">RBI</th></tr>${lineupRows}</table>
            <h3 style="margin-top:16px">Pitching staff</h3>
            <table class="grid"><tr><th>Pitcher</th><th class="r">V/M/C</th><th class="r">STA</th><th class="r">W-L</th><th class="r">ERA</th><th class="r">IP</th><th class="r">K</th><th class="r">Status</th></tr>${staffRows}</table>
            <p class="muted" style="font-size:12px">Ratings are relative to the ${esc(L.name.toLowerCase())} level. ERA is per ${L.innings} innings.</p>`;
    }

    function leadersTab() {
        return `<div class="leaders">${Object.entries(LEADER_STATS).map(([key, def]) => {
            const rows = leaders(season, key);
            return `<div class="panel"><h3>${def.label}</h3>${rows.length ? rows.map((r, i) => {
                const p = lg.players[r.id];
                const t = lg.teams.find((x) => x.batters.includes(r.id) || x.pitchers.includes(r.id));
                return `<div class="leader ${t.id === me ? 'mine' : ''}"><span>${i + 1}. ${esc(shortName(p))} <span class="muted">${t.abbr}</span></span><b>${def.fmt(r.v)}</b></div>`;
            }).join('') : '<div class="muted">Not enough games yet.</div>'}</div>`;
        }).join('')}</div>`;
    }

    function draw() {
        const t = team(me);
        const body = { schedule: scheduleTab, standings: standingsTab, team: teamTab, leaders: leadersTab }[tab]();
        app.root.innerHTML = `
        <div class="page wide">
            <div class="page-head">
                <button data-act="back">← Menu</button>
                <h1>${L.icon} ${season.year} ${esc(season.title)}</h1>
                <span class="muted"><span class="swatch" style="background:${t.color}"></span><b>${esc(teamName(t))}</b> · ${record(me)}</span>
            </div>
            ${nextPanel()}
            <div class="tabs big" style="margin-top:12px">
                ${[['schedule', 'Schedule'], ['standings', 'Standings'], ['team', 'Your team'], ['leaders', 'Leaders']].map(([k, label]) =>
                    `<button data-tab="${k}" class="${tab === k ? 'sel' : ''}">${label}</button>`).join('')}
            </div>
            <div class="panel">${body}</div>
            ${readOnly ? '' : '<div class="row-actions"><button class="small" data-act="abandon">Abandon season</button></div>'}
        </div>`;
    }

    // Run a sim in small chunks so the page stays responsive.
    function runSim(stop, label) {
        if (savedHere() && !confirm('Your game in progress will be simmed from the start. Continue?')) return;
        if (savedHere()) app.clearGame();
        const startDay = season.day;
        const total = Math.max(1, season.schedule.filter((g) => !g.result).length);
        simming = { label, done: 0, total };
        cancelled = false;
        draw();
        const tick = () => {
            const t0 = performance.now();
            let finished = false;
            while (performance.now() - t0 < 25 && !finished && !cancelled) {
                finished = simStep(season, app.F, stop, startDay);
                simming.done = total - season.schedule.filter((g) => !g.result).length;
            }
            if (finished || cancelled) {
                simming = null;
                app.saveSeason();
                draw();
                return;
            }
            draw();
            setTimeout(tick, 0);
        };
        tick();
    }

    const onClick = (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.tab) { tab = btn.dataset.tab; draw(); return; }
        switch (btn.dataset.act) {
            case 'back': if (args.back) args.back(); else app.go('menu'); break;
            case 'new': app.go('seasonSetup'); break;
            case 'abandon':
                if (confirm('Abandon this season? It can’t be recovered.')) {
                    app.season = null;
                    app.saveSeason();
                    if (savedHere()) app.clearGame();
                    app.go('menu');
                }
                break;
            case 'stop': cancelled = true; break;
            case 'play': app.go('seasonLineup'); break;
            case 'resume': app.go('continue'); break;
            case 'sim-game': runSim(1, 'Simming today’s games…'); break;
            case 'sim-to-game': runSim('userGame', 'Simming to your next game…'); break;
            case 'sim-week': runSim(7, 'Simming 7 days…'); break;
            case 'sim-end': runSim('end', `Simming the rest of the ${season.level === 'youth' ? 'tournament' : 'season'}…`); break;
            case 'edit-lineup': app.go('seasonLineup', { editOnly: true }); break;
        }
    };
    app.root.addEventListener('click', onClick);
    draw();
    return () => {
        cancelled = true;
        app.root.removeEventListener('click', onClick);
    };
}

// Lineup card before a season game (or just to edit the lineup).
export function renderSeasonLineup(app, args = {}) {
    const season = app.season;
    const lg = season.league;
    const me = season.userTeamId;
    const g = userGameToday(season);
    if (!g && !args.editOnly) return renderSeason(app);
    const t = lg.teams[me];
    const day = g ? g.day : season.day;
    const order = [...t.pitchers].sort((a, b) => (lg.players[a].role === 'SP' ? 0 : 1) - (lg.players[b].role === 'SP' ? 0 : 1));
    const nextUp = pickStarter(season, me, day);
    const opp = g ? lg.teams[g.home === me ? g.away : g.home] : null;
    return renderLineup(app, {
        league: lg,
        teamId: me,
        title: args.editOnly ? `${teamName(t)}: lineup card` : `${g.home === me ? 'vs' : 'at'} ${teamName(opp)} · ${gameLabel(g)}`,
        playLabel: args.editOnly ? 'Save lineup' : 'Play ball!',
        pitchers: args.editOnly ? null : order.map((id) => ({
            id,
            available: isRested(season, id, day),
            note: isRested(season, id, day) ? (id === nextUp ? 'next up' : 'ready') : `resting ${restLeft(season, id, day)} more day${restLeft(season, id, day) > 1 ? 's' : ''}`,
        })),
        starterId: nextUp,
        onBack: () => app.go('season'),
        onPlay: (lineup, starterId) => {
            if (args.editOnly) {
                app.saveSeason();
                app.go('season', { tab: 'team' });
                return;
            }
            simOthersToday(season, app.F);
            const game = makeGame(season, app.F, g, { userTeamId: me, user: { lineup, starterId }, seed: Date.now() >>> 0 });
            app.saveSeason();
            app.saveGame(game, { seasonGameId: g.id });
            app.go('game', { game, seasonGameId: g.id });
        },
    });
}
