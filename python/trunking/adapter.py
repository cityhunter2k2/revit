"""Front-end contract shared by the real Revit adapter and the fake one.

The build pipeline (:mod:`.builder`) only ever talks to this interface, which is
what lets the exact same build code be unit tested without Revit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

OK = "OK"
FALLBACK = "FALLBACK"
SKIPPED = "SKIPPED"
FAILED = "FAILED"


@dataclass
class CapResult:
    """Outcome of one capability probe / API call."""

    status: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK

    @property
    def failed(self) -> bool:
        return self.status == FAILED

    def __str__(self) -> str:
        return f"{self.status}: {self.message}" if self.message else self.status


def ok(message: str = "") -> CapResult:
    return CapResult(OK, message)


def fallback(message: str) -> CapResult:
    return CapResult(FALLBACK, message)


def skipped(message: str) -> CapResult:
    return CapResult(SKIPPED, message)


def failed(message: str) -> CapResult:
    return CapResult(FAILED, message)


@dataclass
class LabelRequest:
    """One sketch dimension to create, with the geometry needed to place it."""

    solid: str
    loop: int
    axis: str
    label: str
    ref_kind: str  # 'line' | 'rp'
    target_a: Tuple[float, float, float]
    target_b: Tuple[float, float, float]
    ref_a: Optional[Tuple[float, float, float]]
    ref_b: Optional[Tuple[float, float, float]]
    ref_plane: Optional[str]  # RP_X0 / RP_Y0 / RP_Z0
    expected: float
    ref_point: Optional[Tuple[float, float, float]] = None

    @property
    def target_mid(self) -> Tuple[float, float, float]:
        return _mid(self.target_a, self.target_b)

    @property
    def ref_mid(self) -> Tuple[float, float, float]:
        if self.ref_point is not None:
            return self.ref_point
        if self.ref_a is None or self.ref_b is None:
            return self.target_mid
        return _mid(self.ref_a, self.ref_b)


def _mid(a, b):
    return tuple((x + y) / 2.0 for x, y in zip(a, b))


@dataclass
class BuildStep:
    name: str
    result: CapResult
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.name}: {self.result}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class BuiltFamily:
    filename: str
    path: str = ""
    type_count: int = 0
    parameter_count: int = 0
    connector_count: int = 0
    solid_count: int = 0
    dimension_count: int = 0
    part_type: str = ""
    document: Any = None


@dataclass
class BuildReport:
    family: str
    steps: List[BuildStep] = field(default_factory=list)
    capabilities: Dict[str, CapResult] = field(default_factory=dict)
    built: Optional[BuiltFamily] = None
    warnings: List[str] = field(default_factory=list)

    def add(self, name: str, result: CapResult, detail: str = "") -> CapResult:
        self.steps.append(BuildStep(name, result, detail))
        return result

    def add_capability(self, name: str, result: CapResult) -> CapResult:
        self.capabilities[name] = result
        if result.status == FALLBACK:
            self.warnings.append(f"{name}: {result.message}")
        return result

    @property
    def failures(self) -> List[BuildStep]:
        steps = [s for s in self.steps if s.result.failed]
        steps += [
            BuildStep(name, result, "capability")
            for name, result in self.capabilities.items()
            if result.failed
        ]
        return steps

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        counts: Dict[str, int] = {}
        for step in self.steps:
            counts[step.result.status] = counts.get(step.result.status, 0) + 1
        parts = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        return f"{self.family}: {parts}"


class RevitAdapter:
    """Abstract adapter.  Every method documents the Revit API call it wraps."""

    # -- diagnostics ------------------------------------------------------- #
    name = "abstract"

    def log(self, message: str) -> None:  # pragma: no cover - overridden
        pass

    # -- document ---------------------------------------------------------- #
    def open_family_template(self, template_path: str, destination: str) -> Any:
        raise NotImplementedError

    def save_family(self, doc: Any, path: str) -> CapResult:
        raise NotImplementedError

    def close_family(self, doc: Any) -> None:
        raise NotImplementedError

    def regenerate(self, doc: Any) -> None:
        raise NotImplementedError

    # -- family manager ---------------------------------------------------- #
    def family_type_count(self, doc: Any) -> int:
        raise NotImplementedError

    def ensure_single_type(self, doc: Any, name: str) -> CapResult:
        """Rename the template's single type to ``Standard`` - never add one."""
        raise NotImplementedError

    def parameter_names(self, doc: Any) -> Sequence[str]:
        raise NotImplementedError

    def add_instance_parameter(self, doc: Any, definition: Any) -> CapResult:
        raise NotImplementedError

    def set_formula(self, doc: Any, name: str, formula: str) -> CapResult:
        raise NotImplementedError

    def set_value(self, doc: Any, name: str, value: Any) -> CapResult:
        raise NotImplementedError

    # -- categories / materials ------------------------------------------- #
    def ensure_subcategory(self, doc: Any, name: str) -> CapResult:
        raise NotImplementedError

    def ensure_material(self, doc: Any, name: str) -> Any:
        raise NotImplementedError

    def ensure_cable_tray_fitting_category(self, doc: Any) -> CapResult:
        """``FamilyCategory`` = ``OST_CableTrayFitting``."""
        raise NotImplementedError

    def set_part_type(self, doc: Any, part_type: str = "Elbow") -> CapResult:
        """``FAMILY_CONTENT_PART_TYPE`` -> Elbow (probed, several API paths)."""
        raise NotImplementedError

    # -- geometry ---------------------------------------------------------- #
    def create_extrusion(
        self,
        doc: Any,
        solid_def: Any,
        loops: Sequence[Sequence[Tuple[float, float]]],
        start: float,
        end: float,
    ) -> Any:
        raise NotImplementedError

    def associate_extrusion_offsets(
        self, doc: Any, element: Any, start_param: str, end_param: str
    ) -> CapResult:
        """Bind ``EXTRUSION_START_PARAM`` / ``EXTRUSION_END_PARAM`` to family params."""
        raise NotImplementedError

    def apply_sketch_dimensions(
        self, doc: Any, element: Any, requests: Sequence[Any], values: Dict[str, float]
    ) -> CapResult:
        """Label the profile's dimensions so the sketch flexes with the parameters."""
        raise NotImplementedError

    def set_detail_visibility(self, doc: Any, element: Any, detail: str) -> CapResult:
        raise NotImplementedError

    def associate_visibility(self, doc: Any, element: Any, show_param: str) -> CapResult:
        raise NotImplementedError

    def set_element_material(self, doc: Any, element: Any, material_param: str, material: Any) -> CapResult:
        raise NotImplementedError

    # -- connectors -------------------------------------------------------- #
    def create_cable_tray_connector(
        self, doc: Any, connector_def: Any, values: Dict[str, float], host_element: Any
    ) -> Any:
        raise NotImplementedError

    def bind_connector_size(self, doc: Any, connector: Any, width_param: str, height_param: str) -> CapResult:
        raise NotImplementedError

    def link_connectors(self, doc: Any, first: Any, second: Any) -> CapResult:
        raise NotImplementedError

    # -- annotation -------------------------------------------------------- #
    def create_symbolic_line(self, doc: Any, symbol_def: Any, values: Dict[str, float]) -> CapResult:
        raise NotImplementedError
