"""Local browser UI for editing models and seeing their output.

    ballmonitor serve [--port 8765]

Stdlib only. Binds to 127.0.0.1. The browser edits are applied as the same
variant + override layers the CLI uses, so every run is exactly reproducible
from the command line. Saving writes only to variants/ and examples/; changing a
model's defaults stays a deliberate edit of config.toml (see CLAUDE.md).
"""

from __future__ import annotations

import json
import re
import tomllib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ballmonitor.core import backtest as bt
from ballmonitor.core import registry, render
from ballmonitor.core.config import read_toml
from ballmonitor.core.formula import FUNCTIONS, FormulaError
from ballmonitor.core.params import ConfigError

STATIC = Path(__file__).resolve().parent / "static"
# 27K pitching game: its own static build (run `npm run build` in ballmonitor/new27K to refresh)
GAME_27K = Path(__file__).resolve().parent.parent / "new27K" / "dist"
GAME_TRIPLE = Path(__file__).resolve().parent.parent / "games" / "triple_play" / "web"
CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json"}
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_\-]*")
USER_ERRORS = (ConfigError, FormulaError, KeyError, ValueError, TypeError,
               registry.ModelNotReady, NotImplementedError, tomllib.TOMLDecodeError)


# ── API logic (plain functions, easy to test) ────────────────────────────────

def list_models() -> list[dict[str, Any]]:
    out = []
    for name in registry.model_names():
        cfg = registry.config_for(name)
        directory = registry.model_dir(name)
        examples = web_examples(name)
        variants = registry.variant_names(name)
        out.append({
            "name": name,
            "title": cfg.title,
            "status": cfg.status,
            "version": cfg.version,
            "question": cfg.question,
            "description": (cfg.description or "").strip(),
            "examples": examples,
            "examples_count": len(examples),
            "variants_count": len(variants),
            "has_backtest_data": (directory / bt.BACKTEST_FILE).exists(),
        })
    return out


def web_examples(name: str) -> list[str]:
    """Examples shown on the website: all of them minus config.toml [web] hidden_examples."""
    hidden = set(registry.config_for(name).extra.get("web", {}).get("hidden_examples", []))
    return [e for e in registry.example_names(name) if e not in hidden]


def model_detail(name: str, variant: str | None = None) -> dict[str, Any]:
    cfg = registry.config_for(name, variant or None)
    directory = registry.model_dir(name)
    hidden_params = set(cfg.extra.get("web", {}).get("hidden_params", []))
    examples = {
        e: (directory / "examples" / f"{e}.toml").read_text() for e in web_examples(name)
    }
    return {
        "name": name,
        "title": cfg.title,
        "version": cfg.version,
        "status": cfg.status,
        "question": cfg.question,
        "description": cfg.description,
        "assumptions": cfg.assumptions,
        "variant": cfg.variant,
        "variant_description": cfg.variant_description,
        "variants": registry.variant_names(name),
        "examples": examples,
        "params": [
            {
                "name": s.name, "value": s.value, "default": s.default, "description": s.description,
                "unit": s.unit, "source": s.source, "range": s.range, "choices": s.choices,
            }
            for s in cfg.params.specs.values() if s.name not in hidden_params
        ],
        "formulas": [
            {"name": f.name, "expr": f.expr, "default": f.default, "description": f.description,
             "variables": f.variables}
            for f in cfg.params.formulas.values()
        ],
        "functions": sorted(FUNCTIONS),
        "doc": (directory / "MODEL.md").read_text() if (directory / "MODEL.md").exists() else "",
        "has_backtest_data": (directory / bt.BACKTEST_FILE).exists(),
    }


def run_model(name: str, body: dict[str, Any]) -> dict[str, Any]:
    model = registry.load_model(name, body.get("variant") or None, body.get("overrides") or {})
    inputs = tomllib.loads(body.get("inputs_toml", ""))
    pred = model.predict(inputs)
    return {
        "text": render.render_text(pred),
        "markdown": render.render_markdown(pred),
        "prediction": pred.to_dict(),
    }


def backtest_model(name: str, body: dict[str, Any]) -> dict[str, Any]:
    base = registry.load_model(name, None, None)
    tweaked = registry.load_model(name, body.get("variant") or None, body.get("overrides") or {})
    path = bt.default_data_path(base)
    if not path.exists():
        raise ValueError(f"no backtest data yet at {path.relative_to(registry.MODELS_DIR.parent.parent)}")
    rows = bt.load_rows(path)
    base_result = bt.run_backtest(base, rows)
    tweaked_result = bt.run_backtest(tweaked, rows)
    tweaked_result.variant = "current edits"
    return {"text": render.render_backtest([base_result, tweaked_result])}


def save_variant(name: str, body: dict[str, Any]) -> dict[str, Any]:
    variant = _safe_name(body.get("name", ""))
    cfg = registry.config_for(name, body.get("base_variant") or None, body.get("overrides") or {})
    params = {s.name: s.value for s in cfg.params.specs.values() if s.overridden}
    formulas = {f.name: f.expr for f in cfg.params.formulas.values() if f.overridden}
    if not params and not formulas:
        raise ValueError("nothing differs from config.toml — change a parameter or formula first")
    lines = [f"description = {_toml_value(body.get('description', ''))}", ""]
    if params:
        lines += ["[params]", *(f"{k} = {_toml_value(v)}" for k, v in params.items()), ""]
    if formulas:
        lines += ["[formulas]", *(f"{k} = {_toml_value(v)}" for k, v in formulas.items()), ""]
    path = registry.model_dir(name) / "variants" / f"{variant}.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines))
    return {"saved": str(path.relative_to(registry.MODELS_DIR.parent.parent)), "variant": variant}


def save_example(name: str, body: dict[str, Any]) -> dict[str, Any]:
    example = _safe_name(body.get("name", ""))
    text = body.get("inputs_toml", "")
    tomllib.loads(text)  # validate
    path = registry.model_dir(name) / "examples" / f"{example}.toml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n")
    return {"saved": str(path.relative_to(registry.MODELS_DIR.parent.parent)), "example": example}


def _safe_name(name: str) -> str:
    name = name.strip()
    if not NAME_RE.fullmatch(name):
        raise ValueError("names must be lowercase letters, digits, '_' or '-'")
    return name


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # JSON string escapes are valid TOML
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot write {value!r} to TOML")


_ENTITIES: dict[str, Any] | None = None


def entities() -> dict[str, Any]:
    """Autocomplete name lists (built once per server run; reading the data files is slow)."""
    global _ENTITIES
    if _ENTITIES is None:
        from ballmonitor.web.builder import extract_entities
        _ENTITIES = extract_entities()
    return _ENTITIES


# ── Next Pitch Game API ──────────────────────────────────────────────────────

SCENARIOS_PATH = registry.MODELS_DIR / "next_pitch" / "data" / "game_scenarios.json"
_SCENARIOS: list[dict[str, Any]] | None = None


def _get_scenarios() -> list[dict[str, Any]]:
    global _SCENARIOS
    if _SCENARIOS is None:
        if SCENARIOS_PATH.exists():
            _SCENARIOS = json.loads(SCENARIOS_PATH.read_text())
        else:
            _SCENARIOS = []
    return _SCENARIOS


def game_scenario(scenario_id: str | None = None) -> dict[str, Any]:
    import random
    scenarios = _get_scenarios()
    if not scenarios:
        raise ValueError("No game scenarios found at " + str(SCENARIOS_PATH))
    if scenario_id is not None and str(scenario_id).isdigit():
        idx = int(scenario_id) % len(scenarios)
    else:
        idx = random.randint(0, len(scenarios) - 1)
    sc = scenarios[idx]
    return {
        "id": sc["id"],
        "total_scenarios": len(scenarios),
        "pitcher": sc["pitcher"],
        "pitcher_hand": sc["pitcher_hand"],
        "batter": sc["batter"],
        "batter_stand": sc["batter_stand"],
        "batter_ops": sc["batter_ops"],
        "balls": sc["balls"],
        "strikes": sc["strikes"],
        "outs": sc["outs"],
        "bases": sc["bases"],
        "inning": sc["inning"],
        "score_diff": sc["score_diff"],
        "sequence": sc["sequence"],
        "arsenal": sc["arsenal"],
        "pitch_names": sc["pitch_names"],
        "ai_probs": sc["ai_probs"],
    }


def evaluate_game_guess(body: dict[str, Any]) -> dict[str, Any]:
    scenarios = _get_scenarios()
    if not scenarios:
        raise ValueError("No game scenarios found.")
    sc_id = int(body.get("id", 0)) % len(scenarios)
    sc = scenarios[sc_id]
    actual = sc["actual"]
    ai_probs = sc["ai_probs"]
    player_probs = body.get("player_probs", {})

    arsenal = sc["arsenal"]
    p_sum = sum(float(player_probs.get(c, 0.0)) for c in arsenal)
    if p_sum <= 0:
        norm_player = {c: 1.0 / len(arsenal) for c in arsenal}
    else:
        norm_player = {c: float(player_probs.get(c, 0.0)) / p_sum for c in arsenal}

    player_brier = sum((norm_player.get(c, 0.0) - (1.0 if c == actual else 0.0)) ** 2 for c in arsenal)
    ai_brier = sum((ai_probs.get(c, 0.0) - (1.0 if c == actual else 0.0)) ** 2 for c in arsenal)

    better = player_brier < ai_brier
    tie = abs(player_brier - ai_brier) < 1e-4

    return {
        "id": sc["id"],
        "actual": actual,
        "actual_name": sc["actual_name"],
        "ai_probs": ai_probs,
        "player_probs": {c: round(norm_player[c], 4) for c in arsenal},
        "player_brier": round(player_brier, 4),
        "ai_brier": round(ai_brier, 4),
        "delta_brier": round(ai_brier - player_brier, 4),
        "result": "win" if better and not tie else ("tie" if tie else "loss"),
    }


# ── HTTP plumbing ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "ballmonitor"

    def do_GET(self) -> None:
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if not parts or parts == ["index.html"]:
            return self._static("index.html")
        if parts in (["game"], ["play"], ["game.html"]):
            return self._static("game.html")
        if parts and parts[0] == "27k":
            if len(parts) == 1 and not url.path.endswith("/"):
                return self._redirect("/27k/")  # relative asset paths need the trailing slash
            return self._game_27k(parts[1:] or ["index.html"])
        if parts and parts[0] == "triple":
            if len(parts) == 1 and not url.path.endswith("/"):
                return self._redirect("/triple/")
            return self._game_dir(GAME_TRIPLE, parts[1:] or ["index.html"])
        if parts[0] == "static" and len(parts) == 2:
            return self._static(parts[1])
        if parts in (["api", "entities"], ["data", "entities.json"]):
            return self._call(entities)
        if parts == ["api", "models"]:
            return self._call(list_models)
        if len(parts) == 3 and parts[:2] == ["api", "models"]:
            return self._call(model_detail, parts[2], query.get("variant"))
        if parts == ["api", "game", "scenario"]:
            return self._call(game_scenario, query.get("id"))
        if len(parts) == 1 and parts[0] in registry.model_names():
            return self._static("index.html")
        if len(parts) == 2 and parts[0] in ("model", "models") and parts[1] in registry.model_names():
            return self._static("index.html")
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts == ["api", "game", "evaluate"]:
            length = int(self.headers.get("content-length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "request body must be JSON"}, HTTPStatus.BAD_REQUEST)
            return self._call(evaluate_game_guess, body)
        actions = {"run": run_model, "backtest": backtest_model,
                   "save-variant": save_variant, "save-example": save_example}
        if len(parts) == 4 and parts[:2] == ["api", "models"] and parts[3] in actions:
            length = int(self.headers.get("content-length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "request body must be JSON"}, HTTPStatus.BAD_REQUEST)
            return self._call(actions[parts[3]], parts[2], body)
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _call(self, fn, *args) -> None:
        try:
            self._json(fn(*args))
        except USER_ERRORS as exc:
            message = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            self._json({"error": str(message)}, HTTPStatus.BAD_REQUEST)

    def _static(self, filename: str) -> None:
        path = STATIC / filename
        if path.parent != STATIC or not path.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._send(path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

    def _game_27k(self, rel: list[str]) -> None:
        return self._game_dir(GAME_27K, rel)

    def _game_dir(self, base: Path, rel: list[str]) -> None:
        root = base.resolve()
        path = root.joinpath(*rel).resolve()
        if root not in path.parents and path != root or not path.is_file():
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        self._send(path.read_bytes(), CONTENT_TYPES.get(path.suffix, "text/plain"))

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.MOVED_PERMANENTLY)
        self.send_header("location", location)
        self.send_header("content-length", "0")
        self.end_headers()

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(json.dumps(data, default=str).encode(), "application/json", status)

    def _send(self, payload: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("content-type", f"{content_type}; charset=utf-8")
        self.send_header("content-length", str(len(payload)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        if self.command == "POST":  # keep the log to actions, not page/asset loads
            super().log_message(fmt, *args)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"ballmonitor UI on http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
