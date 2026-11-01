"""Command line: list, params, run, compare, backtest, new.

    ballmonitor list
    ballmonitor params race_time
    ballmonitor run race_time                                  # uses examples/default.toml
    ballmonitor run race_time --example two_races --set fit_weight=0.9
    ballmonitor run race_time --in target=10k --format md
    ballmonitor run race_time --set 'formulas.predict=t * (D / d) ** 1.07'
    ballmonitor compare race_time --variant trust_fit --variant pure_riegel
    ballmonitor backtest race_time --variant trust_fit
    ballmonitor new nfl_win_totals --title "NFL win totals"
    ballmonitor serve --port 8765                              # browser UI
    ballmonitor fetch sp500                                    # download/rebuild a model's data
"""

from __future__ import annotations

import argparse
import json
import importlib
import sys
from pathlib import Path
from typing import Any

from ballmonitor.core import backtest as bt
from ballmonitor.core import registry, render
from ballmonitor.core.config import parse_assignments, read_toml
from ballmonitor.core.formula import FormulaError
from ballmonitor.core.params import ConfigError


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ConfigError, FormulaError, KeyError, ValueError, FileExistsError,
            registry.ModelNotReady, NotImplementedError, FileNotFoundError, ImportError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ballmonitor", description="Simple, open probability models.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list models, their status, examples and variants")
    p.set_defaults(handler=cmd_list)

    p = sub.add_parser("params", help="show every parameter and formula with its documentation")
    p.add_argument("model")
    _add_tweak_args(p)
    p.set_defaults(handler=cmd_params)

    p = sub.add_parser("run", help="run a model and print the standard report")
    p.add_argument("model")
    _add_input_args(p)
    _add_tweak_args(p)
    p.add_argument("--format", choices=sorted(render.RENDERERS), default="text")
    p.set_defaults(handler=cmd_run)

    p = sub.add_parser("compare", help="run the base config and one or more variants side by side")
    p.add_argument("model")
    _add_input_args(p)
    p.add_argument("--variant", action="append", required=True, help="variant name or .toml path (repeatable)")
    p.add_argument("--backtest", action="store_true", help="also backtest each variant")
    p.set_defaults(handler=cmd_compare)

    p = sub.add_parser("backtest", help="score the model against data/backtest.csv")
    p.add_argument("model")
    p.add_argument("--variant", action="append", default=[], help="variant to score alongside base (repeatable)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override applied to all runs")
    p.add_argument("--data", type=Path, help="CSV to use instead of the model's data/backtest.csv")
    p.set_defaults(handler=cmd_backtest)

    p = sub.add_parser("fetch", help="download and rebuild a model's data (models with a fetch.py)")
    p.add_argument("model")
    p.add_argument("--offline", action="store_true", help="rebuild from cached raw downloads only")
    p.set_defaults(handler=cmd_fetch)

    p = sub.add_parser("serve", help="start the browser UI for editing and running models")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(handler=cmd_serve)

    p = sub.add_parser("new", help="scaffold a new model from the template")
    p.add_argument("name", help="snake_case model name")
    p.add_argument("--title")
    p.set_defaults(handler=cmd_new)

    p = sub.add_parser("build-site", help="generate a self-contained static site bundle")
    p.add_argument("--out", type=Path, default=Path("dist"), help="output directory (default: dist)")
    p.add_argument("--models", help="comma-separated list of models to include (default: all)")
    p.set_defaults(handler=cmd_build_site)

    p = sub.add_parser("export-replay", help="render a cfb_replay game to a vertical MP4 (needs .[video] + ffmpeg)")
    p.add_argument("--game", help="ESPN game id (or give --in home=... --in away=... --in date=...)")
    p.add_argument("--example", help="a cfb_replay example (examples/<name>.toml)")
    p.add_argument("--in", dest="inputs", action="append", default=[], metavar="KEY=VALUE", help="model input")
    p.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="override a parameter")
    p.add_argument("--out", type=Path, help="output file (default: replay_<game>.mp4)")
    p.add_argument("--fps", type=int, help="frames per second (default from the model, 30)")
    p.set_defaults(handler=cmd_export_replay)

    p = sub.add_parser("views", help="build one model's public page (site.py) and summarise it")
    p.add_argument("model")
    p.add_argument("--out", type=Path, help="also write the page JSON here")
    p.set_defaults(handler=cmd_views)

    p = sub.add_parser("update-and-build",
                       help="fetch the models that are due (config.toml [fetch]) and rebuild the whole static site")
    p.add_argument("--out", type=Path, default=Path("dist"), help="output directory (default: dist)")
    p.add_argument("--models", help="comma-separated models to fetch instead of the scheduled ones "
                                    "(the site is always built with every model)")
    p.add_argument("--offline", action="store_true", help="rebuild from local cached raw data only")
    p.set_defaults(handler=cmd_update_and_build)
    return parser


def _add_input_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--example", help="name of a file in the model's examples/ (default: 'default')")
    p.add_argument("--input", type=Path, help="TOML file of inputs")
    p.add_argument("--in", dest="inputs", action="append", default=[], metavar="KEY=VALUE",
                   help="set/override one input (TOML value syntax)")


def _add_tweak_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--variant", help="variant name (models/<name>/variants/<variant>.toml) or a .toml path")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="override a parameter (fit_weight=0.8) or formula (formulas.predict=...)")


def _inputs(args: argparse.Namespace) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    example = args.example or (None if args.input else "default")
    if example:
        inputs.update(registry.load_example(args.model, example))
    if args.input:
        inputs.update(read_toml(args.input))
    inputs.update(parse_assignments(args.inputs))
    return inputs


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> int:
    rows = []
    for name in registry.model_names():
        cfg = registry.config_for(name)
        rows.append((name, cfg.status, cfg.title, registry.example_names(name), registry.variant_names(name)))
    width = max(len(r[0]) for r in rows)
    print(f" {'model'.ljust(width)}   {'status':<10} title")
    print(" " + "─" * (width + 50))
    for name, status, title, examples, variants in rows:
        print(f" {name.ljust(width)}   {status:<10} {title}")
        extras = []
        if examples:
            extras.append(f"examples: {', '.join(examples)}")
        if variants:
            extras.append(f"variants: {', '.join(variants)}")
        if extras:
            print(f" {' ' * width}   {' ' * 10} {' · '.join(extras)}")
    return 0


def cmd_params(args: argparse.Namespace) -> int:
    cfg = registry.config_for(args.model, args.variant, parse_assignments(args.set))
    print(render.HEAVY)
    print(f" {cfg.title.upper()} — PARAMETERS   ({args.model} v{cfg.version} · {cfg.status})")
    print(render.HEAVY)
    for spec in cfg.params.specs.values():
        mark = "*" if spec.overridden else " "
        print(f"\n {mark} {spec.name} = {render.format_param(spec)}"
              + (f"   (default {spec.default})" if spec.overridden else ""))
        for line in render.wrap(spec.description, indent="     "):
            print(line)
        details = []
        if spec.range:
            details.append(f"range {spec.range[0]} – {spec.range[1]}")
        if spec.choices:
            details.append(f"choices {spec.choices}")
        if details:
            print(f"     [{'; '.join(details)}]")
        for line in render.wrap(f"source: {spec.source}" if spec.source else "", indent="     "):
            print(line)
    for f in cfg.params.formulas.values():
        mark = "*" if f.overridden else " "
        print(f"\n {mark} ƒ {f.name} = {f.expr}")
        for line in render.wrap(f.description, indent="     "):
            print(line)
        if f.variables:
            print(f"     variables supplied by the model: {', '.join(f.variables)}  (+ any numeric param)")
    print("\n" + render.HEAVY)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    model = registry.load_model(args.model, args.variant, parse_assignments(args.set))
    print(render.render(model.predict(_inputs(args)), args.format))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    inputs = _inputs(args)
    models = [registry.load_model(args.model)] + [registry.load_model(args.model, v) for v in args.variant]
    print(render.render_comparison([m.predict(inputs) for m in models]))
    if args.backtest:
        _print_backtest(models, None)
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    overrides = parse_assignments(args.set)
    models = [registry.load_model(args.model, None, overrides)]
    models += [registry.load_model(args.model, v, overrides) for v in args.variant]
    _print_backtest(models, args.data)
    return 0


def _print_backtest(models: list, data: Path | None) -> None:
    path = data or bt.default_data_path(models[0])
    if not path.exists():
        raise ValueError(f"no backtest data at {path}. See the model's MODEL.md for the expected CSV columns.")
    rows = bt.load_rows(path)
    print(render.render_backtest([bt.run_backtest(m, rows) for m in models]))


def cmd_fetch(args: argparse.Namespace) -> int:
    directory = registry.model_dir(args.model)
    if not (directory / "fetch.py").exists():
        raise ValueError(f"model '{args.model}' has no fetch.py")
    module = importlib.import_module(f"ballmonitor.models.{args.model}.fetch")
    for line in module.fetch(directory, offline=args.offline):
        print(line)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from ballmonitor.web.server import serve

    serve(args.host, args.port)
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    path = registry.scaffold(args.name, args.title)
    print(f"created {path}")
    print("next: edit config.toml (params, formulas, assumptions), MODEL.md, model.py, examples/default.toml;")
    print(f"      then `ballmonitor run {args.name}` and `pytest {path}`")
    return 0


def cmd_export_replay(args: argparse.Namespace) -> int:
    from ballmonitor.web.export_replay import export

    lines = []
    if args.example:
        lines.append((registry.model_dir("cfb_replay") / "examples" / f"{args.example}.toml").read_text())
    lines += [_toml_line(a) for a in args.inputs]
    inputs_toml = "\n".join(lines)
    out = args.out or Path(f"replay_{args.game or args.example or 'game'}.mp4")
    try:
        export(args.game, out, parse_assignments(args.set), inputs_toml or None, fps=args.fps)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _toml_line(assignment: str) -> str:
    key, _, value = assignment.partition("=")
    value = value.strip()
    try:
        float(value)
        return f"{key.strip()} = {value}"
    except ValueError:
        return f"{key.strip()} = {json.dumps(value)}"


def cmd_build_site(args: argparse.Namespace) -> int:
    from ballmonitor.web.builder import build_static_site

    models = [m.strip() for m in args.models.split(",")] if args.models else None
    out = build_static_site(args.out, models=models)
    print(f"Static site successfully built at: {out}")
    return 0


def cmd_views(args: argparse.Namespace) -> int:
    import time

    from ballmonitor.web.builder import site_page

    started = time.perf_counter()
    p = site_page(args.model)
    if p is None:
        raise ValueError(f"model '{args.model}' has no site.py")
    print(f"{p['title']}  [{p['sport']}]  built in {time.perf_counter() - started:.1f}s")
    print(f"  {p['summary']}")
    if p.get("updated"):
        print(f"  updated: {p['updated']}")

    def show(vs, indent="  "):
        for v in vs:
            size = {"table": lambda: f"{len(v['rows'])} rows x {len(v['columns'])} cols",
                    "bar": lambda: f"{len(v['items'])} bars",
                    "line": lambda: f"{len(v['series'])} lines, {sum(len(s['points']) for s in v['series'])} points",
                    "picker": lambda: f"{len(v['options'])} options"}[v["kind"]]()
            print(f"{indent}- {v['kind']:<6} {v['title']}  ({size})")
            if v["kind"] == "picker":
                show(v["options"][0]["views"], indent + "    ")
    show(p["views"])
    if args.out:
        args.out.write_text(json.dumps(p, indent=1), encoding="utf-8")
        print(f"wrote {args.out} ({args.out.stat().st_size // 1024} KB)")
    return 0


def cmd_update_and_build(args: argparse.Namespace) -> int:
    from ballmonitor.web.builder import build_static_site

    if args.models:
        # Named models are fetched whatever their [fetch] policy says.
        to_fetch = [m.strip() for m in args.models.split(",") if m.strip()]
        for name in to_fetch:
            if not (registry.model_dir(name) / "fetch.py").exists():
                raise ValueError(f"model '{name}' has no fetch.py")
    else:
        to_fetch = []
        print("Fetch policy (config.toml [fetch]):")
        for name in registry.model_names():
            due, reason = registry.fetch_due(name)
            if reason != "no fetch.py":
                print(f"  {name:<18} {'fetch' if due else 'skip '}  {reason}")
            if due:
                to_fetch.append(name)

    for name in to_fetch:
        print(f"-> Updating data for {name}...", flush=True)
        try:
            module = importlib.import_module(f"ballmonitor.models.{name}.fetch")
            for line in module.fetch(registry.model_dir(name), offline=args.offline):
                print(f"   {line}", flush=True)
        except Exception as exc:
            print(f"   warning: {name} fetch failed ({exc}); building with its existing data")

    # Always the whole site: GitHub Pages replaces everything on each deploy.
    print("Building static site bundle...", flush=True)
    out = build_static_site(args.out)
    print(f"Update & build complete: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
