#!/usr/bin/env python3
"""Draw the pyRevit ribbon icons for the Trunking extension.

Run after changing the palette; the PNGs are committed so pyRevit never needs
this script at runtime:

    python3 python/make_icons.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trunking.pncanvas import Canvas, draw_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(ROOT, "Trunking.extension", "Trunking.tab", "Trunking.panel")

STEEL = (94, 124, 152)
STEEL_DARK = (66, 92, 116)
COVER = (214, 138, 62)
COVER_DARK = (176, 108, 40)
PAPER = (255, 255, 255)
INK = (38, 46, 54)
MUTED = (128, 138, 148)


def _poly(canvas, points, colour, outline=None):
    canvas.fill_polygon(points, colour)
    if outline:
        for index in range(len(points)):
            canvas.draw_line(points[index], points[(index + 1) % len(points)], outline, 2.0)


def draw_elbow(path: str, accent=COVER, label=None, badge=None) -> None:
    """A 96x96 ribbon icon: one mitred elbow in isometric, optional badge."""
    canvas = Canvas(96, 96, PAPER)
    # ground shadow
    canvas.fill_polygon([(12, 78), (84, 78), (78, 84), (18, 84)], (232, 236, 240))
    # outer face of the vertical arm (left) and the horizontal arm (right)
    _poly(canvas, [(20, 26), (44, 18), (44, 66), (20, 74)], STEEL, STEEL_DARK)
    _poly(canvas, [(44, 66), (76, 74), (76, 30), (44, 18)], STEEL_DARK, INK)
    # top faces (cover)
    _poly(canvas, [(20, 26), (44, 18), (60, 22), (36, 30)], accent, COVER_DARK)
    _poly(canvas, [(36, 30), (60, 22), (76, 30), (52, 38)], accent, COVER_DARK)
    # inner shadow line at the mitre
    canvas.draw_line((44, 18), (44, 66), INK, 1.5)
    canvas.draw_line((44, 66), (76, 74), INK, 1.5)
    if label:
        draw_text(canvas, 6, 84, label, MUTED, 1)
    if badge:
        canvas.fill_polygon([(62, 56), (92, 56), (92, 84), (62, 84)], (255, 255, 255))
        draw_text(canvas, 66, 66, badge, INK, 2)
    canvas.save(path)


def draw_verify(path: str) -> None:
    """Same elbow, plus a green tick - the "flex check" button."""
    canvas = Canvas(96, 96, PAPER)
    _poly(canvas, [(10, 26), (34, 18), (34, 56), (10, 64)], STEEL, STEEL_DARK)
    _poly(canvas, [(34, 56), (58, 63), (58, 31), (34, 18)], STEEL_DARK, INK)
    _poly(canvas, [(10, 26), (34, 18), (48, 22), (24, 30)], COVER, COVER_DARK)
    tick = (46, 142, 78)
    canvas.draw_line((50, 62), (62, 78), tick, 7.0)
    canvas.draw_line((62, 78), (90, 36), tick, 7.0)
    canvas.save(path)


def draw_check_setup(path: str) -> None:
    """Magnifier over a small elbow - the environment check button."""
    canvas = Canvas(96, 96, PAPER)
    _poly(canvas, [(8, 30), (30, 23), (30, 56), (8, 63)], STEEL, STEEL_DARK)
    _poly(canvas, [(30, 56), (50, 62), (50, 34), (30, 23)], STEEL_DARK, INK)
    _poly(canvas, [(8, 30), (30, 23), (42, 27), (20, 34)], COVER, COVER_DARK)
    ring = (46, 96, 160)
    for radius, thick in ((22, 5), (15, 4)):
        steps = 60
        for index in range(steps):
            a0 = 6.2831853 * index / steps
            a1 = 6.2831853 * (index + 1) / steps
            canvas.draw_line(
                (60 + radius * __import__("math").cos(a0), 44 + radius * __import__("math").sin(a0)),
                (60 + radius * __import__("math").cos(a1), 44 + radius * __import__("math").sin(a1)),
                ring,
                thick,
            )
    canvas.draw_line((68, 58), (88, 84), ring, 7.0)
    canvas.save(path)


def main() -> int:
    if not os.path.isdir(PANEL):
        print("extension folder missing: %s" % PANEL)
        return 2
    targets = [
        (os.path.join(PANEL, "icon.png"), dict(accent=COVER, badge="90")),
        (
            os.path.join(PANEL, "Build Families.pushbutton", "icon.png"),
            dict(accent=COVER, label="RFA"),
        ),
        (
            os.path.join(PANEL, "Verify Families.pushbutton", "icon.png"),
            dict(accent=COVER, label="CHK"),
        ),
        (
            os.path.join(PANEL, "Check Setup.pushbutton", "icon.png"),
            dict(accent=COVER, label="ENV"),
        ),
    ]
    for path, kwargs in targets:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        draw_elbow(path, **kwargs)
        print("wrote %s" % path)
    verify_icon = os.path.join(PANEL, "Verify Families.pushbutton", "icon.png")
    draw_verify(verify_icon)
    print("wrote %s (verify)" % verify_icon)
    setup_icon = os.path.join(PANEL, "Check Setup.pushbutton", "icon.png")
    draw_check_setup(setup_icon)
    print("wrote %s (setup)" % setup_icon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
