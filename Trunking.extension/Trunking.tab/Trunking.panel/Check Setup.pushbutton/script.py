#! python3
"""Report the runtime environment and whether the trunking package works here.

This button is written in Python 2/3 common syntax on purpose: run it *first*
and it will tell you exactly what is wrong (engine, package path, template,
output folder) instead of letting a build fail halfway.

Checks:
  1. Python engine + version (IronPython 2.7 cannot run the package)
  2. pyRevit version and Revit version
  3. whether python/trunking is found
  4. whether all six family models build and pass their 41 checks
  5. whether Metric Cable Tray Fitting.rft is found
  6. whether the output folder is writable
"""

from __future__ import print_function

import os
import sys

TITLE = "Trunking - Check Setup"


def _alert(message, title=TITLE):
    print(message)
    try:
        from pyrevit import forms

        forms.alert(message, title=title)
    except Exception:
        pass


def _engine_name():
    try:
        from pyrevit import script

        return str(script.get_engine())
    except Exception:
        return "unknown"


def _pyrevit_version():
    try:
        from pyrevit import version

        return str(version.get_pyrevit_version())
    except Exception:
        pass
    try:
        import pyrevit

        return str(getattr(pyrevit, "__version__", "unknown"))
    except Exception:
        return "unknown"


def _revit_version():
    try:
        from pyrevit import HOST_APP

        app = getattr(HOST_APP, "app", None)
        name = getattr(app, "VersionName", "?")
        number = getattr(app, "VersionNumber", "?")
        return "%s (%s)" % (name, number)
    except Exception:
        return "unknown - not running inside Revit?"


def _has_package(candidate):
    return bool(candidate) and os.path.isfile(os.path.join(candidate, "trunking", "spec.py"))


def _normalise(candidate):
    if not candidate:
        return None
    if _has_package(candidate):
        return candidate
    nested = os.path.join(candidate, "python")
    if _has_package(nested):
        return nested
    return None


def _find_python_dir():
    found = _normalise(os.environ.get("TRUNKING_HOME"))
    if found:
        return found
    here = os.path.dirname(os.path.abspath(__file__))
    current = here
    for _ in range(10):
        found = _normalise(os.path.join(current, "python"))
        if found:
            return found
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def _check_models(package_dir):
    """Build and verify the six family models (pure Python, no Revit)."""
    sys.path.insert(0, package_dir)
    from trunking.model import build_model
    from trunking.spec import FAMILY_KINDS
    from trunking.verify import verify_family

    rows = []
    failures = 0
    for kind in FAMILY_KINDS:
        result = verify_family(build_model(kind))
        failures += len(result.failures)
        rows.append(
            "    %-52s %-4s %d checks"
            % (kind.filename, "PASS" if result.ok else "FAIL", len(result.checks))
        )
    return rows, failures


def main():
    lines = []
    python_ok = sys.version_info >= (3, 6)

    lines.append("Python engine : %s" % _engine_name())
    lines.append(
        "Python version: %s.%s.%s%s"
        % (
            sys.version_info[0],
            sys.version_info[1],
            sys.version_info[2],
            "" if python_ok else "   <-- NEEDS 3.6+ (CPython)",
        )
    )
    lines.append("pyRevit       : %s" % _pyrevit_version())
    lines.append("Revit         : %s" % _revit_version())
    lines.append("")

    package_dir = _find_python_dir()
    if package_dir:
        lines.append("Package       : OK  %s" % package_dir)
    else:
        lines.append("Package       : MISSING (set TRUNKING_HOME or add the repo folder)")
    lines.append("")

    if not python_ok:
        lines.append(
            "This engine is IronPython 2.7, so the package cannot be imported.\n"
            "pyRevit 7 ships CPython 3.12: set\n"
            "    pyRevit > Settings > Engines > Default Engine = CPython\n"
            "or keep the '#! python3' header of the buttons and reload pyRevit."
        )
        _alert("\n".join(lines))
        return

    if package_dir:
        try:
            rows, failures = _check_models(package_dir)
            lines.append("Family models : %s" % ("ALL PASS" if failures == 0 else "%d FAILURES" % failures))
            lines.extend(rows)
        except Exception as error:
            lines.append("Family models : ERROR %s: %s" % (type(error).__name__, error))
        lines.append("")

        try:
            from trunking.revit_api import find_template

            template = os.environ.get("TRUNKING_TEMPLATE") or find_template()
        except Exception:
            template = None
        lines.append("Template      : %s" % (template or "NOT FOUND - set TRUNKING_TEMPLATE"))
        lines.append("")

    out_dir = os.environ.get("TRUNKING_OUT") or os.path.join(
        os.path.expanduser("~"), "Documents", "Trunking", "families"
    )
    try:
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        probe = os.path.join(out_dir, ".write_test")
        handle = open(probe, "w")
        handle.write("ok")
        handle.close()
        os.remove(probe)
        lines.append("Output folder : OK  %s" % out_dir)
    except Exception as error:
        lines.append("Output folder : NOT WRITABLE %s (%s)" % (out_dir, error))

    lines.append("")
    lines.append(
        "Next: press 'Build Families'. It writes the six .rfa files into the\n"
        "output folder above, then closes each document."
    )
    _alert("\n".join(lines))


if os.environ.get("TRUNKING_NO_AUTORUN") != "1":
    main()
