/**
 * Quoted strings are lifted out before cleaning, so that text inside them
 * ("2+2", "x < y") is never rewritten, and put back into the postfix at the
 * end. Each string is replaced by a placeholder made only of letters, which
 * the tokenizer treats as one ordinary operand.
 */

const PREFIX = 'strtktk';
const DIGIT_LETTERS = 'ABCDEFGHIJ';

export const placeholder = (n) => PREFIX + [...String(n)].map((d) => DIGIT_LETTERS[d]).join('');
/** Is this word a string's placeholder? (It must stay one token, never be read as letters.) */
export const isPlaceholder = (word) => new RegExp(`^${PREFIX}[${DIGIT_LETTERS}]+$`).test(word);

/**
 * An apostrophe right after a letter, digit, closing bracket or another
 * apostrophe is a prime (f'(x), y''), not the start of a 'string': turn it
 * into ′ so extractStrings leaves it alone.
 */
export function markPrimes(input) {
    let out = '';
    for (let i = 0; i < input.length; i++) {
        const c = input[i];
        if (c === '"' || c === '`') {   // copy a double-quoted or backtick string as it is
            const end = closingQuote(input, i);
            out += input.slice(i, end + 1);
            i = end;
        } else if (c === "'") {
            if (/[A-Za-z0-9)\]′\u0370-\u03FF]/.test(out[out.length - 1] ?? '')) {
                out += '′';
            } else {
                const end = closingQuote(input, i);
                out += input.slice(i, end + 1);
                i = end;
            }
        } else {
            out += c;
        }
    }
    return out;
}

function closingQuote(input, start) {
    let escaped = false;
    for (let j = start + 1; j < input.length; j++) {
        if (escaped) escaped = false;
        else if (input[j] === '\\') escaped = true;
        else if (input[j] === input[start]) return j;
    }
    return input.length - 1;
}

/**
 * @returns {{ text: string, strings: Map<string, string> }} text with
 *   placeholders, and placeholder → original string (quotes included)
 */
export function extractStrings(input) {
    const strings = new Map();
    let text = '';
    let i = 0;
    while (i < input.length) {
        const quote = input[i];
        if (quote !== '"' && quote !== "'" && quote !== '`') {
            text += input[i++];
            continue;
        }
        let j = i + 1;
        let body = '';
        let escaped = false;
        while (j < input.length && (escaped || input[j] !== quote)) {
            escaped = !escaped && input[j] === '\\';
            body += input[j++];
        }
        const id = placeholder(strings.size);
        strings.set(id, quote + body + quote);
        text += id;
        i = j + 1;
    }
    return { text, strings };
}

/** Put the original strings back into each token. */
export function restoreStrings(tokens, strings) {
    if (!strings || strings.size === 0) return tokens;
    // Longest first: strtktkB is a prefix of strtktkBA.
    const entries = [...strings].sort((a, b) => b[0].length - a[0].length);
    return tokens.map((token) => {
        for (const [id, original] of entries) token = token.split(id).join(original);
        return token;
    });
}
