#! python3
"""Build the six cable-trunking elbow families (pyRevit button).

Needs pyRevit's **CPython** engine (Python 3.6+).  The bootstrap below is
Python 2/3 compatible on purpose: if pyRevit falls back to IronPython 2.7 the
button explains what to change instead of dying with a SyntaxError.

Optional environment variables:
    TRUNKING_HOME      folder that contains ``python/trunking``
    TRUNKING_OUT       output folder for the .rfa files
    TRUNKING_TEMPLATE  full path to ``Metric Cable Tray Fitting.rft``
"""

from __future__ import print_function

import json
import os
import sys

TITLE = "Trunking - Build Families"


def _drop_stale_modules():
    """Forget our modules so a reloaded extension runs the new code.

    pyRevit can keep one shared Python runtime per session, so the previous
    press leaves ``trunking``/``build_families`` in ``sys.modules`` and the next
    press would import the version Revit saw first.
    """
    for name in list(sys.modules):
        if name == "build_families" or name == "trunking" or name.startswith("trunking."):
            del sys.modules[name]


def _alert(message, title=TITLE):
    print(message)
    try:
        from pyrevit import forms

        forms.alert(message, title=title)
    except Exception:
        pass


def _exit(code=1):
    try:
        from pyrevit import script

        script.exit()
    except Exception:
        raise SystemExit(code)
    raise SystemExit(code)


def _engine_ok():
    return sys.version_info >= (3, 6)


def _engine_message():
    return (
        "This button needs pyRevit's CPython engine (Python 3.6+).\n\n"
        "Detected engine: Python %s.%s.%s\n\n"
        "How to fix:\n"
        "  1. pyRevit 7.x     : pyRevit > Settings > Core Settings > Engines >\n"
        "                       Active Engine = CPython, or pass '#! python3'\n"
        "  2. pyRevit 5.x+    : CPython is bundled - update pyRevit\n"
        "  3. IronPython only : run build_families.py with CPython instead\n"
        "     (same pipeline, same files) or use the C# add-in.\n\n"
        "The trunking package uses dataclasses/type hints, so it cannot run on\n"
        "IronPython 2.7."
        % (sys.version_info[0], sys.version_info[1], sys.version_info[2])
    )


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
    """Locate the folder that holds the ``trunking`` package."""
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

    marker = os.path.join(here, "trunking_home.txt")
    if os.path.isfile(marker):
        handle = open(marker)
        try:
            found = _normalise(handle.readline().strip())
        finally:
            handle.close()
        if found:
            return found

    try:
        from pyrevit import forms

        folder = forms.pick_folder(
            title="Select the repository folder that contains python/trunking"
        )
        return _normalise(folder) if folder else None
    except Exception:
        return None


def _default_out():
    return os.environ.get("TRUNKING_OUT") or os.path.join(
        os.path.expanduser("~"), "Documents", "Trunking", "families"
    )


def _pick_template(package_dir):
    template = os.environ.get("TRUNKING_TEMPLATE")
    if template and os.path.isfile(template):
        return template
    sys.path.insert(0, package_dir)
    try:
        from trunking.revit_api import find_template

        template = find_template()
    except Exception:
        template = None
    if template:
        return template
    try:
        from pyrevit import forms

        return forms.pick_file(
            file_ext="rft", title="Metric Cable Tray Fitting.rft"
        )
    except Exception:
        return None


def _summary(path):
    if not os.path.isfile(path):
        return ""
    handle = open(path)
    try:
        data = json.load(handle)
    finally:
        handle.close()
    lines = []
    for family in data.get("families", []):
        status = "OK" if family.get("ok") else "FAILED"
        fallbacks = family.get("fallbacks") or {}
        lines.append(
            "  %-52s %-6s type=%s params=%s fallback=%d"
            % (
                family.get("file", ""),
                status,
                family.get("type_count"),
                family.get("parameters"),
                len(fallbacks),
            )
        )
    return "\n".join(lines)


def main():
    _drop_stale_modules()
    if not _engine_ok():
        _alert(_engine_message())
        _exit()
        return

    package_dir = _find_python_dir()
    if not package_dir:
        _alert(
            "Could not find the 'trunking' python package.\n\n"
            "Set TRUNKING_HOME to the repository folder (the one containing\n"
            "python/trunking), or copy trunking_home.txt next to this button."
        )
        _exit()
        return

    template = _pick_template(package_dir)
    if not template:
        _alert(
            "Metric Cable Tray Fitting.rft was not found.\n\n"
            "Set TRUNKING_TEMPLATE to its full path, or pass --template when\n"
            "running build_families.py from a console."
        )
        _exit()
        return

    out_dir = _default_out()
    report = os.path.join(out_dir, "docs", "05-build-report.md")
    sys.path.insert(0, package_dir)
    import build_families

    try:
        code = build_families.main(
            [
                "--out",
                out_dir,
                "--template",
                template,
                "--report",
                report,
            ]
        )
    except SystemExit as exit_error:  # build_families raises SystemExit on error
        code = exit_error.code or 0
    except Exception as error:
        import traceback

        _alert("Build failed:\n\n%s" % traceback.format_exc())
        _exit()
        return

    summary_path = os.path.join(out_dir, "build-summary.json")
    message = (
        "%s\n\nRepository : %s\nTemplate   : %s\nOutput     : %s\nReport     : %s\n\n%s"
        % (
            "Build finished" if code == 0 else "Build finished with errors",
            package_dir,
            template,
            out_dir,
            report,
            _summary(summary_path),
        )
    )
    _alert(message)
    try:
        from pyrevit import script

        script.show_folder_in_explorer(out_dir)
    except Exception:
        pass


# pyRevit executes this file directly; TRUNKING_NO_AUTORUN lets the unit tests
# import the helpers without launching a build inside the test process.
if os.environ.get("TRUNKING_NO_AUTORUN") != "1":
    main()
