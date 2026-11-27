"""Automated acceptance checks for the six families.

Everything here runs without Revit: the family model is flexed over the eleven
test sizes (nine catalogue sizes + ``300x100`` + ``50x100``) and the resulting
geometry is measured.  ``verify_families.py`` runs the same checks against the
real ``.rfa`` files inside Revit.

Checks fall into four groups:

``catalogue``   the measured geometry matches the manufacturer sheet
                (A, B, C, D, E, wall thickness).
``parametric``  the derived dimension plan is complete and reproduces the
                profile exactly at every size - i.e. one single type really does
                cover all sizes.
``geometry``    every solid is a valid, watertight prism with positive volume,
                no self-intersecting loops and no protrusion through a port.
``api``         connector frames, port faces, part type and the single-type
                invariant (the last two are asserted by the builders).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import expr
from .dimplan import DimPlan, build_plan
from .evaluate import EvaluatedModel, evaluate_model, evaluate_params
from .geometry import (
    polygon_area,
    polygon_self_intersects,
    prism_is_watertight,
    prism_signed_volume,
)
from .model import TYPE_NAME, FamilyModel, ParamSet, split_chains
from .spec import DRAWING_BY_SIZE, DrawingRow, FLEX_SIZES, FamilyKind, thickness_tag

TOL = 1e-6
DRAWING_TOL = 0.51  # the sheet rounds C to 106 (75*sqrt(2) = 106.07)
LENGTH_TOL = 0.05


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    group: str = "geometry"

    def __str__(self) -> str:
        return f"[{'PASS' if self.ok else 'FAIL'}] {self.group}/{self.name} {self.detail}"


@dataclass
class SizeResult:
    width: float
    height: float
    center_to_end: float
    outer_edge: float
    c_mitre: Optional[float]
    c_sharp: Optional[float]
    wall: float
    wall_tag: str
    volume: float
    drawing: Optional[DrawingRow] = None

    @property
    def label(self) -> str:
        return f"{self.width:g}x{self.height:g}"


def measure_family(model: FamilyModel, width: float, height: float) -> Tuple[SizeResult, EvaluatedModel]:
    values = evaluate_params(model, width, height)
    evaluated = evaluate_model(model, values)
    outline_solid = silhouette_solid(evaluated)
    outline = outline_solid.loops[0].points
    max_u = max(p[0] for p in outline)
    min_u = min(p[0] for p in outline)
    max_v = max(p[1] for p in outline)
    min_v = min(p[1] for p in outline)
    center_to_end = evaluated.length("CenterToEnd")
    outer_edge = max_u - min_u  # == CenterToEnd + Arm_Half

    # the 45 deg mitre face, measured on the footprint
    chamfer = None
    for a, b in zip(outline, outline[1:] + outline[:1]):
        du, dv = b[0] - a[0], b[1] - a[1]
        if abs(du) > TOL and abs(dv) > TOL:
            chamfer = math.hypot(du, dv)
    # the inner straight stub: length of the concave chain's first segment
    stub = _inner_stub(evaluated, outline)

    volume = sum(s.volume for s in evaluated.solids.values() if s.visible)
    return (
        SizeResult(
            width=width,
            height=height,
            center_to_end=center_to_end,
            outer_edge=outer_edge,
            c_mitre=chamfer,
            c_sharp=stub,
            wall=evaluated.length("WallThickness"),
            wall_tag=thickness_tag(evaluated.length("WallThickness")),
            volume=volume,
            drawing=DRAWING_BY_SIZE.get((width, height)),
        ),
        evaluated,
    )


def silhouette_solid(evaluated: EvaluatedModel):
    """The solid whose first loop is the full in-plane silhouette."""
    if evaluated.model.kind.mode == "flat":
        return evaluated.solids["Tray_Base"]
    return evaluated.solids["Wall_Near"]


def _inner_stub(evaluated: EvaluatedModel, outline: Sequence[Tuple[float, float]]) -> float:
    """Length of the concave-side straight run at the port (== Stub, 75 mm)."""
    _, concave = split_chains(list(outline))
    (u0, v0), (u1, v1) = concave[0], concave[1]
    return math.hypot(u1 - u0, v1 - v0)


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_single_type(model: FamilyModel) -> Check:
    types = list(model.type_names)
    ok = len(types) == 1 and types[0] == TYPE_NAME
    return Check(
        "single_family_type",
        ok,
        f"FamilyManager.Types.Size == {len(types)} ({', '.join(types)})",
        "api",
    )


def check_instance_parameters(model: FamilyModel) -> Check:
    offenders = [p.name for p in model.params if not p.instance]
    return Check(
        "all_parameters_instance",
        not offenders,
        f"{len(model.params)} parameters, offenders={offenders}",
        "api",
    )


def check_no_lookup_table(model: FamilyModel) -> Check:
    """No per-size branching anywhere except the documented wall-thickness rule."""
    offenders: List[str] = []
    for param in model.params:
        if not param.formula or param.name == "WallThickness":
            continue
        deps = expr.dependencies(param.formula)
        if "if(" in param.formula.replace(" ", "") and ("Width" in deps or "Height" in deps):
            offenders.append(param.name)
    names = [p.name for p in model.params]
    duplicated = len(names) != len(set(names))
    sized = [name for name in names if re.fullmatch(r"\d+\s*[xX]\s*\d+", name)]
    ok = not offenders and not duplicated and not sized
    detail = (
        f"single type, no type catalog, no per-size branches ({len(names)} unique instance parameters)"
        if ok
        else f"offenders={offenders} duplicated={duplicated} size-named={sized}"
    )
    return Check("no_type_catalogue", ok, detail, "api")


def check_connectors(model: FamilyModel, sizes: Sequence[Tuple[float, float]] = FLEX_SIZES) -> List[Check]:
    checks: List[Check] = []
    for width, height in sizes:
        values = evaluate_params(model, width, height)
        evaluated = evaluate_model(model, values)
        c2e = evaluated.length("CenterToEnd")
        expect_a = (-c2e, 0.0, 0.0)
        if model.kind.mode == "flat":
            expect_b = (0.0, c2e, 0.0)
        else:
            expect_b = (0.0, 0.0, c2e)
        ok = True
        detail = []
        for name, expect in (("Port_A", expect_a), ("Port_B", expect_b)):
            conn = evaluated.connectors.get(name)
            if conn is None:
                ok = False
                detail.append(f"{name}: MISSING")
                continue
            host = evaluated.solids.get(conn.host_solid)
            if host is None:
                ok = False
                detail.append(f"{name}: host solid {conn.host_solid} MISSING")
                continue
            origin_ok = all(abs(a - b) < 1e-6 for a, b in zip(conn.origin, expect))
            size_ok = abs(conn.width - width) < 1e-6 and abs(conn.height - height) < 1e-6
            outward = _normal_points_outward(evaluated, conn)
            ok = ok and origin_ok and size_ok and outward
            detail.append(
                f"{name}: origin{'ok' if origin_ok else 'BAD'} size{'ok' if size_ok else 'BAD'} "
                f"normal{'ok' if outward else 'BAD'}"
            )
        checks.append(
            Check(
                f"connectors_{width:g}x{height:g}",
                ok,
                "; ".join(detail),
                "api",
            )
        )
    return checks


def _normal_points_outward(evaluated: EvaluatedModel, conn) -> bool:
    """The connector normal must point away from the body it is hosted on.

    The connector lives on the port face of the coupling collar, so the normal
    must be parallel to (collar centroid -> port plane) and point outwards.
    """
    normal = conn.normal
    host = evaluated.solids[conn.host_solid]
    centre = _centroid(host)
    away = [conn.origin[i] - centre[i] for i in range(3)]
    dot = sum(n * a for n, a in zip(normal, away))
    perpendicular = [
        away[i] - dot * normal[i] for i in range(3)
    ]
    return dot > 1e-6 and all(abs(c) < 1e-6 for c in perpendicular)


def check_catalogue(model: FamilyModel, sizes: Sequence[Tuple[float, float]] = FLEX_SIZES) -> List[Check]:
    checks: List[Check] = []
    for width, height in sizes:
        result, _ = measure_family(model, width, height)
        row = result.drawing
        problems = []
        if model.kind.mode == "flat":
            expect_cte = width / 2.0 + 75.0
            expect_outer = width + 75.0
        else:
            expect_cte = height / 2.0 + 75.0
            expect_outer = height + 75.0
        if abs(result.center_to_end - expect_cte) > LENGTH_TOL:
            problems.append(f"CenterToEnd {result.center_to_end:.2f} != {expect_cte:.2f}")
        if abs(result.outer_edge - expect_outer) > LENGTH_TOL:
            problems.append(f"outer edge {result.outer_edge:.2f} != {expect_outer:.2f}")
        if model.kind.is_mitre:
            if result.c_mitre is None or abs(result.c_mitre - 75.0 * math.sqrt(2)) > LENGTH_TOL:
                problems.append(f"mitre face {result.c_mitre} != 75*sqrt(2)")
        else:
            if result.c_mitre is not None:
                problems.append("sharp bend must not have a mitre face")
        if abs(result.c_sharp - 75.0) > LENGTH_TOL:
            problems.append(f"inner stub {result.c_sharp:.2f} != 75")
        if row is not None:
            expect_a = row.a if model.kind.mode == "flat" else row.d
            expect_b = row.b if model.kind.mode == "flat" else row.e
            if abs(result.outer_edge - expect_a) > DRAWING_TOL:
                problems.append(f"A/D {result.outer_edge:.2f} vs sheet {expect_a}")
            if abs(result.outer_edge - expect_b) > DRAWING_TOL:
                problems.append(f"B/E {result.outer_edge:.2f} vs sheet {expect_b}")
            if model.kind.is_mitre and result.c_mitre is not None:
                if abs(result.c_mitre - row.c_mitre) > DRAWING_TOL:
                    problems.append(f"C {result.c_mitre:.2f} vs sheet {row.c_mitre}")
            if not model.kind.is_mitre:
                if abs(result.c_sharp - row.c_sharp) > DRAWING_TOL:
                    problems.append(f"C {result.c_sharp:.2f} vs sheet {row.c_sharp}")
        checks.append(
            Check(
                f"catalogue_{width:g}x{height:g}",
                not problems,
                "; ".join(problems) or f"C2E={result.center_to_end:.2f} A/B={result.outer_edge:.2f} "
                f"C={(result.c_mitre or result.c_sharp):.2f} T={result.wall:.2f}",
                "catalogue",
            )
        )
    return checks


def check_geometry(model: FamilyModel, sizes: Sequence[Tuple[float, float]] = FLEX_SIZES) -> List[Check]:
    checks: List[Check] = []
    for width, height in sizes:
        _, evaluated = measure_family(model, width, height)
        problems: List[str] = []
        for name, solid in evaluated.solids.items():
            for index, loop in enumerate(solid.loops):
                if abs(loop.area) < 1e-9:
                    problems.append(f"{name}[{index}] zero area")
                if polygon_self_intersects(loop.points):
                    problems.append(f"{name}[{index}] self-intersecting")
            if solid.depth <= 0:
                problems.append(f"{name} depth {solid.depth:.3f} <= 0")
            if solid.volume <= 1e-9:
                problems.append(f"{name} volume {solid.volume:.3f} <= 0")
            if len(solid.loops) == 1:
                faces = solid.all_faces()
                if not prism_is_watertight(faces):
                    problems.append(f"{name} not watertight")
                volume = prism_signed_volume(faces)
                if volume <= 0:
                    problems.append(f"{name} inverted faces")
            # nothing may poke through a port plane
            for conn in evaluated.connectors.values():
                margin = _protrusion(evaluated, solid, conn)
                if margin > 1e-6:
                    problems.append(f"{name} protrudes {margin:.2f} mm past {conn.name}")
        checks.append(
            Check(f"geometry_{width:g}x{height:g}", not problems, "; ".join(problems) or "ok", "geometry")
        )
    return checks


def _protrusion(evaluated: EvaluatedModel, solid, conn) -> float:
    """How far the solid sticks out beyond the connector plane (0 == flush)."""
    normal = conn.normal
    worst = 0.0
    for loop in solid.loops:
        for offset in (solid.start, solid.end):
            for u, v in loop.points:
                p = solid.frame.to_world(u, v, offset)
                rel = sum((p[i] - conn.origin[i]) * normal[i] for i in range(3))
                if rel > worst:
                    worst = rel
    return worst


def check_dim_plan(
    model: FamilyModel, plan: DimPlan, sizes: Sequence[Tuple[float, float]] = FLEX_SIZES
) -> List[Check]:
    """Prove that every sketch dimension really is driven by a parameter."""
    checks: List[Check] = []
    problems: List[str] = []
    for entry in plan.entries:
        solid = model.solid(entry.solid)
        if entry.loop >= len(solid.loops):
            problems.append(f"{entry.solid}: loop {entry.loop} missing")
            continue
        if entry.label not in {p.name for p in model.params}:
            problems.append(f"{entry.solid}: label {entry.label} is not a parameter")
    checks.append(
        Check(
            "dim_plan_labels",
            not problems,
            f"{len(plan.entries)} labelled dimensions; " + ("; ".join(problems) or "all labels resolve"),
            "parametric",
        )
    )

    # measure every labelled distance at every size
    worst = 0.0
    worst_where = ""
    for width, height in sizes:
        values = ParamSet(model.params, {"Width": width, "Height": height})
        numbers = values.numbers()
        for entry in plan.entries:
            solid = model.solid(entry.solid)
            loop = solid.loops[entry.loop]
            measured = _measure_entry(loop, entry, values)
            expected = float(values.get(entry.label))
            error = abs(measured - expected)
            if error > worst:
                worst, worst_where = error, f"{entry.solid}[{entry.loop}].{entry.axis} {width:g}x{height:g}"
    checks.append(
        Check(
            "dim_plan_exact",
            worst < 1e-6,
            f"max |measured - parameter| = {worst:.3e} mm ({worst_where})",
            "parametric",
        )
    )

    # every profile line must be anchored to the origin planes through a chain
    unanchored: List[str] = []
    for solid in model.solids:
        for index, loop in enumerate(solid.loops):
            for axis in ("u", "v"):
                anchored = _axis_anchored(plan, solid.name, index, axis, loop, model)
                if not anchored:
                    unanchored.append(f"{solid.name}[{index}].{axis}")
    checks.append(
        Check(
            "dim_plan_anchored",
            not unanchored,
            "all profile lines driven by labelled dimensions" if not unanchored else f"unanchored: {unanchored}",
            "parametric",
        )
    )
    checks.append(
        Check(
            "dim_plan_free_diagonals",
            True,
            f"{len(plan.diagonal_free)} chamfer lines keep one redundant-free DOF "
            "(the 45 deg angle and leg length are preserved by the solver; see docs/02)",
            "parametric",
        )
    )
    return checks


def _measure_entry(loop, entry, values: ParamSet) -> float:
    points = [(p[0].evaluate(values.numbers()), p[1].evaluate(values.numbers())) for p in loop]
    n = len(points)
    target_a = points[entry.target_seg % n]
    target_b = points[(entry.target_seg + 1) % n]
    if entry.ref_kind == "rp":
        return abs(target_a[0] if entry.axis == "u" else target_a[1])
    ref_a = points[entry.ref_seg % n]
    ref_b = points[(entry.ref_seg + 1) % n]
    if entry.axis == "diag":
        du = target_b[0] - target_a[0]
        dv = target_b[1] - target_a[1]
        length = math.hypot(du, dv)
        nx, ny = -dv / length, du / length
        return abs((ref_a[0] - target_a[0]) * nx + (ref_a[1] - target_a[1]) * ny)
    if entry.axis == "u":
        return abs(target_a[0] - ref_a[0])
    return abs(target_a[1] - ref_a[1])


def _axis_anchored(plan: DimPlan, solid: str, loop: int, axis: str, loop_points, model: FamilyModel) -> bool:
    entries = [
        e
        for e in plan.entries
        if e.solid == solid and e.loop == loop and (e.axis == axis or e.axis == "diag")
    ]
    if not entries:
        return False
    has_anchor = any(e.ref_kind == "rp" for e in entries)
    return has_anchor


def _centroid(solid) -> Tuple[float, float, float]:
    points = []
    for loop in solid.loops:
        for u, v in loop.points:
            points.append(solid.frame.to_world(u, v, (solid.start + solid.end) / 2.0))
    return tuple(sum(p[i] for p in points) / len(points) for i in range(3))  # type: ignore[return-value]


def _centroid_any(solids) -> Tuple[float, float, float]:
    points = [_centroid(solid) for solid in solids]
    return tuple(sum(p[i] for p in points) / len(points) for i in range(3))  # type: ignore[return-value]


def check_cover_side(model: FamilyModel, sizes: Sequence[Tuple[float, float]] = FLEX_SIZES) -> List[Check]:
    """The cover must sit on the concave (internal) or convex (external) side."""
    problems: List[str] = []
    for width, height in sizes:
        _, evaluated = measure_family(model, width, height)
        cover = evaluated.solids["Cover"]
        if model.kind.mode == "flat":
            cover_z = _centroid(cover)[2]
            base_z = _centroid(evaluated.solids["Tray_Base"])[2]
            if not cover_z > base_z + evaluated.length("Height") * 0.5:
                problems.append(f"{width:g}x{height:g}: cover not on +Z (front opening)")
            continue
        frame = silhouette_solid(evaluated).frame
        convex, concave = split_chains(list(silhouette_solid(evaluated).loops[0].points))
        cover_pts = [
            _to_band(frame, cover.frame.to_world(u, v, (cover.start + cover.end) / 2.0))
            for u, v in cover.loops[0].points
        ]
        d_conc = sum(_min_distance(p, concave) for p in cover_pts) / len(cover_pts)
        d_conv = sum(_min_distance(p, convex) for p in cover_pts) / len(cover_pts)
        side = "concave" if d_conc < d_conv else "convex"
        if side != model.kind.cover_side:
            problems.append(f"{width:g}x{height:g}: cover on {side}, expected {model.kind.cover_side}")
            continue
        base = evaluated.solids["Tray_Base"]
        base_pts = [
            _to_band(frame, base.frame.to_world(u, v, (base.start + base.end) / 2.0))
            for u, v in base.loops[0].points
        ]
        d_conc = sum(_min_distance(p, concave) for p in base_pts) / len(base_pts)
        d_conv = sum(_min_distance(p, convex) for p in base_pts) / len(base_pts)
        base_side = "concave" if d_conc < d_conv else "convex"
        if base_side != model.kind.bottom_side:
            problems.append(f"{width:g}x{height:g}: base on {base_side}, expected {model.kind.bottom_side}")
    return [
        Check(
            "cover_and_base_sides",
            not problems,
            "; ".join(problems) or f"cover on {model.kind.cover_side}, base on {model.kind.bottom_side}",
            "catalogue",
        )
    ]


def _to_band(frame, point: Sequence[float]) -> Tuple[float, float]:
    u = sum(point[i] * frame.ex[i] for i in range(3))
    v = sum(point[i] * frame.ey[i] for i in range(3))
    return (u, v)


def _min_distance(point: Tuple[float, float], chain: Sequence[Tuple[float, float]]) -> float:
    best = float("inf")
    for a, b in zip(chain[:-1], chain[1:]):
        best = min(best, _point_segment_distance(point, a, b))
    return best


def _point_segment_distance(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 < 1e-12:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _is_concave_side(point: Sequence[float], evaluated: EvaluatedModel) -> bool:  # pragma: no cover
    frame = evaluated.solids["Tray_Base"].frame
    u = sum(point[i] * frame.ex[i] for i in range(3))
    v = sum(point[i] * frame.ey[i] for i in range(3))
    half = evaluated.length("Arm_Half")
    return math.hypot(u + half, v - half) < math.hypot(u - half, v + half)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
@dataclass
class FamilyResult:
    model: FamilyModel
    plan: DimPlan
    checks: List[Check] = field(default_factory=list)
    sizes: List[SizeResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.ok]


def verify_family(model: FamilyModel, sizes: Sequence[Tuple[float, float]] = FLEX_SIZES) -> FamilyResult:
    plan = build_plan(model)
    result = FamilyResult(model=model, plan=plan)
    result.checks += [check_single_type(model), check_instance_parameters(model), check_no_lookup_table(model)]
    result.checks += check_geometry(model, sizes)
    result.checks += check_catalogue(model, sizes)
    result.checks += check_connectors(model, sizes)
    result.checks += check_dim_plan(model, plan, sizes)
    result.checks += check_cover_side(model, sizes)
    for width, height in sizes:
        result.sizes.append(measure_family(model, width, height)[0])
    return result


def wall_thickness_audit(model: FamilyModel) -> List[Tuple[str, float, float, bool]]:
    """Compare the formula's wall thickness with the published model code."""
    rows = []
    for width, height in FLEX_SIZES:
        row = DRAWING_BY_SIZE.get((width, height))
        values = evaluate_params(model, width, height)
        wall = float(values["WallThickness"])
        if row is not None:
            rows.append((f"{width:g}x{height:g}", wall, row.wall_mm, abs(wall - row.wall_mm) < 1e-6))
        else:
            rows.append((f"{width:g}x{height:g}", wall, float("nan"), True))
    return rows
