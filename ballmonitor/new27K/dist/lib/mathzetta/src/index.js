/**
 * MathZetta — reads maths written almost any way (plain text, LaTeX,
 * unicode, JavaScript, Python) into **standard postfix** and a tree.
 *
 *   import { parse, parseTree } from 'mathzetta';
 *   parse('2x^2 + \\sin x')     → ['2', 'x', '2', '^', '*', 'x', 'sin', '+']
 *
 * This is the core: the parser, the operator table and the tree tools.
 * It has no output formats. Add the ones you need:
 *
 *   'mathzetta/latex'      toLaTeX            'mathzetta/javascript'  toJavaScript
 *   'mathzetta/mathml'     toMathML           'mathzetta/python'      toPython
 *   'mathzetta/text'       toText             'mathzetta/sql'         toSQL
 *   'mathzetta/speech'     toSpeech, segments 'mathzetta/glsl'        toGLSL, filterShader
 *   'mathzetta/evaluate'   evaluate (doubles) 'mathzetta/formulas'    strToFunction, strToSQL
 *   'mathzetta/calculate'  calculate (exact) — loading it also fills {{…}} blocks in any input
 *   'mathzetta/all'        everything, plus toUnified; what the <script> build contains
 *
 * Maths display is a separate library, MathView, which draws these trees.
 * The postfix format is described in docs/postfix.md; the pipeline in
 * docs/how-it-works.md.
 */

import { fromPostfix } from './tree.js';
import { operatorNames, precedenceOf } from './operators.js';
import { isNumber } from './parse/vocabulary.js';

export const version = '3.0.0';

export { parse, parse as parseToPostfix, parseSteps, parseTree, clean, setBlockHandler } from './parse/index.js';
export { fromPostfix, toPostfix, asTree, walk, firstVariable, num, sym, op, leaf } from './tree.js';
export { treeOf } from './input.js';
export {
    operator, operatorNames, isOperator, precedenceOf, needsParens, isCustomFunction, VARIADIC, CUSTOM_PREFIX,
} from './operators.js';
// How a tree reads when written out — shared by every outputter, and by MathView.
export {
    GREEK, bracketOp, needsBrackets, unaryNeedsBrackets, isImplicitProduct, bracketedSides, isMinusOneTimes,
    startsWithSign, isVariable, firstLeaf, smallWhole, customName, derivativeOrder,
} from './common.js';

/** Is this array well-formed standard postfix? */
export function validatePostfix(postfix) {
    try {
        fromPostfix(postfix);
        return true;
    } catch {
        return false;
    }
}

export const getOperatorPrecedence = precedenceOf;
export const isNumeric = (text) => isNumber(text, true);

/** Operator names grouped by kind, for documentation pages. */
export function getSupportedOperations() {
    return {
        arithmetic: ['+', '-', '*', '/', '^', 'neg', '!', 'mod', '±'],
        trigonometric: ['sin', 'cos', 'tan', 'csc', 'sec', 'cot', 'sinh', 'cosh', 'tanh'],
        inverse_trig: ['arcsin', 'arccos', 'arctan', 'arcsinh', 'arccosh', 'arctanh', 'atan2'],
        logarithmic: ['ln', 'log', 'loglog', 'logloglog', 'expm1'],
        functions: ['sqrt', 'root', 'abs', 'floor', 'ceil', 'round', 'max', 'min', 'gcd', 'mean', 'random'],
        calculus: ['der', 'int', 'lim'],
        summation: ['sum', 'prod', '\\sumidx', '\\prodidx'],
        comparison: ['=', '===', '≠', '≠=', '<', '>', '≤', '≥', '∈', '∉', '→'],
        logical: ['&', '|', '\\not', '\\xor', '\\nor', '\\nand', '?:'],
        combinatorics: ['perm', 'comb'],
        groups: ['()', '[]', '{}', '(]', '[)'],
        misc: ['_'],
        all: operatorNames(),
    };
}
