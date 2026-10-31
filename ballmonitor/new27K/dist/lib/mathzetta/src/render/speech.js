/**
 * Tree → spoken English, the way a teacher reads an expression aloud:
 *
 *   x^2 + 1               "x squared plus 1"
 *   (x+1)^2               "the quantity x plus 1, squared"
 *   \frac{\sin x}{x}      "sine of x, over x"
 *   \int_0^1 x^2 dx       "the integral from 0 to 1 of x squared, d x"
 *   f'(x) = 2x            "f prime of x equals 2 x"
 *
 * Commas are pauses for a text-to-speech voice, and mark where a group
 * ends: "the quantity x plus 1, squared".
 *
 * Changing how something is said
 * ------------------------------
 * Three layers, from the smallest change to the largest:
 *
 *   words   the connecting words — toSpeech(x, { words: { negative: 'minus' } })
 *           turns "negative 3" into "minus 3". See WORDS below.
 *   names   what a function is called — { names: { ln: 'log' } } says
 *           "log of x" for ln(x). See NAMES.
 *   say     a whole phrase — { say: { sqrt: (parts) => `root ${parts[0]}` } }.
 *           The function gets the operands already spoken, the node, and a
 *           `speak(node)` helper for anything else; it returns the phrase.
 *
 * toSpeechSegments() returns the phrase in pieces, each tagged with the id
 * of the node it belongs to, so a karaoke caption can light up the part of
 * the expression being spoken.
 */

import { isMinusOneTimes, derivativeOrder, customName, GREEK } from '../common.js';
import { operator, isCustomFunction, precedenceOf } from '../operators.js';
import { firstVariable } from '../tree.js';

/** The connecting words. Override any of them with the `words` option. */
export const WORDS = {
    plus: 'plus', minus: 'minus', times: 'times', over: 'over', negative: 'negative', plusOrMinus: 'plus or minus',
    quantity: 'the quantity', of: 'of', and: 'and', or: 'or', not: 'not', xor: 'exclusive or', nand: 'nand', nor: 'nor',
    squared: 'squared', cubed: 'cubed', toThe: 'to the', toThePowerOf: 'to the power of', power: 'power',
    sub: 'sub', factorial: 'factorial', prime: 'prime', doublePrime: 'double prime', triplePrime: 'triple prime',
    inverse: 'inverse', mod: 'mod', percent: 'percent', degrees: 'degrees',
    equals: 'equals', notEqual: 'is not equal to', lessThan: 'is less than', greaterThan: 'is greater than',
    lessOrEqual: 'is less than or equal to', greaterOrEqual: 'is greater than or equal to',
    approx: 'is approximately', congruent: 'is congruent to', approaches: 'approaches', tendsTo: 'approaches',
    isIn: 'is in', isNotIn: 'is not in', union: 'union', intersect: 'intersect',
    squareRoot: 'the square root of', cubeRoot: 'the cube root of', nthRoot: (n) => `the ${n} root of`,
    absoluteValue: 'the absolute value of', floor: 'the floor of', ceiling: 'the ceiling of',
    logBase: 'log base', naturalLog: 'the natural log of', choose: 'choose', permute: 'permute',
    derivative: 'the derivative', secondDerivative: 'the second derivative',
    nthDerivative: (n) => `the ${n} derivative`, withRespectTo: 'with respect to', d: 'd',
    integralOf: 'the integral of', integralFrom: 'the integral from', to: 'to',
    limitAs: 'the limit as', fromTheRight: 'from the right', fromTheLeft: 'from the left',
    sumFrom: 'the sum from', sumOver: 'the sum over', sumOf: 'the sum of',
    productFrom: 'the product from', productOver: 'the product over', productOf: 'the product of',
    theSet: 'the set', theList: 'the list', openInterval: 'the open interval from', closedInterval: 'the closed interval from',
    halfOpenInterval: 'the half-open interval from', comma: ',', if: 'if', then: 'then', otherwise: 'otherwise',
    infinity: 'infinity', pi: 'pi', e: 'e', delta: 'delta', randomNumber: 'a random number',
    rounded: 'rounded to', decimalPlaces: 'decimal places', nearestWholeNumber: 'the nearest whole number',
    reals: 'the real numbers', integers: 'the integers', naturals: 'the natural numbers', rationals: 'the rational numbers',
    complexes: 'the complex numbers', repeating: 'repeating', eToThe: 'e to the',
    // "one half", "two thirds": numerators 1–9 and denominators 2–10 (ordinals[d] names 1/d)
    half: 'half', halves: 'halves', ordinals: ['', '', 'half', 'third', 'quarter', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth'],
    numerators: ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'],
    powers: ['', 'first', 'squared', 'cubed', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth'],
};

/** What functions are called. Override with the `names` option. */
export const NAMES = {
    sin: 'sine', cos: 'cosine', tan: 'tangent', csc: 'cosecant', sec: 'secant', cot: 'cotangent',
    sinh: 'hyperbolic sine', cosh: 'hyperbolic cosine', tanh: 'hyperbolic tangent',
    arcsin: 'inverse sine', arccos: 'inverse cosine', arctan: 'inverse tangent',
    arcsinh: 'inverse hyperbolic sine', arccosh: 'inverse hyperbolic cosine', arctanh: 'inverse hyperbolic tangent',
    ln: 'the natural log', log: 'log', loglog: 'the log of the log', logloglog: 'the log of the log of the log',
    expm1: 'e to the power, minus 1, of', max: 'the maximum', min: 'the minimum', gcd: 'the greatest common divisor',
    mean: 'the mean', atan2: 'the arctangent', round: 'round', random: 'random',
};

/** Greek letters by name: α → "alpha". */
const GREEK_NAMES = Object.fromEntries(Object.entries(GREEK).map(([name, letter]) => [letter, name]));

/**
 * @param {object} node expression tree
 * @param {object} [options] { words, names, say } — see the top of this file
 * @returns {string}
 */
export function toSpeech(node, options = {}) {
    return join(toSpeechSegments(node, options));
}

/**
 * The phrase in pieces: [{ text, id }], where id is the node the words
 * belong to (the operator's own id for "plus", "squared", "the integral
 * from"; a leaf's id for its name).
 */
export function toSpeechSegments(node, options = {}) {
    const speaker = new Speaker({ ...WORDS, ...options.words }, { ...NAMES, ...options.names }, options.say || {});
    return tidy(speaker.speak(node));
}

/**
 * Pauses are emitted as their own ',' pieces while speaking; attach each to
 * the piece before it, drop doubled, leading and trailing ones, and drop
 * empty pieces, so every segment is a word or phrase.
 */
function tidy(segments) {
    const out = [];
    for (const { text, id } of segments) {
        const trimmed = text.trim();
        if (!trimmed) continue;
        const pause = trimmed.startsWith(',');
        const rest = pause ? trimmed.slice(1).trim() : trimmed;
        if (pause && out.length && !out[out.length - 1].text.endsWith(',')) out[out.length - 1].text += ',';
        if (rest) out.push({ text: rest, id });
    }
    if (out.length) out[out.length - 1].text = out[out.length - 1].text.replace(/,$/, '');
    return out;
}

/** Segments → one string: spaces between words, pauses tidied. */
function join(segments) {
    return segments.map((s) => s.text).join(' ')
        .replace(/\s+/g, ' ')
        .replace(/ ,/g, ',')
        .replace(/,(\s*,)+/g, ',')
        .replace(/^,\s*/, '')
        .replace(/,\s*$/, '')
        .trim();
}

const COMPARISONS = {
    '=': 'equals', '===': 'equals', '≠': 'notEqual', '≠=': 'notEqual', '<': 'lessThan', '>': 'greaterThan',
    '≤': 'lessOrEqual', '≥': 'greaterOrEqual', '≈': 'approx', '≡': 'congruent', '→': 'tendsTo',
    '∈': 'isIn', '∉': 'isNotIn', '∪': 'union', '∩': 'intersect', '±': 'plusOrMinus',
    '&': 'and', '|': 'or', '\\xor': 'xor', '\\nand': 'nand', '\\nor': 'nor',
};

const SETS = { 'ℝ': 'reals', 'ℤ': 'integers', 'ℕ': 'naturals', 'ℚ': 'rationals', 'ℂ': 'complexes' };

class Speaker {
    constructor(words, names, say) {
        this.w = words;
        this.names = names;
        this.say = say;
    }

    /** Speak a node as segments. */
    speak(node) {
        const custom = this.say[node.type === 'op' ? node.op : node.type];
        if (custom) {
            const parts = node.type === 'op' ? node.args.map((a) => join(this.speak(a))) : [node.value];
            return [{ text: custom(parts, node, (n) => join(this.speak(n))), id: node.id }];
        }
        if (node.type === 'number') return [this.seg(node, this.number(node.value))];
        if (node.type === 'string') return [this.seg(node, node.value.slice(1, -1))];
        if (node.type === 'symbol') return [this.seg(node, this.symbol(node.value))];
        return this.operation(node);
    }

    seg(node, text) { return { text, id: node.id }; }

    number(v) {
        const w = this.w;
        if (v.endsWith('..')) return `${v.replace(/\.+$/, '')} ${w.repeating}`;
        return v.startsWith('-') ? `${w.negative} ${v.slice(1)}` : v;
    }

    symbol(v) {
        const w = this.w;
        if (v === '∞') return w.infinity;
        if (v === '-∞') return `${w.negative} ${w.infinity}`;
        if (v === 'pi' || v === 'π') return w.pi;
        if (v === 'tau' || v === 'τ') return 'tau';
        if (v === '\\+') return w.plus;
        if (v === '\\-') return w.minus;
        if (v === '°') return w.degrees;
        if (SETS[v]) return w[SETS[v]];
        if (GREEK_NAMES[v]) return GREEK_NAMES[v].toLowerCase();
        if (/^Δ.+$/.test(v)) return `${w.delta} ${this.symbol(v.slice(1))}`;
        const primes = /′+$/.exec(v);
        if (primes) return `${this.symbol(v.slice(0, -primes[0].length))} ${this.primes(primes[0].length)}`;
        if (v.endsWith('⁻¹')) return `${this.symbol(v.slice(0, -2))} ${w.inverse}`;
        return v;
    }

    primes(n) {
        const w = this.w;
        return [w.prime, w.doublePrime, w.triplePrime][n - 1] ?? `${n} ${w.prime}`;
    }

    // ---- grouping -------------------------------------------------------------

    /** Would this node, spoken, run into what follows? Sums, comparisons, conditions. */
    isCompound(node) {
        if (node.type !== 'op') return false;
        if (node.op === 'sum' || node.op === '?:') return true;
        const prec = precedenceOf(node.op);
        return prec !== undefined && prec <= 50 && !operator(node.op).group;
    }

    /** "the quantity x plus 1," — a compound node fenced off with words. */
    quantity(node) {
        if (!this.isCompound(node)) return this.speak(node);
        return [this.seg(node, this.w.quantity), ...this.speak(node), this.seg(node, this.w.comma)];
    }

    /** A function's argument: "x", "2 x", or "the quantity x plus 1,". */
    argument(node) {
        return this.quantity(node);
    }

    // ---- operators --------------------------------------------------------------

    operation(node) {
        const { op, args } = node;
        const [a, b] = args;
        const w = this.w;
        const me = (text) => this.seg(node, text);
        const list = () => args.flatMap((x, i) => (i ? [me(w.comma), ...this.speak(x)] : this.speak(x)));

        if (COMPARISONS[op]) return [...this.speak(a), me(w[COMPARISONS[op]]), ...this.speak(b)];
        if (isCustomFunction(op)) {
            const name = this.symbol(customName(op));
            return args.length ? [me(`${name} ${w.of}`), ...this.arguments(args)] : [me(name)];
        }
        if (this.names[op] && !['log', 'round', 'atan2', 'random', 'expm1'].includes(op)) {
            return [me(`${this.names[op]} ${w.of}`), ...this.arguments(args)];
        }

        switch (op) {
            case '+':
                if (isMinusOneTimes(b)) return [...this.speak(a), me(w.minus), ...this.speak(b.args[1])];
                return [...this.speak(a), me(w.plus), ...this.speak(b)];
            case '-':
                if (isMinusOneTimes(b)) return [...this.speak(a), me(w.plus), ...this.speak(b.args[1])];
                return [...this.speak(a), me(w.minus), ...this.quantityIfSum(b)];
            case '*':
                return this.product(node);
            case '/':
                return this.fraction(node);
            case '^':
                return this.power(node);
            case '_':
                return [...this.speak(a), me(w.sub), ...this.speak(b)];
            case 'neg':
                return this.isCompound(a) || a.type === 'op' && a.op === 'neg'
                    ? [me(`${w.negative} ${w.quantity}`), ...this.speak(a), me(w.comma)]
                    : [me(w.negative), ...this.speak(a)];
            case 'pm':
                return [me(w.plusOrMinus), ...this.speak(a)];
            case '!':
                return [...this.quantity(a), me(w.factorial)];
            case '\\not':
                return [me(w.not), ...this.quantity(a)];
            case 'sqrt':
                return [me(w.squareRoot), ...this.speak(a), ...this.pauseAfter(a)];
            case 'root': {
                const n = a.type === 'number' ? Number(a.value) : NaN;
                const root = n === 3 ? w.cubeRoot : n === 2 ? w.squareRoot : w.nthRoot(n ? this.ordinal(n) : join(this.speak(a)) + 'th');
                return [me(root), ...this.speak(b), ...this.pauseAfter(b)];
            }
            case 'abs':
                return [me(w.absoluteValue), ...this.speak(a), ...this.pauseAfter(a)];
            case 'floor':
                return [me(w.floor), ...this.speak(a), ...this.pauseAfter(a)];
            case 'ceil':
                return [me(w.ceiling), ...this.speak(a), ...this.pauseAfter(a)];
            case 'log':
                if (a.type === 'symbol' && a.value === 'e') return [me(`${this.names.ln} ${w.of}`), ...this.argument(b)];
                return [me(`${w.logBase}`), ...this.speak(a), me(w.of), ...this.argument(b)];
            case 'mod':
                return [...this.quantity(a), me(w.mod), ...this.quantity(b)];
            case 'pmod':
                return [...this.speak(a), me(`${w.comma} ${w.mod}`), ...this.speak(b)];
            case 'perm':
                return [...this.quantity(a), me(w.permute), ...this.quantity(b)];
            case 'comb':
                return [...this.quantity(a), me(w.choose), ...this.quantity(b)];
            case 'round': {
                const digits = b.type === 'number' ? Number(b.value) : NaN;
                const places = digits === 0 ? w.nearestWholeNumber : `${join(this.speak(b))} ${w.decimalPlaces}`;
                return [...this.speak(a), me(`${w.comma} ${w.rounded} ${places}`)];
            }
            case 'atan2':
                return [me(`${this.names.atan2} ${w.of}`), ...this.speak(a), me(w.over), ...this.speak(b)];
            case 'random':
                return [me(w.randomNumber)];
            case 'expm1':
                return [me(w.eToThe), ...this.speak(a), me(`${w.comma} ${w.minus} 1`)];
            case '?:':
                return [me(w.if), ...this.speak(a), me(`${w.comma} ${w.then}`), ...this.speak(b), me(`${w.comma} ${w.otherwise}`), ...this.speak(args[2])];
            case 'sum':
                return args.flatMap((x, i) => (i ? [me(w.plus), ...this.speak(x)] : this.speak(x)));
            case 'prod':
                return args.flatMap((x, i) => (i ? [me(w.times), ...this.quantity(x)] : this.quantity(x)));
            case 'mean': case 'max': case 'min': case 'gcd':
                return [me(`${this.names[op]} ${w.of}`), ...list()];
            case '()':
                if (args.length === 2) return [me(w.openInterval), ...this.speak(a), me(w.to), ...this.speak(b)];
                return list();
            case '[]':
                if (args.length === 2) return [me(w.closedInterval), ...this.speak(a), me(w.to), ...this.speak(b)];
                return [me(w.theList), ...list()];
            case '(]': case '[)':
                return [me(w.halfOpenInterval), ...this.speak(a), me(w.to), ...this.speak(b)];
            case '{}':
                return [me(w.theSet), ...list()];
            case 'der':
                return this.derivative(node);
            case 'int':
                return this.integral(node);
            case 'lim':
                return this.limit(node);
            case '\\sumidx':
                return this.bigOperator(node, w.sumFrom, w.sumOver, w.sumOf);
            case '\\prodidx':
                return this.bigOperator(node, w.productFrom, w.productOver, w.productOf);
        }
        throw new Error(`No speech for '${op}'`);
    }

    /** The arguments of a call: "x", "2 x", "the quantity x plus 1,", or "a, b, c". */
    arguments(args) {
        if (args.length === 1) return this.argument(args[0]);
        return args.flatMap((x, i) => (i ? [{ text: this.w.comma, id: x.id }, ...this.speak(x)] : this.speak(x)));
    }

    /** A pause after a compound argument so the next words don't join it. */
    pauseAfter(node) {
        return this.isCompound(node) ? [this.seg(node, this.w.comma)] : [];
    }

    quantityIfSum(node) {
        return this.quantity(node);
    }

    /** "2 x", "2 pi r", "x squared sine of x" — or "times" where juxtaposing would mislead. */
    product(node) {
        const [a, b] = node.args;
        const w = this.w;
        if (isMinusOneTimes(node)) return [this.seg(node, w.negative), ...this.speak(b)];
        if (b.type === 'symbol' && b.value === '°') return [...this.speak(a), this.seg(node, w.degrees)];
        const left = this.quantity(a);
        const right = this.quantity(b);
        // "2 x", "2 pi r", "x squared sine of x" read fine; "2 the square root of x",
        // "rate time" and "x 2" don't.
        const needsTimes = this.isCompound(a) || this.isCompound(b) || this.isWord(a) || this.isWord(b)
            || this.startsWithNumber(b) || (b.type === 'op' && b.op === '/') || this.isCall(a)
            || right[0].text.startsWith('the ');
        return needsTimes ? [...left, this.seg(node, w.times), ...right] : [...left, ...right];
    }

    /** A multi-letter name that is a word (rate, speed), not a constant or Greek letter. */
    isWord(node) { return node.type === 'symbol' && /^[A-Za-z]{2,}$/.test(node.value) && !GREEK[node.value] && !['pi', 'tau'].includes(node.value); }
    isCall(node) { return node.type === 'op' && (isCustomFunction(node.op) || (operator(node.op)?.fixity === 'prefix' && precedenceOf(node.op) === 100)); }
    startsWithNumber(node) {
        let n = node;
        while (n.type === 'op' && n.args.length) n = n.args[0];
        return n.type === 'number';
    }

    /** "one half", "x over 2", "the quantity x plus 1, over x minus 1,". */
    fraction(node) {
        const [a, b] = node.args;
        const w = this.w;
        const me = (text) => this.seg(node, text);
        if (a.type === 'number' && b.type === 'number' && /^[1-9]$/.test(a.value) && /^([2-9]|10)$/.test(b.value)) {
            const n = Number(a.value);
            const d = Number(b.value);
            const unit = d === 2 ? (n === 1 ? w.half : w.halves) : w.ordinals[d] + (n === 1 ? '' : 's');
            return [me(`${w.numerators[n]} ${unit}`)];
        }
        const top = this.quantity(a);
        const pause = this.isCall(a) ? [me(w.comma)] : [];
        return [...top, ...pause, me(w.over), ...this.quantity(b)];
    }

    /** "x squared", "e to the 2 x", "x to the n minus 1, power", "the quantity x plus 1, squared". */
    power(node) {
        const [base, exp] = node.args;
        const w = this.w;
        const me = (text) => this.seg(node, text);
        const spokenBase = this.isCompound(base) || this.isCall(base) || (base.type === 'number' && base.value.startsWith('-')) || base.type === 'op' && base.op === '/'
            ? [me(w.quantity), ...this.speak(base), me(w.comma)]
            : this.speak(base);
        // sin^2 x: "sine squared of x"
        if (this.isCall(base) && this.names[base.op] && exp.type === 'number' && /^[2-3]$/.test(exp.value) && base.args.length === 1) {
            const word = Number(exp.value) === 2 ? w.squared : w.cubed;
            return [me(`${this.names[base.op]} ${word} ${w.of}`), ...this.argument(base.args[0])];
        }
        if (exp.type === 'number' && /^(?:[1-9]|10)$/.test(exp.value)) {
            const n = Number(exp.value);
            if (n === 2 || n === 3) return [...spokenBase, me(w.powers[n])];
            return [...spokenBase, me(`${w.toThe} ${w.powers[n]}`)];
        }
        if (exp.type === 'number' && /^\d+$/.test(exp.value)) return [...spokenBase, me(`${w.toThe} ${this.ordinal(Number(exp.value))}`)];
        const simpleExponent = !this.isCompound(exp) && !(exp.type === 'op' && exp.op === '/' && this.isCompound(exp.args[0]));
        if (simpleExponent) return [...spokenBase, me(w.toThe), ...this.speak(exp)];
        return [...spokenBase, me(w.toThePowerOf), ...this.speak(exp), me(w.comma)];
    }

    ordinal(n) {
        if (n <= 10 && n >= 1) return this.w.powers[n] === 'squared' ? 'second' : this.w.powers[n] === 'cubed' ? 'third' : this.w.powers[n];
        const suffix = (n % 100 >= 11 && n % 100 <= 13) ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] ?? 'th';
        return `${n}${suffix}`;
    }

    /** "d y d x", "d squared y d x squared", "the derivative of f with respect to x". */
    derivative(node) {
        const { n, body, by, variable } = derivativeOrder(node);
        const w = this.w;
        const me = (text) => this.seg(node, text);
        if (variable) {
            const d = n === 1 ? w.d : `${w.d} ${n === 2 ? w.squared : n === 3 ? w.cubed : `${w.toThe} ${this.ordinal(n)}`}`;
            return [me(d), ...this.speak(body), me(w.d), ...this.speak(by), me(n === 1 ? '' : (n === 2 ? w.squared : n === 3 ? w.cubed : `${w.toThe} ${this.ordinal(n)}`))];
        }
        const which = n === 1 ? w.derivative : n === 2 ? w.secondDerivative : w.nthDerivative(this.ordinal(n));
        return [me(`${which} ${w.withRespectTo}`), ...this.speak(by), me(w.of), ...this.speak(body), ...this.pauseAfter(body)];
    }

    /** "the integral from 0 to 1 of x squared, d x". */
    integral(node) {
        const { args } = node;
        const [f, second, third, fourth] = args;
        const w = this.w;
        const me = (text) => this.seg(node, text);
        const variableGiven = args.length >= 2 && second.type === 'symbol' && second.value.length === 1;
        const variable = variableGiven ? this.speak(second) : [me(firstVariable(f) || 'x')];
        let bounds = [];
        if (args.length === 4) bounds = [third, fourth];
        else if (args.length === 3) bounds = variableGiven ? [third] : [second, third];
        else if (args.length === 2 && !variableGiven) bounds = [second];
        const head = bounds.length === 2
            ? [me(w.integralFrom), ...this.speak(bounds[0]), me(w.to), ...this.speak(bounds[1]), me(w.of)]
            : bounds.length === 1 ? [me(w.integralFrom), ...this.speak(bounds[0]), me(w.of)] : [me(w.integralOf)];
        return [...head, ...this.speak(f), me(`${w.comma} ${w.d}`), ...variable];
    }

    /** "the limit as x approaches 0 of sine of x, over x". */
    limit(node) {
        const { args } = node;
        const [f, second, third, fourth] = args;
        const w = this.w;
        const me = (text) => this.seg(node, text);
        let approach;
        if (args.length >= 3) {
            approach = [...this.speak(second), me(w.approaches), ...this.speak(third)];
            if (args.length === 4) {
                const right = String(fourth.value ?? '').toLowerCase().startsWith('r');
                approach.push(me(right ? w.fromTheRight : w.fromTheLeft));
            }
        } else if (args.length === 2 && second.type === 'op' && second.op === '→') {
            approach = [...this.speak(second.args[0]), me(w.approaches), ...this.speak(second.args[1])];
        } else if (args.length === 2) {
            const v = firstVariable(f);
            approach = v ? [me(v), me(w.approaches), ...this.speak(second)] : this.speak(second);
        } else {
            return [me(`${w.limitAs.replace(/ as$/, '')} ${w.of}`), ...this.speak(f)];
        }
        return [me(w.limitAs), ...approach, me(w.of), ...this.speak(f), ...this.pauseAfter(f)];
    }

    /** "the sum from i equals 1 to n of i squared". */
    bigOperator(node, from, over, of) {
        const { args } = node;
        const [f, lower, upper] = args;
        const w = this.w;
        const me = (text) => this.seg(node, text);
        let head;
        if (args.length === 3) head = [me(from), ...this.speak(lower), me(w.to), ...this.speak(upper), me(w.of)];
        else if (args.length === 2) head = [me(over), ...this.speak(lower), me(w.of)];
        else head = [me(of)];
        return [...head, ...this.speak(f), ...this.pauseAfter(f)];
    }
}
