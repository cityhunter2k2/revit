"""Catalogue data and family definitions for the cable-trunking fittings.

All data transcribed from the manufacturer sheet
``Trunking21 - 25v2_09.jpg`` (page 8: "Cable trunking - Fittings and
accessories 電線槽曲及配件").

The sheet publishes, for every nominal size W x H:

    A, B  outer edge lengths of the two arms, in plan (front opening) -
          also the vertical-arm edge lengths for D/E on the vertical
          opening types,
    C     mitre face length (mitre bend) / inner straight stub (sharp bend),
    D, E  outer edge lengths of the two arms for the vertical bend types,

    W x H     A     B     C(mitre)  C(sharp)  D     E
    50 x 50   125   125   106       75        125   125
    75 x 50   150   150   106       75        125   125
    75 x 75   150   150   106       75        150   150
    100 x 75  175   175   106       75        150   150
    100 x 100 175   175   106       75        175   175
    150 x 100 225   225   106       75        175   175
    150 x 150 225   225   106       75        225   225
    200 x 150 275   275   106       75        225   225
    200 x 200 275   275   106       75        275   275

which is exactly

    A = B = W + 75           (front opening  -> CenterToEnd = W/2 + 75)
    D = E = H + 75           (internal / external opening -> CenterToEnd = H/2 + 75)
    C_mitre  = 75 * sqrt(2)  = 106.07            (45 deg mitre face)
    C_sharp  = 75                                (inner straight stub)

and the wall-thickness / model-code column (T10, T12, T14, T16).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

# Model code -> nominal size, e.g. "2X2" == 50x50 (code unit = 25 mm).
MODEL_CODE_UNIT_MM = 25.0

#: The nine catalogue sizes plus the two non-standard sizes required by the
#: acceptance test (section 5 of the brief).
STANDARD_SIZES: Tuple[Tuple[float, float], ...] = (
    (50, 50),
    (75, 50),
    (75, 75),
    (100, 75),
    (100, 100),
    (150, 100),
    (150, 150),
    (200, 150),
    (200, 200),
)
CUSTOM_SIZES: Tuple[Tuple[float, float], ...] = ((300, 100), (50, 100))
FLEX_SIZES: Tuple[Tuple[float, float], ...] = STANDARD_SIZES + CUSTOM_SIZES


@dataclass(frozen=True)
class DrawingRow:
    """One row of the published dimension tables."""

    width: float
    height: float
    a: float
    b: float
    c_mitre: float
    c_sharp: float
    d: float
    e: float
    wall_mm: float
    model_code: str

    @property
    def size(self) -> Tuple[float, float]:
        return (self.width, self.height)


#: Verbatim transcription of the two published tables, merged.
DRAWING_TABLE: Tuple[DrawingRow, ...] = (
    DrawingRow(50, 50, 125, 125, 106, 75, 125, 125, 1.0, "2X2"),
    DrawingRow(75, 50, 150, 150, 106, 75, 125, 125, 1.2, "3X2"),
    DrawingRow(75, 75, 150, 150, 106, 75, 150, 150, 1.2, "3X3"),
    DrawingRow(100, 75, 175, 175, 106, 75, 150, 150, 1.2, "4X3"),
    DrawingRow(100, 100, 175, 175, 106, 75, 175, 175, 1.2, "4X4"),
    DrawingRow(150, 100, 225, 225, 106, 75, 175, 175, 1.4, "6X4"),
    DrawingRow(150, 150, 225, 225, 106, 75, 225, 225, 1.4, "6X6"),
    DrawingRow(200, 150, 275, 275, 106, 75, 225, 225, 1.6, "8X6"),
    DrawingRow(200, 200, 275, 275, 106, 75, 275, 275, 1.6, "8X8"),
)

DRAWING_BY_SIZE: Dict[Tuple[float, float], DrawingRow] = {row.size: row for row in DRAWING_TABLE}


def model_code(width: float, height: float) -> str:
    """Trunking model code, e.g. 300x100 -> "12X4T14"."""
    w_code = int(round(width / MODEL_CODE_UNIT_MM))
    h_code = int(round(height / MODEL_CODE_UNIT_MM))
    return f"{w_code}X{h_code}"


def thickness_tag(wall_mm: float) -> str:
    """1.0 -> 'T10', 1.2 -> 'T12' (as printed in the model-code column)."""
    return "T%d" % int(round(wall_mm * 10))


# --------------------------------------------------------------------------- #
# The six families
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FamilyKind:
    """Static definition of one of the six deliverables."""

    key: str
    filename: str
    title: str
    bend: str  # 'mitre' | 'sharp'
    opening: str  # 'front' | 'internal' | 'external'
    mode: str  # 'flat' | 'upright'
    routing_slot: str
    drawing_label: str

    @property
    def is_mitre(self) -> bool:
        return self.bend == "mitre"

    @property
    def is_upright(self) -> bool:
        """True for the two vertical-bend families (in-plane width == tray height)."""
        return self.mode == "upright"

    @property
    def cover_side(self) -> str:
        """Which in-plane chain carries the cover (upright families only)."""
        if self.mode != "upright":
            return "top"
        return "concave" if self.opening == "internal" else "convex"

    @property
    def bottom_side(self) -> str:
        if self.mode != "upright":
            return "bottom"
        return "convex" if self.opening == "internal" else "concave"


FAMILY_KINDS: Tuple[FamilyKind, ...] = (
    FamilyKind(
        key="mitre_front",
        filename="Trunking_90_MitreBend_FrontOpening.rfa",
        title="90° 斜角槽曲 - 正面蓋型",
        bend="mitre",
        opening="front",
        mode="flat",
        routing_slot="Horizontal Bend",
        drawing_label="90° Mitre bend 正面蓋型",
    ),
    FamilyKind(
        key="mitre_internal",
        filename="Trunking_90_MitreBend_InternalOpening.rfa",
        title="90° 斜角槽曲 - 內開蓋型",
        bend="mitre",
        opening="internal",
        mode="upright",
        routing_slot="Vertical Inside Bend",
        drawing_label="90° Mitre bend 內開蓋型",
    ),
    FamilyKind(
        key="mitre_external",
        filename="Trunking_90_MitreBend_ExternalOpening.rfa",
        title="90° 斜角槽曲 - 外開蓋型",
        bend="mitre",
        opening="external",
        mode="upright",
        routing_slot="Vertical Outside Bend",
        drawing_label="90° Mitre bend 外開蓋型",
    ),
    FamilyKind(
        key="sharp_front",
        filename="Trunking_90_SharpBend_FrontOpening.rfa",
        title="90° 死角槽曲 - 正面蓋型",
        bend="sharp",
        opening="front",
        mode="flat",
        routing_slot="Horizontal Bend",
        drawing_label="90° Sharp bend 正面蓋型",
    ),
    FamilyKind(
        key="sharp_internal",
        filename="Trunking_90_SharpBend_InternalOpening.rfa",
        title="90° 死角槽曲 - 內開蓋型",
        bend="sharp",
        opening="internal",
        mode="upright",
        routing_slot="Vertical Inside Bend",
        drawing_label="90° Sharp bend 內開蓋型",
    ),
    FamilyKind(
        key="sharp_external",
        filename="Trunking_90_SharpBend_ExternalOpening.rfa",
        title="90° 死角槽曲 - 外開蓋型",
        bend="sharp",
        opening="external",
        mode="upright",
        routing_slot="Vertical Outside Bend",
        drawing_label="90° Sharp bend 外開蓋型",
    ),
)

KIND_BY_KEY: Dict[str, FamilyKind] = {kind.key: kind for kind in FAMILY_KINDS}


def kinds() -> Iterable[FamilyKind]:
    return FAMILY_KINDS
