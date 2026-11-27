"""An in-memory stand-in for the parts of the Revit API the builder touches.

Purpose: the build pipeline can be exercised end to end on a machine without
Revit (CI, this repository's sandbox).  The fake is *not* a simulator of
Revit's constraint solver - it validates the structural contract instead:

* exactly one family type exists before and after the build,
* every parameter is an instance parameter,
* every formula parses and only references parameters that exist,
* every extrusion offset is associated with a parameter,
* every sketch dimension is labelled with an existing instance parameter and
  its measured distance equals that parameter's value,
* two rectangular cable-tray connectors exist, are size-bound and linked,
* the family category and the elbow part type are set,
* nothing outside the model's own parameter list is ever created.

The geometric flexing itself is proved by :mod:`trunking.verify` on the model,
which is what the real family will do once its sketch dimensions are labelled.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import adapter as api
from . import expr
from .adapter import CapResult
from .model import ParamDef, SPEC_ANGLE, SPEC_LENGTH, SPEC_MATERIAL, SPEC_TEXT, SPEC_YESNO
from .spec import thickness_tag


@dataclass
class FakeParam:
    name: str
    spec: str
    instance: bool = True
    formula: Optional[str] = None
    default: Any = 0.0
    value: Any = 0.0
    builtin: Optional[str] = None


@dataclass
class FakeElement:
    kind: str
    name: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeConnector:
    name: str
    origin: Tuple[float, float, float]
    basis_x: Tuple[float, float, float]
    basis_y: Tuple[float, float, float]
    width: float
    height: float
    width_param: Optional[str] = None
    height_param: Optional[str] = None
    linked: Optional["FakeConnector"] = None
    host: Optional[FakeElement] = None
    profile: str = "Rectangular"


@dataclass
class FakeDoc:
    title: str
    category: str = "OST_CableTrayFitting"
    types: List[str] = field(default_factory=lambda: ["Standard"])
    params: Dict[str, FakeParam] = field(default_factory=dict)
    elements: List[FakeElement] = field(default_factory=list)
    connectors: List[FakeConnector] = field(default_factory=list)
    subcategories: Dict[str, str] = field(default_factory=dict)
    materials: Dict[str, str] = field(default_factory=dict)
    part_type: str = ""
    dimensions: List[Dict[str, Any]] = field(default_factory=list)
    symbolic: List[Dict[str, Any]] = field(default_factory=list)
    new_types_created: int = 0
    category_calls: int = 0
    saved_to: str = ""

    # -- evaluation -------------------------------------------------------- #
    def evaluate(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        visiting: List[str] = []

        def resolve(name: str) -> Any:
            if name in values:
                return values[name]
            param = self.params[name]
            if param.formula:
                if name in visiting:
                    raise ValueError(f"circular formula: {' -> '.join(visiting + [name])}")
                visiting.append(name)
                for dep in expr.dependencies(param.formula):
                    if dep not in self.params:
                        raise ValueError(f"{name}: formula references unknown parameter {dep}")
                    resolve(dep)
                value = expr.evaluate(param.formula, {k: _num(v) for k, v in values.items()})
                visiting.pop()
            else:
                value = param.default
            if param.spec == SPEC_YESNO:
                value = bool(value)
            elif param.spec in (SPEC_LENGTH, SPEC_ANGLE):
                value = float(value)
            param.value = value
            values[name] = value
            return value

        for name in self.params:
            resolve(name)
        return values


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


class FakeRevit(api.RevitAdapter):
    """Implements :class:`trunking.adapter.RevitAdapter` without Revit."""

    name = "fake"

    def __init__(self, log=None) -> None:
        self.messages: List[str] = []
        self._log = log
        self.docs: List[FakeDoc] = []

    def log(self, message: str) -> None:
        self.messages.append(message)
        if self._log:
            self._log(message)

    # -- document ---------------------------------------------------------- #
    def open_family_template(self, template_path: str, destination: str) -> FakeDoc:
        doc = FakeDoc(title=os.path.basename(template_path))
        # the metric cable tray fitting template already carries these
        doc.params["Width"] = FakeParam("Width", SPEC_LENGTH, default=100.0, value=100.0, builtin="RBS_CABLETRAY_WIDTH")
        doc.params["Height"] = FakeParam("Height", SPEC_LENGTH, default=50.0, value=50.0, builtin="RBS_CABLETRAY_HEIGHT")
        doc.params["Angle"] = FakeParam("Angle", SPEC_ANGLE, default=90.0, value=90.0, builtin="RBS_FITTING_ANGLE")
        self.docs.append(doc)
        return doc

    def save_family(self, doc: FakeDoc, path: str) -> CapResult:
        doc.saved_to = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        payload = {
            "virtual_rfa": True,
            "title": doc.title,
            "category": doc.category,
            "types": doc.types,
            "part_type": doc.part_type,
            "parameters": {name: {"spec": p.spec, "instance": p.instance, "formula": p.formula} for name, p in doc.params.items()},
            "solids": [
                {"name": e.name, **{k: v for k, v in e.data.items() if k in ("loops", "start", "end", "detail", "subcategory", "material")}}
                for e in doc.elements
                if e.kind == "extrusion"
            ],
            "connectors": [
                {"name": c.name, "origin": c.origin, "normal": _normal(c), "width": c.width, "height": c.height, "linked": c.linked is not None}
                for c in doc.connectors
            ],
            "dimensions": len(doc.dimensions),
            "symbolic_lines": len(doc.symbolic),
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return api.ok(path)

    def close_family(self, doc: FakeDoc) -> None:
        pass

    def regenerate(self, doc: FakeDoc) -> None:
        doc.evaluate()

    # -- family manager ---------------------------------------------------- #
    def family_type_count(self, doc: FakeDoc) -> int:
        return len(doc.types)

    def ensure_single_type(self, doc: FakeDoc, name: str) -> CapResult:
        if len(doc.types) != 1:
            return api.failed(f"template already has {len(doc.types)} types")
        doc.types = [name]
        return api.ok(f"type renamed to {name}; NewType() is never called")

    def parameter_names(self, doc: FakeDoc) -> Sequence[str]:
        return list(doc.params)

    def add_instance_parameter(self, doc: FakeDoc, definition: ParamDef) -> CapResult:
        if definition.name in doc.params:
            return api.failed(f"duplicate parameter {definition.name}")
        if not definition.instance:
            return api.failed(f"{definition.name} would be a type parameter")
        doc.params[definition.name] = FakeParam(
            name=definition.name,
            spec=definition.spec,
            instance=definition.instance,
            formula=None,
            default=definition.default,
            value=definition.default,
        )
        return api.ok("instance" if definition.instance else "TYPE (rejected by model validation)")

    def set_formula(self, doc: FakeDoc, name: str, formula: str) -> CapResult:
        if name not in doc.params:
            return api.failed(f"unknown parameter {name}")
        param = doc.params[name]
        if not param.instance:
            return api.failed("a type parameter cannot reference instance parameters")
        if not expr.checks_out(formula):
            return api.failed(f"formula does not parse: {formula}")
        try:
            doc.evaluate()
        except Exception as exc:  # noqa: BLE001 - surfaced as a build failure
            return api.failed(str(exc))
        param.formula = formula
        try:
            doc.evaluate()
        except Exception as exc:  # noqa: BLE001
            return api.failed(str(exc))
        return api.ok(formula)

    def set_value(self, doc: FakeDoc, name: str, value: Any) -> CapResult:
        if name not in doc.params:
            return api.failed(f"unknown parameter {name}")
        if doc.params[name].formula:
            return api.skipped("parameter is driven by a formula")
        doc.params[name].default = value
        doc.params[name].value = value
        return api.ok(str(value))

    # -- categories / materials ------------------------------------------- #
    def ensure_subcategory(self, doc: FakeDoc, name: str) -> CapResult:
        doc.subcategories.setdefault(name, name)
        return api.ok(name)

    def ensure_material(self, doc: FakeDoc, name: str) -> str:
        doc.materials.setdefault(name, f"material:{name}")
        return doc.materials[name]

    def ensure_cable_tray_fitting_category(self, doc: FakeDoc) -> CapResult:
        doc.category_calls += 1
        doc.category = "OST_CableTrayFitting"
        return api.ok("OST_CableTrayFitting")

    def set_part_type(self, doc: FakeDoc, part_type: str = "Elbow") -> CapResult:
        doc.part_type = part_type
        return api.ok(f"FAMILY_CONTENT_PART_TYPE = {part_type}")

    # -- geometry ---------------------------------------------------------- #
    def create_extrusion(
        self,
        doc: FakeDoc,
        solid_def: Any,
        loops: Sequence[Sequence[Tuple[float, float]]],
        start: float,
        end: float,
    ) -> FakeElement:
        element = FakeElement(
            kind="extrusion",
            name=solid_def.name,
            data={
                "loops": [[[round(u, 6), round(v, 6)] for u, v in loop] for loop in loops],
                "start": start,
                "end": end,
                "detail": solid_def.detail,
                "subcategory": solid_def.subcategory,
                "frame": {
                    "origin": solid_def.frame.origin,
                    "ex": solid_def.frame.ex,
                    "ey": solid_def.frame.ey,
                },
            },
        )
        doc.elements.append(element)
        return element

    def associate_extrusion_offsets(
        self, doc: FakeDoc, element: FakeElement, start_param: str, end_param: str
    ) -> CapResult:
        for name in (start_param, end_param):
            param = doc.params.get(name)
            if param is None:
                return api.failed(f"missing parameter {name}")
            if not param.instance:
                return api.failed(f"{name} must be an instance parameter")
        element.data["offset_params"] = (start_param, end_param)
        return api.ok(f"EXTRUSION_START_PARAM={start_param}, EXTRUSION_END_PARAM={end_param}")

    def apply_sketch_dimensions(
        self, doc: FakeDoc, element: FakeElement, requests: Sequence[Any], values: Dict[str, float]
    ) -> CapResult:
        if not requests:
            return api.skipped("no dimensions for this profile")
        for request in requests:
            param = doc.params.get(request.label)
            if param is None:
                return api.failed(f"{request.solid}: label {request.label} is not a parameter")
            if not param.instance:
                return api.failed(f"{request.solid}: label {request.label} is a type parameter")
            if request.ref_kind not in ("line", "rp"):
                return api.failed(f"{request.solid}: bad reference kind {request.ref_kind}")
            if request.ref_mid == request.target_mid:
                return api.failed(f"{request.solid}: degenerate dimension line for {request.label}")
        element.data["dimensions"] = [r.label for r in requests]
        doc.dimensions.extend(
            {
                "solid": r.solid,
                "axis": r.axis,
                "label": r.label,
                "expected": r.expected,
                "loop": r.loop,
                "ref": r.ref_plane if r.ref_kind == "rp" else "line",
                "target": list(r.target_mid),
            }
            for r in requests
        )
        return api.ok(f"{len(requests)} labelled dimensions")

    def set_detail_visibility(self, doc: FakeDoc, element: FakeElement, detail: str) -> CapResult:
        element.data["detail"] = detail
        return api.ok(detail)

    def associate_visibility(self, doc: FakeDoc, element: FakeElement, show_param: str) -> CapResult:
        param = doc.params.get(show_param)
        if param is None or param.spec != SPEC_YESNO:
            return api.fallback(f"{show_param} is not a Yes/No parameter")
        element.data["show_param"] = show_param
        return api.ok(show_param)

    def set_element_material(self, doc: FakeDoc, element: FakeElement, material_param: str, material: Any) -> CapResult:
        if material is None:
            return api.skipped("no material")
        element.data["material"] = material
        element.data["material_param"] = material_param
        return api.ok(str(material))

    # -- connectors -------------------------------------------------------- #
    def create_cable_tray_connector(
        self, doc: FakeDoc, connector_def: Any, values: Dict[str, float], host_element: Optional[FakeElement]
    ) -> FakeConnector:
        if host_element is None:
            self.log(f"connector {connector_def.name}: host solid missing")
            return None  # type: ignore[return-value]
        origin = tuple(float(expr.evaluate(component, values)) for component in connector_def.origin)
        connector = FakeConnector(
            name=connector_def.name,
            origin=origin,  # type: ignore[arg-type]
            basis_x=connector_def.basis_x,
            basis_y=connector_def.basis_y,
            width=float(values["Width"]),
            height=float(values["Height"]),
            host=host_element,
        )
        doc.connectors.append(connector)
        return connector

    def bind_connector_size(self, doc: FakeDoc, connector: FakeConnector, width_param: str, height_param: str) -> CapResult:
        for name in (width_param, height_param):
            if name not in doc.params:
                return api.failed(f"missing parameter {name}")
            if not doc.params[name].instance:
                return api.failed(f"{name} must be an instance parameter")
        connector.width_param = width_param
        connector.height_param = height_param
        return api.ok(f"{width_param}/{height_param}")

    def link_connectors(self, doc: FakeDoc, first: FakeConnector, second: FakeConnector) -> CapResult:
        if first is second:
            return api.failed("cannot link a connector to itself")
        first.linked = second
        second.linked = first
        return api.ok(f"{first.name} <-> {second.name}")

    # -- annotation -------------------------------------------------------- #
    def create_symbolic_line(self, doc: FakeDoc, symbol_def: Any, values: Dict[str, float]) -> CapResult:
        points = [tuple(float(expr.evaluate(c, values)) for c in p) for p in symbol_def.points]
        doc.symbolic.append({"detail": symbol_def.detail, "points": points})
        return api.ok(f"{len(points)}-point polyline ({symbol_def.detail})")

    # -- test helpers ------------------------------------------------------ #
    def flex(self, doc: FakeDoc, width: float, height: float) -> Dict[str, Any]:
        doc.params["Width"].default = float(width)
        doc.params["Height"].default = float(height)
        return doc.evaluate()


def _normal(connector: FakeConnector) -> Tuple[float, float, float]:
    ax, ay = connector.basis_x, connector.basis_y
    return (
        ax[1] * ay[2] - ax[2] * ay[1],
        ax[2] * ay[0] - ax[0] * ay[2],
        ax[0] * ay[1] - ax[1] * ay[0],
    )
