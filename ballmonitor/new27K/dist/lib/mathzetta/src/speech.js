/** 'mathzetta/speech' — the expression read aloud, as a teacher would. */

import { treeOf, isEmpty } from './input.js';
import { toSpeech as speak, toSpeechSegments as speakSegments } from './render/speech.js';

export { WORDS as SPEECH_WORDS, NAMES as SPEECH_NAMES } from './render/speech.js';

/**
 * @param {string|string[]|object} input expression text, standard postfix or a tree
 * @param {object} [options] { words, names, say } — every word and phrase can be changed; see render/speech.js
 * @returns {string} "x squared plus 1"
 */
export function toSpeech(input, options = {}) {
    if (isEmpty(input)) return '';
    return speak(treeOf(input), options);
}

/** The spoken phrase in pieces tagged with node ids, [{ text, id }], for captions that follow the maths. */
export function toSpeechSegments(input, options = {}) {
    if (isEmpty(input)) return [];
    return speakSegments(treeOf(input), options);
}
