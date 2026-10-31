/**
 * The parser: infix tokens → raw postfix, by precedence climbing (a Pratt
 * parser). Each operator has a binding power (its precedence from
 * vocabulary.js); an expression keeps absorbing operators that bind more
 * tightly than the context it was started in.
 *
 * Raw postfix is postfix with two things left for build.js to settle:
 * commas are still binary "list" operators, and a bracket pair that held
 * commas becomes a group token (`()`, `[]`, `{}`, `(]`, `[)`) — so
 * `max(1,2,3)` comes out as `1 2 , 3 , () max`.
 *
 * The rules that make it read like a person would:
 *
 *   Implicit multiplication. Two things side by side multiply: 2x, xy,
 *   (x+1)(x-2), x sin x, |a||b|. It binds like `*` and `/`, so 1/2x is
 *   (1/2)·x and 2x/3 is (2x)/3.
 *
 *   Function calls and bare functions. `sin(x)` applies to its brackets
 *   only, so sin(x)^2 = (sin x)^2 and sin(x)cos(x) multiplies two calls.
 *   Without brackets, a function takes the product that follows it, up to
 *   the next function or a + - * / or comparison: sin 2x = sin(2x),
 *   sin x^2 = sin(x^2), sin x cos x = sin(x)·cos(x), sin x/x = (sin x)/x.
 *   A power written on the name, sin^2 x, applies to the result.
 *
 *   Signs. `-` and `+` at the start, after `(` or after an operator are
 *   signs; -x^2 = -(x^2), and a minus on a number folds into it (-5).
 *   A lone sign in a bracket or exponent, as in x^+ or {-}, is kept as the
 *   symbol `\+` / `\-`.
 *
 *   Bars. `|` opens an absolute value where an operand is expected and
 *   closes one where an operator is expected. Outside an absolute value it
 *   means "or" — unless an even number of bars remain, in which case it
 *   starts another absolute value: |a||b| = |a|·|b|, a|b = a or b.
 *
 *   `!` is a factorial after an operand and logical not before one.
 */

import { PARSE_PRECEDENCE, RIGHT_ASSOCIATIVE, OPENERS, CLOSERS, isNumber, isOperatorWord } from './vocabulary.js';
import { isCustomFunction, CUSTOM_PREFIX, operator } from '../operators.js';
import { tokenize } from './tokenize.js';
import { FUNCTION_LETTERS } from './words.js';

// Binding powers that aren't operator tokens of their own.
const IMPLICIT = 70;        // side-by-side multiplication: like * and /
const SIGN = 75;            // unary minus: tighter than *, looser than ^
const NOT = 85;             // logical not
const FUNCTION = 100;

/** `%` between operands: the programming remainder, which binds like * and /. */
const PERCENT_MOD = '%mod';

/** Raw token for an empty argument list, as in f(): build.js turns it into no arguments. */
export const EMPTY_LIST = '∅';

const isOpener = (t) => OPENERS.includes(t);
const isCloser = (t) => CLOSERS.includes(t);

/** Words that take an argument: sin, log, max, \:f, ... */
const isFunction = (t) => isCustomFunction(t) || (PARSE_PRECEDENCE[t] === FUNCTION && t !== '_');

/** Words written between their operands instead of before them. */
const INFIX_FUNCTIONS = new Set(['\\comb', '\\perm', 'comb', 'perm']);

/** Prefix words that take two {groups}: \frac{a}{b}, \binom{n}{k}. */
const TWO_GROUPS = { frac: '/', '\\binom': '\\binom' };

/** Words the parser renames once it has finished. */
const RENAMES = { '\\comb': 'comb', '\\perm': 'perm', 'deg': '°', 'π': 'pi', '∨': '|' };

/**
 * @param {string[]} input infix tokens from tokenize()
 * @returns {string[]} raw postfix
 */
export function toRawPostfix(input, mode = 'plain') {
    return new Parser(expandOperands(input, mode)).parseAll().map((t) => RENAMES[t] ?? t);
}

class Parser {
    constructor(tokens) {
        this.tokens = tokens;
        this.pos = 0;
        this.out = [];
        this.absDepth = 0;
        this.frames = [];   // one per open bracket: did it hold a comma?
    }

    peek(offset = 0) { return this.tokens[this.pos + offset]; }
    next() { return this.tokens[this.pos++]; }
    emit(...tokens) { this.out.push(...tokens); }

    parseAll() {
        if (!this.tokens.length) throw new Error('Empty expression');
        this.parseExpression(0);
        const t = this.peek();
        if (t !== undefined) throw new Error(isCloser(t) ? `Unmatched '${t}'` : `Unexpected '${t}'`);
        return this.out;
    }

    /** Parse whatever binds more tightly than `rbp`. `bare`: a function's unbracketed argument. */
    parseExpression(rbp, bare = false) {
        this.parseOperand();
        for (;;) {
            const t = this.peek();
            if (t === undefined || isCloser(t)) return;
            const step = this.operatorAt(t, bare);
            if (!step || step.lbp <= rbp) return;
            step.run();
        }
    }

    /** What to do with the token at an operator position, or null to stop. */
    operatorAt(t, bare) {
        if (t === '|') return this.pipe();
        if (t === ',') {
            return {
                lbp: 5,
                run: () => {
                    this.next();
                    if (this.frames.length) this.frames[this.frames.length - 1].comma = true;
                    this.parseExpression(5);
                    this.emit(',');
                },
            };
        }
        if (t === '?') return { lbp: 9, run: () => this.ternary() };
        if (t === 'mod') return { lbp: PARSE_PRECEDENCE.mod, run: () => this.modulo() };
        if (t === PERCENT_MOD) {
            return { lbp: IMPLICIT, run: () => { this.next(); this.parseExpression(IMPLICIT); this.emit('mod'); } };
        }
        if (t === 'pmod') return { lbp: PARSE_PRECEDENCE.pmod, run: () => { this.next(); this.parseScript(); this.emit('pmod'); } };
        if (t === '?:') return { lbp: 10, run: () => { throw new Error("Unmatched ':'"); } };
        if (t === '!') return { lbp: 90, run: () => { this.next(); this.emit('!'); } };
        if (t === '_') return { lbp: FUNCTION, run: () => { this.next(); this.parseScript(); this.emit('_'); } };
        if (INFIX_FUNCTIONS.has(t)) {
            return { lbp: FUNCTION, run: () => { this.next(); this.parseExpression(FUNCTION); this.emit(t); } };
        }
        const prec = PARSE_PRECEDENCE[t];
        if (prec !== undefined && !isFunction(t) && t !== '\\not' && !(t in TWO_GROUPS)) {
            const rbp = RIGHT_ASSOCIATIVE.has(t) ? prec - 1 : prec;
            return { lbp: prec, run: () => { this.next(); this.parseExpression(rbp); this.emit(t); } };
        }
        if (this.startsOperand(t)) return this.implicit(t, bare);
        return null;
    }

    /** Side by side: multiply. Inside a bare argument, keep going unless a new function starts. */
    implicit(t, bare) {
        const lbp = bare && !isFunction(t) ? IMPLICIT + 1 : IMPLICIT;
        return { lbp, run: () => { this.parseExpression(IMPLICIT); this.emit('*'); } };
    }

    startsOperand(t) {
        if (t === undefined || isCloser(t) || t === '|') return t === '|';
        if (t === PERCENT_MOD) return false;
        if (isOpener(t) || isFunction(t) || t in TWO_GROUPS) return true;
        return !isOperatorWord(t);
    }

    /** A `|` where an operator is expected. */
    pipe() {
        if (this.absDepth > 0) return null;   // it closes the absolute value
        let remaining = 0;
        for (let i = this.pos; i < this.tokens.length; i++) if (this.tokens[i] === '|') remaining++;
        const double = this.peek(1) === '|';
        if (remaining % 2 === 0 && !double && this.startsOperand(this.peek(1))) {
            return this.implicit('|', false);   // |a||b|: a second absolute value
        }
        return {
            lbp: PARSE_PRECEDENCE['|'],
            run: () => {
                this.next();
                if (double && remaining % 2 === 0) this.next();   // `||` written for "or"
                this.parseExpression(PARSE_PRECEDENCE['|']);
                this.emit('|');
            },
        };
    }

    /**
     * `mod` as written in maths: everything to its left (back to an = or a
     * comparison) and one factor to its right. 2 + 3 mod 4 = (2+3) mod 4,
     * c = m^e mod n, a mod 2n = a mod (2n), (2 mod 3)·4, (3 mod tan x) + 4.
     */
    modulo() {
        this.next();
        this.parseExpression(IMPLICIT, true);
        this.emit('mod');
    }

    ternary() {
        this.next();                       // ?
        this.parseExpression(10);          // the cleaner has bracketed the middle part
        if (this.next() !== '?:') throw new Error("Unmatched '?'");
        this.parseExpression(8);
        this.emit('?:');
    }

    /** Something that stands on its own: a number, a bracket, a function call, ... */
    parseOperand() {
        const t = this.next();
        const prev = this.tokens[this.pos - 2];
        const after = this.peek();

        if (t === undefined) throw new Error('An operator is missing an operand at the end');
        // After ∈ or ∉, {…} is a set even with one element: x ∉ {0}.
        if (isOpener(t)) return this.bracket(t, t === '{' && (prev === '∈' || prev === '∉'));
        if (t === '|') return this.absolute();
        if (t === '-' || t === '+') {
            const lone = (prev === '^' && (after === undefined || isCloser(after))) || (isOpener(prev) && isCloser(after));
            if (lone) return this.emit('\\' + t);
            if (t === '+') return this.parseExpression(SIGN);
            return this.negate();
        }
        if (t === '±') {   // ±√3
            this.parseExpression(SIGN);
            return this.emit('pm');
        }
        if (t === '!' || t === '\\not') {
            this.parseExpression(NOT);
            return this.emit('\\not');
        }
        if (t in TWO_GROUPS) {
            this.parseScript();
            this.parseScript();
            return this.emit(TWO_GROUPS[t]);
        }
        if (t === 'log') return this.logarithm();
        if (t === 'lim' && after === '_') return this.limit();
        if ((t === '\\sumidx' || t === '\\prodidx') && after === '_') return this.bigOperator(t);
        if (isFunction(t)) return this.functionCall(t);
        if (isCloser(t) || isOperatorWord(t)) {
            throw new Error(`'${t}' is missing an operand`);
        }
        this.emit(t);
    }

    negate() {
        const start = this.out.length;
        this.parseExpression(SIGN);
        const operand = this.out.slice(start);
        if (operand.length === 1 && (isNumber(operand[0]) || operand[0] === '∞')) {
            this.out[start] = '-' + operand[0];
        } else {
            this.emit('neg');
        }
    }

    /** ( ... ) [ ... ] { ... }: a grouping, or a tuple/list/set/interval if it has commas. */
    bracket(opener, alwaysGroup = false) {
        if (isCloser(this.peek())) {   // (): an empty list, for calls like f()
            this.emit(EMPTY_LIST, opener + this.next());
            return;
        }
        this.frames.push({ comma: false });
        this.parseExpression(0);
        const { comma } = this.frames.pop();
        const closer = this.peek();
        if (isCloser(closer)) {
            this.next();
            if (comma) this.emit(opener + closer);
            else if (alwaysGroup) this.emit('{}');
        }
    }

    absolute() {
        this.absDepth++;
        this.parseExpression(0);
        this.absDepth--;
        if (this.peek() === '|') this.next();
        this.emit('abs');
    }

    /** A single token or a bracketed group: exponents, subscripts, \frac's parts. */
    parseScript() {
        const t = this.peek();
        if (isOpener(t)) return this.parseOperand();
        if (t === '-' || t === '+') return this.parseOperand();
        if (isFunction(t)) return this.parseOperand();
        this.next();
        if (t === undefined || isCloser(t) || isOperatorWord(t)) throw new Error('Missing a sub- or superscript');
        this.emit(t);
    }

    /** log_b x, log_b(x), log x (base e). */
    logarithm() {
        if (this.peek() === '_') {
            this.next();
            this.parseScript();
        } else {
            this.emit('e');
        }
        this.argument();
        this.emit('log');
    }

    /**
     * lim_{x→a} f: the subscript, then f — everything up to the next + or -
     * (or weaker), so lim (x²-4)/(x-2) is the limit of the whole quotient.
     * Comes out as lim(f, x→a), the same as the call lim(f, x→a).
     */
    limit() {
        this.next();   // _
        const start = this.out.length;
        this.parseScript();
        const approach = this.out.splice(start);
        this.parseExpression(PARSE_PRECEDENCE['+'], true);
        this.emit(...approach, ',', '()', 'lim');
    }

    /**
     * \sum_{i=1}^{n} f and \prod: the bounds, then f — everything up to the
     * next + or -, so \sum f(x_i)Δx sums the whole product.
     * Comes out as \sumidx(f, i=1, n).
     */
    bigOperator(name) {
        this.next();   // _
        const start = this.out.length;
        this.parseScript();
        let bounds = this.out.splice(start);
        if (this.peek() === '^') {
            this.next();
            this.parseScript();
            bounds = [...bounds, ...this.out.splice(start), ','];
        }
        this.parseExpression(PARSE_PRECEDENCE['+'], true);
        this.emit(...bounds, ',', '()', name);
    }

    /** sin x, sin(x), sin^2 x, max(1, 2), \:f(x, y), random(). */
    functionCall(name) {
        if (this.peek() === undefined) return this.emit(name);
        let power = null;
        if (this.peek() === '^') {
            this.next();
            const start = this.out.length;
            this.parseScript();
            power = this.out.splice(start);
        }
        // A function of no arguments (random) only takes brackets, never a bare argument.
        if (operator(name)?.arity === 0 && !isOpener(this.peek())) return this.emit(name);
        this.argument();
        this.emit(name);
        if (power) this.emit(...power, '^');
    }

    /** A function's argument: its brackets if it has them, else the bare product that follows. */
    argument() {
        const t = this.peek();
        if (isOpener(t)) {
            this.next();
            return this.bracket(t);
        }
        this.parseExpression(IMPLICIT, true);
    }
}

/**
 * Split operand tokens the tokenizer left whole: `4x` → 4 x, `10%3` →
 * 10 mod 3, `xy` → x y, `xsinx` → x sin x (see words.js). Multiplication
 * between the pieces is implicit.
 */
function expandOperands(tokens, mode) {
    tokens = functionsOfOneVariable(tokens);
    const out = [];
    for (const t of tokens) {
        if (isOperatorWord(t) || isOpener(t) || isCloser(t) || t === '_' || isCustomFunction(t) || isNumber(t)) {
            out.push(t);
            continue;
        }
        out.push(...splitOperand(t, mode));
    }
    return out;
}

/**
 * x(t), a(t), y(0): a letter applied to a single other letter or a number
 * reads as a function, as in a(t) = v'(t) and y(0) = 1. Anything with more
 * inside the brackets is a product — x(x+1), a(b+c) — as is e(…) and a
 * letter applied to itself, x(x). And f^{-1}(x) is the inverse function f⁻¹.
 */
function functionsOfOneVariable(tokens) {
    const out = [];
    for (let i = 0; i < tokens.length; i++) {
        const t = tokens[i];
        const oneLetter = (s) => typeof s === 'string' && /^[a-zA-Z]$/.test(s);
        // f^{-1}(x): the inverse function
        if (FUNCTION_LETTERS.has(t) && tokens.slice(i + 1, i + 7).join(' ') === '^ { - 1 } (') {
            out.push(CUSTOM_PREFIX + t + '⁻¹');
            i += 5;
            continue;
        }
        const [open, arg, close] = tokens.slice(i + 1, i + 4);
        const simple = oneLetter(arg) ? arg !== t : isNumber(arg);
        if (oneLetter(t) && t !== 'e' && open === '(' && simple && close === ')') {
            out.push(CUSTOM_PREFIX + t);
            continue;
        }
        out.push(t);
    }
    return out;
}

function splitOperand(token, mode) {
    const again = (text) => expandOperands(tokenize(text, mode), mode);
    let end = 0;   // length of a numeric prefix
    while (end < token.length && isNumber(token.slice(0, end + 1))) end++;
    if (end === 0) {
        if (token[0] === '%') return [PERCENT_MOD, ...again(token.slice(1))];
        const percent = token.indexOf('%');   // x%3 → x mod 3
        if (percent > 0 && percent < token.length - 1) {
            return [...splitOperand(token.slice(0, percent), mode), PERCENT_MOD, ...again(token.slice(percent + 1))];
        }
        return [token];
    }
    const rest = token.slice(end);
    if (rest[0] === '%') {
        return rest.length === 1 ? [token] : [token.slice(0, end), PERCENT_MOD, ...again(rest.slice(1))];
    }
    return [token.slice(0, end), ...again(rest)];
}
