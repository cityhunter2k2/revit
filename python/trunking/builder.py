"""The build pipeline: model -> ``.rfa`` through a :class:`~.adapter.RevitAdapter`.

Step order matters:

1. open the metric cable tray fitting template and pin the category,
2. make sure the family keeps **exactly one type** and rename it ``Standard``,
3. create every parameter as an *instance* parameter (hard requirement: a type
   parameter's formula may not reference an instance parameter),
4. create the subcategories / material,
5. one extrusion per solid, then bind its extrusion offsets to parameters and
   label its profile dimensions (this is what makes the family flex),
6. connectors on the collar port faces, sizes bound to ``Width``/``Height``,
   then linked to each other,
7. part type = Elbow, symbolic coarse lines, regenerate,
8. assert ``FamilyManager.Types.Size == 1`` and save.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from . import adapter as api
from .adapter import BuildReport, BuiltFamily, CapResult, LabelRequest
from .dimplan import DimPlan, build_plan
from .evaluate import evaluate_model, evaluate_params
from .model import FamilyModel, validate_model

DEFAULT_TYPE_NAME = "Standard"


def build_family(
    model: FamilyModel,
    revit: api.RevitAdapter,
    template_path: str,
    out_path: str,
    report: Optional[BuildReport] = None,
) -> BuildReport:
    report = report or BuildReport(family=model.kind.filename)
    try:
        validate_model(model)
    except ValueError as exc:
        report.add("validate_model", api.failed(str(exc)))
        return report
    report.add("validate_model", api.ok(f"{len(model.params)} instance parameters, single type"))
    plan = build_plan(model)
    values = evaluate_params(model, 100.0, 50.0)
    numbers = {k: (1.0 if v is True else 0.0 if v is False else float(v) if isinstance(v, (int, float)) else 0.0)
               for k, v in values.items()}
    evaluated = evaluate_model(model, values)
    built = BuiltFamily(filename=model.kind.filename)

    # 1 - document ------------------------------------------------------- #
    doc = revit.open_family_template(template_path, out_path)
    built.document = doc
    report.add("open_template", api.ok(template_path), os.path.basename(template_path))
    report.add_capability("category", revit.ensure_cable_tray_fitting_category(doc))

    # 2 - single type ---------------------------------------------------- #
    type_result = revit.ensure_single_type(doc, DEFAULT_TYPE_NAME)
    report.add("ensure_single_type", type_result, f"types={revit.family_type_count(doc)}")
    if revit.family_type_count(doc) != 1:
        report.add(
            "assert_single_type",
            api.failed(f"FamilyManager.Types.Size == {revit.family_type_count(doc)} (expected 1)"),
        )

    # 3 - parameters ----------------------------------------------------- #
    existing = set(revit.parameter_names(doc))
    created = 0
    for definition in model.params:
        if definition.name in existing:
            report.add("parameter_exists", api.skipped(definition.name), definition.name)
            continue
        result = revit.add_instance_parameter(doc, definition)
        report.add("add_parameter", result, definition.name)
        created += 1
    for definition in model.params:
        if definition.formula:
            report.add("set_formula", revit.set_formula(doc, definition.name, definition.formula), definition.formula)
        elif definition.default not in (None, ""):
            report.add("set_default", revit.set_value(doc, definition.name, definition.default), str(definition.default))
    report.add("parameter_count", api.ok(str(len(model.params))), f"{created} created")

    # 4 - subcategories / material -------------------------------------- #
    materials: Dict[str, object] = {}
    for name, material_param in model.subcategories.items():
        report.add("subcategory", revit.ensure_subcategory(doc, name), name)
        material_name = str(values.get(material_param, "Galvanised Steel"))
        if material_name not in materials:
            materials[material_name] = revit.ensure_material(doc, material_name)
    report.add("materials", api.ok(str(sorted(materials))), ", ".join(sorted(materials)))

    # 5 - geometry ------------------------------------------------------- #
    elements: Dict[str, object] = {}
    dimension_count = 0
    for solid in model.solids:
        solid_eval = evaluated.solids[solid.name]
        loops = [loop.points for loop in solid_eval.loops]
        element = revit.create_extrusion(doc, solid, loops, solid_eval.start, solid_eval.end)
        if element is None:
            report.add("create_extrusion", api.failed(solid.name), solid.description)
            continue
        elements[solid.name] = element
        report.add(
            "create_extrusion",
            api.ok(f"depth={solid_eval.depth:.2f}"),
            f"{solid.name} ({len(loops)} loop(s))",
        )
        report.add_capability(
            f"extrusion_offsets:{solid.name}",
            revit.associate_extrusion_offsets(doc, element, solid.start, solid.end),
        )
        entries = [e for e in plan.entries if e.solid == solid.name]
        requests = label_requests(solid, entries, numbers)
        dimension_count += len(requests)
        report.add_capability(
            f"sketch_dimensions:{solid.name}",
            revit.apply_sketch_dimensions(doc, element, requests, numbers),
        )
        report.add_capability(
            f"detail_visibility:{solid.name}", revit.set_detail_visibility(doc, element, solid.detail)
        )
        if solid.show_param:
            report.add_capability(
                f"visibility_param:{solid.name}", revit.associate_visibility(doc, element, solid.show_param)
            )
        material_name = str(values.get(solid.material_param, "Galvanised Steel"))
        report.add_capability(
            f"material:{solid.name}",
            revit.set_element_material(doc, element, solid.material_param, materials.get(material_name)),
        )
        if solid.subcategory:
            report.add("subcategory_assign", api.ok(solid.subcategory), solid.name)

    # 6 - connectors ----------------------------------------------------- #
    connector_refs = []
    for connector in model.connectors:
        host = elements.get(connector.host_solid)
        ref = revit.create_cable_tray_connector(doc, connector, numbers, host)
        if ref is None:
            report.add("create_connector", api.failed(connector.name), connector.host_solid)
            continue
        connector_refs.append(ref)
        report.add("create_connector", api.ok(connector.host_solid), connector.name)
        report.add_capability(
            f"connector_size:{connector.name}",
            revit.bind_connector_size(doc, ref, connector.width_param, connector.height_param),
        )
    if len(connector_refs) == 2:
        report.add("link_connectors", revit.link_connectors(doc, connector_refs[0], connector_refs[1]))
    else:
        report.add("link_connectors", api.failed(f"expected 2 connectors, got {len(connector_refs)}"))

    # 7 - part type, symbols, regenerate --------------------------------- #
    part = revit.set_part_type(doc, "Elbow")
    report.add_capability("part_type", part)
    built.part_type = "Elbow" if part.ok else part.status
    for symbol in model.symbols:
        report.add("symbolic_line", revit.create_symbolic_line(doc, symbol, numbers), symbol.description)
    revit.regenerate(doc)

    # 8 - final single-type assertion + save ----------------------------- #
    built.type_count = revit.family_type_count(doc)
    built.parameter_count = len(model.params)
    built.connector_count = len(connector_refs)
    built.solid_count = len(elements)
    built.dimension_count = dimension_count
    report.add(
        "assert_single_type",
        api.ok(f"FamilyManager.Types.Size == {built.type_count}") if built.type_count == 1 else api.failed(
            f"FamilyManager.Types.Size == {built.type_count}"
        ),
        built.filename,
    )
    saved = revit.save_family(doc, out_path)
    report.add("save", saved, out_path)
    built.path = out_path
    report.built = built
    return report


def label_requests(solid, entries, numbers) -> List[LabelRequest]:
    """Turn plan entries into concrete dimension requests (world millimetres)."""
    requests: List[LabelRequest] = []
    for entry in entries:
        loop = solid.loops[entry.loop]
        count = len(loop)
        ta, tb = loop[entry.target_seg % count], loop[(entry.target_seg + 1) % count]
        tu = (ta[0].evaluate(numbers) + tb[0].evaluate(numbers)) / 2.0
        tv = (ta[1].evaluate(numbers) + tb[1].evaluate(numbers)) / 2.0
        ref_a = ref_b = None
        if entry.ref_kind == "line":
            ra, rb = loop[entry.ref_seg % count], loop[(entry.ref_seg + 1) % count]
            ra_u = (ra[0].evaluate(numbers) + rb[0].evaluate(numbers)) / 2.0
            ra_v = (ra[1].evaluate(numbers) + rb[1].evaluate(numbers)) / 2.0
            ref_a = solid.frame.to_world(ra[0].evaluate(numbers), ra[1].evaluate(numbers), 0.0)
            ref_b = solid.frame.to_world(rb[0].evaluate(numbers), rb[1].evaluate(numbers), 0.0)
            ref_mid = solid.frame.to_world(ra_u, ra_v, 0.0)
        else:
            # anchor to the origin reference plane: pull the coordinate to zero
            if entry.axis == "u":
                ref_mid = solid.frame.to_world(0.0, tv, 0.0)
            else:
                ref_mid = solid.frame.to_world(tu, 0.0, 0.0)
        requests.append(
            LabelRequest(
                solid=solid.name,
                loop=entry.loop,
                axis=entry.axis,
                label=entry.label,
                ref_kind=entry.ref_kind,
                target_a=tuple(solid.frame.to_world(ta[0].evaluate(numbers), ta[1].evaluate(numbers), 0.0)),
                target_b=tuple(solid.frame.to_world(tb[0].evaluate(numbers), tb[1].evaluate(numbers), 0.0)),
                ref_a=tuple(ref_a) if ref_a else None,
                ref_b=tuple(ref_b) if ref_b else None,
                ref_plane=entry.ref_rp,
                expected=entry.expected,
                ref_point=tuple(ref_mid) if entry.ref_kind == "rp" else None,
            )
        )
    return requests


def build_all(
    models: Sequence[FamilyModel],
    revit: api.RevitAdapter,
    template_path: str,
    output_dir: str,
    log=print,
) -> List[BuildReport]:
    os.makedirs(output_dir, exist_ok=True)
    reports: List[BuildReport] = []
    for model in models:
        out_path = os.path.join(output_dir, model.kind.filename)
        log(f"--- building {model.kind.filename}")
        report = build_family(model, revit, template_path, out_path)
        for step in report.steps:
            if step.result.status in (api.FALLBACK, api.FAILED):
                log(f"    {step}")
        reports.append(report)
        log(f"    {report.summary()}")
    return reports
