"""Formula engine tests: the parameter table must be provably evaluable."""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking import expr  # noqa: E402
from trunking.model import WALL_THICKNESS_CATALOGUE, WALL_THICKNESS_SPEC  # noqa: E402
from trunking.spec import DRAWING_TABLE  # noqa: E402


class TestFormulaEngine(unittest.TestCase):
    def test_units(self):
        self.assertAlmostEqual(expr.evaluate("75 mm", {}), 75.0)
        self.assertAlmostEqual(expr.evaluate("1.2cm", {}), 12.0)
        self.assertAlmostEqual(expr.evaluate("2 m", {}), 2000.0)
        self.assertAlmostEqual(expr.evaluate("90 deg", {}), 90.0)

    def test_arithmetic_and_functions(self):
        env = {"Stub": 75.0}
        self.assertAlmostEqual(expr.evaluate("Stub * sqrt(2)", env), 75 * math.sqrt(2))
        self.assertAlmostEqual(expr.evaluate("Stub / 2 + 25 mm", env), 62.5)
        self.assertAlmostEqual(expr.evaluate("round(Stub * 1.41421, 2)", env), 106.07)

    def test_conditionals(self):
        formula = "if(and(Width <= 50 mm, Height <= 50 mm), 1 mm, 2 mm)"
        self.assertAlmostEqual(expr.evaluate(formula, {"Width": 50.0, "Height": 50.0}), 1.0)
        self.assertAlmostEqual(expr.evaluate(formula, {"Width": 75.0, "Height": 50.0}), 2.0)

    def test_dependencies(self):
        self.assertEqual(expr.dependencies("if(Width > Height, Stub, 0 mm)"), ["Width", "Height", "Stub"])

    def test_errors(self):
        with self.assertRaises(expr.FormulaError):
            expr.evaluate("Width +", {"Width": 1.0})
        with self.assertRaises(expr.FormulaError):
            expr.evaluate("Unknown * 2", {})
        with self.assertRaises(expr.FormulaError):
            expr.evaluate("1 mm / 0", {})

    def test_wall_thickness_spec_formula_matches_sheet_for_standard_sizes(self):
        """The brief's formula is authoritative; document where it departs from T-codes."""
        mismatches = []
        for row in DRAWING_TABLE:
            value = expr.evaluate(WALL_THICKNESS_SPEC, {"Width": row.width, "Height": row.height})
            if abs(value - row.wall_mm) > 1e-9:
                mismatches.append((row.size, value, row.wall_mm))
        self.assertEqual(mismatches, [((100, 100), 1.4, 1.2), ((150, 150), 1.6, 1.4)])

    def test_wall_thickness_catalogue_variant_reproduces_every_t_code(self):
        for row in DRAWING_TABLE:
            value = expr.evaluate(WALL_THICKNESS_CATALOGUE, {"Width": row.width, "Height": row.height})
            self.assertAlmostEqual(value, row.wall_mm, msg=f"{row.size}")


if __name__ == "__main__":
    unittest.main()
