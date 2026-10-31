// One game of baseball, pitch by pitch. The state is plain JSON (saveable);
// the Game class wraps it with the league, the formulas and an rng.
//
// The same throwPitch() runs every pitch, whether a person aimed it on the
// moving strike zone or the computer picked a spot.

import { createRng } from './rng.js';
import { PITCH_TYPES, FIELD_POSITIONS } from './data.js';
import { shapePitch, landPitch, locationScope, battingSide, vsPitchRating } from './pitch.js';
import { aiChoosePitch, aiPickReliever } from './ai.js';
import { shortName, skillVs } from './league.js';
import { NEUTRAL_SCOPE } from './formulas.js';
import { recordPitch } from './pitchStats.js';

const other = (key) => (key === 'away' ? 'home' : 'away');

const FIELDS = { L: 'left', C: 'center', R: 'right' };

export class Game {
    constructor(league, F, state) {
        this.league = league;
        this.F = F;
        this.state = state;
        this.rng = createRng(state.rngState);
    }

    // opts: homeId, awayId, userTeamId (null for computer vs computer),
    // innings, difficulty, seed, kOnly, level (1–4), levelVelo, mercy
    // ({ runs, after } or null), home/away: { lineup, starterId, unavailable }
    static create(league, F, opts) {
        const seed = opts.seed ?? Date.now();
        const side = (teamId, o = {}) => {
            const team = league.teams[teamId];
            const starterId = o.starterId ?? team.rotation[team.nextStarter % team.rotation.length];
            return {
                teamId,
                lineup: (o.lineup ?? team.lineup).map((s) => ({ ...s })),
                batIdx: 0,
                pitcherId: starterId,
                pitchersUsed: [starterId],
                removed: [],
                status: { [starterId]: { fatigue: 0, pitches: 0 } },
                // Pitchers resting from earlier games (seasons).
                unavailable: o.unavailable ?? [],
            };
        };
        const level = opts.level ?? 4;
        const state = {
            version: 1,
            rngState: seed >>> 0,
            // kOnly: only strikeouts make outs; a ball caught for an out is a strike instead.
            settings: {
                innings: opts.innings ?? 9, difficulty: opts.difficulty ?? 2, kOnly: !!opts.kOnly,
                level, levelVelo: opts.levelVelo ?? 0, mercy: opts.mercy ?? null,
                pitchLimit: F.eval('pitchLimit', { ...NEUTRAL_SCOPE, level, levelVelo: opts.levelVelo ?? 0 }),
                // Sides a person manages (multiplayer): the computer never
                // changes their pitchers.
                humanSides: opts.humanSides ?? [],
            },
            userTeamId: opts.userTeamId ?? null,
            sides: { away: side(opts.awayId, opts.away), home: side(opts.homeId, opts.home) },
            inning: 1, half: 'top', outs: 0, balls: 0, strikes: 0,
            bases: [null, null, null],
            score: { away: 0, home: 0 },
            line: { away: [0], home: [] },
            hits: { away: 0, home: 0 },
            errors: { away: 0, home: 0 },
            pa: null,
            box: { bat: {}, pitch: {} },
            log: [],
            over: false,
            winner: null,
        };
        const game = new Game(league, F, state);
        game.startPA();
        return game;
    }

    toJSON() { return this.state; }

    // ---- who is where ----
    get battingKey() { return this.state.half === 'top' ? 'away' : 'home'; }
    get fieldingKey() { return other(this.battingKey); }
    side(key) { return this.state.sides[key]; }
    team(key) { return this.league.teams[this.side(key).teamId]; }
    player(id) { return this.league.players[id]; }
    batter() {
        const s = this.side(this.battingKey);
        return this.player(s.lineup[s.batIdx].id);
    }
    pitcher() { return this.player(this.side(this.fieldingKey).pitcherId); }
    pitcherStatus(key = this.fieldingKey) {
        const s = this.side(key);
        return s.status[s.pitcherId];
    }
    userKey() {
        const { userTeamId, sides } = this.state;
        if (userTeamId === null) return null;
        return sides.home.teamId === userTeamId ? 'home' : 'away';
    }
    // The computer makes pitching changes for a side unless the user or
    // (in multiplayer) a person manages it.
    computerManages(key) {
        return this.userKey() !== key && !(this.state.settings.humanSides ?? []).includes(key);
    }
    isUserPitching() { return !this.state.over && this.userKey() === this.fieldingKey; }
    isUserBatting() { return !this.state.over && this.userKey() === this.battingKey; }

    // Players on the bench who can still come in.
    bench(key) {
        const s = this.side(key);
        const inLineup = new Set(s.lineup.map((l) => l.id));
        return this.team(key).batters.filter((id) => !inLineup.has(id) && !s.removed.includes(id));
    }
    bullpen(key) {
        const s = this.side(key);
        return this.team(key).pitchers.filter((id) => !s.pitchersUsed.includes(id) && !(s.unavailable ?? []).includes(id));
    }

    // At the pitch limit, the pitcher must come out (if anyone is left).
    mustChangePitcher(key = this.fieldingKey) {
        const st = this.pitcherStatus(key);
        return st.pitches >= (this.state.settings.pitchLimit ?? Infinity) && this.bullpen(key).length > 0;
    }

    // ---- formula variables ----
    situationScope() {
        const st = this.state;
        const status = this.pitcherStatus();
        const pitcher = this.pitcher();
        return {
            ...NEUTRAL_SCOPE,
            balls: st.balls, strikes: st.strikes, outs: st.outs, inning: st.inning,
            runners: st.bases.filter(Boolean).length,
            risp: st.bases[1] || st.bases[2] ? 1 : 0,
            scoreDiff: st.score[this.fieldingKey] - st.score[this.battingKey],
            difficulty: st.settings.difficulty,
            level: st.settings.level ?? 4,
            levelVelo: st.settings.levelVelo ?? 0,
            fatigue: status.fatigue,
            pitchCount: status.pitches,
            stamina: pitcher.stamina,
            t: 0,
        };
    }

    // type: the pitch type (its kind's rating plus the batter's skill
    // against that particular pitch make vsPitch).
    batterScope(batter, pitcher, type = 'Four-Seam') {
        const side = battingSide(batter, pitcher);
        return {
            contact: batter.contact, power: batter.power, eye: batter.eye, speed: batter.speed,
            vsPitch: vsPitchRating(batter, PITCH_TYPES[type].kind) + skillVs(batter, type),
            platoon: side === pitcher.throws ? 1 : 0,
            runnerSpeed: batter.speed,
            heat: 0,
        };
    }

    // The pitch as it would come out with these efforts (for the UI preview
    // and for the computer's aim).
    previewPitch(pitchIdx, efforts, extra = {}) {
        const pitcher = this.pitcher();
        const batter = this.batter();
        const type = pitcher.pitches[pitchIdx].type;
        const scope = { ...this.situationScope(), ...this.batterScope(batter, pitcher, type), ...extra };
        return shapePitch(this.F, pitcher, pitchIdx, efforts, scope);
    }

    // ---- the pitch ----
    // opts: pitchIdx, effort, moveEffort, aim {x, y} relative to the zone,
    //       t (seconds the zone moved), clockViolation, extraScatter
    throwPitch(opts) {
        const st = this.state;
        if (st.over) throw new Error('Game is over');
        const F = this.F;
        const rng = this.rng;
        const pitcher = this.pitcher();
        const batter = this.batter();
        const side = battingSide(batter, pitcher);
        const shape = this.previewPitch(opts.pitchIdx, opts, { t: opts.t ?? 0 });
        const s = shape.scope;

        // What the batter has seen this at-bat.
        const seen = st.pa.pitches;
        const last = seen[seen.length - 1];
        s.pitchSeen = seen.filter((p) => p.type === shape.name).length;
        s.sameAsLast = last && last.type === shape.name ? 1 : 0;
        s.veloDiff = last ? shape.velocity - last.velocity : 0;

        const result = {
            pitch: { name: shape.name, abbr: shape.abbr, kind: shape.kind, color: shape.color, velocity: shape.velocity },
            aim: opts.aim ? { ...opts.aim } : null,
            loc: null, probs: {}, call: null, play: null, text: '', runs: 0,
            paEnded: false, halfEnded: false, gameOver: false,
            batterId: batter.id, pitcherId: pitcher.id,
            // The situation before this pitch, for stats and achievements.
            before: {
                balls: st.balls, strikes: st.strikes, outs: st.outs, inning: st.inning, half: st.half,
                bases: st.bases.map(Boolean), batIdx: this.side(this.battingKey).batIdx,
                score: { ...st.score },
            },
            clockLeft: opts.clockLeft ?? null,
        };

        if (opts.clockViolation) {
            result.call = 'clock';
        } else {
            const loc = landPitch(shape, opts.aim, rng, opts.extraScatter ?? 0);
            result.loc = loc;
            Object.assign(s, locationScope(loc, batter, side));
            s.locDiff = last && last.x !== undefined ? Math.hypot(loc.x - last.x, loc.y - last.y) : 0;
            const p = result.probs;
            p.hbp = F.eval('hbpChance', s);
            if (rng.chance(p.hbp)) {
                result.call = 'hbp';
            } else {
                p.swing = F.eval('swingChance', s);
                if (!rng.chance(p.swing)) {
                    p.strike = F.eval('strikeCall', s);
                    result.call = rng.chance(p.strike) ? 'called' : 'ball';
                } else {
                    p.contact = F.eval('contactChance', s);
                    if (!rng.chance(p.contact)) {
                        result.call = 'swinging';
                    } else {
                        p.foul = F.eval('foulChance', s);
                        result.call = rng.chance(p.foul) ? 'foul' : 'inplay';
                    }
                }
            }
        }

        // Fatigue and the pitch count.
        const status = this.pitcherStatus();
        // Capped so an exhausted pitcher is bad, not absurd.
        status.fatigue = Math.min(1.5, status.fatigue + F.eval('fatigueGain', s));
        status.pitches += 1;
        const pbox = this.pitchBox(pitcher.id);
        pbox.pitches += 1;
        if (['called', 'swinging', 'foul', 'inplay'].includes(result.call)) pbox.strikes += 1;

        seen.push({
            type: shape.name, abbr: shape.abbr, kind: shape.kind, color: shape.color,
            velocity: shape.velocity, call: result.call,
            ...(result.loc ? { x: result.loc.x, y: result.loc.y } : {}),
        });

        this.applyCall(result, s);
        result.after ??= this.snapshot();
        seen[seen.length - 1].call = result.call;
        recordPitch(this.league, batter.id, shape.name, result);
        st.rngState = this.rng.seed;
        return result;
    }

    applyCall(result, s) {
        const st = this.state;
        const callText = {
            ball: 'Ball', called: 'Called strike', swinging: 'Swinging strike', foul: 'Foul ball',
            hbp: 'Hit by pitch', clock: 'Pitch clock violation: ball', inplay: 'In play',
        }[result.call];
        result.text = callText;

        switch (result.call) {
            case 'ball':
            case 'clock':
                st.balls += 1;
                if (st.balls >= 4) this.endPA(result, 'BB', s);
                break;
            case 'called':
            case 'swinging':
                st.strikes += 1;
                if (st.strikes >= 3) this.endPA(result, result.call === 'called' ? 'KL' : 'K', s);
                break;
            case 'foul':
                if (st.strikes < 2) st.strikes += 1;
                break;
            case 'hbp':
                this.endPA(result, 'HBP', s);
                break;
            case 'inplay': {
                const play = this.ballInPlay(result, s);
                if (st.settings.kOnly && ['GO', 'FO', 'PO', 'E'].includes(play)) {
                    // Strikeouts-only rules: caught is a strike, even strike three.
                    result.call = 'caught';
                    result.text = 'Caught: a strike';
                    st.strikes += 1;
                    if (st.strikes >= 3) this.endPA(result, 'K', s);
                } else {
                    this.endPA(result, play, s);
                }
                break;
            }
        }
    }

    ballInPlay(result, s) {
        const F = this.F;
        const rng = this.rng;
        const p = result.probs;
        p.hit = F.eval('hitChance', s);
        if (rng.chance(p.hit)) {
            p.extraBase = F.eval('extraBaseChance', s);
            if (!rng.chance(p.extraBase)) return '1B';
            p.homer = F.eval('homerShare', s);
            if (rng.chance(p.homer)) return 'HR';
            p.triple = F.eval('tripleShare', s);
            return rng.chance(p.triple) ? '3B' : '2B';
        }
        p.error = F.eval('errorChance', s);
        if (rng.chance(p.error)) return 'E';
        p.ground = F.eval('groundBallShare', s);
        if (rng.chance(p.ground)) return 'GO';
        p.popup = F.eval('popupShare', s);
        return rng.chance(p.popup) ? 'PO' : 'FO';
    }

    // ---- plate appearance results ----
    endPA(result, play, s) {
        const st = this.state;
        const bk = this.battingKey;
        const batter = this.batter();
        const pitcher = this.pitcher();
        const bbox = this.batBox(batter.id);
        const pbox = this.pitchBox(pitcher.id);
        const name = shortName(batter);
        const runnerEntry = { id: batter.id, resp: pitcher.id };
        const scored = [];
        let rbi = 0;
        const outsBefore = st.outs;

        // Score a runner. Runs on the third out never count, so outs are
        // recorded before runners move.
        const score = (entry, countsRbi = true) => {
            if (st.outs >= 3) return;
            st.score[bk] += 1;
            st.line[bk][st.line[bk].length - 1] += 1;
            this.batBox(entry.id).r += 1;
            const rp = this.pitchBox(entry.resp);
            rp.r += 1;
            if (!entry.unearned) rp.er += 1;
            if (countsRbi) rbi += 1;
            scored.push(entry.id);
        };
        const runnerScope = (entry) => ({ ...s, outs: st.outs, runnerSpeed: this.player(entry.id).speed });
        const roll = (id, entry) => {
            const v = this.F.eval(id, runnerScope(entry));
            result.probs[id] = v;
            return this.rng.chance(v);
        };
        const b = st.bases;
        const forceAdvance = (entry) => {
            if (b[0]) {
                if (b[1]) {
                    if (b[2]) score(b[2]);
                    b[2] = b[1];
                }
                b[1] = b[0];
            }
            b[0] = entry;
        };
        const field = () => {
            const side = battingSide(batter, pitcher);
            return FIELDS[this.rng.weighted(['L', 'C', 'R'], (f) => (f === 'C' ? 1 : (f === 'L') === (side === 'R') ? 1.3 : 0.8))];
        };
        const out = () => { st.outs += 1; pbox.outs += 1; };

        let text;
        bbox.pa += 1;
        pbox.bf += 1;
        switch (play) {
            case 'K':
            case 'KL':
                bbox.ab += 1; bbox.k += 1; pbox.k += 1;
                out();
                text = play === 'K' ? `${name} struck out swinging.` : `${name} struck out looking.`;
                break;
            case 'BB':
            case 'HBP':
                if (play === 'BB') { bbox.bb += 1; pbox.bb += 1; } else { bbox.hbp += 1; pbox.hbp += 1; }
                forceAdvance(runnerEntry);
                text = play === 'BB' ? `${name} walked.` : `${name} was hit by the pitch.`;
                break;
            case '1B': {
                if (b[2]) { score(b[2]); b[2] = null; }
                if (b[1]) {
                    if (roll('scoreFromSecond', b[1])) score(b[1]); else b[2] = b[1];
                    b[1] = null;
                }
                if (b[0]) {
                    if (!b[2] && roll('firstToThird', b[0])) b[2] = b[0]; else b[1] = b[0];
                    b[0] = null;
                }
                b[0] = runnerEntry;
                text = `${name} singled to ${field()}.`;
                break;
            }
            case '2B':
                if (b[2]) score(b[2]);
                if (b[1]) score(b[1]);
                b[2] = null; b[1] = null;
                if (b[0]) {
                    if (roll('scoreFromFirst', b[0])) score(b[0]); else b[2] = b[0];
                    b[0] = null;
                }
                b[1] = runnerEntry;
                text = `${name} doubled to ${field()}.`;
                break;
            case '3B':
                for (let i = 2; i >= 0; i--) if (b[i]) score(b[i]);
                st.bases = [null, null, runnerEntry];
                text = `${name} tripled to ${field()}.`;
                break;
            case 'HR':
                for (let i = 2; i >= 0; i--) if (b[i]) score(b[i]);
                score(runnerEntry);
                st.bases = [null, null, null];
                bbox.hr += 1; pbox.hr += 1;
                text = `${name} homered to ${field()}!`;
                break;
            case 'E':
                bbox.ab += 1;
                st.errors[this.fieldingKey] += 1;
                if (b[2]) score(b[2], false);
                b[2] = b[1]; b[1] = b[0];
                b[0] = { ...runnerEntry, unearned: true };
                text = `${name} reached on an error.`;
                break;
            case 'GO': {
                bbox.ab += 1;
                if (outsBefore < 2 && b[0] && roll('doublePlayChance', runnerEntry)) {
                    play = 'DP';
                    out(); out();
                    b[0] = null;
                    if (b[2]) { score(b[2], false); b[2] = null; }
                    if (b[1]) { b[2] = b[1]; b[1] = null; }
                    text = `${name} grounded into a double play.`;
                    break;
                }
                out();
                if (st.outs < 3) {
                    // Forced runners move up; the others may.
                    if (b[2] && (b[1] && b[0] || roll('groundScoreChance', b[2]))) { score(b[2]); b[2] = null; }
                    if (b[1] && !b[2] && (b[0] || roll('groundAdvance', b[1]))) { b[2] = b[1]; b[1] = null; }
                    if (b[0] && !b[1]) { b[1] = b[0]; b[0] = null; }
                }
                text = `${name} grounded out.`;
                break;
            }
            case 'FO':
                out();
                if (st.outs < 3 && b[2] && roll('sacFlyChance', b[2])) {
                    play = 'SF';
                    bbox.sf += 1;
                    score(b[2]);
                    b[2] = null;
                    text = `${name} hit a sacrifice fly to ${field()}.`;
                } else {
                    bbox.ab += 1;
                    text = `${name} flied out to ${field()}.`;
                }
                if (st.outs < 3 && b[1] && !b[2] && roll('tagFromSecond', b[1])) { b[2] = b[1]; b[1] = null; }
                break;
            case 'PO':
                bbox.ab += 1;
                out();
                text = `${name} popped out.`;
                break;
        }

        if (['1B', '2B', '3B', 'HR'].includes(play)) {
            bbox.ab += 1;
            bbox.h += 1;
            if (play === '2B') bbox.d += 1;
            if (play === '3B') bbox.t += 1;
            pbox.h += 1;
            st.hits[bk] += 1;
        }
        bbox.rbi += rbi;

        if (scored.length) {
            const names = scored.filter((id) => !(play === 'HR' && id === batter.id)).map((id) => shortName(this.player(id)));
            if (names.length) text += ` ${names.join(', ')} ${names.length > 1 ? 'score' : 'scores'}.`;
        }
        if (st.outs >= 3) text += ' Three outs.';
        else if (st.outs > outsBefore) text += ` ${st.outs} out${st.outs > 1 ? 's' : ''}.`;

        result.play = play;
        result.text = text;
        result.runs = scored.length;
        result.paEnded = true;
        this.log(text, scored.length ? 'run' : 'pa');

        // Next batter.
        const bs = this.side(bk);
        bs.batIdx = (bs.batIdx + 1) % 9;
        st.balls = 0;
        st.strikes = 0;
        // How things stood when the at-bat ended (the scoreboard while it is
        // played back), before any change of half-inning.
        result.after = this.snapshot();

        // Walk-off, or the home team reaching the mercy margin?
        const mercy = st.settings.mercy;
        if (st.half === 'bottom' && st.inning >= st.settings.innings && st.score.home > st.score.away) {
            this.finish();
        } else if (st.half === 'bottom' && mercy && st.inning >= mercy.after && st.score.home - st.score.away >= mercy.runs) {
            this.finish('mercy');
        } else if (st.outs >= 3) {
            result.halfEnded = true;
            this.endHalf();
        }
        result.gameOver = st.over;
        if (!st.over) this.startPA();
    }

    endHalf() {
        const st = this.state;
        const { innings } = st.settings;
        if (st.half === 'top' && st.inning >= innings && st.score.home > st.score.away) return this.finish();
        if (st.half === 'bottom' && st.inning >= innings && st.score.home !== st.score.away) return this.finish();
        const mercy = st.settings.mercy;
        if (mercy && st.inning >= mercy.after) {
            const lead = st.score.home - st.score.away;
            if (st.half === 'top' && lead >= mercy.runs) return this.finish('mercy');
            if (st.half === 'bottom' && Math.abs(lead) >= mercy.runs) return this.finish('mercy');
        }
        if (st.half === 'top') {
            st.half = 'bottom';
        } else {
            st.half = 'top';
            st.inning += 1;
        }
        st.outs = 0;
        st.bases = [null, null, null];
        st.line[this.battingKey].push(0);
        this.log(`${st.half === 'top' ? 'Top' : 'Bottom'} of the ${ordinal(st.inning)}.`, 'info');
    }

    finish(how = null) {
        const st = this.state;
        st.over = true;
        st.endedBy = how;
        if (how === 'mercy') this.log('Game called: mercy rule.', 'info');
        st.winner = st.score.home > st.score.away ? 'home' : 'away';
        const w = this.team(st.winner);
        this.log(`Final: ${w.city} ${w.name} win ${Math.max(st.score.home, st.score.away)}–${Math.min(st.score.home, st.score.away)}.`, 'info');
    }

    // Before each batter: the computer may change pitchers.
    startPA() {
        const st = this.state;
        if (this.computerManages(this.fieldingKey)) {
            const v = this.mustChangePitcher() ? 1 : this.F.eval('aiHook', this.situationScope());
            if (this.rng.chance(v)) {
                const id = aiPickReliever(this, this.fieldingKey);
                if (id) this.changePitcher(this.fieldingKey, id);
            }
        }
        st.pa = { batterId: this.batter().id, pitcherId: this.pitcher().id, pitches: [] };
        st.rngState = this.rng.seed;
    }

    // ---- managing ----
    changePitcher(key, newId) {
        const s = this.side(key);
        if (s.pitchersUsed.includes(newId)) throw new Error('That pitcher has already been used');
        const oldName = shortName(this.player(s.pitcherId));
        s.pitcherId = newId;
        s.pitchersUsed.push(newId);
        s.status[newId] = { fatigue: 0, pitches: 0 };
        if (this.state.pa && key === this.fieldingKey) this.state.pa.pitcherId = newId;
        this.log(`Pitching change: ${shortName(this.player(newId))} replaces ${oldName}.`, 'info');
    }

    // Whether a side's hitters have batted yet (until then the whole lineup
    // card may change).
    hasBatted(key) {
        const team = this.team(key);
        return team.batters.some((id) => (this.state.box.bat[id]?.pa ?? 0) > 0);
    }

    // A new lineup card for a side that hasn't batted: nine of its batters,
    // one at each position.
    setLineup(key, lineup) {
        if (this.hasBatted(key)) throw new Error('This team has already batted; use substitutions.');
        const team = this.team(key);
        const s = this.side(key);
        if (!Array.isArray(lineup) || lineup.length !== 9) throw new Error('A lineup needs nine batters.');
        const ids = lineup.map((l) => Number(l.id));
        if (new Set(ids).size !== 9 || ids.some((id) => !team.batters.includes(id) || s.removed.includes(id))) {
            throw new Error('Those players can’t all be in this lineup.');
        }
        const positions = lineup.map((l) => l.pos).sort().join();
        if (positions !== [...FIELD_POSITIONS].sort().join()) throw new Error('Each position needs exactly one player.');
        s.lineup = lineup.map((l) => ({ id: Number(l.id), pos: l.pos }));
        if (key === this.battingKey && this.state.pa) this.state.pa.batterId = this.batter().id;
        this.log(`${team.abbr} lineup set.`, 'info');
    }

    // Replace a lineup spot (default: the current batter) with a bench player.
    pinchHit(key, benchId, slot = this.side(key).batIdx) {
        const s = this.side(key);
        if (!this.bench(key).includes(benchId)) throw new Error('That player is not available');
        const outId = s.lineup[slot].id;
        s.removed.push(outId);
        s.lineup[slot] = { id: benchId, pos: s.lineup[slot].pos };
        if (key === this.battingKey && slot === s.batIdx) this.state.pa.batterId = benchId;
        const now = key === this.battingKey && slot === s.batIdx;
        this.log(now ? `Pinch hitter: ${shortName(this.player(benchId))} bats for ${shortName(this.player(outId))}.`
            : `Substitution: ${shortName(this.player(benchId))} replaces ${shortName(this.player(outId))}, batting ${slot + 1}${['st', 'nd', 'rd'][slot] ?? 'th'}.`, 'info');
    }

    // ---- computer play ----
    aiPitch() {
        const choice = aiChoosePitch(this, this.rng);
        return this.throwPitch(choice);
    }

    simPlateAppearance() {
        const results = [];
        let r;
        do {
            r = this.aiPitch();
            results.push(r);
        } while (!r.paEnded);
        return results;
    }

    simHalfInning() {
        const results = [];
        const { inning, half } = this.state;
        while (!this.state.over && this.state.inning === inning && this.state.half === half) {
            results.push(...this.simPlateAppearance());
        }
        return results;
    }

    simToEnd() {
        while (!this.state.over) this.simPlateAppearance();
    }

    // ---- bookkeeping ----
    // The scoreboard as it stands: count, outs, runners, score.
    snapshot() {
        const st = this.state;
        return {
            inning: st.inning, half: st.half, balls: st.balls, strikes: st.strikes, outs: st.outs,
            bases: st.bases.map(Boolean), score: { ...st.score }, hits: { ...st.hits }, errors: { ...st.errors },
            line: { away: st.line.away.slice(), home: st.line.home.slice() }, over: st.over,
        };
    }
    batBox(id) {
        return (this.state.box.bat[id] ??= { pa: 0, ab: 0, r: 0, h: 0, d: 0, t: 0, hr: 0, rbi: 0, bb: 0, k: 0, hbp: 0, sf: 0 });
    }
    pitchBox(id) {
        return (this.state.box.pitch[id] ??= { bf: 0, outs: 0, h: 0, r: 0, er: 0, bb: 0, k: 0, hr: 0, hbp: 0, pitches: 0, strikes: 0 });
    }
    log(text, kind) {
        const st = this.state;
        st.log.push({ inning: st.inning, half: st.half, text, kind });
    }
}

export function ordinal(n) {
    const s = ['th', 'st', 'nd', 'rd'];
    const v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export const kindOf = (typeName) => PITCH_TYPES[typeName].kind;
