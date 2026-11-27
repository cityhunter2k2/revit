"""Template discovery across Revit install layouts.

Revit 2027 ships ``Metric Cable Tray Fitting.rft`` flat inside the locale
folder and a zh-TW install only has ``Traditional Chinese``, so the discovery
must not rely on one hard-coded path.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking import revit_api  # noqa: E402

NAME = revit_api.TEMPLATE_FILENAME


def _touch(root, *parts):
    path = os.path.join(root, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write("")
    return path


class TestTemplateDiscovery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        patcher = mock.patch.object(revit_api, "_template_roots", return_value=[self.root])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        env = os.environ.pop("TRUNKING_TEMPLATE", None)
        if env is not None:
            self.addCleanup(os.environ.__setitem__, "TRUNKING_TEMPLATE", env)

    def test_flat_2027_layout_in_traditional_chinese(self):
        expected = _touch(self.root, "Family Templates", "Traditional Chinese", NAME)
        self.assertEqual(revit_api.find_template(), expected)

    def test_legacy_category_folders_still_found(self):
        expected = _touch(
            self.root, "Family Templates", "English", "Metric", "Cable Tray", NAME
        )
        self.assertEqual(revit_api.find_template(), expected)

    def test_english_preferred_when_several_locales_ship_it(self):
        english = _touch(self.root, "Family Templates", "English", NAME)
        _touch(self.root, "Family Templates", "Traditional Chinese", NAME)
        self.assertEqual(revit_api.find_template(), english)

    def test_simplified_chinese_locale(self):
        expected = _touch(self.root, "Family Templates", "Chinese", NAME)
        self.assertEqual(revit_api.find_template(), expected)

    def test_partial_name_is_not_a_match(self):
        _touch(self.root, "Family Templates", "Traditional Chinese", "Metric Cable Tray.rft")
        self.assertIsNone(revit_api.find_template())

    def test_missing_template_returns_none(self):
        self.assertIsNone(revit_api.find_template())

    def test_explicit_path_wins(self):
        expected = _touch(self.root, "elsewhere", NAME)
        self.assertEqual(revit_api.find_template(explicit=expected), expected)

    def test_explicit_missing_path_returns_none(self):
        # A typo must not silently fall back to some other install.
        self.assertIsNone(
            revit_api.find_template(explicit=os.path.join(self.root, "nope.rft"))
        )

    def test_environment_override(self):
        expected = _touch(self.root, "env", NAME)
        os.environ["TRUNKING_TEMPLATE"] = expected
        self.addCleanup(os.environ.pop, "TRUNKING_TEMPLATE", None)
        self.assertEqual(revit_api.find_template(), expected)

    def test_walk_is_bounded_by_depth(self):
        _touch(
            self.root,
            "Family Templates",
            "a",
            "b",
            "c",
            "d",
            "e",
            NAME,
        )
        self.assertIsNone(revit_api.find_template())


class TestTemplateRoots(unittest.TestCase):
    def test_known_years_come_first_newest_first(self):
        roots = revit_api._template_roots(years=(2027, 2025))
        self.assertTrue(roots[0].endswith("RVT 2027"))
        self.assertTrue(roots[1].endswith("Revit 2027"))
        self.assertTrue(roots[2].endswith("RVT 2025"))

    def test_roots_are_unique(self):
        roots = revit_api._template_roots(years=(2027, 2026))
        self.assertEqual(len(roots), len(set(roots)))


if __name__ == "__main__":
    unittest.main()
