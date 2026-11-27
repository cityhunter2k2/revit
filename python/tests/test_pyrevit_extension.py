"""pyRevit extension structure and button bootstrap tests (no Revit needed)."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXT = os.path.join(ROOT, "Trunking.extension")
PANEL = os.path.join(EXT, "Trunking.tab", "Trunking.panel")
BUTTONS = ("Check Setup", "Build Families", "Verify Families")


def load_button(name):
    path = os.path.join(PANEL, name + ".pushbutton", "script.py")
    os.environ["TRUNKING_NO_AUTORUN"] = "1"
    spec = importlib.util.spec_from_file_location("button_" + name.replace(" ", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExtensionLayout(unittest.TestCase):
    def test_extension_json(self):
        with open(os.path.join(EXT, "extension.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["name"], "Trunking")

    def test_buttons_have_script_icon_and_bundle(self):
        for name in BUTTONS:
            folder = os.path.join(PANEL, name + ".pushbutton")
            for required in ("script.py", "icon.png", "bundle.yaml"):
                self.assertTrue(os.path.isfile(os.path.join(folder, required)), f"{name}/{required}")

    def test_buttons_request_the_cpython_engine(self):
        for name in BUTTONS:
            path = os.path.join(PANEL, name + ".pushbutton", "script.py")
            with open(path, encoding="utf-8") as handle:
                first = handle.readline().strip()
            self.assertEqual(first, "#! python3", name)

    def test_buttons_are_python2_parseable(self):
        """The IronPython fallback must be able to *read* the script to explain itself."""
        import ast

        for name in BUTTONS:
            path = os.path.join(PANEL, name + ".pushbutton", "script.py")
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            ast.parse(source)
            self.assertNotIn('f"', source)
            self.assertNotIn("f'", source)
            self.assertNotIn("->", source.split("def ")[0])  # no annotations in the header


class TestButtonBootstrap(unittest.TestCase):
    def test_package_discovery_from_environment(self):
        module = load_button("Build Families")
        previous = os.environ.get("TRUNKING_HOME")
        os.environ["TRUNKING_HOME"] = ROOT
        try:
            self.assertEqual(module._find_python_dir(), os.path.join(ROOT, "python"))
        finally:
            if previous is None:
                del os.environ["TRUNKING_HOME"]
            else:
                os.environ["TRUNKING_HOME"] = previous

    def test_package_discovery_walks_up_from_the_button(self):
        module = load_button("Verify Families")
        os.environ.pop("TRUNKING_HOME", None)
        self.assertEqual(module._normalise(os.path.join(ROOT, "python")), os.path.join(ROOT, "python"))
        self.assertIsNone(module._normalise(os.path.join(ROOT, "nope")))

    def test_engine_message_mentions_cpython(self):
        for name in ("Build Families", "Verify Families"):
            module = load_button(name)
            message = module._engine_message()
            self.assertIn("CPython", message)

    def test_check_setup_reports_the_environment(self):
        module = load_button("Check Setup")
        self.assertTrue(module._has_package(os.path.join(ROOT, "python")))
        self.assertEqual(module._find_python_dir(), os.path.join(ROOT, "python"))
        rows, failures = module._check_models(os.path.join(ROOT, "python"))
        self.assertEqual(failures, 0)
        self.assertEqual(len(rows), 6)
        self.assertTrue(any("PASS" in row for row in rows))

    def test_build_summary_rendering(self):
        module = load_button("Build Families")
        payload = {
            "families": [
                {"file": "A.rfa", "ok": True, "type_count": 1, "parameters": 40, "fallbacks": {}},
                {"file": "B.rfa", "ok": False, "type_count": 1, "parameters": 38, "fallbacks": {"x": "y"}},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "build-summary.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            text = module._summary(path)
        self.assertIn("A.rfa", text)
        self.assertIn("FAILED", text)
        self.assertIn("fallback=1", text)


if __name__ == "__main__":
    unittest.main()
