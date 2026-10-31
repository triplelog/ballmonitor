/**
 * The cleaner: rewrites whatever the user typed into one compact spelling
 * the tokenizer understands. Its phases, in order:
 *
 *   1. strings     primes (f'(x)) become ′, then quoted strings are swapped
 *                  for placeholders (strings.js);
 *                  then `{{...}}` blocks are evaluated, if a callback is given
 *   2. code        programming spellings (code.js): np.where(c, a, b), a if c
 *                  else b, CASE WHEN, x IN (1, 2), [1, 2].includes(x), mz_sq(x) …
 *   3. words       WORD_REPLACEMENTS, while spaces still separate words:
 *                  ` And ` → `&`, ` choose ` → `\comb`
 *   4. spaced      structural rewrites that need spaces: \lim x→0 f,
 *                  \text{..}, log bases, ternaries, numeric scripts
 *   5. squeeze     whitespace is removed, except one space between two
 *                  letters, which separates words (`cos t`, `x y`)
 *   6. symbols     SYMBOL_REPLACEMENTS and trig spellings:
 *                  \cdot → *, >= → ≥, Math.sqrt( → sqrt(, \sin → sin
 *   7. compact     structural rewrites on the squeezed text: \frac{d}{dx},
 *                  \int, \sum, \sqrt[n], ⌊⌋, matrices, sin^2(x) (latex.js)
 *
 * Every phase is a plain string → string function, and clean() returns the
 * text after each one in `steps`, for debugging.
 */

import { makeReplacer } from './trie.js';
import { WORD_REPLACEMENTS, SYMBOL_REPLACEMENTS, trigReplacements } from './replacements.js';
import { spacedRewrites, compactRewrites } from './latex.js';
import { extractStrings, markPrimes, placeholder } from './strings.js';
import { codeRewrites } from './code.js';

const replaceWords = makeReplacer(WORD_REPLACEMENTS);
const replaceSymbols = makeReplacer([...SYMBOL_REPLACEMENTS, ...trigReplacements()]);

const PHASES = [
    ['code', codeRewrites],
    ['words', replaceWords],
    ['spaced', spacedRewrites],
    ['squeeze', squeeze],
    ['symbols', replaceSymbols],
    ['compact', compactRewrites],
    ['tidy', (s) => s.replace(/ {2,}/g, ' ').trim()],   // replacements may have doubled spaces
];

/**
 * Remove whitespace — except one space between two letters, which keeps
 * words apart: `cos t` must not become `cost`, nor `x y` the word `xy`.
 */
function squeeze(text) {
    return text.replace(/\s+/g, (space, at) => {
        const before = text[at - 1] ?? '';
        const after = text[at + space.length] ?? '';
        if (before === 'Δ') return '';   // Δ x is the one quantity Δx
        return /[A-Za-z\u0370-\u03FF′]/.test(before) && /[A-Za-z\u0370-\u03FF]/.test(after) ? ' ' : '';
    });
}

/**
 * Clean an expression for tokenizing.
 * @param {string} input
 * @param {object} [options]
 * @param {(expression: string) => string} [options.evaluate] called with the
 *   text of each `{{...}}` block; its result replaces the block (a quoted
 *   result, like "undefined", becomes a string). Blocks it throws on are left
 *   as they are. Without it, blocks are left alone.
 * @returns {{ cleaned: string, stringMap: Map<string, string>, steps: Array }}
 *   cleaned text (strings replaced by placeholders), the placeholder → string
 *   map, and [phase name, text after it] for every phase
 */
export function clean(input, options = {}) {
    if (typeof input !== 'string') throw new Error('Expression must be a string');
    const { text, strings } = extractStrings(markPrimes(input));
    let cleaned = text.replace(/\t/g, ' ');
    if (options.evaluate) cleaned = evaluateBlocks(cleaned, strings, options.evaluate);
    const steps = [['strings', cleaned]];
    for (const [name, phase] of PHASES) {
        cleaned = phase(cleaned);
        steps.push([name, cleaned]);
    }
    return { cleaned, stringMap: strings, steps };
}

/** Replace each `{{expression}}` with ` value `, left to right. */
function evaluateBlocks(text, strings, evaluate) {
    let from = 0;
    for (;;) {
        const start = text.indexOf('{{', from);
        if (start < 0) return text;
        const end = matchingClose(text, start);
        if (end < 0) return text;
        let expression = text.slice(start + 2, end).trim();
        for (const [id, original] of strings) expression = expression.split(id).join(original);
        try {
            let value = evaluate(expression);
            if (/^["'`]/.test(value)) {
                const id = placeholder(strings.size);
                strings.set(id, value);
                value = id;
            }
            // A bare number next to a digit would join it: 2{{1+1}} is 2·2, not 22.
            const before = text.slice(0, start).trimEnd();
            const after = text.slice(end + 2).trimStart();
            if (/^[\d.]/.test(value) && (/[\d.]$/.test(before) || /^[\d.]/.test(after))) value = `(${value})`;
            text = text.slice(0, start) + ' ' + value + ' ' + text.slice(end + 2);
            from = 0;
        } catch {
            from = end + 2;
        }
    }
}

/** Index of the `}}` closing the `{{` at `start`, counting braces in between. */
function matchingClose(text, start) {
    let depth = 0;
    for (let i = start + 2; i < text.length; i++) {
        if (text.startsWith('}}', i) && depth === 0) return i;
        if (text[i] === '{') depth++;
        else if (text[i] === '}') depth--;
    }
    return -1;
}
