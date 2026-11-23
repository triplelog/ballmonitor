// How to play: the same words on the menu and in the game's Help window.

export const HOW_TO_STEPS = `
    <li><b>Pick a pitch</b> and dial in your velocity and movement effort. Pushing harder adds speed or break, but widens your scatter and drains energy faster. The dashed line shows the break path, and the ring shows how much the pitch might miss by.</li>
    <li><b>Hit Pitch</b> (or press Space, or tap the field). The strike zone jumps and starts moving. If you hide the break guide, the dashed line disappears once the zone starts moving—so memorize the break first.</li>
    <li><b>Click to throw.</b> On a touchscreen, press and drag to aim, then lift your finger to release. The ball heads for your aim point, breaks from there, and scatters based on your control.</li>
    <li><b>Beat the pitch clock</b> (20 seconds by default; it pops up for the final 10). Let it hit zero and it’s an automatic ball.</li>
    <li><b>Need a plan?</b> Call a <b>catcher’s visit</b> (once per inning) to pause and reset the clock while your catcher recommends what to throw.</li>`;

export function helpHTML({ first = false } = {}) {
    return `<div class="overlay" data-act="help-close"><div class="panel help" role="dialog" aria-label="How to play">
        <h2>${first ? 'Welcome to 27K' : 'How to play'}</h2>
        <p class="muted">You’re on the mound. Record 27 outs and keep the other team from outscoring yours.</p>
        <ol class="help-steps">${HOW_TO_STEPS}</ol>
        <div class="help-cols">
            <div>
                <h3>Reading the field</h3>
                <ul>
                    <li><b>White box:</b> the strike zone. Pitches on its edges and corners are hardest to hit, though the umpire won’t call every borderline pitch.</li>
                    <li><b>Numbered dots:</b> pitches from this at-bat, color-coded by pitch type. Solid dots were strikes; a white ring means the batter swung.</li>
                    <li><b>Energy bar:</b> as your pitcher tires, velocity drops, scatter widens, and the zone moves faster. Open the Bullpen tab to bring in a reliever.</li>
                    <li><b>Batter tab:</b> check his ratings, hot (red) and cold (blue) zones, and how he’s fared against each pitch type.</li>
                    <li><b>Mix your pitches:</b> batters adjust when they see the same pitch repeatedly—changing speeds and locations keeps them off balance.</li>
                </ul>
            </div>
            <div>
                <h3 class="no-touch">Shortcuts</h3>
                <table class="grid help-keys no-touch">
                    <tr><td><span class="kbd">Space</span></td><td>Pitch · skip animation · sim batter</td></tr>
                    <tr><td><span class="kbd">1</span>–<span class="kbd">9</span></td><td>Select a pitch</td></tr>
                    <tr><td><span class="kbd">F</span> <span class="kbd">S</span> <span class="kbd">C</span> …</td><td>Pitch shortcut letter (shown on each button)</td></tr>
                    <tr><td><span class="kbd">?</span></td><td>Open this help window</td></tr>
                    <tr><td><span class="kbd">Esc</span></td><td>Close a window</td></tr>
                </table>
                <h3>Options below the field</h3>
                <ul>
                    <li><b>Heat map</b> overlays the batter’s hot and cold zones on the plate.</li>
                    <li><b>Odds</b> displays the underlying probabilities after each pitch lands.</li>
                    <li><b>Catcher calls pitches</b> lets your catcher suggest each pitch and target—just hit his spot (or shake him off).</li>
                </ul>
            </div>
        </div>
        <div class="row-actions">
            <span class="muted" style="font-size:12px">Every rule under the hood is a formula you can edit in the Formula Lab.</span>
            <button class="primary" data-act="help-close">${first ? 'Play ball' : 'Back to game'}</button>
        </div>
    </div></div>`;
}
