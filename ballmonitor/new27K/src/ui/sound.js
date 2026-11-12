// Sound effects, made on the spot with Web Audio (no files to load): the
// ball in the glove, the crack of the bat, the crowd, the last ticks of the
// pitch clock. Browsers only allow sound after a click or key press, which
// every pitch is.

let ctx = null;
let enabled = true;
let noiseBuf = null;

export function setSound(on) { enabled = !!on; }

function audio() {
    if (!enabled) return null;
    try {
        const AC = window.AudioContext ?? window.webkitAudioContext;
        if (!AC) return null;
        ctx ??= new AC();
        if (ctx.state === 'suspended') ctx.resume();
        return ctx;
    } catch {
        return null;
    }
}

// White noise through a filter, fading out: thumps, cracks and crowds.
function noise(c, { dur, type, freq, q = 1, gain, attack = 0.002, at = 0 }) {
    if (!noiseBuf) {
        noiseBuf = c.createBuffer(1, c.sampleRate, c.sampleRate);
        const d = noiseBuf.getChannelData(0);
        for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    const t = c.currentTime + at;
    const src = c.createBufferSource();
    src.buffer = noiseBuf;
    src.loop = true;
    const f = c.createBiquadFilter();
    f.type = type;
    f.frequency.value = freq;
    f.Q.value = q;
    const g = c.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(f).connect(g).connect(c.destination);
    src.start(t, Math.random() * 0.5);
    src.stop(t + dur + 0.02);
}

function tone(c, { freq, to = freq, dur, gain, type = 'sine', at = 0 }) {
    const t = c.currentTime + at;
    const o = c.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    o.frequency.exponentialRampToValueAtTime(to, t + dur);
    const g = c.createGain();
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(c.destination);
    o.start(t);
    o.stop(t + dur + 0.02);
}

export const sfx = {
    // The ball hits the catcher's glove.
    pop(quiet = false) {
        const c = audio();
        if (!c) return;
        const k = quiet ? 0.5 : 1;
        noise(c, { dur: 0.09, type: 'lowpass', freq: 900, gain: 0.5 * k });
        tone(c, { freq: 170, to: 70, dur: 0.1, gain: 0.35 * k });
    },
    // Bat on ball.
    crack(quiet = false) {
        const c = audio();
        if (!c) return;
        const k = quiet ? 0.5 : 1;
        noise(c, { dur: 0.06, type: 'bandpass', freq: 2600, q: 0.8, gain: 0.6 * k });
        tone(c, { freq: 1150, to: 520, dur: 0.07, gain: 0.25 * k, type: 'triangle' });
    },
    // The crowd: a swell for a good moment, a low groan for a bad one.
    crowd(good = true) {
        const c = audio();
        if (!c) return;
        noise(c, { dur: good ? 1.3 : 0.9, type: 'bandpass', freq: good ? 1300 : 420, q: 0.5, gain: good ? 0.16 : 0.12, attack: good ? 0.25 : 0.15, at: 0.12 });
    },
    // The pitch clock's last seconds.
    tick() {
        const c = audio();
        if (!c) return;
        tone(c, { freq: 880, dur: 0.05, gain: 0.08, type: 'square' });
    },
};
