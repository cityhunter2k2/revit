"""Evaluate a :class:`~.model.FamilyModel` into concrete millimetre geometry.

Used by the verifier, by the preview renderer and by the fake Revit document.
Everything is in millimetres in a right-handed frame whose origin is the
pivot of the elbow (intersection of the two tray centrelines).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import expr
from .geometry import Frame, prism_signed_volume, prism_is_watertight, polygon_area
from .lin import Lin, Point2L, p2_eval
from .model import FamilyModel, SolidDef, ConnectorDef, SymbolicLineDef

Point2 = Tuple[float, float]
Point3 = Tuple[float, float, float]


@dataclass
class EvaluatedLoop:
    points: List[Point2]
    area: float

    @property
    def ccw(self) -> bool:
        return self.area >= 0


@dataclass
class EvaluatedSolid:
    name: str
    frame: Frame
    loops: List[EvaluatedLoop]
    start: float
    end: float
    detail: str
    subcategory: str
    material_param: str
    show_param: Optional[str]
    visible: bool
    is_cover: bool
    description: str = ""

    @property
    def depth(self) -> float:
        return abs(self.end - self.start)

    @property
    def net_area(self) -> float:
        """Outer area minus holes (always positive)."""
        if not self.loops:
            return 0.0
        return abs(self.loops[0].area) - sum(abs(loop.area) for loop in self.loops[1:])

    @property
    def volume(self) -> float:
        return self.net_area * self.depth

    def face_loops_3d(self) -> List[List[Point3]]:
        """Outward oriented 3D boundary loops (holes are skipped)."""
        if len(self.loops) != 1:
            # annular collar: report both faces of the ring, bridged clockwise
            outer = self._face(self.loops[0], self.start, inverted=True)
            top = self._face(self.loops[0], self.end, inverted=False)
            return [outer, top]
        return [
            self._face(self.loops[0], self.start, inverted=True),
            self._face(self.loops[0], self.end, inverted=False),
        ]

    def _face(self, loop: EvaluatedLoop, offset: float, inverted: bool) -> List[Point3]:
        pts = loop.points if not inverted else list(reversed(loop.points))
        return [self.frame.to_world(u, v, offset) for u, v in pts]

    def side_faces(self) -> List[List[Point3]]:
        """Side quads of the prism (hole-free loops only)."""
        faces: List[List[Point3]] = []
        for loop in self.loops:
            pts = loop.points
            n = len(pts)
            for i in range(n):
                u1, v1 = pts[i]
                u2, v2 = pts[(i + 1) % n]
                faces.append(
                    [
                        self.frame.to_world(u1, v1, self.start),
                        self.frame.to_world(u2, v2, self.start),
                        self.frame.to_world(u2, v2, self.end),
                        self.frame.to_world(u1, v1, self.end),
                    ]
                )
        return faces

    def all_faces(self) -> List[List[Point3]]:
        return self.face_loops_3d() + self.side_faces()

    def bbox(self) -> Tuple[Point3, Point3]:
        pts: List[Point3] = []
        for loop in self.loops:
            for u, v in loop.points:
                pts.append(self.frame.to_world(u, v, self.start))
                pts.append(self.frame.to_world(u, v, self.end))
        lo = tuple(min(p[i] for p in pts) for i in range(3))
        hi = tuple(max(p[i] for p in pts) for i in range(3))
        return lo, hi  # type: ignore[return-value]

    def contains_point(self, point: Point3, tol: float = 1e-6) -> bool:
        """Inside test for the prism (hole-free loops)."""
        n = self.frame.normal
        rel = [point[i] - self.frame.origin[i] for i in range(3)]
        offset = sum(rel[i] * n[i] for i in range(3))
        lo, hi = min(self.start, self.end), max(self.start, self.end)
        if offset < lo - tol or offset > hi + tol:
            return False
        u = sum(rel[i] * self.frame.ex[i] for i in range(3))
        v = sum(rel[i] * self.frame.ey[i] for i in range(3))
        return _point_in_loop((u, v), self.loops[0].points)


def _point_in_loop(point: Point2, loop: Sequence[Point2]) -> bool:
    x, y = point
    inside = False
    n = len(loop)
    for i in range(n):
        x1, y1 = loop[i]
        x2, y2 = loop[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_at = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x_at > x:
                inside = not inside
    return inside


@dataclass
class EvaluatedConnector:
    name: str
    origin: Point3
    basis_x: Point3
    basis_y: Point3
    width: float
    height: float
    host_solid: str

    @property
    def normal(self) -> Point3:
        ax, ay = self.basis_x, self.basis_y
        return (
            ax[1] * ay[2] - ax[2] * ay[1],
            ax[2] * ay[0] - ax[0] * ay[2],
            ax[0] * ay[1] - ax[1] * ay[0],
        )

    def corners(self) -> List[Point3]:
        """The four corners of the connector rectangle, in world space."""
        out = []
        hw, hh = self.width / 2.0, self.height / 2.0
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            out.append(
                tuple(
                    self.origin[i] + su * hw * self.basis_x[i] + sv * hh * self.basis_y[i]
                    for i in range(3)
                )
            )
        return out  # type: ignore[return-value]


@dataclass
class EvaluatedModel:
    model: FamilyModel
    values: Dict[str, object]
    solids: Dict[str, EvaluatedSolid]
    connectors: Dict[str, EvaluatedConnector]
    symbols: List[List[Point3]]

    def length(self, name: str) -> float:
        return float(self.values[name])  # type: ignore[arg-type]

    def boolean(self, name: str) -> bool:
        return bool(self.values[name])

    def text(self, name: str) -> str:
        return str(self.values[name])


def evaluate_solid(solid: SolidDef, values: Mapping[str, float], visible: bool = True) -> EvaluatedSolid:
    loops: List[EvaluatedLoop] = []
    for loop in solid.loops:
        pts = [p2_eval(point, values) for point in loop]
        loops.append(EvaluatedLoop(points=pts, area=polygon_area(pts)))
    start = float(expr.evaluate(solid.start, values))
    end = float(expr.evaluate(solid.end, values))
    return EvaluatedSolid(
        name=solid.name,
        frame=solid.frame,
        loops=loops,
        start=start,
        end=end,
        detail=solid.detail,
        subcategory=solid.subcategory,
        material_param=solid.material_param,
        show_param=solid.show_param,
        visible=visible,
        is_cover=solid.is_cover,
        description=solid.description,
    )


def evaluate_model(model: FamilyModel, values: Mapping[str, object]) -> EvaluatedModel:
    numbers = {k: (1.0 if v is True else 0.0 if v is False else float(v) if isinstance(v, (int, float)) else 0.0)
               for k, v in values.items()}
    solids: Dict[str, EvaluatedSolid] = {}
    for solid in model.solids:
        visible = True
        if solid.show_param:
            visible = bool(values.get(solid.show_param, True))
        solids[solid.name] = evaluate_solid(solid, numbers, visible=visible)

    connectors: Dict[str, EvaluatedConnector] = {}
    for conn in model.connectors:
        origin = tuple(float(expr.evaluate(comp, numbers)) for comp in conn.origin)
        connectors[conn.name] = EvaluatedConnector(
            name=conn.name,
            origin=origin,  # type: ignore[arg-type]
            basis_x=conn.basis_x,
            basis_y=conn.basis_y,
            width=float(values.get(conn.width_param, 0.0)),  # type: ignore[arg-type]
            height=float(values.get(conn.height_param, 0.0)),  # type: ignore[arg-type]
            host_solid=conn.host_solid,
        )

    symbols: List[List[Point3]] = []
    for symbol in model.symbols:
        pts = [tuple(float(expr.evaluate(c, numbers)) for c in point) for point in symbol.points]
        symbols.append(pts)  # type: ignore[arg-type]

    return EvaluatedModel(model=model, values=dict(values), solids=solids, connectors=connectors, symbols=symbols)


def evaluate_params(model: FamilyModel, width: float, height: float) -> Dict[str, object]:
    param_set = model.base_values(width, height)
    return {p.name: param_set.get(p.name) for p in model.params}
