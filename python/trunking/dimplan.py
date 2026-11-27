"""Derive a complete, labelled sketch-dimension plan from the symbolic model.

Why this exists
---------------
A family built by API is only *parametric* if the sketch geometry is driven by
labelled dimensions.  Hand-writing those dimensions for 36 profiles x 6
families would be error prone and impossible to keep in sync with the geometry.

Instead, the geometry is described with affine forms (:mod:`.lin`), and this
module recovers, per profile loop and per axis:

* a chain of dimensions between consecutive parallel lines, where the distance
  between the two lines is **exactly** one family parameter, and
* one anchor dimension per axis, from a profile line to the origin reference
  plane, again labelled with a family parameter.

If a distance does not correspond to any existing parameter, a new *instance*
parameter is synthesised with a formula built from the affine form (e.g.
``Cover_Width = Width + Cover_Overhang * 2``).  The plan is therefore closed by
construction, and ``verify.verify_dim_plan`` proves it for every catalogue
size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .lin import Lin, Point2L, p2_eval
from .model import FamilyModel, ParamDef, ParamSet, GROUP_GEOMETRY, SPEC_LENGTH
from . import expr

TOL = 1e-6

RP_X0 = "RP_X0"
RP_Y0 = "RP_Y0"
RP_Z0 = "RP_Z0"

_AXIS_RP = {0: RP_X0, 1: RP_Y0, 2: RP_Z0}

#: friendly names for derived parameters that the closure step synthesises
_FRIENDLY = {
    "Span_Outer_Minus_Wall": "Arm_Half + CenterToEnd - WallThickness",
    "Span_Half_Minus_Wall": "Arm_Half - WallThickness",
    "Span_Inner_Minus_Wall": "-Arm_Half + CenterToEnd - WallThickness",
    "Span_Full_Minus_Wall": "Arm_Half * 2 - WallThickness",
    "Span_Inner_Minus_Overhang": "-Arm_Half + CenterToEnd - Cover_Overhang",
    "Span_Inner_Minus_CoverThk": "-Arm_Half + CenterToEnd - Cover_Thickness",
    "Span_Half_Minus_CoverThk": "Arm_Half - Cover_Thickness",
    "Span_Full_Plus_Overhang": "Arm_Half * 2 + Cover_Overhang * 2",
    "Span_Half_Plus_Overhang": "Arm_Half + Cover_Overhang",
    "Cover_Half_Width": "Half_Width + Cover_Overhang",
    "Cover_Width": "Width + Cover_Overhang * 2",
    "Cover_Outer_Edge": "CenterToEnd + Half_Width + Cover_Overhang",
    "Cover_Margin_Stub_Overhang": "Stub - Cover_Overhang",
    "Cover_Margin_Stub_Thickness": "Stub - Cover_Thickness",
    "Flange_Outer_Half_Width": "Half_Width + Flange_Wrap",
    "Flange_Outer_Half_Height": "Half_Height + Flange_Wrap",
    "Flange_Outer_Width": "Width + Flange_Wrap * 2",
    "Flange_Outer_Height": "Height + Flange_Wrap * 2",
    "Flange_Outer_Width_Y": "Flange_Wrap * 2 + Half_Width * 2",
    "Flange_Outer_Half_Width_Y": "Flange_Wrap + Half_Width",
    "Flange_Outer_Height_Z": "Flange_Wrap * 2 + Half_Height * 2",
    "Flange_Outer_Half_Height_Z": "Flange_Wrap + Half_Height",
}
_NAME_BY_FORMULA = {v: k for k, v in _FRIENDLY.items()}


@dataclass(frozen=True)
class DimEntry:
    solid: str
    loop: int
    axis: str  # 'u' | 'v'
    target_seg: int
    label: str
    expected: float
    ref_kind: str = "line"  # 'line' | 'rp'
    ref_seg: Optional[int] = None
    ref_rp: Optional[str] = None
    reason: str = ""


@dataclass
class DimPlan:
    entries: List[DimEntry] = field(default_factory=list)
    synthesised: List[ParamDef] = field(default_factory=list)
    unmatched: List[Tuple[str, str]] = field(default_factory=list)  # (solid/loop, lin repr)
    diagonal_free: List[Tuple[str, int, int]] = field(default_factory=list)

    def for_solid(self, name: str) -> List[DimEntry]:
        return [e for e in self.entries if e.solid == name]


# --------------------------------------------------------------------------- #
# affine helpers
# --------------------------------------------------------------------------- #
def reference_values(model: FamilyModel, width: float = 100.0, height: float = 50.0) -> Dict[str, float]:
    return ParamSet(model.params, {"Width": width, "Height": height}).numbers()


def param_lins(model: FamilyModel, values: Mapping[str, float]) -> Dict[str, Optional[Lin]]:
    """Affine form of every parameter (``None`` when the formula is not affine)."""
    out: Dict[str, Optional[Lin]] = {}
    names = [p.name for p in model.params]
    for param in model.params:
        if param.formula is None:
            out[param.name] = Lin.of(param.name)
        else:
            try:
                out[param.name] = _lin_of_formula(param.formula, names)
            except ValueError:
                out[param.name] = None
    return out


def _lin_of_formula(text: str, names: Sequence[str]) -> Lin:
    from .lin import lin_from_expr

    return lin_from_expr(text, names)


def lin_to_formula(lin: Lin) -> str:
    """Render an affine form as a Revit family formula with mm units."""
    terms: List[str] = []
    for name in sorted(lin.coeff):
        coeff = lin.coeff[name]
        if abs(abs(coeff) - 1.0) < 1e-9:
            terms.append(("+" if coeff > 0 else "-", f"{name}"))
        else:
            terms.append(("+" if coeff > 0 else "-", f"{name} * {abs(coeff):g}"))
    text = ""
    for i, (sign, body) in enumerate(terms):
        if i == 0:
            text = body if sign == "+" else f"-{body}"
        else:
            text += f" {sign} {body}"
    if abs(lin.k) > 1e-9 or not text:
        constant = f"{abs(lin.k):g} mm"
        if not text:
            text = constant if lin.k >= 0 else f"-{constant}"
        else:
            text += f" {'+' if lin.k > 0 else '-'} {constant}"
    return text


def lin_abs(lin: Lin, values: Mapping[str, float]) -> Lin:
    return lin if lin.evaluate(values) >= 0 else -lin


def match_param(
    distance: Lin,
    model: FamilyModel,
    lins: Mapping[str, Optional[Lin]],
    values: Mapping[str, float],
    prefer: Sequence[str] = (),
) -> Optional[str]:
    """Return the family parameter whose value reproduces ``distance``."""
    # tier 1: symbolic identity with a single parameter
    if len(distance.coeff) == 1 and abs(distance.k) < TOL:
        for name, coeff in distance.coeff.items():
            if abs(coeff - 1.0) < 1e-9 and name in lins:
                return name
    # tier 2: affine equality with a parameter's own formula
    candidates = [
        name
        for name, lin in lins.items()
        if lin is not None and lin.almost_equals(distance, 1e-7)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        for name in prefer:
            if name in candidates:
                return name
        return sorted(candidates)[0]
    # tier 3: numeric equality at the reference size
    if any(name not in values for name in distance.coeff):
        return None
    target = distance.evaluate(values)
    numeric = [
        name
        for name, lin in lins.items()
        if lin is not None and abs(lin.evaluate(values) - target) < 1e-7
    ]
    if len(numeric) == 1:
        return numeric[0]
    if numeric:
        for name in prefer:
            if name in numeric:
                return name
        return sorted(numeric)[0]
    return None


# --------------------------------------------------------------------------- #
# segment classification
# --------------------------------------------------------------------------- #
@dataclass
class _Seg:
    index: int
    a: Point2L
    b: Point2L
    direction: Tuple[float, float]  # unit, at the reference size
    kind: str  # 'u' (u = const), 'v' (v = const) or 'diag'
    offset: Optional[Lin]


def _segments(loop: Sequence[Point2L], values: Mapping[str, float]) -> List[_Seg]:
    out: List[_Seg] = []
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        ax, ay = p2_eval(a, values)
        bx, by = p2_eval(b, values)
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        ux, uy = dx / length, dy / length
        if abs(ux) < 1e-9:
            out.append(_Seg(i, a, b, (ux, uy), "u", a[0]))
        elif abs(uy) < 1e-9:
            out.append(_Seg(i, a, b, (ux, uy), "v", a[1]))
        else:
            out.append(_Seg(i, a, b, (ux, uy), "diag", None))
    return out


def _perpendicular_distance(p1: Point2L, d1: Tuple[float, float], seg: _Seg, values: Mapping[str, float]) -> Lin:
    nx, ny = -d1[1], d1[0]
    q = seg.a
    delta_x = q[0] - p1[0]
    delta_y = q[1] - p1[1]
    return delta_x * nx + delta_y * ny


# --------------------------------------------------------------------------- #
# plan construction
# --------------------------------------------------------------------------- #
def build_plan(model: FamilyModel, width: float = 100.0, height: float = 50.0) -> DimPlan:
    values = reference_values(model, width, height)
    plan = DimPlan()
    seen_forms: Dict[Tuple, str] = {}

    for _ in range(12):  # closure loop: synthesise parameters until stable
        lins = param_lins(model, values)
        plan.entries.clear()
        plan.unmatched.clear()
        plan.diagonal_free.clear()
        missing: List[Tuple[Lin, str]] = []

        for solid in model.solids:
            for loop_index, loop in enumerate(solid.loops):
                segs = _segments(loop, values)
                for axis in ("u", "v"):
                    axis_segs = [s for s in segs if s.kind == axis]
                    if not axis_segs:
                        continue
                    ordered = sorted(axis_segs, key=lambda s: s.offset.evaluate(values))  # type: ignore[union-attr]
                    # deduplicate identical offsets (collinear lines)
                    unique: List[_Seg] = []
                    for seg in ordered:
                        if not unique or not seg.offset.almost_equals(unique[-1].offset):  # type: ignore[union-attr]
                            unique.append(seg)
                        else:
                            unique[-1] = seg  # keep the longest/representative
                    for left, right in zip(unique[:-1], unique[1:]):
                        distance = right.offset - left.offset  # type: ignore[operator]
                        if distance.evaluate(values) < 0:
                            distance = -distance
                        label = match_param(distance, model, lins, values, prefer=("Width", "Height", "WallThickness"))
                        if label is None:
                            missing.append((distance, f"{solid.name}[{loop_index}].{axis}"))
                            continue
                        plan.entries.append(
                            DimEntry(
                                solid=solid.name,
                                loop=loop_index,
                                axis=axis,
                                target_seg=right.index,
                                label=label,
                                expected=distance.evaluate(values),
                                ref_kind="line",
                                ref_seg=left.index if left.index != right.index else left.index,
                                reason="chain",
                            )
                        )
                    # anchor: closest line to the frame origin
                    anchor_seg = min(unique, key=lambda s: abs(s.offset.evaluate(values)))  # type: ignore[union-attr]
                    anchor = lin_abs(anchor_seg.offset, values)  # type: ignore[arg-type]
                    rp = axis_reference_plane(solid.frame, axis)
                    label = match_param(anchor, model, lins, values)
                    if label is None:
                        missing.append((anchor, f"{solid.name}[{loop_index}].{axis}.anchor"))
                    else:
                        plan.entries.append(
                            DimEntry(
                                solid=solid.name,
                                loop=loop_index,
                                axis=axis,
                                target_seg=anchor_seg.index,
                                label=label,
                                expected=anchor.evaluate(values),
                                ref_kind="rp",
                                ref_rp=rp,
                                reason="anchor",
                            )
                        )
                # diagonals: dimension against a parallel partner when one exists
                diags = [s for s in segs if s.kind == "diag"]
                for i, seg in enumerate(diags):
                    partner = None
                    for other in diags[i + 1 :]:
                        if abs(abs(seg.direction[0] * other.direction[0] + seg.direction[1] * other.direction[1]) - 1.0) < 1e-9:
                            partner = other
                            break
                    if partner is None:
                        plan.diagonal_free.append((solid.name, loop_index, seg.index))
                        continue
                    distance = lin_abs(_perpendicular_distance(seg.a, seg.direction, partner, values), values)
                    label = match_param(distance, model, lins, values, prefer=("WallThickness", "Cover_Thickness"))
                    if label is None:
                        missing.append((distance, f"{solid.name}[{loop_index}].diag"))
                        continue
                    plan.entries.append(
                        DimEntry(
                            solid=solid.name,
                            loop=loop_index,
                            axis="diag",
                            target_seg=partner.index,
                            label=label,
                            expected=distance.evaluate(values),
                            ref_kind="line",
                            ref_seg=seg.index,
                            reason="parallel-diagonal",
                        )
                    )

        if not missing:
            return plan

        # synthesise one parameter per distinct missing form
        new_params: List[ParamDef] = []
        for form, where in missing:
            key = form.key()
            if key in seen_forms:
                continue
            formula = lin_to_formula(form)
            name = _NAME_BY_FORMULA.get(formula)
            if name is None:
                name = f"Derived_{len(seen_forms) + 1:02d}"
            if any(p.name == name for p in model.params):
                name = f"{name}_2"
            param = ParamDef(
                name=name,
                spec=SPEC_LENGTH,
                group=GROUP_GEOMETRY,
                formula=formula,
                description=f"自動衍生尺寸 (derived, closes the dimension chain): {formula}",
            )
            new_params.append(param)
            seen_forms[key] = name
            plan.unmatched.append((where, formula))
        if not new_params:
            # nothing new can be synthesised: give up on the remaining forms
            return plan
        model.params.extend(new_params)
        plan.synthesised.extend(new_params)
        values = reference_values(model, width, height)

    return plan


def axis_reference_plane(frame, axis: str) -> str:
    """Name of the world-axis reference plane that hosts the sketch ``axis``."""
    vector = frame.ex if axis == "u" else frame.ey
    index = max(range(3), key=lambda i: abs(vector[i]))
    if abs(abs(vector[index]) - 1.0) > 1e-6:
        raise ValueError(f"sketch axis {axis} is not world aligned: {vector}")
    return _AXIS_RP[index]
