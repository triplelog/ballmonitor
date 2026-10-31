/**
 * What every outputter accepts, and how it gets a tree from it:
 *
 *   - an expression string     '2x + 1'
 *   - standard postfix          ['2', 'x', '*', '1', '+']
 *   - an expression tree        from parseTree() or fromPostfix()
 */

import { parseTree } from './parse/index.js';
import { asTree } from './tree.js';

/**
 * @param {string|string[]|object} input
 * @param {object} [parseOptions] used when the input is text; see parse()
 * @returns {object} a tree whose node ids are postfix indexes
 */
export const treeOf = (input, parseOptions) => (typeof input === 'string' ? parseTree(input, parseOptions) : asTree(input));

/** An empty postfix array: every outputter returns its "nothing" for it. */
export const isEmpty = (input) => Array.isArray(input) && input.length === 0;
