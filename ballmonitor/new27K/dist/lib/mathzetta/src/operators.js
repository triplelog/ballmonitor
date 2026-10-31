/**
 * The operator table — the one place that says what every operator is.
 *
 * Each entry describes one token that can appear in MathZetta postfix:
 *
 *   prec   binding strength, higher binds tighter. Used by the parser
 *          (src/parse/parser.js) and by the renderers to decide on brackets.
 *   assoc  'left' | 'right' | 'none' — how equal-precedence chains group.
 *   arity  how many operands it takes in postfix. VARIADIC means the
 *          operand count is written as a number token just before the
 *          operator: `1 2 3 3 max` is max(1, 2, 3).
 *   fixity 'infix' (a + b), 'prefix' (sin x, -x, ¬p) or 'postfix' (x!).
 *          Only the parser cares; postfix order is the same for all.
 *
 * Adding an operator: add it here, then give it a case in each renderer
 * under src/render/. `test/run.js` checks that every operator in this
 * table renders in every format, so a missing case fails loudly.
 */

export const VARIADIC = -1;

const FUNCTION = 100;   // precedence shared by every named function

const table = {
    // ---- arithmetic -------------------------------------------------------
    '+':   { prec: 50, assoc: 'left', arity: 2, fixity: 'infix' },
    '-':   { prec: 50, assoc: 'left', arity: 2, fixity: 'infix' },
    '±':   { prec: 50, assoc: 'left', arity: 2, fixity: 'infix' },
    '*':   { prec: 70, assoc: 'left', arity: 2, fixity: 'infix' },
    '/':   { prec: 70, assoc: 'left', arity: 2, fixity: 'infix' },
    '^':   { prec: 80, assoc: 'right', arity: 2, fixity: 'infix' },
    'mod': { prec: 45, assoc: 'left', arity: 2, fixity: 'infix' },   // see needsParens
    'neg': { prec: 75, assoc: 'none', arity: 1, fixity: 'prefix' },   // unary minus
    'pm':  { prec: 75, assoc: 'none', arity: 1, fixity: 'prefix' },   // unary ±, as in x = ±√3
    '!':   { prec: 90, assoc: 'none', arity: 1, fixity: 'postfix' },  // factorial
    '_':   { prec: FUNCTION, assoc: 'none', arity: 2, fixity: 'infix' },  // subscript x_1

    // ---- named functions of one argument ------------------------------------
    'sqrt': fn(1), 'abs': fn(1), 'floor': fn(1), 'ceil': fn(1),
    'ln': fn(1), 'loglog': fn(1), 'logloglog': fn(1), 'expm1': fn(1),
    'sin': fn(1), 'cos': fn(1), 'tan': fn(1), 'csc': fn(1), 'sec': fn(1), 'cot': fn(1),
    'sinh': fn(1), 'cosh': fn(1), 'tanh': fn(1),
    'arcsin': fn(1), 'arccos': fn(1), 'arctan': fn(1),
    'arcsinh': fn(1), 'arccosh': fn(1), 'arctanh': fn(1),

    // ---- named functions with a fixed number of arguments -------------------
    'random': fn(0),
    'log':   fn(2),     // base x log      log_base(x)
    'root':  fn(2),     // n x root        n-th root of x
    'atan2': fn(2),     // y x atan2
    'round': fn(2),     // x digits round
    'perm':  fn(2),     // n k perm        nPk
    'comb':  fn(2),     // n k comb        n choose k
    'der':   fn(2),     // f x der         d/dx f

    // ---- named functions with any number of arguments -----------------------
    'max': fn(VARIADIC), 'min': fn(VARIADIC), 'gcd': fn(VARIADIC), 'mean': fn(VARIADIC),
    'sum': fn(VARIADIC),       // sum(a, b, c)      a + b + c
    'prod': fn(VARIADIC),      // prod(a, b, c)     a · b · c
    'int': fn(VARIADIC),       // int(f, x, lo, hi) and shorter forms
    'lim': fn(VARIADIC),       // lim(f, x→a) and longer forms
    '\\sumidx': fn(VARIADIC),  // ∑ with index:   body, from, to
    '\\prodidx': fn(VARIADIC), // ∏ with index:   body, from, to

    // ---- groups: tuples, lists, sets, intervals ----------------------------
    '()': group(), '[]': group(), '{}': group(), '(]': group(), '[)': group(),

    // ---- comparison and sets ------------------------------------------------
    '=':   { prec: 30, assoc: 'left', arity: 2, fixity: 'infix' },
    '===': { prec: 30, assoc: 'left', arity: 2, fixity: 'infix' },
    '≠':   { prec: 30, assoc: 'left', arity: 2, fixity: 'infix' },
    '≠=':  { prec: 30, assoc: 'left', arity: 2, fixity: 'infix' },   // strict not-equal (!==)
    '<':   { prec: 34, assoc: 'left', arity: 2, fixity: 'infix' },
    '>':   { prec: 34, assoc: 'left', arity: 2, fixity: 'infix' },
    '≤':   { prec: 34, assoc: 'left', arity: 2, fixity: 'infix' },
    '≥':   { prec: 34, assoc: 'left', arity: 2, fixity: 'infix' },
    '∈':   { prec: 32, assoc: 'left', arity: 2, fixity: 'infix' },
    '∉':   { prec: 32, assoc: 'left', arity: 2, fixity: 'infix' },
    '∪':   { prec: 33, assoc: 'left', arity: 2, fixity: 'infix' },   // union, for domains
    '∩':   { prec: 33, assoc: 'left', arity: 2, fixity: 'infix' },
    '≈':   { prec: 30, assoc: 'left', arity: 2, fixity: 'infix' },
    '≡':   { prec: 30, assoc: 'left', arity: 2, fixity: 'infix' },   // congruent
    'pmod': { prec: 2, assoc: 'left', arity: 2, fixity: 'infix' },   // statement n pmod: a ≡ b (mod n)
    '→':   { prec: 38, assoc: 'left', arity: 2, fixity: 'infix' },   // x → a, inside limits

    // ---- logic ----------------------------------------------------------------
    '\\not':  { prec: 85, assoc: 'none', arity: 1, fixity: 'prefix' },
    '&':      { prec: 20, assoc: 'left', arity: 2, fixity: 'infix' },
    '\\xor':  { prec: 19, assoc: 'left', arity: 2, fixity: 'infix' },
    '|':      { prec: 18, assoc: 'left', arity: 2, fixity: 'infix' },
    '\\nor':  { prec: 17, assoc: 'left', arity: 2, fixity: 'infix' },
    '\\nand': { prec: 17, assoc: 'left', arity: 2, fixity: 'infix' },
    '?:':     { prec: 10, assoc: 'right', arity: 3, fixity: 'infix' }, // cond a b ?:
};

function fn(arity) {
    return { prec: FUNCTION, assoc: 'none', arity, fixity: 'prefix' };
}

function group() {
    return { prec: 5, assoc: 'left', arity: VARIADIC, fixity: 'none', group: true };
}

/** Prefix for user-defined functions: `f(x, y)` becomes `x y 2 \:f`. */
export const CUSTOM_PREFIX = '\\:';

export const isCustomFunction = (token) =>
    typeof token === 'string' && token.startsWith(CUSTOM_PREFIX) && token.length > CUSTOM_PREFIX.length;

/** The definition for an operator token, or undefined for operands. */
export function operator(token) {
    if (Object.prototype.hasOwnProperty.call(table, token)) return table[token];
    if (isCustomFunction(token)) return CUSTOM;
    return undefined;
}

const CUSTOM = fn(VARIADIC);

export const isOperator = (token) => operator(token) !== undefined;

/** Every built-in operator name, for docs and the test that checks renderers. */
export const operatorNames = () => Object.keys(table);

export const precedenceOf = (token) => operator(token)?.prec;

/**
 * Does a child expression need brackets inside its parent?
 * `side` is 'left' or 'right' for binary parents.
 */
export function needsParens(parentOp, childOp, side) {
    // mod reads differently in maths (everything to its left) and in code
    // (like *), so it gets brackets wherever a reader could hesitate: around
    // any compound operand, (a + b) mod n, (a·b) mod n, a mod (2n); inside a
    // product, (a mod n)·2; and on the right of + or -, 1 + (a mod n).
    // Only `a mod n + 1` reads the same every way and needs none.
    if (parentOp === 'mod' && childOp) return precedenceOf(childOp) <= 70;
    if (childOp === 'mod' && ['*', '/'].includes(parentOp)) return true;
    if (childOp === 'mod' && ['+', '-', '±'].includes(parentOp)) return side === 'right';
    const parent = precedenceOf(parentOp);
    const child = precedenceOf(childOp);
    if (!parent || !child) return false;
    if (child !== parent) return child < parent;
    const assoc = operator(parentOp).assoc;
    if (assoc === 'left') return side === 'right';
    if (assoc === 'right') return side === 'left';
    return false;
}
