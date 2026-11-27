"""Preview/rendering smoke tests (the images are part of the documentation)."""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking import pncanvas  # noqa: E402
from trunking.evaluate import evaluate_model, evaluate_params  # noqa: E402
from trunking.model import build_model  # noqa: E402
from trunking.spec import FAMILY_KINDS  # noqa: E402


class TestCanvas(unittest.TestCase):
    def test_png_magic_and_size(self):
        canvas = pncanvas.Canvas(40, 30, (255, 255, 255))
        pncanvas.draw_text(canvas, 2, 2, "OK", (0, 0, 0), 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "canvas.png")
            canvas.save(path)
            with open(path, "rb") as handle:
                data = handle.read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (40, 30))

    def test_polygon_fill_respects_the_outline(self):
        canvas = pncanvas.Canvas(10, 10, (255, 255, 255))
        canvas.fill_polygon([(2, 2), (8, 2), (8, 8), (2, 8)], (0, 0, 0))
        self.assertEqual(canvas.get(5, 5), (0, 0, 0))
        self.assertEqual(canvas.get(0, 0), (255, 255, 255))


class TestRenders(unittest.TestCase):
    def test_every_family_renders_without_errors(self):
        import preview

        for kind in FAMILY_KINDS:
            model = build_model(kind)
            evaluated = evaluate_model(model, evaluate_params(model, 100, 50))
            canvas = pncanvas.Canvas(320, 240, (255, 255, 255))
            preview.render_plane(canvas, evaluated, (4, 4, 300, 220), "silhouette")
            preview.render_axo(canvas, evaluated, (4, 4, 300, 220), 35.0, 25.0, "axo")
            self.assertTrue(any(value != 255 for value in canvas.pixels))


if __name__ == "__main__":
    unittest.main()
