#!/usr/bin/env python3
"""Build the six cable-trunking elbow families.

Inside Revit (pyRevit / RevitPythonShell / pythonnet):

    pyRevit > (this script)  --out C:\\BIM\\Trunking

Without Revit (CI, sandbox) the same pipeline runs against a fake document, so
the build logic itself is covered by tests:

    python3 build_families.py --dry-run --out ../build/dryrun
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trunking import adapter as api  # noqa: E402
from trunking.builder import build_family  # noqa: E402
from trunking.model import build_model  # noqa: E402
from trunking.report import build_summary_markdown, manual_labelling_markdown  # noqa: E402
from trunking.spec import FAMILY_KINDS, KIND_BY_KEY  # noqa: E402
from trunking.verify import verify_family  # noqa: E402


def get_app():
    """Find the Revit Application object in any of the supported hosts.

    pyRevit (CPython or IronPython), RevitPythonShell and plain pythonnet all
    expose it differently; the first hit wins.
    """
    try:  # pyRevit >= 4.7
        from pyrevit import HOST_APP  # type: ignore

        app = getattr(HOST_APP, "app", None)
        if app is not None:
            return app
    except Exception:  # noqa: BLE001
        pass
    app = globals().get("__revit__")
    if app is not None:
        return app
    try:  # pyRevit without HOST_APP, needs an open document
        from pyrevit import revit as pyrevit_revit  # type: ignore

        return pyrevit_revit.doc.Application
    except Exception:  # noqa: BLE001
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=os.path.join(os.path.dirname(here), "build", "families"))
    parser.add_argument("--template", default=None, help="path to Metric Cable Tray Fitting.rft")
    parser.add_argument("--wall-variant", default="spec", choices=("spec", "catalogue"))
    parser.add_argument("--only", default="", help="comma separated family keys")
    parser.add_argument("--dry-run", action="store_true", help="use the in-memory fake Revit document")
    parser.add_argument("--report", default=os.path.join(os.path.dirname(here), "docs", "05-build-report.md"))
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--keep-open", action="store_true", help="leave the built family documents open in Revit")
    args = parser.parse_args(argv)

    kinds = [KIND_BY_KEY[key.strip()] for key in args.only.split(",") if key.strip()] or list(FAMILY_KINDS)
    models = [build_model(kind, wall_variant=args.wall_variant) for kind in kinds]

    if args.dry_run:
        from trunking.fake_revit import FakeRevit

        revit = FakeRevit(log=lambda m: None)
        out_dir = os.path.join(args.out, "_dryrun")
        template = "Metric Cable Tray Fitting.rft"
        suffix = ".rfa.json"
    else:
        from trunking.revit_api import RevitApi, find_template

        app = get_app()
        if app is None:
            print("ERROR: Revit Application not found. Run this script inside Revit, or use --dry-run.")
            return 2
        template = find_template(args.template)
        if template is None:
            print(
                "ERROR: 'Metric Cable Tray Fitting.rft' not found.\n"
                "       pass --template <path> or set TRUNKING_TEMPLATE."
            )
            return 2
        revit = RevitApi(app, log=print)
        out_dir = args.out
        suffix = ".rfa"

    os.makedirs(out_dir, exist_ok=True)
    reports = []
    paths = {}
    for model in models:
        out_path = os.path.join(out_dir, model.kind.filename.replace(".rfa", suffix))
        print(f"--- {model.kind.filename}")
        report = build_family(model, revit, template, out_path)
        reports.append(report)
        paths[model.kind.key] = out_path
        for step in report.steps:
            if step.result.status in (api.FAILED, api.FALLBACK):
                print(f"    {step}")
        print(f"    {report.summary()}")
        if report.failures:
            print(f"    FAILED: {len(report.failures)} step(s)")
        document = getattr(report.built, "document", None)
        if document is not None and not args.keep_open:
            # close only after the save succeeded; an unsaved document is discarded
            revit.close_family(document)

    # ---- reports ------------------------------------------------------ #
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    title = "建置報告" if not args.dry_run else "建置報告（假 Revit 文件預演 — 非實際 .rfa）"
    with open(args.report, "w", encoding="utf-8") as handle:
        handle.write(build_summary_markdown(reports, title=title))
    print(f"build report   : {args.report}")

    if not args.no_verify:
        results = [verify_family(model) for model in models]
        labelling = os.path.join(os.path.dirname(os.path.abspath(args.report)), "03-manual-labelling.md")
        with open(labelling, "w", encoding="utf-8") as handle:
            handle.write(manual_labelling_markdown(results))
        print(f"labelling table: {labelling}")

    summary = {
        "dry_run": args.dry_run,
        "template": template,
        "wall_variant": args.wall_variant,
        "families": [
            {
                "key": model.kind.key,
                "file": paths[model.kind.key],
                "ok": report.ok,
                "failures": [f"{s.name}: {s.result.message}" for s in report.failures],
                "fallbacks": {k: v.message for k, v in report.capabilities.items() if v.status == api.FALLBACK},
                "type_count": report.built.type_count if report.built else None,
                "parameters": len(model.params),
                "solids": len(model.solids),
                "connectors": len(model.connectors),
            }
            for model, report in zip(models, reports)
        ],
    }
    json_path = os.path.join(out_dir, "build-summary.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
    print(f"summary json   : {json_path}")

    failed = [r for r in reports if r.failures]
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(3)
