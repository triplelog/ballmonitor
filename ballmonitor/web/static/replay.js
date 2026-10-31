// Game replay renderer (cfb_replay). Draws one frame of a vertical 1080x1920 replay for
// any time t (seconds). Frames depend only on t and the model's extras, so the browser
// player and the video export (ballmonitor export-replay) produce identical frames.
// Plain canvas 2D, no dependencies. Exposes window.ReplayRenderer.

(function () {
  "use strict";

  const W = 1080, H = 1920;
  const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif';
  const BG = "#0b1020", PANEL = "#141b2d", PANEL_2 = "#1b2438", INK = "#f3f5f9", MUTED = "#8b95a8", LINE = "#2a3550";

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const ease = (x) => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
  const pct = (p) => `${Math.round(p * 100)}%`;

  function hexToRgb(hex) {
    const h = String(hex || "#888888").replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h.padEnd(6, "0").slice(0, 6), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function luminance(hex) {
    const [r, g, b] = hexToRgb(hex).map((c) => {
      const s = c / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  const rgba = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };

  // A team colour that reads on the dark background (fall back to the alternate colour,
  // then lighten, if the primary is too dark).
  function teamColor(team) {
    const c = /^#?[0-9a-f]{3,6}$/i.test(team.color || "") ? (team.color.startsWith("#") ? team.color : `#${team.color}`) : "#6b7280";
    if (luminance(c) >= 0.06) return c;
    const alt = team.alt_color && (team.alt_color.startsWith("#") ? team.alt_color : `#${team.alt_color}`);
    if (alt && luminance(alt) >= 0.06 && luminance(alt) <= 0.85) return alt;
    const [r, g, b] = hexToRgb(c);
    return `#${[r, g, b].map((v) => Math.round(v + (255 - v) * 0.45).toString(16).padStart(2, "0")).join("")}`;
  }

  // indent: width taken from the first line (a prefix drawn separately)
  function wrap(ctx, text, maxWidth, maxLines, indent = 0) {
    const words = String(text || "").split(/\s+/);
    const lines = [];
    let line = "";
    for (const w of words) {
      const test = line ? `${line} ${w}` : w;
      if (ctx.measureText(test).width + (lines.length ? 0 : indent) <= maxWidth) { line = test; continue; }
      if (line) lines.push(line);
      line = w;
      if (lines.length === maxLines) break;
    }
    if (lines.length < maxLines && line) lines.push(line);
    if (lines.length === maxLines && words.join(" ").length > lines.join(" ").length) {
      let last = lines[maxLines - 1];
      const room = maxWidth - (maxLines === 1 ? indent : 0);
      while (last && ctx.measureText(`${last}…`).width > room) last = last.slice(0, -1);
      lines[maxLines - 1] = `${last}…`;
    }
    return lines;
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  const quarterLabel = (q) => (q <= 4 ? `Q${q}` : q === 5 ? "OT" : `${q - 4}OT`);
  const ordinal = (n) => ({ 1: "1st", 2: "2nd", 3: "3rd", 4: "4th" }[n] || `${n}th`);

  class ReplayRenderer {
    constructor(extras) {
      this.e = extras;
      this.g = extras.game;
      this.plays = extras.plays || [];
      this.tl = extras.timeline || { duration_sec: 30, intro_sec: 1.5, outro_sec: 2.5 };
      this.duration = this.tl.duration_sec;
      this.home = this.g.home;
      this.away = this.g.away;
      this.hc = teamColor(this.home);
      this.ac = teamColor(this.away);
      this.top = new Set(extras.top_plays || []);
      this.sections = extras.structure === "sections" ? (extras.sections || []) : [];
      this.notes = extras.structure === "chart" ? (extras.annotations || []) : [];
    }

    // index of the play on screen at time t (-1 = intro, plays.length = outro)
    playAt(t) {
      if (t < this.tl.intro_sec || !this.plays.length) return -1;
      if (t >= this.duration - this.tl.outro_sec) return this.plays.length;
      let lo = 0, hi = this.plays.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (this.plays[mid].t_start <= t) lo = mid; else hi = mid - 1;
      }
      return lo;
    }

    // home win probability shown at time t (animates from before -> after within a play)
    wpAt(t) {
      const i = this.playAt(t);
      if (i < 0) return this.g.pregame_wp_home;
      if (i >= this.plays.length) return this.plays[this.plays.length - 1].wp_home_after;
      const p = this.plays[i];
      const span = Math.max(0.001, Math.min(0.35, (p.t_end - p.t_start) * 0.5));
      return p.wp_home_before + (p.wp_home_after - p.wp_home_before) * ease((t - p.t_start) / span);
    }

    draw(ctx, t) {
      t = clamp(t, 0, this.duration);
      ctx.save();
      ctx.textBaseline = "alphabetic";
      this.drawBackground(ctx);
      const i = this.playAt(t);
      if (i < 0) this.drawIntro(ctx, t);
      else if (this.notes.length) this.drawChartView(ctx, t, Math.min(i, this.plays.length - 1), i >= this.plays.length);
      else if (i >= this.plays.length) this.drawOutro(ctx, t);
      else this.drawGame(ctx, t, i);
      this.drawFooter(ctx);
      ctx.restore();
    }

    drawBackground(ctx) {
      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, W, H);
      const g1 = ctx.createRadialGradient(0, 0, 0, 0, 0, 900);
      g1.addColorStop(0, rgba(this.ac, 0.22)); g1.addColorStop(1, rgba(this.ac, 0));
      ctx.fillStyle = g1; ctx.fillRect(0, 0, W, H);
      const g2 = ctx.createRadialGradient(W, 0, 0, W, 0, 900);
      g2.addColorStop(0, rgba(this.hc, 0.22)); g2.addColorStop(1, rgba(this.hc, 0));
      ctx.fillStyle = g2; ctx.fillRect(0, 0, W, H);
    }

    drawFooter(ctx) {
      ctx.fillStyle = MUTED;
      ctx.font = `500 26px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillText(`Win probability: ${this.g.wp_source || "ESPN"}`, W / 2, H - 40);
    }

    // ── Intro: matchup card and pregame win probability ──────────────────────
    drawIntro(ctx, t) {
      const a = ease(t / 0.5);
      ctx.globalAlpha = a;
      ctx.textAlign = "center";
      ctx.fillStyle = MUTED;
      ctx.font = `600 34px ${FONT}`;
      ctx.fillText("GAME REPLAY", W / 2, 260);
      ctx.font = `500 30px ${FONT}`;
      ctx.fillText([this.dateText(), this.g.venue].filter(Boolean).join("  ·  "), W / 2, 310);

      this.teamBlock(ctx, this.away, this.ac, 120, 420, 840, 260, "AWAY");
      ctx.fillStyle = MUTED; ctx.font = `700 54px ${FONT}`; ctx.fillText("at", W / 2, 760);
      this.teamBlock(ctx, this.home, this.hc, 120, 800, 840, 260, "HOME");

      ctx.fillStyle = INK; ctx.font = `600 36px ${FONT}`; ctx.textAlign = "center";
      ctx.fillText("Pregame win probability", W / 2, 1230);
      this.wpBar(ctx, 120, 1270, 840, 70, this.g.pregame_wp_home);
      ctx.globalAlpha = 1;
    }

    teamBlock(ctx, team, color, x, y, w, h, tag) {
      roundRect(ctx, x, y, w, h, 28); ctx.fillStyle = PANEL; ctx.fill();
      roundRect(ctx, x, y, 22, h, 11); ctx.fillStyle = color; ctx.fill();
      ctx.textAlign = "left";
      ctx.fillStyle = MUTED; ctx.font = `600 28px ${FONT}`;
      ctx.fillText(tag + (team.record ? `  ·  ${team.record}` : ""), x + 60, y + 70);
      ctx.fillStyle = INK; ctx.font = `800 96px ${FONT}`;
      const rank = team.rank ? `#${team.rank} ` : "";
      ctx.fillText(`${rank}${team.abbr || team.short}`, x + 60, y + 170);
      ctx.fillStyle = MUTED; ctx.font = `500 34px ${FONT}`;
      ctx.fillText(team.name, x + 60, y + 225);
    }

    wpBar(ctx, x, y, w, h, wpHome) {
      const split = x + w * (1 - wpHome);
      roundRect(ctx, x, y, w, h, h / 2); ctx.save(); ctx.clip();
      ctx.fillStyle = this.ac; ctx.fillRect(x, y, split - x, h);
      ctx.fillStyle = this.hc; ctx.fillRect(split, y, x + w - split, h);
      ctx.restore();
      ctx.font = `800 36px ${FONT}`; ctx.fillStyle = "#ffffff";
      ctx.textAlign = "left"; ctx.fillText(`${this.away.abbr} ${pct(1 - wpHome)}`, x + 24, y + h / 2 + 13);
      ctx.textAlign = "right"; ctx.fillText(`${pct(wpHome)} ${this.home.abbr}`, x + w - 24, y + h / 2 + 13);
    }

    dateText() {
      const d = this.g.date ? new Date(this.g.date) : null;
      return d && !isNaN(d) ? d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "";
    }

    // ── Main game view ──────────────────────────────────────────────────────
    drawGame(ctx, t, i) {
      const p = this.plays[i];
      this.scoreboard(ctx, p, t);
      this.fieldBar(ctx, p);
      this.wpChart(ctx, t, i, 660, 470);
      // big plays cross-fade the feed into the highlight card (and back)
      // sequential, never overlapping: the feed (or chapter card) fades out, then the big-play
      // card fades in (reverse at the end)
      const mix = p.highlight ? this.cardAlpha(t, p) : 0;
      const sec = this.sections.length ? this.sections[p.section] : null;
      if (mix < 0.5) {
        ctx.globalAlpha = 1 - 2 * mix;
        if (sec) this.sectionCard(ctx, t, i, sec); else this.feed(ctx, t, i);
        ctx.globalAlpha = 1;
      } else this.highlightCard(ctx, t, p, 2 * mix - 1);
    }

    scoreboard(ctx, p, t) {
      const y = 90, h = 330;
      // every score is emphasised: the scoring team's number pops for the first 0.8 s
      const scored = p.scoring && t !== undefined ? clamp((t - p.t_start) / 0.8, 0, 1) : 1;
      const pulse = scored < 1 ? Math.sin(scored * Math.PI) : 0;
      const prev = p.idx > 0 ? this.plays[p.idx - 1] : { home_score: 0, away_score: 0 };
      const homeScored = p.home_score > prev.home_score, awayScored = p.away_score > prev.away_score;
      const side = (team, color, score, x, possession, align) => {
        roundRect(ctx, x, y, 420, h, 28); ctx.fillStyle = PANEL; ctx.fill();
        ctx.fillStyle = color; roundRect(ctx, x, y, 420, 16, 8); ctx.fill();
        ctx.textAlign = align;
        const tx = align === "left" ? x + 40 : x + 380;
        ctx.fillStyle = MUTED; ctx.font = `600 28px ${FONT}`;
        ctx.fillText(team.rank ? `#${team.rank}` : " ", tx, y + 70);
        ctx.fillStyle = INK; ctx.font = `800 64px ${FONT}`;
        ctx.fillText(team.abbr || team.short, tx, y + 135);
        const pop = (team === this.home ? homeScored : awayScored) ? pulse : 0;
        if (pop > 0) {
          ctx.save();
          ctx.shadowColor = color; ctx.shadowBlur = 60 * pop;
          ctx.font = `800 ${Math.round(150 * (1 + 0.18 * pop))}px ${FONT}`;
          ctx.fillText(String(score), tx, y + 290);
          ctx.restore();
          roundRect(ctx, x, y, 420, h, 28); ctx.strokeStyle = rgba(color, 0.9 * pop); ctx.lineWidth = 6; ctx.stroke();
        } else {
          ctx.font = `800 150px ${FONT}`;
          ctx.fillText(String(score), tx, y + 290);
        }
        if (possession) {
          ctx.fillStyle = color;
          const bx = align === "left" ? x + 380 : x + 40;
          ctx.beginPath(); ctx.arc(bx, y + 112, 14, 0, Math.PI * 2); ctx.fill();
        }
      };
      side(this.away, this.ac, p.away_score, 40, p.possession === "away", "left");
      side(this.home, this.hc, p.home_score, 620, p.possession === "home", "right");
      // centre: quarter / clock
      ctx.textAlign = "center";
      ctx.fillStyle = INK; ctx.font = `800 48px ${FONT}`;
      ctx.fillText(quarterLabel(p.quarter), W / 2, y + 130);
      ctx.fillStyle = MUTED; ctx.font = `700 44px ${FONT}`;
      ctx.fillText(p.clock || "", W / 2, y + 190);
    }

    fieldBar(ctx, p) {
      const x = 40, y = 450, w = W - 80, h = 150;
      roundRect(ctx, x, y, w, h, 24); ctx.fillStyle = PANEL; ctx.fill();
      const drive = p.kind === "drive";
      ctx.textAlign = "left"; ctx.fillStyle = INK; ctx.font = `700 38px ${FONT}`;
      const dd = drive ? `${(p.possession === "away" ? this.away : this.home).abbr} drive · ${p.drive_result || "Drive"}`
        : p.down && p.distance !== null && p.distance !== undefined
          ? `${ordinal(p.down)} & ${p.distance === 0 ? "Goal" : p.distance}` : (p.type || "");
      ctx.fillText(dd, x + 30, y + 52);
      ctx.textAlign = "right"; ctx.fillStyle = MUTED; ctx.font = `600 34px ${FONT}`;
      ctx.fillText(drive ? (p.drive_summary || "") : p.yardline_text ? `Ball on ${p.yardline_text}` : "", x + w - 30, y + 52);
      // field: away end zone on the left, home end zone on the right
      const fx = x + 30, fy = y + 78, fw = w - 60, fh = 46, ez = fw * 0.08;
      ctx.fillStyle = "#1f6f3f"; ctx.fillRect(fx + ez, fy, fw - 2 * ez, fh);
      ctx.fillStyle = this.ac; ctx.fillRect(fx, fy, ez, fh);
      ctx.fillStyle = this.hc; ctx.fillRect(fx + fw - ez, fy, ez, fh);
      ctx.strokeStyle = "rgba(255,255,255,0.35)"; ctx.lineWidth = 2;
      for (let yd = 10; yd < 100; yd += 10) {
        const lx = fx + ez + (fw - 2 * ez) * yd / 100;
        ctx.beginPath(); ctx.moveTo(lx, fy + 6); ctx.lineTo(lx, fy + fh - 6); ctx.stroke();
      }
      const toLeft = (yte) => (p.possession === "away" ? 100 - yte : yte);
      const xAt = (fromLeft) => fx + ez + (fw - 2 * ez) * clamp(fromLeft, 0, 100) / 100;
      if (drive && p.possession && p.yards_to_endzone != null && p.end_yards_to_endzone != null) {
        // a collapsed drive: shade the ground covered, ball at the last snap
        const a = xAt(toLeft(p.yards_to_endzone)), b = xAt(toLeft(p.end_yards_to_endzone));
        ctx.fillStyle = rgba(p.possession === "away" ? this.ac : this.hc, 0.55);
        ctx.fillRect(Math.min(a, b), fy + 8, Math.max(4, Math.abs(b - a)), fh - 16);
        ctx.fillStyle = "#ffffff"; ctx.strokeStyle = p.possession === "away" ? this.ac : this.hc; ctx.lineWidth = 5;
        ctx.beginPath(); ctx.ellipse(b, fy + fh / 2, 20, 13, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      } else if (p.possession && p.yards_to_endzone !== null && p.yards_to_endzone !== undefined) {
        // the offense drives toward the opponent's end zone: away attacks right, home attacks left
        const fromLeft = toLeft(p.yards_to_endzone);
        const bx = fx + ez + (fw - 2 * ez) * clamp(fromLeft, 0, 100) / 100;
        if (p.distance) {
          const toGo = p.possession === "away" ? fromLeft + p.distance : fromLeft - p.distance;
          const lx = fx + ez + (fw - 2 * ez) * clamp(toGo, 0, 100) / 100;
          ctx.strokeStyle = "#facc15"; ctx.lineWidth = 5;
          ctx.beginPath(); ctx.moveTo(lx, fy - 4); ctx.lineTo(lx, fy + fh + 4); ctx.stroke();
        }
        ctx.fillStyle = "#ffffff"; ctx.strokeStyle = p.possession === "away" ? this.ac : this.hc; ctx.lineWidth = 5;
        ctx.beginPath(); ctx.ellipse(bx, fy + fh / 2, 20, 13, 0, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      }
    }

    // Win-probability line for the whole game, drawn up to the current play.
    wpChart(ctx, t, i, y, h) {
      const x = 40, w = W - 80;
      roundRect(ctx, x, y, w, h, 24); ctx.fillStyle = PANEL; ctx.fill();
      const wp = this.wpAt(t);
      const lead = wp >= 0.5 ? this.home : this.away;
      const leadColor = wp >= 0.5 ? this.hc : this.ac;
      ctx.textAlign = "left"; ctx.fillStyle = MUTED; ctx.font = `600 30px ${FONT}`;
      ctx.fillText("WIN PROBABILITY", x + 30, y + 52);
      ctx.textAlign = "right"; ctx.fillStyle = leadColor; ctx.font = `800 64px ${FONT}`;
      ctx.fillText(`${lead.abbr} ${pct(Math.max(wp, 1 - wp))}`, x + w - 30, y + 70);

      const cx = x + 110, cy = y + 100, cw = w - 140, chh = h - 130;
      const n = this.plays.length;
      const px = (k) => cx + cw * (n > 1 ? k / (n - 1) : 0);
      const py = (v) => cy + chh * (1 - v);
      // 50% line + team labels
      ctx.strokeStyle = LINE; ctx.lineWidth = 2; ctx.setLineDash([10, 10]);
      ctx.beginPath(); ctx.moveTo(cx, py(0.5)); ctx.lineTo(cx + cw, py(0.5)); ctx.stroke(); ctx.setLineDash([]);
      ctx.font = `700 26px ${FONT}`; ctx.textAlign = "right";
      ctx.fillStyle = rgba(this.hc, 0.95); ctx.fillText(this.home.abbr, cx - 14, cy + 24);
      ctx.fillStyle = rgba(this.ac, 0.95); ctx.fillText(this.away.abbr, cx - 14, cy + chh);
      ctx.fillStyle = MUTED; ctx.font = `600 22px ${FONT}`; ctx.fillText("50%", cx - 14, py(0.5) + 8);
      // quarter dividers
      ctx.strokeStyle = "rgba(255,255,255,0.06)"; ctx.lineWidth = 2;
      for (let k = 1; k < n; k++) {
        if (this.plays[k].quarter !== this.plays[k - 1].quarter) {
          ctx.beginPath(); ctx.moveTo(px(k), cy); ctx.lineTo(px(k), cy + chh); ctx.stroke();
        }
      }
      // the current chapter's span
      const cur = this.sections.length && i < n ? this.sections[this.plays[i].section] : null;
      if (cur) {
        const sx = px(cur.first_play), ex = px(Math.min(n - 1, cur.last_play + 1));
        ctx.fillStyle = "rgba(255,255,255,0.06)"; ctx.fillRect(sx, cy, Math.max(4, ex - sx), chh);
      }
      // the line up to now, filled toward 50% in the leading team's colour
      const upto = Math.min(i, n - 1);
      const pts = [[px(0), py(this.plays[0].wp_home_before)]];
      for (let k = 0; k < upto; k++) pts.push([px(k + 1), py(this.plays[k].wp_home_after)]);
      pts.push([px(upto + (upto < n - 1 ? 1 : 0)), py(wp)]);
      const fill = (sideColor, clipTop) => {
        ctx.save();
        ctx.beginPath();
        if (clipTop) ctx.rect(cx, cy, cw, py(0.5) - cy); else ctx.rect(cx, py(0.5), cw, cy + chh - py(0.5));
        ctx.clip();
        ctx.beginPath(); ctx.moveTo(pts[0][0], py(0.5));
        for (const [a, b] of pts) ctx.lineTo(a, b);
        ctx.lineTo(pts[pts.length - 1][0], py(0.5)); ctx.closePath();
        ctx.fillStyle = rgba(sideColor, 0.28); ctx.fill();
        ctx.restore();
      };
      fill(this.hc, true); fill(this.ac, false);
      ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
      for (const [a, b] of pts) ctx.lineTo(a, b);
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 5; ctx.lineJoin = "round"; ctx.stroke();
      const [ex, ey] = pts[pts.length - 1];
      ctx.fillStyle = leadColor; ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(ex, ey, 12, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }

    // Chapter card: progress dots, title, summary, and the chapter's key plays lighting up.
    sectionCard(ctx, t, i, sec) {
      const x = 40, y = 1160, w = W - 80, h = 680;
      const enter = ease((t - sec.t_start) / 0.3);
      ctx.save();
      const base = ctx.globalAlpha;
      ctx.globalAlpha = base * enter;
      ctx.translate(0, (1 - enter) * 40);
      roundRect(ctx, x, y, w, h, 24); ctx.fillStyle = PANEL; ctx.fill();
      const swingColor = sec.swing >= 0 ? this.hc : this.ac;
      roundRect(ctx, x, y, 12, h, 6); ctx.fillStyle = swingColor; ctx.fill();
      // progress dots
      const n = this.sections.length, dot = 12, gap = 14;
      const dotsW = n * dot * 2 + (n - 1) * gap;
      for (let k = 0; k < n; k++) {
        const cx = x + w - 40 - dotsW + k * (dot * 2 + gap) + dot;
        ctx.beginPath(); ctx.arc(cx, y + 50, dot, 0, Math.PI * 2);
        ctx.fillStyle = k === sec.idx ? INK : k < sec.idx ? "rgba(255,255,255,0.45)" : "rgba(255,255,255,0.12)";
        ctx.fill();
      }
      const first = this.plays[sec.first_play], last = this.plays[sec.last_play];
      ctx.textAlign = "left"; ctx.fillStyle = MUTED; ctx.font = `600 28px ${FONT}`;
      ctx.fillText(`${sec.idx + 1} / ${n}  ·  ${quarterLabel(first.quarter)} ${first.clock} – ${quarterLabel(last.quarter)} ${last.clock}`, x + 40, y + 60);
      // the title shrinks to fit one line rather than being cut off
      let size = 52;
      ctx.font = `800 ${size}px ${FONT}`;
      while (size > 34 && ctx.measureText(sec.title).width > w - 80) { size -= 2; ctx.font = `800 ${size}px ${FONT}`; }
      ctx.fillStyle = INK;
      ctx.fillText(wrap(ctx, sec.title, w - 80, 1)[0] || "", x + 40, y + 135);
      ctx.fillStyle = "#c9d1de"; ctx.font = `500 34px ${FONT}`;
      const lines = wrap(ctx, sec.summary, w - 80, 3);
      lines.forEach((ln, k) => ctx.fillText(ln, x + 40, y + 190 + k * 44));
      // key plays (every score first-class): appear when reached, current one highlighted
      let ry = y + 200 + lines.length * 44 + 10;
      const rowH = 92;
      for (const k of (sec.key_plays || []).slice(0, 4)) {
        const kp = this.plays[k];
        if (!kp || ry + rowH > y + h - 10) break;
        const shown = clamp((t - kp.t_start) / 0.2, 0, 1);
        const isNow = i === k;
        const helped = kp.swing >= 0 ? this.hc : this.ac;
        ctx.globalAlpha = base * enter * (0.25 + 0.75 * shown);
        roundRect(ctx, x + 30, ry, w - 60, rowH - 12, 16);
        ctx.fillStyle = isNow ? rgba(helped, 0.35) : "rgba(255,255,255,0.04)"; ctx.fill();
        if (kp.scoring) { roundRect(ctx, x + 30, ry, 10, rowH - 12, 5); ctx.fillStyle = helped; ctx.fill(); }
        ctx.textAlign = "left"; ctx.fillStyle = kp.scoring ? helped : MUTED; ctx.font = `800 26px ${FONT}`;
        ctx.fillText(kp.headline || (kp.scoring ? "SCORE" : kp.type.toUpperCase()), x + 60, ry + 34);
        // right-hand label (new score, or the swing) first, so the description fits beside it
        const label = kp.scoring && shown > 0 ? `${this.away.abbr} ${kp.away_score}–${kp.home_score} ${this.home.abbr}`
          : kp.abs_swing >= 0.005 ? `+${Math.round(kp.abs_swing * 100)}%` : "";
        ctx.font = `800 36px ${FONT}`;
        const labelW = label ? ctx.measureText(label).width + 30 : 0;
        ctx.textAlign = "right";
        ctx.fillStyle = kp.scoring && shown > 0 ? INK : helped;
        if (label) ctx.fillText(label, x + w - 50, ry + 52);
        ctx.textAlign = "left"; ctx.fillStyle = INK; ctx.font = `500 28px ${FONT}`;
        const rowText = kp.scoring && kp.phrase ? kp.phrase.replace(/^[^:]+:\s*/, "") : (kp.phrase || kp.short_text);
        ctx.fillText(wrap(ctx, rowText, w - 110 - labelW, 1)[0] || "", x + 60, ry + 68);
        ry += rowH;
      }
      ctx.restore();
    }

    // Scrolling play feed: newest at the bottom, the last few stay visible.
    feed(ctx, t, i) {
      const x = 40, y = 1160, w = W - 80, h = 680, rowH = 150, gap = 14;
      roundRect(ctx, x, y, w, h, 24); ctx.fillStyle = PANEL; ctx.fill();
      ctx.save(); roundRect(ctx, x, y, w, h, 24); ctx.clip();
      const p = this.plays[i];
      const enter = ease((t - p.t_start) / Math.max(0.001, Math.min(0.18, (p.t_end - p.t_start) * 0.6)));
      const bottom = y + h - 20;
      const visible = 5;
      for (let k = 0; k <= visible; k++) {
        const j = i - k;
        if (j < 0) break;
        const rowY = bottom - rowH - k * (rowH + gap) + (1 - enter) * (rowH + gap);
        if (rowY + rowH < y) break;
        const alpha = k === 0 ? enter : clamp(1 - (k - 1) * 0.2, 0.25, 1);
        this.feedRow(ctx, this.plays[j], x + 20, rowY, w - 40, rowH, k === 0, alpha);
      }
      ctx.restore();
    }

    feedRow(ctx, p, x, y, w, h, current, alpha) {
      const base = ctx.globalAlpha;
      ctx.globalAlpha = base * alpha;
      roundRect(ctx, x, y, w, h, 18);
      ctx.fillStyle = current ? PANEL_2 : "rgba(255,255,255,0.03)"; ctx.fill();
      const helped = p.swing >= 0 ? this.hc : this.ac;
      if (p.abs_swing >= 0.005) {
        ctx.fillStyle = helped; roundRect(ctx, x, y, 10, h, 5); ctx.fill();
      }
      ctx.textAlign = "left"; ctx.fillStyle = MUTED; ctx.font = `600 26px ${FONT}`;
      ctx.fillText(`${quarterLabel(p.quarter)} ${p.clock || ""}`, x + 30, y + 42);
      if (p.headline) {
        ctx.fillStyle = helped; ctx.font = `800 26px ${FONT}`;
        ctx.fillText(p.headline, x + 170, y + 42);
      } else if (p.kind === "drive") {
        ctx.fillStyle = MUTED; ctx.font = `800 26px ${FONT}`;
        ctx.fillText("DRIVE", x + 170, y + 42);
      }
      ctx.fillStyle = INK; ctx.font = `${current ? 600 : 500} 32px ${FONT}`;
      const lines = wrap(ctx, p.short_text, w - 220, 2);
      lines.forEach((ln, k) => ctx.fillText(ln, x + 30, y + 88 + k * 40));
      if (p.abs_swing >= 0.005) {
        const team = p.swing >= 0 ? this.home.abbr : this.away.abbr;
        ctx.textAlign = "right"; ctx.fillStyle = helped; ctx.font = `800 40px ${FONT}`;
        ctx.fillText(`+${Math.round(p.abs_swing * 100)}%`, x + w - 24, y + 70);
        ctx.fillStyle = MUTED; ctx.font = `600 24px ${FONT}`;
        ctx.fillText(team, x + w - 24, y + 102);
      }
      ctx.globalAlpha = base;
    }

    // Big plays: a card over the play feed while the play is held, so the win-probability
    // chart above stays visible and shows the jump.
    cardAlpha(t, p) {
      const life = (t - p.t_start) / Math.max(0.001, p.t_end - p.t_start);
      return ease(life / 0.12) * (1 - ease((life - 0.9) / 0.1));
    }

    highlightCard(ctx, t, p, a) {
      const life = (t - p.t_start) / Math.max(0.001, p.t_end - p.t_start);
      const helped = p.swing >= 0 ? this.hc : this.ac;
      const team = p.swing >= 0 ? this.home : this.away;
      const x = 40, y = 1160, w = W - 80, h = 680;
      ctx.save();
      ctx.globalAlpha = a;
      const s = 0.94 + 0.06 * ease(life / 0.12);
      ctx.translate(W / 2, y + h / 2); ctx.scale(s, s); ctx.translate(-W / 2, -(y + h / 2));
      ctx.shadowColor = "rgba(0,0,0,0.5)"; ctx.shadowBlur = 40;
      roundRect(ctx, x, y, w, h, 30); ctx.fillStyle = helped; ctx.fill();
      ctx.shadowBlur = 0;
      const ink = luminance(helped) > 0.5 ? "#0b1020" : "#ffffff";
      ctx.fillStyle = ink; ctx.textAlign = "center";
      ctx.font = `900 72px ${FONT}`;
      ctx.fillText(p.headline || "BIG PLAY", W / 2, y + 120);
      ctx.font = `800 140px ${FONT}`;
      ctx.fillText(`+${Math.round(p.abs_swing * 100)}%`, W / 2, y + 285);
      ctx.font = `700 38px ${FONT}`;
      ctx.fillText(`${team.abbr} win probability ${pct(p.swing >= 0 ? p.wp_home_after : 1 - p.wp_home_after)}`, W / 2, y + 350);
      ctx.font = `500 36px ${FONT}`;
      const desc = p.phrase || p.short_text || "";
      wrap(ctx, `${quarterLabel(p.quarter)} ${p.clock} · ${desc}`, w - 100, 4)
        .forEach((ln, k) => ctx.fillText(ln, W / 2, y + 440 + k * 48));
      ctx.restore();
    }

    // ── Outro: final score and the full chart ───────────────────────────────
    drawOutro(ctx, t) {
      const last = this.plays[this.plays.length - 1];
      const final = this.g.final || { home: last.home_score, away: last.away_score };
      ctx.textAlign = "center"; ctx.fillStyle = MUTED; ctx.font = `700 40px ${FONT}`;
      ctx.fillText("FINAL", W / 2, 190);
      const winnerHome = final.home > final.away;
      const row = (team, color, score, y, won) => {
        roundRect(ctx, 80, y, W - 160, 200, 28); ctx.fillStyle = PANEL; ctx.fill();
        roundRect(ctx, 80, y, 22, 200, 11); ctx.fillStyle = color; ctx.fill();
        ctx.textAlign = "left"; ctx.fillStyle = won ? INK : MUTED; ctx.font = `800 80px ${FONT}`;
        ctx.fillText(`${team.rank ? `#${team.rank} ` : ""}${team.abbr}`, 140, y + 130);
        ctx.textAlign = "right"; ctx.font = `900 120px ${FONT}`;
        ctx.fillText(String(score), W - 130, y + 145);
      };
      row(this.away, this.ac, final.away, 240, !winnerHome);
      row(this.home, this.hc, final.home, 470, winnerHome);
      this.wpChart(ctx, t, this.plays.length - 1, 730, 560);
      const topIdx = (this.e.top_plays || [])[0];
      const big = topIdx !== undefined ? this.plays.find((p) => p.idx === topIdx) : null;
      if (big) {
        roundRect(ctx, 40, 1330, W - 80, 380, 24); ctx.fillStyle = PANEL; ctx.fill();
        ctx.textAlign = "left"; ctx.fillStyle = MUTED; ctx.font = `600 30px ${FONT}`;
        ctx.fillText("BIGGEST SWING", 80, 1390);
        const helped = big.swing >= 0 ? this.hc : this.ac;
        ctx.fillStyle = helped; ctx.font = `800 64px ${FONT}`;
        ctx.fillText(`+${Math.round(big.abs_swing * 100)}% ${big.swing >= 0 ? this.home.abbr : this.away.abbr}`, 80, 1470);
        ctx.fillStyle = INK; ctx.font = `500 34px ${FONT}`;
        wrap(ctx, `${quarterLabel(big.quarter)} ${big.clock} · ${big.short_text}`, W - 160, 4)
          .forEach((ln, k) => ctx.fillText(ln, 80, 1530 + k * 44));
      }
    }

    // ── structure = chart: vertical WP chart (left), annotated plays (right) ──
    // y = the model's warped game time (plays[k].y, 0-1, top to bottom); x = home WP
    // (away 100% at the left edge, home 100% at the right, 50% in the middle). Each card's
    // play sits at the card's vertical centre, so its pointer runs straight across.
    drawChartView(ctx, t, i, outro) {
      const C = { top: 350, bottom: H - 110, x0: 66, x1: 316, cardX: 346, cardW: W - 36 - 346 };
      C.h = C.bottom - C.top;
      const p = this.plays[i];
      this.compactBoard(ctx, outro ? null : p, t, outro);
      this.chartAxes(ctx, C, outro ? this.plays.length - 1 : i);
      const shown = this.notes.filter((a) => outro || t >= a.t_show);
      // pointers sit under the line and the cards
      shown.forEach((a) => this.notePointer(ctx, C, a, t, outro));
      this.chartLine(ctx, C, t, outro ? this.plays.length - 1 : i, outro);
      const current = outro ? -1 : shown.length - 1;
      shown.forEach((a, k) => this.noteCard(ctx, C, a, t, k === current, outro));
    }

    compactBoard(ctx, p, t, outro) {
      const y = 60, h = 200;
      const last = this.plays[this.plays.length - 1];
      const final = this.g.final || { home: last.home_score, away: last.away_score };
      const cur = p || { ...last, home_score: final.home, away_score: final.away };
      const prev = p && p.idx > 0 ? this.plays[p.idx - 1] : { home_score: 0, away_score: 0 };
      const scored = p && p.scoring ? clamp((t - p.t_start) / 0.9, 0, 1) : 1;
      const pulse = scored < 1 ? Math.sin(scored * Math.PI) : 0;
      const side = (team, color, score, x, align, popped, won) => {
        roundRect(ctx, x, y, 400, h, 26); ctx.fillStyle = PANEL; ctx.fill();
        roundRect(ctx, x, y, 400, 12, 6); ctx.fillStyle = color; ctx.fill();
        const tx = align === "left" ? x + 34 : x + 366, sx = align === "left" ? x + 366 : x + 34;
        ctx.textAlign = align; ctx.fillStyle = outro && !won ? MUTED : INK; ctx.font = `800 58px ${FONT}`;
        ctx.fillText(team.abbr || team.short, tx, y + 92);
        ctx.fillStyle = MUTED; ctx.font = `600 26px ${FONT}`;
        ctx.fillText([team.rank ? `#${team.rank}` : "", team.record || ""].filter(Boolean).join(" · ") || " ", tx, y + 142);
        ctx.textAlign = align === "left" ? "right" : "left";
        ctx.fillStyle = outro && !won ? MUTED : INK;
        const pop = popped ? pulse : 0;
        ctx.save();
        if (pop > 0) { ctx.shadowColor = color; ctx.shadowBlur = 50 * pop; }
        ctx.font = `900 ${Math.round(118 * (1 + 0.16 * pop))}px ${FONT}`;
        ctx.fillText(String(score), sx, y + 150);
        ctx.restore();
        if (pop > 0) { roundRect(ctx, x, y, 400, h, 26); ctx.strokeStyle = rgba(color, 0.9 * pop); ctx.lineWidth = 6; ctx.stroke(); }
      };
      const homeWon = final.home > final.away;
      side(this.away, this.ac, cur.away_score, 40, "left", p && p.away_score > prev.away_score, !homeWon);
      side(this.home, this.hc, cur.home_score, 640, "right", p && p.home_score > prev.home_score, homeWon);
      ctx.textAlign = "center";
      if (outro) {
        ctx.fillStyle = INK; ctx.font = `800 46px ${FONT}`;
        ctx.fillText("FINAL", W / 2, y + 90);
        ctx.fillStyle = MUTED; ctx.font = `700 34px ${FONT}`;
        if (last.quarter > 4) ctx.fillText(quarterLabel(last.quarter), W / 2, y + 140);
      } else {
        ctx.fillStyle = INK; ctx.font = `800 46px ${FONT}`;
        ctx.fillText(quarterLabel(cur.quarter), W / 2, y + 80);
        ctx.fillStyle = MUTED; ctx.font = `700 38px ${FONT}`;
        ctx.fillText(cur.quarter > 4 ? "" : String(cur.clock || "").replace(/^0(\d)/, "$1"), W / 2, y + 128);
        const wp = this.wpAt(t);
        ctx.fillStyle = wp >= 0.5 ? this.hc : this.ac; ctx.font = `800 32px ${FONT}`;
        ctx.fillText(`${(wp >= 0.5 ? this.home : this.away).abbr} ${pct(Math.max(wp, 1 - wp))}`, W / 2, y + 180);
      }
    }

    chartAxes(ctx, C, upto) {
      const mid = (C.x0 + C.x1) / 2;
      const xAt = (q) => C.x0 + (C.x1 - C.x0) * q;
      // header: who each side of the chart belongs to
      ctx.font = `700 24px ${FONT}`; ctx.fillStyle = INK;
      ctx.textAlign = "left"; ctx.fillText(this.away.abbr, C.x0, C.top - 66);
      ctx.textAlign = "right"; ctx.fillText(this.home.abbr, C.x1, C.top - 66);
      ctx.font = `700 20px ${FONT}`; ctx.fillStyle = MUTED; ctx.textAlign = "center";
      ctx.fillText("WIN %", mid, C.top - 66);
      ctx.fillStyle = this.ac; ctx.fillRect(C.x0, C.top - 54, mid - C.x0 - 2, 6);
      ctx.fillStyle = this.hc; ctx.fillRect(mid + 2, C.top - 54, C.x1 - mid - 2, 6);
      // grid: 0/25/50/75/100% home WP, labelled as the win % of the team on that side
      const ticks = [0, 0.25, 0.5, 0.75, 1];
      ticks.forEach((q) => {
        const x = xAt(q);
        ctx.strokeStyle = q === 0.5 ? "#4a5679" : LINE; ctx.lineWidth = q === 0.5 ? 3 : 1.5;
        ctx.beginPath(); ctx.moveTo(x, C.top); ctx.lineTo(x, C.bottom); ctx.stroke();
      });
      ctx.font = `600 19px ${FONT}`; ctx.fillStyle = MUTED; ctx.textAlign = "center";
      ticks.forEach((q) => {
        const label = `${Math.round(Math.max(q, 1 - q) * 100)}%`;
        ctx.fillText(label, xAt(q), C.top - 16);
        ctx.fillText(label, xAt(q), C.bottom + 28);
      });
      // quarter starts at their (warped) heights
      let q = 0;
      ctx.font = `700 22px ${FONT}`; ctx.textAlign = "left";
      this.plays.forEach((pl, k) => {
        if (pl.quarter === q || k > upto) return;
        q = pl.quarter;
        const y = C.top + C.h * (k ? (this.plays[k - 1].y + pl.y) / 2 : 0);
        ctx.strokeStyle = LINE; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(C.x0 - 8, y); ctx.lineTo(C.x1, y); ctx.stroke();
        ctx.fillStyle = MUTED; ctx.fillText(quarterLabel(q), 18, y + (k ? 8 : 22));
      });
    }

    chartPoint(C, wp, y) { return [C.x0 + (C.x1 - C.x0) * wp, C.top + C.h * y]; }

    chartLine(ctx, C, t, i, outro) {
      const mid = (C.x0 + C.x1) / 2;
      const pts = [this.chartPoint(C, this.g.pregame_wp_home, 0)];
      for (let k = 0; k < i; k++) pts.push(this.chartPoint(C, this.plays[k].wp_home_after, this.plays[k].y));
      const p = this.plays[i];
      let e = 1;
      if (!outro) {
        const span = Math.max(0.001, Math.min(0.35, (p.t_end - p.t_start) * 0.5));
        e = ease((t - p.t_start) / span);
      }
      const prevY = i ? this.plays[i - 1].y : 0;
      pts.push(this.chartPoint(C, p.wp_home_before + (p.wp_home_after - p.wp_home_before) * e, prevY + (p.y - prevY) * e));
      // area between the line and 50%, in the leading team's colour
      [[this.ac, C.x0 - 2, mid - C.x0 + 2], [this.hc, mid, C.x1 - mid + 2]].forEach(([color, cx, cw]) => {
        ctx.save();
        ctx.beginPath(); ctx.rect(cx, C.top - 2, cw, C.h + 4); ctx.clip();
        ctx.beginPath(); ctx.moveTo(mid, pts[0][1]);
        pts.forEach(([x, y]) => ctx.lineTo(x, y));
        ctx.lineTo(mid, pts[pts.length - 1][1]); ctx.closePath();
        ctx.fillStyle = rgba(color, 0.38); ctx.fill();
        ctx.restore();
      });
      ctx.strokeStyle = INK; ctx.lineWidth = 4; ctx.lineJoin = "round";
      ctx.beginPath(); pts.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
      if (!outro) {
        const [x, y] = pts[pts.length - 1];
        ctx.fillStyle = INK; ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.fill();
      }
    }

    noteSide(a) { return a.team === "home" ? this.home : this.away; }
    noteColor(a) { return a.team === "home" ? this.hc : this.ac; }

    // vertical extent of a card: its slot (slot_h of the chart height) less a gap, centred on its play
    noteBox(C, a) {
      const h = Math.max(56, C.h * a.slot_h - 12);
      return { y: C.top + C.h * a.y - h / 2, h };
    }

    notePointer(ctx, C, a, t, outro) {
      const pl = this.plays[a.play];
      const [px, py] = this.chartPoint(C, pl.wp_home_after, pl.y);
      const k = outro ? 1 : ease((t - a.t_show) / 0.35);
      const color = this.noteColor(a);
      ctx.strokeStyle = rgba(color, 0.75); ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + (C.cardX - px) * k, py); ctx.stroke();
      ctx.fillStyle = BG; ctx.beginPath(); ctx.arc(px, py, 13, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = color; ctx.beginPath(); ctx.arc(px, py, a.scoring ? 10 : 8, 0, Math.PI * 2); ctx.fill();
    }

    noteCard(ctx, C, a, t, current, outro) {
      const k = outro ? 1 : ease((t - a.t_show - 0.15) / 0.35);
      if (k <= 0) return;
      const { y, h } = this.noteBox(C, a);
      const x = C.cardX + 40 * (1 - k), w = C.cardW;
      const color = this.noteColor(a), large = a.size === "large";
      ctx.save();
      ctx.globalAlpha = k * (current || outro ? 1 : 0.72);
      roundRect(ctx, x, y, w, h, 18);
      ctx.fillStyle = a.scoring ? PANEL_2 : PANEL; ctx.fill();
      if (a.scoring) { ctx.fillStyle = rgba(color, 0.16); ctx.fill(); }
      if (current) { ctx.strokeStyle = rgba(color, 0.95); ctx.lineWidth = 4; ctx.stroke(); }
      ctx.save(); roundRect(ctx, x, y, w, h, 18); ctx.clip();
      ctx.fillStyle = color; ctx.fillRect(x, y, a.scoring ? 14 : 8, h); ctx.restore();

      // right label: the new score for scoring plays, otherwise the swing
      const pad = 26, inner = x + pad + 6;
      const big = clamp(Math.round(h * (large ? 0.3 : 0.4)), 28, large ? 64 : 40);
      const label = a.scoring ? `${a.away_score}–${a.home_score}` : `+${Math.round(a.abs_swing * 100)}%`;
      ctx.font = `900 ${big}px ${FONT}`;
      const labelW = ctx.measureText(label).width;
      ctx.textAlign = "right"; ctx.fillStyle = INK;
      ctx.fillText(label, x + w - pad, y + h / 2 + big * 0.36);
      if (!a.scoring && h >= 90) {
        ctx.font = `700 20px ${FONT}`; ctx.fillStyle = MUTED;
        ctx.fillText(this.noteSide(a).abbr, x + w - pad, y + h / 2 + big * 0.36 + 26);
      }
      // left: large cards get a "Q4 2:28 · BIG PLAY" line over the phrase; normal cards put the
      // time inline before the phrase so it can use two lines
      const textW = w - pad * 2 - 6 - labelW - 24;
      const clock = String(a.clock || "").replace(/^0(\d)/, "$1");
      const tag = `${quarterLabel(a.quarter)}${a.quarter <= 4 ? ` ${clock}` : ""}`;
      const meta = large ? clamp(Math.round(h * 0.17), 20, 28) : 0;
      const avail = h - 18 - (meta ? meta + 12 : 0);
      let fs = clamp(Math.round(h * (large ? 0.22 : 0.3)), 22, large ? 40 : 32), lines, prefix = "";
      for (;;) {
        ctx.font = `700 ${fs}px ${FONT}`;
        prefix = large ? "" : `${tag}  `;
        const max = Math.max(1, Math.min(Math.floor(avail / (fs * 1.15)), large ? 3 : 2));
        lines = wrap(ctx, a.phrase, textW, max, prefix ? ctx.measureText(prefix).width : 0);
        if (fs <= 20 || !lines.some((l) => l.endsWith("…"))) break;
        fs -= 2;
      }
      const lineH = fs * 1.15;
      const block = (meta ? meta + 12 : 0) + lines.length * lineH;
      let ty = y + (h - block) / 2;
      ctx.textAlign = "left";
      if (meta) {
        ctx.font = `700 ${meta}px ${FONT}`; ctx.fillStyle = MUTED;
        ctx.fillText(`${tag}  ·  ${a.label || ""}`.toUpperCase(), inner, ty + meta * 0.85);
        ty += meta + 12;
      }
      lines.forEach((ln, n) => {
        const base = ty + lineH * n + fs * 0.92;
        ctx.font = `${large ? 800 : 700} ${fs}px ${FONT}`; ctx.fillStyle = INK;
        ctx.fillText(ln, inner + (n === 0 && prefix ? ctx.measureText(prefix).width : 0), base);
        if (n === 0 && prefix) {
          ctx.font = `700 ${fs}px ${FONT}`; ctx.fillStyle = MUTED; ctx.fillText(tag, inner, base);
        }
      });
      ctx.restore();
    }
  }

  ReplayRenderer.WIDTH = W;
  ReplayRenderer.HEIGHT = H;
  window.ReplayRenderer = ReplayRenderer;
})();
