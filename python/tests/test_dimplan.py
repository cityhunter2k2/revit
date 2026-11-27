"""Dimension-plan tests - the proof that one type covers every size."""

import os
import sys
import math
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking.dimplan import build_plan, lin_to_formula, match_param, param_lins, reference_values  # noqa: E402
from trunking.lin import Lin  # noqa: E402
from trunking.model import ParamSet, build_model  # noqa: E402
from trunking.spec import FAMILY_KINDS, FLEX_SIZES  # noqa: E402


class TestDimPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = [(kind, build_model(kind)) for kind in FAMILY_KINDS]
        cls.plans = {kind.key: build_plan(model) for kind, model in cls.entries}

    def test_every_label_is_a_family_parameter(self):
        for kind, model in self.entries:
            names = {p.name for p in model.params}
            for entry in self.plans[kind.key].entries:
                self.assertIn(entry.label, names, f"{kind.key}:{entry.solid}")

    def test_synthesised_parameters_have_formulas_and_are_instance(self):
        for kind, model in self.entries:
            plan = self.plans[kind.key]
            self.assertTrue(plan.synthesised, f"{kind.key}: expected derived parameters")
            for param in plan.synthesised:
                self.assertTrue(param.formula)
                self.assertTrue(param.instance)

    def test_plan_is_exact_for_every_size(self):
        """measured distance == parameter value, for all 11 sizes, all dims."""
        for kind, model in self.entries:
            plan = self.plans[kind.key]
            for width, height in FLEX_SIZES:
                values = ParamSet(model.params, {"Width": width, "Height": height})
                numbers = values.numbers()
                for entry in plan.entries:
                    loop = model.solid(entry.solid).loops[entry.loop]
                    measured = self._measure(loop, entry, numbers)
                    expected = float(values.get(entry.label))
                    self.assertAlmostEqual(
                        measured,
                        expected,
                        places=6,
                        msg=f"{kind.key} {entry.solid}[{entry.loop}] {entry.axis} {width}x{height} label={entry.label}",
                    )

    def _measure(self, loop, entry, numbers):
        points = [(p[0].evaluate(numbers), p[1].evaluate(numbers)) for p in loop]
        n = len(points)
        ta, tb = points[entry.target_seg % n], points[(entry.target_seg + 1) % n]
        if entry.ref_kind == "rp":
            return abs(ta[0] if entry.axis == "u" else ta[1])
        ra, rb = points[entry.ref_seg % n], points[(entry.ref_seg + 1) % n]
        if entry.axis == "diag":
            du, dv = tb[0] - ta[0], tb[1] - ta[1]
            length = math.hypot(du, dv)
            return abs((ra[0] - ta[0]) * (-dv / length) + (ra[1] - ta[1]) * (du / length))
        if entry.axis == "u":
            return abs(ta[0] - ra[0])
        return abs(ta[1] - ra[1])

    def test_every_axis_is_anchored_to_an_origin_plane(self):
        for kind, model in self.entries:
            plan = self.plans[kind.key]
            for solid in model.solids:
                for index in range(len(solid.loops)):
                    for axis in ("u", "v"):
                        entries = [
                            e
                            for e in plan.entries
                            if e.solid == solid.name and e.loop == index and e.axis == axis
                        ]
                        if not entries:
                            continue
                        self.assertTrue(
                            any(e.ref_kind == "rp" for e in entries),
                            f"{kind.key}:{solid.name}[{index}].{axis} has no origin anchor",
                        )

    def test_anchor_planes_are_world_aligned(self):
        for key, plan in self.plans.items():
            for entry in plan.entries:
                if entry.ref_kind == "rp":
                    self.assertIn(entry.ref_rp, {"RP_X0", "RP_Y0", "RP_Z0"})

    def test_match_param_prefers_symbolic_identity(self):
        model = build_model(FAMILY_KINDS[0])
        values = reference_values(model)
        lins = param_lins(model, values)
        self.assertEqual(match_param(Lin.of("WallThickness"), model, lins, values), "WallThickness")
        self.assertEqual(match_param(Lin.of("Half_Width") * 2, model, lins, values), "Width")
        self.assertIsNone(match_param(Lin.of("Nope"), model, lins, values))

    def test_lin_to_formula_renders_revit_syntax(self):
        form = Lin.of("Width") + Lin.of("Cover_Overhang") * 2
        self.assertEqual(lin_to_formula(form), "Cover_Overhang * 2 + Width")
        self.assertEqual(lin_to_formula(-Lin.of("Stub")), "-Stub")


if __name__ == "__main__":
    unittest.main()
