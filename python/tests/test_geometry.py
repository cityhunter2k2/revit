"""Geometry kernel tests: silhouette, mitre chamfer, flush strips, prisms."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking import geometry
from trunking.geometry import (  # noqa: E402
    FRAME_XY,
    elbow_outline,
    polygon_area,
    polygon_self_intersects,
    prism_is_watertight,
    prism_signed_volume,
)
from trunking.lin import Lin, chain_strip, offset_chain, p2, p2_eval  # noqa: E402
from trunking.model import outline_lin, split_chains  # noqa: E402


class TestSilhouette(unittest.TestCase):
    def test_sharp_outline_is_ccw_and_simple(self):
        points = elbow_outline(50, 125, None)
        self.assertEqual(len(points), 6)
        self.assertGreater(polygon_area(points), 0)
        self.assertFalse(polygon_self_intersects(points))

    def test_mitre_outline_has_45_degree_face(self):
        points = elbow_outline(50, 125, 75)
        self.assertEqual(len(points), 7)
        self.assertFalse(polygon_self_intersects(points))
        diagonals = [
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(points, points[1:] + points[:1])
            if abs(b[0] - a[0]) > 1e-9 and abs(b[1] - a[1]) > 1e-9
        ]
        self.assertEqual(len(diagonals), 1)
        self.assertAlmostEqual(diagonals[0], 75 * math.sqrt(2), places=6)

    def test_mitre_rejects_impossible_chamfers(self):
        with self.assertRaises(ValueError):
            elbow_outline(25, 100, 126)  # leg runs past the port plane
        with self.assertRaises(ValueError):
            elbow_outline(25, 100, 4 * 25 + 1)  # leg would cut the concave corner
        with self.assertRaises(ValueError):
            elbow_outline(50, 125, 0)

    def test_chains_are_trimmed_at_the_ports(self):
        points = elbow_outline(50, 125, 75)
        convex, concave = split_chains([p2(u, v) for u, v in points])
        self.assertEqual(len(convex), 4)
        self.assertEqual(len(concave), 3)
        # the concave chain must no longer contain the port-end segments
        concave_values = [(p[0].k, p[1].k) for p in concave]
        self.assertIn((-50.0, 125.0), concave_values)
        self.assertIn((-125.0, 50.0), concave_values)

    def test_strip_is_flush_with_the_ports(self):
        """A strip built from the trimmed chain never crosses a port plane."""
        for arm_half, c2e, leg in ((25, 100, 75), (50, 125, 75), (100, 175, 75), (50, 125, None)):
            elbow_outline(arm_half, c2e, leg)
            chain = outline_lin(Lin.of("a"), Lin.of("c"), Lin.of("l") if leg else None)
            _, concave = split_chains(chain)
            values = {"a": arm_half, "c": c2e, "l": leg or 0.0}
            strip = chain_strip(concave, Lin.of("t"), values)
            for u, v in strip:
                self.assertGreaterEqual(u.evaluate(values | {"t": 1.6}), -c2e - 1e-6)
                self.assertLessEqual(v.evaluate(values | {"t": 1.6}), c2e + 1e-6)
            pts = [p2_eval(point, values | {"t": 1.6}) for point in strip]
            self.assertGreater(polygon_area(pts), 0)
            self.assertFalse(polygon_self_intersects(pts))

    def test_offset_chain_distance(self):
        chain = [p2(0, 0), p2(100, 0)]
        values = {}
        offset = offset_chain(chain, Lin.const(10), values)
        self.assertEqual([p[1].k for p in offset], [10, 10])

    def test_symbolic_offset_matches_the_numeric_kernel(self):
        """The symbolic offsets must agree with geometry.offset_chain exactly."""
        chains = (
            [(-125.0, -50.0), (50.0, -50.0), (50.0, 125.0)],
            [(-50.0, 125.0), (-50.0, 50.0), (-125.0, 50.0)],
            [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)],
        )
        for chain in chains:
            symbolic = [p2(u, v) for u, v in chain]
            got = [p2_eval(point, {}) for point in offset_chain(symbolic, Lin.const(1.2), {})]
            want = geometry.offset_chain(chain, 1.2)
            self.assertEqual(len(got), len(want), chain)
            for actual, expected in zip(got, want):
                self.assertAlmostEqual(actual[0], expected[0], places=6)
                self.assertAlmostEqual(actual[1], expected[1], places=6)

    def test_wall_strip_is_a_simple_polygon(self):
        """The strip used to come back as a bow-tie: 4th point on the 1st edge."""
        chain = [p2(-125, -50), p2(50, -50), p2(50, 125)]
        strip = chain_strip(chain, Lin.const(1.2), {})
        points = [p2_eval(point, {}) for point in strip]
        self.assertEqual(len(points), 6)
        self.assertFalse(polygon_self_intersects(points))

    def test_a_vertex_lying_on_another_edge_is_not_simple(self):
        """This is the exact bow-tie the offset bug produced."""
        bowtie = [
            (-125.0, -50.0),
            (50.0, -50.0),
            (50.0, 125.0),
            (48.8, -50.0),
            (48.8, -48.8),
            (-125.0, -48.8),
        ]
        self.assertTrue(polygon_self_intersects(bowtie))

    def test_collinear_vertices_are_still_simple(self):
        with_collinear = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        self.assertFalse(polygon_self_intersects(with_collinear))


class TestPrisms(unittest.TestCase):
    def test_watertight_and_volume(self):
        loop = [(0, 0), (100, 0), (100, 50), (0, 50)]
        bottom = [FRAME_XY.to_world(u, v, 0.0) for u, v in reversed(loop)]
        top = [FRAME_XY.to_world(u, v, 10.0) for u, v in loop]
        faces = [bottom, top]
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            faces.append(
                [
                    FRAME_XY.to_world(a[0], a[1], 0.0),
                    FRAME_XY.to_world(b[0], b[1], 0.0),
                    FRAME_XY.to_world(b[0], b[1], 10.0),
                    FRAME_XY.to_world(a[0], a[1], 10.0),
                ]
            )
        self.assertTrue(prism_is_watertight(faces))
        self.assertAlmostEqual(abs(prism_signed_volume(faces)), 100 * 50 * 10, places=6)


if __name__ == "__main__":
    unittest.main()
