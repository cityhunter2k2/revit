#! python3
# -*- coding: utf-8 -*-
"""
Trunking 90-degree bends - FRONT OPENING (正面蓋型)  ->  parametric Revit families (.rfa)
=========================================================================================
Target : Autodesk Revit 2027 (.NET 8)  +  pyRevit 7.1  (IronPython 3.4 / IronPython 2.7 / CPython 3)
Output : 2 families, ONE type ("Standard") each, ALL sizes driven by INSTANCE parameters
           1) Trunking_90_MitreBend_FrontOpening.rfa   (90 deg mitre bend  - outer corner 90, inner corner 45-deg edge)
           2) Trunking_90_SharpBend_FrontOpening.rfa   (90 deg sharp bend  - outer corner 90, inner corner 90)
Category: Cable Tray Fittings, Part Type = horizontal bend (Channel Elbow), 2 cable-tray connectors (linked).

Geometry (mm, family origin = intersection of the two trunking centre lines, Z up)
   W = Width, H = Height, Stub = 75
   CenterToEnd = W/2 + Stub        A = B = W + Stub
   Mitre outline (5 pts) : (-W/2,-W/2) (+W/2+75,-W/2) (+W/2+75,+W/2) (+W/2,+W/2+75) (-W/2,+W/2+75)
   Sharp outline (6 pts) : (-W/2,-W/2) (+W/2+75,-W/2) (+W/2+75,+W/2) (+W/2,+W/2) (+W/2,+W/2+75) (-W/2,+W/2+75)
   Z range -H/2 .. +H/2 ; cover on +Z (top, flush with +H/2) ; cover screw heads protrude 3 mm.

Install : <Your>.extension/<Tab>.tab/<Panel>.panel/<Name>.pushbutton/script.py
"""
__title__ = u"Trunking\nBend RFA"
__author__ = u"MEP BIM Family Tools"
__doc__ = (u"Generate 2 parametric 90-degree trunking bend families (Front opening: mitre / sharp). "
           u"One 'Standard' type, all instance parameters, Flexing-validated for 9 + 2 sizes.")

import clr
import os
import sys
import math
import traceback

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

# Explicit imports: "from Autodesk.Revit.DB import *" does not export everything
# under pythonnet - XYZ was missing from it - so every type is named here.
from Autodesk.Revit.DB import (  # noqa: F401
    Arc, BuiltInCategory, BuiltInParameter, Category, Color, ConnectorElement,
    CurveArrArray, CurveArray, ElementId, ElementTransformUtils,
    FailureProcessingResult, FailureSeverity, Family, FamilyElementVisibility,
    FamilyElementVisibilityType, FamilyParameter, FamilySource,
    FilteredElementCollector, GroupTypeId, IFailuresPreprocessor,
    IFamilyLoadOptions, Line, Material, Options, PartType, PlanarFace, Plane,
    Reference, ReferenceArray, ReferencePlane, SaveAsOptions, SketchPlane, Solid,
    SpecTypeId, Transaction, TransactionStatus, UnitTypeId, UnitUtils, View,
    ViewType, XYZ,
)

from pyrevit import script, HOST_APP

# pyrevit.forms is a stub backend on the CPython engine: pick_file, pick_folder
# and alert all raise PyRevitCPythonNotSupported, and any other attribute of the
# module raises too. Nothing here may use it.


def _routing_table(doc):
    """Every Cable Tray Fitting family in the project with its part type.

    Routing Preferences lists a family only when its category and part type
    match, so this table shows side by side what Revit sees for ours and for the
    families that do appear in the list.
    """
    rows = []
    if doc is None or doc.IsFamilyDocument:
        return rows
    try:
        cat = Category.GetCategory(doc, BuiltInCategory.OST_CableTrayFitting)
    except Exception:
        return rows
    if cat is None:
        return rows
    for fam in FilteredElementCollector(doc).OfClass(Family):
        try:
            if fam.FamilyCategory is None or fam.FamilyCategory.Id.Value != cat.Id.Value:
                continue
        except Exception:
            continue
        label, value = "?", "?"
        try:
            prm = fam.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
            if prm is not None:
                value = str(prm.AsInteger())
                label = prm.AsValueString() or "?"
        except Exception as ex:
            label = "error: {0}".format(ex)
        types = 0
        try:
            types = len(list(fam.GetFamilySymbolIds()))
        except Exception:
            pass
        rows.append([fam.Name, label, value, str(types)])
    return rows


def _alert(message, title=u"Trunking Bend RFA"):
    """Report through the output window and the log instead of a dialog."""
    try:
        output = script.get_output()
        output.print_md(u"**{0}**".format(title))
        output.print_md(u"{0}".format(message))
    except Exception:
        pass
    log(u"{0}: {1}".format(title, message))


def _output_folder():
    """TRUNKING_OUT, else Documents\\Trunking\\families - no folder dialog."""
    folder = os.environ.get("TRUNKING_OUT")
    if not folder:
        folder = os.path.join(os.path.expanduser("~"), "Documents", "Trunking", "families")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def _load_env_file():
    """Apply trunking.env from the repo root (KEY=VALUE, TRUNKING_* only)."""
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(current, "trunking.env")
        if os.path.isfile(candidate):
            try:
                handle = open(candidate)
                try:
                    for raw in handle:
                        line = raw.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        if key.startswith("TRUNKING_"):
                            os.environ[key] = value.strip()
                finally:
                    handle.close()
                return candidate
            except Exception:
                return None
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None

# ----------------------------------------------------------------------------------------
# 0. CONFIGURATION (all values in millimetres unless noted)
# ----------------------------------------------------------------------------------------
TEMPLATE_ROOT = u"C:\\ProgramData\\Autodesk\\RVT 2027\\Family Templates"

FAMILY_SPECS = [
    {"key": "mitre", "mitre": True,
     "file": u"Trunking_90_MitreBend_FrontOpening.rfa",
     "label": "MitreBend_FrontOpening"},
    {"key": "sharp", "mitre": False,
     "file": u"Trunking_90_SharpBend_FrontOpening.rfa",
     "label": "SharpBend_FrontOpening"},
]

STD_SIZES = [(50, 50), (75, 50), (75, 75), (100, 75), (100, 100),
             (150, 100), (150, 150), (200, 150), (200, 200)]
EXTRA_SIZES = [(300, 100), (50, 100)]

DEFAULT_W = 100.0
DEFAULT_H = 100.0
STUB_MM = 75.0            # straight stub length  -> CenterToEnd = W/2 + 75
FLANGE_MM = 25.0          # coupling tab length (Flange_Length)
HOLE_D_MM = 6.0           # coupling tab screw hole diameter (Hole_Diameter)
SCREW_D_MM = 8.0          # cover screw head diameter (M5/M6 pan head)
SCREW_H_MM = 3.0          # cover screw head protrusion above the cover
SCREW_END_MM = 15.0       # screw centre distance to the port edge
SCREW_SIDE_MM = 10.0      # screw centre distance to the side wall (inner face line)

SQRT2 = math.sqrt(2.0)
TOL_MM = 0.5              # flexing tolerance
TOL_FT = 1.0e-5           # geometric matching tolerance (feet)
PLANE_EXTENT_MM = 450.0   # visual half-length of the reference planes
DIM_BASE_MM = 260.0       # dimension line offset
DIM_STEP_MM = 18.0

# Revit formula (no "<=" in Revit formulas -> not(x > limit)); T10 / T12 / T14 / T16
WALL_FORMULA = ("if(and(not(Width > 50 mm), not(Height > 50 mm)), 1.0 mm, "
                "if(and(not(Width > 100 mm), not(Height > 75 mm)), 1.2 mm, "
                "if(and(not(Width > 150 mm), not(Height > 100 mm)), 1.4 mm, 1.6 mm)))")

# PartType: cable-tray fittings use the Channel/Ladder part types. "Elbow" (5) is the duct/pipe one and is only
# kept as the last fallback. The first value that Revit accepts (read-back verified) is used.
PART_TYPE_CANDIDATES = ("ChannelCableTrayElbow", "Elbow")

# CONNECTOR_ANGLE is the connector's own "Angle" property; binding the 90-deg family angle to it could be read as
# a connector rotation and swap width/height. Disabled by default - set True only if you know you need it.
BIND_CONNECTOR_ANGLE = False

LOD_BODY = (False, True, True)      # Coarse / Medium / Fine : U-body + cover
LOD_FINE = (False, False, True)     # tabs + screws          : Fine only
LOD_CENTER = (True, False, False)   # 2D centre line         : Coarse only

LAST_FAILURES = []


def wall_thickness_mm(w, h):
    """Python twin of the Revit WallThickness formula (T10/T12/T14/T16)."""
    if (not w > 50) and (not h > 50):
        return 1.0
    if (not w > 100) and (not h > 75):
        return 1.2
    if (not w > 150) and (not h > 100):
        return 1.4
    return 1.6


def mm(v):
    return UnitUtils.ConvertToInternalUnits(float(v), UnitTypeId.Millimeters)


def to_mm(v):
    return UnitUtils.ConvertFromInternalUnits(float(v), UnitTypeId.Millimeters)


def _clr_type(cls):
    try:
        return clr.GetClrType(cls)
    except Exception:
        return cls


def log(msg):
    try:
        print(msg)
    except Exception:
        pass


# ----------------------------------------------------------------------------------------
# 1. TRANSACTION HELPER (failure swallowing, rollback on errors, no modal dialogs)
# ----------------------------------------------------------------------------------------
try:
    class _FailureSwallower(IFailuresPreprocessor):
        def PreprocessFailures(self, accessor):
            has_error = False
            try:
                for msg in accessor.GetFailureMessages():
                    if msg.GetSeverity() == FailureSeverity.Warning:
                        accessor.DeleteWarning(msg)
                    else:
                        has_error = True
                        LAST_FAILURES.append(str(msg.GetDescriptionText()))
            except Exception as ex:
                LAST_FAILURES.append("failure-preprocessor: {}".format(ex))
            if has_error:
                return FailureProcessingResult.ProceedWithRollBack
            return FailureProcessingResult.Continue
    FAILURE_PREPROCESSOR = _FailureSwallower
except Exception:
    FAILURE_PREPROCESSOR = None


def run_tx(doc, name, func):
    """Run func() inside one Transaction. Raises RuntimeError when Revit rolls the transaction back."""
    t = Transaction(doc, name)
    t.Start()
    try:
        # Failure handling must never be able to abort the build: pythonnet
        # refuses to instantiate a class derived from a .NET interface
        # ("interface takes exactly one argument"), so every step here is
        # optional and the modal dialogs are disabled separately.
        try:
            fho = t.GetFailureHandlingOptions()
            try:
                fho.SetForcedModalHandling(False)
            except Exception:
                pass
            fho.SetClearAfterRollback(True)
            if FAILURE_PREPROCESSOR is not None:
                try:
                    fho.SetFailuresPreprocessor(FAILURE_PREPROCESSOR())
                except Exception as ex:
                    LAST_FAILURES.append("failure preprocessor unavailable: {}".format(ex))
            t.SetFailureHandlingOptions(fho)
        except Exception as ex:
            LAST_FAILURES.append("failure handling options unavailable: {}".format(ex))
        del LAST_FAILURES[:]
        result = func()
        status = t.Commit()
        if status != TransactionStatus.Committed:
            details = list(LAST_FAILURES)
            try:
                for warning in t.Document.GetWarnings():
                    details.append(str(warning.GetDescriptionText()))
            except Exception:
                pass
            raise RuntimeError("Transaction '{}' was not committed ({}): {}".format(
                name, status, "; ".join(details) or "no failure reported"))
        return result
    except Exception:
        try:
            if t.GetStatus() == TransactionStatus.Started:
                t.RollBack()
        except Exception:
            pass
        raise


# ----------------------------------------------------------------------------------------
# 2. FAMILY CONTEXT
# ----------------------------------------------------------------------------------------
class PlaneInfo(object):
    def __init__(self, key, axis, value_mm, rp, normal):
        self.key = key
        self.axis = axis
        self.mm = float(value_mm)
        self.ft = mm(value_mm)
        self.rp = rp
        self.ref = _plane_ref(rp)
        self.normal = normal


class Ctx(object):
    def __init__(self, app, fam_doc, spec):
        self.app = app
        self.doc = fam_doc
        self.spec = spec
        self.mitre = spec["mitre"]
        self.mgr = fam_doc.FamilyManager
        self.fc = fam_doc.FamilyCreate
        self.p = {}               # name -> FamilyParameter
        self.mat = {}             # name -> ElementId
        self.pl = {}              # key  -> PlaneInfo
        self.warnings = []
        self.solid_ids = []       # solid extrusion ids (bounding-box test)
        self.c_curve_id = None    # sketch line that represents "C"
        self.plan = None
        self.front = None
        self.side = None
        self.front_y = 0.0
        self.sk_z0 = None
        self.part_type_used = ""
        self.connector_info = ""

    def warn(self, msg):
        self.warnings.append(msg)
        log("   [warn] " + msg)

    def cur_ft(self, fp):
        return self.mgr.CurrentType.AsDouble(fp)

    def val_mm(self, name):
        return to_mm(self.cur_ft(self.p[name]))


def _plane_ref(rp):
    try:
        return rp.GetReference()
    except Exception:
        return rp.Reference


def _rp_plane(rp):
    """(normal, origin) of a ReferencePlane."""
    try:
        pl = rp.GetPlane()
        return pl.Normal, pl.Origin
    except Exception:
        return rp.Normal, rp.BubbleEnd


# ----------------------------------------------------------------------------------------
# 3. TEMPLATE LOOKUP
# ----------------------------------------------------------------------------------------
def find_template(app):
    roots = [TEMPLATE_ROOT]
    try:
        p = app.FamilyTemplatePath
        if p and p not in roots:
            roots.append(p)
    except Exception:
        pass
    zh_key = [u"电缆桥架", u"電纜橋架", u"桥架", u"橋架", u"电缆梯架", u"線槽", u"线槽"]
    zh_fit = [u"配件", u"管件", u"连接件", u"連接件"]
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            for f in fn:
                if not f.lower().endswith(".rft"):
                    continue
                lf = f.lower()
                en = ("cable tray" in lf) and ("fitting" in lf)
                zh = any(k in f for k in zh_key) and any(k in f for k in zh_fit)
                if en or zh:
                    score = 0
                    if "metric" in lf or u"公制" in f:
                        score -= 2
                    if "english" in dp.lower():
                        score -= 1
                    hits.append((score, os.path.join(dp, f)))
    if hits:
        hits.sort(key=lambda x: (x[0], len(x[1])))
        return hits[0][1]
    override = os.environ.get("TRUNKING_TEMPLATE")
    if override and os.path.isfile(override):
        return override
    raise RuntimeError(u"no cable tray fitting template (.rft) found; set TRUNKING_TEMPLATE to the full path, "
                       u"e.g. C:\\ProgramData\\Autodesk\\RVT 2027\\Family Templates\\Traditional Chinese\\"
                       u"Metric Cable Tray Fitting.rft")


# ----------------------------------------------------------------------------------------
# 4. PARAMETERS (everything is an INSTANCE parameter; exactly one type 'Standard')
# ----------------------------------------------------------------------------------------
INPUT_LENGTHS = [
    ("Width", DEFAULT_W), ("Height", DEFAULT_H), ("Stub", STUB_MM), ("Flange_Length", FLANGE_MM),
    ("Hole_Diameter", HOLE_D_MM), ("Screw_Head_Diameter", SCREW_D_MM), ("Screw_Head_Height", SCREW_H_MM),
    ("Screw_End_Offset", SCREW_END_MM), ("Screw_Side_Offset", SCREW_SIDE_MM),
]

DERIVED_LENGTHS = [
    ("CenterToEnd", "Width / 2 + Stub"),
    ("WallThickness", WALL_FORMULA),
    ("Half_Width", "Width / 2"),
    ("Half_Height", "Height / 2"),
    ("Neg_Half_Height", "-Height / 2"),
    ("Floor_Top_Z", "-Height / 2 + WallThickness"),
    ("Wall_Top_Z", "Height / 2 - WallThickness"),
    ("Neg_WallThickness", "-WallThickness"),
    ("Mitre_Wall_Offset", "WallThickness * 1.4142135624"),
    ("Hole_Radius", "Hole_Diameter / 2"),
    ("Hole_Axial_Offset", "Flange_Length / 2"),
    ("Hole_Z_Offset", "Height / 4"),
    ("Screw_Head_Radius", "Screw_Head_Diameter / 2"),
    ("Screw_Top_Z", "Height / 2 + Screw_Head_Height"),
]


def add_param(ctx, name, group, spec_type, is_instance=True):
    fp = ctx.mgr.get_Parameter(name)
    if fp is None:
        fp = ctx.mgr.AddParameter(name, group, spec_type, is_instance)
    elif bool(fp.IsInstance) != bool(is_instance):
        try:
            if is_instance:
                ctx.mgr.MakeInstance(fp)
            else:
                ctx.mgr.MakeType(fp)
        except Exception as ex:
            ctx.warn("parameter '{}' already exists as {} ({})".format(
                name, "instance" if fp.IsInstance else "type", ex))
    ctx.p[name] = fp
    return fp


def set_formula(ctx, name, formula):
    try:
        ctx.mgr.SetFormula(ctx.p[name], formula)
    except Exception:
        # locales with a decimal comma
        ctx.mgr.SetFormula(ctx.p[name], formula.replace(".", ","))


def ensure_single_type(ctx):
    """A new family from a template normally has no type. Exactly ONE type 'Standard' is created / kept.
    (NewType is only used for this single mandatory type - never for sizes.)"""
    mgr = ctx.mgr
    if mgr.Types.Size == 0:
        mgr.NewType("Standard")
    else:
        types = [t for t in mgr.Types]
        keep = types[0]
        for t in types[1:]:
            mgr.CurrentType = t
            mgr.DeleteCurrentType()
        mgr.CurrentType = keep
        if keep.Name != "Standard":
            mgr.RenameCurrentType("Standard")
    if mgr.CurrentType is None:
        raise RuntimeError("Family has no current type")


def get_or_create_material(doc, keywords, name, rgb):
    for m in FilteredElementCollector(doc).OfClass(_clr_type(Material)):
        nm = (m.Name or "").lower()
        if any(k in nm for k in keywords):
            return m.Id
    mid = Material.Create(doc, name)
    try:
        mat = doc.GetElement(mid)
        mat.Color = Color(rgb[0], rgb[1], rgb[2])
        mat.Shininess = 70
        mat.Smoothness = 60
    except Exception:
        pass
    return mid


def step_category_part_type_params(ctx):
    doc = ctx.doc
    fam = doc.OwnerFamily
    # --- category -------------------------------------------------------------------
    cat = Category.GetCategory(doc, BuiltInCategory.OST_CableTrayFitting)
    cur = fam.FamilyCategory
    if cur is None or cur.Id.Value != cat.Id.Value:
        fam.FamilyCategory = cat
    # --- part type: horizontal bend ------------------------------------------------
    prm = fam.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
    if prm is None:
        raise RuntimeError("FAMILY_CONTENT_PART_TYPE not found - is the template a cable tray fitting template?")
    for nm in PART_TYPE_CANDIDATES:
        pt = getattr(PartType, nm, None)
        if pt is None:
            continue
        try:
            if prm.Set(int(pt)) and prm.AsInteger() == int(pt):
                ctx.part_type_used = "{} ({})".format(nm, int(pt))
                break
        except Exception:
            continue
    if not ctx.part_type_used:
        # FAMILY_CONTENT_PART_TYPE is read-only in some 2027 fitting templates;
        # the Family property is the route that works there
        for nm in PART_TYPE_CANDIDATES:
            pt = getattr(PartType, nm, None)
            if pt is None:
                continue
            try:
                fam.FamilyContentPartType = pt
                check = fam.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
                if check is not None and check.AsInteger() == int(pt):
                    ctx.part_type_used = "{} ({}) via property".format(nm, int(pt))
                    break
            except Exception:
                continue
    if not ctx.part_type_used:
        ctx.warn("could not set a valid Part Type")

    # --- the single type -------------------------------------------------------------
    ensure_single_type(ctx)

    geo = GroupTypeId.Geometry
    # --- inputs (instance) ------------------------------------------------------------
    for name, val in INPUT_LENGTHS:
        add_param(ctx, name, geo, SpecTypeId.Length, True)
        ctx.mgr.Set(ctx.p[name], mm(val))
    add_param(ctx, "Angle", geo, SpecTypeId.Angle, True)
    ctx.mgr.Set(ctx.p["Angle"], math.radians(90.0))
    # --- derived (instance, formula) --------------------------------------------------
    for name, _f in DERIVED_LENGTHS:
        add_param(ctx, name, geo, SpecTypeId.Length, True)
    # --- visibility switches ------------------------------------------------------------
    for name in ("Show_Cover", "Show_Flanges", "Show_Fasteners"):
        add_param(ctx, name, GroupTypeId.Visibility, SpecTypeId.Boolean.YesNo, True)
        ctx.mgr.Set(ctx.p[name], 1)
    add_param(ctx, "Show_Cover_Screws", GroupTypeId.Visibility, SpecTypeId.Boolean.YesNo, True)
    # --- identity ---------------------------------------------------------------------------
    add_param(ctx, "Cover_Type", GroupTypeId.IdentityData, SpecTypeId.String.Text, True)
    ctx.mgr.Set(ctx.p["Cover_Type"], "QT")   # QT centre caption / ST screw fix / CT clip fix
    # --- materials --------------------------------------------------------------------------
    ctx.mat["Body_Material"] = get_or_create_material(doc, ["galvaniz"], "Galvanized Steel", (186, 192, 198))
    ctx.mat["Cover_Material"] = ctx.mat["Body_Material"]
    ctx.mat["Screw_Material"] = get_or_create_material(doc, ["stainless"], "Stainless Steel", (150, 154, 160))
    for name in ("Body_Material", "Cover_Material", "Screw_Material"):
        add_param(ctx, name, GroupTypeId.Materials, SpecTypeId.Reference.Material, True)
        ctx.mgr.Set(ctx.p[name], ctx.mat[name])
    # --- formulas -------------------------------------------------------------------------------
    for name, formula in DERIVED_LENGTHS:
        set_formula(ctx, name, formula)
    ctx.mgr.SetFormula(ctx.p["Show_Cover_Screws"], "and(Show_Cover, Show_Fasteners)")


# ----------------------------------------------------------------------------------------
# 5. VIEWS, REFERENCE PLANES, LABELLED DIMENSIONS
# ----------------------------------------------------------------------------------------
AXIS_VEC = {"X": XYZ(1, 0, 0), "Y": XYZ(0, 1, 0), "Z": XYZ(0, 0, 1)}


def step_find_views(ctx):
    plan = front = side = None
    for v in FilteredElementCollector(ctx.doc).OfClass(_clr_type(View)):
        try:
            if v.IsTemplate:
                continue
            vt = v.ViewType
            if vt == ViewType.FloorPlan:
                if plan is None or "ref" in v.Name.lower():
                    plan = v
            elif vt == ViewType.Elevation:
                d = v.ViewDirection
                if abs(abs(d.Y) - 1.0) < 1e-6:
                    if front is None or v.Name.lower() == "front":
                        front = v
                elif abs(abs(d.X) - 1.0) < 1e-6:
                    if side is None or v.Name.lower() in ("left", "right"):
                        side = v
        except Exception:
            continue
    if plan is None or front is None or side is None:
        raise RuntimeError("Template lacks a floor plan and front / side elevations (plan={}, front={}, side={})".format(
            plan is not None, front is not None, side is not None))
    ctx.plan, ctx.front, ctx.side = plan, front, side
    ctx.front_y = front.Origin.Y
    ctx.sk_z0 = SketchPlane.Create(ctx.doc, Plane.CreateByNormalAndOrigin(XYZ(0, 0, 1), XYZ(0, 0, 0)))


def _make_plane(ctx, key, axis, value_mm):
    v = mm(value_mm)
    L = mm(PLANE_EXTENT_MM)
    if axis == "X":
        view, b0, f0, cut = ctx.plan, XYZ(v, -L, 0), XYZ(v, L, 0), XYZ(0, 0, 1)
    elif axis == "Y":
        view, b0, f0, cut = ctx.plan, XYZ(-L, v, 0), XYZ(L, v, 0), XYZ(0, 0, 1)
    else:
        y0 = ctx.front_y
        view, b0, f0, cut = ctx.front, XYZ(-L, y0, v), XYZ(L, y0, v), XYZ(0, 1, 0)
    want = AXIS_VEC[axis]
    tries = [(b0, f0, cut), (f0, b0, cut), (b0, f0, cut.Negate()), (f0, b0, cut.Negate())]
    chosen = None
    chosen_n = None
    for (b, f, c) in tries:
        rp = ctx.fc.NewReferencePlane(b, f, c, view)
        n, _o = _rp_plane(rp)
        if n is None or n.DotProduct(want) > 0.99:
            chosen, chosen_n = rp, n
            break
        ctx.doc.Delete(rp.Id)
    if chosen is None:   # keep a plane with the "wrong" sign rather than failing
        chosen = ctx.fc.NewReferencePlane(b0, f0, cut, view)
        chosen_n, _o = _rp_plane(chosen)
        ctx.warn("plane '{}' normal could not be oriented to +{}".format(key, axis))
    chosen.Name = "TRK_" + key
    info = PlaneInfo(key, axis, value_mm, chosen, chosen_n)
    ctx.pl[key] = info
    return info


def plane_defs(mitre, w=DEFAULT_W, h=DEFAULT_H):
    """(key, axis, value_mm) of every parametric reference plane at the default size."""
    t = wall_thickness_mm(w, h)
    hw = w / 2.0
    ce = hw + STUB_MM
    out = []
    for ax in ("X", "Y"):
        out += [
            (ax + "_out", ax, -hw), (ax + "_out_T", ax, -hw + t),
            (ax + "_in_T", ax, hw - t), (ax + "_in", ax, hw),
            (ax + "_end", ax, ce), (ax + "_fl_end", ax, ce + FLANGE_MM),
            (ax + "_hole", ax, ce + FLANGE_MM / 2.0),
            (ax + "_scr_end", ax, ce - SCREW_END_MM),
            (ax + "_scr_pos", ax, hw - SCREW_SIDE_MM),
            (ax + "_scr_neg", ax, -(hw - SCREW_SIDE_MM)),
        ]
        if mitre:
            out.append((ax + "_in_D", ax, hw - t * SQRT2))
    out += [("Z_top", "Z", h / 2.0), ("Z_bot", "Z", -h / 2.0), ("Z_wall_top", "Z", h / 2.0 - t),
            ("Z_hole_up", "Z", h / 4.0), ("Z_hole_dn", "Z", -h / 4.0)]
    return out


def dim_defs(mitre):
    """(plane A, plane B, parameter) - exactly one driving dimension per movable plane."""
    out = []
    for ax in ("X", "Y"):
        out += [
            (ax + "_C", ax + "_in", "Half_Width"),
            (ax + "_C", ax + "_out", "Half_Width"),
            (ax + "_out", ax + "_out_T", "WallThickness"),
            (ax + "_in_T", ax + "_in", "WallThickness"),
            (ax + "_C", ax + "_end", "CenterToEnd"),
            (ax + "_end", ax + "_fl_end", "Flange_Length"),
            (ax + "_end", ax + "_hole", "Hole_Axial_Offset"),
            (ax + "_scr_end", ax + "_end", "Screw_End_Offset"),
            (ax + "_scr_pos", ax + "_in", "Screw_Side_Offset"),
            (ax + "_out", ax + "_scr_neg", "Screw_Side_Offset"),
        ]
        if mitre:
            out.append((ax + "_in_D", ax + "_in", "Mitre_Wall_Offset"))
    out += [("Z_C", "Z_top", "Half_Height"), ("Z_C", "Z_bot", "Half_Height"),
            ("Z_top", "Z_wall_top", "WallThickness"),
            ("Z_C", "Z_hole_up", "Hole_Z_Offset"), ("Z_C", "Z_hole_dn", "Hole_Z_Offset")]
    return out


def _register_centre_planes(ctx):
    found = {}
    for rp in FilteredElementCollector(ctx.doc).OfClass(_clr_type(ReferencePlane)):
        try:
            n, o = _rp_plane(rp)
            if abs(n.X) > 0.99 and abs(o.X) < 1e-6 and "X" not in found:
                found["X"] = (rp, n)
            elif abs(n.Y) > 0.99 and abs(o.Y) < 1e-6 and "Y" not in found:
                found["Y"] = (rp, n)
            elif abs(n.Z) > 0.99 and abs(o.Z) < 1e-6 and "Z" not in found:
                found["Z"] = (rp, n)
        except Exception:
            continue
    for ax in ("X", "Y", "Z"):
        if ax in found:
            rp, n = found[ax]
            ctx.pl[ax + "_C"] = PlaneInfo(ax + "_C", ax, 0.0, rp, n)
        else:
            _make_plane(ctx, ax + "_C", ax, 0.0)
        try:
            ctx.pl[ax + "_C"].rp.Pinned = True      # the origin planes must never move
        except Exception:
            pass


def label_dimension(ctx, ka, kb, pname, lane):
    a, b = ctx.pl[ka], ctx.pl[kb]
    off = mm(-(DIM_BASE_MM + DIM_STEP_MM * lane))
    if a.axis == "X":
        view, p0, p1 = ctx.plan, XYZ(a.ft, off, 0), XYZ(b.ft, off, 0)
    elif a.axis == "Y":
        view, p0, p1 = ctx.plan, XYZ(off, a.ft, 0), XYZ(off, b.ft, 0)
    else:
        view, p0, p1 = ctx.front, XYZ(off, ctx.front_y, a.ft), XYZ(off, ctx.front_y, b.ft)
    refs = ReferenceArray()
    refs.Append(a.ref)
    refs.Append(b.ref)
    dim = ctx.fc.NewDimension(view, Line.CreateBound(p0, p1), refs)
    dim.FamilyLabel = ctx.p[pname]
    return dim


def step_planes_and_dimensions(ctx):
    step_find_views(ctx)
    _register_centre_planes(ctx)
    for key, axis, val in plane_defs(ctx.mitre):
        _make_plane(ctx, key, axis, val)
    ctx.doc.Regenerate()
    lanes = {"X": 0, "Y": 0, "Z": 0}
    for ka, kb, pname in dim_defs(ctx.mitre):
        ax = ctx.pl[ka].axis
        try:
            label_dimension(ctx, ka, kb, pname, lanes[ax])
            lanes[ax] += 1
        except Exception as ex:
            ctx.warn("dimension {} -> {} ({}) failed: {}".format(ka, kb, pname, ex))
    ctx.doc.Regenerate()


# ----------------------------------------------------------------------------------------
# 6. SKETCH CONSTRAINT ENGINE  (profile lines / end points / circle centres locked to planes)
# ----------------------------------------------------------------------------------------
def _align(ctx, view, plane_ref, other_ref, what):
    if plane_ref is None or other_ref is None:
        ctx.warn("alignment skipped (null reference): " + what)
        return False
    try:
        ctx.fc.NewAlignment(view, plane_ref, other_ref)
        return True
    except Exception as ex:
        ctx.warn("alignment failed: {} ({})".format(what, str(ex).split("\n")[0]))
        return False


def _fresh(ctx, mc):
    return ctx.doc.GetElement(mc.Id)


def _sketch_curves(ctx, ext):
    out = []
    try:
        for eid in ext.Sketch.GetAllElements():
            e = ctx.doc.GetElement(eid)
            if e is not None and hasattr(e, "GeometryCurve"):
                out.append(e)
    except Exception as ex:
        ctx.warn("cannot read sketch of extrusion: {}".format(ex))
    return out


def _find_line(mcs, a, b):
    for mc in mcs:
        c = mc.GeometryCurve
        if not isinstance(c, Line):
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        if (p0.DistanceTo(a) < TOL_FT and p1.DistanceTo(b) < TOL_FT) or \
           (p0.DistanceTo(b) < TOL_FT and p1.DistanceTo(a) < TOL_FT):
            return mc
    return None


def constrain_polyline(ctx, view, keys, pts, mcs, closed, tag):
    """keys = [(u_plane_key, v_plane_key)], pts = [XYZ].  Every axis-parallel edge is aligned to its plane; every
    vertex coordinate that is still free (diagonal edges) is locked by aligning the end point to its plane."""
    n = len(keys)
    m = n if closed else n - 1
    edge_mc = {}
    fixed = [[False, False] for _ in range(n)]
    for k in range(m):
        i0, i1 = k, (k + 1) % n
        mc = _find_line(mcs, pts[i0], pts[i1])
        edge_mc[k] = mc
        if mc is None:
            ctx.warn("{}: sketch line {} not found".format(tag, k))
            continue
        (ua, va), (ub, vb) = keys[i0], keys[i1]
        ref = _fresh(ctx, mc).GeometryCurve.Reference
        if ua == ub:
            if _align(ctx, view, ctx.pl[ua].ref, ref, "{} edge {} -> {}".format(tag, k, ua)):
                fixed[i0][0] = fixed[i1][0] = True
        elif va == vb:
            if _align(ctx, view, ctx.pl[va].ref, ref, "{} edge {} -> {}".format(tag, k, va)):
                fixed[i0][1] = fixed[i1][1] = True
    for i in range(n):
        for axis in (0, 1):
            if fixed[i][axis]:
                continue
            cand = []
            if i < m:
                cand.append(i)
            if closed or i - 1 >= 0:
                cand.append((i - 1) % n)
            done = False
            for k in cand:
                mc = edge_mc.get(k)
                if mc is None:
                    continue
                c = _fresh(ctx, mc).GeometryCurve
                idx = 0 if c.GetEndPoint(0).DistanceTo(pts[i]) < TOL_FT else 1
                done = _align(ctx, view, ctx.pl[keys[i][axis]].ref, c.GetEndPointReference(idx),
                              "{} vertex {} end point -> {}".format(tag, i, keys[i][axis]))
                if done:
                    break
    return edge_mc


def _circle_curves(normal, center, radius):
    pl = Plane.CreateByNormalAndOrigin(normal, center)
    try:
        return [Arc.Create(pl, radius, 0.0, 2.0 * math.pi)]
    except Exception:
        # two half arcs fallback
        xa = pl.XVec
        ya = pl.YVec
        p0 = center + xa.Multiply(radius)
        p1 = center - xa.Multiply(radius)
        return [Arc.Create(p0, p1, center + ya.Multiply(radius)),
                Arc.Create(p1, p0, center - ya.Multiply(radius))]


def _center_reference(ctx, mc):
    ref = None
    try:
        ref = _fresh(ctx, mc).CenterPointReference
    except Exception:
        ref = None
    if ref is not None:
        return ref
    try:   # make the centre mark visible, then ask again
        for prm in _fresh(ctx, mc).Parameters:
            try:
                s = str(prm.Definition.BuiltInParameter).upper()
                if "CENTER" in s and "MARK" in s and not prm.IsReadOnly:
                    prm.Set(1)
            except Exception:
                continue
        ctx.doc.Regenerate()
        return _fresh(ctx, mc).CenterPointReference
    except Exception:
        return None


def constrain_circle(ctx, view, mcs, center, radius, ukey, vkey, rparam, tag):
    mc = None
    for m in mcs:
        c = m.GeometryCurve
        if isinstance(c, Arc) and c.Center.DistanceTo(center) < TOL_FT and abs(c.Radius - radius) < TOL_FT:
            mc = m
            break
    if mc is None:
        ctx.warn("{}: circle not found in sketch".format(tag))
        return
    cref = _center_reference(ctx, mc)
    if cref is None:
        ctx.warn("{}: circle centre reference unavailable".format(tag))
    else:
        _align(ctx, view, ctx.pl[ukey].ref, cref, "{} centre -> {}".format(tag, ukey))
        _align(ctx, view, ctx.pl[vkey].ref, cref, "{} centre -> {}".format(tag, vkey))
    if rparam is not None:
        try:
            c = _fresh(ctx, mc).GeometryCurve
            dim = ctx.fc.NewRadialDimension(view, c.Reference, c.Center)
            dim.FamilyLabel = rparam
        except Exception as ex:
            ctx.warn("{}: radius dimension failed: {}".format(tag, str(ex).split("\n")[0]))


# ----------------------------------------------------------------------------------------
# 7. EXTRUSION BUILDER
# ----------------------------------------------------------------------------------------
def poly(keys, closed=True):
    return {"type": "poly", "keys": keys, "closed": closed}


def free_poly(coords_mm):
    return {"type": "free", "coords": coords_mm}


def circ(ukey, vkey, r_mm, rparam):
    return {"type": "circle", "u": ukey, "v": vkey, "r": r_mm, "rparam": rparam}


def set_visibility(elem, lod, view_specific=False):
    # Symbolic curves refuse a ViewSpecific visibility object; solids refuse
    # nothing here. Try the preferred kind first, then the other one.
    kinds = (FamilyElementVisibilityType.ViewSpecific, FamilyElementVisibilityType.Model)
    if not view_specific:
        kinds = (FamilyElementVisibilityType.Model, FamilyElementVisibilityType.ViewSpecific)
    for kind in kinds:
        try:
            fev = FamilyElementVisibility(kind)
            fev.IsShownInCoarse = lod[0]
            fev.IsShownInMedium = lod[1]
            fev.IsShownInFine = lod[2]
            # the axis flags are unset on a fresh FamilyElementVisibility, so the
            # element would not be drawn in plan or elevation views
            fev.IsShownInTopBottom = True
            fev.IsShownInFrontBack = True
            fev.IsShownInLeftRight = True
            elem.SetVisibility(fev)
            return True
        except Exception:
            continue
    return False


def _set_range(ctx, ext, start, end):
    ps = ext.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM)
    pe = ext.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM)

    def val(x):
        return ctx.cur_ft(x) if isinstance(x, FamilyParameter) else mm(x)
    s, e = val(start), val(end)
    if s < pe.AsDouble() - 1e-9:
        ps.Set(s)
        pe.Set(e)
    else:
        pe.Set(e)
        ps.Set(s)
    for prm, x in ((ps, start), (pe, end)):
        if isinstance(x, FamilyParameter):
            ctx.mgr.AssociateElementParameterToFamilyParameter(prm, x)


def build_profile(ctx, name, frame, host, loops, rng, material=None, visible=None, lod=None, solid=True):
    """Create one extrusion.
       frame : "XY" (sketch on Z=0, view = plan) | "XZ" (hosted on a Y plane, front elevation)
               | "YZ" (hosted on an X plane, side elevation)
       rng   : (start, end) - FamilyParameter or mm number, or the string "THICK" (plate of WallThickness
               extruded along +normal of the hosting plane).
       returns (extrusion, {(loop, edge): sketch line id})"""
    doc = ctx.doc
    if frame == "XY":
        sp, view, normal = ctx.sk_z0, ctx.plan, XYZ(0, 0, 1)
        hp = None

        def to3d(u, v):
            return XYZ(u, v, 0.0)
    else:
        hp = ctx.pl[host]
        sp = None
        for maker in (lambda: SketchPlane.Create(doc, hp.ref),
                      lambda: SketchPlane.Create(doc, hp.rp.Id),
                      lambda: SketchPlane.Create(doc, hp.rp.GetPlane())):
            try:
                sp = maker()
                break
            except Exception:
                continue
        if sp is None:
            raise RuntimeError("cannot create sketch plane on {}".format(host))
        if frame == "XZ":
            view, normal = ctx.front, XYZ(0, 1, 0)

            def to3d(u, v):
                return XYZ(u, hp.ft, v)
        else:
            view, normal = ctx.side, XYZ(1, 0, 0)

            def to3d(u, v):
                return XYZ(hp.ft, u, v)

    # ---- curves ----------------------------------------------------------------------
    arr_all = CurveArrArray()
    meta = []
    for li, L in enumerate(loops):
        ca = CurveArray()
        if L["type"] == "poly":
            pts = [to3d(ctx.pl[ku].ft, ctx.pl[kv].ft) for (ku, kv) in L["keys"]]
            n = len(pts)
            for i in range(n if L["closed"] else n - 1):
                ca.Append(Line.CreateBound(pts[i], pts[(i + 1) % n]))
            meta.append(("poly", L, pts))
        elif L["type"] == "free":
            pts = [to3d(mm(u), mm(v)) for (u, v) in L["coords"]]
            for i in range(len(pts)):
                ca.Append(Line.CreateBound(pts[i], pts[(i + 1) % len(pts)]))
            meta.append(("free", L, pts))
        else:
            c = to3d(ctx.pl[L["u"]].ft, ctx.pl[L["v"]].ft)
            for crv in _circle_curves(normal, c, mm(L["r"])):
                ca.Append(crv)
            meta.append(("circle", L, c))
        arr_all.Append(ca)

    ext = ctx.fc.NewExtrusion(solid, arr_all, sp, mm(10.0))
    # ---- extrusion range -------------------------------------------------------------------
    if rng == "THICK":
        flip = False
        try:
            flip = sp.GetPlane().Normal.DotProduct(AXIS_VEC[hp.axis]) < 0
        except Exception:
            pass
        rng = (ctx.p["Neg_WallThickness"], 0.0) if flip else (0.0, ctx.p["WallThickness"])
    _set_range(ctx, ext, rng[0], rng[1])
    try:
        ext.Name = "TRK_" + name
    except Exception:
        pass
    doc.Regenerate()

    # ---- constraints ------------------------------------------------------------------------
    mcs = _sketch_curves(ctx, ext)
    edge_ids = {}
    for li, (kind, L, data) in enumerate(meta):
        if kind == "poly":
            em = constrain_polyline(ctx, view, L["keys"], data, mcs, L["closed"], "{}[{}]".format(name, li))
            for k, mc in em.items():
                if mc is not None:
                    edge_ids[(li, k)] = mc.Id
        elif kind == "circle":
            constrain_circle(ctx, view, mcs, data, mm(L["r"]), L["u"], L["v"],
                             ctx.p[L["rparam"]] if L["rparam"] else None, "{}[{}]".format(name, li))
    doc.Regenerate()

    # ---- parameters bound to the form ----------------------------------------------------------
    if solid:
        if material:
            prm = ext.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
            if prm is not None:
                ctx.mgr.AssociateElementParameterToFamilyParameter(prm, ctx.p[material])
        if visible:
            prm = ext.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
            if prm is not None:
                ctx.mgr.AssociateElementParameterToFamilyParameter(prm, ctx.p[visible])
        if lod:
            if not set_visibility(ext, lod):
                ctx.warn("{}: detail-level visibility could not be set".format(name))
        ctx.solid_ids.append(ext.Id)
    return ext, edge_ids


# ----------------------------------------------------------------------------------------
# 8. THE BEND GEOMETRY
# ----------------------------------------------------------------------------------------
def outline_keys(mitre):
    """XY outline as (u-plane, v-plane) pairs - identical to the Three.js preview."""
    if mitre:
        return [("X_out", "Y_out"), ("X_end", "Y_out"), ("X_end", "Y_in"), ("X_in", "Y_end"), ("X_out", "Y_end")]
    return [("X_out", "Y_out"), ("X_end", "Y_out"), ("X_end", "Y_in"), ("X_in", "Y_in"),
            ("X_in", "Y_end"), ("X_out", "Y_end")]


def step_geometry(ctx):
    P = ctx.p
    mitre = ctx.mitre
    outline = outline_keys(mitre)

    # 1) floor (bottom plate)  z: -H/2 .. -H/2 + T
    build_profile(ctx, "Floor", "XY", None, [poly(outline)],
                  (P["Neg_Half_Height"], P["Floor_Top_Z"]), "Body_Material", None, LOD_BODY)

    # 2) outer walls (L shaped, open at both ports)  z: -H/2 + T .. H/2 - T
    outer = [("X_out", "Y_end"), ("X_out", "Y_out"), ("X_end", "Y_out"), ("X_end", "Y_out_T"),
             ("X_out_T", "Y_out_T"), ("X_out_T", "Y_end")]
    build_profile(ctx, "OuterWall", "XY", None, [poly(outer)],
                  (P["Floor_Top_Z"], P["Wall_Top_Z"]), "Body_Material", None, LOD_BODY)

    # 3) inner walls : mitre = one 45-degree wall (C = 75 * sqrt 2) / sharp = L shaped, two walls of C = 75
    if mitre:
        inner = [("X_end", "Y_in"), ("X_in", "Y_end"), ("X_in_D", "Y_end"), ("X_end", "Y_in_D")]
    else:
        inner = [("X_end", "Y_in"), ("X_in", "Y_in"), ("X_in", "Y_end"), ("X_in_T", "Y_end"),
                 ("X_in_T", "Y_in_T"), ("X_end", "Y_in_T")]
    build_profile(ctx, "InnerWall", "XY", None, [poly(inner)],
                  (P["Floor_Top_Z"], P["Wall_Top_Z"]), "Body_Material", None, LOD_BODY)

    # 4) cover (front opening, +Z top)  z: H/2 - T .. H/2   - Show_Cover
    _ext, ids = build_profile(ctx, "Cover", "XY", None, [poly(outline)],
                              (P["Wall_Top_Z"], P["Half_Height"]), "Cover_Material", "Show_Cover", LOD_BODY)
    ctx.c_curve_id = ids.get((0, 2))     # edge 3 -> 4 : mitre diagonal / sharp inner straight

    # 5) coupling tabs with through holes (hole = inner loop of the tab sketch) - Show_Flanges
    for frame, uax, hosts in (("XZ", "X", ("Y_out", "Y_in_T")), ("YZ", "Y", ("X_out", "X_in_T"))):
        for host in hosts:
            rect = poly([(uax + "_end", "Z_bot"), (uax + "_fl_end", "Z_bot"),
                         (uax + "_fl_end", "Z_wall_top"), (uax + "_end", "Z_wall_top")])
            holes = [circ(uax + "_hole", "Z_hole_up", HOLE_D_MM / 2.0, "Hole_Radius"),
                     circ(uax + "_hole", "Z_hole_dn", HOLE_D_MM / 2.0, "Hole_Radius")]
            build_profile(ctx, "Tab_{}_{}".format(uax, host), frame, host, [rect] + holes, "THICK",
                          "Body_Material", "Show_Flanges", LOD_FINE)

    # 6) cover fixing screws : 2 per port, on the +Z face of the cover - Show_Cover AND Show_Fasteners
    screws = [circ("X_scr_end", "Y_scr_pos", SCREW_D_MM / 2.0, "Screw_Head_Radius"),
              circ("X_scr_end", "Y_scr_neg", SCREW_D_MM / 2.0, "Screw_Head_Radius"),
              circ("X_scr_pos", "Y_scr_end", SCREW_D_MM / 2.0, "Screw_Head_Radius"),
              circ("X_scr_neg", "Y_scr_end", SCREW_D_MM / 2.0, "Screw_Head_Radius")]
    build_profile(ctx, "CoverScrews", "XY", None, screws, (P["Half_Height"], P["Screw_Top_Z"]),
                  "Screw_Material", "Show_Cover_Screws", LOD_FINE)


# ----------------------------------------------------------------------------------------
# 9. CONNECTORS (2 x cable tray connector, outward normals, linked)  +  2D CENTRE LINES
# ----------------------------------------------------------------------------------------
def _marker_face_reference(ctx, key):
    """Fallback: a tiny void (10 x 10 x 1 mm, inside the port, cuts nothing) whose outer face lies exactly in
    the port plane. Its planar face hosts the connector at the face centroid = port centre."""
    pl = ctx.pl[key]
    frame = "YZ" if pl.axis == "X" else "XZ"
    sq = [(-5.0, -5.0), (5.0, -5.0), (5.0, 5.0), (-5.0, 5.0)]
    ext, _ids = build_profile(ctx, "PortMarker_" + key, frame, key, [free_poly(sq)], (-1.0, 0.0),
                              None, None, None, solid=False)
    opt = Options()
    opt.ComputeReferences = True
    opt.IncludeNonVisibleObjects = True
    want = AXIS_VEC[pl.axis]
    for g in ext.get_Geometry(opt):
        if isinstance(g, Solid):
            for f in g.Faces:
                if isinstance(f, PlanarFace) and f.FaceNormal.DotProduct(want) > 0.99:
                    d = f.Origin.X if pl.axis == "X" else f.Origin.Y
                    if abs(d - pl.ft) < TOL_FT * 10:
                        return f.Reference
    raise RuntimeError("no marker face found for connector host '{}'".format(key))


def _create_connector(ctx, key):
    try:
        return ConnectorElement.CreateCableTrayConnector(ctx.doc, ctx.pl[key].ref)
    except Exception as ex:
        ctx.warn("connector on reference plane '{}' failed ({}); using marker-face fallback".format(
            key, str(ex).split("\n")[0]))
    return ConnectorElement.CreateCableTrayConnector(ctx.doc, _marker_face_reference(ctx, key))


def _bind(ctx, elem, bip_name, fp):
    bip = getattr(BuiltInParameter, bip_name, None)
    if bip is None:
        return False
    prm = elem.get_Parameter(bip)
    if prm is None:
        return False
    ctx.mgr.AssociateElementParameterToFamilyParameter(prm, fp)
    return True


def step_connectors_and_centerlines(ctx):
    P = ctx.p
    ce = mm(DEFAULT_W / 2.0 + STUB_MM)
    targets = [("X_end", XYZ(ce, 0, 0)), ("Y_end", XYZ(0, ce, 0))]
    conns = []
    for key, target in targets:
        conn = _create_connector(ctx, key)
        ctx.doc.Regenerate()
        try:   # connector must sit on the centre line of the port
            delta = target - conn.Origin
            if delta.GetLength() > TOL_FT:
                ElementTransformUtils.MoveElement(ctx.doc, conn.Id, delta)
        except Exception as ex:
            ctx.warn("connector '{}' could not be centred: {}".format(key, str(ex).split("\n")[0]))
        if not _bind(ctx, conn, "CONNECTOR_WIDTH", P["Width"]):
            raise RuntimeError("CONNECTOR_WIDTH could not be bound")
        if not _bind(ctx, conn, "CONNECTOR_HEIGHT", P["Height"]):
            raise RuntimeError("CONNECTOR_HEIGHT could not be bound")
        if BIND_CONNECTOR_ANGLE:
            try:
                _bind(ctx, conn, "CONNECTOR_ANGLE", P["Angle"])
            except Exception as ex:
                ctx.warn("CONNECTOR_ANGLE binding skipped: {}".format(ex))
        conns.append(conn)
    conns[0].SetLinkedConnectorElement(conns[1])
    ctx.connector_info = "2 cable tray connectors (linked)"

    # 2D centre lines : symbolic lines, Coarse only, locked to the centre / port planes
    for keys in ([("X_C", "Y_C"), ("X_end", "Y_C")], [("X_C", "Y_C"), ("X_C", "Y_end")]):
        try:
            pts = [XYZ(ctx.pl[ku].ft, ctx.pl[kv].ft, 0.0) for (ku, kv) in keys]
            sc = ctx.fc.NewSymbolicCurve(Line.CreateBound(pts[0], pts[1]), ctx.sk_z0)
            constrain_polyline(ctx, ctx.plan, keys, pts, [sc], False, "CentreLine")
            if not set_visibility(sc, LOD_CENTER, True):
                ctx.warn("centre line detail-level visibility could not be set")
        except Exception as ex:
            ctx.warn("centre line failed: {}".format(str(ex).split("\n")[0]))
    ctx.doc.Regenerate()


# ----------------------------------------------------------------------------------------
# 10. FLEXING VALIDATION (single type - only the instance parameters Width / Height are changed)
# ----------------------------------------------------------------------------------------
def solid_bbox_mm(ctx):
    mn = [1.0e12, 1.0e12, 1.0e12]
    mx = [-1.0e12, -1.0e12, -1.0e12]
    for eid in ctx.solid_ids:
        bb = ctx.doc.GetElement(eid).get_BoundingBox(None)
        if bb is None:
            continue
        for i, (a, b) in enumerate(((bb.Min.X, bb.Max.X), (bb.Min.Y, bb.Max.Y), (bb.Min.Z, bb.Max.Z))):
            mn[i] = min(mn[i], to_mm(a))
            mx[i] = max(mx[i], to_mm(b))
    return mn, mx


def connector_state(ctx):
    out = []
    for c in FilteredElementCollector(ctx.doc).OfClass(_clr_type(ConnectorElement)):
        o = c.Origin
        out.append(((to_mm(o.X), to_mm(o.Y), to_mm(o.Z)), to_mm(c.Width), to_mm(c.Height)))
    return out


def flex_to(ctx, w, h):
    def _do():
        ctx.mgr.Set(ctx.p["Width"], mm(w))
        ctx.mgr.Set(ctx.p["Height"], mm(h))
        ctx.doc.Regenerate()
    run_tx(ctx.doc, "Flex {}x{}".format(int(w), int(h)), _do)


def validate_size(ctx, w, h):
    """returns (row, ok)"""
    errs = []
    try:
        flex_to(ctx, w, h)
    except Exception as ex:
        return ([ctx.spec["label"], "{}x{}".format(int(w), int(h)), "-", "-", "-", "-", "-", "-",
                 "FAIL regenerate: {}".format(str(ex).split("\n")[0][:90])], False)
    mn, mx = solid_bbox_mm(ctx)
    fl = ctx.val_mm("Flange_Length")
    ce = ctx.val_mm("CenterToEnd")
    t = ctx.val_mm("WallThickness")
    a_meas = (mx[0] - fl) - mn[0]
    b_meas = (mx[1] - fl) - mn[1]
    c_meas = None
    try:
        c_meas = to_mm(ctx.doc.GetElement(ctx.c_curve_id).GeometryCurve.Length)
    except Exception:
        errs.append("C curve unreadable")
    exp_a = w + STUB_MM
    exp_c = STUB_MM * SQRT2 if ctx.mitre else STUB_MM
    exp_t = wall_thickness_mm(w, h)
    exp_min = (-w / 2.0, -w / 2.0, -h / 2.0)
    exp_max = (w / 2.0 + STUB_MM + FLANGE_MM, w / 2.0 + STUB_MM + FLANGE_MM, h / 2.0 + SCREW_H_MM)

    def chk(label, got, exp, tol=TOL_MM):
        if got is None or abs(got - exp) > tol:
            errs.append("{} {} != {}".format(label, "n/a" if got is None else "{:.2f}".format(got),
                                              "{:.2f}".format(exp)))
    chk("A", a_meas, exp_a)
    chk("B", b_meas, exp_a)
    chk("C", c_meas, exp_c)
    chk("T", t, exp_t, 0.001)
    chk("CenterToEnd", ce, w / 2.0 + STUB_MM)
    for i, ax in enumerate("XYZ"):
        chk("min" + ax, mn[i], exp_min[i])
        chk("max" + ax, mx[i], exp_max[i])
    cs = connector_state(ctx)
    if len(cs) != 2:
        errs.append("connector count {}".format(len(cs)))
    else:
        want = [(ce, 0.0, 0.0), (0.0, ce, 0.0)]
        for (o, cw, chh) in cs:
            hit = False
            for wv in want:
                if abs(o[0] - wv[0]) < TOL_MM and abs(o[1] - wv[1]) < TOL_MM and abs(o[2] - wv[2]) < TOL_MM:
                    hit = True
            if not hit:
                errs.append("connector origin {:.1f},{:.1f},{:.1f}".format(o[0], o[1], o[2]))
            chk("conn W", cw, w)
            chk("conn H", chh, h)
    row = [ctx.spec["label"], "{}x{}".format(int(w), int(h)),
           "{:.1f}".format(a_meas), "{:.1f}".format(b_meas),
           "{:.1f}".format(c_meas) if c_meas is not None else "n/a",
           "{:.1f}".format(t),
           "{:.0f} x {:.0f} x {:.0f}".format(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]),
           "{:.0f}/{:.0f}".format(ce, ce),
           "PASS" if not errs else "FAIL " + "; ".join(errs[:3])]
    return row, not errs


# ----------------------------------------------------------------------------------------
# 11. ONE FAMILY
# ----------------------------------------------------------------------------------------
def build_family(app, template, spec, folder):
    fam_doc = app.NewFamilyDocument(template)
    if fam_doc is None:
        raise RuntimeError("NewFamilyDocument returned None for " + template)
    result = {"file": spec["file"], "path": None, "rows": [], "ok": False, "warnings": [], "part_type": ""}
    try:
        ctx = Ctx(app, fam_doc, spec)
        log("== {} ==".format(spec["file"]))
        run_tx(fam_doc, "Category, Part Type and Parameters", lambda: step_category_part_type_params(ctx))
        run_tx(fam_doc, "Reference planes and labelled dimensions", lambda: step_planes_and_dimensions(ctx))
        run_tx(fam_doc, "Trunking geometry", lambda: step_geometry(ctx))
        run_tx(fam_doc, "Connectors and centre lines", lambda: step_connectors_and_centerlines(ctx))

        all_ok = True
        for (w, h) in STD_SIZES + EXTRA_SIZES:
            row, ok = validate_size(ctx, float(w), float(h))
            result["rows"].append(row)
            all_ok = all_ok and ok
            log("   flex {}x{} -> {}".format(w, h, row[-1]))
        # back to the default 100 x 100
        flex_to(ctx, DEFAULT_W, DEFAULT_H)
        if ctx.mgr.Types.Size != 1:
            raise AssertionError("family must contain exactly 1 type, found {}".format(ctx.mgr.Types.Size))
        path = os.path.join(folder, spec["file"])
        opt = SaveAsOptions()
        opt.OverwriteExistingFile = True
        fam_doc.SaveAs(path, opt)
        result.update({"path": path, "ok": all_ok, "warnings": list(ctx.warnings), "part_type": ctx.part_type_used})
    finally:
        fam_doc.Close(False)
    return result


# ----------------------------------------------------------------------------------------
# 12. LOAD INTO THE ACTIVE PROJECT
# ----------------------------------------------------------------------------------------
try:
    class _LoadOptions(IFamilyLoadOptions):
        # common pyRevit pattern: always load / overwrite
        def OnFamilyFound(self, familyInUse, overwriteParameterValues):
            overwriteParameterValues = True
            return True

        def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
            source = FamilySource.Family
            overwriteParameterValues = True
            return True
    LOAD_OPTIONS = _LoadOptions
except Exception:
    LOAD_OPTIONS = None


def load_into_project(doc, paths):
    if doc is None or doc.IsFamilyDocument:
        return "No project document is open - nothing loaded."
    loaded = 0
    for p in paths:
        ok = False

        def _load():
            res = False
            try:
                res = doc.LoadFamily(p)
            except Exception:
                res = False
            if not res and LOAD_OPTIONS is not None:
                try:
                    out = doc.LoadFamily(p, LOAD_OPTIONS())
                    res = bool(out[0]) if isinstance(out, tuple) else bool(out)
                except Exception:
                    res = False
            return res
        try:
            ok = run_tx(doc, "Load trunking bend family", _load)
        except Exception as ex:
            log("load failed for {}: {}".format(p, ex))
        loaded += 1 if ok else 0
    return "{} / {} families loaded (or already present).".format(loaded, len(paths))


# ----------------------------------------------------------------------------------------
# 13. MAIN
# ----------------------------------------------------------------------------------------
def main():
    app = HOST_APP.app
    output = script.get_output()

    # the header comes before any document access: reading the active document
    # can fail on cloud models (DesktopConnectorInterop) and used to leave no
    # output at all
    output.print_md(u"## Trunking 90-degree bends - front opening (2 families)")
    output.print_md(u"Revit **{0}** build {1}".format(app.VersionNumber, app.VersionBuild))
    env_file = _load_env_file()
    if env_file:
        output.print_md(u"Settings: `{0}`".format(env_file))

    doc = None
    try:
        doc = HOST_APP.doc
    except Exception as ex:
        output.print_md(u"Active document unavailable: {0}".format(ex))

    template = find_template(app)
    log("template: {}".format(template))
    folder = _output_folder()
    output.print_md(u"Template: `{0}`".format(template))
    output.print_md(u"Output: `{0}`".format(folder))

    results = []
    for spec in FAMILY_SPECS:
        try:
            results.append(build_family(app, template, spec, folder))
        except Exception as ex:
            log("FAILED {}: {}".format(spec["file"], ex))
            log(traceback.format_exc())
            results.append({"file": spec["file"], "path": None, "ok": False, "warnings": [str(ex)],
                            "rows": [[spec["label"], "-", "-", "-", "-", "-", "-", "-",
                                      "ERROR: " + str(ex).split("\n")[0][:110]]], "part_type": ""})

    columns = ["Family", "W x H", "A (mm)", "B (mm)", "C (mm)", "Wall T (mm)", "BBox X x Y x Z (mm)",
               "CenterToEnd", "Result"]
    rows = []
    for r in results:
        rows.extend(r["rows"])
    output.print_md("## Trunking 90-degree bends - Front opening : single-type Flexing report")
    output.print_table(table_data=rows, title="2 families x 11 sizes (9 standard + 300x100, 50x100)",
                       columns=columns)
    for r in results:
        output.print_md("* **{}** -> `{}`  | Part Type: `{}`  | warnings: {}".format(
            r["file"], r["path"], r.get("part_type", ""), len(r["warnings"])))
        for w in r["warnings"][:25]:
            output.print_md("    * " + str(w))

    try:
        import io
        log_path = os.path.join(folder, "bends-build.log")
        # UTF-8: the default codec here is cp950 and cannot encode the names
        handle = io.open(log_path, "w", encoding="utf-8", errors="replace")
        try:
            for r in results:
                handle.write(u"{0}\n  path: {1}\n  ok: {2}\n  part_type: {3}\n".format(
                    r["file"], r["path"], r["ok"], r.get("part_type", "")))
                for w in r.get("warnings") or []:
                    handle.write(u"  warning: {0}\n".format(w))
                for row in r.get("rows") or []:
                    handle.write(u"  " + u" | ".join(u"{0}".format(c) for c in row) + u"\n")
        finally:
            handle.close()
        output.print_md(u"Log: `{0}`".format(log_path))
    except Exception as ex:
        log(u"could not write bends-build.log: {0}".format(ex))

    saved = [r["path"] for r in results if r["path"]]
    failed = [r["file"] for r in results if not r["ok"]]
    summary = u"已完成 {} / 2 個族。\n{}".format(
        len(saved), u"全部 Flexing 驗收通過 / all flexing checks passed." if not failed
        else u"注意：驗收未通過 / checks failed: " + u", ".join(failed))
    if not saved:
        _alert(summary)
        return
    if os.environ.get("TRUNKING_LOAD", "1") != "1":
        _alert(summary + u"\n\n已存檔，未載入專案（TRUNKING_LOAD=0）。")
        return
    if doc is None or doc.IsFamilyDocument:
        _alert(summary + u"\n\n目前沒有可用的專案文件，請手動載入 .rfa。")
        return
    _alert(summary + u"\n\n" + load_into_project(doc, saved))

    rows = _routing_table(doc)
    if rows:
        columns = ["Family", "Part type", "Value", "Types"]
        output.print_table(table_data=rows,
                           title="Cable tray fitting families in the project (what Routing Preferences sees)",
                           columns=columns)
        try:
            import io
            handle = io.open(log_path, "a", encoding="utf-8", errors="replace")
            try:
                handle.write(u"\n[project fittings]\n")
                for row in rows:
                    handle.write(u"  " + u" | ".join(u"{0}".format(cell) for cell in row) + u"\n")
            finally:
                handle.close()
        except Exception:
            pass


main()
