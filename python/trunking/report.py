"""Markdown reports: verification matrix, parameter tables, build reports."""

from __future__ import annotations

import datetime
import math
from typing import Dict, Iterable, List, Optional, Sequence

from .dimplan import DimPlan
from .model import FamilyModel
from .spec import DRAWING_TABLE, DRAWING_BY_SIZE, FamilyKind
from .verify import Check, FamilyResult, SizeResult, wall_thickness_audit

STATUS_ICON = {"OK": "✅", "FALLBACK": "⚠️", "SKIPPED": "➖", "FAILED": "❌"}


def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def parameter_table(model: FamilyModel) -> str:
    lines = ["| # | 參數 Parameter | 類型 | 實例? | 公式 Formula | 說明 |", "|---|---|---|---|---|---|"]
    for index, param in enumerate(model.params, start=1):
        spec = {"length": "長度", "angle": "角度", "text": "文字", "yesno": "是/否", "material": "材質"}.get(
            param.spec, param.spec
        )
        lines.append(
            f"| {index} | `{param.name}` | {spec} | {'實例' if param.instance else '**類型**'} | "
            f"{('`' + param.formula + '`') if param.formula else '—'} | {param.description} |"
        )
    return "\n".join(lines)


def solid_table(result: FamilyResult) -> str:
    lines = [
        "| 實體 Solid | 子類別 | 詳細程度 | 拉伸起/迄 (實例參數) | 隱藏參數 | 說明 |",
        "|---|---|---|---|---|---|",
    ]
    for solid in result.model.solids:
        lines.append(
            f"| `{solid.name}` | {solid.subcategory} | {solid.detail} | "
            f"`{solid.start}` → `{solid.end}` | {solid.show_param or '—'} | {solid.description} |"
        )
    return "\n".join(lines)


def dimension_summary(result: FamilyResult) -> str:
    plan = result.plan
    by_solid: Dict[str, int] = {}
    for entry in plan.entries:
        by_solid[entry.solid] = by_solid.get(entry.solid, 0) + 1
    rows = ", ".join(f"{name}×{count}" for name, count in sorted(by_solid.items()))
    return (
        f"共 **{len(plan.entries)}** 個具參數標籤的草圖尺寸；"
        f"自動衍生參數 {len(plan.synthesised)} 個；"
        f"斜切邊保留 {len(plan.diagonal_free)} 個自由自由度（角度與邊長由相鄰受控線自然維持）。\n\n"
        f"分佈：{rows}"
    )


def size_table(result: FamilyResult) -> str:
    kind = result.model.kind
    header = "| W×H | A=B (外邊) | C 斜角面 | C 內直段 | D=E (外邊, 高向) | 板厚 T | 圖紙 T | 通過 |"
    lines = [header, "|---|---|---|---|---|---|---|---|"]
    for size in result.sizes:
        sheet = size.drawing
        sheet_wall = f"T{int(round(sheet.wall_mm * 10))}" if sheet else "—"
        wall_ok = "✅" if (sheet is None or abs(size.wall - sheet.wall_mm) < 1e-6) else "⚠️"
        lines.append(
            f"| {size.width:.0f}×{size.height:.0f} | {_fmt(size.outer_edge, 1)} | "
            f"{_fmt(size.c_mitre, 2) if kind.is_mitre else '—'} | {_fmt(size.c_sharp, 2)} | "
            f"{_fmt(size.height + 75.0, 1)} | T{int(round(size.wall * 10))} | {sheet_wall} | {wall_ok} |"
        )
    return "\n".join(lines)


def flex_matrix(results: Sequence[FamilyResult]) -> str:
    """The acceptance matrix of the brief: every size, every family."""
    header = ["| W×H |"]
    for result in results:
        tag = result.model.kind.key.replace("mitre_", "M-").replace("sharp_", "S-")
        header.append(f" {tag} A/B | {tag} C | {tag} T |")
    lines = ["".join(header).rstrip("|") + "|", "|" + "---|" * (1 + 3 * len(results))]
    sizes = results[0].sizes if results else []
    for index, size in enumerate(sizes):
        cells = [f"| {size.width:.0f}×{size.height:.0f} "]
        for result in results:
            item = result.sizes[index]
            cells.append(f"| {item.outer_edge:.1f} | {(item.c_mitre if result.model.kind.is_mitre else item.c_sharp):.1f} | T{int(round(item.wall * 10))} ")
        lines.append("".join(cells) + "|")
    return "\n".join(lines)


def catalogue_table() -> str:
    lines = [
        "| W×H | 型號 | A | B | C 斜角 | C 死角 | D | E | 圖紙 T |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in DRAWING_TABLE:
        lines.append(
            f"| {row.width:.0f}×{row.height:.0f} | {row.model_code} | {row.a:.0f} | {row.b:.0f} | "
            f"{row.c_mitre:.0f} | {row.c_sharp:.0f} | {row.d:.0f} | {row.e:.0f} | T{int(round(row.wall_mm * 10))} |"
        )
    return "\n".join(lines)


def wall_audit_table(model: FamilyModel) -> str:
    lines = ["| W×H | 公式計算 T | 圖紙型號 T | 相符 |", "|---|---|---|---|"]
    for label, computed, sheet, ok in wall_thickness_audit(model):
        sheet_text = "—" if math.isnan(sheet) else f"T{int(round(sheet * 10))}"
        lines.append(f"| {label} | T{int(round(computed * 10))} | {sheet_text} | {'✅' if ok else '⚠️'} |")
    return "\n".join(lines)


def checks_table(result: FamilyResult, group: Optional[str] = None) -> str:
    lines = ["| 檢查 Check | 群組 | 結果 | 內容 |", "|---|---|---|---|"]
    for check in result.checks:
        if group and check.group != group:
            continue
        lines.append(
            f"| `{check.name}` | {check.group} | {'✅ PASS' if check.ok else '❌ FAIL'} | {check.detail} |"
        )
    return "\n".join(lines)


def family_section(result: FamilyResult) -> str:
    model = result.model
    kind = model.kind
    status = "✅ PASS" if result.ok else "❌ FAIL"
    parts = [
        f"## {kind.filename} — {status}",
        "",
        f"- 標題：**{kind.title}**",
        f"- 彎頭類型：`PartType.Elbow`；佈線首選項槽位：**{kind.routing_slot}**",
        f"- 單一族類型：`Standard`（`FamilyManager.Types.Size == 1`）",
        f"- 參數總數：{len(model.params)}（全部為**實例參數**）",
        f"- 檢查總數：{len(result.checks)}，失敗：{len(result.failures)}",
        "",
        "### 參數表",
        "",
        parameter_table(model),
        "",
        "### 實體與拉伸參數",
        "",
        solid_table(result),
        "",
        "### 草圖約束",
        "",
        dimension_summary(result),
        "",
        "### 尺寸驗證（單一族類型，逐一 Flex）",
        "",
        size_table(result),
        "",
        "### 檢查明細",
        "",
        checks_table(result),
        "",
    ]
    if result.failures:
        parts.append("### 失敗項目")
        parts.append("")
        for check in result.failures:
            parts.append(f"- `{check.name}` — {check.detail}")
        parts.append("")
    return "\n".join(parts)


def build_report_markdown(results: Sequence[FamilyResult], title: str = "驗證報告") -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_checks = sum(len(r.checks) for r in results)
    failures = sum(len(r.failures) for r in results)
    lines = [
        f"# {title}",
        "",
        f"產生時間：{stamp}",
        "",
        "## 總覽",
        "",
        "| 族檔 Family | 槽位 | 檢查 | 失敗 | 結果 |",
        "|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| `{result.model.kind.filename}` | {result.model.kind.routing_slot} | "
            f"{len(result.checks)} | {len(result.failures)} | {'✅' if result.ok else '❌'} |"
        )
    lines += [
        "",
        f"合計 {len(results)} 個族、{total_checks} 項檢查、{failures} 項失敗。",
        "",
        "## 單一族類型全尺寸 Flex 矩陣",
        "",
        flex_matrix(results),
        "",
        "## 圖紙規格對照（原廠規格表）",
        "",
        catalogue_table(),
        "",
        "## 板厚公式 vs 圖紙型號",
        "",
        wall_audit_table(results[0].model) if results else "",
        "",
    ]
    for result in results:
        lines.append(family_section(result))
    return "\n".join(lines)


def build_summary_markdown(reports: Sequence, title: str = "建置報告") -> str:
    lines = [
        f"# {title}",
        "",
        f"產生時間：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "| 族檔 | 步驟 | 失敗 | 能力降級 | 類型數 | 參數 | 實體 | 尺寸 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        built = report.built
        fallbacks = sum(1 for c in report.capabilities.values() if c.status == "FALLBACK")
        lines.append(
            f"| `{report.family}` | {len(report.steps)} | {len(report.failures)} | {fallbacks} | "
            f"{built.type_count if built else '—'} | {built.parameter_count if built else '—'} | "
            f"{built.solid_count if built else '—'} | {built.dimension_count if built else '—'} |"
        )
    lines.append("")
    for report in reports:
        lines.append(f"## {report.family}")
        lines.append("")
        lines.append("| 能力 Capability | 狀態 | 說明 |")
        lines.append("|---|---|---|")
        for name, cap in sorted(report.capabilities.items()):
            lines.append(f"| `{name}` | {STATUS_ICON.get(cap.status, cap.status)} {cap.status} | {cap.message} |")
        lines.append("")
        if report.failures:
            lines.append("**失敗步驟**")
            lines.append("")
            for step in report.failures:
                lines.append(f"- `{step.name}` — {step.result.message} {step.detail}")
            lines.append("")
        if report.warnings:
            lines.append("**降級提示**")
            lines.append("")
            for warning in report.warnings:
                lines.append(f"- {warning}")
            lines.append("")
    return "\n".join(lines)


def manual_labelling_markdown(results: Sequence[FamilyResult]) -> str:
    """The fallback table: exactly which dimension to label, per family."""
    lines = [
        "# 手動標註清單（僅在 `sketch_dimensions` 降級時需要）",
        "",
        "若建置報告出現 `sketch_dimensions: FALLBACK`，代表該 Revit 版本不允許透過 API 建立"
        "草圖尺寸。此時依下表在**族編輯器**中補標：每個實體的草圖 → 註解 → 對齊尺寸，"
        "把尺寸的「標籤」設為指定參數即可。表格由程式自動推導，數值為 100×50 的預設尺寸。",
        "",
    ]
    for result in results:
        lines.append(f"## {result.model.kind.filename}")
        lines.append("")
        lines.append("| 實體 | 迴圈 | 方向 | 標籤參數 | 預設距離 (mm) |")
        lines.append("|---|---|---|---|---|")
        for entry in result.plan.entries:
            lines.append(
                f"| `{entry.solid}` | {entry.loop} | {entry.axis} | `{entry.label}` | {entry.expected:.2f} |"
            )
        lines.append("")
    return "\n".join(lines)
