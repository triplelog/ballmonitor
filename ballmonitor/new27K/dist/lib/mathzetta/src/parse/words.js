/**
 * Deciding what a run of letters means: one name, or several names
 * multiplied. `xy` is x·y and `xsinx` is x·sin x, but `cost`, `speed` and
 * `profit` are words.
 *
 * In order, most certain first:
 *
 *   1. Names the caller declares — parse(text, { names: ['cost'] }) — and
 *      names the author marked: \text{rate}, \mathrm{rate}, \operatorname{sgn}.
 *      These are protected before cleaning (see parse/index.js), so they
 *      never reach this file as letters.
 *   2. Whole words that are always one thing: function names (sin, max),
 *      constants and Greek letters (pi, theta), true/false, and the word list
 *      below (cost, sine, point, order, ...): ordinary words that happen to
 *      contain a function or constant name.
 *   3. LaTeX input — anything with a \command in it — follows TeX, where
 *      letters side by side are a product: every run is split into known
 *      names and single letters (`rate` is r·a·t·e; write \text{rate}).
 *   4. Plain input: runs of one or two letters are split (xy, dx, ab).
 *      Longer runs stay whole — speed, abc, health — with two exceptions:
 *      a function name with at most one letter before it and two after
 *      (sinx, xsinx, lnx, sint), when something follows for it to apply to;
 *      and pi in a three-letter word (pir, pid). Everything else is a word:
 *      basin, topic, octane, distance.
 *
 * When in doubt, declare the name: parse(text, { names: ['dt', 'pin'] }).
 */

import { PARSE_PRECEDENCE } from './vocabulary.js';
import { GREEK } from '../common.js';

/** Function names that can appear inside a run of letters. */
const FUNCTION_NAMES = Object.keys(PARSE_PRECEDENCE).filter((w) => PARSE_PRECEDENCE[w] === 100 && /^[a-z]{2,}$/.test(w));

/** Also cut out of words: `xfrac{1}{2}` is x · \frac{1}{2}. */
const PREFIX_WORDS = ['frac'];

/** Multi-letter names that mean one thing: constants and Greek letters. */
const NAMES = [...Object.keys(GREEK), 'pi', 'tau', 'inf', 'infinity', 'exp'];

/**
 * Ordinary words that contain a function or constant name, and would
 * otherwise be read as one: cost is not cos(t), point is not p·o·int.
 */
const WORD_LIST = `
    cost costs coast cosine cosines cosy sine sines since sincere sinus single
    tank tanks tango stand stank
    point points print prints paint paints pint pints mint hint hints lint tint saint faint joint into
    spin spine pipe pipes pine pines pick picks pink pity pie pies pilot pivot pixel pizza piano
    order orders under wonder border render older elder ladder cider rider wider bidder
    logic logo logs blog clog login slog
    model models mode modes modal modest modern module modules
    limb limbs slim lime limo limit limits climb
    maxi minute minutes mince mind mine mines
    sums sumo summit rounds floors ceils means meant sect sects secs expo kiln
    meta metal metals taxi must mute muse nut nuts
`.trim().split(/\s+/);

/** Words that are never split. */
const WHOLE = new Set([...NAMES, ...WORD_LIST, 'true', 'false', 'null', 'undefined', 'deg', 'mod', 'pmod', 'NaN', 'Infinity']);

const LETTER = /^[a-zA-ZͰ-Ͽ]$/;
export const isLetters = (text) => text.length > 0 && [...text].every((c) => LETTER.test(c));

/** Single letters that name functions when written f(x): f, g, h, u, v. */
export const FUNCTION_LETTERS = new Set(['f', 'g', 'h', 'u', 'v', 'F', 'G', 'H']);

export const isFunctionName = (word) => FUNCTION_NAMES.includes(word) || PREFIX_WORDS.includes(word);

const ALL_PARTS = [...FUNCTION_NAMES, ...PREFIX_WORDS, ...NAMES].sort((a, b) => b.length - a.length);
const PLAIN_PARTS = [...FUNCTION_NAMES, ...PREFIX_WORDS, 'pi'].sort((a, b) => b.length - a.length);

/** Greedy left-to-right split into known names and single letters. */
export function decompose(word, parts = ALL_PARTS) {
    const pieces = [];
    let i = 0;
    while (i < word.length) {
        const piece = parts.find((p) => word.startsWith(p, i)) ?? word[i];
        pieces.push(piece);
        i += piece.length;
    }
    return pieces;
}

/** Does the run end in a function name (sin, xsin), so digits after it are its argument? */
export function endsWithFunction(word) {
    if (isFunctionName(word)) return true;
    const pieces = decompose(word, PLAIN_PARTS);
    return pieces.length > 1 && isFunctionName(pieces[pieces.length - 1]) && !WHOLE.has(word);
}

/**
 * Read a run of letters (and primes).
 * @param {string} word
 * @param {object} [context]
 * @param {'latex'|'plain'} [context.mode] see the rules above
 * @param {boolean} [context.followed] does something follow that a function could apply to?
 * @returns {string[]} the names, in order
 */
export function readWord(word, { mode = 'plain', followed = true } = {}) {
    if (word.includes('′') && /^[a-zA-Z′]+$/.test(word) && !/^.′+$/.test(word)) {
        return word.match(/[a-zA-Z]′*/g);   // f′g → f′ g: each prime belongs to the letter before it
    }
    if (!isLetters(word) || word.length === 1 || WHOLE.has(word) || isFunctionName(word)) return [word];
    if (word[0] === 'Δ' && word.length === 2) return [word];   // Δx is one quantity

    if (mode === 'latex') return withoutDanglingFunction(decompose(word), followed);

    if (word.length <= 2) return [...word];
    const pieces = withoutDanglingFunction(decompose(word, PLAIN_PARTS), followed);
    const named = pieces.findIndex((p) => p.length > 1);
    if (named < 0) return [word];
    if (pieces[named] === 'pi' && !pieces.some((p) => FUNCTION_NAMES.includes(p))) {
        return word.length === 3 ? pieces : [word];
    }
    // Letters before the first name, and the longest run of letters anywhere else.
    const before = named;
    let run = 0;
    let longestAfter = 0;
    for (const p of pieces.slice(named)) {
        run = p.length === 1 ? run + 1 : 0;
        longestAfter = Math.max(longestAfter, run);
    }
    return before <= 1 && longestAfter <= 2 ? pieces : [word];
}

/** A function name at the very end with nothing to apply to is just letters: `basin`, `xsin`. */
function withoutDanglingFunction(pieces, followed) {
    const last = pieces[pieces.length - 1];
    if (followed || !FUNCTION_NAMES.includes(last)) return pieces;
    return [...pieces.slice(0, -1), ...last];
}
