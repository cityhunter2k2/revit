"""Revit-style formula subset: tokenizer + recursive-descent evaluator.

Why this module exists
----------------------
Every dimension that drives the trunking fittings is expressed as a Revit
family-parameter formula (``if(and(Width <= 50 mm, Height <= 50 mm), 1 mm, ...)``).
Being able to evaluate exactly those strings outside Revit is what makes the
whole design testable without a Revit installation:

* ``params.py`` uses it to resolve instance parameter values,
* ``model.py`` uses it to build the idempotent linear forms that prove each
  sketch dimension equals a real family parameter,
* ``fake_revit.py`` uses it to emulate ``FamilyManager`` formula evaluation.

Supported syntax (deliberately a subset of Revit's formula language):

    numbers with optional unit suffix  -> 12, 1.2, 75 mm, 1.4cm, 2 m, 90 deg, 45°
    identifiers                        -> Width, Half_Width, Cover_Type
    operators                          -> + - * / ^  <  >  <=  >=  =  <>  ( )
    functions                          -> if(cond,a,b) and(a,b,...) or(a,b,...)
                                          not(x) sqrt(x) abs(x) round(x,n)
                                          sin cos tan (degrees), pi()

Revit evaluates lengths in feet internally; this module evaluates lengths in
millimetres and angles in degrees.  Only *relative* consistency matters for the
tests, and mm/deg is far easier to reason about.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Sequence, Tuple, Union

Number = Union[float, int]
Value = Union[float, bool, str]

#: unit suffix -> multiplier that converts the token to millimetres
_LENGTH_UNITS = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "millimeters": 1.0,
    "centimeters": 10.0,
    "meters": 1000.0,
}
_ANGLE_UNITS = {"deg": 1.0, "°": 1.0, "degrees": 1.0, "rad": 180.0 / math.pi}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|<>|[-+*/^(),<>=°])
    """,
    re.VERBOSE,
)


class FormulaError(ValueError):
    """Raised when a formula cannot be tokenized, parsed or evaluated."""


def tokenize(text: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise FormulaError(f"unexpected character {text[pos]!r} at {pos} in {text!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        value = m.group()
        if kind == "number":
            # absorb a following unit suffix, if any
            rest = text[pos:]
            unit_match = re.match(
                r"\s*(millimeters|centimeters|meters|degrees|mm|cm|m|deg|°|rad)(?![A-Za-z0-9_])",
                rest,
            )
            if unit_match and unit_match.group(1):
                unit = unit_match.group(1)
                # 'm' must not swallow the 'm' of a keyword such as 'mm' (handled
                # by ordering) nor the start of an identifier like 'merged'
                if unit in _LENGTH_UNITS:
                    value = str(float(value) * _LENGTH_UNITS[unit])
                elif unit in _ANGLE_UNITS:
                    value = str(float(value) * _ANGLE_UNITS[unit])
                pos += unit_match.end()
        tokens.append((kind, value))
    tokens.append(("eof", ""))
    return tokens


# --------------------------------------------------------------------------- #
# AST
# --------------------------------------------------------------------------- #
class Node:
    def eval(self, env: Dict[str, Value]) -> Value:  # pragma: no cover - interface
        raise NotImplementedError

    def deps(self) -> Iterable[str]:  # pragma: no cover - interface
        return ()


class Const(Node):
    __slots__ = ("value",)

    def __init__(self, value: Value) -> None:
        self.value = value

    def eval(self, env: Dict[str, Value]) -> Value:
        return self.value

    def __repr__(self) -> str:  # pragma: no cover
        return f"Const({self.value!r})"


class Var(Node):
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def eval(self, env: Dict[str, Value]) -> Value:
        try:
            return env[self.name]
        except KeyError as exc:
            raise FormulaError(f"unknown parameter {self.name!r}") from exc

    def deps(self) -> Iterable[str]:
        yield self.name

    def __repr__(self) -> str:  # pragma: no cover
        return f"Var({self.name})"


class Unary(Node):
    __slots__ = ("op", "operand")

    def __init__(self, op: str, operand: Node) -> None:
        self.op = op
        self.operand = operand

    def eval(self, env: Dict[str, Value]) -> Value:
        val = _num(self.operand.eval(env))
        if self.op == "-":
            return -val
        if self.op == "+":
            return val
        if self.op.lower() == "not":
            return not _truth(self.operand.eval(env))
        raise FormulaError(f"bad unary operator {self.op!r}")

    def deps(self) -> Iterable[str]:
        return self.operand.deps()


class Binary(Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op: str, left: Node, right: Node) -> None:
        self.op = op
        self.left = left
        self.right = right

    def eval(self, env: Dict[str, Value]) -> Value:
        op = self.op
        if op in ("and", "or"):
            left = _truth(self.left.eval(env))
            if op == "and":
                return left and _truth(self.right.eval(env))
            return left or _truth(self.right.eval(env))
        a = self.left.eval(env)
        b = self.right.eval(env)
        if op in ("<", ">", "<=", ">=", "=", "<>"):
            a, b = _comparable(a, b)
            return {
                "<": a < b,
                ">": a > b,
                "<=": a <= b,
                ">=": a >= b,
                "=": a == b,
                "<>": a != b,
            }[op]
        a, b = _num(a), _num(b)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise FormulaError("division by zero")
            return a / b
        if op == "^":
            return a ** b
        raise FormulaError(f"bad operator {op!r}")

    def deps(self) -> Iterable[str]:
        yield from self.left.deps()
        yield from self.right.deps()


class Call(Node):
    __slots__ = ("name", "args")

    def __init__(self, name: str, args: Sequence[Node]) -> None:
        self.name = name.lower()
        self.args = list(args)

    def eval(self, env: Dict[str, Value]) -> Value:
        name = self.name
        if name == "if":
            if len(self.args) != 3:
                raise FormulaError("if() takes exactly 3 arguments")
            cond = _truth(self.args[0].eval(env))
            return self.args[1].eval(env) if cond else self.args[2].eval(env)
        if name == "and":
            return all(_truth(a.eval(env)) for a in self.args)
        if name == "or":
            return any(_truth(a.eval(env)) for a in self.args)
        if name == "not":
            return not _truth(self.args[0].eval(env))
        if name == "pi":
            return math.pi
        vals = [_num(a.eval(env)) for a in self.args]
        if name == "sqrt":
            return math.sqrt(vals[0])
        if name == "abs":
            return abs(vals[0])
        if name == "round":
            digits = int(vals[1]) if len(vals) > 1 else 0
            return float(round(vals[0], digits))
        if name == "sin":
            return math.sin(math.radians(vals[0]))
        if name == "cos":
            return math.cos(math.radians(vals[0]))
        if name == "tan":
            return math.tan(math.radians(vals[0]))
        if name == "asin":
            return math.degrees(math.asin(vals[0]))
        if name == "acos":
            return math.degrees(math.acos(vals[0]))
        if name == "max" and vals:
            return max(vals)
        if name == "min" and vals:
            return min(vals)
        raise FormulaError(f"unsupported function {name}()")

    def deps(self) -> Iterable[str]:
        for arg in self.args:
            yield from arg.deps()


def _num(value: Value) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        raise FormulaError(f"text value {value!r} used in a numeric expression")
    return float(value)


def _truth(value: Value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raise FormulaError(f"text value {value!r} used as a condition")
    return value != 0


def _comparable(a: Value, b: Value) -> Tuple[Value, Value]:
    if isinstance(a, bool) or isinstance(b, bool):
        return _truth(a), _truth(b)
    return _num(a), _num(b)


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
class _Parser:
    def __init__(self, tokens: List[Tuple[str, str]]) -> None:
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Tuple[str, str]:
        return self.tokens[self.i]

    def next(self) -> Tuple[str, str]:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def accept(self, *, op: str | None = None, name: str | None = None) -> bool:
        kind, value = self.peek()
        if op is not None and kind == "op" and value == op:
            self.i += 1
            return True
        if name is not None and kind == "name" and value.lower() == name:
            self.i += 1
            return True
        return False

    def expect(self, op: str) -> None:
        if not self.accept(op=op):
            raise FormulaError(f"expected {op!r} but found {self.peek()[1]!r}")

    # expression := comparison
    def parse(self) -> Node:
        node = self.comparison()
        if self.peek()[0] != "eof":
            raise FormulaError(f"unexpected trailing token {self.peek()[1]!r}")
        return node

    def comparison(self) -> Node:
        node = self.additive()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("<", ">", "<=", ">=", "=", "<>"):
                self.i += 1
                node = Binary(value, node, self.additive())
            else:
                return node

    def additive(self) -> Node:
        node = self.multiplicative()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("+", "-"):
                self.i += 1
                node = Binary(value, node, self.multiplicative())
            else:
                return node

    def multiplicative(self) -> Node:
        node = self.unary()
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("*", "/"):
                self.i += 1
                node = Binary(value, node, self.unary())
            else:
                return node

    def unary(self) -> Node:
        kind, value = self.peek()
        if kind == "op" and value in ("-", "+"):
            self.i += 1
            return Unary(value, self.unary())
        if kind == "name" and value.lower() == "not":
            self.i += 1
            return Unary("not", self.unary())
        return self.power()

    def power(self) -> Node:
        node = self.primary()
        while self.accept(op="^"):
            node = Binary("^", node, self.unary())
        return node

    def primary(self) -> Node:
        kind, value = self.next()
        if kind == "number":
            return Const(float(value))
        if kind == "op" and value == "(":
            node = self.comparison()
            self.expect(")")
            return node
        if kind == "name":
            lowered = value.lower()
            if lowered in ("and", "or"):
                self.expect("(")
                args = [self.comparison()]
                while self.accept(op=","):
                    args.append(self.comparison())
                self.expect(")")
                node: Node = args[0]
                for extra in args[1:]:
                    node = Binary(lowered, node, extra)
                return node
            if self.peek()[0] == "op" and self.peek()[1] == "(":
                self.i += 1
                args = []
                if not (self.peek()[0] == "op" and self.peek()[1] == ")"):
                    args.append(self.comparison())
                    while self.accept(op=","):
                        args.append(self.comparison())
                self.expect(")")
                return Call(lowered, args)
            return Var(value)
        raise FormulaError(f"unexpected token {value!r}")


_PARSE_CACHE: Dict[str, Node] = {}


def parse(text: str) -> Node:
    """Parse ``text`` into an AST (cached, formulas are re-evaluated a lot)."""
    key = text.strip()
    node = _PARSE_CACHE.get(key)
    if node is None:
        node = _Parser(tokenize(key)).parse()
        _PARSE_CACHE[key] = node
    return node


def evaluate(text: str, env: Dict[str, Value]) -> Value:
    """Evaluate a Revit formula string against ``env``."""
    return parse(text).eval(env)


def dependencies(text: str) -> List[str]:
    """All identifiers referenced by ``text`` (order preserved, deduplicated)."""
    seen: List[str] = []
    for dep in parse(text).deps():
        if dep not in seen:
            seen.append(dep)
    return seen


def checks_out(text: str) -> bool:
    """True when the formula parses (used by the parameter-table validator)."""
    try:
        parse(text)
    except FormulaError:
        return False
    return True
