// Achievements: feats unlocked during any game you pitch (quick games,
// challenges, and later the season). Each check sees the tracker after the
// pitch, the pitch result and the game.

import { edgeDistance } from './pitch.js';

const isK = (r) => r.play === 'K' || r.play === 'KL';
// An inning you pitched from its first out to its last.
const fullInning = (t, r) => r.halfEnded && t.inning.startOuts === 0 && t.inning.outs === 3;
const fullGame = (t, r, g) => {
    if (!r.gameOver || !t.game.fromStart || g.state.settings.innings < 9) return false;
    const key = g.userKey();
    return key && g.side(key).pitchersUsed.length === 1 && g.team(key).pitchers.includes(r.pitcherId);
};

export const ACHIEVEMENTS = [
    // At-bat
    { id: 'firstK', tier: 'At-bat', icon: '⚾', name: 'Punch-out', desc: 'Record a strikeout.',
      check: (t, r) => isK(r) },
    { id: 'framed', tier: 'At-bat', icon: '🧤', name: 'Thank the Catcher', desc: 'Get a called strike three on a pitch outside the zone.',
      check: (t, r) => r.play === 'KL' && r.loc && edgeDistance(r.loc.x, r.loc.y) < 0 },
    { id: 'paint', tier: 'At-bat', icon: '🎨', name: 'Painted the Corner', desc: 'Strike a batter out looking with a pitch within an inch of the edge.',
      check: (t, r) => r.play === 'KL' && r.loc && edgeDistance(r.loc.x, r.loc.y) >= 0 && edgeDistance(r.loc.x, r.loc.y) <= 1 },
    { id: 'heat', tier: 'At-bat', icon: '🔥', name: 'Triple Digits', desc: 'Strike out a batter with a pitch of 100 mph or more (or its equal at lower levels).',
      check: (t, r, g) => isK(r) && r.pitch.velocity - (g.state.settings.levelVelo ?? 0) >= 100 },
    { id: 'eephus', tier: 'At-bat', icon: '🐌', name: 'Slow Your Roll', desc: 'Strike out a batter with a pitch of 65 mph or less.',
      check: (t, r, g) => isK(r) && r.pitch.velocity - (g.state.settings.levelVelo ?? 0) <= 65 },
    { id: 'repertoire', tier: 'At-bat', icon: '🃏', name: 'Full Repertoire', desc: 'Strike out a batter after throwing him three or more different pitches.',
      check: (t, r) => isK(r) && t.pa.types.length >= 3 },
    { id: 'comeback', tier: 'At-bat', icon: '↩️', name: 'Back from 3-0', desc: 'Fall behind 3-0, then strike the batter out.',
      check: (t, r) => isK(r) && t.pa.wasThreeOh },
    { id: 'buzzer', tier: 'At-bat', icon: '⏱️', name: 'Buzzer Beater', desc: 'Throw a strike with less than a second left on the pitch clock.',
      check: (t, r) => (r.call === 'called' || r.call === 'swinging') && r.clockLeft !== null && r.clockLeft < 1 },

    // Inning
    { id: 'onetwothree', tier: 'Inning', icon: '🧹', name: '1-2-3 Inning', desc: 'Retire the side in order.',
      check: (t, r) => fullInning(t, r) && t.inning.bf === 3 },
    { id: 'side', tier: 'Inning', icon: '🔱', name: 'Struck Out the Side', desc: 'Get all three outs of an inning by strikeout.',
      check: (t, r) => fullInning(t, r) && t.inning.outsK === 3 },
    { id: 'immaculate', tier: 'Inning', icon: '✨', name: 'Immaculate Inning', desc: 'Three strikeouts on nine pitches.',
      check: (t, r) => fullInning(t, r) && t.inning.outsK === 3 && t.inning.pitches === 9 },
    { id: 'econ', tier: 'Inning', icon: '💨', name: 'Three-Pitch Inning', desc: 'Get three outs on three pitches.',
      check: (t, r) => fullInning(t, r) && t.inning.pitches === 3 },
    { id: 'houdini', tier: 'Inning', icon: '🎩', name: 'Houdini', desc: 'Load the bases with nobody out, then escape without a run.',
      check: (t, r) => r.halfEnded && t.inning.loadedNoOuts && t.inning.runs === 0 },
    { id: 'heart', tier: 'Inning', icon: '💔', name: 'Heart of the Order', desc: 'Strike out the 3, 4 and 5 hitters in a row.',
      check: (t) => t.heart >= 3 },

    // Game
    { id: 'k10', tier: 'Game', icon: '🔟', name: 'Double Digits', desc: 'Strike out 10 in a game.',
      check: (t) => t.game.k >= 10 },
    { id: 'k15', tier: 'Game', icon: '🌪️', name: 'Fifteen Up', desc: 'Strike out 15 in a game.',
      check: (t) => t.game.k >= 15 },
    { id: 'k20', tier: 'Game', icon: '🏆', name: 'Twenty', desc: 'Strike out 20 in a game, tying the major-league record.',
      check: (t) => t.game.k >= 20 },
    { id: 'kstreak', tier: 'Game', icon: '⛓️', name: 'Six Straight', desc: 'Strike out six batters in a row.',
      check: (t) => t.kStreak >= 6 },
    { id: 'sombrero', tier: 'Game', icon: '👒', name: 'Golden Sombrero', desc: 'Strike out the same batter four times in one game.',
      check: (t, r) => isK(r) && t.batterKs[r.batterId] >= 4 },
    { id: 'cg', tier: 'Game', icon: '🏁', name: 'Complete Game', desc: 'Pitch a whole nine-inning game without help from the bullpen.',
      check: (t, r, g) => fullGame(t, r, g) },
    { id: 'nobb', tier: 'Game', icon: '🎯', name: 'Pinpoint', desc: 'Complete game without a walk or hit batter.',
      check: (t, r, g) => fullGame(t, r, g) && t.game.bb + t.game.hbp === 0 },
    { id: 'shutout', tier: 'Game', icon: '🚫', name: 'Shutout', desc: 'Complete game without allowing a run.',
      check: (t, r, g) => fullGame(t, r, g) && t.game.runs === 0 },
    { id: 'maddux', tier: 'Game', icon: '🧠', name: 'Maddux', desc: 'Complete-game shutout on fewer than 100 pitches.',
      check: (t, r, g) => fullGame(t, r, g) && t.game.runs === 0 && t.game.pitches < 100 },
    { id: 'nohitter', tier: 'Game', icon: '🫥', name: 'No-Hitter', desc: 'Complete game without allowing a hit.',
      check: (t, r, g) => fullGame(t, r, g) && t.game.hits === 0 },
    { id: 'perfect', tier: 'Game', icon: '💎', name: 'Perfect Game', desc: '27 up, 27 down: nobody reaches base.',
      check: (t, r, g) => fullGame(t, r, g) && t.game.baserunners === 0 && t.game.outs >= 27 },
    { id: 'k27', tier: 'Game', icon: '👑', name: '27K', desc: 'Every out of a nine-inning complete game is a strikeout.',
      check: (t, r, g) => fullGame(t, r, g) && t.game.outs >= 27 && t.game.nonKOuts === 0 },
];

// Strikeout feats that are automatic when only strikeouts make outs.
const NOT_IN_K_ONLY = ['side', 'immaculate', 'k10', 'k15', 'k20', 'kstreak', 'sombrero', 'heart', 'k27'];

export const ACHIEVEMENT_BY_ID = Object.fromEntries(ACHIEVEMENTS.map((a) => [a.id, a]));

// Ids of achievements met by this pitch. `already` holds ids earned
// earlier in the same game, so each counts once per game.
export function checkAchievements(t, r, game, already = []) {
    const got = [];
    for (const a of ACHIEVEMENTS) {
        if (already.includes(a.id)) continue;
        if (game.state.settings.kOnly && NOT_IN_K_ONLY.includes(a.id)) continue;
        try {
            if (a.check(t, r, game)) got.push(a.id);
        } catch {
            // A check that can't run here (e.g. no at-bat yet) just doesn't fire.
        }
    }
    return got;
}
