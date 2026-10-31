/**
 * Longest-match text replacement with a trie.
 *
 * Scanning left to right, at each position the longest table key that
 * starts there is replaced, and scanning resumes after the replacement —
 * so replacements never cascade into each other.
 */

/**
 * Build a replacer from [from, to, caseSensitive?] entries.
 * @returns {(text: string) => string}
 */
export function makeReplacer(entries) {
    const map = new Map();
    for (const [from, to, caseSensitive] of entries) {
        if (!from || from.trim() === '') continue;
        map.set(from, to);   // a later exact entry overrides an earlier one
        if (caseSensitive) continue;
        for (const variant of caseVariants(from)) {
            if (!map.get(variant)) map.set(variant, to);
        }
    }

    const root = new Map();
    for (const key of map.keys()) {
        let node = root;
        for (let i = 0; i < key.length; i++) {
            if (!node.has(key[i])) node.set(key[i], new Map());
            node = node.get(key[i]);
        }
        node.end = true;
    }

    return (text) => {
        let out = '';
        let i = 0;
        while (i < text.length) {
            const length = longestMatch(root, text, i);
            if (length) {
                out += map.get(text.slice(i, i + length));
                i += length;
            } else {
                out += text[i++];
            }
        }
        return out;
    };
}

function longestMatch(root, text, start) {
    let node = root;
    let best = 0;
    for (let i = start; i < text.length; i++) {
        node = node.get(text[i]);
        if (!node) break;
        if (node.end) best = i - start + 1;
    }
    return best;
}

/** `Max` → `max`, `MAX`; `math.pi` → `Math.Pi`: lower, upper and capitalised words. */
function caseVariants(text) {
    const variants = new Set([text.toLowerCase(), text.toUpperCase(), capitalise(text)]);
    variants.delete(text);
    return variants;
}

function capitalise(text) {
    let out = '';
    let afterLetter = false;
    for (const ch of text) {
        const lower = ch >= 'a' && ch <= 'z';
        const upper = ch >= 'A' && ch <= 'Z';
        out += !afterLetter && lower ? ch.toUpperCase() : ch;
        afterLetter = lower || upper;
    }
    return out;
}
