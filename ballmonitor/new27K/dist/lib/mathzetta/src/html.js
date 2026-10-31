/**
 * 'mathzetta/html' — plain nested <span>s laid out with HTML_STYLES.
 *
 * Deprecated: MathView (../mathview) draws the same trees properly —
 * fractions on the axis, stretching brackets, integrals, piecewise — with
 * the same node ids. Use it for anything people look at.
 */

import { treeOf, isEmpty } from './input.js';
import { toHtml } from './render/html.js';

export { HTML_STYLES } from './render/html.js';

/**
 * @param {string|string[]|object} input expression text, standard postfix or a tree
 * @param {object} [options] `classPrefix` (default 'mz'), `attributes(node)`
 */
export function toHTML(input, options = {}) {
    if (isEmpty(input)) return '<span class="mz"></span>';
    return toHtml(treeOf(input), options);
}
