"""The one place output appearance is defined. Every model's output goes through here.

Text layout (every model, always in this order):

    ══════  TITLE  ·  model vX.Y.Z  ·  status  ══════
    question
    INPUTS                 what was fed in
    RESULT                 outcome table (estimate / interval / probability / note)
    HOW IT WAS COMPUTED    numbered steps recorded by the model
    PARAMETERS             every parameter and formula; * marks changes from config.toml
    KEY ASSUMPTIONS        from config.toml [meta].assumptions
    docs pointer
"""

from __future__ import annotations

import json
import math
import textwrap

from ballmonitor.core.backtest import CLOSER_TO_ZERO, HIGHER_IS_BETTER, METRIC_NOTES, TARGETS, BacktestResult
from ballmonitor.core.params import ParamSpec
from ballmonitor.core.prediction import Outcome, Prediction
from ballmonitor.core.units import format_time

WIDTH = 78
HEAVY = "═" * WIDTH
LIGHT = "─"


# ── value formatting ─────────────────────────────────────────────────────────

def format_value(value: float | None, fmt: str) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    match fmt:
        case "pct":
            return f"{value * 100:.1f}%"
        case "time":
            return format_time(value)
        case "currency":
            return f"${value:,.0f}" if abs(value) >= 1000 else f"${value:,.2f}"
        case "int":
            return f"{round(value):,}"
        case "points":
            return f"{value:+.1f}"
        case _:
            if abs(value) >= 1000:
                return f"{value:,.0f}"
            return f"{value:,.3g}" if abs(value) < 1 else f"{value:,.2f}"


def format_probability(p: float | None) -> str:
    if p is None:
        return ""
    if p < 0.001:
        return "<0.1%"
    if p > 0.999:
        return ">99.9%"
    return f"{p * 100:.1f}%"


def format_param(spec: ParamSpec) -> str:
    value = spec.value
    text = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{text} {spec.unit}".strip()


# ── text ─────────────────────────────────────────────────────────────────────

def render_text(pred: Prediction) -> str:
    out = [HEAVY, _header(pred.title.upper(), f"{pred.model} v{pred.version} · {pred.status}")]
    if pred.variant:
        out.append(f" variant: {pred.variant}")
    out += wrap(pred.question, indent=" ")
    out.append(HEAVY)

    out += _section("INPUTS", _leaders(pred.inputs))
    out += _section("RESULT", _outcome_table(pred))
    for table in pred.tables:
        out += _section(table.title.upper(), _table_lines(table))
    if pred.steps:
        steps = []
        for i, step in enumerate(pred.steps, 1):
            steps += wrap(step, indent=f"   {i:>2}. ", subsequent=" " * 7)
        out += _section("HOW IT WAS COMPUTED", steps)
    out += _section("PARAMETERS   (* = changed from config.toml)", _param_lines(pred))
    if pred.assumptions:
        bullets = []
        for a in pred.assumptions:
            bullets += wrap(a, indent="   • ", subsequent="     ")
        out += _section("KEY ASSUMPTIONS", bullets)
    out += ["", f" Full documentation: {pred.doc}", HEAVY]
    return "\n".join(out)


def _header(left: str, right: str) -> str:
    gap = max(2, WIDTH - len(left) - len(right) - 2)
    return f" {left}{' ' * gap}{right}"


def wrap(text: str, indent: str = "", subsequent: str | None = None) -> list[str]:
    if not text:
        return []
    return textwrap.wrap(
        text, WIDTH, initial_indent=indent,
        subsequent_indent=subsequent if subsequent is not None else indent,
    )


def _section(title: str, lines: list[str]) -> list[str]:
    return ["", f" {title}", *lines]


def _leaders(items: dict[str, str], marks: dict[str, str] | None = None) -> list[str]:
    if not items:
        return ["   (none)"]
    width = max(len(k) for k in items) + 4
    lines = []
    for key, value in items.items():
        mark = (marks or {}).get(key, " ")
        head = f" {mark} {key} {'.' * (width - len(key))} "
        if len(head) + len(str(value)) <= WIDTH:
            lines.append(head + str(value))
        else:  # long values (lists) wrap under themselves
            lines += textwrap.wrap(str(value), WIDTH, initial_indent=head, subsequent_indent=" " * len(head),
                                   break_on_hyphens=False) or [head]
    return lines


def _outcome_columns(pred: Prediction) -> list[tuple[str, callable]]:
    outcomes = pred.outcomes
    cols: list[tuple[str, callable]] = [("Outcome", lambda o: o.label)]
    if any(o.estimate is not None for o in outcomes):
        cols.append(("Estimate", lambda o: format_value(o.estimate, o.fmt)))
    if any(o.interval is not None for o in outcomes):
        level = f"{pred.interval_level * 100:g}% range" if pred.interval_level else "Range"
        cols.append((level, lambda o: (
            f"{format_value(o.interval[0], o.fmt)} – {format_value(o.interval[1], o.fmt)}"
            if o.interval else ""
        )))
    if any(o.probability is not None for o in outcomes):
        cols.append(("Probability", lambda o: format_probability(o.probability)))
    if any(o.note for o in outcomes):
        cols.append(("Note", lambda o: o.note))
    return cols


def _outcome_table(pred: Prediction) -> list[str]:
    cols = _outcome_columns(pred)
    cells = [[fn(o) for _, fn in cols] for o in pred.outcomes]
    widths = [max(len(h), *(len(r[i]) for r in cells)) for i, (h, _) in enumerate(cols)]

    # Keep the table within WIDTH: wrap a long Note column (always last) onto extra lines,
    # or, if the other columns leave it too little room, print notes under their rows.
    # Columns are 3 spaces apart, or 2 when 3 would not fit.
    gap = 3 if 3 + sum(widths) + 3 * (len(widths) - 1) <= WIDTH else 2
    notes_below = False
    note_lines: list[list[str]] = [[] for _ in cells]
    if cols[-1][0] == "Note":
        note_lines = [[r[-1]] for r in cells]
        room = WIDTH - (3 + sum(widths[:-1]) + gap * (len(widths) - 1))
        if widths[-1] > room:
            if room >= 20:
                note_lines = [textwrap.wrap(r[-1], room) or [""] for r in cells]
                widths[-1] = max(len("Note"), *(len(line) for lines in note_lines for line in lines))
            else:
                notes_below = True
                note_lines = [wrap(r[-1], "       ") for r in cells]
                cols, widths, cells = cols[:-1], widths[:-1], [r[:-1] for r in cells]

    def row(values: list[str]) -> str:
        parts = [
            v.ljust(w) if header in ("Outcome", "Note") else v.rjust(w)
            for (header, _), v, w in zip(cols, values, widths)
        ]
        return ("   " + (" " * gap).join(parts)).rstrip()

    lines = [row([h for h, _ in cols]), "   " + LIGHT * (sum(widths) + gap * (len(widths) - 1))]
    group = None
    for outcome, values, notes in zip(pred.outcomes, cells, note_lines):
        if outcome.group != group:
            group = outcome.group
            if group:
                lines.append(f"   ▸ {group}")
        if notes_below:
            lines += [row(values), *notes]
        elif notes:
            lines.append(row(values[:-1] + [notes[0]]))
            lines += [row([""] * (len(cols) - 1) + [extra]) for extra in notes[1:]]
        else:
            lines.append(row(values))
    return lines


def _param_lines(pred: Prediction) -> list[str]:
    items = {p.name: format_param(p) + (f"   (default {p.default})" if p.overridden else "") for p in pred.params}
    marks = {p.name: "*" for p in pred.params if p.overridden}
    lines = _leaders(items, marks) if items else []
    for f in pred.formulas:
        mark = "*" if f.overridden else " "
        lines += wrap(f"{f.name} = {f.expr}", indent=f" {mark} ƒ ", subsequent="       ")
    return lines or ["   (none)"]


# ── markdown / json ──────────────────────────────────────────────────────────

def render_markdown(pred: Prediction) -> str:
    out = [f"## {pred.title}", "", f"*{pred.question}*", "",
           f"`{pred.model}` v{pred.version} · status: {pred.status}"
           + (f" · variant: `{pred.variant}`" if pred.variant else ""), ""]
    out += ["### Inputs", ""] + [f"- **{k}**: {v}" for k, v in pred.inputs.items()] + [""]
    cols = _outcome_columns(pred)
    out += ["### Result", "", "| " + " | ".join(h for h, _ in cols) + " |",
            "|" + "|".join("---" for _ in cols) + "|"]
    cell = lambda v: str(v).replace("|", "\\|")  # noqa: E731  (a "|" would split the cell)
    for o in pred.outcomes:
        label = f"{o.group}: {o.label}" if o.group else o.label
        out.append("| " + " | ".join(cell(c) for c in [label] + [fn(o) for _, fn in cols[1:]]) + " |")
    out.append("")
    for table in pred.tables:
        out += [f"### {table.title}", "", "| " + " | ".join(cell(c) for c in table.columns) + " |",
                "|" + "|".join("---" for _ in table.columns) + "|"]
        out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in table.rows]
        out += (["", f"*{table.note}*"] if table.note else []) + [""]
    if pred.steps:
        out += ["### How it was computed", ""] + [f"{i}. {s}" for i, s in enumerate(pred.steps, 1)] + [""]
    out += ["### Parameters", "", "| | name | value |", "|---|---|---|"]
    out += [f"| {'*' if p.overridden else ''} | `{p.name}` | {format_param(p)} |" for p in pred.params]
    out += [f"| {'*' if f.overridden else ''} | ƒ `{f.name}` | `{f.expr}` |" for f in pred.formulas]
    out.append("")
    if pred.assumptions:
        out += ["### Key assumptions", ""] + [f"- {a}" for a in pred.assumptions] + [""]
    out.append(f"Docs: `{pred.doc}`")
    return "\n".join(out)


def render_json(pred: Prediction) -> str:
    return json.dumps(pred.to_dict(), indent=2, default=str)


RENDERERS = {"text": render_text, "md": render_markdown, "json": render_json}


def render(pred: Prediction, fmt: str = "text") -> str:
    return RENDERERS[fmt](pred)


# ── comparisons & backtests (same visual language) ───────────────────────────

def render_comparison(preds: list[Prediction]) -> str:
    """Side-by-side primary numbers for the same inputs under different variants."""
    names = [p.variant or "base" for p in preds]
    first = preds[0]
    out = [HEAVY, _header(f"{first.title.upper()} — VARIANT COMPARISON", f"{first.model} v{first.version}"),
           HEAVY]
    out += _section("INPUTS", _leaders(first.inputs))

    def cell(o: Outcome) -> str:
        if o.estimate is not None:
            return format_value(o.estimate, o.fmt)
        return format_probability(o.probability)

    rows = [[o.label] + [cell(p.outcome(o.label)) for p in preds] for o in first.outcomes]
    out += _section("RESULT", _grid(["Outcome", *names], rows))

    changes = []
    for p in preds[1:]:
        diffs = [f"{s.name}: {s.default} → {s.value}" for s in p.params if s.overridden]
        diffs += [f"ƒ {f.name}: {f.expr}" for f in p.formulas if f.overridden]
        changes += wrap(f"{p.variant or 'base'}: " + ("; ".join(diffs) or "no changes"), indent="   ")
    if changes:
        out += _section("CHANGES FROM BASE CONFIG", changes)
    out.append(HEAVY)
    return "\n".join(out)


def render_backtest(results: list[BacktestResult]) -> str:
    first = results[0]
    names = [r.variant or "base" for r in results]
    out = [HEAVY, _header("BACKTEST", f"{first.model}"), HEAVY]

    def metric_rows(n_of, metrics_of) -> list[list[str]]:
        metrics = list(dict.fromkeys(m for r in results for m in metrics_of(r)))
        rows = [["cases scored", *(str(n_of(r)) for r in results)]]
        for m in metrics:
            if m in TARGETS:
                label = METRIC_NOTES.get(m, m)
            else:
                better = "closer to 0" if m in CLOSER_TO_ZERO else "higher" if m in HIGHER_IS_BETTER else "lower"
                label = f"{METRIC_NOTES.get(m, m)} ({better} = better)"
            rows.append([label, *(format_value(metrics_of(r).get(m), "number") for r in results)])
        return rows

    groups = list(dict.fromkeys(g for r in results for g in r.groups))
    out += _section("METRICS — all cases" if groups else "METRICS",
                    _grid(["Metric", *names], metric_rows(lambda r: r.n, lambda r: r.metrics)))
    for g in groups:
        out += _section(f"METRICS — {g}", _grid(["Metric", *names], metric_rows(
            lambda r: r.group_n.get(g, 0), lambda r: r.groups.get(g, {}))))
    failures = [f"   {r.variant or 'base'} {msg}" for r in results for msg in r.failures]
    if failures:
        out += _section("ROWS THAT FAILED", failures)
    out.append(HEAVY)
    return "\n".join(out)


def _table_lines(table) -> list[str]:
    """A Table as text: split into blocks of columns (each repeating the first column) so no
    line is wider than WIDTH; the first column is cut to at most 24 characters."""
    rows = [list(map(str, r)) for r in table.rows]
    first_w = min(24, max(len(x) for x in [table.columns[0]] + [r[0] for r in rows]))
    cut = lambda t: t if len(t) <= first_w else t[: first_w - 1] + "…"  # noqa: E731
    widths = [max(len(str(x)) for x in [table.columns[i]] + [r[i] for r in rows]) for i in range(1, len(table.columns))]
    lines: list[str] = []
    i = 0
    while i < len(widths):
        used, j = 3 + first_w, i
        while j < len(widths) and (j == i or used + 2 + widths[j] <= WIDTH):
            used += 2 + widths[j]
            j += 1
        cols = range(i, j)
        fmt = lambda vals: "   " + cut(vals[0]).ljust(first_w) + "".join(  # noqa: E731
            "  " + vals[k + 1].rjust(widths[k]) for k in cols)
        if lines:
            lines.append("")
        lines.append(fmt([table.columns[0]] + table.columns[1:]))
        lines.append("   " + LIGHT * (used - 3))
        lines += [fmt(r) for r in rows]
        i = j
    if table.note:
        lines += [""] + wrap(table.note, indent="   ")
    return lines


def _grid(header: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]

    def row(values: list[str]) -> str:
        return "   " + "   ".join(
            [values[0].ljust(widths[0])] + [v.rjust(w) for v, w in zip(values[1:], widths[1:])]
        )

    return [row(header), "   " + LIGHT * (sum(widths) + 3 * (len(widths) - 1)), *map(row, rows)]
