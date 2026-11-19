"""Running progress. See MODEL.md (method) and RESEARCH.md (fit and test)."""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.units import format_time
from ballmonitor.models.running_progress.features import (
    SOUTHERN_COUNTRIES,
    Features,
    as_date,
    season_value,
    summarise,
    target_week_mids,
    weekly_totals,
)

# The output contract: 2.5/10/25/50/75/90/97.5% quantiles -> median + 50/80/95% bands.
QUANTILE_KEYS = ("p025", "p10", "p25", "p50", "p75", "p90", "p975")
QUANTILE_LEVELS = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)
BAND_INDEX = {0.5: (2, 4), 0.8: (1, 5), 0.95: (0, 6)}
MEDIAN = 3


def _fmt_pace(sec: float) -> str:
    return format_time(sec)


class RunningProgressModel(BaseModel):
    # ── inputs ─────────────────────────────────────────────────────────────

    def _dates(self, inputs: dict[str, Any]) -> tuple[dt.date, float]:
        p = self.params
        if "today" in inputs:
            today = as_date(inputs["today"])
        elif inputs.get("log"):
            today = max(as_date(e["date"]) for e in inputs["log"]) + dt.timedelta(days=1)
        else:
            raise ValueError("give `today` (the day the forecast is made)")
        if "target_date" in inputs:
            h = (as_date(inputs["target_date"]) - today).days / 7.0
        elif "weeks_ahead" in inputs:
            h = float(inputs["weeks_ahead"])
        else:
            raise ValueError("give `target_date` or `weeks_ahead`")
        if not p.min_horizon_weeks <= h <= p.max_horizon_weeks:
            raise ValueError(
                f"the target must be {p.min_horizon_weeks:g}-{p.max_horizon_weeks:g} weeks after today "
                f"(got {h:.1f}); the target window is the {int(p.target_weeks)} weeks before it")
        return today, h

    @staticmethod
    def _southern(inputs: dict[str, Any]) -> bool:
        hemi = str(inputs.get("hemisphere", "")).strip().lower()
        if hemi:
            if hemi not in ("north", "south"):
                raise ValueError("hemisphere must be north or south")
            return hemi == "south"
        return str(inputs.get("country", "")).strip() in SOUTHERN_COUNTRIES

    # ── prediction ─────────────────────────────────────────────────────────

    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params
        today, h = self._dates(inputs)
        southern = self._southern(inputs)
        rows, ignored = weekly_totals(inputs, today, int(p.lookback_weeks))
        f = summarise(rows, today, p)
        steps = self._feature_steps(f, ignored)

        # season: target weeks vs base weeks (h rounded to whole weeks for the calendar)
        t_mids = target_week_mids(today, round(h), int(p.target_weeks))
        target_end = today + dt.timedelta(days=round(7 * h))
        sp = season_value(t_mids, "season_pace", southern, p) - season_value(f.week_mids, "season_pace", southern, p)
        sk = season_value(t_mids, "season_km", southern, p) - season_value(f.week_mids, "season_km", southern, p)
        steps.append(
            f"Season ({'southern' if southern else 'northern'} hemisphere): target weeks vs base weeks "
            f"change ln pace by {sp:+.4f} and ln km by {sk:+.4f} (season_pace_mMM, season_km_mMM).")

        # pace
        loc = p.formula("pace_location", lp_base=f.lp_base, tr_recent=f.tr_recent, tr_long=f.tr_long, season=sp)
        scale = p.formula("pace_scale", h=h, share=f.share, lp_base=f.lp_base, tr_recent=f.tr_recent)
        if not scale > 0:
            raise ValueError(f"formula 'pace_scale' gave {scale}; it must be > 0")
        pace_q = self._quantiles("pace", loc, scale)
        steps.append(
            f"Pace location = ln {_fmt_pace(math.exp(loc))}/km [{p.expr('pace_location')}] "
            f"with h = {h:.1f} weeks.")
        steps.append(f"Pace scale = {scale:.4f} [{p.expr('pace_scale')}].")
        steps.append(
            "Pace quantiles = exp(location + scale * pace_z_*): "
            + ", ".join(f"{lv * 100:g}% {_fmt_pace(v)}" for lv, v in zip(QUANTILE_LEVELS, pace_q)) + ".")

        # weekly distance (given still training)
        kloc = p.formula("km_location", lk_base=f.lk_base, ktr_recent=f.ktr_recent, ktr_long=f.ktr_long,
                         season=sk, share=f.share)
        kscale = p.formula("km_scale", h=h, share=f.share, lk_base=f.lk_base, ktr_recent=f.ktr_recent)
        if not kscale > 0:
            raise ValueError(f"formula 'km_scale' gave {kscale}; it must be > 0")
        km_q = self._quantiles("km", kloc, kscale)
        steps.append(
            f"Distance location = ln({math.exp(kloc):.1f}) [{p.expr('km_location')}]; scale = "
            f"{kscale:.3f} [{p.expr('km_scale')}]; quantiles (km/week, if still training): "
            + ", ".join(f"{lv * 100:g}% {v:.1f}" for lv, v in zip(QUANTILE_LEVELS, km_q)) + ".")

        # still training
        prob = p.formula("p_running", share=f.share, since=f.since, lk_base=f.lk_base, h=h)
        steps.append(f"P(still training) = {prob:.3f} [{p.expr('p_running')}].")

        # Tanda (2011): literature formula, not validated on this data
        tanda_pace = f.tanda.pace or f.base.pace  # no run in the Tanda window: use the base pace
        tanda_now = self._tanda(f.tanda.km_per_week, tanda_pace)
        tanda_target = self._tanda(km_q[MEDIAN], pace_q[MEDIAN])
        steps.append(
            f"Tanda (2011) marathon = {format_time(tanda_now)} today (K = {f.tanda.km_per_week:.1f} km/wk, "
            f"P = {_fmt_pace(tanda_pace)}/km over {int(p.tanda_weeks)} weeks) and "
            f"{format_time(tanda_target)} at the target (median km and pace) "
            f"[{p.expr('tanda_marathon')}]. Not validated on this data.")

        level = p.interval_level
        lo, hi = BAND_INDEX[level]
        group_t = f"At the target ({int(p.target_weeks)} weeks to {target_end.isoformat()})"
        outcomes = [
            Outcome("Average pace (per km)", estimate=pace_q[MEDIAN], interval=(pace_q[lo], pace_q[hi]),
                    fmt="time", group=group_t, note=self._band_note(pace_q, _fmt_pace)),
            Outcome("Weekly km, if training", estimate=km_q[MEDIAN], interval=(km_q[lo], km_q[hi]),
                    group=group_t, note=self._band_note(km_q, lambda v: f"{v:.1f}")),
            Outcome("Still training", probability=prob, group=group_t,
                    note=f"a run in the {int(p.target_weeks)} weeks before"),
            Outcome("Average pace now", estimate=f.recent.pace or f.base.pace, fmt="time",
                    group="Today (from the log)",
                    note=f"last {int(p.recent_weeks)} wk" if f.recent.pace else f"last {int(p.base_weeks)} wk"),
            Outcome("Weekly km now", estimate=f.recent.km_per_week, group="Today (from the log)",
                    note=f"last {int(p.recent_weeks)} weeks"),
            Outcome("Weeks with a run", probability=f.share, group="Today (from the log)",
                    note=f"of the last {f.base.weeks}"),
            Outcome("Marathon now (Tanda)", estimate=tanda_now, fmt="time",
                    group="From the literature (not validated here)", note=self._tanda_note(tanda_now)),
            Outcome("Marathon at target (Tanda)", estimate=tanda_target, fmt="time",
                    group="From the literature (not validated here)", note=self._tanda_note(tanda_target)),
        ]
        shown = {
            "today": today.isoformat(),
            "target": f"{target_end.isoformat()} ({h:.1f} weeks ahead)",
            "log": f"{f.series_weeks} weeks, {sum(1 for k, _ in f.weekly if k)} with running",
            "hemisphere": "south" if southern else "north",
        }
        for key in ("gender", "age_group", "country"):
            if key in inputs:
                shown[key] = inputs[key]
        return self.prediction(
            inputs=shown, outcomes=outcomes, steps=steps, interval_level=level,
            extras={
                "horizon_weeks": h, "season_pace": sp, "season_km": sk,
                "pace_location": loc, "pace_scale": scale, "pace_quantiles": pace_q,
                "km_location": kloc, "km_scale": kscale, "km_quantiles": km_q,
                "p_running": prob, "tanda_now": tanda_now, "tanda_target": tanda_target,
                "features": {
                    "share": f.share, "since": f.since, "lp_base": f.lp_base, "tr_recent": f.tr_recent,
                    "tr_long": f.tr_long, "lk_base": f.lk_base, "ktr_recent": f.ktr_recent,
                    "ktr_long": f.ktr_long, "series_weeks": f.series_weeks, "missing_weeks": f.missing_weeks,
                },
            },
        )

    def _quantiles(self, what: str, loc: float, scale: float) -> list[float]:
        p = self.params
        zs = sorted(float(p[f"{what}_z_{k}"]) for k in QUANTILE_KEYS)  # sorted: never crossing
        return [p.formula(f"{what}_quantile", loc=loc, scale=scale, z=z) for z in zs]

    def _tanda(self, km_per_week: float, pace: float) -> float:
        return self.params.formula("tanda_marathon", K=km_per_week, P=pace)

    def _tanda_note(self, seconds: float) -> str:
        p = self.params
        minutes = seconds / 60
        inside = p.tanda_valid_lo <= minutes <= p.tanda_valid_hi
        return "within the paper's range" if inside else "outside the paper's 2:47-3:36"

    @staticmethod
    def _band_note(q: list[float], fmt) -> str:
        return f"50%: {fmt(q[2])}-{fmt(q[4])} · 95%: {fmt(q[0])}-{fmt(q[6])}"

    def _feature_steps(self, f: Features, ignored: int) -> list[str]:
        p = self.params
        steps = [
            f"Log -> {f.series_weeks} weekly totals ending the day before today"
            + (f"; {ignored} entries outside the window ignored" if ignored else "")
            + (f"; {f.missing_weeks} implausible weeks dropped (pace outside "
               f"{p.min_pace_min_per_km:g}-{p.max_pace_min_per_km:g} min/km or > {p.max_week_km:g} km)"
               if f.missing_weeks else "") + ".",
        ]
        if f.series_weeks < p.base_weeks:
            steps.append(
                f"Only {f.series_weeks} weeks of log (fit used >= {int(p.base_weeks)}): windows use what "
                "is there; treat the bands as optimistic.")
        rp = _fmt_pace(f.recent.pace) if f.recent.pace else "no runs"
        steps.append(
            f"Windows: recent {int(p.recent_weeks)} wk {f.recent.km_per_week:.1f} km/wk at {rp}; base "
            f"{int(p.base_weeks)} wk {f.base.km_per_week:.1f} km/wk at {_fmt_pace(f.base.pace)}; long "
            f"{f.long.weeks} wk {f.long.km_per_week:.1f} km/wk at {_fmt_pace(f.long.pace)} (pace = total "
            "time / total distance).")
        steps.append(
            f"Features: share = {f.share:.2f} of base weeks with a run, since = {f.since} weeks since the "
            f"last run week, tr_recent = {f.tr_recent:+.4f}, tr_long = {f.tr_long:+.4f}, "
            f"ktr_recent = {f.ktr_recent:+.3f}, ktr_long = {f.ktr_long:+.3f}.")
        return steps

    # ── backtest ───────────────────────────────────────────────────────────

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], Any]:
        # data/backtest.csv columns: see MODEL.md (Backtest data)
        inputs = {
            "today": row["today"],
            "weeks_ahead": float(row["weeks_ahead"]),
            "hemisphere": row["hemisphere"],
            "weekly_km": [float(x) for x in row["weekly_km"].split()],
            "weekly_minutes": [float(x) for x in row["weekly_minutes"].split()],
        }
        actual = {
            "running": row["actual_running"] == "1",
            "pace": float(row["actual_pace"]) if row["actual_pace"] else None,
            "km": float(row["actual_km"]),
        }
        return inputs, actual

    def backtest_group(self, row: dict[str, str]) -> str | None:
        return row["split"]

    def score(self, prediction: Prediction, actual: Any) -> dict[str, float]:
        """Pace (primary): |% error| of the median, band coverage; distance: 80% coverage;
        still training: Brier and log loss. Pace/distance metrics only when still training."""
        x = prediction.extras
        prob = x["p_running"]
        y = 1.0 if actual["running"] else 0.0
        out = {
            "brier_running": (prob - y) ** 2,
            "log_loss_running": -math.log(max(prob if y else 1 - prob, 1e-12)),
        }
        nan = math.nan
        pq, kq = x["pace_quantiles"], x["km_quantiles"]
        pace, km = actual["pace"], actual["km"]
        ok = actual["running"] and pace is not None
        out["abs_pct_error"] = abs(pq[MEDIAN] / pace - 1) * 100 if ok else nan
        out["bias"] = (pq[MEDIAN] / pace - 1) * 100 if ok else nan
        for level, key in ((0.5, "in_50"), (0.8, "in_80"), (0.95, "in_95")):
            lo, hi = BAND_INDEX[level]
            out[key] = float(pq[lo] <= pace <= pq[hi]) if ok else nan
        lo, hi = BAND_INDEX[0.8]
        out["km_in_80"] = float(kq[lo] <= km <= kq[hi]) if ok else nan
        return out
