/**
 * Structural rewrites: notation a lookup table can't handle because it
 * needs to find matching brackets. Each rewrite turns a construct into
 * plain function-call syntax the parser understands:
 *
 *   \frac{d}{dx} f, d/dx f    der(f,x)       (see derivatives())
 *   \frac{dy}{dx}, dy/dx      der(y,x)
 *   \frac{d^2y}{dx^2}         der(y,x,2)
 *   ddx(f)                der(f,x)
 *   \sqrt[n]{x}           sqrt{n,x}              (the parser makes this root(n, x))
 *   \int_a^b f dx         int(f,x,a,b)
 *   ⌊x⌋  ⌈x⌉              floor(x)  ceil(x)
 *   \binom56              \binom{5}{6}
 *   \begin{matrix}..      [[a, b], [c, d]]
 *   log(x, b)             log_{b}(x)
 *   a ? b : c             a ?(b)?: c
 *   if a then b else c    ((a) ? (b) : (c))      (no else: the value `unchanged`)
 *   x^-12, x_12           x^{-12}, x_{12}
 *   \text{abc}            abc
 *   \begin{cases} a & \text{if } p \\ b & \text{otherwise} \end{cases}    ((p) ? (a) : (b))   (casesToTernary, before names are protected)
 *
 * spacedRewrites() runs while spaces are still present; compactRewrites()
 * runs on the whitespace-free text. Limits, sums and products are left to
 * the parser, which reads lim_{x→a} and \sum_{i=1}^{n} like functions with
 * sub- and superscripts.
 */

const isSpace = (c) => c === ' ' || c === '\t' || c === '\n';
const OPEN = '({[';
const CLOSE = ')}]';

/** Phase run before whitespace is removed. */
export function spacedRewrites(input) {
    input = ifThenElse(input);
    // a ≡ b (mod n): the congruence form, applying to the whole statement
    input = input.replace(/\(\s*\\?b?mod\s+([^()]+?)\s*\)/g, ' \\pmod{$1}');
    // lim x->0 f, lim x→a f: the spaces show where the subscript ends.
    input = input.replace(/(^|[^A-Za-z\\])lim\s+([^\s_{}]+?)\s*(->|→|\\to)\s*([^\s]+)\s+/g, '$1lim_{$2→$4} ');
    input = unwrapText(input);
    input = logBases(input);
    for (let i = 0; i < input.length - 1; i++) {
        if (input[i] === '?' && input[i + 1] !== ':') {
            input = wrapTernaryMiddle(input, i);
        } else if (input[i] === '_' || input[i] === '^') {
            // A numeric sub/superscript gets braces: x^-12 → x^{-12}, x^2-4 → x^{2}-4
            // and so does a protected name: \int_0^b with b a value (§0§) → \int_0^{§0§}
            const kept = /^§\d+§/.exec(input.slice(i + 1));
            if (kept) { input = `${input.slice(0, i + 1)}{${kept[0]}}${input.slice(i + 1 + kept[0].length)}`; continue; }
            let j = i + 1;
            if (input[j] === '-') j++;
            while (j < input.length && '.0123456789'.includes(input[j])) j++;
            if (j === i + 2 && input[i + 1] === '-') j = i + 1;   // a lone `-` is not a number
            if (j > i + 1) input = input.slice(0, i + 1) + '{' + input.slice(i + 1, j) + '}' + input.slice(j);
        }
    }
    return input;
}

/** Phase run after whitespace is removed and symbols are replaced. */
export function compactRewrites(input) {
    input = logBases(input);
    input = input.replace(/(?<![A-Za-z])frac(\d)(\d)/g, 'frac{$1}{$2}');   // \frac12 → \frac{1}{2}
    input = primedGroups(input);
    input = derivatives(input);
    for (let i = 0; i < input.length; i++) {
        const char = input[i];
        const before = (n) => input.slice(Math.max(0, i - n), i);
        const through = (n) => input.slice(Math.max(0, i - n), i + 1);

        if (char === '{') {
            if (before(6) === '\\begin') {
                const matrix = matrixToLists(input.slice(i + 1));
                if (matrix) input = input.slice(0, i - 6) + matrix;
            }
        } else if (char === '[') {
            if (before(5) === '\\sqrt') {
                input = input.slice(0, i - 5) + 'sqrt' + rootIndexToArgument(input.slice(i + 1));
            } else if (before(4) === 'sqrt') {
                input = input.slice(0, i - 4) + 'sqrt' + rootIndexToArgument(input.slice(i + 1));
            }
        } else if (char === '⌊' || char === '⌈') {
            input = input.slice(0, i) + floorCeil(input.slice(i));
        } else if (char === 't') {
            if (through(3) === '\\int') input = input.slice(0, i - 3) + integral(input.slice(i + 1));
        } else if (char === 'm') {
            if (through(5) === '\\binom') {
                input = input.slice(0, i - 5) + '\\binom' + braceBinomDigits(input.slice(i + 1));
            }
        } else if (char === 'd') {
            if (through(1) === 'dd' && input[i + 2] === '(') {
                const rewritten = ddxCall(input.slice(i + 1));
                if (rewritten) input = input.slice(0, i - 1) + 'der' + rewritten;
            }
        }
    }
    return input.replace(/\\log/g, 'log');
}

// ---- before names are protected ----------------------------------------------

/**
 * `\begin{cases} a & \text{if } p \\ b & \text{otherwise} \end{cases}` →
 * `((p) ? (a) : (b))`; more rows nest (`p ? a : q ? b : c`), and without an
 * otherwise row the last value is `unchanged`, as for `if … then`. Innermost
 * first, so a case inside a case works.
 */
export function casesToTernary(input) {
    for (let guard = 0; guard < 50; guard++) {
        const start = input.lastIndexOf('\\begin{cases}');
        const end = start < 0 ? -1 : input.indexOf('\\end{cases}', start);
        if (end < 0) return input;
        const rows = splitAtDepthZero(input.slice(start + '\\begin{cases}'.length, end), '\\\\')
            .map((row) => splitAtDepthZero(row, '&'))
            .filter((row) => row.join('').trim());
        let out = null;
        for (let k = rows.length - 1; k >= 0; k--) {
            const value = rows[k][0].trim();
            const condition = caseCondition(rows[k].slice(1).join('&'));
            if (out === null && !condition) out = `(${value})`;
            else out = `((${condition || 'true'}) ? (${value}) : ${out ?? '(unchanged)'})`;
        }
        input = input.slice(0, start) + (out ?? '') + input.slice(end + '\\end{cases}'.length);
    }
    return input;
}

/** A case's condition without its `if`; '' for otherwise / else. */
function caseCondition(text) {
    const words = /^\s*(?:\\(?:text|textrm|mathrm)\s*\{\s*(?:if|for|when|where)\s*\}|\b(?:if|for|when|where)\b)\s*,?/;
    const condition = text.replace(words, '').replace(/[\s,.;]+$/, '').trim();
    return /^(?:\\(?:text|textrm|mathrm)\s*\{\s*)?(?:otherwise|else)\s*\}?$/.test(condition) ? '' : condition;
}

/** Split at `separator` where no bracket or brace is open. */
function splitAtDepthZero(text, separator) {
    const parts = [];
    let depth = 0;
    let from = 0;
    for (let i = 0; i < text.length; i++) {
        if (OPEN.includes(text[i])) depth++;
        else if (CLOSE.includes(text[i])) depth--;
        else if (depth === 0 && text.startsWith(separator, i)) {
            parts.push(text.slice(from, i));
            i += separator.length - 1;
            from = i + 1;
        }
    }
    parts.push(text.slice(from));
    return parts;
}

// ---- spaced phase -----------------------------------------------------------

/** `\text{abc}` → `abc`. */
function unwrapText(input) {
    for (let i = 0; i < input.length; i++) {
        const through = (n) => input.slice(Math.max(0, i - n), i + 1);
        if (input[i] === 't' && through(4) === '\\text' && input[i + 1] === '{') {
            let depth = 1;
            let j = i + 2;
            let text = '';
            while (depth > 0 && j < input.length) {
                if (input[j] === '{') depth++;
                else if (input[j] === '}') depth--;
                else text += input[j];
                j++;
            }
            input = input.slice(0, i - 4) + text + input.slice(j);
        }
    }
    return input;
}

/**
 * `if a then b else c` → `((a) ? (b) : (c))`, and `if a then b` →
 * `((a) ? (b) : (unchanged))` — `unchanged` being "whatever this value
 * was", which an image filter binds to the pixel's own channel. Rewritten
 * from the last `if` backwards, so `else if` chains nest properly.
 */
function ifThenElse(input) {
    for (let guard = 0; guard < 100; guard++) {
        const starts = [...input.matchAll(/\bif\b/gi)];
        if (!starts.length) return input;
        const start = starts[starts.length - 1].index;
        const then = wordAtDepthZero(input, start + 2, 'then');
        if (then < 0) return input;
        const condition = input.slice(start + 2, then);
        const otherwise = wordAtDepthZero(input, then + 4, 'else');
        const end = closeOfGroup(input, otherwise < 0 ? then + 4 : otherwise + 4);
        const value = input.slice(then + 4, otherwise < 0 ? end : otherwise);
        const fallback = otherwise < 0 ? 'unchanged' : input.slice(otherwise + 4, end).trim();
        input = `${input.slice(0, start)}((${condition.trim()}) ? (${value.trim()}) : (${fallback}))${input.slice(end)}`;
    }
    return input;
}

/** Index of `word` after `from`, outside any brackets opened since; -1 if a bracket closes first. */
function wordAtDepthZero(text, from, word) {
    let depth = 0;
    const pattern = new RegExp(`\\b${word}\\b`, 'iy');
    for (let i = from; i < text.length; i++) {
        if (OPEN.includes(text[i])) depth++;
        else if (CLOSE.includes(text[i])) { if (--depth < 0) return -1; }
        else if (depth === 0) {
            pattern.lastIndex = i;
            if (pattern.test(text)) return i;
        }
    }
    return -1;
}

/** Where the bracket enclosing `from` closes (or the text ends). */
function closeOfGroup(text, from) {
    let depth = 0;
    for (let i = from; i < text.length; i++) {
        if (OPEN.includes(text[i])) depth++;
        else if (CLOSE.includes(text[i]) && --depth < 0) return i;
    }
    return text.length;
}

/** `a ? b : c` → `a ?(b)?: c`, matching nested ternaries. */
function wrapTernaryMiddle(input, i) {
    let depth = 1;
    for (let j = i + 1; j < input.length; j++) {
        if (input[j] === '?') depth++;
        else if (input[j] === ':' && --depth === 0) {
            return input.slice(0, i + 1) + '(' + input.slice(i + 1, j) + ')?:' + input.slice(j + 1);
        }
    }
    return input;
}

/**
 * `log_2x` → `log_{2}x`, `log_10 x` → `log_{10}x`, `log_bx` → `log_{b}x`: an
 * unbraced base is a run of digits or a single letter, as in LaTeX. And
 * `log(x, b)` → `log_{b}(x)`.
 */
function logBases(input) {
    for (let i = 2; i < input.length; i++) {
        if (input[i] !== 'g' || input.slice(i - 2, i + 1) !== 'log') continue;
        if (input[i + 1] === '_') {
            if (OPEN.includes(input[i + 2])) continue;
            const base = /^(?:\d+(?:\.\d+)?|[A-Za-z\u0370-\u03FF])/.exec(input.slice(i + 2))?.[0];
            if (!base) continue;
            const j = i + 2 + base.length;
            input = input.slice(0, i + 2) + '{' + base + '}' + input.slice(j);
        } else if (input[i + 1] === '(') {
            let depth = 1;
            let commas = 0;
            let value = '';
            let base = '';
            let end = 0;
            for (let j = i + 2; j < input.length; j++) {
                if (')]'.includes(input[j])) depth--;
                else if ('(['.includes(input[j])) depth++;
                if (depth === 0) {
                    end = j;
                    break;
                }
                if (depth === 1 && input[j] === ',') commas++;
                else if (commas === 0) value += input[j];
                else base += input[j];
            }
            if (commas === 1) input = input.slice(0, i + 1) + '_{' + base + '}(' + value + ')' + input.slice(end + 1);
        }
    }
    return input;
}

// ---- compact phase ----------------------------------------------------------

/** `⌊x⌋` → `floor(x)`, `⌈x⌉` → `ceil(x)`. */
function floorCeil(input) {
    const type = input[0] === '⌈' ? 'ceil' : 'floor';
    let depth = 1;
    for (let i = 1; i < input.length; i++) {
        if (input[i] === '⌊' || input[i] === '⌈') depth++;
        else if (input[i] === '⌋' || input[i] === '⌉') depth--;
        if (depth === 0) return type + '(' + input.slice(1, i) + ')' + input.slice(i + 1);
    }
    return input;
}

/** After `sqrt[`: `n]{x}` → `{n,x}`, `n]x` → `{n,x}`: the index becomes the first argument. */
function rootIndexToArgument(input) {
    let depth = 1;
    for (let i = 0; i < input.length; i++) {
        if (')]'.includes(input[i])) depth--;
        else if ('(['.includes(input[i])) depth++;
        if (depth !== 0) continue;
        const index = input.slice(0, i);
        const opener = input[i + 1];
        if (opener === '{' || opener === '(') return opener + index + ',' + input.slice(i + 2);
        const word = /^[A-Za-z0-9.\u0370-\u03FF]+/.exec(input.slice(i + 1))?.[0] ?? '';   // ∛x
        return '{' + index + ',' + word + '}' + input.slice(i + 1 + word.length);
    }
    return input;
}

/** After `\begin{`: a matrix environment → nested lists, or false. */
function matrixToLists(input) {
    const close = input.indexOf('}');
    const open = input.indexOf('{');
    if (close < 0 || (open >= 0 && open < close)) return false;
    const kind = input.slice(0, close);
    if (!kind.includes('matrix')) return false;

    const end = input.indexOf('\\end{' + kind + '}');
    const nested = input.indexOf('\\begin{' + kind + '}', close + 1);
    if (end < 0 || (nested !== -1 && nested < end)) return false;

    const rows = input.slice(close + 1, end).trim().split('\\\\')
        .map((row) => row.trim())
        .filter((row) => row.length)
        .map((row) => '[' + row.replace(/&/g, ', ') + ']');
    return '[' + rows.join(', ') + ']' + input.slice(end + 6 + kind.length);
}

/** Read `_x` or `_{...}` (and likewise `^`) at input[at]; returns [text, next index]. */
function readScript(input, at) {
    if (input[at + 1] !== '{') return [input[at + 1], at + 2];
    let depth = 1;
    let text = '';
    for (let i = at + 2; i < input.length; i++) {
        if (input[i] === '{') depth++;
        else if (input[i] === '}' && --depth === 0) return [text, i + 1];
        text += input[i];
    }
    return [text, input.length];
}

/** Read the optional _lower^upper of \int. */
function readBounds(input) {
    let lower = '';
    let upper = '';
    let next = 0;
    if (input[0] === '_') {
        [lower, next] = readScript(input, 0);
        if (input[next] === '^') [upper, next] = readScript(input, next);
    }
    return { lower, upper, next };
}

/** After `\int`: `_a^b f dx` → `int(f,x,a,b)`. */
function integral(input) {
    const { lower, upper, next } = readBounds(input);
    const tail = input.slice(next);
    const stripSpacing = (s) => s.replace(/\\,/g, '').replace(/\\!/g, '');

    let body;
    let variable = '';
    let rest = '';
    let d = tail.indexOf('\\mathrm{d}');
    if (d >= 0) {
        body = tail.slice(0, d);
        const named = /^\{([^{}]*)\}/.exec(tail.slice(d + 10));   // \mathrm{d}{x}
        variable = named ? named[1] : tail[d + 10];
        rest = tail.slice(d + 10 + (named ? named[0].length : 1));
    } else if ((d = differential(tail)) >= 0) {
        body = tail.slice(0, d);
        variable = tail[d + 1];
        rest = tail.slice(d + 2);
    } else {
        body = tail;
    }

    // ∫ dx/(1+x²) written \frac{dx}{1+x^2}: the dx sits in the numerator.
    if (!variable) {
        const m = /frac\{d([A-Za-z])\}/.exec(body);
        if (m) {
            variable = m[1];
            body = body.replace(m[0], 'frac{1}');
        }
    }

    let out = 'int(' + (stripSpacing(body) || '1');   // ∫ dx is ∫ 1 dx
    if (variable) out += ',' + variable;
    if (lower || upper) out += ',' + lower + ',' + upper;
    return out + ')' + rest;
}

/**
 * Where the `dx` of an integral starts: the first `d` outside any brackets
 * that is followed by a single letter — `x^{2}dx`, `xdx`, `sinx\,dx`.
 */
function differential(tail) {
    let depth = 0;
    for (let i = 0; i < tail.length; i++) {
        if (OPEN.includes(tail[i])) depth++;
        else if (CLOSE.includes(tail[i])) depth--;
        else if (depth === 0 && tail[i] === 'd' && /[A-Za-z\u0370-\u03FF]/.test(tail[i + 1] ?? '')
            && !/[A-Za-z]/.test(tail[i + 2] ?? '')) return i;
    }
    return -1;
}

/** After `dd`: `x(f)` → `(f,x)`, or false if no variable letter follows. */
function ddxCall(input) {
    const variable = input[0];
    const isLetter = (variable >= 'A' && variable <= 'Z') || (variable >= 'a' && variable <= 'z')
        || (variable >= 'α' && variable <= 'ω');
    if (!isLetter) return false;
    const body = input.slice(2);
    let depth = 1;
    for (let i = 0; i < body.length; i++) {
        if (CLOSE.includes(body[i])) depth--;
        else if (OPEN.includes(body[i])) depth++;
        if (depth === 0) return '(' + body.slice(0, i) + ',' + variable + ')' + body.slice(i + 1);
    }
    return false;
}

/** After `\binom`: two bare digits get braces, `56` → `{5}{6}`. */
function braceBinomDigits(input) {
    if (input[0] === '{' || input.length < 2) return input;
    return '{' + input[0] + '}{' + input[1] + '}' + input.slice(2);
}

// ---- derivative notation ----------------------------------------------------

/**
 * (fg)′ → der((fg),x): a prime on a bracketed expression differentiates
 * it. A call takes its name along: sin(x)′ and f(x)′ are (sin x)′, (f(x))′.
 */
function primedGroups(text) {
    for (let i = text.indexOf(')′'); i >= 0; i = text.indexOf(')′', i + 1)) {
        let depth = 0;
        let start = -1;
        for (let j = i; j >= 0; j--) {
            if (text[j] === ')') depth++;
            else if (text[j] === '(' && --depth === 0) { start = j; break; }
        }
        if (start < 0) continue;
        while (start > 0 && /[A-Za-z\u0370-\u03FF′]/.test(text[start - 1])) start--;
        let n = 0;
        while (text[i + 1 + n] === '′') n++;
        text = text.slice(0, start) + der(text.slice(start, i + 1), 'x', n) + text.slice(i + 1 + n);
        i = start;
    }
    return text;
}

const VARIABLE = /[A-Za-z\u0370-\u03FF]/;

/** Read `{...}` at text[at]; returns [inside, index after] or null. */
function braced(text, at) {
    if (text[at] !== '{') return null;
    let depth = 0;
    for (let i = at; i < text.length; i++) {
        if (text[i] === '{') depth++;
        else if (text[i] === '}' && --depth === 0) return [text.slice(at + 1, i), i + 1];
    }
    return null;
}

/** `^{2}` or `^2` at text[at] → [2, index after]; nothing there → [1, at]. */
function order(text, at) {
    const m = /^\^(?:\{(\d+)\}|(\d))/.exec(text.slice(at));
    return m ? [Number(m[1] ?? m[2]), at + m[0].length] : [1, at];
}

/**
 * The parts of a Leibniz fraction: numerator `d`, `d^{n}`, `dy`, `d^{n}y`
 * and denominator `dx`, `dx^{n}` (\mathrm{d} counts as d). Returns
 * { n, of, by } — `of` is '' for the operator form d/dx — or null.
 */
function leibniz(numerator, denominator) {
    const num = numerator.replace(/\\mathrm\{d\}/g, 'd');
    const den = denominator.replace(/\\mathrm\{d\}/g, 'd');
    const top = /^d(?:\^\{?(\d+)\}?)?([A-Za-z\u0370-\u03FF]?)$/.exec(num);
    const bottom = /^d([A-Za-z\u0370-\u03FF])(?:\^\{?(\d+)\}?)?$/.exec(den);
    if (!top || !bottom) return null;
    return { n: Number(top[1] ?? 1), of: top[2], by: bottom[1] };
}

/**
 * What d/dx applies to, starting at text[at]: a bracketed group if one
 * follows, otherwise everything up to `=`, `,` or a closing bracket.
 * Returns [body, index after].
 */
function derivativeBody(text, at) {
    if (OPEN.includes(text[at])) {
        let depth = 0;
        for (let i = at; i < text.length; i++) {
            if (OPEN.includes(text[i])) depth++;
            else if (CLOSE.includes(text[i]) && --depth === 0) return [text.slice(at, i + 1), i + 1];
        }
        return [text.slice(at), text.length];
    }
    let depth = 0;
    for (let i = at; i < text.length; i++) {
        if (OPEN.includes(text[i])) depth++;
        else if (CLOSE.includes(text[i]) && --depth < 0) return [text.slice(at, i), i];
        else if (depth === 0 && (text[i] === '=' || text[i] === ',')) return [text.slice(at, i), i];
    }
    return [text.slice(at), text.length];
}

const der = (body, by, n) => `der(${body},${by}${n > 1 ? ',' + n : ''})`;

/**
 * Leibniz notation → der(...):
 *
 *   \frac{d}{dx} f, d/dx f       der(f,x)      f: a bracketed group, or the
 *   \frac{d^2}{dx^2} f            der(f,x,2)    rest up to = , or a bracket
 *   \frac{dy}{dx}, dy/dx          der(y,x)
 *   \frac{d^2y}{dx^2}             der(y,x,2)
 */
function derivatives(text) {
    for (let i = 0; i < text.length; i++) {
        const prevIsLetter = i > 0 && VARIABLE.test(text[i - 1]);
        let parts = null;
        let after = i;

        if (text.startsWith('frac{', i)) {
            const num = braced(text, i + 4);
            const den = num && braced(text, num[1]);
            parts = den && leibniz(num[0], den[0]);
            if (parts) after = den[1];
        } else if (text[i] === 'd' && !prevIsLetter) {
            // d/dx…, dy/dx…, d^{2}y/dx^{2}…: the variables are single letters,
            // which is how `d/dxx^2` (from "d/dx x^2") can be read at all.
            let [n, j] = order(text, i + 1);
            let of = '';
            if (VARIABLE.test(text[j] ?? '') && text[j + 1] === '/') of = text[j++];
            if (text[j] === '/' && text[j + 1] === 'd' && VARIABLE.test(text[j + 2] ?? '')) {
                const by = text[j + 2];
                const [, k] = order(text, j + 3);
                parts = { n, of, by };
                after = k;
            }
        }
        if (!parts) continue;

        let replacement;
        if (parts.of) {
            replacement = der(parts.of, parts.by, parts.n);
        } else {
            const [body, end] = derivativeBody(text, after);
            if (!body) continue;
            replacement = der(body, parts.by, parts.n);
            after = end;
        }
        text = text.slice(0, i) + replacement + text.slice(after);
        i += 3;   // past "der", so a body that is itself d/dx… is still rewritten
    }
    return text;
}
