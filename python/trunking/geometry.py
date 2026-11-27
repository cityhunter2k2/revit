"""2D/3D geometry kernel for the trunking elbow fittings.

Conventions
-----------
Every solid in the six families is a **prism**: one planar profile loop (or a
loop plus holes) swept along a straight direction.  That keeps the Revit side
trivial - one ``Extrusion`` per solid, one sketch per solid - and it makes the
whole design verifiable with plane geometry.

The bend itself is described in a local 2D frame ``(u, v)``:

    arm A  runs along +u  and ends at u = -CenterToEnd
    arm B  runs along +v  and ends at v = +CenterToEnd
    the pivot (centerline intersection) is (0, 0)

so the in-plane silhouette is an L-shaped band of half-width ``a/2`` with

    convex  corner at (+a/2, -a/2)      (outside of the turn)
    concave corner at (-a/2, +a/2)      (inside of the turn)

For the *front opening* (horizontal bend) families the frame is (X, Y) and the
band half-width is W/2: the tray height H is the out-of-plane thickness.
For the *vertical* (upright) families the frame is (X, Z) and the band
half-width is H/2: the tray width W is the out-of-plane thickness.  Sign of the
in-plane axes is chosen so that both families share one silhouette routine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]

EPS = 1e-9


# --------------------------------------------------------------------------- #
# small vector helpers
# --------------------------------------------------------------------------- #
def v_add(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    return tuple(x + y for x, y in zip(a, b))


def v_sub(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b))


def v_mul(a: Sequence[float], k: float) -> Tuple[float, ...]:
    return tuple(x * k for x in a)


def v_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def v_cross(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def v_norm(a: Sequence[float]) -> float:
    return math.sqrt(v_dot(a, a))


def v_unit(a: Sequence[float]) -> Tuple[float, ...]:
    n = v_norm(a)
    if n < EPS:
        raise ValueError("cannot normalise a zero vector")
    return tuple(x / n for x in a)


def left_normal(direction: Point2) -> Point2:
    dx, dy = direction
    length = math.hypot(dx, dy)
    if length < EPS:
        raise ValueError("degenerate segment")
    return (-dy / length, dx / length)


# --------------------------------------------------------------------------- #
# polygons
# --------------------------------------------------------------------------- #
def polygon_area(points: Sequence[Point2]) -> float:
    """Signed area - positive for counter-clockwise loops."""
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def ensure_ccw(points: Sequence[Point2]) -> List[Point2]:
    pts = list(points)
    return pts if polygon_area(pts) >= 0 else list(reversed(pts))


def point_in_polygon(point: Point2, polygon: Sequence[Point2]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_at = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x_at > x:
                inside = not inside
    return inside


def _segments_cross(a: Point2, b: Point2, c: Point2, d: Point2) -> bool:
    def orient(p: Point2, q: Point2, r: Point2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if (o1 > EPS and o2 < -EPS) or (o1 < -EPS and o2 > EPS):
        if (o3 > EPS and o4 < -EPS) or (o3 < -EPS and o4 > EPS):
            return True
    return False


def polygon_self_intersects(points: Sequence[Point2]) -> bool:
    """True when two non-adjacent edges properly cross."""
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or (i + 1) % n == j:
                continue
            c, d = points[j], points[(j + 1) % n]
            if _segments_cross(a, b, c, d):
                return True
    return False


def offset_chain(chain: Sequence[Point2], distance: float) -> List[Point2]:
    """Offset an open polyline to its **left** by ``distance`` (miter joins).

    With a counter-clockwise polygon, "left" is the polygon interior, so a
    positive distance shrinks the loop and a negative one grows it.
    """
    if len(chain) < 2:
        raise ValueError("a chain needs at least two points")
    lines = []
    for p, q in zip(chain[:-1], chain[1:]):
        n = left_normal((q[0] - p[0], q[1] - p[1]))
        lines.append(((p[0] + n[0] * distance, p[1] + n[1] * distance), v_sub(q, p)))
    out: List[Point2] = [lines[0][0]]
    for i in range(1, len(lines)):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        hit = _line_intersection(p1, d1, p2, d2)
        out.append(hit if hit is not None else p2)
    last_point, last_dir = lines[-1]
    out.append((last_point[0] + last_dir[0], last_point[1] + last_dir[1]))
    return out


def _line_intersection(p1: Point2, d1: Point2, p2: Point2, d2: Point2) -> Point2 | None:
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-12:
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / denom
    return (p1[0] + d1[0] * t, p1[1] + d1[1] * t)


def chain_strip(chain: Sequence[Point2], distance: float) -> List[Point2]:
    """Ribbon polygon between ``chain`` and its left offset by ``distance``."""
    inner = offset_chain(chain, distance)
    return list(chain) + list(reversed(inner))


def distance_between_parallel_lines(
    p1: Point2, q1: Point2, p2: Point2, q2: Point2
) -> float:
    """Perpendicular distance between two (assumed) parallel lines."""
    d1 = v_sub(q1, p1)
    n = left_normal(d1)
    return abs(v_dot(v_sub(p2, p1), n))


# --------------------------------------------------------------------------- #
# the L-shaped silhouette
# --------------------------------------------------------------------------- #
def elbow_outline(
    arm_half: float, center_to_end: float, mitre_leg: float | None
) -> List[Point2]:
    """Closed CCW silhouette of the 90 deg elbow, in the local (u, v) frame.

    ``arm_half``       half width of the in-plane band (W/2 for the flat
                       families, H/2 for the upright ones)
    ``center_to_end``  centerline length from the pivot to each port
    ``mitre_leg``      leg of the 45 deg outer-corner chamfer, or ``None`` for
                       the sharp (square outer corner) bend
    """
    h = arm_half
    c = center_to_end
    if mitre_leg is None:
        return [(-c, -h), (h, -h), (h, c), (-h, c), (-h, h), (-c, h)]
    if mitre_leg <= 0:
        raise ValueError("mitre leg must be positive")
    # The chamfer cuts the outer corner with two legs of ``mitre_leg``.  It must
    # not run past a port plane, and it must not reach the concave notch corner:
    # the chamfer line is u - v = 2h - leg and the notch corner sits at u - v = -2h.
    if mitre_leg >= h + c:
        raise ValueError("mitre leg would run past the port plane")
    if mitre_leg >= 4.0 * h:
        raise ValueError("mitre leg would cut into the concave (inner) corner")
    return [
        (-c, -h),
        (h - mitre_leg, -h),
        (h, -h + mitre_leg),
        (h, c),
        (-h, c),
        (-h, h),
        (-c, h),
    ]


def elbow_chains(outline: Sequence[Point2]) -> Tuple[List[Point2], List[Point2]]:
    """Split the silhouette into its convex-side and concave-side chains.

    Both chains start at the arm-A port and end at the arm-B port, and both are
    traversed in polygon (counter-clockwise) order, so ``offset_chain(chain,
    +d)`` always moves toward the material.
    """
    pts = list(outline)
    n = len(pts)
    # the two ports are the vertices with the smallest u and largest v
    start = min(range(n), key=lambda i: pts[i][0])
    end = max(range(n), key=lambda i: pts[i][1])
    convex: List[Point2] = []
    i = start
    while True:
        convex.append(pts[i])
        if i == end:
            break
        i = (i + 1) % n
    concave: List[Point2] = [pts[end]]
    i = end
    while True:
        i = (i + 1) % n
        concave.append(pts[i])
        if i == start:
            break
    # concave runs end -> start, i.e. arm B -> arm A; reverse for readability
    concave.reverse()
    return convex, concave


def grow_outline(
    arm_half: float, center_to_end: float, mitre_leg: float | None, grow: float
) -> List[Point2]:
    """Silhouette offset **outwards** by ``grow`` with the ports kept flush."""
    if mitre_leg is None:
        return elbow_outline(arm_half + grow, center_to_end, None)
    return elbow_outline(
        arm_half + grow,
        center_to_end,
        mitre_leg + grow * (2.0 - math.sqrt(2.0)),
    )


# --------------------------------------------------------------------------- #
# 3D frames and prisms
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Frame:
    """Right-handed sketch frame: ``p = origin + u*ex + v*ey``, normal = ex x ey."""

    origin: Point3
    ex: Point3
    ey: Point3

    @property
    def normal(self) -> Point3:
        return v_cross(self.ex, self.ey)

    def to_world(self, u: float, v: float, offset: float = 0.0) -> Point3:
        n = self.normal
        return (
            self.origin[0] + u * self.ex[0] + v * self.ey[0] + offset * n[0],
            self.origin[1] + u * self.ex[1] + v * self.ey[1] + offset * n[1],
            self.origin[2] + u * self.ex[2] + v * self.ey[2] + offset * n[2],
        )


FRAME_XY = Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))  # normal +Z
FRAME_ZY = Frame((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))  # normal +X
FRAME_YZ = Frame((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))  # normal +X
FRAME_ZX = Frame((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))  # normal +Y
FRAME_XZ = Frame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))  # normal -Y
FRAME_XZ_UP = Frame((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))  # normal +Y


def prism_is_watertight(faces: Sequence[Sequence[Point3]], tol: float = 1e-6) -> bool:
    """Every undirected edge must appear exactly twice, in opposite directions."""
    key = lambda p: tuple(round(c / tol) for c in p)  # noqa: E731
    edges: dict = {}
    for face in faces:
        n = len(face)
        for i in range(n):
            a, b = key(face[i]), key(face[(i + 1) % n])
            if a == b:
                return False
            edges[(a, b)] = edges.get((a, b), 0) + 1
    for (a, b), count in edges.items():
        if count != 1:
            return False
        if edges.get((b, a), 0) != 1:
            return False
    return True


def prism_signed_volume(faces: Sequence[Sequence[Point3]]) -> float:
    """Divergence-theorem volume (positive for outward-facing loops)."""
    total = 0.0
    for face in faces:
        p0 = face[0]
        for i in range(1, len(face) - 1):
            p1, p2 = face[i], face[i + 1]
            total += v_dot(p0, v_cross(v_sub(p1, p0), v_sub(p2, p0))) / 6.0
    return total
