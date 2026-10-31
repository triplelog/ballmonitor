// Multiplayer: two people alternate pitching half-innings of one game.
//
// The home player pitches the top of each inning, the away player the
// bottom. Turns alternate between two phases:
//   pitch:  the fielding player throws the half-inning;
//   manage: before a team bats, its player sets the lineup card (before
//           the team's first at-bat) or makes substitutions.
// So the order is: away manages, home pitches the top, home manages,
// away pitches the bottom, away manages, ...
//
// The server is the referee. Browsers send only their inputs (which pitch,
// how hard, where they aimed, or a lineup move); the server runs the engine
// with a random-number state the browsers never see, checks every move
// against the rules, and enforces the optional time limit per turn by
// letting the computer finish an expired half. Player ids are secrets:
// they are never sent to anyone else.

import { mkdirSync, readdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';
import { generateLeague } from '../src/engine/league.js';
import { createFormulas } from '../src/engine/formulas.js';
import { LEVELS, levelGameOptions } from '../src/engine/levels.js';
import { seedHistory } from '../src/engine/pitchStats.js';
import { Game } from '../src/engine/game.js';

const CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const PITCH_LOG_MAX = 2000;

export class MpError extends Error {
    constructor(status, message, extra = {}) {
        super(message);
        this.status = status;
        this.extra = extra;
    }
}

const fieldingKey = (state) => (state.half === 'top' ? 'home' : 'away');
const battingKey = (state) => (state.half === 'top' ? 'away' : 'home');
const halfOf = (state) => `${state.inning}${state.half}`;
const cleanName = (n) => String(n ?? '').trim().slice(0, 24) || 'Player';
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const num = (v, fallback = 0) => (Number.isFinite(Number(v)) ? Number(v) : fallback);

export function createMpStore({ dir, now = () => Date.now() } = {}) {
    mkdirSync(dir, { recursive: true });
    const games = new Map();
    const formulas = new Map();      // game id -> compiled FormulaSet
    for (const f of readdirSync(dir)) {
        if (!f.endsWith('.json')) continue;
        try {
            const rec = JSON.parse(readFileSync(join(dir, f), 'utf8'));
            games.set(rec.id, rec);
        } catch { /* skip a damaged file */ }
    }

    function save(rec) {
        rec.updatedAt = now();
        const file = join(dir, `${rec.id}.json`);
        writeFileSync(file + '.tmp', JSON.stringify(rec));
        renameSync(file + '.tmp', file);
    }

    function find(idOrCode) {
        const key = String(idOrCode ?? '').trim();
        const rec = games.get(key) ?? [...games.values()].find((g) => g.code === key.toUpperCase());
        if (!rec) throw new MpError(404, 'No game with that code.');
        return rec;
    }

    const seatsOf = (rec, playerId) => ['home', 'away'].filter((k) => playerId && rec.seats[k]?.playerId === playerId);

    const formulasFor = (rec) => {
        if (!formulas.has(rec.id)) formulas.set(rec.id, createFormulas(rec.settings.formulas ?? {}));
        return formulas.get(rec.id);
    };

    // A working copy of the game, managed by `key`'s player.
    function load(rec, key) {
        const state = structuredClone(rec.state);
        state.userTeamId = key ? state.sides[key].teamId : null;
        return new Game(rec.league, formulasFor(rec), state);
    }

    function commit(rec, game) {
        game.state.userTeamId = null;
        rec.state = game.state;
        rec.version += 1;
    }

    function newTurn(rec, key, phase) {
        rec.turn = {
            key, phase, half: halfOf(rec.state), since: now(),
            deadline: rec.settings.timeLimit ? now() + rec.settings.timeLimit * 1000 : null,
        };
    }

    function finishIfOver(rec) {
        if (!rec.state.over) return false;
        rec.status = 'done';
        rec.turn = null;
        rec.result = { winner: rec.state.winner, score: { ...rec.state.score }, innings: rec.state.inning };
        return true;
    }

    // The game just became active: the away team bats first.
    function firstTurn(rec) {
        if (rec.settings.manage) newTurn(rec, battingKey(rec.state), 'manage');
        else newTurn(rec, fieldingKey(rec.state), 'pitch');
    }

    // After a pitch: if the half ended, the player who just pitched manages
    // his hitters (who bat next), unless he timed out.
    function afterPitch(rec, { skipManage = false } = {}) {
        if (finishIfOver(rec)) return;
        if (rec.turn.half === halfOf(rec.state)) return;
        if (rec.settings.manage && !skipManage) newTurn(rec, battingKey(rec.state), 'manage');
        else newTurn(rec, fieldingKey(rec.state), 'pitch');
    }

    // An expired turn: the computer finishes the half, or managing ends
    // with no changes.
    function enforceDeadline(rec) {
        if (rec.status !== 'active' || !rec.turn?.deadline || now() < rec.turn.deadline) return false;
        const { key, phase } = rec.turn;
        const who = rec.seats[key]?.name ?? key;
        if (phase === 'manage') {
            const game = load(rec, null);
            game.log(`Time ran out for ${who}: no lineup changes.`, 'info');
            commit(rec, game);
            newTurn(rec, fieldingKey(rec.state), 'pitch');
        } else {
            const game = load(rec, null);
            game.state.settings = { ...game.state.settings, humanSides: game.state.settings.humanSides.filter((k) => k !== key) };
            game.log(`Time ran out for ${who}: the computer finished the half.`, 'info');
            game.simHalfInning();
            game.state.settings = { ...game.state.settings, humanSides: ['home', 'away'] };
            commit(rec, game);
            afterPitch(rec, { skipManage: true });
        }
        rec.timeouts = { ...(rec.timeouts ?? {}), [key]: (rec.timeouts?.[key] ?? 0) + 1 };
        return true;
    }

    function checkAll() {
        for (const rec of games.values()) if (enforceDeadline(rec)) save(rec);
    }

    function requireTurn(rec, body, phase) {
        if (enforceDeadline(rec)) {
            save(rec);
            throw new MpError(409, 'Time ran out for this turn.', { game: view(rec, body.playerId) });
        }
        if (rec.status !== 'active') throw new MpError(409, 'This game is not in progress.', { game: view(rec, body.playerId) });
        if (Number(body.version) !== rec.version) throw new MpError(409, 'The game has moved on.', { game: view(rec, body.playerId) });
        if (!body.playerId || rec.seats[rec.turn.key]?.playerId !== body.playerId) throw new MpError(403, 'It is not your turn.');
        if (rec.turn.phase !== phase) throw new MpError(409, phase === 'pitch' ? 'It is time to manage, not pitch.' : 'It is time to pitch, not manage.');
    }

    // What a player may see: no one's player id, no random-number state,
    // no pitch log; seats say which are yours.
    function view(rec, playerId, { league = false } = {}) {
        const mine = seatsOf(rec, playerId);
        const { rngState, ...state } = rec.state;
        void rngState;
        return {
            id: rec.id, code: rec.code, version: rec.version, status: rec.status,
            createdAt: rec.createdAt, updatedAt: rec.updatedAt,
            settings: rec.settings,
            seats: Object.fromEntries(['home', 'away'].map((k) => [k, rec.seats[k] ? { name: rec.seats[k].name, mine: mine.includes(k) } : null])),
            state, turn: rec.turn, result: rec.result ?? null, resigned: rec.resigned ?? null, timeouts: rec.timeouts ?? {},
            ...(league ? { league: rec.league } : {}),
        };
    }

    function summary(rec, playerId) {
        const mine = seatsOf(rec, playerId);
        const st = rec.state;
        const team = (k) => rec.league.teams[st.sides[k].teamId];
        const t = (k) => ({ name: `${team(k).city} ${team(k).name}`, abbr: team(k).abbr, color: team(k).color });
        return {
            id: rec.id, code: rec.code, status: rec.status, version: rec.version,
            level: rec.settings.level, innings: rec.settings.innings, timeLimit: rec.settings.timeLimit,
            seats: { home: rec.seats.home?.name ?? null, away: rec.seats.away?.name ?? null },
            teams: { home: t('home'), away: t('away') },
            mine,
            score: { ...st.score }, inning: st.inning, half: st.half, outs: st.outs,
            turn: rec.turn, myTurn: rec.status === 'active' && !!rec.turn && mine.includes(rec.turn.key),
            result: rec.result ?? null, resigned: rec.resigned ?? null, timeouts: rec.timeouts ?? {},
            createdAt: rec.createdAt, updatedAt: rec.updatedAt,
        };
    }

    return {
        // body: { playerId, name, level, innings, timeLimit (seconds or null),
        //         side ('home' | 'away' | 'random'), both (both seats),
        //         manage (lineup/substitution turns, default on), formulas, difficulty }
        create(body) {
            const playerId = String(body.playerId ?? '');
            if (playerId.length < 8) throw new MpError(400, 'Missing player id.');
            const level = LEVELS[body.level] ? body.level : 'pro';
            const L = LEVELS[level];
            const rules = body.formulas && typeof body.formulas === 'object' ? body.formulas : {};
            const F = createFormulas(rules);
            const seed = randomBytes(4).readUInt32LE(0);
            const full = generateLeague(seed, { level });
            seedHistory(full, F, full.teams.length * 10);
            const ids = [...full.teams.keys()].sort(() => Math.random() - 0.5).slice(0, 2);
            const league = trimLeague(full, ids);
            const innings = clamp(Math.round(num(body.innings, L.innings)), 1, 12);
            const timeLimit = body.timeLimit ? Math.max(30, num(body.timeLimit, 0)) : null;
            const difficulty = clamp(Math.round(num(body.difficulty, 2)), 1, 5);
            const game = Game.create(league, F, {
                ...levelGameOptions(level), innings, homeId: 0, awayId: 1,
                seed: randomBytes(4).readUInt32LE(0), difficulty, humanSides: ['home', 'away'],
            });
            game.state.log = [];
            const side = body.side === 'home' || body.side === 'away' ? body.side : (Math.random() < 0.5 ? 'home' : 'away');
            const me = { playerId, name: cleanName(body.name) };
            const seats = { home: null, away: null };
            seats[side] = me;
            if (body.both) seats[side === 'home' ? 'away' : 'home'] = { ...me };
            let code;
            do {
                code = Array.from(randomBytes(6), (b) => CODE_CHARS[b % CODE_CHARS.length]).join('');
            } while ([...games.values()].some((g) => g.code === code));
            const rec = {
                id: randomBytes(8).toString('hex'), code, version: 1,
                createdAt: now(), updatedAt: now(),
                settings: { level, innings, timeLimit, formulas: rules, difficulty, manage: body.manage !== false },
                league, seats,
                status: seats.home && seats.away ? 'active' : 'waiting',
                state: game.state, turn: null, pitchLog: [],
            };
            if (rec.status === 'active') firstTurn(rec);
            games.set(rec.id, rec);
            save(rec);
            return view(rec, playerId, { league: true });
        },

        join(idOrCode, body) {
            const rec = find(idOrCode);
            const playerId = String(body.playerId ?? '');
            if (playerId.length < 8) throw new MpError(400, 'Missing player id.');
            if (!seatsOf(rec, playerId).length) {
                const open = ['home', 'away'].find((k) => !rec.seats[k]);
                if (!open || rec.status !== 'waiting') throw new MpError(409, 'That game is full.');
                rec.seats[open] = { playerId, name: cleanName(body.name) };
                rec.status = 'active';
                rec.version += 1;
                firstTurn(rec);
                save(rec);
            }
            return view(rec, playerId, { league: true });
        },

        get(idOrCode, playerId, opts = {}) {
            const rec = find(idOrCode);
            if (enforceDeadline(rec)) save(rec);
            return view(rec, playerId, opts);
        },

        list(playerId) {
            checkAll();
            return [...games.values()]
                .filter((g) => seatsOf(g, playerId).length)
                .sort((a, b) => b.updatedAt - a.updatedAt)
                .map((g) => summary(g, playerId));
        },

        // One pitch: { playerId, version, pitchIdx, effort, moveEffort,
        // aim: {x, y} | null, t, clockLeft, clockViolation }.
        pitch(idOrCode, body) {
            const rec = find(idOrCode);
            requireTurn(rec, body, 'pitch');
            const key = rec.turn.key;
            const game = load(rec, key);
            if (game.mustChangePitcher(key)) throw new MpError(409, 'Pitch limit reached: bring in a reliever first.');
            const pitcher = game.pitcher();
            const pitchIdx = Math.round(num(body.pitchIdx, -1));
            if (pitchIdx < 0 || pitchIdx >= pitcher.pitches.length) throw new MpError(400, 'No such pitch.');
            const opts = {
                pitchIdx,
                effort: clamp(num(body.effort, 50), 0, 100),
                moveEffort: clamp(num(body.moveEffort, 50), 0, 100),
                t: clamp(num(body.t, 0), 0, 120),
                clockLeft: body.clockLeft == null ? null : clamp(num(body.clockLeft, 0), 0, 120),
            };
            if (body.clockViolation || !body.aim) opts.clockViolation = true;
            else opts.aim = { x: clamp(num(body.aim.x), -60, 60), y: clamp(num(body.aim.y), -60, 60) };
            const result = game.throwPitch(opts);
            rec.pitchLog.push({ at: now(), key, ...opts, call: result.call, play: result.play ?? null });
            if (rec.pitchLog.length > PITCH_LOG_MAX) rec.pitchLog.splice(0, rec.pitchLog.length - PITCH_LOG_MAX);
            commit(rec, game);
            afterPitch(rec);
            save(rec);
            return { result, game: view(rec, body.playerId) };
        },

        // A managing move: { playerId, version, action }. Actions:
        //   { type: 'changePitcher', pitcherId }            (pitching)
        //   { type: 'setLineup', lineup: [{ id, pos }×9] }   (managing, before first at-bat)
        //   { type: 'sub', slot, benchId }                    (managing)
        //   { type: 'done' }                                  (managing: let them pitch)
        action(idOrCode, body) {
            const rec = find(idOrCode);
            const a = body.action ?? {};
            requireTurn(rec, body, a.type === 'changePitcher' ? 'pitch' : 'manage');
            const key = rec.turn.key;
            const game = load(rec, key);
            try {
                switch (a.type) {
                    case 'changePitcher': {
                        const id = Number(a.pitcherId);
                        if (!game.bullpen(key).includes(id)) throw new Error('That pitcher isn’t available.');
                        game.changePitcher(key, id);
                        break;
                    }
                    case 'setLineup': game.setLineup(key, a.lineup); break;
                    case 'sub': {
                        const slot = Math.round(num(a.slot, -1));
                        if (slot < 0 || slot > 8) throw new Error('No such lineup spot.');
                        game.pinchHit(key, Number(a.benchId), slot);
                        break;
                    }
                    case 'done': break;
                    default: throw new Error('Unknown move.');
                }
            } catch (e) {
                throw new MpError(400, e.message);
            }
            commit(rec, game);
            if (a.type === 'done') newTurn(rec, fieldingKey(rec.state), 'pitch');
            save(rec);
            return view(rec, body.playerId);
        },

        resign(idOrCode, body) {
            const rec = find(idOrCode);
            const mine = seatsOf(rec, body.playerId);
            if (!mine.length) throw new MpError(403, 'You are not in this game.');
            if (rec.status === 'done') return view(rec, body.playerId);
            const loser = mine.length === 2 ? rec.turn?.key ?? mine[0] : mine[0];
            rec.status = 'done';
            rec.resigned = loser;
            rec.result = { winner: loser === 'home' ? 'away' : 'home', score: { ...rec.state.score }, innings: rec.state.inning };
            rec.turn = null;
            rec.version += 1;
            save(rec);
            return view(rec, body.playerId);
        },

        // For the host: every pitch's inputs, to look into suspicious games.
        pitchLog: (idOrCode) => find(idOrCode).pitchLog,
    };
}

// Just the two teams (re-numbered 0 = home, 1 = away), their players, and
// their batters' records against each pitch type.
function trimLeague(full, [homeIdx, awayIdx]) {
    const teams = [homeIdx, awayIdx].map((i, n) => ({ ...full.teams[i], id: n }));
    const players = {};
    const pitchStats = {};
    for (const t of teams) {
        for (const id of [...t.batters, ...t.pitchers]) players[id] = full.players[id];
        for (const id of t.batters) if (full.pitchStats?.[id]) pitchStats[id] = full.pitchStats[id];
    }
    return { seed: full.seed, level: full.level, teams, players, pitchStats, historyGames: full.historyGames, nextId: full.nextId };
}
