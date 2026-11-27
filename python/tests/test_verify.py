"""Acceptance suite tests: all six families pass, and the suite has teeth."""

import dataclasses
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking.model import build_model  # noqa: E402
from trunking.spec import FAMILY_KINDS, FLEX_SIZES, KIND_BY_KEY  # noqa: E402
from trunking.verify import measure_family, verify_family  # noqa: E402


class TestAcceptance(unittest.TestCase):
    def test_all_six_families_pass(self):
        for kind in FAMILY_KINDS:
            result = verify_family(build_model(kind))
            self.assertEqual(result.failures, [], msg=f"{kind.key}: {result.failures}")
            self.assertTrue(result.ok)
            self.assertEqual(len(result.checks), 41, kind.key)

    def test_measurement_matches_every_catalogue_row(self):
        for kind in FAMILY_KINDS:
            model = build_model(kind)
            for width, height in FLEX_SIZES:
                measured, _ = measure_family(model, width, height)
                in_plane = height if kind.is_upright else width
                self.assertAlmostEqual(measured.outer_edge, in_plane + 75.0, places=6)
                if kind.is_mitre:
                    self.assertAlmostEqual(measured.c_mitre, 75.0 * 2 ** 0.5, places=6)
                else:
                    self.assertAlmostEqual(measured.c_sharp, 75.0, places=6)
                self.assertAlmostEqual(measured.center_to_end, in_plane / 2.0 + 75.0, places=6)

    def test_upright_families_use_the_height_axis(self):
        for key in ("mitre_internal", "sharp_external"):
            model = build_model(KIND_BY_KEY[key])
            for width, height in FLEX_SIZES:
                measured, _ = measure_family(model, width, height)
                self.assertAlmostEqual(measured.center_to_end, height / 2.0 + 75.0, places=6)
                self.assertAlmostEqual(measured.outer_edge, height + 75.0, places=6)


class TestSuiteHasTeeth(unittest.TestCase):
    def _fails(self, model, check_name):
        result = verify_family(model)
        names = {check.name for check in result.failures}
        self.assertIn(check_name, names, f"expected {check_name} to fail, got {sorted(names)}")
        return result

    def test_extra_type_is_caught(self):
        model = build_model(KIND_BY_KEY["mitre_front"])
        broken = dataclasses.replace(model, type_names=("Standard", "50x50"))
        self._fails(broken, "single_family_type")

    def test_duplicate_parameter_is_caught(self):
        model = build_model(KIND_BY_KEY["sharp_front"])
        broken = dataclasses.replace(model, params=list(model.params) + [model.params[0]])
        self._fails(broken, "no_type_catalogue")

    def test_size_named_parameter_is_caught(self):
        model = build_model(KIND_BY_KEY["sharp_front"])
        extra = dataclasses.replace(model.params[0], name="100x100", formula=None)
        broken = dataclasses.replace(model, params=list(model.params) + [extra])
        self._fails(broken, "no_type_catalogue")

    def test_per_size_branching_is_caught(self):
        model = build_model(KIND_BY_KEY["mitre_front"])
        params = list(model.params)
        index = [p.name for p in params].index("CenterToEnd")
        params[index] = dataclasses.replace(
            params[index],
            formula="if(Width <= 100 mm, Half_Width + Stub, Half_Width + 100 mm)",
        )
        broken = dataclasses.replace(model, params=params)
        self._fails(broken, "no_type_catalogue")

    def test_wrong_cover_side_is_caught(self):
        for key in ("mitre_front", "mitre_internal"):
            model = build_model(KIND_BY_KEY[key])
            swapped = []
            for solid in model.solids:
                if solid.name == "Cover":
                    swapped.append(dataclasses.replace(solid, name="Tray_Base"))
                elif solid.name == "Tray_Base":
                    swapped.append(dataclasses.replace(solid, name="Cover"))
                else:
                    swapped.append(solid)
            broken = dataclasses.replace(model, solids=swapped)
            self._fails(broken, "cover_and_base_sides")

    def test_wrong_center_to_end_is_caught(self):
        model = build_model(KIND_BY_KEY["sharp_front"])
        params = list(model.params)
        index = [p.name for p in params].index("CenterToEnd")
        params[index] = dataclasses.replace(params[index], formula="Half_Width + Stub * 2")
        broken = dataclasses.replace(model, params=params)
        result = self._fails(broken, "catalogue_100x100")
        self.assertTrue(any("CenterToEnd" in c.detail for c in result.failures))

    def test_missing_connector_is_caught(self):
        model = build_model(KIND_BY_KEY["mitre_front"])
        broken = dataclasses.replace(model, connectors=model.connectors[:1])
        self._fails(broken, "connectors_50x50")

    def test_wrong_dimension_label_is_caught(self):
        model = build_model(KIND_BY_KEY["mitre_front"])
        params = list(model.params)
        index = [p.name for p in params].index("CenterToEnd")
        params[index] = dataclasses.replace(params[index], formula="Half_Width + Stub + 5 mm")
        broken = dataclasses.replace(model, params=params)
        self.assertFalse(verify_family(broken).ok)


if __name__ == "__main__":
    unittest.main()
