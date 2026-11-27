"""Build-pipeline tests, executed against the in-memory fake Revit document."""

import dataclasses
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking import adapter as api  # noqa: E402
from trunking.builder import DEFAULT_TYPE_NAME, build_all, build_family, skipped_phases  # noqa: E402
from build_families import open_progress_log  # noqa: E402
from trunking.fake_revit import FakeRevit  # noqa: E402
from trunking.model import build_model  # noqa: E402
from trunking.report import build_summary_markdown  # noqa: E402
from trunking.spec import FAMILY_KINDS, FLEX_SIZES, KIND_BY_KEY  # noqa: E402

TEMPLATE = "Metric Cable Tray Fitting.rft"


class BuildFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="trunking-build-")
        cls.revit = FakeRevit(log=lambda message: None)
        cls.models = [build_model(kind) for kind in FAMILY_KINDS]
        cls.docs = {}
        cls.reports = []
        for model in cls.models:
            path = os.path.join(cls.tmp, model.kind.filename)
            report = build_family(model, cls.revit, TEMPLATE, path)
            cls.docs[model.kind.key] = report.built.document
            cls.reports.append(report)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestBuildContract(BuildFixture):
    def test_every_family_builds_without_failures(self):
        for report in self.reports:
            self.assertEqual(report.failures, [], msg=f"{report.family}: {report.failures}")
            self.assertTrue(report.ok)

    def test_no_capability_fell_back(self):
        for report in self.reports:
            for name, cap in report.capabilities.items():
                self.assertIn(cap.status, (api.OK, api.SKIPPED), msg=f"{report.family}:{name}={cap.status}")

    def test_exactly_one_type_and_new_type_never_called(self):
        for key, doc in self.docs.items():
            self.assertEqual(doc.types, [DEFAULT_TYPE_NAME], key)
            self.assertEqual(doc.new_types_created, 0, key)

    def test_category_and_part_type(self):
        for key, doc in self.docs.items():
            self.assertEqual(doc.category, "OST_CableTrayFitting", key)
            self.assertEqual(doc.part_type, "Elbow", key)

    def test_all_parameters_are_instance_parameters(self):
        for key, doc in self.docs.items():
            for name, param in doc.params.items():
                self.assertTrue(param.instance, f"{key}:{name}")

    def test_required_parameters_exist(self):
        required = (
            "Width",
            "Height",
            "Angle",
            "WallThickness",
            "CenterToEnd",
            "Show_Cover",
            "Show_Flanges",
            "Cover_Type",
            "Tray_Material",
            "Cover_Material",
        )
        for key, doc in self.docs.items():
            for name in required:
                self.assertIn(name, doc.params, f"{key}:{name}")

    def test_solids_create_with_offsets_and_dimensions(self):
        for key, doc in self.docs.items():
            extrusions = [e for e in doc.elements if e.kind == "extrusion"]
            self.assertEqual(len(extrusions), 6, key)
            for element in extrusions:
                self.assertIn("start", element.data)
                self.assertIn("end", element.data)
                self.assertIn("offset_params", element.data, f"{key}:{element.name}")
                self.assertTrue(element.data.get("dimensions"), f"{key}:{element.name}")

    def test_flanges_are_fine_only_and_bound_to_show_flanges(self):
        for key, doc in self.docs.items():
            for element in doc.elements:
                if element.name.startswith("Flange_"):
                    self.assertEqual(str(element.data.get("detail")).lower(), "fine", key)
                    self.assertEqual(element.data.get("show_param"), "Show_Flanges", key)

    def test_connectors_are_linked_bound_and_sized(self):
        for key, doc in self.docs.items():
            self.assertEqual(len(doc.connectors), 2, key)
            first, second = doc.connectors
            self.assertIs(first.linked, second)
            self.assertIs(second.linked, first)
            self.assertEqual(first.width_param, "Width")
            self.assertEqual(first.height_param, "Height")
            self.assertEqual(first.profile, "Rectangular")

    def test_each_family_saved_a_valid_artifact(self):
        for key, doc in self.docs.items():
            self.assertTrue(os.path.isfile(doc.saved_to), key)
            with open(doc.saved_to, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertTrue(payload["virtual_rfa"])
            self.assertEqual(payload["types"], [DEFAULT_TYPE_NAME])
            self.assertEqual(len(payload["solids"]), 6)
            self.assertGreater(payload["dimensions"], 30)

    def test_report_markdown_mentions_every_family(self):
        text = build_summary_markdown(self.reports)
        for report in self.reports:
            self.assertIn(report.family, text)


class TestFlexing(BuildFixture):
    def test_single_type_flexes_over_all_sizes(self):
        doc = self.docs["mitre_front"]
        for width, height in FLEX_SIZES:
            values = self.revit.flex(doc, width, height)
            self.assertAlmostEqual(values["CenterToEnd"], width / 2.0 + 75.0, places=6)
            self.assertAlmostEqual(values["Outer_Edge_AB"], width + 75.0, places=6)
            self.assertAlmostEqual(values["Mitre_Face_C"], 75 * 2 ** 0.5, places=4)
        self.assertEqual(doc.types, [DEFAULT_TYPE_NAME])

    def test_vertical_type_flexes_on_the_height_axis(self):
        doc = self.docs["sharp_internal"]
        for width, height in FLEX_SIZES:
            values = self.revit.flex(doc, width, height)
            self.assertAlmostEqual(values["CenterToEnd"], height / 2.0 + 75.0, places=6)

    def test_wall_thickness_follows_the_formula(self):
        doc = self.docs["sharp_front"]
        for width, height in FLEX_SIZES:
            values = self.revit.flex(doc, width, height)
            expected = 1.0 if width <= 50 and height <= 50 else 1.2 if width <= 100 and height <= 75 else 1.4 if width <= 150 and height <= 100 else 1.6
            self.assertAlmostEqual(values["WallThickness"], expected, places=6)


class TestBuildFailures(unittest.TestCase):
    def test_type_parameter_aborts_the_build(self):
        tmp = tempfile.mkdtemp(prefix="trunking-fail-")
        try:
            model = build_model(KIND_BY_KEY["mitre_front"])
            params = list(model.params)
            params[0] = dataclasses.replace(params[0], instance=False)
            broken = dataclasses.replace(model, params=params)
            revit = FakeRevit(log=lambda message: None)
            path = os.path.join(tmp, "broken.rfa")
            report = build_family(broken, revit, TEMPLATE, path)
            self.assertFalse(report.ok)
            self.assertFalse(os.path.exists(path))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_bad_formula_aborts_the_build(self):
        tmp = tempfile.mkdtemp(prefix="trunking-fail-")
        try:
            model = build_model(KIND_BY_KEY["sharp_front"])
            params = list(model.params)
            index = [p.name for p in params].index("CenterToEnd")
            params[index] = dataclasses.replace(params[index], formula="Half_Width + Nope")
            broken = dataclasses.replace(model, params=params)
            revit = FakeRevit(log=lambda message: None)
            report = build_family(broken, revit, TEMPLATE, os.path.join(tmp, "broken.rfa"))
            self.assertFalse(report.ok)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_build_all_writes_six_files(self):
        tmp = tempfile.mkdtemp(prefix="trunking-all-")
        try:
            revit = FakeRevit(log=lambda message: None)
            models = [build_model(kind) for kind in FAMILY_KINDS]
            reports = build_all(models, revit, TEMPLATE, tmp, log=lambda message: None)
            self.assertEqual(len(reports), 6)
            self.assertTrue(all(report.ok for report in reports))
            files = sorted(os.listdir(tmp))
            self.assertEqual(len(files), 6)
            self.assertIn("Trunking_90_MitreBend_FrontOpening.rfa", files)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestCrashDiagnostics(unittest.TestCase):
    """A native crash cannot be caught, so these two carry the evidence."""

    def test_skipped_phases_parses_the_switch(self):
        previous = os.environ.get("TRUNKING_SKIP")
        try:
            os.environ["TRUNKING_SKIP"] = "types, Connectors"
            self.assertEqual(skipped_phases(), {"types", "connectors"})
            os.environ["TRUNKING_SKIP"] = ""
            self.assertEqual(skipped_phases(), set())
            os.environ.pop("TRUNKING_SKIP")
            self.assertEqual(skipped_phases(), set())
        finally:
            if previous is None:
                os.environ.pop("TRUNKING_SKIP", None)
            else:
                os.environ["TRUNKING_SKIP"] = previous

    def test_progress_log_is_on_disk_before_the_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            log, path, close = open_progress_log(tmp)
            try:
                log("phase 2/8 single type")
                log("   solid Tray_Base")
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
            finally:
                close()
            self.assertIn("phase 2/8 single type", text)
            self.assertIn("solid Tray_Base", text)


if __name__ == "__main__":
    unittest.main()
