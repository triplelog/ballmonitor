// Entry point: loads the league, formulas and preferences, and switches
// between screens. Each screen renders into #app and returns a cleanup
// function.

import { generateLeague, ensureTypeSkills } from '../engine/league.js';
import { seedHistory } from '../engine/pitchStats.js';
import { createFormulas } from '../engine/formulas.js';
import { Game } from '../engine/game.js';
import { store } from './storage.js';
import { renderMenu, renderQuickSetup, renderLineup } from './screens.js';
import { renderGame } from './gameScreen.js';
import { renderLab, readShared } from './lab.js';
import { renderChallenges } from './challengesScreen.js';
import { CHALLENGE_BY_ID, challengeLeague, challengeFormulas } from '../engine/challenges.js';
import { createTracker } from '../engine/tracker.js';
import { renderSeason, renderSeasonSetup, renderSeasonLineup } from './seasonScreens.js';
import { recordGame, SEASON_VERSION } from '../engine/season.js';
import { renderMultiplayer, renderMpGame } from './mpScreens.js';
import { renderCareers, renderCareerHub } from './careerScreens.js';
import { careerStore } from './idb.js';
import { recordCareerGame, CAREER_VERSION } from '../engine/career.js';

const LEAGUE_VERSION = 1;

// Modes that are built but not open yet: Quick Game and Challenges come
// first. Their screens go back to the menu and their saves wait.
const COMING_LATER = new Set(['season', 'seasonSetup', 'seasonLineup', 'multiplayer', 'mpGame', 'careers', 'careerHub']);

const DEFAULT_PREFS = {
    userTeamId: 0, oppTeamId: 1, userHome: true, innings: 9, difficulty: 2,
    showOdds: true, showHeat: false, clockSeconds: 20,
};

const F = createFormulas(store.load('formulas', {}));

// Every league starts with a simulated past (for batters' records against
// each pitch type).
function prepareLeague(league) {
    ensureTypeSkills(league);
    if (!league.historyGames) {
        seedHistory(league, F);
        store.save('league', league);
    }
    return league;
}

function loadLeague() {
    const saved = store.load('league');
    if (saved && saved.version === LEAGUE_VERSION) return prepareLeague(saved);
    return newLeague();
}

function newLeague() {
    const league = generateLeague(Date.now() >>> 0);
    league.version = LEAGUE_VERSION;
    return prepareLeague(league);
}

const app = {
    root: document.getElementById('app'),
    league: loadLeague(),
    F,
    prefs: { ...DEFAULT_PREFS, ...store.load('prefs', {}) },
    cleanup: null,

    season: (() => {
        const s = store.load('season');
        // Seasons from before the new formats can't continue.
        if (!s || s.version !== SEASON_VERSION) return null;
        ensureTypeSkills(s.league);
        return s;
    })(),
    saveSeason() {
        if (!this.season) { store.remove('season'); return; }
        if (!store.save('season', this.season) && !this.warnedFull) {
            this.warnedFull = true;
            alert('Your browser’s storage is full, so the season couldn’t be saved. Clearing old data (or abandoning another saved game) frees room.');
        }
    },
    // A season game the user played has ended: fold it into the season.
    finishSeasonGame(game, gameId) {
        const g = this.season?.schedule[gameId];
        if (!g || g.result) return;
        recordGame(this.season, g, game, this.F);
        this.saveSeason();
    },

    // The career being played (careers live in IndexedDB).
    career: null,
    async loadCareer(id) {
        if (this.career?.id === id) return this.career;
        const c = await careerStore.get(id);
        if (!c || c.version !== CAREER_VERSION) return null;
        this.career = c;
        return c;
    },
    saveCareer() {
        if (!this.career) return Promise.resolve();
        this.career.updatedAt = Date.now();
        return careerStore.put(this.career).catch((e) => alert(`Couldn’t save the career: ${e?.message ?? e}`));
    },
    // A start the user pitched has ended: fold it into the career.
    finishCareerGame(game, gameId) {
        const c = this.career;
        const g = c?.season?.schedule[gameId];
        if (!g || g.result) return;
        recordCareerGame(c, this.F, g, game);
        c.pendingStart = null;
        this.saveCareer();
    },

    savePrefs() { store.save('prefs', this.prefs); },
    saveLeague() { store.save('league', this.league); },
    newLeague() {
        this.league = newLeague();
        store.remove('game');
    },

    savedGame() {
        const saved = store.load('game');
        if (!saved || !saved.state || saved.state.over) return null;
        if (saved.careerId || saved.seasonGameId !== undefined) return null;   // coming later
        return saved;
    },
    // extra: { tracker, earned } kept with the game so achievements and
    // challenges carry on after a reload.
    saveGame(game, extra = {}) { store.save('game', { state: game.toJSON(), ...extra }); },
    clearGame() { store.remove('game'); },

    go(screen, args) {
        if (COMING_LATER.has(screen)) screen = 'menu';
        if (this.cleanup) this.cleanup();
        this.cleanup = null;
        this.root.innerHTML = '';
        window.scrollTo(0, 0);
        const screens = {
            menu: () => renderMenu(this),
            quick: () => renderQuickSetup(this),
            lineup: () => renderLineup(this, args),
            game: () => renderGame(this, args),
            lab: () => renderLab(this),
            challenges: () => renderChallenges(this, args),
            season: () => renderSeason(this, args),
            seasonSetup: () => renderSeasonSetup(this),
            seasonLineup: () => renderSeasonLineup(this, args),
            multiplayer: () => renderMultiplayer(this, args),
            mpGame: () => renderMpGame(this, args),
            careers: () => renderCareers(this),
            careerHub: () => renderCareerHub(this, args),
            continue: () => {
                const saved = this.savedGame();
                if (!saved) return renderMenu(this);
                if (saved.careerId) {
                    // Load the career, then pick the start back up.
                    let cleanup = null;
                    let gone = false;
                    this.loadCareer(saved.careerId).then((career) => {
                        if (gone) return;
                        if (!career?.season) { this.clearGame(); this.go('careers'); return; }
                        const game = new Game(career.season.league, this.F, saved.state);
                        cleanup = renderGame(this, { game, career, seasonGameId: saved.seasonGameId, tracker: saved.tracker, earned: saved.earned });
                    });
                    return () => { gone = true; if (cleanup) cleanup(); };
                }
                const ch = CHALLENGE_BY_ID[saved.state.challengeId];
                const tracker = saved.tracker ?? createTracker();
                const earned = saved.earned ?? [];
                if (ch) {
                    const league = challengeLeague(this.league, ch, saved.state.userTeamId);
                    const game = new Game(league, challengeFormulas(ch), saved.state);
                    return renderGame(this, { game, challenge: ch, tracker, earned });
                }
                if (saved.seasonGameId !== undefined && this.season) {
                    const game = new Game(this.season.league, this.F, saved.state);
                    return renderGame(this, { game, tracker, earned, seasonGameId: saved.seasonGameId });
                }
                return renderGame(this, { game: new Game(this.league, this.F, saved.state), tracker, earned });
            },
        };
        this.cleanup = screens[screen]() || null;
    },
};

// A shared rules link (#formulas=…) offers to import them, whether the page
// was opened with it or the link was pasted into this tab.
function importSharedLink() {
    if (!location.hash.includes('formulas=')) return false;
    const shared = readShared(location.hash);
    history.replaceState(null, '', location.pathname);
    if (!shared || !confirm(`Import ${Object.keys(shared).length} shared formula(s) into your rules?`)) return false;
    const errors = [];
    for (const [id, text] of Object.entries(shared)) {
        const err = app.F.setText(id, text);
        if (err) errors.push(`${id}: ${err}`);
    }
    store.save('formulas', app.F.overrides());
    if (errors.length) alert(`Some formulas were not imported:\n${errors.join('\n')}`);
    app.go('lab');
    return true;
}
// An invite link (#join=CODE) opens the multiplayer lobby ready to join.
function openInvite() {
    const m = location.hash.match(/join=([A-Za-z0-9]+)/);
    if (!m) return false;
    history.replaceState(null, '', location.pathname);
    app.go('multiplayer', { code: m[1].toUpperCase() });
    return true;
}
window.addEventListener('hashchange', () => importSharedLink() || openInvite());
if (!importSharedLink() && !openInvite()) app.go('menu');
window.app27k = app;   // handy from the console
