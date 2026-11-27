"""Revit front-end for the build pipeline.

Runs inside Revit (pyRevit / RevitPythonShell / pythonnet) and implements
:class:`trunking.adapter.RevitAdapter` with the real API.

Design rule for this module: **never assume an API shape that cannot be probed.**
Revit's family API differs between releases, and a few of the steps needed here
(sketch dimensions, part type, element visibility) are not documented in a
stable way across versions.  Every such call therefore goes through
:func:`_probe`, which tries candidate paths in order, logs the one that worked,
and degrades to a reported ``FALLBACK`` instead of killing the build.
``verify_families.py`` then measures the result inside Revit, so a degradation
is always visible instead of silent.

Units: the family model is millimetre based; everything handed to Revit is
converted to internal units (feet / radians) by :class:`Units`.
"""

from __future__ import annotations

import glob
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import adapter as api
from . import expr
from .adapter import CapResult, LabelRequest
from .model import SPEC_ANGLE, SPEC_LENGTH, SPEC_MATERIAL, SPEC_TEXT, SPEC_YESNO, ParamDef

MM_PER_FOOT = 304.8

GROUP_MAP = {
    # model group -> (GroupTypeId candidates, BuiltInParameterGroup)
    # Revit 2027 has no GroupTypeId.Dimensions and no "Identity Data" with a
    # space, so the first name that exists on the running release wins.
    "Data": (("Data",), "PG_DATA"),
    "Dimensions": (("Dimensions", "Geometry", "Constraints"), "PG_DIMENSIONS"),
    "Geometry": (("Geometry",), "PG_GEOMETRY"),
    "Materials and Finishes": (("Materials",), "PG_MATERIALS"),
    "Graphics": (("Graphics", "Display"), "PG_GRAPHICS"),
    "Identity Data": (("IdentityData", "Data"), "PG_IDENTITY_DATA"),
}

SPEC_MAP = {
    SPEC_LENGTH: ("Length", "Length"),
    SPEC_ANGLE: ("Angle", "Angle"),
    SPEC_TEXT: ("String", "Text"),
    SPEC_YESNO: ("Boolean", "YesNo"),
    SPEC_MATERIAL: ("Reference", "Material"),
}

#: Suffix used when a parameter name is already owned by a localised built-in.
PARAM_SUFFIX = "_TS"

#: Tokens allowed in a Revit formula besides parameter names.
FORMULA_WORDS = frozenset(
    {
        "if",
        "and",
        "or",
        "not",
        "mm",
        "cm",
        "m",
        "ft",
        "in",
        "degrees",
        "radians",
        "pi",
    }
)


def element_id_value(element_id: Any) -> int:
    """Integer value of an ``ElementId`` on this Revit release.

    Revit 2027 removed ``ElementId.IntegerValue``; ``ElementId.Value`` (Int64)
    replaced it in 2024 and is the only member left now. Everything here compares
    ids against ``int(BuiltInCategory.…)``, so the number is what matters.
    """
    for attribute in ("Value", "IntegerValue"):
        value = getattr(element_id, attribute, None)
        if value is not None:
            return int(value)
    raise AttributeError(
        "ElementId exposes neither 'Value' nor 'IntegerValue' on this Revit release"
    )


def element_id_of(value: Any):
    """ElementId of an element/material, or the value itself when it is an id."""
    inner = getattr(value, "Id", None)
    return inner if inner is not None else value


def _material_name(doc, material) -> str:
    """Display name of a material that may be given as an ElementId."""
    name = getattr(material, "Name", None)
    if name:
        return str(name)
    try:
        resolved = doc.GetElement(material)
    except Exception:  # noqa: BLE001
        resolved = None
    if resolved is not None and getattr(resolved, "Name", None):
        return str(resolved.Name)
    return "material"


def _probe(attempts: Sequence[Tuple[str, Any]], log=None) -> CapResult:
    """Run candidate API paths in order; return the first that succeeds."""
    errors: List[str] = []
    for label, call in attempts:
        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 - probing is the whole point
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            continue
        if result is None or result is False:
            errors.append(f"{label}: returned {result!r}")
            continue
        if log:
            log(f"    probe ok: {label}")
        return api.ok(label)
    # Nothing worked: that is a failure, not a degradation. Callers check
    # `.failed` and used to see FALLBACK here, so every failed AddParameter was
    # reported as "ok" while no parameter had been created.
    return api.failed("; ".join(errors[:3]) or "no candidate path available")


class Units:
    """Millimetre/degree <-> Revit internal units across API generations."""

    def __init__(self, db) -> None:
        self._unit_utils = getattr(db, "UnitUtils", None)
        self._unit_type_id = getattr(db, "UnitTypeId", None)

    def length_to_internal(self, value_mm: float) -> float:
        if self._unit_utils is not None and self._unit_type_id is not None:
            return self._unit_utils.ConvertToInternalUnits(value_mm, self._unit_type_id.Millimeters)
        return value_mm / MM_PER_FOOT

    def length_from_internal(self, value: float) -> float:
        if self._unit_utils is not None and self._unit_type_id is not None:
            return self._unit_utils.ConvertFromInternalUnits(value, self._unit_type_id.Millimeters)
        return value * MM_PER_FOOT

    def angle_to_internal(self, value_deg: float) -> float:
        if self._unit_utils is not None and self._unit_type_id is not None:
            return self._unit_utils.ConvertToInternalUnits(value_deg, self._unit_type_id.Degrees)
        return math.radians(value_deg)


class RevitApi(api.RevitAdapter):
    name = "revit"

    def __init__(self, app, log=None) -> None:
        self.app = app
        self._log = log
        self._spec_by_name: Dict[str, str] = {}
        self._family_params: Dict[str, Any] = {}
        self._transaction = None
        self._import()

    # -- imports ----------------------------------------------------------- #
    def _import(self) -> None:
        import clr  # noqa: F401 - only importable inside Revit

        # pyRevit's CPython engine needs the assemblies loaded explicitly;
        # IronPython already has them referenced by the host application.
        for assembly in ("RevitAPI", "RevitAPIUI", "RevitServices", "System"):
            try:
                clr.AddReference(assembly)
            except Exception:  # noqa: BLE001 - already loaded is fine
                pass
        import Autodesk.Revit.DB as DB

        self.DB = DB
        self.XYZ = DB.XYZ
        self.Line = DB.Line
        self.Plane = DB.Plane
        self.units = Units(DB)

    def log(self, message: str) -> None:
        if self._log:
            self._log(message)

    # -- document ---------------------------------------------------------- #
    def _begin_build_transaction(self, doc) -> None:
        """Open the one transaction every modification of the build happens in.

        Revit refuses SketchPlane.Create, Material.Create, parameter writes and
        the rest with ModificationOutsideTransactionException when no
        transaction is open. One transaction for the whole family also keeps the
        element handles valid: a Reference taken in one transaction is dead in
        the next.
        """
        self._transaction = None
        try:
            transaction = self.DB.Transaction(doc, "Trunking family build")
            transaction.Start()
            self._transaction = transaction
        except Exception as exc:  # noqa: BLE001
            self.log(f"    could not start a transaction: {type(exc).__name__}: {exc}")

    def _commit_build_transaction(self, doc) -> CapResult:
        transaction = self._transaction
        self._transaction = None
        if transaction is None:
            return api.failed("no open transaction - the build modified nothing")
        try:
            transaction.Commit()
        except Exception as exc:  # noqa: BLE001
            return api.failed(f"transaction commit: {type(exc).__name__}: {exc}")
        status = transaction.GetStatus()
        if status != self.DB.TransactionStatus.Committed:
            return api.failed(f"transaction status {status}")
        return api.ok("transaction committed")

    def open_family_template(self, template_path: str, destination: str):
        if not os.path.isfile(template_path):
            raise RuntimeError("family template not found: %s" % template_path)
        # OpenDocumentFile returns the document that is *already open* for that
        # path, so a leftover template document from an earlier run is reused and
        # every "new" family accumulates the previous one's parameters.
        # NewFamilyDocument always builds a fresh document from the template.
        doc = None
        try:
            doc = self.app.NewFamilyDocument(template_path)
        except Exception as exc:  # noqa: BLE001 - older hosts may not expose it
            self.log("    NewFamilyDocument failed: %s: %s" % (type(exc).__name__, exc))
        if doc is None:
            doc = self.app.OpenDocumentFile(template_path)
        if doc is None:
            raise RuntimeError("Revit could not open %s" % template_path)
        # FamilyParameter proxies belong to one document; carrying the previous
        # family's cache into this one means calling Set/SetFormula with an
        # object from another document, which does not raise, it takes Revit
        # down.
        self._family_params = {}
        self._spec_by_name = {}
        try:
            self.log(
                "    document %r, %d parameters before the build"
                % (doc.Title, len(self.parameter_inventory(doc)))
            )
        except Exception:  # noqa: BLE001
            pass
        # a template opens untitled; SaveAs(destination) turns it into the .rfa
        self._begin_build_transaction(doc)
        return doc

    def save_family(self, doc, path: str) -> CapResult:
        committed = self._commit_build_transaction(doc)
        if committed.failed:
            return committed
        try:
            options = self.DB.SaveAsOptions()
            options.OverwriteExistingFile = True
            doc.SaveAs(path, options)
            return api.ok("%s (%s)" % (path, committed.message))
        except Exception as exc:  # noqa: BLE001
            return api.failed(f"{type(exc).__name__}: {exc}")

    def close_family(self, doc) -> None:
        transaction = self._transaction
        if transaction is not None:
            self._transaction = None
            try:
                transaction.RollBack()
            except Exception:  # noqa: BLE001
                pass
        try:
            doc.Close(False)
        except Exception:  # noqa: BLE001
            pass

    def regenerate(self, doc) -> None:
        doc.Regenerate()

    # -- family manager ---------------------------------------------------- #
    def family_type_count(self, doc) -> int:
        return int(doc.FamilyManager.Types.Size)

    def ensure_single_type(self, doc, name: str) -> CapResult:
        """Collapse the template's types down to the one delivered type.

        ``Metric Cable Tray Fitting.rft`` ships three types; the design is a
        single flexing type, so the extras are deleted instead of refusing the
        build. A deleted FamilyType is a dead proxy: its Name has to be read
        *before* DeleteCurrentType, never after.
        """
        manager = doc.FamilyManager
        dropped = []
        try:
            total = int(manager.Types.Size)
            if total == 0:
                return api.failed("the template holds no type at all")
            while int(manager.Types.Size) > 1:
                if len(dropped) >= total:
                    return api.failed("Revit kept reporting extra types after deleting them")
                current = manager.CurrentType
                label = str(current.Name)
                manager.DeleteCurrentType()
                dropped.append(label)
                remaining = list(manager.Types)
                if not remaining:
                    return api.failed("deleting the extra types left no type behind")
                manager.CurrentType = remaining[0]
            if manager.CurrentType.Name != name:
                manager.RenameCurrentType(name)
        except Exception as exc:  # noqa: BLE001 - a type change must not kill the build
            return api.failed(f"{type(exc).__name__}: {exc}")
        if dropped:
            return api.ok(f"deleted {len(dropped)} template type(s) and kept '{name}'")
        return api.ok(f"single type already named {name}")

    def parameter_names(self, doc) -> Sequence[str]:
        return [p.Definition.Name for p in doc.FamilyManager.Parameters]

    def _spec_id(self, spec: str):
        st = self.DB.SpecTypeId
        if spec == SPEC_LENGTH:
            return st.Length
        if spec == SPEC_ANGLE:
            return st.Angle
        if spec == SPEC_TEXT:
            return st.String.Text
        if spec == SPEC_YESNO:
            return st.Boolean.YesNo
        if spec == SPEC_MATERIAL:
            return st.Reference.Material
        raise AttributeError(spec)

    def add_instance_parameter(self, doc, definition: ParamDef) -> CapResult:
        manager = doc.FamilyManager
        forge_names, bip_group = GROUP_MAP.get(definition.group, (("Data",), "PG_DATA"))
        forge_group = None
        for candidate in forge_names:
            if getattr(self.DB.GroupTypeId, candidate, None) is not None:
                forge_group = candidate
                break
        _, ptype = SPEC_MAP.get(definition.spec, ("Length", "Length"))
        self._spec_by_name[definition.name] = definition.spec
        self.log("    add %s (%s, group %s)" % (definition.name, definition.spec, forge_group))

        created = []

        def create(name):
            if forge_group is None:
                raise AttributeError("no GroupTypeId for %r" % definition.group)
            parameter = manager.AddParameter(
                name, getattr(self.DB.GroupTypeId, forge_group), self._spec_id(definition.spec), True
            )
            created.append(parameter)
            return parameter is not None

        def legacy():
            group = getattr(self.DB.BuiltInParameterGroup, bip_group, None)
            if group is None:
                raise AttributeError("no BuiltInParameterGroup.%s" % bip_group)
            parameter = manager.AddParameter(
                definition.name, group, getattr(self.DB.ParameterType, ptype), True
            )
            created.append(parameter)
            return parameter is not None

        result = _probe(
            (
                ("FamilyManager.AddParameter(ForgeTypeId)", lambda: create(definition.name)),
                ("FamilyManager.AddParameter(ParameterType)", legacy),
            ),
            log=self.log,
        )
        if result.failed:
            # A localised built-in (桥架宽度 for Width) owns the name, so the
            # family cannot hold a second parameter called like it: use a
            # suffixed twin and let the formula translation follow the name.
            twin = definition.name + PARAM_SUFFIX
            existing = {}
            for parameter in manager.Parameters:
                try:
                    existing[str(parameter.Definition.Name)] = parameter
                except Exception:  # noqa: BLE001
                    continue
            if twin in existing:
                self._family_params[definition.name] = existing[twin]
                self._spec_by_name[twin] = definition.spec
                self.log("    reusing the existing %s for %s" % (twin, definition.name))
                return api.fallback("%s is taken by a built-in; using %s" % (definition.name, twin))
            created[:] = []
            twin_result = _probe(
                (("FamilyManager.AddParameter(%s)" % twin, lambda: create(twin)),), log=self.log
            )
            if twin_result.failed:
                self.log("    add failed %s: %s" % (definition.name, result.message))
                return api.failed(f"could not create {definition.name}: {result.message}")
            if created and created[-1] is not None:
                self._family_params[definition.name] = created[-1]
            self._spec_by_name[twin] = definition.spec
            self.log("    created %s instead of %s (%s)" % (twin, definition.name, result.message))
            return api.fallback("%s is taken; created %s" % (definition.name, twin))
        # Keep the object Revit handed back: looking the parameter up again by
        # Definition.Name is what turned "Width" into "unknown parameter" once
        # the template already owned a parameter of that name.
        if created and created[-1] is not None:
            self._family_params[definition.name] = created[-1]
        return api.ok(f"instance {definition.spec}")

    def _param(self, doc, name: str):
        cached = self._family_params.get(name)
        if cached is not None:
            return cached
        for param in doc.FamilyManager.Parameters:
            if param.Definition.Name == name:
                return param
        self.log(
            "    parameter %r not found; the family holds: %s"
            % (name, ", ".join(self.parameter_inventory(doc)))
        )
        return None

    def parameter_inventory(self, doc) -> Sequence[str]:
        """Names Revit actually holds, for when a lookup went wrong."""
        names = []
        for param in doc.FamilyManager.Parameters:
            try:
                names.append(str(param.Definition.Name))
            except Exception:  # noqa: BLE001
                names.append("<no name>")
        return names

    def _revit_names(self) -> Dict[str, str]:
        """Model parameter name -> the name Revit actually stores.

        A family template may already own parameters called "Width", "Height",
        ... and hand back its own (possibly localised) definition when asked to
        add them again. Formulas are parsed by Revit against those real names.
        """
        mapping: Dict[str, str] = {}
        for model_name, parameter in self._family_params.items():
            try:
                actual = str(parameter.Definition.Name)
            except Exception:  # noqa: BLE001
                continue
            if actual and actual != model_name:
                mapping[model_name] = actual
        return mapping

    def translated_formula(self, formula: str) -> str:
        """Rewrite the identifiers in a formula to the names Revit holds."""
        mapping = self._revit_names()
        if not mapping:
            return formula
        pattern = re.compile(
            r"\b(?:%s)\b" % "|".join(re.escape(key) for key in sorted(mapping, key=len, reverse=True))
        )
        return pattern.sub(lambda match: mapping[match.group(0)], formula)

    def _unknown_references(self, doc, formula: str) -> List[str]:
        """Identifiers in a formula that the family does not have.

        Revit parses the text its own way, and a reference to a parameter that
        is not there does not always raise: the profile of the crash on the
        second family fits a formula referencing a parameter that was never
        created. Check the text against the parameters that exist first.
        """
        tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula or ""))
        known = set(self.parameter_inventory(doc))
        return sorted(token for token in tokens if token not in known and token not in FORMULA_WORDS)

    @staticmethod
    def _normalise_formula(formula: str) -> str:
        """Rewrite a leading unary minus as a subtraction.

        Revit's parser is happy with ``-Half_Height`` but the parenthesised form
        ``-(Half_Width + Cover_Overhang)`` is the kind of token sequence that has
        taken the process down; ``0 - (…)`` means the same and parses plainly.
        """
        text = (formula or "").strip()
        if text.startswith("-"):
            rest = text[1:].strip()
            if rest.startswith("(") and rest.endswith(")"):
                return "0 - %s" % rest
            return "0 - (%s)" % rest
        return text

    def set_formula(self, doc, name: str, formula: str) -> CapResult:
        self.log("    formula %s = %s" % (name, formula))
        param = self._param(doc, name)
        if param is None:
            return api.failed(f"unknown parameter {name}")
        if not param.IsInstance:
            return api.failed(f"{name} is a type parameter - formulas may not reference instances")
        translated = self._normalise_formula(self.translated_formula(formula))
        if translated != formula:
            self.log(f"    formula for {name} renamed to {translated!r}")
        unknown = self._unknown_references(doc, translated)
        if unknown:
            return api.failed(
                "%s: the formula references %s, which this family does not have"
                % (name, ", ".join(unknown))
            )
        try:
            doc.FamilyManager.SetFormula(param, translated)
            return api.ok(translated)
        except Exception as exc:  # noqa: BLE001
            return api.failed(f"{name}: {type(exc).__name__}: {exc}")

    def set_value(self, doc, name: str, value: Any) -> CapResult:
        self.log("    default %s = %r" % (name, value))
        param = self._param(doc, name)
        if param is None:
            return api.failed(f"unknown parameter {name}")
        spec = self._spec_by_name.get(name, SPEC_LENGTH)
        if spec == SPEC_MATERIAL:
            # a material parameter stores an element id, not the material name
            return api.skipped("material parameter is set from the element material")
        try:
            if isinstance(value, bool):
                doc.FamilyManager.Set(param, 1 if value else 0)
            elif isinstance(value, (int, float)):
                if spec == SPEC_ANGLE:
                    doc.FamilyManager.Set(param, self.units.angle_to_internal(float(value)))
                else:
                    doc.FamilyManager.Set(param, self.units.length_to_internal(float(value)))
            else:
                doc.FamilyManager.Set(param, str(value))
            return api.ok(str(value))
        except Exception as exc:  # noqa: BLE001
            return api.failed(f"{name}: {type(exc).__name__}: {exc}")

    # -- categories / materials ------------------------------------------- #
    def ensure_subcategory(self, doc, name: str) -> CapResult:
        category = doc.OwnerFamily.FamilyCategory
        try:
            for existing in category.SubCategories:
                if existing.Name == name:
                    return api.ok(f"{name} exists")
            doc.Settings.Categories.NewSubcategory(category, name)
            return api.ok(f"created {name}")
        except Exception as exc:  # noqa: BLE001
            return api.failed(f"{type(exc).__name__}: {exc}")

    def ensure_material(self, doc, name: str):
        for material in self.DB.FilteredElementCollector(doc).OfClass(self.DB.Material):
            if material.Name == name:
                return material
        try:
            created = self.DB.Material.Create(doc, name)
        except Exception:  # noqa: BLE001
            self.log(f"    could not create material {name}")
            return None
        # Material.Create returns the *identifier* of the new material, not the
        # material: resolve it so callers can use .Id and .Name.
        if getattr(created, "Name", None) is not None:
            return created
        try:
            resolved = doc.GetElement(created)
        except Exception:  # noqa: BLE001
            resolved = None
        return resolved if resolved is not None else created

    def ensure_cable_tray_fitting_category(self, doc) -> CapResult:
        try:
            category = doc.OwnerFamily.FamilyCategory
            if category is None:
                return api.failed("family has no category")
            expected = int(self.DB.BuiltInCategory.OST_CableTrayFitting)
            if element_id_value(category.Id) != expected:
                return api.failed(
                    f"family category is {category.Name}, expected Cable Tray Fitting - "
                    "re-run from 'Metric Cable Tray Fitting.rft'"
                )
            return api.ok("OST_CableTrayFitting")
        except Exception as exc:  # noqa: BLE001 - a capability must not kill the build
            return api.failed(f"{type(exc).__name__}: {exc}")

    def set_part_type(self, doc, part_type: str = "Elbow") -> CapResult:
        owner = doc.OwnerFamily
        enum_value = None
        for enum_name in ("PartType", "FamilyContentPartType"):
            enum = getattr(self.DB, enum_name, None)
            if enum is None:
                continue
            enum_value = getattr(enum, part_type, None)
            if enum_value is not None:
                break
        if enum_value is None:
            return api.fallback(f"no PartType.{part_type} enum in this Revit release")

        def via_bip():
            bip = getattr(self.DB.BuiltInParameter, "FAMILY_CONTENT_PART_TYPE", None)
            if bip is None:
                raise AttributeError("FAMILY_CONTENT_PART_TYPE missing")
            param = owner.get_Parameter(bip)
            if param is None:
                raise AttributeError("not found on the OwnerFamily")
            param.Set(enum_value)
            return True

        def via_property():
            setattr(owner, "FamilyContentPartType", enum_value)
            return True

        result = _probe(
            (
                ("OwnerFamily FAMILY_CONTENT_PART_TYPE", via_bip),
                ("OwnerFamily.FamilyContentPartType", via_property),
            ),
            log=self.log,
        )
        if result.failed:
            return api.fallback(
                "part type not settable via API - set once in the Family Editor: "
                "Family Category and Parameters -> Part Type = Elbow"
            )
        return api.ok(result.message)

    # -- geometry ---------------------------------------------------------- #
    def _internal(self, point):
        """Millimetres (the family model's unit) to Revit internal units."""
        return tuple(self.units.length_to_internal(float(component)) for component in point)

    def _sketch_plane(self, doc, frame):
        plane = self.Plane.CreateByOriginAndBasis(
            self.XYZ(*self._internal(frame.origin)), self.XYZ(*frame.ex), self.XYZ(*frame.ey)
        )
        return self.DB.SketchPlane.Create(doc, plane)

    def create_extrusion(self, doc, solid_def, loops, start: float, end: float):
        frame = solid_def.frame
        profile = self.DB.CurveArrArray()
        for loop in loops:
            curve_array = self.DB.CurveArray()
            count = len(loop)
            for index in range(count):
                u1, v1 = loop[index]
                u2, v2 = loop[(index + 1) % count]
                p1 = self.XYZ(*self._internal(frame.to_world(u1, v1, 0.0)))
                p2 = self.XYZ(*self._internal(frame.to_world(u2, v2, 0.0)))
                curve_array.Append(self.Line.CreateBound(p1, p2))
            profile.Append(curve_array)
        sketch_plane = self._sketch_plane(doc, frame)
        extrusion = doc.FamilyCreate.NewExtrusion(True, profile, sketch_plane, 1.0)
        try:
            extrusion.StartOffset = self.units.length_to_internal(start)
            extrusion.EndOffset = self.units.length_to_internal(end)
        except Exception as exc:  # noqa: BLE001
            self.log(f"    StartOffset/EndOffset assignment failed: {exc}")
        return extrusion

    def associate_extrusion_offsets(self, doc, element, start_param: str, end_param: str) -> CapResult:
        manager = doc.FamilyManager
        attempts = []
        for bip_name, param_name in (("EXTRUSION_START_PARAM", start_param), ("EXTRUSION_END_PARAM", end_param)):
            bip = getattr(self.DB.BuiltInParameter, bip_name, None)
            if bip is None:
                return api.fallback(f"{bip_name} is not exposed in this Revit release")
            element_param = element.get_Parameter(bip)
            family_param = self._param(doc, param_name)
            if element_param is None or family_param is None:
                return api.fallback(f"{bip_name}: element or family parameter missing")

            def bind(element_param=element_param, family_param=family_param):
                manager.AssociateElementParameterToFamilyParameter(element_param, family_param)
                return True

            attempts.append((bip_name, bind))
        return _probe(attempts, log=self.log)

    # -- sketch dimensions ------------------------------------------------- #
    def apply_sketch_dimensions(self, doc, element, requests: Sequence[LabelRequest], values) -> CapResult:
        """Label the profile's dimensions so the sketch follows the parameters.

        Steps: locate the extrusion's ``Sketch`` -> open a ``SketchEditScope`` ->
        for each request build a dimension between the two profile lines (or a
        line and an origin reference plane) and set ``Dimension.FamilyLabel``.
        Any failure degrades to ``FALLBACK`` with the labelling table logged.
        """
        if not requests:
            return api.skipped("nothing to label")
        sketch = self._find_sketch(doc, element, requests)
        if sketch is None:
            return self._fallback_labels(requests, "extrusion sketch not reachable")
        try:
            scope = self.DB.SketchEditScope(doc, "label trunking profile")
        except Exception as exc:  # noqa: BLE001
            return self._fallback_labels(requests, f"SketchEditScope unavailable: {exc}")

        labelled = 0
        try:
            scope.Start(sketch.Id)
            curves = self._sketch_curves(sketch)
            if not curves:
                raise RuntimeError("sketch curves not exposed by sketch.Profile")
            view = self._dimension_view(doc)
            for request in requests:
                target = self._match_curve(curves, request.target_mid)
                if target is None:
                    continue
                if request.ref_kind == "line":
                    ref = self._match_curve(curves, request.ref_mid)
                    if ref is None:
                        continue
                else:
                    ref = self._reference_plane(doc, request.ref_plane)
                    if ref is None:
                        continue
                if self._add_dimension(doc, view, ref, target, request):
                    labelled += 1
            scope.Commit(None)
        except Exception as exc:  # noqa: BLE001
            try:
                scope.Cancel()
            except Exception:  # noqa: BLE001
                pass
            return self._fallback_labels(requests, f"{type(exc).__name__}: {exc}")
        if labelled != len(requests):
            return self._fallback_labels(
                requests, f"only {labelled}/{len(requests)} dimensions could be created and labelled"
            )
        return api.ok(f"{labelled} labelled sketch dimensions")

    def _fallback_labels(self, requests: Sequence[LabelRequest], reason: str) -> CapResult:
        self.log("    manual labelling needed:")
        for request in requests:
            self.log(f"      {request.solid}[{request.loop}] {request.axis}: label = {request.label}")
        return api.fallback(reason + " - see docs/03-manual-labelling.md and the printed table")

    def _find_sketch(self, doc, element, requests: Sequence[LabelRequest]):
        expected = requests[0].target_mid if requests else None
        for attr in ("Sketch", "SketchId"):
            value = getattr(element, attr, None)
            if value is None:
                continue
            if hasattr(value, "Id"):
                return value
            try:  # SketchId is an ElementId, not a Sketch
                sketch = doc.GetElement(value)
                if sketch is not None:
                    return sketch
            except Exception:  # noqa: BLE001
                pass
        try:
            candidates = list(self.DB.FilteredElementCollector(doc).OfClass(self.DB.Sketch))
        except Exception:  # noqa: BLE001
            return None
        if len(candidates) == 1:
            return candidates[0]
        best = None
        best_distance = 1e9
        for sketch in candidates:
            curves = self._sketch_curves(sketch)
            if not curves:
                continue
            if expected is None:
                return sketch
            point = self.XYZ(*expected)
            distance = min(
                (curve.GetEndPoint(0) - point).GetLength() + (curve.GetEndPoint(1) - point).GetLength()
                for curve in curves
            )
            if distance < best_distance:
                best_distance, best = distance, sketch
        return best

    def _sketch_curves(self, sketch) -> List[Any]:
        curves: List[Any] = []
        try:
            profile = sketch.Profile
            for index in range(profile.Size):
                loop = profile.get_Item(index)
                for i in range(loop.Size):
                    curves.append(loop.get_Item(i))
        except Exception:  # noqa: BLE001
            return []
        return curves

    def _match_curve(self, curves: Sequence[Any], midpoint) -> Optional[Any]:
        target = self.XYZ(*midpoint)
        best, best_distance = None, 1e9
        for curve in curves:
            try:
                mid = curve.Evaluate(0.5, True)
            except Exception:  # noqa: BLE001
                mid = (curve.GetEndPoint(0) + curve.GetEndPoint(1)) * 0.5
            distance = (mid - target).GetLength()
            if distance < best_distance:
                best_distance, best = distance, curve
        # Refuse to guess: a wrong curve would silently label the wrong geometry,
        # which is far worse than degrading to the manual labelling table.
        return best if best_distance < 1.0 * MM_PER_FOOT else None

    def _dimension_view(self, doc):
        active = doc.ActiveView
        if active is not None and not active.IsTemplate:
            return active
        for view in self.DB.FilteredElementCollector(doc).OfClass(self.DB.View):
            if not view.IsTemplate and view.ViewType in (
                self.DB.ViewType.FloorPlan,
                self.DB.ViewType.Elevation,
                self.DB.ViewType.Section,
            ):
                return view
        return active

    def _reference_plane(self, doc, name: Optional[str]):
        if not name:
            return None
        for plane in self.DB.FilteredElementCollector(doc).OfClass(self.DB.ReferencePlane):
            if plane.Name == name:
                return plane.GetReference()
        return None

    def _add_dimension(self, doc, view, ref_a, ref_b, request: LabelRequest) -> bool:
        try:
            refs = self.DB.ReferenceArray()
            refs.Append(ref_a)
            refs.Append(ref_b)
            p_ref = self.XYZ(*self._internal(request.ref_mid))
            p_target = self.XYZ(*self._internal(request.target_mid))
            if (p_target - p_ref).GetLength() < 1e-6:
                raise RuntimeError("degenerate dimension line")
            line = self.Line.CreateBound(p_ref, p_target)
            dimension = doc.Create.NewDimension(view, line, refs)
            family_param = self._param(doc, request.label)
            dimension.FamilyLabel = family_param
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"      dimension {request.label} failed: {type(exc).__name__}: {exc}")
            return False

    # -- visibility / materials ------------------------------------------- #
    def set_detail_visibility(self, doc, element, detail: str) -> CapResult:
        coarse = detail == "coarse"
        medium = detail in ("coarse", "medium")
        fine = detail in ("coarse", "medium", "fine")
        if detail == "medium":
            coarse, medium, fine = False, True, True
        elif detail == "fine":
            coarse, medium, fine = False, False, True

        def build_visibility():
            visibility = self.DB.FamilyElementVisibility(self.DB.FamilyElementVisibilityType.Model)
            visibility.IsShownInCoarse = coarse
            visibility.IsShownInMedium = medium
            visibility.IsShownInFine = fine
            visibility.IsShownInTopBottom = True
            visibility.IsShownInFrontBack = True
            visibility.IsShownInLeftRight = True
            return visibility

        def element_set_visibility():
            setter = getattr(element, "SetVisibility", None)
            if setter is None:
                raise AttributeError("Element.SetVisibility")
            setter(build_visibility())
            return True

        def doc_set_visibility():
            setter = getattr(doc, "SetElementVisibility", None) or getattr(doc, "SetFamilyElementVisibility", None)
            if setter is None:
                raise AttributeError("Document.SetElementVisibility")
            setter(element, build_visibility())
            return True

        result = _probe(
            (("Element.SetVisibility", element_set_visibility), ("Document.SetElementVisibility", doc_set_visibility)),
            log=self.log,
        )
        if result.failed:
            return api.fallback(
                "per-element detail-level visibility is not reachable through the API on this release; "
                "solids stay visible at all detail levels (the coarse symbolic line is still drawn)"
            )
        return result

    def associate_visibility(self, doc, element, show_param: str) -> CapResult:
        family_param = self._param(doc, show_param)
        if family_param is None:
            return api.failed(f"{show_param} is not a family parameter")
        for name in ("FAMILY_ELEMENT_IS_VISIBLE", "VISIBLE", "ELEMENT_VISIBILITY", "FAMILY_ELEMENT_VISIBILITY"):
            bip = getattr(self.DB.BuiltInParameter, name, None)
            if bip is None:
                continue
            element_param = element.get_Parameter(bip)
            if element_param is None:
                continue
            try:
                doc.FamilyManager.AssociateElementParameterToFamilyParameter(element_param, family_param)
                return api.ok(f"{show_param} -> {name}")
            except Exception:  # noqa: BLE001
                continue
        return api.fallback(
            f"{show_param} cannot drive solid visibility on this Revit release (no parameter-driven "
            "element visibility); the parameter is still created for schedules and automation"
        )

    def set_element_material(self, doc, element, material_param: str, material) -> CapResult:
        if material is None:
            return api.skipped("material missing")
        bip = getattr(self.DB.BuiltInParameter, "MATERIAL_ID_PARAM", None)
        if bip is None:
            return api.fallback("MATERIAL_ID_PARAM unavailable")
        element_param = element.get_Parameter(bip)
        if element_param is None:
            return api.fallback("element material parameter missing")
        try:
            element_param.Set(element_id_of(material))
        except Exception as exc:  # noqa: BLE001
            self.log(f"    material set failed: {exc}")
        name = _material_name(doc, material)
        family_param = self._param(doc, material_param)
        if family_param is not None:
            try:
                doc.FamilyManager.AssociateElementParameterToFamilyParameter(element_param, family_param)
                return api.ok(f"{name} bound to {material_param}")
            except Exception:  # noqa: BLE001
                pass
        return api.ok(f"{name} (fixed)")

    # -- connectors -------------------------------------------------------- #
    def create_cable_tray_connector(self, doc, connector_def, values, host_element):
        origin = tuple(float(expr.evaluate(c, values)) for c in connector_def.origin)
        width_int = self.units.length_to_internal(float(values["Width"]))
        height_int = self.units.length_to_internal(float(values["Height"]))
        plane_origin = self.XYZ(*self._internal(origin))
        plane = self.Plane.CreateByOriginAndBasis(
            plane_origin, self.XYZ(*connector_def.basis_x), self.XYZ(*connector_def.basis_y)
        )

        attempts = []
        face_ref = self._port_face_reference(host_element, plane_origin)
        if face_ref is not None:
            attempts.append(
                (
                    "CreateCableTrayConnector(face) - hosted, follows the parameters",
                    lambda: self.DB.ConnectorElement.CreateCableTrayConnector(doc, face_ref, width_int, height_int),
                )
            )
        attempts.append(
            (
                "CreateCableTrayConnector(plane) - fixed position, size still bound",
                lambda: self.DB.ConnectorElement.CreateCableTrayConnector(doc, plane, width_int, height_int),
            )
        )
        # Revit 2027 only keeps the reference overloads: the size comes from
        # bind_connector_size() afterwards (builder step 6b).
        if face_ref is not None:
            attempts.append(
                (
                    "CreateCableTrayConnector(face) - 2027 overload",
                    lambda: self.DB.ConnectorElement.CreateCableTrayConnector(doc, face_ref),
                )
            )
        attempts.append(
            (
                "CreateCableTrayConnector(plane) - 2027 overload",
                lambda: self.DB.ConnectorElement.CreateCableTrayConnector(doc, plane),
            )
        )
        for label, call in attempts:
            try:
                connector = call()
            except Exception as exc:  # noqa: BLE001
                self.log(f"    {label} failed: {type(exc).__name__}: {exc}")
                continue
            if connector is not None:
                self.log(f"    connector {connector_def.name}: {label}")
                return connector
        return None

    def _port_face_reference(self, element, plane_origin):
        if element is None:
            return None
        try:
            options = self.DB.Options()
            options.ComputeReferences = True
            options.DetailLevel = self.DB.ViewDetailLevel.Fine
            found = None
            for obj in element.get_Geometry(options):
                solid = obj if isinstance(obj, self.DB.Solid) else None
                if solid is None:
                    continue
                for face in solid.Faces:
                    if not isinstance(face, self.DB.PlanarFace):
                        continue
                    if abs((face.Origin - plane_origin).DotProduct(face.FaceNormal)) < 1e-4:
                        found = face.Reference
            return found
        except Exception:  # noqa: BLE001
            return None

    def bind_connector_size(self, doc, connector, width_param: str, height_param: str) -> CapResult:
        """Bind the connector width/height to the family parameters.

        Revit 2027 dropped the width/height overloads of
        ``CreateCableTrayConnector``, so the size can only follow the family
        through this association. The parameter names also moved: the assembly
        only carries ``CONNECTOR_WIDTH``/``CONNECTOR_HEIGHT`` now, the ``RBS_*``
        spellings are kept for older releases.
        """
        manager = doc.FamilyManager
        bound = []
        missing = []
        axes = (
            ("CONNECTOR_WIDTH", "RBS_CONNECTOR_WIDTH", "RBS_CABLETRAYCONNECTOR_WIDTH"),
            ("CONNECTOR_HEIGHT", "RBS_CONNECTOR_HEIGHT", "RBS_CABLETRAYCONNECTOR_HEIGHT"),
        )
        for candidates, family_name in zip(axes, (width_param, height_param)):
            family_parameter = self._param(doc, family_name)
            if family_parameter is None:
                missing.append("%s (family parameter)" % family_name)
                continue
            element_parameter = None
            used = ""
            for candidate in candidates:
                bip = getattr(self.DB.BuiltInParameter, candidate, None)
                if bip is None:
                    continue
                element_parameter = connector.get_Parameter(bip)
                if element_parameter is not None:
                    used = candidate
                    break
            if element_parameter is None:
                missing.append("%s (connector parameter)" % candidates[0])
                continue
            try:
                manager.AssociateElementParameterToFamilyParameter(element_parameter, family_parameter)
                bound.append(used)
            except Exception as exc:  # noqa: BLE001
                missing.append("%s: %s: %s" % (used, type(exc).__name__, exc))
        if bound and not missing:
            return api.ok("bound " + ", ".join(bound))
        if bound:
            return api.fallback("bound %s; failed %s" % (", ".join(bound), ", ".join(missing)))
        return api.failed("no connector size bound: " + "; ".join(missing))

    def link_connectors(self, doc, first, second) -> CapResult:
        try:
            first.SetLinkedConnectorElement(second)
            return api.ok("SetLinkedConnectorElement")
        except Exception as exc:  # noqa: BLE001
            return api.failed(f"{type(exc).__name__}: {exc}")

    # -- annotation -------------------------------------------------------- #
    def create_symbolic_line(self, doc, symbol_def, values) -> CapResult:
        try:
            if symbol_def.frame_name == "XY":
                ex, ey = self.XYZ(1, 0, 0), self.XYZ(0, 1, 0)
            else:
                ex, ey = self.XYZ(1, 0, 0), self.XYZ(0, 0, 1)
            plane = self.Plane.CreateByOriginAndBasis(self.XYZ(0, 0, 0), ex, ey)
            sketch_plane = self.DB.SketchPlane.Create(doc, plane)
            points = [tuple(float(expr.evaluate(c, values)) for c in p) for p in symbol_def.points]
            for a, b in zip(points[:-1], points[1:]):
                doc.FamilyCreate.NewSymbolicCurve(
                    self.Line.CreateBound(self.XYZ(*self._internal(a)), self.XYZ(*self._internal(b))),
                    sketch_plane,
                )
            return api.ok(f"{len(points) - 1} segments")
        except Exception as exc:  # noqa: BLE001
            return api.fallback(f"symbolic centerline not created: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# template discovery
# --------------------------------------------------------------------------- #
TEMPLATE_FILENAME = "Metric Cable Tray Fitting.rft"

#: Pre-2027 layout, kept for reference and for the fallback search.
TEMPLATE_RELATIVE = os.path.join(
    "Family Templates", "English", "Metric", "Cable Tray", TEMPLATE_FILENAME
)

#: Locales to probe, in order. ``English`` first keeps an existing install's
#: language; zh-TW installs only ship ``Traditional Chinese`` and Simplified
#: Chinese is ``Chinese`` in both the 2024 and 2027 template trees.
TEMPLATE_LOCALES = (
    "English",
    "Traditional Chinese",
    "Chinese",
    "English-Imperial",
    "Japanese",
    "Korean",
    "Russian",
    "French",
    "German",
)

#: Revit releases to probe, newest first.
TEMPLATE_YEARS = (2027, 2026, 2025, 2024, 2023, 2022, 2021, 2020)


def _template_roots(years: Sequence[int] = TEMPLATE_YEARS) -> List[str]:
    """Template roots to probe: known releases first, then whatever is installed."""
    roots: List[str] = []
    for year in years:
        for pattern in (
            r"C:\ProgramData\Autodesk\RVT {0}",
            r"C:\Program Files\Autodesk\Revit {0}",
        ):
            candidate = pattern.format(year)
            if candidate not in roots:
                roots.append(candidate)
    for pattern in (r"C:\ProgramData\Autodesk\RVT *", r"C:\Program Files\Autodesk\Revit *"):
        for found in sorted(glob.glob(pattern), reverse=True):
            if found not in roots:
                roots.append(found)
    return roots


def _locale_candidates(base: str, filename: str = TEMPLATE_FILENAME) -> List[str]:
    """Candidate paths under one install root, flat layout before the old one.

    Revit 2027 ships the template flat inside the locale folder
    (``Family Templates\\Traditional Chinese\\Metric Cable Tray Fitting.rft``)
    while pre-2027 keeps the category folders
    (``Family Templates\\English\\Metric\\Cable Tray\\...``).
    """
    family_templates = os.path.join(base, "Family Templates")
    candidates: List[str] = []
    for locale in TEMPLATE_LOCALES:
        candidates.append(os.path.join(family_templates, locale, filename))
        candidates.append(
            os.path.join(family_templates, locale, "Metric", "Cable Tray", filename)
        )
    return candidates


def _walk_for(base: str, filename: str = TEMPLATE_FILENAME, max_depth: int = 4) -> Optional[str]:
    """Last resort: look for the file anywhere under ``Family Templates``."""
    family_templates = os.path.join(base, "Family Templates")
    if not os.path.isdir(family_templates):
        return None
    root_depth = family_templates.rstrip("\\/").count(os.sep)
    for dirpath, dirnames, filenames in os.walk(family_templates):
        if dirpath.count(os.sep) - root_depth >= max_depth:
            dirnames[:] = []
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def find_template(
    explicit: Optional[str] = None, years: Sequence[int] = TEMPLATE_YEARS
) -> Optional[str]:
    """Locate ``Metric Cable Tray Fitting.rft`` (env var, then default installs).

    The install layout differs between releases: 2027 puts the template flat in
    the locale folder and a zh-TW install only has ``Traditional Chinese``, so a
    fixed path guess misses.  Order: explicit argument, ``TRUNKING_TEMPLATE``,
    the known locale/layout combinations, then a bounded walk.
    """
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    env = os.environ.get("TRUNKING_TEMPLATE")
    if env and os.path.isfile(env):
        return env
    roots = _template_roots(years)
    for base in roots:
        for candidate in _locale_candidates(base):
            if os.path.isfile(candidate):
                return candidate
    for base in roots:
        found = _walk_for(base)
        if found:
            return found
    return None
