// Challenges (set situations with a goal and star ratings) and the
// achievements earned in any game.

import { CHALLENGES, startChallenge, strongestOffense } from '../engine/challenges.js';
import { ACHIEVEMENTS } from '../engine/achievements.js';
import { teamName } from '../engine/league.js';
import { createTracker } from '../engine/tracker.js';
import { achievements, challengeRecords, recordChallenge } from './progress.js';
import { esc } from './storage.js';

const TIERS = [
    ['Quick', 'One inning or less'],
    ['Medium', 'A few innings, your offense simmed in between'],
    ['Epic', 'A whole game'],
];

export const starsHTML = (n, of = 3) =>
    `<span class="stars">${'★'.repeat(n)}<span class="off">${'★'.repeat(of - n)}</span></span>`;

export function renderChallenges(app, args = {}) {
    let tab = args.tab ?? 'challenges';
    const opp = strongestOffense(app.league, app.prefs.userTeamId);

    const draw = () => {
        const recs = challengeRecords();
        const ach = achievements();
        const totalStars = CHALLENGES.reduce((sum, c) => sum + (recs[c.id]?.stars ?? 0), 0);
        const earned = ACHIEVEMENTS.filter((a) => ach[a.id]).length;

        let body;
        if (tab === 'challenges') {
            body = `<p class="muted">You pitch for the ${esc(teamName(app.league.teams[app.prefs.userTeamId]))} (change your team in Quick Game) against the league’s best lineup, the ${esc(teamName(opp))}.
                Challenges use the standard formulas, plus any rules the challenge changes.</p>`
            + TIERS.map(([tier, sub]) => {
                const list = CHALLENGES.filter((c) => c.tier === tier);
                return `<h2 class="ch-tier">${tier} <span class="muted" style="font-size:13px;font-weight:400">${sub}</span></h2>
                <div class="ch-grid">${list.map((c) => {
                    const rec = recs[c.id];
                    return `<div class="panel ch-card">
                        <div class="card-head"><span class="ch-name">${c.icon} ${esc(c.name)}</span><span class="chip level-${c.level.replace(' ', '-').toLowerCase()}">${c.level}</span></div>
                        <div class="ch-desc">${esc(c.desc)}</div>
                        <div class="muted" style="font-size:11px">${c.stars.map((s, i) => `${'★'.repeat(i + 1)} ${esc(s)}`).join(' · ')}</div>
                        <div class="ch-foot">
                            <span>${starsHTML(rec?.stars ?? 0)} <span class="muted" style="font-size:11px">${rec ? `${rec.wins}/${rec.attempts} won` : 'not tried'}</span></span>
                            <button class="primary" data-play="${c.id}">Play</button>
                        </div>
                    </div>`;
                }).join('')}</div>`;
            }).join('');
        } else {
            const tiers = ['At-bat', 'Inning', 'Game'];
            body = `<p class="muted">Earned in any game you pitch: quick games, challenges and (soon) the season.</p>`
            + tiers.map((tier) => `<h2 class="ch-tier">${tier}</h2><div class="ach-grid">${ACHIEVEMENTS.filter((a) => a.tier === tier).map((a) => {
                const got = ach[a.id];
                return `<div class="panel ach ${got ? 'got' : ''}">
                    <div class="icon">${a.icon}</div>
                    <div><div class="a-name">${esc(a.name)}</div><div class="a-desc">${esc(a.desc)}</div>
                    ${got ? `<div class="a-when">Earned ${new Date(got.first).toLocaleDateString()}${got.count > 1 ? ` · ×${got.count}` : ''}</div>` : ''}</div>
                </div>`;
            }).join('')}</div>`).join('');
        }

        app.root.innerHTML = `
        <div class="page wide">
            <div class="page-head"><button data-act="back">← Menu</button><h1>Challenges & Achievements</h1>
                <span class="muted">${starsHTML(1, 1)} ${totalStars}/${CHALLENGES.length * 3} · 🏅 ${earned}/${ACHIEVEMENTS.length}</span></div>
            <div class="tabs big">
                <button data-tab="challenges" class="${tab === 'challenges' ? 'sel' : ''}">Challenges</button>
                <button data-tab="achievements" class="${tab === 'achievements' ? 'sel' : ''}">Achievements</button>
            </div>
            ${body}
        </div>`;
    };

    const onClick = (e) => {
        const btn = e.target.closest('button');
        if (!btn) return;
        if (btn.dataset.tab) { tab = btn.dataset.tab; draw(); }
        if (btn.dataset.act === 'back') app.go('menu');
        if (btn.dataset.play) playChallenge(app, btn.dataset.play);
    };
    app.root.addEventListener('click', onClick);
    draw();
    return () => app.root.removeEventListener('click', onClick);
}

export function playChallenge(app, id) {
    const ch = CHALLENGES.find((c) => c.id === id);
    const { game } = startChallenge(app.league, ch, app.prefs.userTeamId);
    recordChallenge(id, null);
    app.go('game', { game, challenge: ch, tracker: createTracker(), earned: [] });
}
