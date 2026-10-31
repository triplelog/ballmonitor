"""Race podium prediction for positions 1 through 5 in a given race division. See MODEL.md."""

from __future__ import annotations

import csv
import math
from statistics import NormalDist
from pathlib import Path
from typing import Any

from ballmonitor.core import BaseModel, Outcome, Prediction
from ballmonitor.core.stats import z_for_level
from ballmonitor.core.units import (
    METERS_PER_KM,
    METERS_PER_MILE,
    distance_label,
    format_time,
    parse_distance,
    parse_time,
)
from ballmonitor.models.race_podium.age_curves import (
    continuous_age_factor,
    get_annual_aging_decline_pct,
    get_bracket_relative_factor,
)
from ballmonitor.models.race_podium.ingest import RaceResultsIngester
from ballmonitor.models.race_podium.participation import (
    COMMON_BREAKDOWNS,
    STANDARD_BRACKETS,
    get_breakdown_divisions,
    get_demographic_share,
    get_gender_share,
    smooth_division_field_size,
)
from ballmonitor.models.race_podium.weather import fetch_weather, geocode_city_state


_ND = NormalDist()


def _as_int(value: Any, name: str) -> int:
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from exc
    if f != int(f):
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    return int(f)


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _first_present(inputs: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if inputs.get(k) is not None:
            return inputs[k]
    return None


class RacePodiumModel(BaseModel):
    def predict(self, inputs: dict[str, Any]) -> Prediction:
        p = self.params

        # 1. Parse division and race metadata
        race_name = str(inputs.get("race_name", "Road Race")).strip()
        gender = str(inputs.get("gender", "M")).strip().upper()
        if gender not in ("M", "F", "X", "ALL"):
            raise ValueError(f"gender must be M, F, X or all, got {inputs.get('gender')!r}")
        age_min = _as_int(inputs.get("age_min", 40), "age_min")
        age_max = _as_int(inputs.get("age_max", 44), "age_max")
        if age_min > age_max:
            raise ValueError(f"age_min ({age_min}) must not exceed age_max ({age_max})")
        field_size_given = inputs.get("field_size") is not None
        target_field_size = _as_int(inputs.get("field_size", p.default_field_size), "field_size")
        if target_field_size < 1:
            raise ValueError(f"field_size must be at least 1, got {target_field_size}")

        dist_str = inputs.get("distance")
        distance = parse_distance(dist_str) if dist_str else p.default_distance_m
        distance_specified = dist_str is not None

        is_open_division = (age_min <= 0 and age_max >= 90) or (gender == "ALL")
        division_str = (
            f"{gender} Open"
            if is_open_division
            else f"{gender} {age_min}+"
            if age_max >= 90
            else f"{gender} {age_min}-{age_max}"
        )

        steps: list[str] = []

        # Demographic field size smoothing (resolves random Poisson dips between popular adjacent brackets)
        total_race_size = inputs.get("total_field_size") or inputs.get("total_race_field_size")
        if total_race_size is not None:
            total_race_size = float(total_race_size)

        adjacent_counts = inputs.get("adjacent_counts") or inputs.get("bracket_counts")

        bracket_str = f"{age_min}-{age_max}"
        if not field_size_given and total_race_size is not None:
            g_share = get_gender_share(distance, gender) if gender != "ALL" else 1.0
            if is_open_division:
                target_field_size = max(round(total_race_size * g_share), 1)
                steps.append(
                    f"Estimated open division field size N={target_field_size} from total race size N={total_race_size:.0f} "
                    f"and gender share ({g_share:.1%} for {gender})."
                )
            else:
                b_share = get_demographic_share(age_min, age_max, distance, gender)
                target_field_size = max(round(total_race_size * g_share * b_share), 1)
                steps.append(
                    f"Estimated division field size N={target_field_size} from total race size N={total_race_size:.0f}, "
                    f"gender share ({g_share:.1%}), and demographic share ({b_share:.1%} for {division_str} at {distance_label(distance)})."
                )
        elif adjacent_counts or (total_race_size is not None and not is_open_division):
            raw_n = float(target_field_size)
            smoothed_n, expl = smooth_division_field_size(
                target_bracket=bracket_str,
                raw_division_size=raw_n,
                total_race_size=total_race_size,
                adjacent_counts=adjacent_counts,
                distance_m=distance,
                gender=gender,
            )
            if abs(smoothed_n - raw_n) >= 0.5:
                steps.append(expl)
                target_field_size = max(round(smoothed_n), 1)

        city = inputs.get("city")
        state = inputs.get("state")
        target_date = inputs.get("target_date")
        lat = _as_float(inputs["lat"], "lat") if "lat" in inputs else None
        lng = _as_float(inputs["lng"], "lng") if "lng" in inputs else None

        if (lat is None or lng is None) and city and state:
            coords = geocode_city_state(city, state)
            if coords:
                lat, lng = coords

        # 2. Extract historical editions, the gender-open history (for the cross-division prior) and prior runners
        hist_editions, prior_runners, overall_top3_rates, open_editions = self._load_history(
            inputs, gender, age_min, age_max, distance
        )
        if is_open_division or gender not in ("M", "F"):
            open_editions = []
        target_year = self._target_year(inputs, hist_editions + open_editions)

        # 3. Weather normalization of historical editions (only where weather is known)
        hist_penalties = []
        for e in hist_editions:
            e_temp = e.get("temp_f")
            e_dp = e.get("dew_point_f")
            e_date = e.get("date")
            if (e_temp is None or e_dp is None) and lat is not None and lng is not None and e_date:
                w = fetch_weather(lat, lng, str(e_date))
                if "temp_f" in w and "dew_point_f" in w:
                    e_temp = w["temp_f"]
                    e_dp = w["dew_point_f"]
            if e_temp is not None and e_dp is not None:
                pen = p.formula("weather_penalty", temp_f=float(e_temp), dew_point_f=float(e_dp), distance_m=distance)
            else:
                pen = 0.0
            hist_penalties.append(pen)
            e["times"] = [t / (1.0 + pen / 100.0) for t in e["times"]] if pen > 0.0 else list(e["times"])

        if any(pen > 0 for pen in hist_penalties):
            steps.append(
                "Normalized historical editions to weather-neutral conditions (penalties: "
                + ", ".join(f"+{pen:.1f}%" for pen in hist_penalties)
                + f" via [{p.expr('weather_penalty')}])."
            )

        # 4. Expected field size
        if not field_size_given and total_race_size is None and hist_editions:
            w_n = [p.recency_decay ** max(target_year - int(e["year"]), 0) for e in hist_editions]
            target_field_size = max(
                sum(w * float(e["field_size"]) for w, e in zip(w_n, hist_editions)) / sum(w_n), 1.0
            )
            steps.append(
                f"No field_size given: assumed the recency-weighted mean division field "
                f"N={target_field_size:.1f} (recency_decay = {p.recency_decay:g} per year back)."
            )
        n_target = float(target_field_size)

        # 5. Place estimates: own history (field-size shifted, weighted) shrunk toward the prior
        n_places = 6  # one extra place so overall-award exclusion can shift places down
        own_logs: list[float | None] = []
        own_w: list[float] = []
        mode = "history"
        if hist_editions:
            for k in range(1, n_places + 1):
                lt, wt = self._own_estimate(hist_editions, k, n_target, target_year)
                own_logs.append(lt)
                own_w.append(wt)
            steps.append(
                f"Own history: {len(hist_editions)} edition(s); each edition's k-th place log time is "
                f"shifted to N={n_target:.0f} by [{p.expr('order_score_shift')}] (score = expected "
                f"normal order score of the k-th fastest of N) and weighted by "
                f"[{p.expr('edition_weight')}]: 1st {format_time(math.exp(own_logs[0]))} "
                f"(weight {own_w[0]:.2f} editions)."
            )
        else:
            own_logs = [None] * n_places
            own_w = [0.0] * n_places

        prior_logs: list[float | None] = [None] * n_places
        mid_age = (age_min + min(age_max, p.open_ended_age_cap)) / 2.0
        age_factor = continuous_age_factor(mid_age, distance, gender) if gender in ("M", "F") else 1.0
        open_baseline = inputs.get("open_winning_time") or inputs.get("open_baseline_time")
        if open_editions:
            for k in range(1, n_places + 1):
                prior_logs[k - 1] = self._prior_estimate(open_editions, k, n_target, target_year, age_factor)
            steps.append(
                f"Cross-division prior from {len(open_editions)} {gender}-open edition(s): open winners "
                f"shifted to this division's N and place, times age factor {age_factor:.4f} (mid-age "
                f"{mid_age:.1f}) -> 1st {format_time(math.exp(prior_logs[0]))}."
            )
        elif not hist_editions and open_baseline is not None:
            t_open = parse_time(open_baseline)
            # The open baseline is taken as the open winner of a field the size of this division
            # (no field-size shift), as in v0.7.
            ed = [{"year": target_year, "field_size": n_target, "times": [t_open]}]
            for k in range(1, n_places + 1):
                prior_logs[k - 1] = self._prior_estimate(ed, k, n_target, target_year, age_factor)
            mode = "open baseline"
            steps.append(
                f"Derived division baseline from open baseline time {format_time(t_open)} using age "
                f"factor {age_factor:.4f} for {division_str} at {distance_label(distance)}: "
                f"{format_time(math.exp(prior_logs[0]))}; places 2-6 from order-score spacing."
            )

        place_logs: list[float] = []
        place_w: list[float] = []
        for k in range(n_places):
            own, wt, pr = own_logs[k], own_w[k], prior_logs[k]
            if own is not None and pr is not None and p.prior_weight > 0:
                place_logs.append(p.formula("shrunk_log_time", own=own, own_weight=wt, prior=pr))
                place_w.append(wt + p.prior_weight)
            elif own is not None:
                place_logs.append(own)
                place_w.append(wt)
            elif pr is not None:
                place_logs.append(pr)
                place_w.append(p.prior_weight)
            else:
                place_logs.append(math.nan)
                place_w.append(0.0)

        if math.isnan(place_logs[0]):
            # No history, no open information: rough judgement default
            mode = "default"
            dist_km = distance / 1000.0
            base_open_pace = p.default_open_pace_f if gender == "F" else p.default_open_pace_m
            t1_default = base_open_pace * (dist_km ** p.default_open_exponent) * age_factor
            gaps = self._default_gaps()
            place_logs = [math.log(t1_default)] + [math.log(t1_default + g * age_factor) for g in gaps]
            steps.append(
                f"No historical editions found; rough default baseline {format_time(t1_default)} (open winner "
                f"{base_open_pace:.0f} s/km x km^{p.default_open_exponent}, age factor {age_factor:.3f}). "
                f"Supply history for a real prediction."
            )
        elif any(pr is not None for pr in prior_logs) and hist_editions:
            steps.append(
                f"Shrunk own history toward the prior with prior_weight={p.prior_weight:g} editions "
                f"[{p.expr('shrunk_log_time')}]: 1st {format_time(math.exp(place_logs[0]))}."
            )

        t_field_times: list[float] = []
        for lt in place_logs:
            t = math.exp(lt)
            if t_field_times:
                t = max(t, t_field_times[-1] + p.min_tail_spread_sec)
            t_field_times.append(t)

        # Per-place uncertainty (log scale)
        if mode == "default":
            sigmas = [p.no_history_sigma_pct / 100.0] * n_places
        else:
            sigmas = [
                p.formula("place_sigma_pct", n=n_target, weight=max(w, 1e-6)) / 100.0 for w in place_w
            ]
        steps.append(
            f"Positions 1-5: " + ", ".join(f"#{i}: {format_time(t)}" for i, t in enumerate(t_field_times[:5], 1))
            + f". 1-sigma by place [{p.expr('place_sigma_pct')}]: "
            + ", ".join(f"{s * 100:.1f}%" for s in sigmas[:5]) + "."
        )

        # 6. Cohort aging-up & returning runner modeling
        t_field_1 = t_field_times[0]
        p_win_age_in = 0.0
        fastest_aging_proj: float | None = None
        aging_candidates = [r for r in prior_runners if r.get("age") == (age_min - 1)]
        cand_age = float(age_min - 1)
        if p.specs["annual_aging_decline_pct"].overridden:
            decline_pct = p.annual_aging_decline_pct
        else:
            decline_pct = get_annual_aging_decline_pct(cand_age, distance, gender)
        aging_sigma = max(sigmas[0] * t_field_1, p.min_aging_sigma_sec)

        cand_time: float | None = None
        cand_label = ""
        if aging_candidates and age_min > 0:
            fastest_cand = min(aging_candidates, key=lambda r: r["time"])
            cand_time = fastest_cand["time"]
            cand_label = f"Aging-in candidate {fastest_cand.get('name', f'Runner aged {age_min - 1}')}"
        elif inputs.get("prior_fastest_aging_in") and age_min > 0:
            cand_time = parse_time(inputs["prior_fastest_aging_in"])
            cand_label = "Specified aging-in contender"
        if cand_time is not None:
            fastest_aging_proj = p.formula("aged_time", prior_time=cand_time, annual_aging_decline_pct=decline_pct)
            p_win_raw = p.formula(
                "aging_win_probability", t_field=t_field_1, t_projected=fastest_aging_proj, sigma=aging_sigma
            )
            p_win_age_in = min(max(p_win_raw, 0.0), p.repeat_runner_prob)
            steps.append(
                f"{cand_label}: ran {format_time(cand_time)} at age {age_min - 1} last year; projected "
                f"{format_time(fastest_aging_proj)} at {age_min} (+{decline_pct:.2f}% age curve at "
                f"{distance_label(distance)}, [{p.expr('aged_time')}]). Chance of returning and winning: "
                f"{p_win_age_in:.1%} [{p.expr('aging_win_probability')}]."
            )

        if p_win_age_in > 0.0 and fastest_aging_proj is not None:
            post_aging_times = [p_win_age_in * min(fastest_aging_proj, t_field_1) + (1.0 - p_win_age_in) * t_field_1]
            for rank in range(2, n_places + 1):
                t_blended = p_win_age_in * t_field_times[rank - 2] + (1.0 - p_win_age_in) * t_field_times[rank - 1]
                post_aging_times.append(max(t_blended, post_aging_times[-1] + p.min_tail_spread_sec))
            steps.append(
                f"Blended with the aging-up contender: 1st {format_time(post_aging_times[0])}, "
                f"2nd {format_time(post_aging_times[1])}, 3rd {format_time(post_aging_times[2])}."
            )
        else:
            post_aging_times = list(t_field_times)

        # 7. Overall winner exclusion ("no double dipping")
        overall_awards_count = _as_int(inputs.get("overall_awards_count", p.overall_awards_count), "overall_awards_count")
        p_overall_exclude = 0.0
        if not is_open_division and overall_awards_count > 0:
            if overall_top3_rates:
                p_overall_exclude = overall_top3_rates.get(division_str, 0.0)
            elif age_min == 40 and gender == "M":
                p_overall_exclude = p.overall_exclusion_prob_m40
            elif age_min in (35, 45) and gender == "M":
                p_overall_exclude = p.overall_exclusion_prob_m35_45
            elif age_min in (35, 40) and gender == "F":
                p_overall_exclude = p.overall_exclusion_prob_f35_40
        if p_overall_exclude > 0.0:
            post_exclusion_times = [
                (1.0 - p_overall_exclude) * post_aging_times[r] + p_overall_exclude * post_aging_times[r + 1]
                for r in range(5)
            ]
            steps.append(
                f"Overall winner exclusion ('no double dipping'): {p_overall_exclude:.1%} chance an athlete in "
                f"{division_str} places in the overall top {overall_awards_count} and is removed from "
                f"age-group awards. 1st place: {format_time(post_aging_times[0])} -> "
                f"{format_time(post_exclusion_times[0])}."
            )
        else:
            post_exclusion_times = post_aging_times[:5]

        # 8. Target race weather adjustment
        target_temp_f = _first_present(inputs, "forecast_temp_f", "temp_f")
        target_dp_f = _first_present(inputs, "forecast_dew_point_f", "dew_point_f")
        weather_source = "input" if (target_temp_f is not None and target_dp_f is not None) else "climatology"
        if (target_temp_f is None or target_dp_f is None) and lat is not None and lng is not None and target_date:
            w_target = fetch_weather(lat, lng, str(target_date))
            if "temp_f" in w_target and "dew_point_f" in w_target:
                target_temp_f = w_target["temp_f"]
                target_dp_f = w_target["dew_point_f"]
                weather_source = w_target.get("source", "forecast")

        mean_pen = sum(hist_penalties) / len(hist_penalties) if hist_penalties else 0.0
        if target_temp_f is not None and target_dp_f is not None:
            target_penalty_pct = p.formula(
                "weather_penalty", temp_f=float(target_temp_f), dew_point_f=float(target_dp_f), distance_m=distance
            )
            steps.append(
                f"Target weather ({weather_source}): {float(target_temp_f):.1f}°F, dew point "
                f"{float(target_dp_f):.1f}°F -> +{target_penalty_pct:.2f}% [{p.expr('weather_penalty')}]."
            )
        else:
            target_penalty_pct = mean_pen
            if mean_pen > 0:
                steps.append(f"No forecast: applied the historical mean weather penalty (+{mean_pen:.2f}%).")

        final_times = [
            p.formula("weather_adjusted_time", time_neutral=t, weather_penalty_pct=target_penalty_pct)
            for t in post_exclusion_times
        ]

        # 9. Intervals (log-normal, per place)
        z = z_for_level(p.interval_level)
        sigma_total_pct = sigmas[0] * 100.0
        steps.append(
            f"Intervals at {p.interval_level:.0%}: t * exp(±{z:.2f} sigma); sigma_year_pct and "
            f"sigma_field_pct were fitted walk-forward on real races (RESEARCH.md) and already "
            f"include ordinary weather variation."
        )

        outcomes: list[Outcome] = []
        labels = ["1st place (winning time)", "2nd place time", "3rd place time", "4th place time", "5th place time"]
        groups = ["Podium Predictions", "Podium Predictions", "Podium Predictions", "Top 5 Places", "Top 5 Places"]
        notes = ["Expected division winner", "Podium finish", "Podium finish", "Division top 5", "Division top 5"]
        for t, sg, lbl, grp, note in zip(final_times, sigmas, labels, groups, notes):
            outcomes.append(
                Outcome(
                    label=lbl,
                    estimate=t,
                    interval=(t * math.exp(-z * sg), t * math.exp(z * sg)),
                    fmt="time",
                    group=grp,
                    note=note,
                )
            )

        # Probability outcome
        outcomes.append(
            Outcome(
                label="Aging-up runner wins division",
                probability=p_win_age_in,
                fmt="pct",
                group="Cohort Transitions",
                note=(
                    f"Contender aged {age_min - 1} turning {age_min}"
                    if fastest_aging_proj is not None
                    else "No aging-in contender supplied"
                ),
            )
        )

        # Pace outcomes if distance is specified
        if distance_specified:
            miles = distance / METERS_PER_MILE
            km = distance / METERS_PER_KM
            win_t = final_times[0]
            win_lo, win_hi = outcomes[0].interval  # type: ignore
            outcomes.append(
                Outcome(
                    label="Winning pace per mile",
                    estimate=win_t / miles,
                    interval=(win_lo / miles, win_hi / miles),
                    fmt="time",
                    group="Pace Estimates",
                    note=f"Distance: {distance_label(distance)}",
                )
            )
            outcomes.append(
                Outcome(
                    label="Winning pace per km",
                    estimate=win_t / km,
                    interval=(win_lo / km, win_hi / km),
                    fmt="time",
                    group="Pace Estimates",
                    note=f"Distance: {distance_label(distance)}",
                )
            )

        # Multi-division board if bracket_mode is requested
        bracket_mode = inputs.get("bracket_mode") or inputs.get("breakdown")
        if bracket_mode is True:
            bracket_mode = "5-year"

        board = None
        if bracket_mode:
            b_mode_str = str(bracket_mode).lower().strip()
            board = self.predict_all_brackets(inputs, breakdown=b_mode_str)
            steps.append(
                f"Generated full {b_mode_str} division awards board ({board['total_divisions']} categories)."
            )
            # Add division winners to outcomes grouped by gender/category
            for div in board["divisions"]:
                grp_name = f"{b_mode_str.title()} Awards ({'Men' if div['gender'] == 'M' else 'Women'})"
                if "masters" in b_mode_str:
                    grp_name = f"Masters Awards ({'Men' if div['gender'] == 'M' else 'Women'})"
                outcomes.append(
                    Outcome(
                        label=f"{div['label']} Winner",
                        estimate=div["winning_time_sec"],
                        interval=div["winning_interval_sec"],
                        fmt="time",
                        group=grp_name,
                        note=f"Pace: {div['pace_per_mile']}/mi | Field: {div['field_size']}",
                    )
                )

        shown_inputs = {
            "Race": race_name,
            "Division": division_str,
            "Expected field size": f"{target_field_size:.0f}",
            "Historical editions used": str(len(hist_editions)),
        }
        if open_editions:
            shown_inputs["Open-division editions (prior)"] = str(len(open_editions))
        if distance_specified:
            shown_inputs["Distance"] = distance_label(distance)
        if target_temp_f is not None and target_dp_f is not None:
            shown_inputs["Race weather"] = f"{float(target_temp_f):.1f}°F, {float(target_dp_f):.1f}°F dew pt ({weather_source})"
        if p_overall_exclude > 0.0:
            shown_inputs["Overall exclusion applied"] = f"Yes ({p_overall_exclude:.1%} chance)"
        if aging_candidates or inputs.get("prior_fastest_aging_in"):
            shown_inputs["Aging-up contenders tracked"] = "Yes"
        if bracket_mode and board:
            shown_inputs["Division breakdown"] = f"{bracket_mode} ({board['total_divisions']} divisions)"
        if "_discovered_years" in inputs:
            disc_years = sorted(inputs["_discovered_years"], reverse=True)
            shown_inputs["Discovered years"] = ", ".join(str(y) for y in disc_years)

        extras_payload: dict[str, Any] = {
            "final_times": final_times,
            "field_times": t_field_times[:5],
            "sigma_total_pct": sigma_total_pct,
            "p_win_age_in": p_win_age_in,
            "target_penalty_pct": target_penalty_pct,
            "n_target": n_target,
            "target_year": target_year,
            "sigmas_pct": [sg * 100.0 for sg in sigmas[:5]],
            "own_times": [math.exp(v) if v is not None else None for v in own_logs[:5]],
            "prior_times": [math.exp(v) if v is not None else None for v in prior_logs[:5]],
            "estimate_mode": mode,
        }
        if board:
            extras_payload["division_board"] = board
            extras_payload["division_table"] = board["summary_table"]
        if "_discovered_years" in inputs:
            extras_payload["discovered_years"] = sorted(inputs["_discovered_years"], reverse=True)

        return self.prediction(
            inputs=shown_inputs,
            outcomes=outcomes,
            steps=steps,
            interval_level=p.interval_level,
            extras=extras_payload,
        )

    def predict_all_brackets(
        self,
        inputs: dict[str, Any],
        breakdown: str = "5-year",
        gender: str | None = None,
    ) -> dict[str, Any]:
        """Generate podium predictions across all gender and age brackets for a given breakdown.

        Supported breakdowns:
        - '5-year': M & F 0-14, 15-19, 20-24, ..., 75-79, 80+ (30 divisions)
        - '10-year': M & F Under 20, 20-29, 30-39, 40-49, 50-59, 60-69, 70+ (14 divisions)
        - 'masters': Open, Masters (40+), Grand Masters (50+), Senior GM (60+), Veteran (70+) (10 divisions)

        Returns structured division board and formatted markdown comparison table.
        """
        div_specs = get_breakdown_divisions(breakdown, gender)
        race_name = str(inputs.get("race_name", "Road Race")).strip()
        dist_str = inputs.get("distance")
        distance = parse_distance(dist_str) if dist_str else self.params.default_distance_m

        # Base inputs copy without bracket_mode to prevent recursion
        base_inputs = dict(inputs)
        base_inputs.pop("bracket_mode", None)
        base_inputs.pop("breakdown", None)
        base_inputs.pop("all_brackets", None)

        # Pre-ingest URL once if provided, so subsequent division runs don't re-scrape
        results_url = base_inputs.get("results_url") or base_inputs.get("url")
        if results_url and "_discovered_editions" not in base_inputs:
            try:
                ingester = RaceResultsIngester()
                html_by_url = base_inputs.get("mock_html_by_url") or base_inputs.get("html_by_url")
                max_years = int(base_inputs.get("max_history_years", self.params.max_history_years))
                disc_eds = ingester.ingest_multi_year(
                    results_url, max_years=max_years, html_by_url=html_by_url
                )
                if disc_eds:
                    base_inputs["_discovered_editions"] = disc_eds
                    base_inputs["_discovered_years"] = [ed["year"] for ed in disc_eds]
            except Exception:
                pass

        # If history was supplied for a specific division, derive the open baseline so other divisions scale realistically
        orig_age_min = int(inputs.get("age_min", 40))
        orig_age_max = int(inputs.get("age_max", 44))
        orig_gender = str(inputs.get("gender", "M")).upper()
        orig_is_open = (orig_age_min <= 0 and orig_age_max >= 90) or (orig_gender == "ALL")

        if "history" in base_inputs and not orig_is_open:
            orig_mid = (orig_age_min + orig_age_max) / 2.0
            orig_factor = continuous_age_factor(orig_mid, distance, orig_gender)
            hist_t1 = [e["times"][0] for e in base_inputs["history"] if e.get("times")]
            if hist_t1:
                avg_t1 = sum(parse_time(t) if isinstance(t, str) else float(t) for t in hist_t1) / len(hist_t1)
                derived_open = avg_t1 / max(orig_factor, 0.5)
                base_inputs["_derived_open_baseline"] = derived_open

        divisions_data: list[dict[str, Any]] = []
        table_rows: list[str] = [
            "| Division | Exp. Field | 1st Place | 2nd Place | 3rd Place | Winning Pace | 80% CI |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]

        for spec in div_specs:
            div_inputs = {
                **base_inputs,
                "gender": spec["gender"],
                "age_min": spec["age_min"],
                "age_max": spec["age_max"],
            }
            # If this division is not the original division for which history was provided,
            # use the derived open baseline rather than copying the original division's times
            if "_derived_open_baseline" in base_inputs:
                is_same_div = (
                    spec["gender"] == orig_gender
                    and spec["age_min"] == orig_age_min
                    and spec["age_max"] == orig_age_max
                )
                if not is_same_div:
                    div_inputs.pop("history", None)
                    div_inputs.pop("prior_runners", None)
                    # Same gender with open_history given: prior-only estimate from that history
                    if not (base_inputs.get("open_history") and spec["gender"] == orig_gender):
                        div_inputs.pop("open_history", None)
                        div_inputs["open_baseline_time"] = base_inputs["_derived_open_baseline"]

            # A field_size above board_total_field_threshold is read as the whole race's size and
            # split into divisions; a smaller one is used as each division's size.
            if "field_size" in inputs and "total_field_size" not in inputs:
                raw_fs = float(inputs["field_size"])
                if raw_fs > self.params.board_total_field_threshold:
                    div_inputs.pop("field_size", None)
                    div_inputs["total_field_size"] = raw_fs

            pred = self.predict(div_inputs)
            extras = pred.extras
            t1, t2, t3, t4, t5 = extras["final_times"][:5]
            ci_lo, ci_hi = pred.primary.interval
            miles = distance / METERS_PER_MILE
            km = distance / METERS_PER_KM
            pace_mi = format_time(t1 / miles)
            pace_km = format_time(t1 / km)

            f_size = int(pred.inputs["Expected field size"])
            p_aging = float(extras.get("p_win_age_in", 0.0))

            div_info = {
                "label": spec["label"],
                "gender": spec["gender"],
                "age_min": spec["age_min"],
                "age_max": spec["age_max"],
                "field_size": f_size,
                "winning_time": format_time(t1),
                "winning_time_sec": t1,
                "podium_times": [format_time(t1), format_time(t2), format_time(t3)],
                "top_5_times": [format_time(t) for t in (t1, t2, t3, t4, t5)],
                "winning_interval": (format_time(ci_lo), format_time(ci_hi)),
                "winning_interval_sec": (ci_lo, ci_hi),
                "pace_per_mile": pace_mi,
                "pace_per_km": pace_km,
                "aging_runner_win_prob": p_aging,
            }
            divisions_data.append(div_info)

            table_rows.append(
                f"| **{spec['label']}** | {f_size} | **{format_time(t1)}** | {format_time(t2)} | "
                f"{format_time(t3)} | {pace_mi}/mi | {format_time(ci_lo)} - {format_time(ci_hi)} |"
            )

        markdown_table = "\n".join(table_rows)

        return {
            "race_name": race_name,
            "breakdown": breakdown,
            "distance": distance_label(distance),
            "total_divisions": len(divisions_data),
            "divisions": divisions_data,
            "summary_table": markdown_table,
        }

    def _target_year(self, inputs: dict[str, Any], editions: list[dict[str, Any]]) -> int:
        """Target edition year: `target_year`/`year` input, else target_date, else last edition + 1."""
        for key in ("target_year", "year"):
            if inputs.get(key) is not None:
                return _as_int(inputs[key], key)
        if inputs.get("target_date"):
            try:
                return int(str(inputs["target_date"])[:4])
            except ValueError:
                pass
        years = [int(e["year"]) for e in editions if e.get("year") is not None]
        return max(years) + 1 if years else 0

    def _order_score(self, k: int, n: float) -> float:
        """Expected standard-normal score of the k-th fastest of n finishers (Blom approximation).

        Very negative for the winner of a big field; used to shift times between field sizes."""
        a = self.params.order_score_alpha
        n = max(float(n), float(k))
        return _ND.inv_cdf((k - a) / (n + 1.0 - 2.0 * a))

    def _own_estimate(
        self, editions: list[dict[str, Any]], k: int, n_target: float, target_year: int
    ) -> tuple[float, float]:
        """Weighted mean log time of place k over earlier editions, each shifted to n_target.

        An edition with fewer than k known places contributes its slowest known place, shifted
        by the order-score difference. Returns (log time, total edition weight)."""
        p = self.params
        z_t = self._order_score(k, n_target)
        sw = sa = 0.0
        for e in editions:
            times = e["times"]
            m = min(k, len(times))
            n_e = max(float(e.get("field_size") or len(times)), float(len(times)))
            years_back = max(target_year - int(e.get("year") or target_year), 0)
            w = p.formula("edition_weight", years_back=years_back, n=n_e)
            shift = p.formula("order_score_shift", score_target=z_t, score_edition=self._order_score(m, n_e))
            sw += w
            sa += w * (math.log(times[m - 1]) + shift)
        return sa / sw, sw

    def _prior_estimate(
        self, open_editions: list[dict[str, Any]], k: int, n_target: float, target_year: int, age_factor: float
    ) -> float:
        """Cross-division prior: open winners shifted to this division's field size and place,
        times the bracket's age factor (log scale)."""
        p = self.params
        z_t = self._order_score(k, n_target)
        sw = sa = 0.0
        for e in open_editions:
            n_e = max(float(e.get("field_size") or 1), 1.0)
            years_back = max(target_year - int(e.get("year") or target_year), 0)
            w = p.recency_decay ** years_back
            shift = p.formula("order_score_shift", score_target=z_t, score_edition=self._order_score(1, n_e))
            sw += w
            sa += w * (math.log(e["times"][0]) + shift)
        return sa / sw + math.log(age_factor)

    def _load_history(
        self, inputs: dict[str, Any], gender: str, age_min: int, age_max: int, distance_m: float = 10000.0
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
        """Extract historical editions, prior runners, overall top-3 rates and gender-open editions."""
        editions: list[dict[str, Any]] = []
        prior_runners: list[dict[str, Any]] = []
        overall_top3_rates: dict[str, float] = {}
        open_editions: list[dict[str, Any]] = []

        # 1. Direct inputs history
        if "history" in inputs:
            for i, item in enumerate(inputs["history"], 1):
                raw_times = item.get("times") or item.get("top_times") or []
                if not raw_times:
                    raise ValueError(f"history edition {i} ({item.get('year', '?')}) needs a non-empty 'times' list")
                sec_times = sorted(parse_time(t) for t in raw_times)
                fs = item.get("field_size", self.params.default_field_size)
                if _as_int(fs, f"history edition {i} field_size") < 1:
                    raise ValueError(f"history edition {i}: field_size must be at least 1")
                editions.append({
                    "year": item.get("year"),
                    "date": item.get("date"),
                    "temp_f": item.get("temp_f"),
                    "dew_point_f": item.get("dew_point_f"),
                    "field_size": float(fs),
                    "times": sec_times[:6],
                })

        # 1b. Gender-open history (for the cross-division prior)
        for i, item in enumerate(inputs.get("open_history") or [], 1):
            raw_times = item.get("times") or ([item["time"]] if item.get("time") else [])
            if not raw_times or item.get("field_size") is None:
                raise ValueError(f"open_history edition {i} needs 'field_size' and 'times' (or 'time')")
            if _as_int(item["field_size"], f"open_history edition {i} field_size") < 1:
                raise ValueError(f"open_history edition {i}: field_size must be at least 1")
            open_editions.append({
                "year": item.get("year"),
                "field_size": float(item["field_size"]),
                "times": sorted(parse_time(t) for t in raw_times)[:6],
            })

        # 2. Direct prior runners
        raw_priors = inputs.get("prior_runners", inputs.get("prior_year_runners"))
        for i, r in enumerate(raw_priors or [], 1):
            if "age" not in r or "time" not in r:
                raise ValueError(f"prior runner {i} ({r.get('name', '?')}) needs 'age' and 'time'")
            prior_runners.append({
                "name": r.get("name", "Runner"),
                "age": _as_int(r["age"], f"prior runner {i} age"),
                "time": parse_time(r["time"]),
                "gender": str(r.get("gender", gender)).upper(),
            })

        # 3. URL Ingestion if results_url or url provided
        results_url = inputs.get("results_url") or inputs.get("url")
        if not editions and (results_url or "_discovered_editions" in inputs):
            try:
                discovered_editions = inputs.get("_discovered_editions")
                if not discovered_editions and results_url:
                    ingester = RaceResultsIngester()
                    html_by_url = inputs.get("mock_html_by_url") or inputs.get("html_by_url")
                    max_years = int(inputs.get("max_history_years", self.params.max_history_years))
                    discovered_editions = ingester.ingest_multi_year(
                        results_url, max_years=max_years, html_by_url=html_by_url
                    )
                    if not discovered_editions:
                        single_meta, single_records = ingester.ingest_url(
                            results_url, html=html_by_url.get(results_url) if html_by_url else None
                        )
                        if single_records:
                            discovered_editions = [{
                                "year": single_meta.get("year"),
                                "url": results_url,
                                "meta": single_meta,
                                "records": single_records,
                                "total_finishers": len(single_records),
                            }]

                if discovered_editions:
                    overall_top3_counts: dict[str, int] = {}
                    for ed in sorted(discovered_editions, key=lambda x: x["year"]):
                        y = ed["year"]
                        records = ed["records"]
                        # Track overall top 3
                        for r in records[:3]:
                            if r.age and r.age >= 35:
                                b_start = (r.age // 5) * 5
                                b_str = f"{r.gender} {b_start}-{b_start + 4}"
                                overall_top3_counts[b_str] = overall_top3_counts.get(b_str, 0) + 1

                        div_runners = [
                            r
                            for r in records
                            if (r.age is None or (age_min <= r.age <= age_max))
                            and (gender == "ALL" or r.gender == gender)
                        ]
                        g_times = sorted(r.chip_time_sec for r in records if r.gender == gender)
                        if g_times and not inputs.get("open_history"):
                            open_editions.append({"year": y, "field_size": float(len(g_times)), "times": g_times[:6]})
                        if div_runners:
                            sorted_times = sorted(r.chip_time_sec for r in div_runners)

                            adj_counts: dict[str, float] = {}
                            for r in records:
                                if gender != "ALL" and r.gender != gender:
                                    continue
                                if r.age:
                                    b_start = (r.age // 5) * 5
                                    b_key = f"{b_start}-{b_start + 4}"
                                    adj_counts[b_key] = adj_counts.get(b_key, 0.0) + 1.0

                            smoothed_n, _ = smooth_division_field_size(
                                target_bracket=f"{age_min}-{age_max}",
                                raw_division_size=float(len(div_runners)),
                                total_race_size=float(len(records)),
                                adjacent_counts=adj_counts,
                                distance_m=distance_m,
                                gender=gender,
                            )

                            editions.append({
                                "year": y,
                                "field_size": smoothed_n,
                                "times": sorted_times[:6],
                            })

                    if len(discovered_editions) > 1:
                        overall_top3_rates = {
                            k: min(v / len(discovered_editions), self.params.max_overall_exclusion_prob)
                            for k, v in overall_top3_counts.items()
                        }

                    # Contender tracking from most recent edition
                    latest_ed = max(discovered_editions, key=lambda x: x["year"])
                    for r in latest_ed["records"]:
                        if r.age is not None:
                            prior_runners.append({
                                "name": f"{r.first_name} {r.last_name}",
                                "age": r.age,
                                "time": r.chip_time_sec,
                                "gender": r.gender,
                            })

                    inputs["_discovered_years"] = [ed["year"] for ed in discovered_editions]
            except Exception:
                pass

        # 4. CSV file data loading if specified or fallback to sample_results
        csv_file = inputs.get("data_file")
        if not editions and csv_file:
            path = Path(csv_file)
            if not path.is_absolute() and not path.exists():
                path = self.dir / path
            if not path.exists():
                raise ValueError(f"data_file not found: {csv_file}")
            if path.exists():
                editions, file_priors, overall_top3_rates, file_open = self._parse_csv_results(
                    path, gender, age_min, age_max, distance_m
                )
                if not open_editions:
                    open_editions = file_open
                if not prior_runners:
                    prior_runners = file_priors

        # 4. Fallback if summary inputs provided
        if not editions and "hist_winning_mean" in inputs:
            t1 = parse_time(inputs["hist_winning_mean"])
            n_ref = float(inputs.get("hist_n_ref", self.params.default_field_size))
            gaps = self._default_gaps()
            editions.append({
                "year": None,
                "field_size": n_ref,
                "times": [t1] + [t1 + g for g in gaps],
                "temp_f": inputs.get("hist_temp_f"),
                "dew_point_f": inputs.get("hist_dew_point_f"),
            })

        return editions, prior_runners, overall_top3_rates, open_editions

    def _parse_csv_results(
        self, path: Path, gender: str, age_min: int, age_max: int, distance_m: float = 10000.0
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float], list[dict[str, Any]]]:
        """Parse an individual results CSV into division editions, prior contenders, overall
        pull rates and gender-open editions."""
        editions_by_year: dict[int, list[float]] = {}
        counts_by_year: dict[int, int] = {}
        all_runners_by_year: dict[int, list[dict[str, Any]]] = {}
        overall_top3_counts: dict[str, int] = {}

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                g = row.get("gender", "").strip().upper()
                try:
                    age = int(row["age"])
                    time_sec = parse_time(row["time"]) if "time" in row else float(row["chip_time_sec"])
                    year = int(row["year"])
                    place = int(row["place"]) if ("place" in row and str(row["place"]).isdigit()) else 999999
                except (KeyError, ValueError):
                    continue

                if year not in all_runners_by_year:
                    all_runners_by_year[year] = []
                all_runners_by_year[year].append({
                    "name": row.get("name", f"Runner_{len(all_runners_by_year[year])}"),
                    "age": age,
                    "time": time_sec,
                    "gender": g,
                    "place": place,
                })

                # Check if runner was in overall top 3
                if place <= 3 and age >= 35:
                    div_label = f"{g} {age // 5 * 5}-{age // 5 * 5 + 4}"
                    overall_top3_counts[div_label] = overall_top3_counts.get(div_label, 0) + 1

                if gender != "ALL" and g and g != gender:
                    continue

                if (age_min <= age <= age_max) or (age_min <= 0 and age_max >= 90):
                    counts_by_year[year] = counts_by_year.get(year, 0) + 1
                    if year not in editions_by_year:
                        editions_by_year[year] = []
                    editions_by_year[year].append(time_sec)

        editions = []
        for y in sorted(editions_by_year.keys()):
            times = sorted(editions_by_year[y])

            # Build adjacent counts for this specific year to regularize single-year Poisson dips
            raw_field_count = float(counts_by_year.get(y, 1))
            adj_counts: dict[str, float] = {}
            total_y_runners = float(len(all_runners_by_year.get(y, [])))
            for r in all_runners_by_year.get(y, []):
                if gender != "ALL" and r.get("gender") and r["gender"] != gender:
                    continue
                r_age = r["age"]
                b_str = f"{r_age // 5 * 5}-{r_age // 5 * 5 + 4}"
                adj_counts[b_str] = adj_counts.get(b_str, 0.0) + 1.0

            smoothed_field_count, _ = smooth_division_field_size(
                target_bracket=f"{age_min}-{age_max}",
                raw_division_size=raw_field_count,
                total_race_size=total_y_runners if total_y_runners > 0 else None,
                adjacent_counts=adj_counts,
                distance_m=distance_m,
                gender=gender,
            )

            editions.append({
                "year": y,
                "field_size": smoothed_field_count,
                "times": times[:6],
            })

        # Calculate overall top 3 rate per division
        num_years = max(len(editions_by_year), 1)
        p_max = self.params.max_overall_exclusion_prob
        top3_rates = {k: min(v / num_years, p_max) for k, v in overall_top3_counts.items()}

        prior_runners: list[dict[str, Any]] = []
        if all_runners_by_year:
            max_year = max(all_runners_by_year.keys())
            prior_runners = all_runners_by_year[max_year]

        open_editions = []
        if gender in ("M", "F"):
            for y in sorted(all_runners_by_year):
                g_times = sorted(r["time"] for r in all_runners_by_year[y] if r["gender"] == gender)
                if g_times:
                    open_editions.append({"year": y, "field_size": float(len(g_times)), "times": g_times[:6]})
        return editions, prior_runners, top3_rates, open_editions

    def _default_gaps(self) -> list[float]:
        """Default gaps (s) from 1st to 2nd..6th place when no history gives them."""
        gaps = [float(g) for g in self.params.default_gaps_sec]
        while len(gaps) < 5:
            gaps.append(gaps[-1] + self.params.missing_rank_gap_sec)
        return gaps[:5]

    @staticmethod
    def _parse_hist_column(text: str) -> list[dict[str, Any]]:
        """Parse "year:field_size:t1|t2|...;..." (backtest.csv history columns)."""
        out = []
        for chunk in text.split(";"):
            year, fs, times = chunk.split(":", 2)
            out.append({"year": int(year), "field_size": int(fs), "times": times.split("|")})
        return out

    def backtest_case(self, row: dict[str, str]) -> tuple[dict[str, Any], float]:
        """Convert a row of backtest.csv into (inputs, actual fastest division time in seconds).

        The target is the fastest division finisher, so the overall-award exclusion step is
        turned off. A blank field_size lets the model assume its expected field."""
        gender = row.get("gender", "M").strip().upper()
        inputs: dict[str, Any] = {
            "race_name": row.get("race", "Backtest Race"),
            "gender": gender,
            "age_min": int(row.get("age_min", 40)),
            "age_max": int(row.get("age_max", 44)),
            "overall_awards_count": 0,
        }
        if row.get("field_size"):
            inputs["field_size"] = int(float(row["field_size"]))
        if row.get("year"):
            inputs["target_year"] = int(row["year"])
        if row.get("distance"):
            inputs["distance"] = row["distance"]

        if row.get("history"):
            inputs["history"] = self._parse_hist_column(row["history"])
        elif row.get("hist_winning_mean"):
            inputs["hist_winning_mean"] = row["hist_winning_mean"]
            inputs["hist_n_ref"] = float(row.get("hist_n_ref") or self.params.default_field_size)
        if row.get("open_history"):
            inputs["open_history"] = self._parse_hist_column(row["open_history"])

        if row.get("prior_fastest_aging_in"):
            inputs["prior_fastest_aging_in"] = row["prior_fastest_aging_in"]
        if row.get("temp_f"):
            inputs["forecast_temp_f"] = float(row["temp_f"])
        if row.get("dew_point_f"):
            inputs["forecast_dew_point_f"] = float(row["dew_point_f"])

        return inputs, parse_time(row["actual_time"])
