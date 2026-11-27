#!/usr/bin/env python3
"""Render documentation previews of the six trunking families.

    python3 preview.py                 # writes docs/preview/*.png
    python3 preview.py --out DIR

The previews come from the *same* :mod:`trunking` model the Revit builders
consume, so they double as a visual check of the geometry: silhouette, mitre
chamfer, cover side, collar placement and connector frames.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from typing import Dict, List, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trunking.evaluate import EvaluatedModel, EvaluatedSolid, evaluate_model, evaluate_params  # noqa: E402
from trunking.model import FamilyModel, build_model  # noqa: E402
from trunking.pncanvas import Canvas, Color, draw_text, text_width  # noqa: E402
from trunking.spec import FAMILY_KINDS, FamilyKind  # noqa: E402

BODY = (116, 147, 178)
COVER = (222, 148, 74)
FLANGE = (150, 150, 155)
EDGE = (35, 42, 50)
CENTER = (196, 62, 62)
TEXT = (40, 44, 50)
MUTED = (120, 126, 134)
PANEL = (247, 248, 250)
GRID = (214, 218, 224)

LIGHT = (0.42, -0.36, 0.83)


class Camera:
    def __init__(self, az: float, el: float) -> None:
        az_r, el_r = math.radians(az), math.radians(el)
        self.direction = (
            math.cos(el_r) * math.cos(az_r),
            math.cos(el_r) * math.sin(az_r),
            math.sin(el_r),
        )
        self.right = (-math.sin(az_r), math.cos(az_r), 0.0)
        self.up = (
            -math.sin(el_r) * math.cos(az_r),
            -math.sin(el_r) * math.sin(az_r),
            math.cos(el_r),
        )

    def project(self, point: Sequence[float]) -> Tuple[float, float, float]:
        sx = sum(p * r for p, r in zip(point, self.right))
        sy = -sum(p * u for p, u in zip(point, self.up))
        depth = sum(p * d for p, d in zip(point, self.direction))
        return sx, sy, depth


def _fit(points: Sequence[Tuple[float, float]], rect: Tuple[int, int, int, int], margin: int = 16):
    x, y, w, h = rect
    if not points:
        return lambda p: (x + w / 2.0, y + h / 2.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span_x = max(max(xs) - min(xs), 1e-6)
    span_y = max(max(ys) - min(ys), 1e-6)
    scale = min((w - 2 * margin) / span_x, (h - 2 * margin) / span_y)
    cx = (max(xs) + min(xs)) / 2.0
    cy = (max(ys) + min(ys)) / 2.0

    def transform(p: Tuple[float, float]) -> Tuple[float, float]:
        return (x + w / 2.0 + (p[0] - cx) * scale, y + h / 2.0 + (p[1] - cy) * scale)

    return transform


def _shade(colour: Color, factor: float) -> Color:
    return tuple(max(0, min(255, int(c * factor))) for c in colour)  # type: ignore[return-value]


def _face_normal(face: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    ax = [face[1][i] - face[0][i] for i in range(3)]
    bx = [face[2][i] - face[0][i] for i in range(3)]
    n = (
        ax[1] * bx[2] - ax[2] * bx[1],
        ax[2] * bx[0] - ax[0] * bx[2],
        ax[0] * bx[1] - ax[1] * bx[0],
    )
    length = math.sqrt(sum(c * c for c in n)) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)


# --------------------------------------------------------------------------- #
# panels
# --------------------------------------------------------------------------- #
def panel(canvas: Canvas, rect: Tuple[int, int, int, int], title: str = "") -> None:
    x, y, w, h = rect
    canvas.rect(x, y, w, h, PANEL)
    canvas.draw_line((x, y), (x + w, y), GRID, 1.0)
    canvas.draw_line((x, y + h), (x + w, y + h), GRID, 1.0)
    canvas.draw_line((x, y), (x, y + h), GRID, 1.0)
    canvas.draw_line((x + w, y), (x + w, y + h), GRID, 1.0)
    if title:
        draw_text(canvas, x + 10, y + 8, title, TEXT, 2)


def render_axo(
    canvas: Canvas,
    evaluated: EvaluatedModel,
    rect: Tuple[int, int, int, int],
    az: float = 218.0,
    el: float = 24.0,
    title: str = "",
) -> None:
    panel(canvas, rect, title)
    cam = Camera(az, el)
    faces = []
    wire: List[Tuple[Tuple[float, float], Tuple[float, float], Color]] = []
    points: List[Tuple[float, float]] = []

    for solid in evaluated.solids.values():
        if not solid.visible:
            continue
        colour = COVER if solid.is_cover else (FLANGE if solid.subcategory == "Flange" else BODY)
        if solid.subcategory == "Flange":
            for loop in solid.loops:
                for offset in (solid.start, solid.end):
                    pts = [cam.project(solid.frame.to_world(u, v, offset)) for u, v in loop.points]
                    for i in range(len(pts)):
                        wire.append((pts[i], pts[(i + 1) % len(pts)], FLANGE))
                        points.append((pts[i][0], pts[i][1]))
            continue
        for face in solid.all_faces():
            proj = [cam.project(p) for p in face]
            normal = _face_normal(face)
            light = sum(n * l for n, l in zip(normal, LIGHT))
            faces.append(
                (
                    sum(p[2] for p in proj) / len(proj),
                    proj,
                    colour,
                    0.62 + 0.38 * max(0.0, light),
                )
            )
            points.extend((p[0], p[1]) for p in proj)

    transform = _fit(points, (rect[0], rect[1] + 22, rect[2], rect[3] - 22))
    for depth, proj, colour, shade in sorted(faces, key=lambda item: item[0]):
        pts = [transform((p[0], p[1])) for p in proj]
        canvas.fill_polygon(pts, _shade(colour, shade))
        for i in range(len(pts)):
            canvas.draw_line(pts[i], pts[(i + 1) % len(pts)], EDGE, 1.0)
    for a, b, colour in wire:
        canvas.draw_line(transform((a[0], a[1])), transform((b[0], b[1])), colour, 1.2)


def _plane_view_axes(kind: FamilyKind) -> Tuple[int, int]:
    """World axes used for the in-plane silhouette view."""
    return (0, 1) if kind.mode == "flat" else (0, 2)


def render_plane(
    canvas: Canvas,
    evaluated: EvaluatedModel,
    rect: Tuple[int, int, int, int],
    title: str = "",
    show_dimensions: bool = True,
) -> None:
    panel(canvas, rect, title)
    ax, ay = _plane_view_axes(evaluated.model.kind)
    # the silhouette lives in the band's frame: project through the band axis
    solids = [s for s in evaluated.solids.values() if s.name in ("Tray_Base",) or s.subcategory == "Flange"]
    base = evaluated.solids["Tray_Base"]
    frame = base.frame

    def to2d(point: Sequence[float]) -> Tuple[float, float]:
        u = sum(point[i] * frame.ex[i] for i in range(3))
        v = sum(point[i] * frame.ey[i] for i in range(3))
        return (u, -v)  # screen y grows downwards

    points: List[Tuple[float, float]] = []
    polys: List[Tuple[List[Tuple[float, float]], Tuple[int, int, int], float]] = []
    for solid in evaluated.solids.values():
        if not solid.visible:
            continue
        if solid.subcategory == "Flange":
            for loop in solid.loops:
                pts = [to2d(solid.frame.to_world(u, v, solid.start)) for u, v in loop.points]
                polys.append((pts, FLANGE, 0.35))
                points.extend(pts)
            continue
        if solid.name in ("Tray_Base", "Cover"):
            for loop in solid.loops:
                pts = [to2d(solid.frame.to_world(u, v, solid.start)) for u, v in loop.points]
                colour = COVER if solid.is_cover else BODY
                polys.append((pts, colour, 0.30 if solid.is_cover else 0.55))
                points.extend(pts)

    transform = _fit(points, (rect[0], rect[1] + 22, rect[2], rect[3] - 22))
    for pts, colour, alpha in polys:
        canvas.fill_polygon([transform(p) for p in pts], colour, alpha)
        tp = [transform(p) for p in pts]
        for i in range(len(tp)):
            canvas.draw_line(tp[i], tp[(i + 1) % len(tp)], EDGE, 1.0)

    # centreline
    for symbol in evaluated.symbols:
        pts = [transform(to2d(p)) for p in symbol]
        for a, b in zip(pts[:-1], pts[1:]):
            canvas.dashed(a, b, CENTER, 1.2)

    # connector frames: draw the port cross-section tick in the view plane
    for conn in evaluated.connectors.values():
        origin = to2d(conn.origin)
        for basis, extent in ((conn.basis_x, conn.width / 2.0), (conn.basis_y, conn.height / 2.0)):
            sx = sum(basis[i] * frame.ex[i] for i in range(3))
            sy = -sum(basis[i] * frame.ey[i] for i in range(3))
            norm = math.hypot(sx, sy)
            if norm < 0.5:  # this basis is the port normal - it points out of the view
                continue
            sx, sy = sx / norm, sy / norm
            a = transform((origin[0] - extent * sx, origin[1] - extent * sy))
            b = transform((origin[0] + extent * sx, origin[1] + extent * sy))
            canvas.draw_line(a, b, (30, 120, 200), 2.0)
            draw_text(
                canvas,
                max(6, int(b[0]) - 6),
                int(b[1]) - 16,
                conn.name.replace("Port_", "P"),
                (30, 120, 200),
                1,
            )

    if show_dimensions:
        c2e = evaluated.length("CenterToEnd")
        outer = evaluated.length("Outer_Edge_AB") if evaluated.model.kind.mode == "flat" else evaluated.length("Outer_Edge_DE")
        arm_half = evaluated.length("Arm_Half")
        start = transform((0.0, 0.0))
        # pivot to port A
        canvas.dashed(start, transform((-c2e, 0.0)), MUTED, 1.0, 4, 4)
        draw_text(
            canvas,
            max(10, rect[0] + 10),
            rect[1] + rect[3] - 20,
            "C2E %d" % round(c2e),
            MUTED,
            1,
        )
        draw_text(
            canvas,
            max(10, rect[0] + 10),
            rect[1] + rect[3] - 34,
            "A/B %d  W %d H %d  T %.1f" % (round(outer), round(evaluated.length("Width")), round(evaluated.length("Height")), evaluated.length("WallThickness")),
            MUTED,
            1,
        )


# --------------------------------------------------------------------------- #
# documents
# --------------------------------------------------------------------------- #
def build_all(wall_variant: str = "spec") -> Dict[str, FamilyModel]:
    return {kind.key: build_model(kind, wall_variant=wall_variant) for kind in FAMILY_KINDS}


OVERVIEW_SIZES = ((50.0, 50.0), (100.0, 75.0), (200.0, 150.0))


def render_overview(models: Dict[str, FamilyModel], path: str, sizes=OVERVIEW_SIZES) -> None:
    col_w, row_h = 430, 300
    width = 250 + col_w * len(sizes) + 30
    height = 60 + row_h * len(FAMILY_KINDS) + 30
    canvas = Canvas(width, height, (255, 255, 255))
    draw_text(canvas, 20, 18, "TRUNKING 90 DEG ELBOW FAMILIES - SINGLE TYPE, ALL SIZES", TEXT, 2)

    for row, kind in enumerate(FAMILY_KINDS):
        model = models[kind.key]
        y = 55 + row * row_h
        draw_text(canvas, 12, y + 10, kind.bend.upper(), TEXT, 2)
        draw_text(canvas, 12, y + 32, kind.opening.upper(), MUTED, 2)
        draw_text(canvas, 12, y + 56, kind.routing_slot, MUTED, 1)
        for col, size in enumerate(sizes):
            values = evaluate_params(model, size[0], size[1])
            evaluated = evaluate_model(model, values)
            rect = (250 + col * col_w, y, col_w - 12, row_h - 16)
            render_axo(
                canvas,
                evaluated,
                rect,
                az=214.0 if kind.mode == "flat" else 232.0,
                el=26.0 if kind.mode == "flat" else 18.0,
                title="%d x %d" % (round(values["Width"]), round(values["Height"])),
            )
    canvas.save(path)


def render_family(model: FamilyModel, path: str, size=(200.0, 100.0)) -> None:
    values = evaluate_params(model, size[0], size[1])
    evaluated = evaluate_model(model, values)
    canvas = Canvas(1240, 620, (255, 255, 255))
    draw_text(canvas, 20, 16, model.kind.filename, TEXT, 2)
    draw_text(canvas, 20, 42, model.kind.title + "  |  " + model.kind.routing_slot, MUTED, 1)
    render_plane(canvas, evaluated, (16, 70, 600, 530), "IN-PLANE SILHOUETTE (MM)")
    render_axo(canvas, evaluated, (630, 70, 596, 530), 218, 24, "AXONOMETRIC")
    canvas.save(path)


def render_flex_sheet(model: FamilyModel, path: str, sizes: Sequence[Tuple[float, float]]) -> None:
    cols = 4
    cell_w, cell_h = 300, 240
    rows = (len(sizes) + cols - 1) // cols
    canvas = Canvas(20 + cols * cell_w, 60 + rows * cell_h, (255, 255, 255))
    draw_text(canvas, 16, 16, "FLEX CHECK - ONE TYPE, %d SIZES" % len(sizes), TEXT, 2)
    for index, (w, h) in enumerate(sizes):
        col, row = index % cols, index // cols
        values = evaluate_params(model, w, h)
        evaluated = evaluate_model(model, values)
        rect = (12 + col * cell_w, 50 + row * cell_h, cell_w - 12, cell_h - 14)
        render_plane(
            canvas,
            evaluated,
            rect,
            "%d x %d  T%.1f" % (w, h, values["WallThickness"]),
            show_dimensions=False,
        )
    canvas.save(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "preview"))
    parser.add_argument("--wall-variant", default="spec", choices=("spec", "catalogue"))
    args = parser.parse_args(argv)

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    models = build_all(args.wall_variant)
    render_overview(models, os.path.join(out, "families-overview.png"))
    for kind in FAMILY_KINDS:
        model = models[kind.key]
        render_family(model, os.path.join(out, f"{kind.key}.png"))
    render_flex_sheet(
        models["mitre_front"],
        os.path.join(out, "flex-mitre-front.png"),
        [(50, 50), (75, 50), (100, 75), (100, 100), (150, 100), (150, 150), (200, 150), (200, 200), (300, 100), (50, 100)],
    )
    print(f"previews written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
