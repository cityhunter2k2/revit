#! python3
"""Flex every built trunking family inside Revit and measure it (pyRevit button).

Opens each ``.rfa``, asserts that it holds exactly one family type, then drives
that single type through the nine catalogue sizes plus ``300x100`` / ``50x100``
by changing only ``Width`` / ``Height``.  Solid bounding boxes and volumes are
compared with the model's prediction (0.5 mm / 2 % tolerance).

Needs pyRevit's **CPython** engine (Python 3.6+); the bootstrap is Python 2/3
compatible so an IronPython fallback explains itself instead of crashing.

Optional environment variables:
    TRUNKING_HOME  folder that contains ``python/trunking``
    TRUNKING_OUT   folder holding the built .rfa files
"""

from __future__ import print_function

import os
import sys

TITLE = "Trunking - Verify Families"


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


def _engine_message():
    return (
        "This button needs pyRevit's CPython engine (Python 3.6+).\n\n"
        "Detected engine: Python %s.%s.%s"
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
    found = _normalise(os.environ.get("TRUNKING_HOME"))
    if found:
        return found
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(10):
        found = _normalise(os.path.join(current, "python"))
        if found:
            return found
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    marker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trunking_home.txt")
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


def _pick_family_folder():
    folder = os.environ.get("TRUNKING_OUT")
    if folder and os.path.isdir(folder):
        return folder
    default = os.path.join(os.path.expanduser("~"), "Documents", "Trunking", "families")
    try:
        from pyrevit import forms

        folder = forms.pick_folder(
            title="Select the folder with the six .rfa files"
        )
        return folder or default
    except Exception:
        return default


def main():
    if sys.version_info < (3, 6):
        _alert(_engine_message())
        _exit()
        return

    package_dir = _find_python_dir()
    if not package_dir:
        _alert("Could not find the 'trunking' python package (set TRUNKING_HOME).")
        _exit()
        return

    families = _pick_family_folder()
    if not os.path.isdir(families):
        _alert("Folder not found:\n\n%s" % families)
        _exit()
        return

    docs = os.path.join(families, "docs")
    report = os.path.join(docs, "06-revit-verification.md")
    sys.path.insert(0, package_dir)
    import verify_families

    try:
        code = verify_families.main(["--families", families, "--docs", docs])
    except SystemExit as exit_error:
        code = exit_error.code or 0
    except Exception:
        import traceback

        _alert("Verification failed:\n\n%s" % traceback.format_exc())
        _exit()
        return

    _alert(
        "%s\n\nFamilies : %s\nReport   : %s"
        % (
            "All families flex correctly" if code == 0 else "Failures found - see report",
            families,
            report,
        )
    )
    try:
        from pyrevit import script

        script.show_folder_in_explorer(docs)
    except Exception:
        pass


# pyRevit executes this file directly; TRUNKING_NO_AUTORUN lets the unit tests
# import the helpers without launching a build inside the test process.
if os.environ.get("TRUNKING_NO_AUTORUN") != "1":
    main()
