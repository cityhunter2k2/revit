"""The declarative family model: parameters, solids, connectors, symbols.

This module is Revit-agnostic on purpose.  It is the single source of truth
that both front-ends consume:

* ``revit_adapter.py`` turns the model into an actual ``.rfa`` through the
  Revit API,
* ``fake_revit.py`` turns it into an in-memory document so the build logic can
  be unit tested,
* ``preview.py`` renders it,
* ``verify.py`` flexes it over every catalogue size and checks the geometry.

Because every sketch coordinate is a :class:`~.lin.Lin` affine form of family
parameters, the model can be *proved* to be fully parametric: ``dimplan.py``
derives, for each profile, a complete chain of sketch dimensions whose labels
are real family parameters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import expr
from .geometry import Frame, FRAME_XY, FRAME_YZ, FRAME_ZX, FRAME_XZ, polygon_area
from .lin import Lin, Point2L, chain_strip, lin_from_expr, offset_chain, p2, p2_eval
from .spec import FamilyKind, thickness_tag

# --------------------------------------------------------------------------- #
# parameter definitions
# --------------------------------------------------------------------------- #
SPEC_LENGTH = "length"
SPEC_ANGLE = "angle"
SPEC_TEXT = "text"
SPEC_YESNO = "yesno"
SPEC_MATERIAL = "material"

WALL_THICKNESS_SPEC = (
    "if(and(Width <= 50 mm, Height <= 50 mm), 1 mm, "
    "if(and(Width <= 100 mm, Height <= 75 mm), 1.2 mm, "
    "if(and(Width <= 150 mm, Height <= 100 mm), 1.4 mm, 1.6 mm)))"
)

#: Same intent, transcribed from the published model codes (T10/T12/T14/T16).
#: Differs from the brief's formula only at 100 x 100 mm, see docs/02.
WALL_THICKNESS_CATALOGUE = (
    "if(and(Width <= 50 mm, Height <= 50 mm), 1 mm, "
    "if(and(Width <= 100 mm, Height <= 100 mm), 1.2 mm, "
    "if(and(Width <= 150 mm, Height <= 150 mm), 1.4 mm, 1.6 mm)))"
)

WALL_VARIANTS = {"spec": WALL_THICKNESS_SPEC, "catalogue": WALL_THICKNESS_CATALOGUE}

# Revit parameter groups (mapped to ForgeTypeId / BuiltInParameterGroup by the
# Revit adapter).
GROUP_DATA = "Data"
GROUP_DIMENSIONS = "Dimensions"
GROUP_GEOMETRY = "Geometry"
GROUP_MATERIALS = "Materials and Finishes"
GROUP_VISIBILITY = "Graphics"
GROUP_IDENTITY = "Identity Data"


@dataclass(frozen=True)
class ParamDef:
    name: str
    spec: str
    group: str
    formula: Optional[str] = None
    default: object = 0.0
    description: str = ""
    instance: bool = True  # hard requirement: every parameter is an instance param


@dataclass(frozen=True)
class SymbolicLineDef:
    frame_name: str
    points: Tuple[Tuple[str, str, str], ...]
    detail: str = "coarse"
    closed: bool = False
    description: str = ""


@dataclass(frozen=True)
class ConnectorDef:
    name: str  # 'Port_A' / 'Port_B'
    origin: Tuple[str, str, str]
    basis_x: Tuple[float, float, float]  # width direction
    basis_y: Tuple[float, float, float]  # height direction
    host_solid: str  # solid whose port face carries the connector
    width_param: str = "Width"
    height_param: str = "Height"


@dataclass(frozen=True)
class SolidDef:
    name: str
    subcategory: str
    material_param: str
    frame: Frame
    loops: Tuple[Tuple[Point2L, ...], ...]  # first loop = outer boundary
    start: str  # extrusion start offset expression (along frame normal)
    end: str  # extrusion end offset expression
    show_param: Optional[str] = None
    detail: str = "medium"
    description: str = ""
    is_cover: bool = False


# --------------------------------------------------------------------------- #
# parameter table
# --------------------------------------------------------------------------- #
def common_params(wall_variant: str = "spec", mitre: bool = True) -> List[ParamDef]:
    wall_formula = WALL_VARIANTS[wall_variant]
    params = [
        ParamDef(
            "Width",
            SPEC_LENGTH,
            GROUP_DIMENSIONS,
            default=100.0,
            description="電纜線槽標稱寬度 W (nominal tray width)",
        ),
        ParamDef(
            "Height",
            SPEC_LENGTH,
            GROUP_DIMENSIONS,
            default=50.0,
            description="電纜線槽標稱高度 H (nominal tray height)",
        ),
        ParamDef(
            "Stub",
            SPEC_LENGTH,
            GROUP_DIMENSIONS,
            default=75.0,
            description="直段長度 (straight stub length, 75 mm on the catalogue)",
        ),
        ParamDef(
            "Angle",
            SPEC_ANGLE,
            GROUP_DIMENSIONS,
            default=90.0,
            description="彎頭角度 (fixed 90 deg elbow)",
        ),
        ParamDef(
            "WallThickness",
            SPEC_LENGTH,
            GROUP_DIMENSIONS,
            formula=wall_formula,
            description="鋼板厚度 T10/T12/T14/T16, 依 W/H 自動計算",
        ),
        ParamDef("Half_Width", SPEC_LENGTH, GROUP_GEOMETRY, formula="Width / 2"),
        ParamDef("Half_Height", SPEC_LENGTH, GROUP_GEOMETRY, formula="Height / 2"),
        ParamDef(
            "Cover_Thickness",
            SPEC_LENGTH,
            GROUP_GEOMETRY,
            formula="WallThickness",
            description="蓋板厚度",
        ),
        ParamDef(
            "Cover_Overhang",
            SPEC_LENGTH,
            GROUP_GEOMETRY,
            formula="WallThickness * 2",
            description="蓋板外伸量 (cover overhang beyond the tray walls)",
        ),
        ParamDef(
            "Flange_Length",
            SPEC_LENGTH,
            GROUP_GEOMETRY,
            formula="20 mm",
            description="連接耳長度 (coupling collar length)",
        ),
        ParamDef(
            "Flange_Wrap",
            SPEC_LENGTH,
            GROUP_GEOMETRY,
            formula="WallThickness * 1.5",
            description="連接耳外包量 (collar wrap around the tray)",
        ),
        ParamDef(
            "Show_Cover",
            SPEC_YESNO,
            GROUP_VISIBILITY,
            default=True,
            description="顯示蓋板",
        ),
        ParamDef(
            "Show_Flanges",
            SPEC_YESNO,
            GROUP_VISIBILITY,
            default=True,
            description="顯示兩端連接耳 (Fine detail level only)",
        ),
        ParamDef(
            "Cover_Type",
            SPEC_TEXT,
            GROUP_IDENTITY,
            default="QT",
            description="蓋板形式 QT 中心肚臍 / ST 螺絲 / CT 夾片",
        ),
        ParamDef(
            "Tray_Material",
            SPEC_MATERIAL,
            GROUP_MATERIALS,
            default="Galvanised Steel",
            description="槽體材質",
        ),
        ParamDef(
            "Cover_Material",
            SPEC_MATERIAL,
            GROUP_MATERIALS,
            default="Galvanised Steel",
            description="蓋板材質",
        ),
    ]
    if mitre:
        params.append(
            ParamDef(
                "Mitre_Leg",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="Stub",
                description="45° 斜切倒角邊長 (mitre chamfer leg)",
            )
        )
    return params


def kind_params(kind: FamilyKind, wall_variant: str = "spec") -> List[ParamDef]:
    """Full instance-parameter table for one family kind."""
    params = common_params(wall_variant=wall_variant, mitre=kind.is_mitre)
    if kind.mode == "flat":
        params += [
            ParamDef("Arm_Half", SPEC_LENGTH, GROUP_GEOMETRY, formula="Half_Width"),
            ParamDef(
                "CenterToEnd",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="Half_Width + Stub",
                description="中心線交點至端口距離 (W/2 + 75)",
            ),
            ParamDef(
                "Outer_Edge_AB",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="CenterToEnd + Arm_Half",
                description="外邊長 A = B = W + 75",
            ),
            ParamDef("Base_Start", SPEC_LENGTH, GROUP_GEOMETRY, formula="-Half_Height"),
            ParamDef(
                "Base_End",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="-Half_Height + WallThickness",
            ),
            ParamDef(
                "Wall_Start",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="-Half_Height + WallThickness",
            ),
            ParamDef("Wall_End", SPEC_LENGTH, GROUP_GEOMETRY, formula="Half_Height"),
            ParamDef("Cover_Start", SPEC_LENGTH, GROUP_GEOMETRY, formula="Half_Height"),
            ParamDef(
                "Cover_End",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="Half_Height + Cover_Thickness",
            ),
            ParamDef("Flange_A_Start", SPEC_LENGTH, GROUP_GEOMETRY, formula="-CenterToEnd"),
            ParamDef(
                "Flange_A_End",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="-CenterToEnd + Flange_Length",
            ),
            ParamDef(
                "Flange_B_Start",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="CenterToEnd - Flange_Length",
            ),
            ParamDef("Flange_B_End", SPEC_LENGTH, GROUP_GEOMETRY, formula="CenterToEnd"),
        ]
        if kind.is_mitre:
            params.append(
                ParamDef(
                    "Mitre_Face_C",
                    SPEC_LENGTH,
                    GROUP_GEOMETRY,
                    formula="Mitre_Leg * 1.41421356",
                    description="斜角面長度 C = 75√2 ≈ 106",
                )
            )
    else:
        params += [
            ParamDef("Arm_Half", SPEC_LENGTH, GROUP_GEOMETRY, formula="Half_Height"),
            ParamDef(
                "CenterToEnd",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="Half_Height + Stub",
                description="中心線交點至端口距離 (H/2 + 75)",
            ),
            ParamDef(
                "Outer_Edge_DE",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="CenterToEnd + Arm_Half",
                description="外邊長 D = E = H + 75",
            ),
            ParamDef("Wall_Near_Start", SPEC_LENGTH, GROUP_GEOMETRY, formula="-Half_Width"),
            ParamDef(
                "Wall_Near_End",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="-Half_Width + WallThickness",
            ),
            ParamDef(
                "Wall_Far_Start",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="Half_Width - WallThickness",
            ),
            ParamDef("Wall_Far_End", SPEC_LENGTH, GROUP_GEOMETRY, formula="Half_Width"),
            ParamDef("Base_Start", SPEC_LENGTH, GROUP_GEOMETRY, formula="-Half_Width"),
            ParamDef("Base_End", SPEC_LENGTH, GROUP_GEOMETRY, formula="Half_Width"),
            ParamDef(
                "Cover_Start",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="-(Half_Width + Cover_Overhang)",
            ),
            ParamDef(
                "Cover_End",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="Half_Width + Cover_Overhang",
            ),
            ParamDef("Flange_A_Start", SPEC_LENGTH, GROUP_GEOMETRY, formula="-CenterToEnd"),
            ParamDef(
                "Flange_A_End",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="-CenterToEnd + Flange_Length",
            ),
            ParamDef(
                "Flange_B_Start",
                SPEC_LENGTH,
                GROUP_GEOMETRY,
                formula="CenterToEnd - Flange_Length",
            ),
            ParamDef("Flange_B_End", SPEC_LENGTH, GROUP_GEOMETRY, formula="CenterToEnd"),
        ]
        if kind.is_mitre:
            params.append(
                ParamDef(
                    "Mitre_Face_C",
                    SPEC_LENGTH,
                    GROUP_GEOMETRY,
                    formula="Mitre_Leg * 1.41421356",
                    description="斜角面長度 C = 75√2 ≈ 106",
                )
            )
    return params


class ParamSet:
    """Resolved parameter values (mm / degrees / bool / str) for one instance."""

    def __init__(self, defs: Sequence[ParamDef], overrides: Optional[Mapping[str, object]] = None):
        self.defs = list(defs)
        self.overrides = dict(overrides or {})
        self._by_name = {p.name: p for p in self.defs}
        self.values: Dict[str, object] = {}
        self._resolve([p.name for p in self.defs])

    def _resolve(self, names: Iterable[str]) -> None:
        for name in names:
            self.get(name)

    def get(self, name: str) -> object:
        if name in self.values:
            return self.values[name]
        if name in self.overrides:
            self.values[name] = self.overrides[name]
            return self.values[name]
        param = self._by_name.get(name)
        if param is None:
            raise KeyError(f"unknown parameter {name!r}")
        if param.formula:
            for dep in expr.dependencies(param.formula):
                self.get(dep)
            value = expr.evaluate(param.formula, self.values)
        else:
            value = param.default
        if param.spec == SPEC_YESNO:
            value = bool(value)
        elif param.spec in (SPEC_LENGTH, SPEC_ANGLE):
            value = float(value)
        self.values[name] = value
        return value

    def numbers(self) -> Dict[str, float]:
        """All numeric values (used by the affine-form evaluator)."""
        out: Dict[str, float] = {}
        for param in self.defs:
            value = self.get(param.name)
            if isinstance(value, bool):
                out[param.name] = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                out[param.name] = float(value)
            else:
                out[param.name] = 0.0
        return out

    def length(self, name: str) -> float:
        return float(self.get(name))

    def boolean(self, name: str) -> bool:
        return bool(self.get(name))

    def text(self, name: str) -> str:
        return str(self.get(name))

    def __getitem__(self, name: str) -> object:
        return self.get(name)

    def wall_thickness(self) -> float:
        return self.length("WallThickness")


# --------------------------------------------------------------------------- #
# silhouette helpers (symbolic)
# --------------------------------------------------------------------------- #
def outline_lin(half: Lin, center_to_end: Lin, mitre_leg: Optional[Lin]) -> List[Point2L]:
    h, c = half, center_to_end
    if mitre_leg is None:
        return [
            p2(-c, -h),
            p2(h, -h),
            p2(h, c),
            p2(-h, c),
            p2(-h, h),
            p2(-c, h),
        ]
    return [
        p2(-c, -h),
        p2(h - mitre_leg, -h),
        p2(h, -h + mitre_leg),
        p2(h, c),
        p2(-h, c),
        p2(-h, h),
        p2(-c, h),
    ]


def split_chains(points: Sequence[Point2L]) -> Tuple[List[Point2L], List[Point2L]]:
    """Return (convex chain, concave chain), both in counter-clockwise order.

    The port-end segments are trimmed off both chains.  That matters a lot: a
    strip built by offsetting a chain is offset *perpendicular to every
    segment*, so a chain that still contained the port edge would push the
    strip past the port plane (cover) or pull it short (inner wall).  Trimming
    them makes the strip end in a perpendicular cap that lies exactly on the
    port plane, i.e. flush with the connector - which is what the sheet shows.
    """
    n = len(points)
    if n == 7:  # mitre
        end = 3
    elif n == 6:  # sharp
        end = 2
    else:
        raise ValueError(f"unexpected silhouette with {n} vertices")
    convex = list(points[: end + 1])
    concave_longitudinal = list(points[end + 1 :])
    return convex, concave_longitudinal


def grow_outline_lin(
    half: Lin, center_to_end: Lin, mitre_leg: Optional[Lin], grow: Lin
) -> List[Point2L]:
    if mitre_leg is None:
        return outline_lin(half + grow, center_to_end, None)
    factor = 2.0 - math.sqrt(2.0)
    return outline_lin(half + grow, center_to_end, mitre_leg + grow * factor)


def ring_loop(
    u_half: Lin, v_half: Lin, wrap: Lin
) -> List[List[Point2L]]:
    """Rectangular collar ring: outer boundary + hole."""
    outer = [
        p2(-(u_half + wrap), -(v_half + wrap)),
        p2(u_half + wrap, -(v_half + wrap)),
        p2(u_half + wrap, v_half + wrap),
        p2(-(u_half + wrap), v_half + wrap),
    ]
    inner = [
        p2(-u_half, -v_half),
        p2(u_half, -v_half),
        p2(u_half, v_half),
        p2(-u_half, v_half),
    ]
    return [outer, inner]


# --------------------------------------------------------------------------- #
# family model
# --------------------------------------------------------------------------- #
#: The one and only family type of every delivered .rfa.
TYPE_NAME = "Standard"


@dataclass
class FamilyModel:
    kind: FamilyKind
    params: List[ParamDef]
    solids: List[SolidDef]
    connectors: List[ConnectorDef]
    symbols: List[SymbolicLineDef]
    subcategories: Dict[str, str]  # name -> material parameter
    wall_variant: str = "spec"
    type_names: Tuple[str, ...] = (TYPE_NAME,)

    # -- helpers ----------------------------------------------------------- #
    @property
    def name(self) -> str:
        return self.kind.filename.replace(".rfa", "")

    def param(self, name: str) -> ParamDef:
        for param in self.params:
            if param.name == name:
                return param
        raise KeyError(name)

    def base_values(self, width: float = 100.0, height: float = 50.0) -> ParamSet:
        return ParamSet(self.params, {"Width": width, "Height": height})

    def solid(self, name: str) -> SolidDef:
        for solid in self.solids:
            if solid.name == name:
                return solid
        raise KeyError(name)


CONNECTOR_FRAMES = {
    # name: (origin exprs, basis_x, basis_y)
    "Port_A": (("-CenterToEnd", "0", "0"), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "Port_B_flat": (("0", "CenterToEnd", "0"), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "Port_B_upright": (("0", "0", "CenterToEnd"), (0.0, -1.0, 0.0), (1.0, 0.0, 0.0)),
}

SYMBOL_FRAME_XY = "XY"
SYMBOL_FRAME_XZ = "XZ"


def build_model(kind: FamilyKind, wall_variant: str = "spec") -> FamilyModel:
    params = kind_params(kind, wall_variant=wall_variant)
    by_name = {p.name: p for p in params}

    def L(name: str) -> Lin:  # noqa: E743 - short local helper
        return Lin.of(name)

    def const(value: float) -> Lin:
        return Lin.const(value)

    half_arm = L("Arm_Half")
    c2e = L("CenterToEnd")
    wall = L("WallThickness")
    overhang = L("Cover_Overhang")
    cover_t = L("Cover_Thickness")
    wrap = L("Flange_Wrap")
    mitre_leg = L("Mitre_Leg") if kind.is_mitre else None

    outline = outline_lin(half_arm, c2e, mitre_leg)
    convex, concave = split_chains(outline)

    # offsetting needs concrete segment directions; every direction in these
    # profiles is parameter independent, so a reference evaluation is exact.
    reference = ParamSet(params, {"Width": 100.0, "Height": 50.0}).numbers()

    solids: List[SolidDef] = []
    if kind.mode == "flat":
        solids.append(
            SolidDef(
                name="Tray_Base",
                subcategory="Tray Body",
                material_param="Tray_Material",
                frame=FRAME_XY,
                loops=(tuple(outline),),
                start="Base_Start",
                end="Base_End",
                detail="medium",
                description="U 型槽體底板 (base plate)",
            )
        )
        solids.append(
            SolidDef(
                name="Tray_Wall_Outer",
                subcategory="Tray Body",
                material_param="Tray_Material",
                frame=FRAME_XY,
                loops=(tuple(chain_strip(convex, wall, reference)),),
                start="Wall_Start",
                end="Wall_End",
                detail="medium",
                description="外側槽壁 (outer wall, follows the convex chain)",
            )
        )
        solids.append(
            SolidDef(
                name="Tray_Wall_Inner",
                subcategory="Tray Body",
                material_param="Tray_Material",
                frame=FRAME_XY,
                loops=(tuple(chain_strip(concave, wall, reference)),),
                start="Wall_Start",
                end="Wall_End",
                detail="medium",
                description="內側槽壁 (inner wall, follows the concave chain)",
            )
        )
        solids.append(
            SolidDef(
                name="Cover",
                subcategory="Cover",
                material_param="Cover_Material",
                frame=FRAME_XY,
                loops=(tuple(grow_outline_lin(half_arm, c2e, mitre_leg, overhang)),),
                start="Cover_Start",
                end="Cover_End",
                show_param="Show_Cover",
                detail="medium",
                description="蓋板 (front opening cover, sits on +Z)",
                is_cover=True,
            )
        )
    else:  # upright
        # side walls: the full silhouette, one plate on each side of the tray
        solids.append(
            SolidDef(
                name="Wall_Near",
                subcategory="Tray Body",
                material_param="Tray_Material",
                frame=FRAME_XZ,
                loops=(tuple(outline),),
                start="Wall_Near_Start",
                end="Wall_Near_End",
                detail="medium",
                description="槽壁 (side wall at +Y)",
            )
        )
        solids.append(
            SolidDef(
                name="Wall_Far",
                subcategory="Tray Body",
                material_param="Tray_Material",
                frame=FRAME_XZ,
                loops=(tuple(outline),),
                start="Wall_Far_Start",
                end="Wall_Far_End",
                detail="medium",
                description="槽壁 (side wall at -Y)",
            )
        )
        bottom_chain = convex if kind.bottom_side == "convex" else concave
        cover_chain = concave if kind.cover_side == "concave" else convex
        solids.append(
            SolidDef(
                name="Tray_Base",
                subcategory="Tray Body",
                material_param="Tray_Material",
                frame=FRAME_XZ,
                loops=(tuple(chain_strip(bottom_chain, wall, reference)),),
                start="Base_Start",
                end="Base_End",
                detail="medium",
                description="U 型槽體底板 (base strip on the %s side)" % kind.bottom_side,
            )
        )
        solids.append(
            SolidDef(
                name="Cover",
                subcategory="Cover",
                material_param="Cover_Material",
                frame=FRAME_XZ,
                loops=(tuple(chain_strip(cover_chain, -cover_t, reference)),),
                start="Cover_Start",
                end="Cover_End",
                show_param="Show_Cover",
                detail="medium",
                description="蓋板 (cover on the %s side)" % kind.cover_side,
                is_cover=True,
            )
        )

    # -- coupling collars (連接耳) ---------------------------------------- #
    if kind.mode == "flat":
        flange_a = ring_loop(L("Half_Width"), L("Half_Height"), wrap)
        flange_b = ring_loop(L("Half_Height"), L("Half_Width"), wrap)
        frame_a, frame_b = FRAME_YZ, FRAME_ZX
    else:
        flange_a = ring_loop(L("Half_Width"), L("Half_Height"), wrap)
        flange_b = ring_loop(L("Half_Height"), L("Half_Width"), wrap)
        frame_a, frame_b = FRAME_YZ, FRAME_XY

    solids.append(
        SolidDef(
            name="Flange_Port_A",
            subcategory="Flange",
            material_param="Tray_Material",
            frame=frame_a,
            loops=tuple(tuple(loop) for loop in flange_a),
            start="Flange_A_Start",
            end="Flange_A_End",
            show_param="Show_Flanges",
            detail="fine",
            description="端口 A 連接耳 (coupling collar, Fine detail only)",
        )
    )
    solids.append(
        SolidDef(
            name="Flange_Port_B",
            subcategory="Flange",
            material_param="Tray_Material",
            frame=frame_b,
            loops=tuple(tuple(loop) for loop in flange_b),
            start="Flange_B_Start",
            end="Flange_B_End",
            show_param="Show_Flanges",
            detail="fine",
            description="端口 B 連接耳 (coupling collar, Fine detail only)",
        )
    )

    # -- connectors -------------------------------------------------------- #
    port_b_key = "Port_B_flat" if kind.mode == "flat" else "Port_B_upright"
    connectors = [
        ConnectorDef(
            name="Port_A",
            origin=CONNECTOR_FRAMES["Port_A"][0],
            basis_x=CONNECTOR_FRAMES["Port_A"][1],
            basis_y=CONNECTOR_FRAMES["Port_A"][2],
            host_solid="Flange_Port_A",
        ),
        ConnectorDef(
            name="Port_B",
            origin=CONNECTOR_FRAMES[port_b_key][0],
            basis_x=CONNECTOR_FRAMES[port_b_key][1],
            basis_y=CONNECTOR_FRAMES[port_b_key][2],
            host_solid="Flange_Port_B",
        ),
    ]

    # -- coarse symbolic centerline --------------------------------------- #
    if kind.mode == "flat":
        symbols = [
            SymbolicLineDef(
                frame_name=SYMBOL_FRAME_XY,
                points=(
                    ("-CenterToEnd", "0", "0"),
                    ("0", "0", "0"),
                    ("0", "CenterToEnd", "0"),
                ),
                detail="coarse",
                description="粗略 LOD 單線 (plan centerline)",
            )
        ]
    else:
        symbols = [
            SymbolicLineDef(
                frame_name=SYMBOL_FRAME_XZ,
                points=(
                    ("-CenterToEnd", "0", "0"),
                    ("0", "0", "0"),
                    ("0", "0", "CenterToEnd"),
                ),
                detail="coarse",
                description="粗略 LOD 單線 (elevation centerline)",
            )
        ]

    subcategories = {
        "Tray Body": "Tray_Material",
        "Cover": "Cover_Material",
        "Flange": "Tray_Material",
    }

    # normalise loop orientation once, using the reference size: outer loops
    # counter-clockwise, holes clockwise.  Revit copes with either, but a
    # deterministic order keeps the previews and the face checks honest.
    import dataclasses

    normalised: List[SolidDef] = []
    for solid in solids:
        loops = []
        for index, loop in enumerate(solid.loops):
            pts = list(loop)
            area = polygon_area([p2_eval(point, reference) for point in pts])
            if (area >= 0) != (index == 0):
                pts = list(reversed(pts))
            loops.append(tuple(pts))
        normalised.append(dataclasses.replace(solid, loops=tuple(loops)))
    solids = normalised

    model = FamilyModel(
        kind=kind,
        params=params,
        solids=solids,
        connectors=connectors,
        symbols=symbols,
        subcategories=subcategories,
        wall_variant=wall_variant,
    )
    validate_model(model)
    return model


def validate_model(model: FamilyModel) -> None:
    """Fail fast on structural mistakes (called by every front-end)."""
    names = {p.name for p in model.params}
    for param in model.params:
        if not param.instance:
            raise ValueError(f"{param.name}: only instance parameters are allowed")
        if param.formula:
            if not expr.checks_out(param.formula):
                raise ValueError(f"{param.name}: formula does not parse: {param.formula}")
            for dep in expr.dependencies(param.formula):
                if dep not in names:
                    raise ValueError(f"{param.name}: formula references unknown {dep}")
    seen = set()
    for solid in model.solids:
        if solid.name in seen:
            raise ValueError(f"duplicate solid {solid.name}")
        seen.add(solid.name)
        if not solid.loops:
            raise ValueError(f"{solid.name}: no profile loops")
        for label in (solid.start, solid.end):
            for dep in expr.dependencies(label) if _is_formula(label) else []:
                if dep not in names:
                    raise ValueError(f"{solid.name}: references unknown {dep}")
        if solid.subcategory not in model.subcategories:
            raise ValueError(f"{solid.name}: unknown subcategory {solid.subcategory}")
    for conn in model.connectors:
        if conn.host_solid not in seen:
            raise ValueError(f"{conn.name}: unknown host solid")
    ids = {p.name for p in model.params}
    if "Width" not in ids or "Height" not in ids:
        raise ValueError("Width/Height parameters are mandatory")


def _is_formula(text: str) -> bool:
    return any(ch.isalpha() or ch == "_" for ch in text)
