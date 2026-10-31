/**
 * The helpers JavaScript output calls inline where Math has no function:
 * `${JS_HELPERS.factorial}(x)`. Shared by the writer (render/code.js) and the
 * reader (parse/clean/code.js), so what mathzetta writes it can read back.
 */
export const JS_HELPERS = {
    factorial: '((n) => { if (!Number.isInteger(n) || n < 0) return NaN; let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; })',
    perm: '((n, k) => { let r = 1; for (let i = n - k + 1; i <= n; i++) r *= i; return r; })',
    comb: '((n, k) => { let r = 1; for (let i = 1; i <= k; i++) r = r * (n - k + i) / i; return r; })',
    gcd: '((args)=>{let gcd = function(a,b) { return (!b)?a:gcd(b,a%b); }; return Math.abs(args.reduce(gcd));})',
};
