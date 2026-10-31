// Build a static copy of the game in dist/, ready to upload as-is to any
// static host (GitHub Pages, Netlify, Cloudflare Pages, a plain web server).
//   node tools/build-static.js [out=dist]        (npm run build)
//
// It copies the page, styles and the game's sources, plus only the MathZetta
// files the game loads: starting from the entry points in index.html's
// import map, it follows their imports and copies just those .js files into
// lib/mathzetta/, then points the import map there. Multiplayer needs the
// Node server and is not open yet; everything else runs in the browser.

import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(root, process.argv[2] ?? 'dist');
const pkgDir = join(root, 'node_modules', 'mathzetta');
const libDir = join(out, 'lib', 'mathzetta');

if (!existsSync(join(pkgDir, 'src', 'index.js'))) {
    console.error('MathZetta not found in node_modules/mathzetta: run npm install first.');
    process.exit(1);
}

// The import map: { "mathzetta": "./node_modules/mathzetta/src/index.js", … }
const html = readFileSync(join(root, 'index.html'), 'utf8');
const mapMatch = html.match(/<script type="importmap">([\s\S]*?)<\/script>/);
if (!mapMatch) throw new Error('index.html has no import map');
const imports = JSON.parse(mapMatch[1]).imports;

// Every module reachable from the entries, by its path inside the package.
const IMPORT_RE = /(?:\bimport|\bexport)\s*(?:[\w*{}\s,]*?\bfrom\s*)?['"](\.{1,2}\/[^'"]+)['"]/g;
const files = new Set();
function visit(file) {
    if (files.has(file)) return;
    if (!existsSync(file) || !statSync(file).isFile()) return;   // e.g. a path in a comment
    files.add(file);
    const text = readFileSync(file, 'utf8');
    for (const m of text.matchAll(IMPORT_RE)) visit(resolve(dirname(file), m[1]));
}
const newImports = {};
for (const [name, address] of Object.entries(imports)) {
    const prefix = './node_modules/mathzetta/';
    if (!address.startsWith(prefix)) { newImports[name] = address; continue; }
    const entry = join(pkgDir, address.slice(prefix.length));
    visit(entry);
    newImports[name] = './lib/mathzetta/' + relative(pkgDir, entry).split('\\').join('/');
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(join(root, 'css'), join(out, 'css'), { recursive: true });
cpSync(join(root, 'src'), join(out, 'src'), { recursive: true });
for (const file of files) {
    const dest = join(libDir, relative(pkgDir, file));
    mkdirSync(dirname(dest), { recursive: true });
    cpSync(file, dest, { dereference: true });
}
if (existsSync(join(pkgDir, 'LICENSE'))) cpSync(join(pkgDir, 'LICENSE'), join(libDir, 'LICENSE'), { dereference: true });

const map = JSON.stringify({ imports: newImports }, null, 4).replace(/\n/g, '\n    ');
writeFileSync(join(out, 'index.html'), html.replace(mapMatch[1], `\n    ${map}\n    `));

const kb = Math.round([...files].reduce((sum, f) => sum + statSync(f).size, 0) / 1024);
console.log(`Built ${relative(root, out) || out}/: the game plus ${files.size} MathZetta files (${kb} KB).`);
console.log('Upload the folder as-is; serve it over http(s), e.g.  python3 -m http.server -d dist');
