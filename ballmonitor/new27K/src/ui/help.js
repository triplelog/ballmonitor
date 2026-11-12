// How to play: the same words on the menu and in the game's Help window.

export const HOW_TO_STEPS = `
    <li><b>Choose a pitch</b> and set your velocity and movement effort. More effort means more speed or break, but less control and more fatigue. The dashed line shows how the pitch will break, and the ring at its end how far it may scatter.</li>
    <li><b>Press Pitch</b> (or Space, or the field). The strike zone jumps to a new spot and starts to wander. With the break guide set to hidden, the line disappears now, so remember it.</li>
    <li><b>Click where to aim.</b> On a touch screen, put a finger down, drag to adjust, and lift to throw. The ball comes in on that spot, breaks from there and scatters by your control.</li>
    <li><b>Beat the pitch clock</b> (20 seconds unless you change it; it appears for the last 10). Run out of time and it’s a ball.</li>
    <li><b>Stuck?</b> Once an inning, call a <b>catcher’s visit</b>: it stops and resets the clock, and he’ll tell you what to throw this hitter.</li>`;

export function helpHTML({ first = false } = {}) {
    return `<div class="overlay" data-act="help-close"><div class="panel help" role="dialog" aria-label="How to play">
        <h2>${first ? 'Welcome to 27K' : 'How to play'}</h2>
        <p class="muted">You are the pitcher. Get 27 outs before they score more than your hitters do.</p>
        <ol class="help-steps">${HOW_TO_STEPS}</ol>
        <div class="help-cols">
            <div>
                <h3>Reading the field</h3>
                <ul>
                    <li><b>White box:</b> the strike zone. Pitches on its edges are the hardest to hit, and the umpire doesn’t always give them.</li>
                    <li><b>Numbered dots:</b> this at-bat’s pitches, in each pitch’s colour. Solid ones were strikes; a white rim means he swung.</li>
                    <li><b>Energy bar:</b> a tired pitcher throws slower and wilder, and the zone moves faster. The Bullpen tab brings in a reliever.</li>
                    <li><b>Batter tab:</b> his ratings, his hot (red) and cold (blue) spots, and how he hits each pitch type.</li>
                    <li><b>Mixing it up:</b> a hitter does worse against a pitch he hasn’t seen this at-bat, and after a change of speed or location.</li>
                </ul>
            </div>
            <div>
                <h3 class="no-touch">Keys</h3>
                <table class="grid help-keys no-touch">
                    <tr><td><span class="kbd">Space</span></td><td>Pitch · skip ahead · sim your batter</td></tr>
                    <tr><td><span class="kbd">1</span>–<span class="kbd">9</span></td><td>Choose a pitch</td></tr>
                    <tr><td><span class="kbd">F</span> <span class="kbd">S</span> <span class="kbd">C</span> …</td><td>Each pitch’s own letter (on its button)</td></tr>
                    <tr><td><span class="kbd">?</span></td><td>This help</td></tr>
                    <tr><td><span class="kbd">Esc</span></td><td>Close a window</td></tr>
                </table>
                <h3>Under the field</h3>
                <ul>
                    <li><b>Heat map</b> paints his hot and cold spots on the zone.</li>
                    <li><b>Odds</b> shows the chances behind each pitch after it lands.</li>
                    <li><b>Catcher calls pitches</b> has him pick the pitch and the spot; your job is to hit it.</li>
                </ul>
            </div>
        </div>
        <div class="row-actions">
            <span class="muted" style="font-size:12px">Every rule here is a formula you can change in the Formula Lab.</span>
            <button class="primary" data-act="help-close">${first ? 'Play ball' : 'Back to the game'}</button>
        </div>
    </div></div>`;
}
