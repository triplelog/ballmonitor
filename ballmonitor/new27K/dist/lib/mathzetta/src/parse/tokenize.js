/**
 * Tokenizer: cleaned text → infix tokens.
 *
 * Runs after the cleaner, so spellings are normalised (`\sin` → `sin`,
 * `×` → `*`, ...) and whitespace is gone except single spaces between two
 * letters, which separate words (`cos t`). The rules:
 *
 *   - Brackets ( ) { } [ ] and `_` are always tokens of their own.
 *   - A run of letters is gathered whole and then read by words.js, which
 *     decides between one name and several: `cost`, `xy` → x y,
 *     `xsinx` → x sin x.
 *   - Other operator words and symbols are cut out greedily, longest match
 *     first: `===` beats `==`, `\sumidx` is one token.
 *   - Everything else accumulates into one operand token. Splitting `4x`
 *     into `4 x` happens later, in the parser.
 *   - A protected name (`§0§`, standing for a declared or \text{} name,
 *     see parse/index.js) is one token; followed by `(` it is a call.
 *   - A word directly followed by an opening bracket may be a function
 *     call: known words keep their name (`sin(`), LaTeX commands lose their
 *     backslash (`\foo(` → `foo` if known), the letters f g h u v F G H and
 *     primed letters (f′) are functions, and unknown words of three or more
 *     letters become custom functions `\:name`. Other single letters and
 *     two-letter words are left for the parser (`x(t)` is a call, `x(x+1)` a
 *     product), and `xsin(` is `x` then `sin(`. A number before a bracket
 *     gets an explicit `*`.
 */

import { isOperatorWord, isNumber, OPENERS } from './vocabulary.js';
import { CUSTOM_PREFIX } from '../operators.js';
import { isFunctionName, FUNCTION_LETTERS, readWord, endsWithFunction } from './words.js';
import { isPlaceholder } from './clean/strings.js';

const BRACKETS = '(){}[]';
/** Marks a protected name: `§0§`. */
export const PROTECTED = '§';
const LETTER = /[A-Za-zͰ-Ͽ′]/;
const isLetterRun = (word) => /^[A-Za-zͰ-Ͽ][A-Za-zͰ-Ͽ′]*$/.test(word);

/**
 * @param {string} input cleaned expression text
 * @param {'latex'|'plain'} [mode] how runs of letters are read (words.js)
 * @returns {string[]} infix tokens
 */
export function tokenize(input, mode = 'plain') {
    if (typeof input !== 'string') throw new Error('Tokenizer input must be a string');

    const tokens = [];
    let word = '';
    const flush = (next) => {
        if (!word) return;
        if (isLetterRun(word)) tokens.push(...letterRun(word, next, mode));
        else tokens.push(word);
        word = '';
    };

    for (let i = 0; i < input.length; i++) {
        const char = input[i];

        if (char === PROTECTED) {
            flush(char);
            const end = input.indexOf(PROTECTED, i + 1);
            const name = input.slice(i, end + 1);
            tokens.push(OPENERS.includes(input[end + 1]) ? CUSTOM_PREFIX + name : name);
            i = end;
            continue;
        }

        // Letters gather into a run, read as a whole when it ends.
        // atan2, log10: an operator name with digits in it stays whole.
        if (isLetterRun(word) && /[0-9]/.test(char) && isOperatorWord(word + char)) {
            const { op, end } = longestOperator(input, i, word + char);
            tokens.push(op);
            word = '';
            i = end;
            continue;
        }
        if (LETTER.test(char) && char !== '′' && isNumber(word)) {
            tokens.push(word);   // 2x: the number, then a run of letters read on its own
            word = '';
        }
        if (LETTER.test(char) && (word === '' ? char !== '′' : isLetterRun(word))) {
            word += char;
            continue;
        }
        // x1, v0: digits after a variable stay part of its name — but sin2x is sin(2x).
        if (/[0-9]/.test(char) && isLetterRun(word) && !endsWithFunction(word)) {
            word += char;
            continue;
        }
        if (isLetterRun(word)) flush(char === ' ' ? input[i + 1] : char);

        if (BRACKETS.includes(char)) {
            if (word) tokens.push(...wordBeforeBracket(word, char));
            word = '';
            tokens.push(char);
            continue;
        }

        if (char === '_' || char === ' ') {
            flush(input[i + 1]);
            if (char === '_') tokens.push('_');
            continue;
        }

        // An operator word that ends here, e.g. the `x` completing `\sumidx`.
        if (isOperatorWord(word + char)) {
            const { op, end } = longestOperator(input, i, word + char);
            tokens.push(op);
            word = '';
            i = end;
            continue;
        }

        // An operator word that starts here.
        if (isOperatorWord(char)) {
            flush(char);
            const { op, end } = longestOperator(input, i, char);
            tokens.push(op);
            i = end;
            continue;
        }

        word += char;
    }
    flush(undefined);
    return tokens;
}

/** Extend `op` (which ends at input[index]) while it stays an operator word. */
function longestOperator(input, index, op) {
    let end = index;
    while (end + 1 < input.length && isOperatorWord(op + input[end + 1])) {
        op += input[end + 1];
        end++;
    }
    // `!_` is the cleaner's mark for "this ! is a factorial": drop the `_`.
    if (op === '!' && input[end + 1] === '_') end++;
    return { op, end };
}

/** A run of letters, given what comes after it. */
function letterRun(word, next, mode) {
    if (isPlaceholder(word)) return [word];   // a "string", whatever the mode
    if (OPENERS.includes(next)) return callOrProduct(word, mode);
    // A function name needs something after it to apply to.
    const followed = next !== undefined && !/[+\-*/=<>),\]}|!≤≥≠]/.test(next);
    return readWord(word, { mode, followed });
}

/** A run of letters directly followed by an opening bracket. */
function callOrProduct(word, mode) {
    if (/^[a-zA-Z]′+$/.test(word)) return [CUSTOM_PREFIX + word];   // f′(x)
    if (word.toLowerCase() === 'if') return [CUSTOM_PREFIX + 'if'];   // IF(c, a, b), as in a spreadsheet
    if (word.length === 1) return FUNCTION_LETTERS.has(word) ? [CUSTOM_PREFIX + word] : [word];
    if (isOperatorWord(word)) return [word];
    const pieces = readWord(word, { mode, followed: true });
    if (pieces.length > 1) return pieces;                             // xsin( → x sin(
    if (word.length <= 2) return [...word];                           // ab( → a b (
    return [CUSTOM_PREFIX + word];                                    // myFunction(
}

/** What a non-letter word turns into when a bracket follows it. */
function wordBeforeBracket(word, bracket) {
    if (!OPENERS.includes(bracket)) return [word];
    if (word[0] === '\\') {
        const name = word.slice(1);
        return [isOperatorWord(name) ? name : CUSTOM_PREFIX + name];
    }
    if (isNumber(word)) return [word, '*'];
    if (isOperatorWord(word) || isFunctionName(word)) return [word];
    if (isNumber(word[0])) return [word];         // `4x(` — the parser splits it
    return [CUSTOM_PREFIX + word];
}
