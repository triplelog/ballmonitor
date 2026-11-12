// Draws the view from behind the plate (a right-handed batter on the left,
// pitches coming toward you): batter, plate, the moving strike zone, earlier pitches in the at-bat, the aiming guide and the pitch in
// flight. Everything is in inches; (0, 0) is the zone's home position.

import { ZONE, HEAT } from '../engine/data.js';

const VIEW = { left: -30, right: 30, top: 29, bottom: -32 };
const GROUND = -28;
// Where the pieces of the ballpark sit on the screen (inches, like VIEW).
const FIELD = { standsTop: 20.5, wallTop: 11.2, wallBottom: 8.4, mound: -6.2, dirtTop: GROUND + 7 };

export class PlateView {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.resize();
    }

    resize() {
        const rect = this.canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        const w = Math.max(200, rect.width);
        const h = w * (VIEW.top - VIEW.bottom) / (VIEW.right - VIEW.left);
        this.canvas.style.height = h + 'px';
        this.canvas.width = Math.round(w * dpr);
        this.canvas.height = Math.round(h * dpr);
        this.scale = this.canvas.width / (VIEW.right - VIEW.left);
        // The ballpark never changes, so it is painted once per size and
        // copied in each frame.
        this.field = document.createElement('canvas');
        this.field.width = this.canvas.width;
        this.field.height = this.canvas.height;
        this.drawField(this.field.getContext('2d'));
    }

    px(x) { return (x - VIEW.left) * this.scale; }
    py(y) { return (VIEW.top - y) * this.scale; }
    len(d) { return d * this.scale; }

    // Mouse event → inches.
    toInches(evt) {
        const rect = this.canvas.getBoundingClientRect();
        const fx = (evt.clientX - rect.left) / rect.width;
        const fy = (evt.clientY - rect.top) / rect.height;
        return {
            x: VIEW.left + fx * (VIEW.right - VIEW.left),
            y: VIEW.top - fy * (VIEW.top - VIEW.bottom),
        };
    }

    // v: { zone: {x, y}, side, heat, showHeat, pitches, aim, guide, plan,
    //      flight, banner, clock, dim }
    draw(v) {
        const c = this.ctx;
        const W = this.canvas.width;
        const H = this.canvas.height;
        c.clearRect(0, 0, W, H);

        c.drawImage(this.field, 0, 0);
        this.drawBatter(v.batter ?? (v.side ? { side: v.side, time: 0 } : null));

        const zx = v.zone.x;
        const zy = v.zone.y;
        if (v.showHeat && v.heat) this.drawHeat(zx, zy, v.heat, v.side === 'L');
        this.drawZone(zx, zy, v.zoneColor);

        (v.pitches || []).forEach((p, i) => {
            if (p.x === undefined) return;
            this.drawMarker(zx + p.x, zy + p.y, p.color, i + 1, p.call);
        });

        if (v.plan) this.drawPlan(v.plan);
        if (v.aim) this.drawAim(v.aim, v.guide);
        if (v.flight) this.drawFlight(v.flight);
        if (v.impact) this.drawImpact(v.impact);
        if (v.clock) this.drawClock(v.clock, v.side);
        if (v.dim) {
            c.fillStyle = 'rgba(0,0,0,0.35)';
            c.fillRect(0, 0, W, H);
        }
        if (v.banner) this.drawBanner(v.banner);
    }

    // The ballpark at night, seen from behind the plate: sky and lights, the
    // stands, the outfield wall, mowed grass, the mound with the pitcher on
    // it, and the dirt around home with its chalk. Kept dark and soft so the
    // zone, the ball and the markers stand out.
    drawField(c) {
        const W = this.canvas.width;
        const H = this.canvas.height;
        const X = (x) => this.px(x);
        const Y = (y) => this.py(y);
        const L = (d) => this.len(d);
        const rnd = seeded(27);
        const ellipse = (x, y, rx, ry, fill) => {
            c.fillStyle = fill;
            c.beginPath();
            c.ellipse(X(x), Y(y), L(rx), L(ry), 0, 0, Math.PI * 2);
            c.fill();
        };

        // Sky, with the glow of two light towers.
        const sky = c.createLinearGradient(0, 0, 0, Y(FIELD.standsTop));
        sky.addColorStop(0, '#060b17');
        sky.addColorStop(1, '#13233b');
        c.fillStyle = sky;
        c.fillRect(0, 0, W, Y(FIELD.standsTop) + 1);
        for (const x of [-21, 21]) {
            const glow = c.createRadialGradient(X(x), Y(26.5), 0, X(x), Y(26.5), L(13));
            glow.addColorStop(0, 'rgba(255, 244, 214, 0.5)');
            glow.addColorStop(0.25, 'rgba(255, 244, 214, 0.14)');
            glow.addColorStop(1, 'rgba(255, 244, 214, 0)');
            c.fillStyle = glow;
            c.fillRect(X(x) - L(13), 0, L(26), L(16));
            // the tower: a pole and a bank of lamps
            c.fillStyle = '#0b1220';
            c.fillRect(X(x) - L(0.25), Y(26), L(0.5), Y(FIELD.standsTop) - Y(26));
            c.fillStyle = '#1b2638';
            c.fillRect(X(x) - L(3), Y(27.6), L(6), L(2.2));
            c.fillStyle = '#fff6dc';
            for (let r = 0; r < 2; r++) for (let k = 0; k < 6; k++) {
                c.beginPath();
                c.arc(X(x) - L(2.5) + L(k), Y(27.1 - r * 0.95), L(0.3), 0, Math.PI * 2);
                c.fill();
            }
        }

        // The stands: tiers of seats and a crowd of dots.
        const stands = c.createLinearGradient(0, Y(FIELD.standsTop), 0, Y(FIELD.wallTop));
        stands.addColorStop(0, '#141d2c');
        stands.addColorStop(1, '#1d2a3d');
        c.fillStyle = stands;
        c.fillRect(0, Y(FIELD.standsTop), W, Y(FIELD.wallTop) - Y(FIELD.standsTop) + 1);
        const crowd = ['#c9d2e0', '#e8c170', '#d76a5c', '#7fa7d9', '#9aa5b5', '#f1ede4'];
        const rows = 9;
        for (let r = 0; r < rows; r++) {
            const y = FIELD.standsTop - 0.6 - r * (FIELD.standsTop - FIELD.wallTop - 0.8) / rows;
            for (let x = VIEW.left + rnd() * 0.8; x < VIEW.right; x += 0.75 + rnd() * 0.5) {
                if (rnd() < 0.18) continue;     // an empty seat
                c.globalAlpha = 0.22 + rnd() * 0.3;
                c.fillStyle = crowd[Math.floor(rnd() * crowd.length)];
                c.beginPath();
                c.arc(X(x), Y(y + rnd() * 0.3), L(0.26), 0, Math.PI * 2);
                c.fill();
            }
        }
        c.globalAlpha = 1;
        c.fillStyle = 'rgba(8, 12, 22, 0.35)';      // aisles
        for (const x of [-20, -7, 7, 20]) c.fillRect(X(x) - L(0.3), Y(FIELD.standsTop), L(0.6), Y(FIELD.wallTop) - Y(FIELD.standsTop));

        // The outfield wall, with its yellow line and the distance to centre.
        const wall = c.createLinearGradient(0, Y(FIELD.wallTop), 0, Y(FIELD.wallBottom));
        wall.addColorStop(0, '#12382a');
        wall.addColorStop(1, '#0d2a20');
        c.fillStyle = wall;
        c.fillRect(0, Y(FIELD.wallTop), W, Y(FIELD.wallBottom) - Y(FIELD.wallTop) + 1);
        c.fillStyle = '#d9b54a';
        c.fillRect(0, Y(FIELD.wallTop), W, Math.max(1, L(0.22)));
        c.fillStyle = 'rgba(255, 255, 255, 0.5)';
        c.font = `700 ${Math.round(L(1.5))}px system-ui, sans-serif`;
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillText('400', X(0), Y((FIELD.wallTop + FIELD.wallBottom) / 2 - 0.1));

        // Grass, mowed in bands that widen toward you.
        const top = FIELD.wallBottom;
        const span = top - VIEW.bottom;
        const bands = 11;
        const edge = (k) => top - span * Math.pow(k / bands, 1.7);
        for (let k = 0; k < bands; k++) {
            const depth = k / (bands - 1);
            const light = k % 2 === 0;
            c.fillStyle = mixColor(light ? '#1c5233' : '#184a2d', light ? '#236440' : '#1f5a39', depth);
            c.fillRect(0, Y(edge(k)), W, Y(edge(k + 1)) - Y(edge(k)) + 1);
        }
        // The far edge of the infield dirt, and the mound.
        ellipse(0, FIELD.mound + 3.6, 44, 1.5, 'rgba(122, 86, 52, 0.55)');
        ellipse(0, FIELD.mound - 0.6, 8.5, 1.7, '#6f4d2f');
        ellipse(0, FIELD.mound - 0.3, 7.6, 1.25, '#80593a');
        c.fillStyle = '#efece3';
        c.fillRect(X(-0.9), Y(FIELD.mound - 0.1), L(1.8), Math.max(1, L(0.3)));
        this.drawPitcher(c);

        // The dirt around home plate, and the chalk of the batter's boxes.
        const dirt = c.createLinearGradient(0, Y(FIELD.dirtTop), 0, H);
        dirt.addColorStop(0, '#6b4a2d');
        dirt.addColorStop(1, '#86603a');
        c.fillStyle = dirt;
        c.beginPath();
        c.ellipse(X(0), Y(VIEW.bottom - 2), L(47), L(FIELD.dirtTop - VIEW.bottom + 2), 0, 0, Math.PI * 2);
        c.fill();
        // a few scuffs so the dirt isn't flat
        for (let i = 0; i < 70; i++) {
            const x = VIEW.left + rnd() * (VIEW.right - VIEW.left);
            const y = VIEW.bottom + rnd() * (FIELD.dirtTop - VIEW.bottom - 2.5);
            c.fillStyle = rnd() < 0.5 ? 'rgba(0, 0, 0, 0.08)' : 'rgba(255, 235, 200, 0.06)';
            c.beginPath();
            c.ellipse(X(x), Y(y), L(0.6 + rnd() * 1.6), L(0.15 + rnd() * 0.25), 0, 0, Math.PI * 2);
            c.fill();
        }
        c.strokeStyle = 'rgba(244, 241, 234, 0.55)';
        c.lineWidth = Math.max(1, L(0.3));
        c.lineJoin = 'round';
        for (const d of [-1, 1]) {
            c.beginPath();
            c.moveTo(X(d * 12.5), Y(VIEW.bottom - 1));
            c.lineTo(X(d * 11), Y(GROUND + 5));
            c.lineTo(X(d * 27), Y(GROUND + 5));
            c.lineTo(X(d * 31.5), Y(VIEW.bottom - 1));
            c.stroke();
        }

        // Darker toward the corners, so the eye stays on the zone.
        const vig = c.createRadialGradient(W / 2, H * 0.46, H * 0.3, W / 2, H * 0.46, H * 0.85);
        vig.addColorStop(0, 'rgba(0, 0, 0, 0)');
        vig.addColorStop(1, 'rgba(0, 0, 0, 0.42)');
        c.fillStyle = vig;
        c.fillRect(0, 0, W, H);
        this.drawPlate(c);
    }

    // The pitcher, far away on the mound: a small grey figure at the set.
    drawPitcher(c) {
        const X = (x) => this.px(x);
        const Y = (y) => this.py(y);
        const L = (d) => this.len(d);
        const y0 = FIELD.mound;
        const line = (pts, w, color) => {
            c.strokeStyle = color;
            c.lineWidth = L(w);
            c.lineCap = 'round';
            c.lineJoin = 'round';
            c.beginPath();
            pts.forEach(([x, y], i) => (i ? c.lineTo(X(x), Y(y0 + y)) : c.moveTo(X(x), Y(y0 + y))));
            c.stroke();
        };
        c.fillStyle = 'rgba(0, 0, 0, 0.25)';
        c.beginPath();
        c.ellipse(X(0.3), Y(y0 - 0.05), L(1.5), L(0.3), 0, 0, Math.PI * 2);
        c.fill();
        line([[-0.45, 0.1], [-0.35, 2.3]], 0.6, '#c9ccd1');      // legs
        line([[0.45, 0.1], [0.35, 2.3]], 0.6, '#c9ccd1');
        line([[0, 2.2], [0, 4.1]], 1.35, '#b9bdc4');            // jersey
        line([[-0.7, 3.9], [-0.9, 3], [-0.1, 3.1]], 0.5, '#b9bdc4');   // glove arm, hands together
        line([[0.7, 3.9], [0.9, 3], [0.1, 3.1]], 0.5, '#b9bdc4');
        c.fillStyle = '#7a5a3c';                                // glove
        c.beginPath();
        c.arc(X(0), Y(y0 + 3.1), L(0.42), 0, Math.PI * 2);
        c.fill();
        c.fillStyle = '#c99873';                                // head and cap
        c.beginPath();
        c.arc(X(0), Y(y0 + 4.95), L(0.55), 0, Math.PI * 2);
        c.fill();
        c.fillStyle = '#28303d';
        c.beginPath();
        c.arc(X(0), Y(y0 + 5.05), L(0.58), Math.PI, 0);
        c.fill();
        c.fillRect(X(-0.75), Y(y0 + 5.08), L(1.5), Math.max(1, L(0.14)));
    }

    drawPlate(c = this.ctx) {
        const y = GROUND + 1.5;
        c.fillStyle = '#f4f1ea';
        c.beginPath();
        c.moveTo(this.px(-8.5), this.py(y));
        c.lineTo(this.px(8.5), this.py(y));
        c.lineTo(this.px(8.5), this.py(y - 1.5));
        c.lineTo(this.px(0), this.py(y - 3.5));
        c.lineTo(this.px(-8.5), this.py(y - 1.5));
        c.closePath();
        c.fill();
        c.strokeStyle = 'rgba(0, 0, 0, 0.35)';
        c.lineWidth = Math.max(1, this.len(0.2));
        c.stroke();
    }

    // The batter, seen from behind the plate (where this view is: a
    // right-handed batter on the left, the ball coming toward you). He
    // stands in the box beside the plate, side-on: feet and shoulders lined
    // up toward the mound (parallel to the edge of the plate), looking out at
    // the pitcher with his back half to you. He is posed in 3D, in his own
    // inches (x toward the plate, y up, z toward the mound), and drawn from a
    // camera a little above and behind the plate, so his front foot (nearer
    // the mound) sits higher and smaller on the screen than his back foot.
    // b: { side, color, number, skin, time, swing (0–1, contact at 0.5, or null) }
    drawBatter(b) {
        if (!b || !b.side) return;
        const c = this.ctx;
        const dir = b.side === 'R' ? 1 : -1;      // +1: the plate is to his screen right
        const S = 0.68;                           // stylised: smaller than life, so he fits the view
        const baseX = -dir * 23.5;                // his feet, from the middle of the plate
        const P = ([x, y, z]) => [this.px(baseX + dir * x * S), this.py(GROUND + 0.5 + S * (y + 0.25 * z))];
        const L = (d, z = 0) => this.len(d * S * (1 - z * 0.006));
        const line = (pts, width, color) => {
            c.strokeStyle = color;
            c.lineWidth = L(width, pts[0][2]);
            c.lineCap = 'round';
            c.lineJoin = 'round';
            c.beginPath();
            pts.forEach((p, i) => { const [X, Y] = P(p); if (i) c.lineTo(X, Y); else c.moveTo(X, Y); });
            c.stroke();
        };
        const fill = (pts, color) => {
            c.fillStyle = color;
            c.beginPath();
            pts.forEach(([X, Y], i) => { if (i) c.lineTo(X, Y); else c.moveTo(X, Y); });
            c.closePath();
            c.fill();
        };
        const dot = (p, r, color) => {
            const [X, Y] = P(p);
            c.fillStyle = color;
            c.beginPath();
            c.arc(X, Y, L(r, p[2]), 0, Math.PI * 2);
            c.fill();
        };
        const color = b.color || '#2a4b8d';
        const dark = shade(color, -0.4);
        const pants = '#e9e6dc';
        const skin = b.skin || '#c68b59';

        const pose = batterPose(b.swing, b.time ?? 0);
        const { hands, frontFoot, backFoot } = pose;
        const deg = Math.PI / 180;
        const yaw = (psi) => ({ u: [-Math.sin(psi * deg), 0, Math.cos(psi * deg)], n: [Math.cos(psi * deg), 0, Math.sin(psi * deg)] });
        const sh = yaw(pose.psi);         // u: back → front shoulder; n: the way his chest faces
        const hp = yaw(pose.hipPsi);
        const sc = pose.shoulders;
        const hc = [-1.5, 34, pose.shoulders[2] * 0.4];
        const frontSh = add(sc, mul(sh.u, 8));
        const backSh = add(sc, mul(sh.u, -8));
        const frontHip = add(hc, mul(hp.u, 5));
        const backHip = add(hc, mul(hp.u, -5));

        // Body parts, each drawn far to near (the camera looks toward +z).
        const leg = (hip, foot, heelUp) => () => {
            const knee = joint(hip, foot, 17, 16.5, [1, 0.15, 0]);
            line([hip, knee, foot], 6.5, pants);
            line([lerp3(knee, foot, 0.6), add(foot, [0, 1, 0])], 4.8, color);
            const heel = add(foot, [-2.5, -1.2 + heelUp * 3, 0]);
            const toe = add(foot, [6.5, -2, 0]);
            line([heel, toe], 3.6, '#1a1a1a');
        };
        const armParts = (shoulder, pole) => {
            const elbow = joint(shoulder, hands, 11.5, 11, pole);
            return { z: (shoulder[2] + elbow[2] + hands[2]) / 3, draw: () => { line([shoulder, elbow, hands], 3.6, color); dot(hands, 2, skin); } };
        };
        const bat = () => {
            const d = pose.batDir;
            const knob = add(hands, mul(d, -2.5));
            const tip = add(hands, mul(d, 31));
            const [kx, ky] = P(knob);
            const [tx, ty] = P(tip);
            const grad = c.createLinearGradient(kx, ky, tx, ty);
            grad.addColorStop(0, '#8a5a2b');
            grad.addColorStop(1, '#e2b97a');
            c.strokeStyle = grad;
            c.lineCap = 'round';
            // taper: handle thin, barrel thick
            for (const [from, to, w] of [[0, 0.45, 1.1], [0.4, 0.75, 1.9], [0.7, 1, 2.6]]) {
                c.lineWidth = L(w, (knob[2] + tip[2]) / 2);
                c.beginPath();
                c.moveTo(kx + (tx - kx) * from, ky + (ty - ky) * from);
                c.lineTo(kx + (tx - kx) * to, ky + (ty - ky) * to);
                c.stroke();
            }
        };

        // Torso: a box from the shoulders to the hips. Fill its outline, then
        // shade the sides that face you; his number is on the back.
        const top = [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([a, k]) => add(sc, add(mul(sh.u, 8.5 * a), mul(sh.n, 4.5 * k))));
        const bottom = [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([a, k]) => add(add(hc, [0, -1, 0]), add(mul(hp.u, 6.5 * a), mul(hp.n, 4.5 * k))));
        const torso = () => {
            fill(hull([...top, ...bottom].map(P)), shade(color, -0.15));
            // faces: [corner indices, outward normal]; the camera sees -z
            const faces = [[[0, 1], sh.u], [[1, 2], mul(sh.n, -1)], [[2, 3], mul(sh.u, -1)], [[3, 0], sh.n]];
            for (const [[i, j], nrm] of faces) {
                if (nrm[2] >= -0.05) continue;
                fill([top[i], top[j], bottom[j], bottom[i]].map(P), shade(color, -0.12 * nrm[2] - 0.05 * Math.abs(nrm[0])));
            }
            const belt = [[1, 1], [1, -1], [-1, -1], [-1, 1]].map(([a, k]) => add(hc, add(mul(hp.u, 6.6 * a), mul(hp.n, 4.6 * k))));
            fill(hull([...belt, ...belt.map((p) => add(p, [0, 2.2, 0]))].map(P)), '#222');
            // the number, on his back as it turns toward you
            const back = mul(sh.n, -1);
            if (back[2] < -0.3 && b.number != null) {
                const mid = lerp3(lerp3(top[1], top[2], 0.5), lerp3(bottom[1], bottom[2], 0.5), 0.4);
                const [NX, NY] = P(mid);
                c.save();
                c.translate(NX, NY);
                c.scale(Math.min(1, -back[2] * 1.1), 1);
                c.fillStyle = '#fff';
                c.font = `800 ${Math.round(L(7.5, mid[2]))}px system-ui, sans-serif`;
                c.textAlign = 'center';
                c.textBaseline = 'middle';
                c.fillText(String(b.number), 0, 0);
                c.restore();
            }
        };
        // Neck and head: he looks out at the pitcher, so you see the back of
        // his helmet, with the ear flap on the side toward the mound.
        const head = add(sc, [1.5, 8.8, 2.5]);
        const headPart = () => {
            line([add(sc, [0.5, 1, 0.5]), add(head, [0, -3.5, 0])], 3.4, skin);
            dot(head, 5, skin);
            const [HX, HY] = P(head);
            const hr = L(5.6, head[2]);
            c.fillStyle = dark;
            c.beginPath();
            c.ellipse(HX, HY - hr * 0.05, hr * 1.02, hr * 0.98, 0, Math.PI * 0.92, Math.PI * 0.08);
            c.fill();
            fill([add(head, [-5.2, 0, 0]), add(head, [-1.8, 0, 0.5]), add(head, [-2.3, -4.8, 1]), add(head, [-4.9, -3.6, 0.5])].map(P), dark);
        };

        const backArm = armParts(backSh, pose.backPole);
        const frontArm = armParts(frontSh, pose.frontPole);
        const batZ = hands[2] + 15 * pose.batDir[2];
        const parts = [
            { z: frontFoot[2], draw: leg(frontHip, frontFoot, 0) },
            { z: backFoot[2], draw: leg(backHip, backFoot, pose.heelUp) },
            frontArm, backArm,
            { z: batZ, draw: bat },
        ];
        const bodyZ = sc[2];

        c.save();
        c.globalAlpha = 0.92;
        // shadow on the dirt
        const [sx, sy] = P([1, 0, 0]);
        c.fillStyle = 'rgba(0,0,0,0.2)';
        c.beginPath();
        c.ellipse(sx, sy, L(10), L(4), 0, 0, Math.PI * 2);
        c.fill();
        const far = parts.filter((p) => p.z > bodyZ).sort((a, z) => z.z - a.z);
        const near = parts.filter((p) => p.z <= bodyZ).sort((a, z) => z.z - a.z);
        far.forEach((p) => p.draw());
        torso();
        headPart();
        near.forEach((p) => p.draw());
        c.restore();
    }

    drawHeat(zx, zy, heat, mirror) {
        const c = this.ctx;
        const x0 = zx - HEAT.cellW * HEAT.cols / 2;
        const y0 = zy + HEAT.cellH * HEAT.rows / 2;
        for (let r = 0; r < HEAT.rows; r++) {
            for (let col = 0; col < HEAT.cols; col++) {
                const src = mirror ? HEAT.cols - 1 - col : col;
                const v = heat[r * HEAT.cols + src];
                c.fillStyle = heatColor(v, 0.45);
                c.fillRect(
                    this.px(x0 + col * HEAT.cellW), this.py(y0 - r * HEAT.cellH),
                    this.len(HEAT.cellW) + 0.5, this.len(HEAT.cellH) + 0.5,
                );
            }
        }
    }

    drawZone(zx, zy, color = '#ffffff') {
        const c = this.ctx;
        const x = this.px(zx - ZONE.halfW);
        const y = this.py(zy + ZONE.halfH);
        const w = this.len(2 * ZONE.halfW);
        const h = this.len(2 * ZONE.halfH);
        c.save();
        c.fillStyle = 'rgba(4, 12, 9, 0.3)';
        c.fillRect(x, y, w, h);
        c.strokeStyle = 'rgba(255,255,255,0.25)';
        c.lineWidth = Math.max(1, this.len(0.15));
        c.beginPath();
        for (let i = 1; i < 3; i++) {
            c.moveTo(x + (w * i) / 3, y);
            c.lineTo(x + (w * i) / 3, y + h);
            c.moveTo(x, y + (h * i) / 3);
            c.lineTo(x + w, y + (h * i) / 3);
        }
        c.stroke();
        c.strokeStyle = color;
        c.lineWidth = Math.max(2, this.len(0.35));
        c.strokeRect(x, y, w, h);
        c.restore();
    }

    drawMarker(x, y, color, n, call) {
        const c = this.ctx;
        const r = this.len(ZONE.ballR);
        c.save();
        c.beginPath();
        c.arc(this.px(x), this.py(y), r, 0, Math.PI * 2);
        const strike = call === 'called' || call === 'swinging' || call === 'foul' || call === 'inplay';
        c.fillStyle = color;
        c.globalAlpha = strike ? 0.95 : 0.45;
        c.fill();
        c.globalAlpha = 1;
        c.lineWidth = Math.max(1, this.len(0.25));
        c.strokeStyle = call === 'swinging' || call === 'foul' || call === 'inplay' ? '#fff' : 'rgba(0,0,0,0.5)';
        c.stroke();
        c.fillStyle = '#fff';
        c.font = `bold ${Math.round(r * 1.1)}px system-ui, sans-serif`;
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillText(String(n), this.px(x), this.py(y) + 1);
        c.restore();
    }

    drawAim(aim, guide) {
        const c = this.ctx;
        const ax = this.px(aim.x);
        const ay = this.py(aim.y);
        c.save();
        c.strokeStyle = 'rgba(255,255,255,0.9)';
        c.lineWidth = Math.max(1, this.len(0.2));
        const s = this.len(2);
        c.beginPath();
        c.moveTo(ax - s, ay); c.lineTo(ax + s, ay);
        c.moveTo(ax, ay - s); c.lineTo(ax, ay + s);
        c.stroke();
        if (guide) {
            const ex = this.px(aim.x + guide.dx);
            const ey = this.py(aim.y + guide.dy);
            c.setLineDash([this.len(0.8), this.len(0.6)]);
            c.strokeStyle = guide.color || '#ffd166';
            c.lineWidth = Math.max(1.5, this.len(0.3));
            c.beginPath();
            // The ball comes in on the aim point and drifts along this
            // line as it breaks.
            c.moveTo(ax, ay);
            c.lineTo(ex, ey);
            c.stroke();
            c.setLineDash([]);
            // an arrowhead where the break ends
            const ang = Math.atan2(ey - ay, ex - ax);
            const h = this.len(1.3);
            if (Math.hypot(ex - ax, ey - ay) > h * 1.5) {
                c.beginPath();
                c.moveTo(ex, ey);
                c.lineTo(ex - h * Math.cos(ang - 0.45), ey - h * Math.sin(ang - 0.45));
                c.lineTo(ex - h * Math.cos(ang + 0.45), ey - h * Math.sin(ang + 0.45));
                c.closePath();
                c.fillStyle = guide.color || '#ffd166';
                c.fill();
            }
            c.beginPath();
            c.arc(ex, ey, this.len(guide.scatter), 0, Math.PI * 2);
            c.fillStyle = 'rgba(255, 209, 102, 0.12)';
            c.fill();
            c.stroke();
            if (guide.label) {
                c.font = `700 ${Math.round(this.len(1.5))}px system-ui, sans-serif`;
                c.textAlign = 'center';
                c.textBaseline = 'top';
                c.lineWidth = this.len(0.35);
                c.strokeStyle = 'rgba(0,0,0,0.6)';
                const ly = ey + this.len(guide.scatter) + this.len(0.5);
                c.strokeText(guide.label, ex, ly);
                c.fillStyle = '#fff';
                c.fillText(guide.label, ex, ly);
            }
        }
        c.restore();
    }

    // The catcher's spot (his call, or a mound visit's plan): a dashed
    // target on the zone, labelled with the pitch.
    drawPlan({ x, y, color, label }) {
        const c = this.ctx;
        c.save();
        c.setLineDash([this.len(0.6), this.len(0.5)]);
        c.strokeStyle = color || '#fff';
        c.lineWidth = Math.max(1.5, this.len(0.3));
        c.beginPath();
        c.arc(this.px(x), this.py(y), this.len(ZONE.ballR * 1.6), 0, Math.PI * 2);
        c.stroke();
        c.setLineDash([]);
        c.fillStyle = color || '#fff';
        c.beginPath();
        c.arc(this.px(x), this.py(y), this.len(0.45), 0, Math.PI * 2);
        c.fill();
        if (label) {
            c.font = `800 ${Math.round(this.len(1.5))}px system-ui, sans-serif`;
            c.textAlign = 'center';
            c.textBaseline = 'bottom';
            const ly = this.py(y) - this.len(ZONE.ballR * 1.6 + 0.4);
            c.lineWidth = this.len(0.35);
            c.strokeStyle = 'rgba(0,0,0,0.6)';
            c.strokeText(label, this.px(x), ly);
            c.fillStyle = color || '#fff';
            c.fillText(label, this.px(x), ly);
        }
        c.restore();
    }

    // flight: { from, to, p (0–1), color } in screen inches
    drawFlight(f) {
        const c = this.ctx;
        const p = f.p;
        // Break is late: most of it in the last part of the flight.
        const bp = p * p;
        const x = f.from.x + (f.to.x - f.from.x) * bp;
        const y = f.from.y + (f.to.y - f.from.y) * bp;
        const r = this.len(ZONE.ballR * (0.35 + 0.65 * p));
        c.save();
        // trail
        c.strokeStyle = 'rgba(255,255,255,0.35)';
        c.lineWidth = Math.max(1, r * 0.6);
        c.beginPath();
        for (let i = 0; i <= 12; i++) {
            const q = (p * i) / 12;
            const tx = f.from.x + (f.to.x - f.from.x) * q * q;
            const ty = f.from.y + (f.to.y - f.from.y) * q * q;
            if (i === 0) c.moveTo(this.px(tx), this.py(ty)); else c.lineTo(this.px(tx), this.py(ty));
        }
        c.stroke();
        const bx = this.px(x);
        const by = this.py(y);
        const ball = c.createRadialGradient(bx - r * 0.35, by - r * 0.35, r * 0.1, bx, by, r);
        ball.addColorStop(0, '#ffffff');
        ball.addColorStop(1, '#d9d6cc');
        c.beginPath();
        c.arc(bx, by, r, 0, Math.PI * 2);
        c.fillStyle = ball;
        c.fill();
        c.strokeStyle = f.color;
        c.lineWidth = Math.max(1, r * 0.25);
        c.stroke();
        // seams, turning as it comes
        if (r > 4) {
            const spin = p * 9;
            c.strokeStyle = '#c0392b';
            c.lineWidth = Math.max(1, r * 0.12);
            for (const s of [-1, 1]) {
                c.beginPath();
                c.arc(bx + Math.cos(spin) * r * 1.05 * s, by + Math.sin(spin) * r * 1.05 * s, r * 0.85, spin + (s > 0 ? Math.PI * 0.72 : -Math.PI * 0.28), spin + (s > 0 ? Math.PI * 1.28 : Math.PI * 0.28));
                c.stroke();
            }
        }
        c.restore();
    }

    // A ring that spreads from where the pitch landed. t: 0–1.
    drawImpact({ x, y, t, color }) {
        const c = this.ctx;
        c.save();
        c.globalAlpha = Math.max(0, 1 - t) * 0.9;
        c.strokeStyle = color || '#fff';
        c.lineWidth = Math.max(1, this.len(0.35) * (1 - t * 0.6));
        c.beginPath();
        c.arc(this.px(x), this.py(y), this.len(ZONE.ballR * (1 + 1.6 * t)), 0, Math.PI * 2);
        c.stroke();
        c.restore();
    }

    // Drawn in the top corner away from the batter.
    drawClock({ left, total }, side) {
        const c = this.ctx;
        const x = side === 'L' ? this.len(5) : this.canvas.width - this.len(5);
        const y = this.len(5);
        const r = this.len(3.2);
        const frac = Math.max(0, left / total);
        c.save();
        c.beginPath();
        c.arc(x, y, r, 0, Math.PI * 2);
        c.fillStyle = 'rgba(0,0,0,0.45)';
        c.fill();
        c.beginPath();
        c.moveTo(x, y);
        c.arc(x, y, r, -Math.PI / 2, -Math.PI / 2 + frac * Math.PI * 2);
        c.closePath();
        c.fillStyle = left < 3 ? '#e5484d' : '#ffd166';
        c.fill();
        c.fillStyle = '#fff';
        c.font = `bold ${Math.round(r * 0.9)}px system-ui, sans-serif`;
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillText(String(Math.ceil(left)), x, y + this.len(5.2));
        c.restore();
    }

    drawBanner({ text, sub, color }) {
        const c = this.ctx;
        const W = this.canvas.width;
        const y = this.len(10);
        c.save();
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.font = `800 ${Math.round(this.len(4.2))}px system-ui, sans-serif`;
        c.lineWidth = this.len(0.8);
        c.strokeStyle = 'rgba(0,0,0,0.6)';
        c.strokeText(text, W / 2, y);
        c.fillStyle = color || '#fff';
        c.fillText(text, W / 2, y);
        if (sub) {
            c.font = `600 ${Math.round(this.len(2.2))}px system-ui, sans-serif`;
            c.strokeText(sub, W / 2, y + this.len(4.5));
            c.fillStyle = '#e8eef5';
            c.fillText(sub, W / 2, y + this.len(4.5));
        }
        c.restore();
    }
}

export function heatColor(v, alpha = 0.6) {
    const a = Math.min(1, Math.abs(v)) * alpha;
    return v >= 0 ? `rgba(229, 72, 77, ${a})` : `rgba(62, 99, 221, ${a})`;
}

// A small heat-map picture for the batter card.
export function drawHeatThumb(canvas, heat, mirror) {
    const dpr = window.devicePixelRatio || 1;
    const size = canvas.clientWidth || 110;
    canvas.width = size * dpr;
    canvas.height = size * dpr * (HEAT.rows * HEAT.cellH) / (HEAT.cols * HEAT.cellW);
    const c = canvas.getContext('2d');
    const cw = canvas.width / HEAT.cols;
    const ch = canvas.height / HEAT.rows;
    c.fillStyle = '#1b2430';
    c.fillRect(0, 0, canvas.width, canvas.height);
    for (let r = 0; r < HEAT.rows; r++) {
        for (let col = 0; col < HEAT.cols; col++) {
            const src = mirror ? HEAT.cols - 1 - col : col;
            c.fillStyle = heatColor(heat[r * HEAT.cols + src], 0.9);
            c.fillRect(col * cw, r * ch, cw + 0.5, ch + 0.5);
        }
    }
    c.strokeStyle = '#fff';
    c.lineWidth = 1.5 * dpr;
    c.strokeRect(cw, ch, cw * 3, ch * 3);
}

// A small repeatable random-number stream (so the crowd doesn't change
// between sizes).
function seeded(seed) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// Blend two #rrggbb colours (t = 0 gives a, 1 gives b).
function mixColor(a, b, t) {
    const x = parseInt(a.slice(1), 16);
    const y = parseInt(b.slice(1), 16);
    const ch = (s) => Math.round(((x >> s) & 255) + (((y >> s) & 255) - ((x >> s) & 255)) * t);
    return `rgb(${ch(16)}, ${ch(8)}, ${ch(0)})`;
}

// Lighten (amount > 0) or darken a #rrggbb colour.
function shade(hex, amount) {
    const n = parseInt(hex.slice(1), 16);
    const f = (v) => Math.round(Math.max(0, Math.min(255, amount < 0 ? v * (1 + amount) : v + (255 - v) * amount)));
    return `rgb(${f(n >> 16)}, ${f((n >> 8) & 255)}, ${f(n & 255)})`;
}

// ---------- the batter's pose ----------

const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a) => mul(a, 1 / (Math.hypot(...a) || 1));
const lerp3 = (a, b, t) => add(a, mul(sub(b, a), t));

// The middle joint (elbow, knee) of a limb from a to b with these segment
// lengths, bent toward `pole`.
function joint(a, b, l1, l2, pole) {
    const ab = sub(b, a);
    const d = Math.min(Math.hypot(...ab), l1 + l2 - 0.01);
    const axis = norm(ab);
    const along = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
    const h = Math.sqrt(Math.max(0, l1 * l1 - along * along));
    const p = norm(sub(pole, mul(axis, dot3(pole, axis))));
    return add(add(a, mul(axis, along)), mul(p, h));
}

// Convex hull of screen points (for the torso outline).
function hull(pts) {
    const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [];
    for (const q of p) {
        while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), q) <= 0) lower.pop();
        lower.push(q);
    }
    const upper = [];
    for (const q of p.slice().reverse()) {
        while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), q) <= 0) upper.pop();
        upper.push(q);
    }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
}

// Key poses of a right-handed swing in his own inches (x toward the plate,
// y up, z toward the mound): the stance, the stride, contact (0.5, when the
// ball arrives), extension and the finish. psi turns the shoulders and hips
// open toward the mound; the bat points along (theta, phi): theta 0 is
// across the plate, 90 at the mound, -90 back at the catcher.
const SWING_KEYS = [
    { at: 0, psi: 10, hipPsi: 6, hands: [-3, 55, -8], theta: -100, phi: 50, stride: 13, shoulders: [-1, 56, 0], heelUp: 0, backPole: [-0.3, 0.5, -1], frontPole: [0.2, -1, 0.3] },
    { at: 0.3, psi: 0, hipPsi: 0, hands: [-4, 55, -11], theta: -95, phi: 42, stride: 18, shoulders: [-1.5, 56, -2], heelUp: 0, backPole: [-0.3, 0.4, -1], frontPole: [0.2, -1, 0.3] },
    { at: 0.42, psi: 25, hipPsi: 40, hands: [0, 49, -6], theta: -45, phi: -8, stride: 18, shoulders: [-1.2, 55.5, 0], heelUp: 0.2, backPole: [0, -1, -0.5], frontPole: [0.1, -1, 0.2] },
    { at: 0.5, psi: 50, hipPsi: 62, hands: [5, 45, 3], theta: 4, phi: -6, stride: 18, shoulders: [-1, 55, 2], heelUp: 0.5, backPole: [0, -1, -0.2], frontPole: [0, -1, 0.2] },
    { at: 0.65, psi: 80, hipPsi: 80, hands: [7, 48, 11], theta: 80, phi: 8, stride: 18, shoulders: [-0.5, 55.5, 3], heelUp: 1, backPole: [0, -1, 0.2], frontPole: [0, -1, 0.4] },
    { at: 1, psi: 98, hipPsi: 88, hands: [-2, 63, 5], theta: 215, phi: 45, stride: 18, shoulders: [-0.5, 56, 3], heelUp: 1, backPole: [0.3, -0.6, 1], frontPole: [-0.5, -0.4, 1] },
];

function batterPose(swing, time) {
    const sw = swing == null ? 0 : Math.max(0, Math.min(1, swing));
    let i = 0;
    while (i < SWING_KEYS.length - 2 && sw > SWING_KEYS[i + 1].at) i++;
    const a = SWING_KEYS[i];
    const b = SWING_KEYS[i + 1];
    const raw = (sw - a.at) / (b.at - a.at);
    const t = raw * raw * (3 - 2 * raw);
    const mix = (k) => (Array.isArray(a[k]) ? lerp3(a[k], b[k], t) : a[k] + (b[k] - a[k]) * t);
    const pose = Object.fromEntries(Object.keys(a).map((k) => [k, mix(k)]));
    // A little waggle while he waits.
    if (swing == null) {
        const w = Math.sin(time * 2.6);
        pose.theta += w * 6;
        pose.hands = add(pose.hands, [0, w * 0.6, w * 0.4]);
    }
    const th = pose.theta * Math.PI / 180;
    const ph = pose.phi * Math.PI / 180;
    pose.batDir = [Math.cos(ph) * Math.cos(th), Math.sin(ph), Math.cos(ph) * Math.sin(th)];
    // The front foot lifts as he strides, then plants.
    const lift = sw < 0.3 ? Math.sin(Math.PI * sw / 0.3) * 3 : 0;
    pose.frontFoot = [0, 3 + lift, pose.stride];
    pose.backFoot = [0, 3, -13];
    pose.backArmFront = sw > 0.4;
    return pose;
}
