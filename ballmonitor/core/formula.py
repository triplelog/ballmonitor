"""Safe evaluation of the small math formulas stored in config files.

Formulas are plain arithmetic expressions such as ``t * (D / d) ** k``. Only
numbers, named variables, arithmetic / comparison / boolean operators,
``a if cond else b`` and the whitelisted FUNCTIONS below are allowed. There is
no attribute access, indexing, import or arbitrary call, so editing a config
file can change the math but can never run arbitrary code.
"""

from __future__ import annotations

import ast
import math
import operator
from statistics import NormalDist


class FormulaError(ValueError):
    pass


FUNCTIONS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "exp": math.exp,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "logistic": lambda x: 1.0 / (1.0 + math.exp(-x)),
    "normal_cdf": lambda x, mu=0.0, sd=1.0: NormalDist(mu, sd).cdf(x),
    "clamp": lambda x, lo, hi: min(max(x, lo), hi),
}

CONSTANTS = {"pi": math.pi, "e": math.e}

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_COMPARE = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}
_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp,
    ast.Compare, ast.BoolOp, ast.And, ast.Or, ast.IfExp, ast.Call,
    *_BINARY, *_UNARY, *_COMPARE,
)


def _parse(expr: str) -> ast.Expression:
    try:
        return ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"cannot parse formula {expr!r}: {exc.msg}") from None


def check(expr: str, allowed_names: set[str]) -> None:
    """Raise FormulaError if `expr` uses unsupported syntax or unknown names."""
    tree = _parse(expr)
    function_nodes = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(f"formula {expr!r}: '{type(node).__name__}' is not allowed")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise FormulaError(
                    f"formula {expr!r}: only these functions are allowed: {', '.join(sorted(FUNCTIONS))}"
                )
            if node.keywords:
                raise FormulaError(f"formula {expr!r}: keyword arguments are not allowed")
            function_nodes.add(id(node.func))
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise FormulaError(f"formula {expr!r}: only numeric constants are allowed")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in function_nodes:
            if node.id not in allowed_names and node.id not in CONSTANTS:
                raise FormulaError(
                    f"formula {expr!r}: unknown name '{node.id}'. "
                    f"Available: {', '.join(sorted(allowed_names | CONSTANTS.keys()))}"
                )


def evaluate(expr: str, variables: dict[str, float]) -> float:
    tree = _parse(expr)
    return _eval(tree.body, {**CONSTANTS, **variables}, expr)


def _eval(node: ast.AST, env: dict, expr: str):
    match node:
        case ast.Constant(value=value) if isinstance(value, (int, float)):
            return value
        case ast.Name(id=name):
            if name not in env:
                raise FormulaError(f"formula {expr!r}: unknown variable '{name}'")
            return env[name]
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY:
            return _BINARY[type(op)](_eval(left, env, expr), _eval(right, env, expr))
        case ast.UnaryOp(op=op, operand=operand) if type(op) in _UNARY:
            return _UNARY[type(op)](_eval(operand, env, expr))
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            current = _eval(left, env, expr)
            for op, right_node in zip(ops, comparators):
                if type(op) not in _COMPARE:
                    break
                right = _eval(right_node, env, expr)
                if not _COMPARE[type(op)](current, right):
                    return False
                current = right
            else:
                return True
        case ast.BoolOp(op=ast.And(), values=values):
            return all(_eval(v, env, expr) for v in values)
        case ast.BoolOp(op=ast.Or(), values=values):
            return any(_eval(v, env, expr) for v in values)
        case ast.IfExp(test=test, body=body, orelse=orelse):
            return _eval(body, env, expr) if _eval(test, env, expr) else _eval(orelse, env, expr)
        case ast.Call(func=ast.Name(id=fname), args=args, keywords=[]) if fname in FUNCTIONS:
            return FUNCTIONS[fname](*(_eval(a, env, expr) for a in args))
    raise FormulaError(f"formula {expr!r}: unsupported syntax near '{ast.unparse(node)}'")
