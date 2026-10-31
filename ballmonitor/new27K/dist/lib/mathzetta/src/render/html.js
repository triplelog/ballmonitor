/**
 * Tree → plain HTML: nested <span>s, laid out with CSS. No KaTeX, no
 * MathML; good enough for a spreadsheet cell, a game UI or a worked step,
 * and every part of it can be styled or clicked.
 *
 * Every node is one element:
 *
 *   <span class="mz-node mz-op mz-op-add" data-node="4" data-op="+">
 *     <span class="mz-node mz-number" data-node="0">3</span>
 *     <span class="mz-sym">+</span>
 *     <span class="mz-node mz-symbol" data-node="1">x</span>
 *   </span>
 *
 * `data-node` is the node id — the index of its token in the postfix, the
 * same number MathML puts in `id="mz-4"` and the id map of toUnified()
 * uses. So:
 *
 *   colour a part      [data-node="4"] { color: red }
 *   find what was      element.closest('[data-node]').dataset.node
 *   clicked
 *   style by kind      .mz-number, .mz-symbol, .mz-op-frac, .mz-fn
 *
 * Brackets, operator signs and other decoration have classes (mz-paren,
 * mz-sym, mz-fn) but no data-node; a click on them reaches the node that
 * drew them. The stylesheet the markup needs is exported as HTML_STYLES.
 */

import {
    GREEK, needsBrackets, unaryNeedsBrackets, isMinusOneTimes, isImplicitProduct,
    isVariable, firstLeaf, customName, derivativeOrder, bracketedSides, bracketOp,
} from '../common.js';
import { firstVariable } from '../tree.js';
import { isCustomFunction, precedenceOf } from '../operators.js';

/**
 * @param {object} node expression tree
 * @param {object} [options]
 * @param {string} [options.classPrefix] default 'mz'
 * @param {(node: object) => Record<string, string>} [options.attributes]
 *   extra attributes for a node's element, e.g. () => ({ tabindex: '0' })
 * @returns {string} `<span class="mz">…</span>`
 */
export function toHtml(node, options = {}) {
    const p = options.classPrefix || 'mz';
    const extra = options.attributes || (() => ({}));
    const out = new Renderer(p, extra).render(node);
    return `<span class="${p}">${out}</span>`;
}

const escape = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** A readable class name for each operator, so CSS can target `.mz-op-frac`. */
const OP_CLASS = {
    '+': 'add', '-': 'sub', '*': 'mul', '/': 'frac', '^': 'pow', '_': 'subscript', 'neg': 'neg', 'pm': 'pm',
    '!': 'factorial', '=': 'eq', '===': 'eq', '≠': 'neq', '≠=': 'neq', '<': 'lt', '>': 'gt', '≤': 'le', '≥': 'ge',
    '≈': 'approx', '≡': 'equiv', '∈': 'in', '∉': 'notin', '∪': 'union', '∩': 'intersect', '→': 'to', '±': 'pm',
    '&': 'and', '|': 'or', '\\not': 'not', '\\xor': 'xor', '\\nand': 'nand', '\\nor': 'nor', '?:': 'ternary',
    '()': 'tuple', '[]': 'list', '{}': 'set', '(]': 'interval', '[)': 'interval',
    '\\sumidx': 'sum', '\\prodidx': 'prod', 'mod': 'mod', 'pmod': 'pmod',
};

const SIGNS = {
    '=': '=', '===': '=', '≠': '≠', '≠=': '≠', '<': '<', '>': '>', '≤': '≤', '≥': '≥',
    '∈': '∈', '∉': '∉', '→': '→', '±': '±', '≈': '≈', '∪': '∪', '∩': '∩', '≡': '≡', 'mod': 'mod',
    '&': '∧', '|': '∨', '\\xor': '⊕', '\\nand': '↑', '\\nor': '↓',
};

const NAMED = {
    sin: 'sin', cos: 'cos', tan: 'tan', csc: 'csc', sec: 'sec', cot: 'cot',
    sinh: 'sinh', cosh: 'cosh', tanh: 'tanh', arcsin: 'arcsin', arccos: 'arccos', arctan: 'arctan',
    arcsinh: 'arcsinh', arccosh: 'arccosh', arctanh: 'arctanh', atan2: 'atan2',
    ln: 'ln', max: 'max', min: 'min', gcd: 'gcd', mean: 'mean', round: 'round', expm1: 'expm1', random: 'random',
};

const GROUPS = { '()': ['(', ')'], '[]': ['[', ']'], '{}': ['{', '}'], '(]': ['(', ']'], '[)': ['[', ')'] };
const BLACKBOARD = { 'ℝ': 'ℝ', 'ℕ': 'ℕ', 'ℤ': 'ℤ', 'ℚ': 'ℚ', 'ℂ': 'ℂ' };
const MINUS = '−';

class Renderer {
    constructor(prefix, extra) {
        this.p = prefix;
        this.extra = extra;
    }

    /** An element of class `mz-<kind>`. */
    tag(kind, content, attrs = {}) {
        const classes = [`${this.p}-${kind}`].concat(attrs.class ? [attrs.class] : []).join(' ');
        const rest = Object.entries(attrs).filter(([k]) => k !== 'class').map(([k, v]) => ` ${k}="${escape(v)}"`).join('');
        return `<span class="${classes}"${rest}>${content}</span>`;
    }

    sym(s) { return this.tag('sym', escape(s)); }
    /** A sign in front of something: no gap after it. */
    sign(s) { return this.tag('sign', escape(s)); }
    paren(s) { return this.tag('paren', escape(s)); }
    fenced(content, open = '(', close = ')') { return this.paren(open) + content + this.paren(close); }

    /** The element for a node: carries its id and kind, plus the caller's attributes. */
    nodeTag(node, kinds, content) {
        const attrs = { ...this.extra(node), class: kinds.map((k) => `${this.p}-${k}`).join(' ') };
        if (node.id !== undefined) attrs['data-node'] = String(node.id);
        if (node.type === 'op') attrs['data-op'] = node.op;
        return this.tag('node', content, attrs);
    }

    render(node) {
        if (node.type === 'number') return this.nodeTag(node, ['number'], escape(node.value.replace(/^-/, MINUS)));
        if (node.type === 'string') return this.nodeTag(node, ['string'], escape(node.value));
        if (node.type === 'symbol') return this.nodeTag(node, ['symbol'], this.symbol(node.value));
        return this.operation(node);
    }

    symbol(v) {
        if (GREEK[v]) return GREEK[v];
        if (v === '\\+' || v === '\\-') return v[1];
        if (v === '-∞') return MINUS + '∞';
        if (BLACKBOARD[v]) return v;
        if (/^[A-Za-z]{2,}$/.test(v)) return this.tag('name', escape(v));   // upright, like \mathrm
        if (/^[A-Za-z]′+$/.test(v)) return escape(v);
        return escape(v.replace('⁻¹', '')) + (v.endsWith('⁻¹') ? this.tag('sup', MINUS + '1') : '');
    }

    operation(node) {
        const { op, args } = node;
        const [a, b] = args;
        const r = (n) => this.render(n);
        const side = (child, s) => (needsBrackets(node, child, s) && child.op !== '/' ? this.fenced(r(child)) : r(child));
        const unary = (child) => (unaryNeedsBrackets(op, child) ? this.fenced(r(child)) : r(child));
        const kinds = ['op', `op-${OP_CLASS[op] ?? (/^[a-z0-9]+$/i.test(op) ? op : 'other')}`];
        const wrap = (content) => this.nodeTag(node, kinds, content);
        const call = (name) => wrap(this.tag('fn', escape(name)) + this.fenced(args.map(r).join(this.sym(','))));

        if (NAMED[op]) return call(NAMED[op]);
        if (isCustomFunction(op)) {
            const name = customName(op);
            // f(x), g′(x): a one-letter function is italic like a variable; sgn(x) is upright.
            const kind = /^[A-Za-z]′*(⁻¹)?$/.test(name) ? 'symbol' : 'fn';
            return wrap(this.tag(kind, this.symbol(name)) + this.fenced(args.map(r).join(this.sym(','))));
        }
        if (GROUPS[op]) return wrap(this.fenced(args.map(r).join(this.sym(',')), ...GROUPS[op]));
        if (SIGNS[op] && args.length === 2) return wrap(side(a, 'left') + this.sym(SIGNS[op]) + side(b, 'right'));

        switch (op) {
            case '+':
                return wrap(side(a, 'left') + (isMinusOneTimes(b) ? '' : this.sym('+')) + side(b, 'right'));
            case '-':
                return wrap(side(a, 'left') + this.sym(isMinusOneTimes(b) ? '+' : MINUS) + side(b, 'right'));
            case '*': {
                if (isMinusOneTimes(node)) return wrap(this.sign(MINUS) + r(b));
                const times = isImplicitProduct(a, b, bracketedSides(node)) ? this.tag('times', '') : this.sym('·');
                return wrap(side(a, 'left') + times + side(b, 'right'));
            }
            case '/':
                return wrap(this.tag('num', r(a)) + this.tag('den', r(b)));
            case '^': {
                const bracketBase = needsBrackets(node, a, 'left') || (a.type === 'number' && a.value.startsWith('-'));
                return wrap((bracketBase ? this.fenced(r(a)) : r(a)) + this.tag('sup', r(b)));
            }
            case '_':
                return wrap(r(a) + this.tag('sub', r(b)));
            case 'neg':
                return wrap(this.sign(MINUS) + unary(a));
            case 'pm':
                return wrap(this.sign('±') + unary(a));
            case '!':
                return wrap(unary(a) + this.sym('!'));
            case '\\not':
                return wrap(this.sign('¬') + unary(a));
            case 'pmod':
                return wrap(r(a) + this.paren('(') + this.sym('mod') + r(b) + this.paren(')'));
            case 'sqrt':
                return wrap(this.tag('radical', '√') + this.tag('radicand', r(a)));
            case 'root':
                return wrap(this.tag('index', r(a)) + this.tag('radical', '√') + this.tag('radicand', r(b)));
            case 'abs':
                return wrap(this.sym('|') + r(a) + this.sym('|'));
            case 'floor':
                return wrap(this.sym('⌊') + r(a) + this.sym('⌋'));
            case 'ceil':
                return wrap(this.sym('⌈') + r(a) + this.sym('⌉'));
            case 'log':
                return wrap(this.tag('fn', 'log') + this.tag('sub', r(a)) + this.fenced(r(b)));
            case 'loglog':
                return wrap(this.tag('fn', 'ln') + this.fenced(this.tag('fn', 'ln') + this.fenced(r(a))));
            case 'logloglog':
                return wrap(this.tag('fn', 'ln') + this.fenced(this.tag('fn', 'ln') + this.fenced(this.tag('fn', 'ln') + this.fenced(r(a)))));
            case 'perm':
                return wrap(this.tag('sup', r(a)) + this.tag('fn', 'P') + this.tag('sub', r(b)));
            case 'comb':
                return wrap(this.fenced(this.tag('frac', this.tag('num', r(a)) + this.tag('den', r(b), { class: `${this.p}-den-bare` }))));
            case '?:':
                return wrap(r(a) + this.sym('?') + r(b) + this.sym(':') + r(args[2]));
            case 'sum':
                return wrap(args.map(r).join(this.sym('+')));
            case 'prod':
                return wrap(args.map(r).join(this.sym('·')));
            case 'der':
                return wrap(this.derivative(node));
            case 'int':
                return wrap(this.integral(args));
            case 'lim':
                return wrap(this.limit(args));
            case '\\sumidx':
                return wrap(this.bigOperator('∑', args));
            case '\\prodidx':
                return wrap(this.bigOperator('∏', args));
        }
        throw new Error(`No HTML for '${op}'`);
    }

    /** dy/dx, d²y/dx², and d/dx [f] with the body after the fraction. */
    derivative(node) {
        const { n, body, by, variable } = derivativeOrder(node);
        const power = n > 1 ? this.tag('sup', String(n)) : '';
        const d = this.tag('name', 'd');
        const dx = d + this.render(by) + power;
        const fraction = (top) => this.tag('num', top) + this.tag('den', dx);
        if (variable) return this.tag('frac', fraction(d + power + this.render(body)));
        // d/dx [x² + 1] gets brackets; d/dx sin x doesn't — the same rule as LaTeX.
        const compound = bracketOp(body) && precedenceOf(bracketOp(body)) < 100;
        const inner = compound ? this.fenced(this.render(body), '[', ']') : this.render(body);
        return this.tag('frac', fraction(d + power)) + inner;
    }

    /** ∫ with limits stacked above and below the sign, then the integrand and dx. */
    integral(args) {
        const [f, second, third, fourth] = args;
        const r = (n) => this.render(n);
        const dx = (v) => this.tag('name', 'd') + v;
        const guess = () => this.tag('symbol', escape(firstVariable(f) || 'x'));
        const sign = (lo, hi) => this.big('∫', lo, hi);
        switch (args.length) {
            case 1: return sign() + r(f) + dx(guess());
            case 2: return isVariable(second) ? sign() + r(f) + dx(r(second)) : sign(r(second)) + r(f) + dx(guess());
            case 3: return isVariable(second) ? sign(r(third)) + r(f) + dx(r(second)) : sign(r(second), r(third)) + r(f) + dx(guess());
            default: return sign(r(third), r(fourth)) + r(f) + dx(r(second));
        }
    }

    limit(args) {
        const [f, second, third, fourth] = args;
        const r = (n) => this.render(n);
        const under = (content) => this.big('lim', content) + r(f);
        switch (args.length) {
            case 1: return this.tag('fn', 'lim') + r(f);
            case 2: {
                const v = firstVariable(f);
                const approaches = second.type === 'number' || (second.type === 'symbol' && second.value.includes('∞'));
                return under(v && approaches ? this.tag('symbol', escape(v)) + this.sym('→') + r(second) : r(second));
            }
            case 3: return under(r(second) + this.sym('→') + r(third));
            default: {
                const sideSign = firstLeaf(fourth).toLowerCase().startsWith('r') ? '+' : MINUS;
                return under(r(second) + this.sym('→') + r(third) + this.tag('sup', sideSign));
            }
        }
    }

    bigOperator(symbol, args) {
        const [f, from, to] = args;
        const r = (n) => this.render(n);
        if (args.length === 1) return this.big(symbol) + r(f);
        if (args.length === 2) return this.big(symbol, r(from)) + r(f);
        return this.big(symbol, r(from), r(to)) + r(f);
    }

    /** A big operator sign with optional limits below and above it. */
    big(symbol, below = '', above = '') {
        const isWord = /^[a-z]+$/.test(symbol);
        return this.tag('big',
            (above ? this.tag('above', above) : '') +
            this.tag(isWord ? 'fn' : 'bigsym', escape(symbol)) +
            (below ? this.tag('below', below) : ''));
    }
}

/**
 * The stylesheet toHtml's markup needs. Put it on the page once:
 *   <style>${HTML_STYLES}</style>
 * Colours are left to the page: `[data-node="3"] { color: … }`.
 */
export const HTML_STYLES = `
.mz { display: inline-block; font-family: "Times New Roman", "STIX Two Math", serif; font-size: 1.15em; line-height: 1.3; white-space: nowrap; }
.mz .mz-node { display: inline-block; vertical-align: middle; }
.mz .mz-symbol { font-style: italic; }
.mz .mz-name, .mz .mz-fn { font-style: normal; }
.mz .mz-string { font-family: inherit; font-style: normal; }
.mz .mz-sym { margin: 0 0.18em; }
.mz .mz-sign { margin-right: 0.02em; }
.mz .mz-paren { margin: 0 0.05em; }
.mz .mz-fn { margin-right: 0.08em; }
.mz .mz-times { display: inline-block; width: 0.08em; }
.mz .mz-op-frac, .mz .mz-frac { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 0.15em; }
.mz .mz-num, .mz .mz-den { display: block; padding: 0 0.15em; text-align: center; line-height: 1.2; }
.mz .mz-den { border-top: 0.06em solid currentColor; }
.mz .mz-den-bare { border-top: none; }
.mz .mz-sup, .mz .mz-sub, .mz .mz-index { font-size: 0.7em; line-height: 1; }
.mz .mz-sup { vertical-align: 0.55em; }
.mz .mz-sub { vertical-align: -0.3em; }
.mz .mz-index { vertical-align: 0.7em; margin-right: -0.3em; }
.mz .mz-radical { font-size: 1.1em; }
.mz .mz-radicand { border-top: 0.06em solid currentColor; padding: 0 0.1em; }
.mz .mz-big { display: inline-flex; flex-direction: column; align-items: center; vertical-align: middle; margin: 0 0.15em; line-height: 1; }
.mz .mz-bigsym { font-size: 1.6em; }
.mz .mz-above, .mz .mz-below { font-size: 0.65em; }
.mz .mz-above { margin-bottom: 0.1em; }
.mz .mz-below { margin-top: 0.1em; }
`.trim();
