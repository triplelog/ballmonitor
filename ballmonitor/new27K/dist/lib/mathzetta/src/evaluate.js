/**
 * 'mathzetta/evaluate' — numeric evaluation in double precision, without
 * generating or running any code. For exact answers (fractions, surds,
 * 2^100) see 'mathzetta/calculate'.
 *
 * Variables come from `scope`; pi, e, tau, ∞, true and false are built in.
 * Symbolic operators (der, int, lim, ...) can't be evaluated and throw.
 */

import { treeOf } from './input.js';

const CONSTANTS = {
    pi: Math.PI, 'π': Math.PI, e: Math.E, tau: 2 * Math.PI, 'τ': 2 * Math.PI,
    '∞': Infinity, '-∞': -Infinity, true: true, false: false,
};

const factorial = (n) => {
    if (!Number.isInteger(n) || n < 0) return NaN;
    if (n > 170) return Infinity;   // 171! overflows a double; no point looping to it
    let r = 1;
    for (let i = 2; i <= n; i++) r *= i;
    return r;
};
/** n·(n−1)···(n−k+1), without the overflow of n!/(n−k)!. */
const perm = (n, k) => {
    if (!Number.isInteger(n) || !Number.isInteger(k) || k < 0 || k > n) return NaN;
    let r = 1;
    for (let i = n - k + 1; i <= n; i++) r *= i;
    return r;
};
const gcd2 = (a, b) => (b ? gcd2(b, a % b) : Math.abs(a));

const ONE = {
    neg: (a) => -a, pm: (a) => [a, -a], '!': factorial, '\\not': (a) => !a,
    sqrt: Math.sqrt, abs: Math.abs, floor: Math.floor, ceil: Math.ceil,
    ln: Math.log, loglog: (a) => Math.log10(Math.log10(a)), logloglog: (a) => Math.log10(Math.log10(Math.log10(a))),
    expm1: Math.expm1,
    sin: Math.sin, cos: Math.cos, tan: Math.tan,
    csc: (a) => 1 / Math.sin(a), sec: (a) => 1 / Math.cos(a), cot: (a) => 1 / Math.tan(a),
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    arcsin: Math.asin, arccos: Math.acos, arctan: Math.atan,
    arcsinh: Math.asinh, arccosh: Math.acosh, arctanh: Math.atanh,
};

const TWO = {
    '+': (a, b) => a + b, '-': (a, b) => a - b, '*': (a, b) => a * b, '/': (a, b) => a / b,
    '^': (a, b) => a ** b, mod: (a, b) => a % b,
    log: (base, x) => Math.log(x) / Math.log(base),
    root: (n, x) => x ** (1 / n),
    atan2: Math.atan2,
    round: (x, d) => Math.round(x * 10 ** d) / 10 ** d,
    perm, comb: (n, k) => perm(n, k) / factorial(k),
    '=': (a, b) => a == b, '===': (a, b) => a === b, '≠': (a, b) => a != b, '≠=': (a, b) => a !== b,
    '≈': (a, b) => Math.abs(a - b) < 1e-9,
    '≡': (a, b) => a === b,
    '∪': (a, b) => [...new Set([...[].concat(a), ...[].concat(b)])],
    '∩': (a, b) => [].concat(a).filter((x) => [].concat(b).includes(x)),
    '<': (a, b) => a < b, '>': (a, b) => a > b, '≤': (a, b) => a <= b, '≥': (a, b) => a >= b,
    '&': (a, b) => a && b, '|': (a, b) => a || b,
    '\\xor': (a, b) => Boolean(a) !== Boolean(b), '\\nor': (a, b) => !(a || b), '\\nand': (a, b) => !(a && b),
};

const MANY = {
    max: (xs) => Math.max(...xs), min: (xs) => Math.min(...xs),
    sum: (xs) => xs.reduce((a, b) => a + b, 0), prod: (xs) => xs.reduce((a, b) => a * b, 1),
    mean: (xs) => xs.reduce((a, b) => a + b, 0) / xs.length,
    gcd: (xs) => xs.reduce(gcd2),
    '()': (xs) => xs, '[]': (xs) => xs, '{}': (xs) => xs,
};

/**
 * @param {string|string[]|object} input expression text, standard postfix or a tree
 * @param {object} [scope] variable values, e.g. { x: 2 }
 * @returns {number|boolean|string|Array}
 */
export function evaluate(input, scope = {}) {
    return value(treeOf(input), scope);
}

function value(node, scope) {
    switch (node.type) {
        case 'number':
            return Number(node.value);
        case 'string':
            return node.value.slice(1, -1);
        case 'symbol':
            if (Object.prototype.hasOwnProperty.call(scope, node.value)) return scope[node.value];
            if (Object.prototype.hasOwnProperty.call(CONSTANTS, node.value)) return CONSTANTS[node.value];
            throw new Error(`No value for '${node.value}'`);
    }

    const { op, args } = node;
    if (op === '?:') return value(args[0], scope) ? value(args[1], scope) : value(args[2], scope);
    if (op === '∈' || op === '∉') return membership(node, scope);
    if (op === 'random') return Math.random();
    if (op === 'pmod') {
        const [statement, modulus] = args;
        const n = value(modulus, scope);
        if (statement.type === 'op' && ['≡', '='].includes(statement.op)) {
            const [l, r] = statement.args.map((s) => value(s, scope));
            return (l - r) % n === 0;
        }
        return value(statement, scope) % n;
    }

    const vals = args.map((a) => value(a, scope));
    if (ONE[op] && vals.length === 1) return ONE[op](vals[0]);
    if (TWO[op] && vals.length === 2) return TWO[op](vals[0], vals[1]);
    if (MANY[op]) return MANY[op](vals);
    throw new Error(`Can't evaluate '${op}'`);
}

const NUMBER_SETS = {
    'ℝ': Number.isFinite,
    'ℤ': Number.isInteger,
    'ℕ': (v) => Number.isInteger(v) && v > 0,
};

function membership(node, scope) {
    const [x, set] = node.args;
    const v = value(x, scope);
    let inside;
    if (set.type === 'symbol' && NUMBER_SETS[set.value]) {
        inside = NUMBER_SETS[set.value](v);
        return node.op === '∈' ? inside : !inside;
    }
    if (set.type === 'op' && ['()', '[]', '(]', '[)'].includes(set.op) && set.args.length === 2) {
        const [lo, hi] = set.args.map((a) => value(a, scope));
        const lower = set.op[0] === '[' ? v >= lo : v > lo;
        const upper = set.op[1] === ']' ? v <= hi : v < hi;
        inside = lower && upper;
    } else {
        const items = value(set, scope);
        inside = Array.isArray(items) && items.includes(v);
    }
    return node.op === '∈' ? inside : !inside;
}
