/**
 * Helpers shared by the renderers.
 */

import { needsParens, operator } from './operators.js';
import { isNumber } from './parse/vocabulary.js';

export const GREEK = {
    alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', zeta: 'ζ', eta: 'η', theta: 'θ',
    iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', omicron: 'ο', pi: 'π',
    rho: 'ρ', sigma: 'σ', tau: 'τ', upsilon: 'υ', phi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
    Alpha: 'Α', Beta: 'Β', Gamma: 'Γ', Delta: 'Δ', Epsilon: 'Ε', Zeta: 'Ζ', Eta: 'Η', Theta: 'Θ',
    Iota: 'Ι', Kappa: 'Κ', Lambda: 'Λ', Mu: 'Μ', Nu: 'Ν', Xi: 'Ξ', Omicron: 'Ο', Pi: 'Π',
    Rho: 'Ρ', Sigma: 'Σ', Tau: 'Τ', Upsilon: 'Υ', Phi: 'Φ', Chi: 'Χ', Psi: 'Ψ', Omega: 'Ω',
};

const isGreekLetter = (text) => Boolean(GREEK[text]) || /^[ʹ-Ͽ]$/.test(text);

/** The leftmost leaf of a subtree — the first token of its postfix. */
export function firstLeaf(node) {
    while (node.type === 'op' && node.args.length) node = node.args[0];
    return node.type === 'op' ? '' : node.value;
}

/** `-1 * x`, which every format writes as plain `-x`. */
export function isMinusOneTimes(node) {
    if (node.op !== '*') return false;
    const [left, right] = node.args;
    return left.type === 'number' && left.value === '-1' && firstLeaf(right) !== '-1';
}

/**
 * The operator that decides whether a node needs brackets inside another.
 * `sum(a, b)` behaves like `+`, `prod(a, b)` like `*`, and neither `-1 * x`
 * (written `-x`) nor a group like {1, 2} ever needs them. Leaves have none.
 */
export function bracketOp(node) {
    if (node.type !== 'op') return null;
    if (operator(node.op)?.group) return null;   // (a, b), {1, 2}: already bracketed
    if (node.op === 'sum') return '+';
    if (node.op === 'prod') return '*';
    if (isMinusOneTimes(node)) return null;
    return node.op;
}

/** Does `child` need brackets as the `side` operand of `parent`? */
export const needsBrackets = (parent, child, side) => needsParens(parent.op, bracketOp(child), side);

/**
 * Does a prefix or postfix operator (neg, !, \not) need brackets around its
 * operand? Anything with an operator weaker than a function call does.
 */
export function unaryNeedsBrackets(parentOp, child) {
    const op = bracketOp(child);
    const childPrec = op && operator(op)?.prec;
    if (!childPrec) return false;
    if (parentOp === '!') return childPrec <= operator('!').prec;   // (5!)! not 5!!
    if (parentOp === '\\not') return childPrec < operator('\\not').prec;
    // A minus sign in front of a product, quotient or power changes nothing:
    // -x^2, -2x, -\frac{1}{x}. Sums and another sign need brackets: -(a + b), -(-x).
    return childPrec < 70 || startsWithSign(child) || op === '\\not';
}

/**
 * Should `a * b` be written without a sign, as maths is typeset: 2x, xy,
 * 3\sin x, x^2y, \frac{1}{2}x, (x+1)(x-2), 2\sec^2 x? Yes, unless the dot is
 * needed to keep things apart: a digit or sign starting the right side
 * (x · 2, 2 · 3^x, 2 · -3), a multi-letter name (speed · time), a fraction
 * after a number (2 · \frac{1}{3}, which would read as 2⅓), or two fractions.
 */
export function isImplicitProduct(left, right, bracketed = {}) {
    const l = bracketed.left ? 'bracket' : lastDrawn(left);
    const r = bracketed.right ? 'bracket' : firstDrawn(right);
    if (r === 'digit' || r === 'sign' || l === 'word' || r === 'word' || l === 'other') return false;
    if (r === 'frac') return l !== 'digit' && l !== 'frac';
    return true;
}

/** One-letter variables, Greek letters, Δx, f′, π, e: names that can sit side by side. */
function isShortName(value) {
    return value.length === 1 || Boolean(GREEK[value]) || /^Δ.$/.test(value) || /^.′+$/.test(value);
}

/** Drawn as a bracket at its edges when it is a factor: x + 1 inside a product. */
function isBracketed(node) {
    return node.type === 'op' && !operator(node.op)?.group && (operator(node.op)?.prec ?? 100) < 70 && !['sum', 'prod'].includes(node.op);
}

/** What the left edge of a node looks like when drawn. */
function firstDrawn(node) {
    if (node.type === 'number') return node.value.startsWith('-') ? 'sign' : 'digit';
    if (node.type !== 'op') return node.type === 'symbol' && isShortName(node.value) ? 'name' : 'word';
    const op = node.op;
    if (op === 'neg' || op === 'pm' || isMinusOneTimes(node)) return 'sign';
    if (op === '/') return 'frac';
    if (operator(op)?.group || isBracketed(node)) return 'bracket';
    if (isFunctionCall(node) || ['der', 'int', 'lim', 'comb'].includes(op)) return 'call';
    if (['^', '!', '_'].includes(op)) return isBracketed(node.args[0]) ? 'bracket' : firstDrawn(node.args[0]);
    if (['*', 'sum', 'prod', 'perm'].includes(op)) return firstDrawn(node.args[0]);
    return 'other';
}

/** What the right edge of a node looks like when drawn. */
function lastDrawn(node) {
    if (node.type === 'number') return 'digit';
    if (node.type !== 'op') return node.type === 'symbol' && isShortName(node.value) ? 'name' : 'word';
    const op = node.op;
    if (op === '/') return 'frac';
    if (op === '^' || op === '_') return 'script';
    if (operator(op)?.group || isBracketed(node) || isFunctionCall(node) || ['der', 'int', 'lim', 'comb', 'perm'].includes(op)) return 'bracket';
    if (['*', 'neg', 'pm', 'sum', 'prod'].includes(op)) return lastDrawn(node.args[node.args.length - 1]);
    return 'other';
}

/** Which operands of a product will be drawn in brackets (a fraction never is). */
export function bracketedSides(node) {
    const [a, b] = node.args;
    return {
        left: needsBrackets(node, a, 'left') && a.op !== '/',
        right: needsBrackets(node, b, 'right') && b.op !== '/',
    };
}

/** sin(..), sqrt(..), |..|: written with a name or bracket in front. */
function isFunctionCall(node) {
    if (node.type !== 'op') return false;
    const def = operator(node.op);
    return def?.fixity === 'prefix' && def.prec === 100;
}

/** Will this node render with a leading minus sign? */
export function startsWithSign(node) {
    if (node.type === 'number') return node.value.startsWith('-');
    if (node.type !== 'op') return false;
    if (node.op === 'neg' || isMinusOneTimes(node)) return true;
    const def = operator(node.op);
    return def?.fixity === 'infix' && !needsBrackets(node, node.args[0], 'left') && startsWithSign(node.args[0]);
}

/** Single letters and Greek letters: the things integrals and limits range over. */
export const isVariable = (node) =>
    node.type === 'symbol' && node.value.length === 1 && /[a-zA-Zʹ-Ͽ]/.test(node.value);

/** Small non-negative whole number literal, as a number, else NaN. */
export function smallWhole(node, limit) {
    if (node.type !== 'number' || !/^\d+$/.test(node.value)) return NaN;
    const n = Number(node.value);
    return n < limit ? n : NaN;
}

/** The name of a custom function: `\:myFunc` → `myFunc`. */
export const customName = (op) => op.slice(2);

/**
 * d/dx applied n times: { n, body, by } for der(der(f, x), x) etc., and
 * whether the body is a plain variable, which is written dy/dx.
 */
export function derivativeOrder(node) {
    const by = node.args[1];
    let n = 0;
    let body = node;
    while (body.type === 'op' && body.op === 'der' && sameLeaf(body.args[1], by)) {
        n++;
        body = body.args[0];
    }
    return { n, body, by, variable: body.type === 'symbol' && isShortName(body.value) };
}

const sameLeaf = (a, b) => a.type === b.type && a.value === b.value && a.type !== 'op';
