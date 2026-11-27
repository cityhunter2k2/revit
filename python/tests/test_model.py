"""Model tests: catalogue consistency, parameter rules, solids and connectors."""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking import expr  # noqa: E402
from trunking.evaluate import evaluate_model, evaluate_params  # noqa: E402
from trunking.model import build_model, validate_model  # noqa: E402
from trunking.spec import (  # noqa: E402
    DRAWING_TABLE,
    FAMILY_KINDS,
    FLEX_SIZES,
    KIND_BY_KEY,
    STANDARD_SIZES,
    model_code,
)


class TestCatalogue(unittest.TestCase):
    def test_nine_catalogue_sizes(self):
        self.assertEqual(len(STANDARD_SIZES), 9)
        self.assertEqual(len(FLEX_SIZES), 11)

    def test_published_dimensions_follow_the_formulas(self):
        for row in DRAWING_TABLE:
            self.assertAlmostEqual(row.a, row.width + 75.0, msg=str(row.size))
            self.assertAlmostEqual(row.b, row.width + 75.0, msg=str(row.size))
            self.assertAlmostEqual(row.d, row.height + 75.0, msg=str(row.size))
            self.assertAlmostEqual(row.e, row.height + 75.0, msg=str(row.size))
            self.assertEqual(row.c_sharp, 75.0)
            self.assertAlmostEqual(row.c_mitre, 106.0, delta=0.5)

    def test_model_codes(self):
        self.assertEqual(model_code(50, 50), "2X2")
        self.assertEqual(model_code(200, 150), "8X6")


class TestParameters(unittest.TestCase):
    def test_every_parameter_is_an_instance_parameter(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            self.assertTrue(model.params)
            for param in model.params:
                self.assertTrue(param.instance, f"{kind.key}:{param.name} must be an instance parameter")

    def test_formulas_parse_and_resolve(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            names = {p.name for p in model.params}
            for param in model.params:
                if not param.formula:
                    continue
                self.assertTrue(expr.checks_out(param.formula), f"{kind.key}:{param.name}")
                for dep in expr.dependencies(param.formula):
                    self.assertIn(dep, names, f"{kind.key}:{param.name} -> {dep}")

    def test_width_dependent_formulas_carry_no_size_literals(self):
        """No per-size lookup: A/B/C come from Width/Height through arithmetic only."""
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            by_name = {p.name: p for p in model.params}
            for name in ("CenterToEnd", "Half_Width", "Half_Height"):
                self.assertIn(name, by_name)
                self.assertIsNotNone(by_name[name].formula, f"{kind.key}:{name}")
            for name in ("CenterToEnd", "Half_Width", "Half_Height", "Mitre_Leg", "Mitre_Face_C"):
                if name not in by_name:
                    continue
                self.assertIsNotNone(by_name[name].formula, f"{kind.key}:{name}")
                self.assertIsNone(
                    re.search(r"\d+\s*(mm|cm|m)\b", by_name[name].formula),
                    f"{kind.key}:{name} has a literal size",
                )
            self.assertFalse(any(re.fullmatch(r"\d+x\d+", p.name) for p in model.params))

    def test_parameter_set_is_identical_for_every_size(self):
        """The one type must not branch on size - same parameters, same formulas."""
        for kind in FAMILY_KINDS:
            first = build_model(kind)
            second = build_model(kind)
            self.assertEqual(
                [(p.name, p.formula) for p in first.params],
                [(p.name, p.formula) for p in second.params],
            )

    def test_center_to_end_formula(self):
        front = build_model(KIND_BY_KEY["mitre_front"])
        upright = build_model(KIND_BY_KEY["mitre_internal"])
        for width, height in FLEX_SIZES:
            for model, expected in (
                (front, width / 2.0 + 75.0),
                (upright, height / 2.0 + 75.0),
            ):
                values = evaluate_params(model, width, height)
                self.assertAlmostEqual(values["CenterToEnd"], expected, places=9)

    def test_mitre_face_c(self):
        for key in ("mitre_front", "mitre_internal", "mitre_external"):
            model = build_model(KIND_BY_KEY[key])
            for width, height in FLEX_SIZES:
                values = evaluate_params(model, width, height)
                self.assertAlmostEqual(values["Mitre_Face_C"], 75 * 2 ** 0.5, places=6)

    def test_model_validation_rejects_type_parameters(self):
        model = build_model(KIND_BY_KEY["sharp_front"])
        import dataclasses

        broken = list(model.params)
        broken[0] = dataclasses.replace(broken[0], instance=False)
        model.params = broken
        with self.assertRaises(ValueError):
            validate_model(model)


class TestSolids(unittest.TestCase):
    def test_solids_and_connectors(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            names = [solid.name for solid in model.solids]
            self.assertIn("Tray_Base", names)
            self.assertIn("Cover", names)
            self.assertIn("Flange_Port_A", names)
            self.assertIn("Flange_Port_B", names)
            self.assertEqual(len(model.connectors), 2)
            self.assertEqual({c.name for c in model.connectors}, {"Port_A", "Port_B"})

    def test_each_family_has_six_solids_and_one_cover(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            self.assertEqual(len(model.solids), 6)
            self.assertEqual(sum(1 for s in model.solids if s.is_cover), 1)

    def test_cover_and_base_are_on_the_documented_sides(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            cover = model.solid("Cover")
            if kind.mode == "flat":
                self.assertGreater(float(expr.evaluate(cover.start, evaluate_params(model, 100, 50))), 0)
            else:
                self.assertEqual(kind.cover_side, "concave" if kind.opening == "internal" else "convex")
                self.assertEqual(kind.bottom_side, "convex" if kind.opening == "internal" else "concave")

    def test_connector_frames_are_orthonormal_and_outward(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            values = evaluate_params(model, 100, 50)
            evaluated = evaluate_model(model, values)
            for name, conn in evaluated.connectors.items():
                dot = sum(a * b for a, b in zip(conn.basis_x, conn.basis_y))
                self.assertAlmostEqual(dot, 0.0, places=9)
                for basis in (conn.basis_x, conn.basis_y, conn.normal):
                    self.assertAlmostEqual(sum(c * c for c in basis), 1.0, places=9)
            a, b = evaluated.connectors["Port_A"], evaluated.connectors["Port_B"]
            self.assertAlmostEqual(a.normal[0], -1.0, places=9)  # port A always faces -X
            if kind.mode == "flat":
                self.assertAlmostEqual(b.normal[1], 1.0, places=9)
            else:
                self.assertAlmostEqual(b.normal[2], 1.0, places=9)

    def test_geometry_volumes_are_positive_for_all_sizes(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            for width, height in FLEX_SIZES:
                evaluated = evaluate_model(model, evaluate_params(model, width, height))
                for solid in evaluated.solids.values():
                    self.assertGreater(solid.volume, 0.0, f"{kind.key}:{solid.name} {width}x{height}")


if __name__ == "__main__":
    unittest.main()
