/**
 * The words and symbols the tokenizer recognises as operators, with the
 * precedence (binding power) the parser gives them.
 *
 * This is deliberately separate from the operator table in ../operators.js.
 * That table describes the *output* (standard postfix); this one describes
 * the *input* the parser accepts, which includes spellings that get rewritten
 * later (`frac`, `pow`, `sqrtpow`, `\binom`, `==`, ...) and the comma that
 * builds argument lists.
 */

const FUNCTION = 100;

export const PARSE_PRECEDENCE = {
    // functions
    'ln': FUNCTION, 'log': FUNCTION, 'loglog': FUNCTION, 'logloglog': FUNCTION,
    'sqrt': FUNCTION, 'sqrtpow': FUNCTION, 'pow': FUNCTION, 'expm1': FUNCTION,
    'der': FUNCTION, 'lim': FUNCTION, 'int': FUNCTION,
    'round': FUNCTION, 'floor': FUNCTION, 'ceil': FUNCTION, 'abs': FUNCTION, 'random': FUNCTION,
    'sum': FUNCTION, 'prod': FUNCTION, '\\sumidx': FUNCTION, '\\prodidx': FUNCTION,
    'perm': FUNCTION, 'comb': FUNCTION, '\\perm': FUNCTION, '\\comb': FUNCTION, '\\binom': FUNCTION,
    'max': FUNCTION, 'min': FUNCTION, 'gcd': FUNCTION, 'mean': FUNCTION,
    'sin': FUNCTION, 'cos': FUNCTION, 'tan': FUNCTION, 'csc': FUNCTION, 'sec': FUNCTION, 'cot': FUNCTION,
    'sinh': FUNCTION, 'cosh': FUNCTION, 'tanh': FUNCTION,
    'arcsin': FUNCTION, 'arccos': FUNCTION, 'arctan': FUNCTION,
    'arcsinh': FUNCTION, 'arccosh': FUNCTION, 'arctanh': FUNCTION, 'atan2': FUNCTION,
    '_': FUNCTION,

    // operators, tightest first
    '!': 90,
    '\\not': 85,
    '^': 80,
    '*': 70, '/': 70, 'frac': 70,
    'mod': 45,      // see parser.js: takes all of its left side, one factor on the right
    '+': 50, '-': 50, '±': 50,
    '→': 38,
    '<': 34, '>': 34, '≤': 34, '≥': 34,
    '∈': 32, '∉': 32, '∪': 33, '∩': 33,
    '=': 30, '==': 30, '===': 30, '≠': 30, '≠=': 30, '!==': 30, '≈': 30, '≡': 30,
    'pmod': 2,      // a ≡ b (mod n): applies to the whole statement
    '&': 20,
    '\\xor': 19,
    '|': 18, '∨': 18,   // ∨ is "or" written so it can't be mistaken for an absolute value bar
    '\\nor': 17, '\\nand': 17,
    '?:': 10,
    '?': 9,
    ',': 5,
};

/** Is `text` a word the tokenizer should cut out as an operator? */
export const isOperatorWord = (text) =>
    Object.prototype.hasOwnProperty.call(PARSE_PRECEDENCE, text);

/** Operators that group right-to-left: 2^3^4 = 2^(3^4). */
export const RIGHT_ASSOCIATIVE = new Set(['^', '?:', '?', 'log']);

export const OPENERS = ['(', '{', '['];
export const CLOSERS = [')', '}', ']'];

/** A run of digits and dots: 3, 0.5, .5, 1.333.. — no sign, no exponent. */
export function isNumber(text, allowSign = false) {
    if (!text) return false;
    for (let i = 0; i < text.length; i++) {
        if ('0123456789.'.includes(text[i])) continue;
        if (allowSign && i === 0 && text[i] === '-' && text.length > 1) continue;
        return false;
    }
    return true;
}
