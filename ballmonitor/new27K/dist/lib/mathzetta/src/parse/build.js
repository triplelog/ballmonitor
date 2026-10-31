/**
 * Raw postfix → expression tree.
 *
 * The parser leaves two things unresolved, and this step settles
 * both while building the tree:
 *
 * 1. Argument lists. Commas are binary in raw postfix and a bracket that
 *    held commas becomes a group token, so `max(1,2,3)` arrives as
 *    `1 2 , 3 , () max`. A function applied directly to a group takes the
 *    group's items as its arguments; anywhere else a group is a value in its
 *    own right — a tuple, list, set or interval.
 *
 * 2. Spellings and defaults. `pow(a,b)` is `a^b`, `sqrt(n,x)` is the n-th
 *    root, `round(x)` rounds to 0 places, `der(f)` differentiates by x, and
 *    so on — see normalize().
 *
 * Every operator then has exactly the arity the operator table gives it,
 * which is what makes the tree's postfix "standard".
 */

import { operator, isCustomFunction, VARIADIC } from '../operators.js';
import { PARSE_PRECEDENCE } from './vocabulary.js';
import { EMPTY_LIST } from './parser.js';
import { leaf, op, num, sym } from '../tree.js';

const GROUPS = new Set(['()', '[]', '{}', '(]', '[)']);

/** Raw-only spellings and the operator they stand for. */
const RENAMES = {
    'pow': '^', 'sqrtpow': 'root', '\\binom': 'comb', '\\comb': 'comb', '\\perm': 'perm',
    'frac': '/', '==': '=', '!==': '≠=',
};

/**
 * How many operands a function takes from the stack when it is *not*
 * applied to a group. Functions written with a single argument are
 * completed with defaults in normalize(): `round(x)` and `der(f)`.
 */
const SINGLE_ARGUMENT = new Set(['round', 'der']);

const isFunction = (token) => isCustomFunction(token) || PARSE_PRECEDENCE[token] === 100;

/**
 * @param {string[]} raw raw postfix from toRawPostfix()
 * @returns {object} expression tree in standard form; throws on bad input
 */
export function buildTree(raw) {
    const stack = [];   // tree nodes, plus { list: [...] } for comma lists

    const pop = (token) => {
        if (!stack.length) throw new Error(`'${token}' is missing an operand`);
        return stack.pop();
    };
    const items = (entry) => (entry.list ? entry.list : [entry]);
    const node = (entry, token) => {
        if (entry.list) throw new Error(`A list of values needs brackets around it (near '${token}')`);
        return entry;
    };

    raw.forEach((token, index) => {
        if (token === EMPTY_LIST) {
            stack.push({ list: [] });
            return;
        }
        if (token === ',') {
            const right = pop(token);
            const left = pop(token);
            stack.push({ list: [...items(left), ...items(right)] });
            return;
        }
        if (GROUPS.has(token)) {
            const members = items(pop(token));
            // Empty brackets only mean something as a call's argument list: f().
            if (!members.length && !isFunction(raw[index + 1])) throw new Error('Empty brackets');
            stack.push(op(token, members));
            return;
        }

        const name = RENAMES[token] ?? token;
        const def = operator(name);
        if (!def) {
            if (token === '?' || token === 'abs(') throw new Error(`Unmatched '${token[0]}'`);
            stack.push(leaf(token));
            return;
        }

        let args;
        const appliedToGroup = isFunction(token) && GROUPS.has(raw[index - 1]) && stack[stack.length - 1]?.op === raw[index - 1];
        if (appliedToGroup) {
            args = stack.pop().args;
        } else {
            let count = def.arity === VARIADIC || SINGLE_ARGUMENT.has(name) ? 1 : def.arity;
            if (stack.length < count) {
                throw new Error(`'${token}' needs ${count} operand${count === 1 ? '' : 's'}`);
            }
            args = stack.splice(stack.length - count, count).map((e) => node(e, token));
        }
        stack.push(normalize(name, args));
    });

    if (stack.length !== 1) {
        throw new Error(stack.length ? 'Some values are not connected by an operator' : 'Empty expression');
    }
    return node(stack[0], 'end');
}

/** Resolve one operator application to its standard form. */
function normalize(name, args) {
    switch (name) {
        case 'sqrt':
            if (args.length === 2) return op('root', args);       // sqrt[n]{x} arrives as sqrt(n, x)
            break;
        case 'round':
            if (args.length === 1) return op('round', [args[0], num(0)]);
            break;
        case 'der':
            if (args.length === 1) return op('der', [args[0], sym('x')]);
            if (args.length === 3) return nthDerivative(args);
            break;
        case 'log':
            if (args[0].type === 'symbol' && args[0].value === 'e') return op('ln', [args[1]]);
            break;
        case 'lim':
            return op('lim', oneSided(args));
        case '\\:if':   // IF(condition, value, otherwise) — without the third, the value is `unchanged`
            if (args.length === 2 || args.length === 3) return op('?:', [args[0], args[1], args[2] ?? sym('unchanged')]);
            throw new Error('if() takes a condition, a value, and optionally an alternative');
    }
    checkArity(name, args);
    return op(name, args);
}

/**
 * x→0^+ is a one-sided limit: lim(f, x→a^+) and lim(f, x, a^+) become
 * lim(f, x, a, r) — and l for a^-.
 */
function oneSided(args) {
    const side = (n) => (n.type === 'op' && n.op === '^' && n.args[1].type === 'symbol'
        ? { '\\+': 'r', '\\-': 'l' }[n.args[1].value] : undefined);
    const [f, second, third] = args;
    if (args.length === 2 && second.type === 'op' && second.op === '→' && side(second.args[1])) {
        const [x, a] = second.args;
        return [f, x, a.args[0], sym(side(a))];
    }
    if (args.length === 3 && side(third)) return [f, second, third.args[0], sym(side(third))];
    return args;
}

/** der(f, x, n) for a whole number n is d/dx applied n times. */
function nthDerivative([f, x, n]) {
    const times = n.type === 'number' ? Number(n.value) : NaN;
    if (!Number.isInteger(times) || times < 1 || times > 20) {
        throw new Error('der(f, x, n) needs n to be a whole number from 1 to 20');
    }
    let result = f;
    for (let i = 0; i < times; i++) result = op('der', [result, x]);
    return result;
}

function checkArity(name, args) {
    const { arity } = operator(name);
    if (arity === VARIADIC) {
        // Only a user's own function can be called with nothing: f().
        if (args.length === 0 && !isCustomFunction(name)) throw new Error(`'${name}' needs at least one argument`);
        return;
    }
    if (args.length !== arity) {
        const s = arity === 1 ? '' : 's';
        throw new Error(`'${name}' takes ${arity} argument${s}, not ${args.length}`);
    }
}
