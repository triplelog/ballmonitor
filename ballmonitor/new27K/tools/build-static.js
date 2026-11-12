// Build a static copy of the game in dist/, ready to upload as-is to any
// static host (GitHub Pages, Netlify, Cloudflare Pages, a plain web server).
//   npm install && node tools/build-static.js [out=dist]        (npm run build)
//
// It copies the page, styles and the game's sources to dist/, plus the published
// browser builds of MathZetta and InlineMath (from node_modules, exact versions pinned
// in package.json) into dist/lib/, and points the import map there. The game loads
// nothing from a CDN, so it works offline once loaded and when a CDN is blocked.

import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(root, process.argv[2] ?? 'dist');
const nm = join(root, 'node_modules');

// [package dir in node_modules, files/dirs to copy, folder under dist/lib/]
const LIBS = [
    ['mathzetta', ['build/esm', 'LICENSE', 'package.json'], 'mathzetta'],
    ['@mathzetta/inlinemath', ['dist/inlinemath.external.js', 'dist/chunks', 'inlinemath.css', 'LICENSE', 'package.json'], 'inlinemath'],
];

for (const [pkg] of LIBS) {
    if (!existsSync(join(nm, pkg, 'package.json'))) {
        console.error(`node_modules/${pkg} is missing: run npm install first.`);
        process.exit(1);
    }
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(join(root, 'css'), join(out, 'css'), { recursive: true });
cpSync(join(root, 'src'), join(out, 'src'), { recursive: true });
cpSync(join(root, 'favicon.svg'), join(out, 'favicon.svg'));

const versions = [];
for (const [pkg, items, dest] of LIBS) {
    for (const item of items) {
        cpSync(join(nm, pkg, item), join(out, 'lib', dest, item), { recursive: true });
    }
    versions.push(`${pkg}@${JSON.parse(readFileSync(join(nm, pkg, 'package.json'), 'utf8')).version}`);
}

// index.html points at node_modules/ for local development; the build points at lib/.
let html = readFileSync(join(root, 'index.html'), 'utf8');
html = html
    .replaceAll('node_modules/@mathzetta/inlinemath/', 'lib/inlinemath/')
    .replaceAll('node_modules/mathzetta/', 'lib/mathzetta/');
if (html.includes('node_modules/')) {
    console.error('index.html still refers to node_modules/ after rewriting; update LIBS.');
    process.exit(1);
}
writeFileSync(join(out, 'index.html'), html);

console.log(`Built ${relative(root, out) || out}/ with ${versions.join(', ')} in lib/.`);
console.log('Upload the folder as-is; serve it over http(s), e.g. python3 -m http.server -d dist');
