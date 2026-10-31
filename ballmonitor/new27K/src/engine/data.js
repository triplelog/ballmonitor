// Static tables: the strike zone, pitch types, positions, names and teams.
//
// Coordinates are inches, seen from behind the pitcher: x is positive toward
// the first-base side (screen right), y is positive up, and (0, 0) is the
// middle of the strike zone.

export const ZONE = {
    halfW: 8.5,      // half of the 17-inch plate
    halfH: 11,       // half of a 22-inch knees-to-letters zone
    ballR: 1.45,     // a pitch is a strike if any part of the ball touches the zone
};

// Heat maps are a 5×5 grid of cells, each a third of the zone: the middle
// 3×3 is the zone itself and the outer ring is just off the edges.
export const HEAT = { cols: 5, rows: 5, cellW: (2 * ZONE.halfW) / 3, cellH: (2 * ZONE.halfH) / 3 };

// Break is for a right-handed pitcher, in inches, relative to a straight
// fastball: run is toward the pitcher's arm side (−x for a righty, the
// third-base side where a right-handed batter stands; +x for a lefty) and
// drop is downward. So a righty's slider, sweeper, cutter and curve break
// right (away from a right-handed batter) and his changeup, sinker and
// two-seamer run left (in on him). Velo is a typical mph. Wobble is random
// late movement (inches), for knuckleballs.
export const PITCH_TYPES = {
    'Four-Seam':   { abbr: 'FF', kind: 'fast',  velo: 94, run: 3,  drop: 0,  wobble: 0, color: '#e5484d' },
    'Two-Seam':    { abbr: 'FT', kind: 'fast',  velo: 92, run: 7,  drop: 3,  wobble: 0, color: '#f06a3a' },
    'Sinker':      { abbr: 'SI', kind: 'fast',  velo: 92, run: 6,  drop: 6,  wobble: 0, color: '#e07b39' },
    'Cutter':      { abbr: 'FC', kind: 'fast',  velo: 89, run: -4, drop: 2,  wobble: 0, color: '#c2410c' },
    'Splitter':    { abbr: 'FS', kind: 'off',   velo: 86, run: 4,  drop: 8,  wobble: 0, color: '#2f9e6f' },
    'Changeup':    { abbr: 'CH', kind: 'off',   velo: 84, run: 7,  drop: 6,  wobble: 0, color: '#30a46c' },
    'Palmball':    { abbr: 'PB', kind: 'off',   velo: 76, run: 2,  drop: 11, wobble: 0, color: '#46a758' },
    'Screwball':   { abbr: 'SC', kind: 'off',   velo: 80, run: 9,  drop: 9,  wobble: 0, color: '#3e9b8a' },
    'Slider':      { abbr: 'SL', kind: 'break', velo: 85, run: -8, drop: 5,  wobble: 0, color: '#8e4ec6' },
    'Sweeper':     { abbr: 'SW', kind: 'break', velo: 82, run: -14, drop: 4, wobble: 0, color: '#a855f7' },
    'Curveball':   { abbr: 'CU', kind: 'break', velo: 78, run: -5, drop: 14, wobble: 0, color: '#3e63dd' },
    'Gyroball':    { abbr: 'GY', kind: 'break', velo: 85, run: -2, drop: 7,  wobble: 0, color: '#0090ff' },
    'Knuckleball': { abbr: 'KN', kind: 'off',   velo: 72, run: 0,  drop: 4,  wobble: 4, color: '#8d8d8d' },
    'Eephus':      { abbr: 'EP', kind: 'off',   velo: 60, run: 0,  drop: 22, wobble: 0, color: '#d6409f' },
};

// What starters and relievers usually throw, with how often each shows up.
export const ARSENAL_WEIGHTS = {
    primary: { 'Four-Seam': 6, 'Two-Seam': 2, 'Sinker': 3, 'Cutter': 1.5 },
    secondary: {
        'Slider': 6, 'Curveball': 4, 'Changeup': 6, 'Cutter': 2, 'Splitter': 2, 'Sweeper': 2.5,
        'Two-Seam': 1, 'Sinker': 1, 'Palmball': 0.4, 'Screwball': 0.4, 'Gyroball': 0.4,
        'Knuckleball': 0.15, 'Eephus': 0.15,
    },
};

export const FIELD_POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];

export const FIRST_NAMES = [
    'Aaron', 'Abel', 'Adrian', 'Alex', 'Andre', 'Angel', 'Ben', 'Blake', 'Bo', 'Brady', 'Caleb', 'Carlos',
    'Casey', 'Chase', 'Cole', 'Cody', 'Dante', 'Darius', 'Davi', 'Dean', 'Diego', 'Dylan', 'Eli', 'Emilio',
    'Eric', 'Ezra', 'Felix', 'Finn', 'Gabe', 'Grant', 'Hank', 'Hector', 'Hiro', 'Ian', 'Isaac', 'Ivan',
    'Jack', 'Jalen', 'Jamal', 'Javier', 'Jesse', 'Joel', 'Jonah', 'Jose', 'Julian', 'Kai', 'Kenji', 'Kyle',
    'Lance', 'Leo', 'Luis', 'Luke', 'Malik', 'Marco', 'Mason', 'Mateo', 'Miguel', 'Miles', 'Nate', 'Nico',
    'Noah', 'Omar', 'Oscar', 'Owen', 'Pablo', 'Quinn', 'Rafael', 'Ray', 'Reid', 'Rico', 'Rowan', 'Ryu',
    'Sam', 'Santi', 'Shane', 'Shohei', 'Silas', 'Tate', 'Theo', 'Tomas', 'Trey', 'Tyler', 'Victor', 'Wade',
    'Wes', 'Will', 'Xavier', 'Yuki', 'Zack', 'Zeke',
];

export const LAST_NAMES = [
    'Abreu', 'Adler', 'Alvarez', 'Archer', 'Baker', 'Banks', 'Barrett', 'Bell', 'Boone', 'Brennan', 'Brooks',
    'Burke', 'Cabrera', 'Calloway', 'Castillo', 'Chen', 'Clarke', 'Cole', 'Cortez', 'Crane', 'Cruz', 'Dalton',
    'Diaz', 'Dorsey', 'Duarte', 'Ellis', 'Espinoza', 'Fields', 'Fisher', 'Flores', 'Ford', 'Fox', 'Garcia',
    'Grady', 'Graves', 'Hale', 'Hart', 'Hayes', 'Herrera', 'Hill', 'Holt', 'Ito', 'Jansen', 'Keller', 'Kim',
    'Knox', 'Lane', 'Larkin', 'Lowe', 'Maddox', 'Marsh', 'Medina', 'Mercer', 'Morales', 'Nash', 'Navarro',
    'Nolan', 'Ochoa', 'Ortega', 'Park', 'Payne', 'Pena', 'Price', 'Quintana', 'Ramos', 'Reyes', 'Rhodes',
    'Rivera', 'Rojas', 'Sato', 'Shaw', 'Silva', 'Soto', 'Stone', 'Suzuki', 'Tanaka', 'Torres', 'Tucker',
    'Valdez', 'Vance', 'Vargas', 'Walsh', 'Ward', 'Webb', 'West', 'Wolfe', 'Yates', 'Young', 'Zamora',
];

export const TEAMS = [
    { city: 'Harbor City', name: 'Gulls', abbr: 'HBR', color: '#1f6feb' },
    { city: 'Red Mesa', name: 'Roadrunners', abbr: 'RMS', color: '#c2410c' },
    { city: 'Pine Hollow', name: 'Lumberjacks', abbr: 'PHL', color: '#2f855a' },
    { city: 'Port Royal', name: 'Corsairs', abbr: 'PRC', color: '#111827' },
    { city: 'Silver Falls', name: 'Miners', abbr: 'SFM', color: '#64748b' },
    { city: 'Bayview', name: 'Herons', abbr: 'BAY', color: '#0e7490' },
    { city: 'Granite Peak', name: 'Goats', abbr: 'GRP', color: '#7c3aed' },
    { city: 'Copper Basin', name: 'Comets', abbr: 'CPB', color: '#b45309' },
    { city: 'Lakeshore', name: 'Loons', abbr: 'LAK', color: '#0f766e' },
    { city: 'Thunder Ridge', name: 'Bison', abbr: 'THR', color: '#7f1d1d' },
    { city: 'Sunset Valley', name: 'Suns', abbr: 'SUN', color: '#d97706' },
    { city: 'Ironwood', name: 'Foxes', abbr: 'IRW', color: '#be123c' },
];

// Keyboard keys for pitches, in order of preference. A pitcher's arsenal
// gets the first free key for each pitch (digits 1–9 work too).
export const PITCH_KEYS = {
    'Four-Seam': 'FQ', 'Two-Seam': 'TW', 'Sinker': 'SK', 'Cutter': 'XU', 'Splitter': 'PI',
    'Changeup': 'CH', 'Palmball': 'MA', 'Screwball': 'WR', 'Slider': 'SL', 'Sweeper': 'EW',
    'Curveball': 'CVB', 'Gyroball': 'GY', 'Knuckleball': 'KN', 'Eephus': 'EPO',
};

export function pitchKeys(pitches) {
    const used = new Set();
    return pitches.map((p) => {
        const prefs = (PITCH_KEYS[p.type] ?? '') + 'ABDGJMNOQRVYZ';
        const key = [...prefs].find((k) => !used.has(k));
        used.add(key);
        return key;
    });
}
