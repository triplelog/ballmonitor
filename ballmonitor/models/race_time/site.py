"""Public page: a calculator (your races in, every distance out) and what a 5K time says about
the other common race distances.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views race_time`): the tables
are one model.predict() per 5K time and gender, using only the committed band fit. The
calculator (web/static/apps/race_time.js) is a copy of the default method's formulas, fed the
model's parameters from here; tests/test_race_calc.py checks it against model.predict. No runner
data or names are shown.
"""

from __future__ import annotations


from ballmonitor.core import units
from ballmonitor.core import views as V
from ballmonitor.models.race_time.bands import BAND_FEATURES, QUANTILE_KEYS, QUANTILE_LEVELS, param_name
from ballmonitor.models.race_time.model import BENCHMARKS

GENDERS = (("M", "Men"), ("F", "Women"))
COLUMNS = (("mile", "Mile"), ("10k", "10K"), ("half", "Half Marathon"), ("marathon", "Marathon"))
RANGE_ROWS = ("Mile", "10K", "15K", "10 Mile", "Half Marathon", "Marathon")
NICE = {"Half Marathon": "Half marathon", "10 Mile": "10 miles"}


def _to_minute(sec: float) -> float:
    """Marathon times are shown to the minute: the seconds aren't meaningful at that distance."""
    return round(sec / 60) * 60


def _clock(sec: float) -> str:
    """5025 -> "1:23:45"; under an hour -> "25:00"."""
    sec = int(round(sec))
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _hm(sec: float) -> str:
    """Long-race time to the minute: 15000 -> "4:10"."""
    m = int(round(sec / 60))
    return f"{m // 60}:{m % 60:02d}"


CALC_INPUTS = ("Mile", "5K", "8K", "10K", "15K", "10 Mile", "Half Marathon", "Marathon")   # races you can enter
CALC_TICKS = (("Mile", "Mile"), ("5K", "5K"), ("10K", "10K"), ("Half Marathon", "Half"), ("Marathon", "Marathon"))
CALC_WHENS = ((0.0, "This month"), (0.25, "3 months ago"), (0.5, "6 months ago"), (1.0, "1 year ago"),
              (2.0, "2 years ago"), (3.0, "3 or more years ago"))
CALC_GENDERS = (("M", "Men"), ("F", "Women"), ("", "Not saying"))
CALC_CURVE_POINTS = 40
CALC_MAX_RACES = 6
CALC_ADD_ORDER = ("10K", "Half Marathon", "Marathon", "5K", "Mile", "8K", "15K", "10 Mile")   # "Add another race" picks the first unused


def _key(label: str) -> str:
    return V.slug(label)


def calculator_data(model) -> dict:
    """Everything the calculator needs: the default method's parameters (read from the config,
    so a tweak reaches the page) and the distances it reports."""
    p = model.params
    if p.method != "weighted_riegel":
        raise ValueError("the race time calculator copies the weighted_riegel method; method is " + str(p.method))
    exponents = {g: float(p.formula("exponent", male=1.0 if g == "M" else 0.0, female=1.0 if g == "F" else 0.0))
                 for g, _ in CALC_GENDERS}
    by_label = {lbl: m for lbl, m, _ in BENCHMARKS}
    lo, hi = by_label["Mile"], by_label["Marathon"]
    example = float(p.site_example_5k_sec)
    return {
        "exponent": {"base": float(p.riegel_exponent), "male": float(p.exponent_offset_male),
                     "female": float(p.exponent_offset_female)},
        "weights": {"distance_scale": float(p.race_weight_distance_scale),
                    "half_life_years": float(p.race_weight_half_life_years)},
        "combination": str(p.race_combination),
        "bands": {"levels": list(QUANTILE_LEVELS),
                  "coef": [[float(p[param_name(k, f)]) for f in BAND_FEATURES] for k in QUANTILE_KEYS],
                  "max_years": float(p.band_max_years), "max_races": int(p.band_max_races),
                  "scale": float(p.band_scale)},
        "distances": [{"key": _key(lbl), "label": NICE.get(lbl, lbl), "meters": m, "input": lbl in CALC_INPUTS}
                      for lbl, m, _ in BENCHMARKS],
        "curve": [lo * (hi / lo) ** (i / (CALC_CURVE_POINTS - 1)) for i in range(CALC_CURVE_POINTS)],
        "ticks": [[by_label[lbl], name] for lbl, name in CALC_TICKS],
        "meters_per_mile": units.METERS_PER_MILE,
        "genders": [list(g) for g in CALC_GENDERS],
        "default_gender": "M",
        "typical": exponents,
        "own_curve_margin": float(p.site_own_curve_margin),
        "whens": [list(w) for w in CALC_WHENS],
        "max_races": CALC_MAX_RACES,
        "add_order": [_key(lbl) for lbl in CALC_ADD_ORDER],
        "pace_limits": [float(p.site_calc_fastest_pace_sec), float(p.site_calc_slowest_pace_sec)],
        # placeholder starting races (not anyone's real results): the page's example 5K time and a
        # half marathon six months ago, so the table and chart show something at once
        "example": [{"distance": _key("5K"), "time": _clock(example), "when": 0.0},
                    {"distance": _key("Half Marathon"), "time": _clock(example * 4.6), "when": 0.5}],
    }


def _bench(model, gender: str, five_k_sec: float) -> dict[str, dict]:
    pred = model.predict({"target": "marathon", "gender": gender,
                          "races": [{"distance": "5k", "time": five_k_sec}]})
    return {b["label"]: b for b in pred.extras["benchmarks"]}


def page(model) -> dict:
    p = model.params
    fast, slow, step = int(p.site_5k_fastest_sec), int(p.site_5k_slowest_sec), int(p.site_5k_step_sec)
    grid = list(range(fast, slow + 1, step))
    example = float(p.site_example_5k_sec)

    options, lines, answers = [], [], {}
    for g, g_name in GENDERS:
        rows, points, band = [], [], []
        for t in grid:
            b = _bench(model, g, t)
            row = {"five_k": t}
            for key, label in COLUMNS:
                row[key] = round(b[label]["p50_sec"], 1)
            row["marathon"] = _to_minute(row["marathon"])
            row["pace"] = b["Marathon"]["pace_per_mile_sec"]
            rows.append(row)
            m = b["Marathon"]
            points.append((t, m["p50_sec"]))
            band.append((t, m["p10_sec"], m["p90_sec"]))
        lines.append(V.series(g_name, points, band))

        equiv = V.table(
            f"equivalent_{g}", f"Equivalent race times ({g_name.lower()})",
            [V.col("five_k", "Your 5K", "time"), V.col("mile", "Mile", "time"), V.col("10k", "10K", "time"),
             V.col("half", "Half marathon", "time"), V.col("marathon", "Marathon", "time"),
             V.col("pace", "Marathon pace / mile", "time")],
            rows, search=True, page_size=20,
            subtitle="Find your 5K time to see the most likely time at each distance with the same training.",
            note="Assumes a flat course, normal weather and proper training for the longer race. "
                 "The marathon is the hardest to predict: many runners finish slower than this.")

        b = _bench(model, g, example)
        sure_rows = []
        for lbl in RANGE_ROWS:
            r = (_to_minute if lbl == "Marathon" else (lambda x: x))
            sure_rows.append({"distance": NICE.get(lbl, lbl),
                              **{k: r(b[lbl][f"{q}_sec"]) for k, q in
                                 (("fast", "p10"), ("low", "p25"), ("mid", "p50"), ("high", "p75"), ("slow", "p90"))}})
        ex = f"{int(example // 60)}:{int(example % 60):02d}"
        sure = V.table(
            f"range_{g}", f"How sure is it? A {ex} 5K ({g_name.lower()})",
            [V.col("distance", "Distance"), V.col("fast", "Fast end", "time"),
             V.col("low", "Middle half from", "time"), V.col("mid", "Most likely", "time"),
             V.col("high", "Middle half to", "time"), V.col("slow", "Slow end", "time")],
            sure_rows,
            subtitle=(f"Runners with the same {ex} 5K don't all run the same marathon. Half land in the "
                      "middle range; 8 in 10 land between the fast and slow ends."),
            note="The ranges come from how real runners' later races compared with their 5K times.")
        half, mara = b["Half Marathon"]["p50_sec"], _to_minute(b["Marathon"]["p50_sec"])
        answers[g] = (half, mara)
        intro = (f"A {ex} 5K: about {_hm(half)} for the half marathon and {_hm(mara)} for the marathon; "
                 f"8 in 10 finish the marathon between {_hm(_to_minute(b['Marathon']['p10_sec']))} and "
                 f"{_hm(_to_minute(b['Marathon']['p90_sec']))}.")
        options.append(V.option(g_name, [equiv, sure], intro=intro))

    chart = V.line(
        "marathon_vs_5k", "Marathon time from your 5K", lines,
        x_label="5K time", y_label="Marathon time", x_fmt="time", y_fmt="time",
        subtitle="The line is the most likely marathon time; the shaded area is where 8 in 10 runners finish.")

    calculator = V.app(
        "calculator", "Your races, every distance", "race_time", calculator_data(model),
        subtitle="Enter one or more recent races. You get the most likely time at every distance, "
                 "using all of them: the closer a race is to a distance, and the more recent it is, "
                 "the more it counts.",
        note="Assumes a flat course, normal weather and proper training for each distance. The range is "
             "where 8 in 10 runners like you finish; it widens with old races and long jumps in distance.")

    ex = _clock(example)
    (mh, mm), (fh, fm) = answers["M"], answers["F"]
    headline = (f"A {ex} 5K points to about a {_hm(mh)} half marathon and a {_hm(mm)} marathon for men "
                f"({_hm(fh)} and {_hm(fm)} for women).")

    return V.page(
        title="Race time calculator",
        headline=headline,
        summary="Enter your recent races and see what they say you could run at every distance, from the mile "
                "to the marathon.",
        sport="Running",
        updated="Ranges checked against 2018-2025 race results",
        how=("Longer races are slower per mile, and the model stretches a 5K time to each distance with a "
             "simple, well-known rule (women slow down a little less than men as races get longer). "
             "The ranges come from about 5,000 real road racers in Ohio whose later race times we compared "
             "with what their earlier races predicted."),
        views=[calculator, V.picker("by_gender", "Equivalent times", "Runners", options), chart],
    )
