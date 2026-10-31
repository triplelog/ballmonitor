/**
 * Programming spellings, rewritten into ones the rest of the cleaner reads:
 * what JavaScript, Python (math, numpy, scipy), SQL and GLSL write for
 * maths — MathZetta's own code outputs among them, so each reads back as the
 * maths it came from (test/unit/roundtrip.test.js).
 *
 *   np.sin(x), np.arctan2(y, x)        Math.sin(x), Math.atan2(y, x)   (then replacements.js)
 *   np.where(c, a, b), a if c else b   ((c) ? (a) : (b))
 *   np.logical_and(a, b), a ^^ b       ((a) & (b)), a \xor b
 *   np.isin(x, [1, 2]), [1, 2].includes(x), contains(S, x), x IN (1, 2)    x ∈ {1, 2}
 *   math.isclose(a, b)                 ((a) ≈ (b))
 *   Number.isInteger(x), float(x).is_integer(), Number.isFinite(x)          x ∈ ℤ, x ∈ ℝ
 *   math.factorial(n), mz_factorial(n), FACTORIAL(n)                        (n)!
 *   sum(f for i in range(1, n + 1))    (\sum_{i=1}^{n} (f))   (and math.prod, and JavaScript's loop)
 *   CASE WHEN c THEN a ELSE b END      ((c) ? (a) : (b))
 *   POWER(x, 2), GREATEST(a, b), LOG(2, x), PI(), a <> b, 9e999            pow(x, 2), max(a, b), log_{2}(x), π, a ≠ b, ∞
 *   mz_sq(x), mz_cube(x), fract(x), atan(y, x)                              (x)^2, (x)^3, x - floor(x), atan2(y, x)
 *   1e-9, a % (b), True, None          (1*10^{-9}), a \mod (b), true, null
 *
 * Runs first, while spaces still separate words (`a if c else b`,
 * `CASE WHEN`), on text whose strings are already placeholders.
 */

import { JS_HELPERS } from '../../js-helpers.js';

const OPEN = '([{';
const CLOSE = ')]}';

/** The index of the bracket closing the one at `open`, or -1. */
function closing(text, open) {
    let depth = 0;
    for (let i = open; i < text.length; i++) {
        if (OPEN.includes(text[i])) depth++;
        else if (CLOSE.includes(text[i]) && --depth === 0) return i;
    }
    return -1;
}

/** Split at commas where no bracket is open. */
function splitArgs(text) {
    if (!text.trim()) return [];
    const args = [];
    let depth = 0;
    let from = 0;
    for (let i = 0; i < text.length; i++) {
        if (OPEN.includes(text[i])) depth++;
        else if (CLOSE.includes(text[i])) depth--;
        else if (text[i] === ',' && depth === 0) {
            args.push(text.slice(from, i).trim());
            from = i + 1;
        }
    }
    args.push(text.slice(from).trim());
    return args;
}

/**
 * Rewrite each call `name(args)` the pattern finds (it must end at the `(`),
 * innermost first. `replace(args, match, after)` returns the new text, or null
 * to leave the call alone; `after` is the text following the call.
 */
function rewriteCalls(text, pattern, replace) {
    const matches = [...text.matchAll(pattern)];
    for (let k = matches.length - 1; k >= 0; k--) {
        const m = matches[k];
        const open = m.index + m[0].length - 1;
        const close = closing(text, open);
        if (close < 0) continue;
        const out = replace(splitArgs(text.slice(open + 1, close)), m, text.slice(close + 1));
        if (out == null) continue;
        const [replacement, consumed = 0] = Array.isArray(out) ? out : [out];
        text = text.slice(0, m.index) + replacement + text.slice(close + 1 + consumed);
    }
    return text;
}

const call = (names) => new RegExp(`(?<![\\w.])(${names})\\s*\\(`, 'g');
const p = (x) => `(${x})`;
const setOf = (list) => (/^\[.*\]$/s.test(list.trim()) ? `{${list.trim().slice(1, -1)}}` : list);

// ---- JavaScript's inline helpers (js-helpers.js) and loops ----------------------

function jsHelpers(text) {
    for (const [name, source] of Object.entries(JS_HELPERS)) {
        for (let at = text.lastIndexOf(source); at >= 0; at = at > 0 ? text.lastIndexOf(source, at - 1) : -1) {
            const open = at + source.length;
            const close = text[open] === '(' ? closing(text, open) : -1;
            if (close < 0) continue;
            let args = text.slice(open + 1, close);
            if (name === 'gcd') args = args.trim().replace(/^\[|\]$/g, '');
            const replacement = name === 'factorial' ? `((${args})!)` : `${name}(${args})`;
            text = text.slice(0, at) + replacement + text.slice(close + 1);
        }
    }
    // (()=>{let sum = 0; … for (let i=1;i<=n;i++) {…; sum += f;}; return sum;})()
    return text.replace(
        /\(\(\)=>\{let (sum|prod) = [01]; let loopCount = 0; for \(let (\w+)=(.*?);\2<=(.*?);\2\+\+\) \{if \(loopCount\+\+ > 1000000\)\{break\};\1 [+*]= (.*?);\}; return \1;\}\)\(\)/g,
        (whole, kind, v, from, to, body) => `(\\${kind === 'sum' ? 'sum' : 'prod'}_{${v}=${from}}^{${to}} (${body}))`);
}

// ---- spreadsheets (a formula starting with =) ---------------------------------------

/** Excel and Sheets functions, by what they are in maths (render/excel.js writes them). */
const SHEET_CALLS = {
    IF: (a) => a.length >= 2 && `((${a[0]}) ? (${a[1]}) : (${a[2] ?? 'false'}))`,
    AND: (a) => a.length && `(${a.map(p).join(' & ')})`,
    OR: (a) => a.length && `(${a.map(p).join(' ∨ ')})`,
    NOT: (a) => a.length === 1 && `(!(${a[0]}))`,
    XOR: (a) => a.length === 2 && `((${a[0]})  \\xor  (${a[1]}))`,
    LOG: (a) => (a.length === 2 ? `log_{${a[1]}}(${a[0]})` : a.length === 1 && `log_{10}(${a[0]})`),
    ATAN2: (a) => a.length === 2 && `atan2(${a[1]}, ${a[0]})`,
    INT: (a) => a.length === 1 && `floor(${a[0]})`,
    'FLOOR.MATH': (a) => a.length === 1 && `floor(${a[0]})`,
    'CEILING.MATH': (a) => a.length === 1 && `ceil(${a[0]})`,
    FACT: (a) => a.length === 1 && `((${a[0]})!)`,
    COMBIN: (a) => a.length === 2 && `comb(${a.join(', ')})`,
    PERMUT: (a) => a.length === 2 && `perm(${a.join(', ')})`,
    AVERAGE: (a) => `mean(${a.join(', ')})`,
    SUM: (a) => `sum(${a.join(', ')})`,
    PRODUCT: (a) => `prod(${a.join(', ')})`,
    MAX: (a) => `max(${a.join(', ')})`,
    MIN: (a) => `min(${a.join(', ')})`,
    MEDIAN: (a) => `median(${a.join(', ')})`,
    'STDEV.P': (a) => `stdev(${a.join(', ')})`,
    STDEVP: (a) => `stdev(${a.join(', ')})`,
    CEILING: (a) => (a.length === 1 || (a.length === 2 && a[1].trim() === '1')) && `ceil(${a[0]})`,
    RAND: (a) => !a.length && 'random(1)',
    ISNUMBER: (a) => a.length === 1 && `((${a[0]}) ∈ ℝ)`,
    LOG10: (a) => a.length === 1 && `log_{10}(${a[0]})`,
};

function spreadsheet(text) {
    text = text.replace(/^\s*=/, '').replace(/(?<![\w.])_xlfn\./g, '');
    // Excel's minus binds tighter than ^ (-x^2 is (-x)^2), and ^ groups left to right (2^3^2 is 64)
    const operand = '(?:[\\p{L}_][\\p{L}\\p{N}_.]*|\\d+(?:\\.\\d+)?|§\\d+§)';
    text = text.replace(new RegExp(`(^|[(,=<>*/+^-]\\s*)-\\s*(${operand})(?=\\s*\\^)`, 'gu'), '$1(-$2)');
    for (let again = true; again;) {
        const before = text;
        text = text.replace(new RegExp(`(^|[^\\p{L}\\p{N}_.)§])(${operand}\\s*\\^\\s*${operand})(?=\\s*\\^)`, 'u'), '$1($2)');
        again = text !== before;
    }
    return rewriteCalls(text, /(?<![\w.])([A-Z][A-Z0-9]*(?:\.[A-Z]+)?)\s*\(/g, (args, m) => SHEET_CALLS[m[1]]?.(args) || null);
}

// ---- SQL ---------------------------------------------------------------------

/** CASE WHEN c THEN a [WHEN …] ELSE b END → nested ternaries, innermost first. */
function sqlCase(text) {
    for (let guard = 0; guard < 50; guard++) {
        const starts = [...text.matchAll(/\bCASE\s+WHEN\b/gi)];
        if (!starts.length) return text;
        const start = starts[starts.length - 1].index;
        const end = /\bEND\b/i.exec(text.slice(start));
        if (!end) return text;
        const parts = text.slice(start + 4, start + end.index).split(/\b(WHEN|THEN|ELSE)\b/i).map((s) => s.trim());
        const branches = [];
        let otherwise = 'null';
        for (let i = 1; i < parts.length; i += 2) {
            const word = parts[i].toUpperCase();
            if (word === 'WHEN') branches.push([parts[i + 1], parts[i + 3]]);
            else if (word === 'ELSE') otherwise = parts[i + 1];
        }
        const out = branches.reduceRight((rest, [c, v]) => `((${c}) ? (${v}) : ${rest})`, p(otherwise));
        text = text.slice(0, start) + out + text.slice(start + end.index + 3);
    }
    return text;
}

/** SQL's functions, written in capitals. */
const SQL_NAMES = {
    POWER: 'pow', SQRT: 'sqrt', ABS: 'abs', LN: 'ln', EXP: 'exp', FLOOR: 'floor', CEIL: 'ceil', CEILING: 'ceil',
    ROUND: 'round', GREATEST: 'max', LEAST: 'min', MOD: 'mod', ATAN2: 'atan2', FACTORIAL: 'factorial',
    SIN: 'sin', COS: 'cos', TAN: 'tan', SEC: 'sec', CSC: 'csc', COT: 'cot', ASIN: 'asin', ACOS: 'acos', ATAN: 'atan',
    SINH: 'sinh', COSH: 'cosh', TANH: 'tanh', ASINH: 'asinh', ACOSH: 'acosh', ATANH: 'atanh',
    COMB: 'comb', PERM: 'perm', GCD: 'gcd', DERIVATIVE: 'derivative', LIMIT: 'limit', UNION: 'union', EXPM1: 'expm1',
    TRUNC: 'trunc',
};

/** A string placeholder (strings.js): SQL's 'integer' is one by the time this runs. */
const STRING = 'strtktk[A-J]+';

function sql(text) {
    // SQLite's x ∈ ℤ, ℕ, ℝ (render/sql.js): (typeof(x) IN ('integer', 'real') AND x = TRUNC(x) …)
    const typeTest = new RegExp(`^\\(typeof\\(([^()]*)\\)\\s+IN\\s+\\(${STRING},\\s*${STRING}\\)\\s+AND\\s+(.*)\\)$`, 's');
    for (let at = text.lastIndexOf('(typeof('); at >= 0; at = at > 0 ? text.lastIndexOf('(typeof(', at - 1) : -1) {
        const close = closing(text, at);
        const m = close > 0 && typeTest.exec(text.slice(at, close + 1));
        if (!m) continue;
        const [, v, test] = m;
        const set = { [`${v} = TRUNC(${v})`]: 'ℤ', [`${v} = TRUNC(${v}) AND ${v} > 0`]: 'ℕ', [`ABS(${v}) < ∞`]: 'ℝ' }[test.trim()];
        if (set) text = `${text.slice(0, at)}((${v}) ∈ ${set})${text.slice(close + 1)}`;
    }
    // CAST(x AS REAL): SQLite's real division
    text = rewriteCalls(text, /(?<![\w.])CAST\s*\(/gi, (args) => {
        const m = args.length === 1 && /^(.*)\s+AS\s+(?:REAL|FLOAT|DOUBLE(?:\s+PRECISION)?|NUMERIC|DECIMAL|INTEGER|INT)\s*$/is.exec(args[0]);
        return m ? `(${m[1]})` : null;
    });
    text = text.replace(/(?<![\w.])ARRAY\s*\[/g, '[');   // ARRAY[a, b]: PostgreSQL's ± and lists
    text = sqlCase(text);
    text = rewriteCalls(text, /(?<![\w.])LOG\s*\(/g, (args) => (args.length === 2 ? `log_{${args[0]}}(${args[1]})` : `log_{10}(${args[0]})`));
    text = text.replace(/(?<![\w.])PI\s*\(\s*\)/g, 'π');
    text = text.replace(/(?<![\w.])([A-Z][A-Z0-9]*)(?=\s*\()/g, (name) => SQL_NAMES[name] ?? name);
    // x IN (1, 2), x NOT IN (1, 2): capitals only, as (0, 1) after "in" is an interval in maths
    for (const [pattern, symbol] of [[/\bNOT\s+IN\s*\(/g, '∉'], [/\bIN\s*\(/g, '∈']]) {
        for (let m = pattern.exec(text); m; m = pattern.exec(text)) {
            const open = m.index + m[0].length - 1;
            const close = closing(text, open);
            if (close < 0) break;
            text = `${text.slice(0, m.index)}${symbol} {${text.slice(open + 1, close)}}${text.slice(close + 1)}`;
            pattern.lastIndex = 0;
        }
    }
    return text.replace(/<>/g, ' ≠ ');
}

// ---- numpy, math, scipy, sympy, Number, GLSL's mz_ ------------------------------------

const NP_AS_MATH = {
    sin: 'sin', cos: 'cos', tan: 'tan', sinh: 'sinh', cosh: 'cosh', tanh: 'tanh',
    arcsin: 'asin', arccos: 'acos', arctan: 'atan', arcsinh: 'asinh', arccosh: 'acosh', arctanh: 'atanh', arctan2: 'atan2',
    sqrt: 'sqrt', cbrt: 'cbrt', exp: 'exp', expm1: 'expm1', log: 'log', log2: 'log2', log10: 'log10',
    floor: 'floor', ceil: 'ceil', round: 'round', power: 'pow', abs: 'abs', absolute: 'abs', fabs: 'abs',
    pi: 'PI', e: 'E', gcd: 'gcd',
};
const NP_BARE = {
    maximum: 'max', minimum: 'min', nanmax: 'max', nanmin: 'min', nansum: 'sum', nanprod: 'prod', nanmean: 'mean',
    nanmedian: 'median', nanstd: 'stdev', mod: 'mod', fmod: 'mod', where: 'where', isin: 'isin', isclose: 'isclose',
    isfinite: 'isfinite', logical_and: 'logical_and', logical_or: 'logical_or', logical_not: 'logical_not',
    logical_xor: 'logical_xor', prod: 'prod', sum: 'sum',
};

function prefixes(text) {
    text = text.replace(/(?<![\w.])(?:np|numpy)\.random\.random\(\s*\)|(?<![\w.])random\.random\(\s*\)/g, 'Math.random()');
    text = text.replace(/(?<![\w.])(?:np|numpy)\.(\w+)/g, (whole, name) => {
        if (NP_AS_MATH[name]) return `Math.${NP_AS_MATH[name]}`;
        if (NP_BARE[name]) return NP_BARE[name];
        return { inf: '∞', nan: 'NaN' }[name] ?? whole;
    });
    text = text.replace(/(?<![\w.])(?:math|Math)\.(factorial|isfinite|isclose|prod|inf|nan|abs)\b/g,
        (whole, name) => ({ inf: '∞', nan: 'NaN' }[name] ?? name));
    text = text.replace(/(?<![\w.])Number\.(isInteger|isFinite)\b/g, (whole, name) => name.toLowerCase());
    text = text.replace(/(?<![\w.])scipy\.(?:special|integrate)\.(\w+)/g, '$1');
    text = sympyNames(text);
    text = text.replace(/\bMZ_INFINITY\b/g, '∞');
    return text.replace(/(?<![\w.])mz_(?=\w+\s*\()/g, '');   // GLSL's helpers: mz_sinh(x) → sinh(x)
}

/** SymPy's names (what render/code.js writes for sympy: true) → the ones read here or by the cleaner. */
const SYMPY_CONSTANTS = { pi: 'π', E: 'e', oo: '∞', true: 'true', false: 'false', nan: 'NaN', I: 'i' };
const SYMPY_SETS = { Reals: 'ℝ', Integers: 'ℤ', Naturals: 'ℕ', Naturals0: 'ℕ', Rationals: 'ℚ', Complexes: 'ℂ' };
const SYMPY_CALLS = {
    sqrt: 'Math.sqrt', exp: 'Math.exp', sin: 'Math.sin', cos: 'Math.cos', tan: 'Math.tan', sinh: 'Math.sinh', cosh: 'Math.cosh', tanh: 'Math.tanh',
    asin: 'Math.asin', acos: 'Math.acos', atan: 'Math.atan', asinh: 'Math.asinh', acosh: 'Math.acosh', atanh: 'Math.atanh', atan2: 'atan2',
    csc: 'csc', sec: 'sec', cot: 'cot', log: 'log', Abs: 'abs', floor: 'floor', ceiling: 'ceil', Max: 'max', Min: 'min',
    factorial: 'factorial', binomial: 'comb', ff: 'perm', gcd: 'gcd', gcd_list: 'sympy_list_gcd', Mod: 'mod', root: 'sympy_root',
    Rational: 'sympy_rational', Integer: 'sympy_value', Float: 'sympy_value', Eq: 'sympy_eq', Ne: 'sympy_ne',
    And: 'sympy_and', Or: 'sympy_or', Not: 'sympy_not', Xor: 'sympy_xor', Nand: 'sympy_nand', Nor: 'sympy_nor',
    Piecewise: 'sympy_piecewise', FiniteSet: 'sympy_set', Interval: 'sympy_interval', Contains: 'sympy_contains',
    Union: 'union', Intersection: 'intersection', diff: 'derivative', integrate: 'sympy_integrate', limit: 'sympy_limit',
    summation: 'sympy_summation', product: 'sympy_product', expm1: 'expm1',
};
const SYMPY_INTERVALS = { open: '()', Lopen: '(]', Ropen: '[)' };

function sympyNames(text) {
    text = text.replace(/(?<![\w.])sympy\.Interval\.(open|Lopen|Ropen)\s*\(/g, (whole, kind) => `sympy_interval_${kind}(`);
    text = text.replace(/(?<![\w.])sympy\.S\.(\w+)/g, (whole, name) => SYMPY_SETS[name] ?? whole);
    return text.replace(/(?<![\w.])sympy\.(\w+)/g, (whole, name) => SYMPY_CALLS[name] ?? SYMPY_CONSTANTS[name] ?? whole);
}

/** A SymPy (value, condition) pair: the two parts of one Piecewise piece. */
const pieceOf = (arg) => {
    const m = /^\((.*)\)$/s.exec(arg.trim());
    return m ? splitArgs(m[1]) : null;
};
const interval = (brackets) => (a) => a.length === 2 && `${brackets[0]}${a[0]}, ${a[1]}${brackets[1]}`;
/** (x, a, b) in integrate and summation: the variable and its bounds. */
const bounds = (arg) => pieceOf(arg) ?? [arg];

/** Calls the cleaner doesn't otherwise know, as maths. */
const CALLS = {
    where: (a) => a.length === 3 && `((${a[0]}) ? (${a[1]}) : (${a[2]}))`,
    logical_and: (a) => a.length === 2 && `((${a[0]}) & (${a[1]}))`,
    logical_or: (a) => a.length === 2 && `((${a[0]}) ∨ (${a[1]}))`,
    logical_xor: (a) => a.length === 2 && `((${a[0]})  \\xor  (${a[1]}))`,
    logical_not: (a) => a.length === 1 && `(!(${a[0]}))`,
    isin: (a) => a.length === 2 && `((${a[0]}) ∈ ${setOf(a[1])})`,
    contains: (a) => a.length === 2 && `((${a[1]}) ∈ ${setOf(a[0])})`,
    isclose: (a) => a.length >= 2 && `((${a[0]}) ≈ (${a[1]}))`,
    isfinite: (a) => a.length === 1 && `((${a[0]}) ∈ ℝ)`,
    isinteger: (a) => a.length === 1 && `((${a[0]}) ∈ ℤ)`,
    factorial: (a) => a.length === 1 && `((${a[0]})!)`,
    union: (a) => a.length === 2 && `((${a[0]}) ∪ (${a[1]}))`,
    union_: (a) => a.length === 2 && `((${a[0]}) ∪ (${a[1]}))`,
    intersection: (a) => a.length === 2 && `((${a[0]}) ∩ (${a[1]}))`,
    sq: (a) => a.length === 1 && `((${a[0]})^2)`,
    cube: (a) => a.length === 1 && `((${a[0]})^3)`,
    fract: (a) => a.length === 1 && `((${a[0]}) - floor(${a[0]}))`,
    mod: (a) => a.length === 2 && `((${a[0]}) \\mod (${a[1]}))`,
    atan: (a) => a.length === 2 && `atan2(${a[0]}, ${a[1]})`,
    exp2: (a) => a.length === 1 && `((2)^(${a[0]}))`,
    trunc: (a) => a.length === 1 && `((${a[0]}) - ((${a[0]}) \\mod 1))`,
    vec2: (a) => `(${a.join(', ')})`,
    vec3: (a) => `(${a.join(', ')})`,
    vec4: (a) => `(${a.join(', ')})`,
    derivative: (a) => a.length >= 2 && `der(${a.join(', ')})`,
    sympy_rational: (a) => a.length === 2 && `((${a[0]})/(${a[1]}))`,
    sympy_value: (a) => a.length === 1 && `(${a[0]})`,
    sympy_eq: (a) => a.length === 2 && `((${a[0]}) = (${a[1]}))`,
    sympy_ne: (a) => a.length === 2 && `((${a[0]}) ≠ (${a[1]}))`,
    sympy_and: (a) => a.length && `(${a.map(p).join(' & ')})`,
    sympy_or: (a) => a.length && `(${a.map(p).join(' ∨ ')})`,
    sympy_not: (a) => a.length === 1 && `(!(${a[0]}))`,
    sympy_xor: (a) => a.length === 2 && `((${a[0]})  \\xor  (${a[1]}))`,
    sympy_nand: (a) => a.length === 2 && `((${a[0]})  \\nand  (${a[1]}))`,
    sympy_nor: (a) => a.length === 2 && `((${a[0]})  \\nor  (${a[1]}))`,
    sympy_piecewise: (a) => {
        const pieces = a.map(pieceOf);
        if (!pieces.length || pieces.some((x) => !x || x.length !== 2)) return null;
        return pieces.reduceRight((rest, [value, condition]) => (rest === null || /^True$|^true$/.test(condition.trim()) && rest === undefined
            ? `(${value})` : `((${condition}) ? (${value}) : ${rest ?? '(null)'})`), undefined);
    },
    sympy_set: (a) => `{${a.join(', ')}}`,
    sympy_interval: interval('[]'),
    sympy_interval_open: interval('()'),
    sympy_interval_Lopen: interval('(]'),
    sympy_interval_Ropen: interval('[)'),
    sympy_contains: (a) => a.length === 2 && `((${a[0]}) ∈ ${a[1]})`,
    sympy_list_gcd: (a) => a.length === 1 && `gcd(${a[0].trim().replace(/^\[|\]$/g, '')})`,
    sympy_root: (a) => a.length === 2 && `root(${a[1]}, ${a[0]})`,
    sympy_integrate: (a) => {
        if (a.length !== 2) return null;
        const b = bounds(a[1]);
        return b.length === 3 ? `int(${a[0]}, ${b.join(', ')})` : b.length === 1 ? `int(${a[0]}, ${b[0]})` : null;
    },
    sympy_limit: (a) => a.length >= 3 && `lim(${a.slice(0, 3).join(', ')}${a[3] ? `, ${a[3]}` : ''})`,
    sympy_summation: (a) => {
        const b = a.length === 2 && bounds(a[1]);
        return b?.length === 3 && `(\\sum_{${b[0]}=${b[1]}}^{${b[2]}} (${a[0]}))`;
    },
    sympy_product: (a) => {
        const b = a.length === 2 && bounds(a[1]);
        return b?.length === 3 && `(\\prod_{${b[0]}=${b[1]}}^{${b[2]}} (${a[0]}))`;
    },
    limit: (a) => a.length >= 3 && `lim(${a.join(', ')})`,
    sum: generator('sum'),
    prod: generator('prod'),
};

/** sum(f for i in range(a, b)) → (\sum_{i=a}^{b-1} (f)); anything else is left to the parser. */
function generator(kind) {
    return (a) => {
        const m = a.length === 1 && /^(.*?)\s+for\s+(\w+)\s+in\s+range\((.*)\)\s*$/s.exec(a[0]);
        if (!m) return null;
        const bounds = splitArgs(m[3]);
        const [from, to] = bounds.length === 1 ? ['0', bounds[0]] : bounds;
        const last = /\s*\+\s*1$/.test(to) ? to.replace(/\s*\+\s*1$/, '') : `(${to}) - 1`;
        return `(\\${kind}_{${m[2]}=${from}}^{${last}} (${m[1]}))`;
    };
}

function calls(text) {
    // scipy.integrate.quad(lambda x: f, a, b)[0] → int(f, x, a, b)
    text = rewriteCalls(text, call('quad'), (args, m, after) => {
        const fn = /^lambda\s+(\w+)\s*:\s*(.*)$/s.exec(args[0] ?? '');
        if (!fn || args.length !== 3) return null;
        const index = /^\s*\[\s*0\s*\]/.exec(after);
        return [`int(${fn[2]}, ${fn[1]}, ${args[1]}, ${args[2]})`, index ? index[0].length : 0];
    });
    text = rewriteCalls(text, call(Object.keys(CALLS).join('|')), (args, m) => CALLS[m[1]](args) || null);
    // float(x).is_integer() → x ∈ ℤ
    text = rewriteCalls(text, call('float'), (args, m, after) => {
        const method = /^\s*\.is_integer\(\s*\)/.exec(after);
        return method && args.length === 1 ? [`((${args[0]}) ∈ ℤ)`, method[0].length] : null;
    });
    // [1, 2].includes(x), S.includes(x) → x ∈ {1, 2}, x ∈ S
    for (let at = text.lastIndexOf('.includes('); at >= 0; at = at > 0 ? text.lastIndexOf('.includes(', at - 1) : -1) {
        const open = at + '.includes'.length;
        const close = closing(text, open);
        let start = at;
        if (CLOSE.includes(text[at - 1])) {
            let depth = 0;
            for (start = at - 1; start >= 0; start--) {
                if (CLOSE.includes(text[start])) depth++;
                else if (OPEN.includes(text[start]) && --depth === 0) break;
            }
        } else {
            while (start > 0 && /[\w.]/.test(text[start - 1])) start--;
        }
        if (close < 0 || start < 0 || start === at) continue;
        text = `${text.slice(0, start)}((${text.slice(open + 1, close)}) ∈ ${setOf(text.slice(start, at))})${text.slice(close + 1)}`;
    }
    return text;
}

// ---- Python's a if c else b -----------------------------------------------------------

/** `a if c else b` (Python's conditional, the lowest precedence) → ((c) ? (a) : (b)). */
function pythonConditionals(text) {
    for (let guard = 0; guard < 50; guard++) {
        let done = true;
        for (const m of text.matchAll(/\bif\b/g)) {
            const at = m.index;
            // the else at the same depth, before the group closes; an if … then is ifThenElse's (latex.js)
            let depth = 0;
            let otherwise = -1;
            let end = text.length;
            for (let i = at + 2; i < text.length; i++) {
                if (OPEN.includes(text[i])) depth++;
                else if (CLOSE.includes(text[i]) && --depth < 0) { end = i; break; }
                else if (depth === 0 && text[i] === ',' ) { end = i; break; }
                else if (depth === 0 && /^then\b/.test(text.slice(i)) && /\W/.test(text[i - 1])) { otherwise = -2; break; }
                else if (depth === 0 && otherwise < 0 && /^else\b/.test(text.slice(i)) && /\W/.test(text[i - 1])) otherwise = i;
            }
            if (otherwise < 0) continue;
            depth = 0;
            let start = 0;
            for (let i = at - 1; i >= 0; i--) {
                if (CLOSE.includes(text[i])) depth++;
                else if (OPEN.includes(text[i]) && --depth < 0) { start = i + 1; break; }
                else if (depth === 0 && text[i] === ',') { start = i + 1; break; }
            }
            const value = text.slice(start, at).trim();
            if (!value) continue;   // `if c then …` with no value before it
            const out = `((${text.slice(at + 2, otherwise).trim()}) ? (${value}) : (${text.slice(otherwise + 4, end).trim()}))`;
            text = text.slice(0, start) + out + text.slice(end);
            done = false;
            break;
        }
        if (done) return text;
    }
    return text;
}

// ---- the phase ---------------------------------------------------------------------

export function codeRewrites(text) {
    if (!/^\s*=|[(.%^<_eE]|\bif\b|\b(?:True|False|None|TRUE|FALSE|NULL)\b/.test(text)) return text;
    if (/^\s*=(?!=)/.test(text)) text = spreadsheet(text);
    text = jsHelpers(text);
    text = text.replace(/(?<![\w.])9e999\b/g, '∞');
    text = text.replace(/(?<![\w.])(\d+(?:\.\d+)?)[eE]([+-]\d+)(?![\w.])/g, '($1*10^{$2})');
    text = sql(text);
    text = prefixes(text);
    text = calls(text);
    text = pythonConditionals(text);
    text = text.replace(/\b(?:True|TRUE)\b/g, 'true').replace(/\b(?:False|FALSE)\b/g, 'false').replace(/\b(?:None|NULL)\b/g, 'null');
    text = text.replace(/\^\^/g, '  \\xor  ');
    // a % (b), a % -b, a % f(x): the remainder (the parser reads a%b itself, and 5% alone as a percentage)
    return text.replace(/%(?=\s*(?:[(-]|[A-Za-z_][\w.]*\s*\())/g, ' \\mod ');
}
