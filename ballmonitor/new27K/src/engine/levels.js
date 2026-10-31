// Levels of play. Ratings are always relative to the level (about 50 is
// an average player there), so the formulas work unchanged; what differs is
// raw speed (levelVelo), fielding (via `level` in the error formula), game
// length, the mercy rule, pitch limits and rest, roster sizes and arsenals.
//
// ratingShift is how many rating points an average player at this level is
// below an average pro. A career player moving up a level loses the
// difference (a 70 in high school is about a 61 in college).

import { TEAMS } from './data.js';

export const LEVELS = {
    youth: {
        id: 'youth', n: 1, name: 'Youth', icon: '🧢',
        desc: '12-and-under: six innings, a 10-run mercy rule after four, strict pitch counts and rest days, shaky defense, mostly fastballs and changeups.',
        innings: 6, levelVelo: -26, mercy: { runs: 10, after: 4 }, ratingShift: 32, gap: 3,
        teamCount: 6, lengths: [10, 15, 20], defaultLength: 15,
        bench: ['IF', 'OF', 'UT'], starters: 3, relievers: 4,
        stamina: { SP: [60, 8], RP: [32, 6] }, spread: 13,
        arsenal: { primary: { 'Four-Seam': 1 }, secondary: { Changeup: 6, 'Two-Seam': 2, Curveball: 1 }, sp: [1, 1], rp: [0, 1], secondFastball: 0 },
    },
    hs: {
        id: 'hs', n: 2, name: 'High School', icon: '🏫',
        desc: 'Seven-inning games, a 10-run mercy rule after five, a 105-pitch limit with rest days. Breaking balls start to appear.',
        innings: 7, levelVelo: -12, mercy: { runs: 10, after: 5 }, ratingShift: 20, gap: 2,
        teamCount: 8, lengths: [14, 21, 28], defaultLength: 21,
        bench: ['C', 'IF', 'OF'], starters: 4, relievers: 5,
        stamina: { SP: [80, 9], RP: [35, 6] }, spread: 11,
        arsenal: {
            primary: { 'Four-Seam': 6, 'Two-Seam': 2 },
            secondary: { Curveball: 5, Changeup: 5, Slider: 3, Splitter: 0.5, Knuckleball: 0.1, Eephus: 0.1 },
            sp: [1, 2], rp: [1, 1], secondFastball: 0.15,
        },
    },
    college: {
        id: 'college', n: 3, name: 'College', icon: '🎓',
        desc: 'Nine innings with a 10-run rule after seven. Deep pitching staffs, real arsenals, and starters on rest.',
        innings: 9, levelVelo: -5, mercy: { runs: 10, after: 7 }, ratingShift: 9, gap: 1,
        teamCount: 10, lengths: [27, 45, 56], defaultLength: 45,
        bench: ['C', 'IF', 'IF', 'OF'], starters: 4, relievers: 7,
        stamina: { SP: [90, 10], RP: [34, 6] }, spread: 10,
        arsenal: null,  // the full pro mix
    },
    pro: {
        id: 'pro', n: 4, name: 'Pro', icon: '🏟️',
        desc: 'The big leagues: nine innings, no mercy, five-man rotations, the full pitch menu.',
        innings: 9, levelVelo: 0, mercy: null, ratingShift: 0, gap: 1,
        teamCount: 12, lengths: [30, 60, 162], defaultLength: 60,
        bench: ['C', 'IF', 'IF', 'OF'], starters: 5, relievers: 7,
        stamina: { SP: [95, 10], RP: [32, 6] }, spread: 9,
        arsenal: null,
    },
};

export const LEVEL_ORDER = ['youth', 'hs', 'college', 'pro'];

// Settings a game at this level gets (merged into Game.create options).
export function levelGameOptions(levelId) {
    const L = LEVELS[levelId];
    return { innings: L.innings, level: L.n, levelVelo: L.levelVelo, mercy: L.mercy };
}

export const TEAM_NAMES = {
    youth: [
        ['Main St. Pizza', 'Pirates'], ['Hendrix Hardware', 'Hornets'], ['Lakeside Dental', 'Dragons'],
        ['Rotary Club', 'Rockets'], ['Fire Dept.', 'Flames'], ['Corner Bakery', 'Cubs'],
        ['Valley Bank', 'Bandits'], ['Sunny Pools', 'Sharks'],
    ],
    hs: [
        ['Lincoln High', 'Lions'], ['Westview', 'Wolverines'], ['Central Catholic', 'Crusaders'], ['North Ridge', 'Rams'],
        ['Eastlake', 'Eagles'], ['Riverside', 'Rebels'], ['Oak Grove', 'Owls'], ['Summit', 'Spartans'],
        ['Bayside', 'Buccaneers'], ['Pinecrest', 'Panthers'],
    ],
    college: [
        ['Coastal State', 'Mariners'], ['Northern Tech', 'Engineers'], ['Mountain U', 'Peaks'], ['Delta A&M', 'Gators'],
        ['Prairie State', 'Bison'], ['St. Augustine', 'Friars'], ['Capital City', 'Senators'], ['Redwood', 'Lumberjacks'],
        ['Gulf Coast', 'Pelicans'], ['High Desert', 'Scorpions'], ['Lakeland', 'Lakers'], ['Ironbridge', 'Forge'],
    ],
    pro: TEAMS.map((t) => [t.city, t.name]),
};

const PALETTE = ['#1f6feb', '#c2410c', '#2f855a', '#7c3aed', '#be123c', '#0e7490', '#b45309', '#64748b', '#d97706', '#0f766e', '#7f1d1d', '#4338ca'];

export function teamIdentity(levelId, i) {
    if (levelId === 'pro') return { ...TEAMS[i] };
    const [city, name] = TEAM_NAMES[levelId][i];
    const words = city.replace(/[^A-Za-z ]/g, '').split(/\s+/).filter(Boolean);
    const abbr = (words.length > 1 ? words.map((w) => w[0]).join('') + name[0] : city.slice(0, 3)).toUpperCase().slice(0, 3);
    return { city, name, abbr, color: PALETTE[i % PALETTE.length] };
}
