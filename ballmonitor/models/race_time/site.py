"""Public page: what a 5K time says about the other common race distances.

Built at site-build time (`ballmonitor build-site`, `ballmonitor views race_time`): one
model.predict() per 5K time and gender, using only the committed band fit. No runner data or
names are shown; the inputs are a grid of round 5K times.
"""

from __future__ import annotations

from ballmonitor.core import views as V

GENDERS = (("M", "Men"), ("F", "Women"))
COLUMNS = (("mile", "Mile"), ("10k", "10K"), ("half", "Half Marathon"), ("marathon", "Marathon"))
RANGE_ROWS = ("Mile", "10K", "15K", "10 Mile", "Half Marathon", "Marathon")
NICE = {"Half Marathon": "Half marathon", "10 Mile": "10 miles"}


def _bench(model, gender: str, five_k_sec: float) -> dict[str, dict]:
    pred = model.predict({"target": "marathon", "gender": gender,
                          "races": [{"distance": "5k", "time": five_k_sec}]})
    return {b["label"]: b for b in pred.extras["benchmarks"]}


def page(model) -> dict:
    p = model.params
    fast, slow, step = int(p.site_5k_fastest_sec), int(p.site_5k_slowest_sec), int(p.site_5k_step_sec)
    grid = list(range(fast, slow + 1, step))
    example = float(p.site_example_5k_sec)

    options, lines = [], []
    for g, g_name in GENDERS:
        rows, points, band = [], [], []
        for t in grid:
            b = _bench(model, g, t)
            row = {"five_k": t}
            for key, label in COLUMNS:
                row[key] = round(b[label]["p50_sec"], 1)
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
        sure_rows = [{
            "distance": NICE.get(lbl, lbl),
            "fast": b[lbl]["p10_sec"], "low": b[lbl]["p25_sec"], "mid": b[lbl]["p50_sec"],
            "high": b[lbl]["p75_sec"], "slow": b[lbl]["p90_sec"],
        } for lbl in RANGE_ROWS]
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
        options.append(V.option(g_name, [equiv, sure]))

    chart = V.line(
        "marathon_vs_5k", "Marathon time from your 5K", lines,
        x_label="5K time", y_label="Marathon time", x_fmt="time", y_fmt="time",
        subtitle="The line is the most likely marathon time; the shaded area is where 8 in 10 runners finish.")

    return V.page(
        title="Race time calculator",
        summary="What your 5K time says you could run for a mile, 10K, half marathon or marathon.",
        sport="Running",
        updated="Ranges checked against 2018-2025 race results",
        how=("Longer races are slower per mile, and the model stretches a 5K time to each distance with a "
             "simple, well-known rule (women slow down a little less than men as races get longer). "
             "The ranges come from about 5,000 real road racers in Ohio whose later race times we compared "
             "with what their earlier races predicted."),
        views=[V.picker("by_gender", "Equivalent times", "Runners", options), chart],
    )
