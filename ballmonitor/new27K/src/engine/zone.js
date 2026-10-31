// The moving strike zone. While you aim, the zone wanders: its speed, how
// sharply it turns (chaos) and how far it may drift are all formulas.

export class ZoneMover {
    constructor(F, rng) {
        this.F = F;
        this.rng = rng;
        this.x = 0;
        this.y = 0;
        this.heading = rng.range(0, 2 * Math.PI);
        this.t = 0;
        this.scope = null;
        this.range = 10;
        this.speed = 0;
        this.chaos = 0;
    }

    // scope: the situation variables (balls, strikes, fatigue, difficulty…)
    // The zone first jumps to a random spot at least half its range away,
    // so where it was before you pressed Pitch tells you nothing.
    start(scope) {
        this.scope = { ...scope };
        this.t = 0;
        this.range = this.F.eval('zoneRange', { ...this.scope, t: 0 });
        this.heading = this.rng.range(0, 2 * Math.PI);
        const r = this.range;
        let best = null;
        for (let i = 0; i < 12; i++) {
            const p = { x: this.rng.range(-r, r), y: this.rng.range(-r, r) };
            const d = Math.hypot(p.x - this.x, p.y - this.y);
            if (!best || d > best.d) best = { ...p, d };
            if (d >= r / 2) break;
        }
        this.x = best.x;
        this.y = best.y;
    }

    update(dt) {
        this.t += dt;
        const s = { ...this.scope, t: this.t };
        this.speed = this.F.eval('zoneSpeed', s);
        this.chaos = this.F.eval('zoneChaos', s);
        this.heading += this.rng.gauss() * this.chaos * Math.sqrt(dt);
        this.x += Math.cos(this.heading) * this.speed * dt;
        this.y += Math.sin(this.heading) * this.speed * dt;
        const r = this.range;
        if (this.x > r || this.x < -r) {
            this.x = Math.max(-r, Math.min(r, this.x));
            this.heading = Math.PI - this.heading;
        }
        if (this.y > r || this.y < -r) {
            this.y = Math.max(-r, Math.min(r, this.y));
            this.heading = -this.heading;
        }
    }
}
