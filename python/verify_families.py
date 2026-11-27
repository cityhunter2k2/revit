#!/usr/bin/env python3
"""Acceptance verification for the six trunking families.

Two modes:

``--model-only`` (runs anywhere, no Revit)
    Flexes the family *model* over the nine catalogue sizes plus ``300x100``
    and ``50x100`` and checks geometry, connectors, cover side and the
    dimension plan.  Writes ``docs/04-verification-report.md``.

``--families DIR`` (runs inside Revit)
    Opens every ``.rfa``, asserts ``FamilyManager.Types.Size == 1``, then flexes
    that single type through every size, measures the *actual* solid geometry
    and compares it with what the model predicts.  Writes
    ``docs/06-revit-verification.md``.  This is the run that proves the family
    really flexes inside Revit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trunking.evaluate import evaluate_model, evaluate_params  # noqa: E402
from trunking.model import build_model  # noqa: E402
from trunking.report import (  # noqa: E402
    build_report_markdown,
    flex_matrix,
    manual_labelling_markdown,
)
from trunking.spec import FAMILY_KINDS, FLEX_SIZES, KIND_BY_KEY  # noqa: E402
from trunking.verify import verify_family  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# --------------------------------------------------------------------------- #
# model mode (no Revit)
# --------------------------------------------------------------------------- #
def model_mode(args) -> int:
    kinds = [KIND_BY_KEY[key.strip()] for key in args.only.split(",") if key.strip()] or list(FAMILY_KINDS)
    results = [verify_family(build_model(kind, wall_variant=args.wall_variant)) for kind in kinds]

    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    report_path = os.path.join(docs, "04-verification-report.md")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(
            build_report_markdown(
                results, title="電纜線槽彎頭族 — 單一族類型全尺寸驗證報告"
            )
        )
    with open(os.path.join(docs, "03-manual-labelling.md"), "w", encoding="utf-8") as handle:
        handle.write(manual_labelling_markdown(results))

    print(f"report: {report_path}")
    total_failures = 0
    for result in results:
        failures = len(result.failures)
        total_failures += failures
        print(
            f"{'PASS' if result.ok else 'FAIL'}  {result.model.kind.filename:52s} "
            f"checks={len(result.checks):3d} failures={failures}"
        )
        for check in result.failures[:5]:
            print(f"        {check}")
    print(f"\n{len(results)} families, {total_failures} failing checks")
    return 0 if total_failures == 0 else 1


# --------------------------------------------------------------------------- #
# Revit mode
# --------------------------------------------------------------------------- #
def _get_app():
    try:
        from pyrevit import revit as pyrevit_revit  # type: ignore

        return pyrevit_revit.doc.Application
    except Exception:  # noqa: BLE001
        return globals().get("__revit__")


def revit_mode(args) -> int:
    from trunking.revit_api import RevitApi, Units

    app = _get_app()
    if app is None:
        print("ERROR: run inside Revit, or use --model-only")
        return 2
    api = RevitApi(app, log=lambda m: None)
    DB = api.DB
    units = Units(DB)

    rows: List[Dict[str, object]] = []
    failures = 0
    for kind in FAMILY_KINDS:
        path = os.path.join(args.families, kind.filename)
        if not os.path.isfile(path):
            print(f"missing {path}")
            failures += 1
            continue
        model = build_model(kind, wall_variant=args.wall_variant)
        doc = app.OpenDocumentFile(path)
        if doc is None:
            print(f"could not open {path}")
            failures += 1
            continue
        try:
            type_count = int(doc.FamilyManager.Types.Size)
            ok_type = type_count == 1
            if not ok_type:
                failures += 1
            print(f"{kind.filename}: Types.Size={type_count} {'OK' if ok_type else 'FAIL'}")
            size_rows = _flex_in_revit(doc, model, api, units)
            family_failures = sum(1 for row in size_rows if not row["ok"])
            failures += family_failures
            rows.append(
                {
                    "family": kind.filename,
                    "slot": kind.routing_slot,
                    "type_count": type_count,
                    "sizes": size_rows,
                    "failures": family_failures,
                }
            )
        finally:
            api.close_family(doc)

    report_path = os.path.join(args.docs, "06-revit-verification.md")
    os.makedirs(args.docs, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(_revit_report(rows))
    print(f"report: {report_path}")
    print(f"{failures} failing measurements")
    return 0 if failures == 0 else 1


def _flex_in_revit(doc, model, api, units) -> List[Dict[str, object]]:
    manager = doc.FamilyManager
    params = {p.Definition.Name: p for p in manager.Parameters}
    width_param = params.get("Width")
    height_param = params.get("Height")
    if width_param is None or height_param is None:
        return [{"size": "n/a", "ok": False, "detail": "Width/Height parameters missing"}]

    rows: List[Dict[str, object]] = []
    for width, height in FLEX_SIZES:
        manager.Set(width_param, units.length_to_internal(float(width)))
        manager.Set(height_param, units.length_to_internal(float(height)))
        doc.Regenerate()
        values = evaluate_params(model, width, height)
        expected = evaluate_model(model, values)
        measured = _measure_doc(doc, api)
        problems: List[str] = []
        for name, solid in expected.solids.items():
            got = measured.get(name)
            if got is None:
                problems.append(f"{name}: not found")
                continue
            lo, hi = solid.bbox()
            for axis, index in (("x", 0), ("y", 1), ("z", 2)):
                if abs(got["min"][index] - lo[index]) > 0.5 or abs(got["max"][index] - hi[index]) > 0.5:
                    problems.append(
                        f"{name}.{axis} [{got['min'][index]:.1f},{got['max'][index]:.1f}] "
                        f"!= [{lo[index]:.1f},{hi[index]:.1f}]"
                    )
            if solid.volume > 1e-6 and abs(got["volume"] - solid.volume) > max(1.0, solid.volume * 0.02):
                problems.append(f"{name}.volume {got['volume']:.1f} != {solid.volume:.1f}")
        rows.append(
            {
                "size": f"{width:.0f}x{height:.0f}",
                "ok": not problems,
                "detail": "; ".join(problems[:6]),
                "c2e": expected.length("CenterToEnd"),
                "wall": expected.length("WallThickness"),
            }
        )
        print(f"    {width:.0f}x{height:.0f}: {'ok' if not problems else problems[:2]}")
    return rows


def _measure_doc(doc, api) -> Dict[str, Dict[str, object]]:
    DB = api.DB
    options = DB.Options()
    options.DetailLevel = DB.ViewDetailLevel.Fine
    options.ComputeReferences = False
    out: Dict[str, Dict[str, object]] = {}
    for element in DB.FilteredElementCollector(doc).OfClass(DB.Extrusion):
        geometry = element.get_Geometry(options)
        solid = None
        for obj in geometry:
            if isinstance(obj, DB.Solid) and obj.Volume > 0:
                solid = obj
                break
        if solid is None:
            continue
        bbox = solid.GetBoundingBox()
        if bbox is None:
            continue
        transform = bbox.Transform
        corners = []
        for x in (bbox.Min.X, bbox.Max.X):
            for y in (bbox.Min.Y, bbox.Max.Y):
                for z in (bbox.Min.Z, bbox.Max.Z):
                    point = transform.OfPoint(DB.XYZ(x, y, z))
                    corners.append(
                        (
                            api.units.length_from_internal(point.X),
                            api.units.length_from_internal(point.Y),
                            api.units.length_from_internal(point.Z),
                        )
                    )
        minimum = tuple(min(c[i] for c in corners) for i in range(3))
        maximum = tuple(max(c[i] for c in corners) for i in range(3))
        out[element.Name or element.Id.IntegerValue.__str__()] = {
            "min": minimum,
            "max": maximum,
            "volume": solid.Volume * (304.8 ** 3),
        }
    return out


def _revit_report(rows: Sequence[Dict[str, object]]) -> str:
    lines = [
        "# Revit 內部驗證報告（唯一族類型 Flex 實測）",
        "",
        "每個族在 Revit 中開啟後，**不新增任何族類型**，僅以 `FamilyManager.Set` 修改"
        " `Width` / `Height` 實例參數，重新生成後量測實體邊界框與體積，和程式模型的預測值比對（容差 0.5 mm / 2%）。",
        "",
        "| 族檔 | 槽位 | Types.Size | 尺寸數 | 失敗 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['family']}` | {row['slot']} | {row['type_count']} | {len(row['sizes'])} | {row['failures']} |"
        )
    lines.append("")
    for row in rows:
        lines.append(f"## {row['family']}")
        lines.append("")
        lines.append("| 尺寸 | CenterToEnd | T | 結果 | 差異 |")
        lines.append("|---|---|---|---|---|")
        for item in row["sizes"]:
            lines.append(
                f"| {item['size']} | {item.get('c2e', 0):.1f} | T{int(round(item.get('wall', 0) * 10))} | "
                f"{'✅' if item['ok'] else '❌'} | {item['detail']} |"
            )
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-only", action="store_true", help="verify the model without Revit")
    parser.add_argument("--families", default=os.path.join(ROOT, "build", "families"), help="folder with the .rfa files")
    parser.add_argument("--docs", default=os.path.join(ROOT, "docs"))
    parser.add_argument("--wall-variant", default="spec", choices=("spec", "catalogue"))
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    if args.model_only:
        return model_mode(args)
    return revit_mode(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(3)
