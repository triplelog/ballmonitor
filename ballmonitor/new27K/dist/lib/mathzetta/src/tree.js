/**
 * Expression trees, and conversion to and from standard postfix.
 *
 * Every renderer works on a tree, never on postfix directly. There are four
 * kinds of node:
 *
 *   { type: 'number', value: '3' }          also '-2', '0.5', '1.333..'
 *   { type: 'symbol', value: 'x' }          variables and constants: x, pi, e, ∞, θ, true
 *   { type: 'string', value: '"abc"' }      quoted text, quotes included
 *   { type: 'op', op: '+', args: [a, b] }   every operator and function
 *
 * `fromPostfix` gives each node an `id`: the index of its token in the
 * postfix array. So a node can always be traced back to the token that made
 * it, and two renderings of the same postfix share ids — which is what lets
 * a display highlight the part being spoken about.
 */

import { operator, VARIADIC } from './operators.js';
import { isNumber } from './parse/vocabulary.js';

export const num = (value) => ({ type: 'number', value: String(value) });
export const sym = (value) => ({ type: 'symbol', value });
export const op = (name, args) => ({ type: 'op', op: name, args });

const QUOTES = ['"', "'", '`'];

/** The leaf node for an operand token. */
export function leaf(token) {
    if (isNumber(token, true)) return num(token);
    if (QUOTES.includes(token[0])) return { type: 'string', value: token };
    return sym(token);
}

/** Old or alternative spellings accepted when reading postfix. */
const ALIASES = { '0-': 'neg', 'sqrtpow': 'root', 'pow': '^', '==': '=', '!==': '≠=' };

/**
 * Read standard postfix into a tree.
 * @param {string[]} tokens
 * @returns {object} root node; throws if the postfix is malformed
 */
export function fromPostfix(tokens) {
    if (!Array.isArray(tokens) || tokens.length === 0) throw new Error('Empty postfix');
    const stack = [];
    tokens.forEach((raw, id) => {
        const token = ALIASES[raw] ?? String(raw);
        const def = operator(token);
        if (!def) {
            stack.push({ ...leaf(token), id });
            return;
        }
        let count = def.arity;
        if (count === VARIADIC) {
            const counter = stack.pop();
            count = counter && counter.type === 'number' ? Number(counter.value) : NaN;
            if (!Number.isInteger(count) || count < 0) {
                throw new Error(`'${token}' takes a variable number of arguments, so it must follow a count`);
            }
        }
        if (stack.length < count) {
            throw new Error(`'${token}' needs ${count} operand${count === 1 ? '' : 's'}`);
        }
        stack.push({ ...op(token, stack.splice(stack.length - count, count)), id });
    });
    if (stack.length !== 1) {
        throw new Error(`Postfix leaves ${stack.length} values instead of 1`);
    }
    return stack[0];
}

/** Write a tree as standard postfix. Variadic operators get their count. */
export function toPostfix(node) {
    const out = [];
    (function visit(n) {
        if (n.type !== 'op') {
            out.push(n.value);
            return;
        }
        n.args.forEach(visit);
        if (operator(n.op)?.arity === VARIADIC) out.push(String(n.args.length));
        out.push(n.op);
    })(node);
    return out;
}

/** Accept a tree, or a postfix array, and return a tree. */
export function asTree(input) {
    if (Array.isArray(input)) return fromPostfix(input);
    if (input && typeof input === 'object' && input.type) return input;
    throw new Error('Expected a postfix array or an expression tree');
}

/** Visit every node, parents before children. */
export function walk(node, visit, parent = null) {
    visit(node, parent);
    if (node.type === 'op') node.args.forEach((child) => walk(child, visit, node));
}

/** The first single-letter variable in a tree, or '' (used to guess `dx`). */
export function firstVariable(node) {
    let found = '';
    walk(node, (n) => {
        if (!found && n.type === 'symbol' && n.value.length === 1 && /[a-zA-Zʹ-Ͽ]/.test(n.value)) {
            found = n.value;
        }
    });
    return found;
}
