// Headless simulation: computer vs computer games, to check the engine and
// see what the formulas produce. Usage:
//   node test/sim.js [games=200] [seed=1] [formulas.json]
// formulas.json, if given, maps formula ids to replacement text.

import { readFileSync } from 'node:fs';
import { generateLeague } from '../src/engine/league.js';
import { createFormulas } from '../src/engine/formulas.js';
import { createSim, summarize } from '../src/engine/simStats.js';

const games = Number(process.argv[2] ?? 200);
const seed = Number(process.argv[3] ?? 1);
const overrides = process.argv[4] ? JSON.parse(readFileSync(process.argv[4], 'utf8')) : {};

const league = generateLeague(seed);
const F = createFormulas(overrides);
for (const [id, err] of Object.entries(F.errors)) console.warn(`formula ${id}: ${err}`);

const totals = createSim(league, F, { games, seed }).runAll();
console.log('Games'.padEnd(28), games);
for (const row of summarize(totals)) console.log(row.label.padEnd(28), row.text.padEnd(10), `MLB ~${row.mlbText}`);
for (const p of totals.problems) console.error(p);
console.log('Consistency problems'.padEnd(28), totals.problems.length, '(should be 0)');
if (totals.problems.length) process.exitCode = 1;
