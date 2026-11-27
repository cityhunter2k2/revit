"""Affine forms over family parameters (exact symbolic arithmetic).

Every sketch coordinate in these families is an affine combination of family
parameters, e.g.

    Half_Width - WallThickness
    -(Half_Width + Cover_Overhang)
    CenterToEnd - Flange_Length + Flange_Wrap

Representing coordinates as ``Lin`` objects instead of floats buys two things:

1. **Dimension labels are provable.**  The distance between two profile lines
   is itself a ``Lin``; if that ``Lin`` equals a family parameter's ``Lin``,
   then labelling the sketch dimension with that parameter reproduces the same
   geometry for *every* size - this is exactly what ``dimplan.py`` relies on.
2. **Offsets stay exact.**  Miter intersections of 0/90/45 degree segments are
   affine, so offsetting a chain symbolically never accumulates float drift.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from . import expr

TOL = 1e-9


class Lin:
    """``k + sum(coeff[name] * value[name])``."""

    __slots__ = ("k", "coeff")

    def __init__(self, k: float = 0.0, coeff: Mapping[str, float] | None = None) -> None:
        self.k = float(k)
        self.coeff: Dict[str, float] = {name: float(v) for name, v in (coeff or {}).items() if abs(v) > TOL}

    # -- construction ------------------------------------------------------ #
    @staticmethod
    def of(name: str) -> "Lin":
        return Lin(0.0, {name: 1.0})

    @staticmethod
    def const(value: float) -> "Lin":
        return Lin(value)

    def _coerce(self, other: object) -> "Lin":
        if isinstance(other, Lin):
            return other
        if isinstance(other, (int, float)):
            return Lin(float(other))
        raise TypeError(f"cannot combine Lin with {type(other).__name__}")

    # -- arithmetic -------------------------------------------------------- #
    def __add__(self, other: object) -> "Lin":
        other = self._coerce(other)
        coeff = dict(self.coeff)
        for name, value in other.coeff.items():
            coeff[name] = coeff.get(name, 0.0) + value
        return Lin(self.k + other.k, coeff)

    __radd__ = __add__

    def __sub__(self, other: object) -> "Lin":
        return self + (-self._coerce(other))

    def __rsub__(self, other: object) -> "Lin":
        return self._coerce(other) + (-self)

    def __neg__(self) -> "Lin":
        return Lin(-self.k, {name: -v for name, v in self.coeff.items()})

    def __mul__(self, other: object) -> "Lin":
        if isinstance(other, Lin):
            if self.is_constant() and other.is_constant():
                return Lin(self.k * other.k)
            raise TypeError("Lin * Lin is not affine (use a constant factor)")
        factor = float(other)  # type: ignore[arg-type]
        return Lin(self.k * factor, {name: v * factor for name, v in self.coeff.items()})

    __rmul__ = __mul__

    def __truediv__(self, other: float) -> "Lin":
        if isinstance(other, Lin):
            if not other.is_constant():
                raise TypeError("Lin / Lin is only supported for constants")
            other = other.k
        if abs(float(other)) < TOL:
            raise ZeroDivisionError("division of a Lin by zero")
        return self * (1.0 / float(other))

    # -- queries ----------------------------------------------------------- #
    def is_constant(self) -> bool:
        return not self.coeff

    def evaluate(self, values: Mapping[str, float]) -> float:
        total = self.k
        for name, coeff in self.coeff.items():
            total += coeff * float(values[name])
        return total

    def key(self) -> Tuple:
        return (round(self.k, 6), tuple(sorted((n, round(v, 6)) for n, v in self.coeff.items())))

    def names(self) -> Iterable[str]:
        return self.coeff.keys()

    def almost_equals(self, other: "Lin", tol: float = 1e-7) -> bool:
        if abs(self.k - other.k) > tol:
            return False
        for name in set(self.coeff) | set(other.coeff):
            if abs(self.coeff.get(name, 0.0) - other.coeff.get(name, 0.0)) > tol:
                return False
        return True

    def __eq__(self, other: object) -> bool:  # type: ignore[override]
        return isinstance(other, Lin) and self.key() == other.key()

    def __hash__(self) -> int:
        return hash(self.key())

    def __repr__(self) -> str:
        parts = [f"{self.k:g}"]
        for name in sorted(self.coeff):
            coeff = self.coeff[name]
            sign = "+" if coeff >= 0 else "-"
            parts.append(f" {sign} {abs(coeff):g}*{name}")
        return "".join(parts)


# Point helpers ------------------------------------------------------------- #
Point2L = Tuple[Lin, Lin]
Point3L = Tuple[Lin, Lin, Lin]


def point2(k: str | Lin | float, coeff: str | None = None) -> Tuple[Lin, Lin]:  # pragma: no cover
    raise NotImplementedError


def p2(u: Lin | float, v: Lin | float) -> Point2L:
    return (u if isinstance(u, Lin) else Lin(float(u)), v if isinstance(v, Lin) else Lin(float(v)))


def p2_add(point: Point2L, delta: Sequence[float]) -> Point2L:
    return (point[0] + delta[0], point[1] + delta[1])


def p2_sub(a: Point2L, b: Point2L) -> Tuple[Lin, Lin]:
    return (a[0] - b[0], a[1] - b[1])


def p2_eval(point: Point2L, values: Mapping[str, float]) -> Tuple[float, float]:
    return (point[0].evaluate(values), point[1].evaluate(values))


def lin_from_expr(text: str, param_names: Sequence[str]) -> Lin:
    """Build the affine form of a formula string.

    The expression is evaluated at the origin and at each unit basis vector of
    the parameter space; a random probe then verifies the expression really is
    affine (all geometry expressions in this project are).
    """
    names = [n for n in param_names]
    deps = [n for n in expr.dependencies(text) if n in names]
    base = {n: 0.0 for n in names}
    k = float(expr.evaluate(text, base))
    coeff: Dict[str, float] = {}
    for name in deps:
        probe = dict(base)
        probe[name] = 1.0
        coeff[name] = float(expr.evaluate(text, probe)) - k
    form = Lin(k, coeff)
    rng = [1.7, 0.9, 2.3, 1.1, 3.1, 0.4, 1.9, 2.6]
    probe = {n: rng[i % len(rng)] for i, n in enumerate(names)}
    if abs(form.evaluate(probe) - float(expr.evaluate(text, probe))) > 1e-6:
        raise ValueError(f"expression {text!r} is not affine in the family parameters")
    return form


# --------------------------------------------------------------------------- #
# symbolic polyline offsetting (0/90/45 degree segments only)
# --------------------------------------------------------------------------- #
def _direction(a: Point2L, b: Point2L, values: Mapping[str, float]) -> Tuple[float, float]:
    ax, ay = p2_eval(a, values)
    bx, by = p2_eval(b, values)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ValueError("degenerate chain segment")
    return (dx / length, dy / length)


def offset_chain(
    chain: Sequence[Point2L], distance: float, values: Mapping[str, float]
) -> list[Point2L]:
    """Symbolic equivalent of :func:`geometry.offset_chain` (left offset).

    Every segment contributes its own offset line; the vertices are where two
    consecutive offset lines meet. Zipping ``chain`` with the segment directions
    instead drops the last vertex and miter-joins the wrong pair, which is how
    the wall strips ended up as bow-ties.
    """
    if len(chain) < 2:
        raise ValueError("a chain needs at least two points")
    dirs = [_direction(a, b, values) for a, b in zip(chain[:-1], chain[1:])]

    def offset_point(point: Point2L, direction: Tuple[float, float]) -> Point2L:
        return (point[0] - direction[1] * distance, point[1] + direction[0] * distance)

    lines = [(offset_point(chain[i], dirs[i]), dirs[i]) for i in range(len(dirs))]
    out: list[Point2L] = [lines[0][0]]
    for index in range(1, len(lines)):
        (p1, d1), (p2, d2) = lines[index - 1], lines[index]
        det = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(det) < 1e-9:  # parallel: the offset line continues straight
            out.append(p2)
            continue
        delta = p2_sub(p2, p1)
        t = (delta[0] * d2[1] - delta[1] * d2[0]) / det
        out.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    # the end vertex is the last offset start plus the whole last segment
    last_offset = lines[-1][0]
    start, end = chain[-2], chain[-1]
    out.append((last_offset[0] + (end[0] - start[0]), last_offset[1] + (end[1] - start[1])))
    return out


def chain_strip(
    chain: Sequence[Point2L], distance: float, values: Mapping[str, float]
) -> list[Point2L]:
    inner = offset_chain(chain, distance, values)
    return list(chain) + list(reversed(inner))


def chain_direction(a: Point2L, b: Point2L, values: Mapping[str, float]) -> Tuple[float, float]:
    return _direction(a, b, values)
