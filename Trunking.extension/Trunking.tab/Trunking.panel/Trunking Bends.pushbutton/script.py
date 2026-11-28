#! python3
# -*- coding: utf-8 -*-
# pylint: skip-file
"""Cable Trunking 90-degree Bend Family Generator  (Front Opening / 正面蓋型)

Target   : Autodesk Revit 2027 (.NET 8)  +  pyRevit 7.1
Engines  : IronPython 3.4 / IronPython 2.7 / CPython 3  (standard library + clr + Revit API + pyrevit only)
Install  : <ext>.extension/<tab>.tab/<panel>.panel/TrunkingBends.pushbutton/script.py

One click creates TWO parametric Cable Tray Fitting families (.rfa):
  1. Trunking_90_MitreBend_FrontOpening.rfa   90 deg Mitre bend / 斜角槽曲  -> Revit Horizontal Bend
       outer corner = full 90 deg right angle, inner corner = 45 deg chamfer, C = Stub * sqrt(2) = 106.07 mm
  2. Trunking_90_SharpBend_FrontOpening.rfa   90 deg Sharp bend / 死角槽曲  -> Revit Horizontal Bend
       outer corner = full 90 deg right angle, inner corner = square,      C = Stub = 75 mm

SINGLE TYPE FOR ALL SIZES
  * every family contains exactly ONE family type named "Standard" (asserted before SaveAs)
  * no size-specific types, no type catalog, no lookup table
  * all size inputs (Width, Height, Angle, Stub) and all derived values (CenterToEnd, WallThickness, etc.)
    are INSTANCE parameters, so the same type adapts to every trunking size in the project
    (Routing Preferences -> Horizontal Bend).

GEOMETRY (plan, XY, mm).  Origin (0,0,0) = intersection of the two tray centre lines.
  W = Width, H = Height, Stub = 75, CenterToEnd = W/2 + Stub, A = B = W + Stub
  Mitre bend outline (5 vertices):
      P1 (-W/2, -W/2)              outer corner - full right angle (never chamfered)
      P2 (+W/2+75, -W/2)           port 1 outer
      P3 (+W/2+75, +W/2)           port 1 inner
      P4 (+W/2, +W/2+75)           port 2 inner  (P3 -> P4 = inner 45 deg chamfer, C = 75*sqrt(2) = 106.07)
      P5 (-W/2, +W/2+75)           port 2 outer
  Sharp bend outline (6 vertices): same, plus inner square corner (+W/2, +W/2) between P3 and P4 (C = 75 / 75)
  Z: body (U channel) from -H/2 to +H/2, front cover on top (+Z) from +H/2 to +H/2 + WallThickness.

REVIT 2027 API COMPLIANCE
  * ElementId        : only .Value (Int64) / ElementId(Int64).  The removed 32-bit accessor is never used.
  * Specs            : SpecTypeId.Length / SpecTypeId.Angle / SpecTypeId.Boolean.YesNo /
                       SpecTypeId.String.Text / SpecTypeId.Reference.Material
  * Groups           : GroupTypeId.Geometry (shown as "Dimensions" in the UI), GroupTypeId.Visibility,
                       GroupTypeId.IdentityData, GroupTypeId.Materials
  * Units            : UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)
  * AddParameter     : fam_mgr.AddParameter(name, GroupTypeId.xxx, SpecTypeId.xxx, is_instance)
  * Connectors       : ConnectorElement.CreateCableTrayConnector(doc, face_ref) on both ports,
                       CONNECTOR_WIDTH / CONNECTOR_HEIGHT / CONNECTOR_ANGLE associated to instance
                       parameters, conn1.SetLinkedConnectorElement(conn2)
  * Deprecated API   : the legacy parameter-type / parameter-group / display-unit enums are never used.

Note on the wall thickness formula: Revit formulas do not implement "<=" / ">=".
The specification  if(and(W <= 50 mm, H <= 50 mm), 1.0 mm, (nested ifs))  is therefore written with
the Revit-legal equivalent  not(W > 50 mm)  which yields exactly the same T10/T12/T14/T16 result.
"""

from __future__ import print_function, division

__title__ = 'Trunking\n90\xb0 Bends'
__author__ = 'MEP BIM Library Automation'
__doc__ = ('Generate 2 parametric cable trunking 90-degree bend families (Mitre / Sharp, front opening)\n'
           'for Revit 2027 cable tray routing preferences.  Single type "Standard" drives all sizes.')
__min_revit_ver__ = 2024

import os
import math
import traceback

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
clr.AddReference('System')

from System import Int64

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Category,
    Color,
    ConnectorElement,
    CurveArrArray,
    CurveArray,
    CurveElement,
    ElementId,
    Family,
    FamilyElementVisibility,
    FamilyElementVisibilityType,
    FamilySource,
    FilteredElementCollector,
    GeometryInstance,
    GroupTypeId,
    IFamilyLoadOptions,
    Line,
    Material,
    Options,
    PartType,
    Plane,
    PlanarFace,
    ReferenceArray,
    ReferencePlane,
    SaveAsOptions,
    SketchPlane,
    Solid,
    SpecTypeId,
    Transaction,
    UnitTypeId,
    UnitUtils,
    View,
    ViewDetailLevel,
    ViewType,
    XYZ,
)

from pyrevit import revit, script

logger = script.get_logger()
output = script.get_output()


def _alert(message, title='Trunking bends'):
    """Report without pyRevit dialogs.

    On the CPython engine pyrevit.forms is a stub backend: pick_folder,
    pick_file and alert all raise PyRevitCPythonNotSupported. Messages go to
    the output window and the log instead.
    """
    try:
        logger.info(u'[{0}] {1}'.format(title, message))
    except Exception:
        pass
    try:
        output.print_md(u'**{0}**'.format(title))
        output.print_md(u'{0}'.format(message))
    except Exception:
        print(u'{0}: {1}'.format(title, message))


def _output_folder():
    """TRUNKING_OUT, else Documents\\Trunking\\families (no folder dialog)."""
    folder = os.environ.get('TRUNKING_OUT')
    if not folder:
        folder = os.path.join(os.path.expanduser('~'), 'Documents', 'Trunking', 'families')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def _load_env_file():
    """Apply trunking.env from the repo root (KEY=VALUE, TRUNKING_* only).

    Same file the other buttons read, so TRUNKING_OUT / TRUNKING_TEMPLATE /
    TRUNKING_LOAD can be changed without touching system environment variables.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    current = here
    for _ in range(6):
        candidate = os.path.join(current, 'trunking.env')
        if os.path.isfile(candidate):
            try:
                handle = open(candidate)
                try:
                    for raw in handle:
                        line = raw.strip()
                        if not line or line.startswith('#') or '=' not in line:
                            continue
                        key, _, value = line.partition('=')
                        key = key.strip()
                        if key.startswith('TRUNKING_'):
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

# =====================================================================================
#  CONSTANTS
# =====================================================================================
TARGET_REVIT_VERSION = '2027'
TEMPLATE_ROOT = r'C:\ProgramData\Autodesk\RVT 2027\Family Templates'
# search keywords, best match first (English metric, then Traditional / Simplified Chinese names)
TEMPLATE_KEYWORDS = [
    u'Metric Cable Tray Fitting',
    u'公制電纜架配件',
    u'公制電纜架管件',
    u'公制電纜橋架配件',
    u'公制電纜橋架管件',
    u'公制电缆桥架配件',
    u'公制电缆桥架管件',
    u'電纜架配件',
    u'電纜架管件',
    u'電纜橋架',
    u'电缆桥架',
    u'Cable Tray Fitting',
]

TYPE_NAME = 'Standard'
DEFAULT_W = 100.0        # mm  design size used while drawing the sketches
DEFAULT_H = 100.0        # mm
DEFAULT_STUB = 75.0      # mm  inner straight length (C of the sharp bend)
DEFAULT_FLANGE = 25.0    # mm  coupling tab length beyond the port face
TAB_CLEARANCE = 2.0      # mm  tab inset from floor / top
PLANE_HALF_LEN = 450.0   # mm  graphical half-length of created reference planes
TOL_MM = 0.5             # mm  flexing acceptance tolerance (bounding box / connector origin)
MATCH_TOL_MM = 0.02      # mm  sketch-line to reference-plane matching tolerance

STANDARD_SIZES = [(50, 50), (75, 50), (75, 75), (100, 75), (100, 100),
                  (150, 100), (150, 150), (200, 150), (200, 200)]
EXTRA_SIZES = [(300, 100), (50, 100)]

# Revit-legal version of:  if(and(W <= 50, H <= 50), 1.0, if(and(W <= 100, H <= 75), 1.2,
#                           if(and(W <= 150, H <= 100), 1.4, 1.6)))
WALL_THICKNESS_FORMULA = (
    'if(and(not(Width > 50 mm), not(Height > 50 mm)), 1.0 mm, '
    'if(and(not(Width > 100 mm), not(Height > 75 mm)), 1.2 mm, '
    'if(and(not(Width > 150 mm), not(Height > 100 mm)), 1.4 mm, 1.6 mm)))'
)

FAMILY_SPECS = [
    {
        'kind': 'mitre',
        'file': 'Trunking_90_MitreBend_FrontOpening',
        'title': u'90\xb0 Mitre Bend - Front Opening (90\xb0 斜角槽曲 正面蓋型)',
        'c_formula': 'Stub * sqrt(2)',
        'description': 'Cable trunking 90 deg mitre bend, front opening cover, inner 45 deg chamfer C = Stub*sqrt(2)',
    },
    {
        'kind': 'sharp',
        'file': 'Trunking_90_SharpBend_FrontOpening',
        'title': u'90\xb0 Sharp Bend - Front Opening (90\xb0 死角槽曲 正面蓋型)',
        'c_formula': 'Stub',
        'description': 'Cable trunking 90 deg sharp bend, front opening cover, inner square corner C = Stub',
    },
]


# =====================================================================================
#  SMALL HELPERS
# =====================================================================================
def mm(value):
    """millimetres -> Revit internal units (feet)."""
    return UnitUtils.ConvertToInternalUnits(float(value), UnitTypeId.Millimeters)


def to_mm(value):
    """Revit internal units -> millimetres."""
    return UnitUtils.ConvertFromInternalUnits(float(value), UnitTypeId.Millimeters)


def pt(x_mm, y_mm, z_mm=0.0):
    return XYZ(mm(x_mm), mm(y_mm), mm(z_mm))


def eid(value):
    """ElementId from a 64-bit integer (Revit 2024+ signature)."""
    return ElementId(Int64(int(value)))


def fmt_xyz(p):
    return '({0:.2f}, {1:.2f}, {2:.2f})'.format(to_mm(p.X), to_mm(p.Y), to_mm(p.Z))


def resolve_group(*names):
    """Return the first GroupTypeId member that exists (e.g. 'Dimensions' -> 'Geometry')."""
    for name in names:
        member = getattr(GroupTypeId, name, None)
        if member is not None:
            return member
    return GroupTypeId.Geometry


def wall_thickness_mm(w, h):
    """Python mirror of WALL_THICKNESS_FORMULA (T10 / T12 / T14 / T16)."""
    if w <= 50 and h <= 50:
        return 1.0
    if w <= 100 and h <= 75:
        return 1.2
    if w <= 150 and h <= 100:
        return 1.4
    return 1.6


def outline_vertices(kind, w, stub):
    """Closed outer outline of the bend in plan (mm).  Mitre = 5 vertices, Sharp = 6 vertices."""
    half = w / 2.0
    cte = half + stub
    pts = [(-half, -half),      # P1 outer corner, full right angle
           (cte, -half),        # P2 port 1 outer
           (cte, half)]         # P3 port 1 inner
    if kind == 'sharp':
        pts.append((half, half))    # inner square corner (sharp bend only)
    pts.append((half, cte))     # P4 port 2 inner  (mitre: P3->P4 is the 45 deg chamfer)
    pts.append((-half, cte))    # P5 port 2 outer
    return pts


def cavity_vertices(kind, w, stub, t):
    """Cable space (void) outline: wall thickness t on outer / inner walls, open at both ports."""
    half = w / 2.0
    cte = half + stub
    if kind == 'mitre':
        d = t * math.sqrt(2.0)   # the chamfer wall is diagonal: its inner face sits t*sqrt(2) in along X/Y
        return [(-half + t, -half + t), (cte, -half + t), (cte, half - d),
                (half - d, cte), (-half + t, cte)]
    return [(-half + t, -half + t), (cte, -half + t), (cte, half - t),
            (half - t, half - t), (half - t, cte), (-half + t, cte)]


def tab_rectangles(port, w, stub, t, flange):
    """Two thin coupling tabs per port, sitting just inside the walls, beyond the port face."""
    half = w / 2.0
    cte = half + stub
    if port == 1:
        return [[(cte, -half + t), (cte + flange, -half + t), (cte + flange, -half + 2 * t), (cte, -half + 2 * t)],
                [(cte, half - 2 * t), (cte + flange, half - 2 * t), (cte + flange, half - t), (cte, half - t)]]
    return [[(-half + t, cte), (-half + 2 * t, cte), (-half + 2 * t, cte + flange), (-half + t, cte + flange)],
            [(half - 2 * t, cte), (half - t, cte), (half - t, cte + flange), (half - 2 * t, cte + flange)]]


def expected_values(kind, w, h, stub=DEFAULT_STUB):
    return {
        'A': w + stub,
        'B': w + stub,
        'C': stub * math.sqrt(2.0) if kind == 'mitre' else stub,
        'CenterToEnd': w / 2.0 + stub,
        'T': wall_thickness_mm(w, h),
    }


def assert_single_type(fam_mgr, stage):
    size = fam_mgr.Types.Size
    if size != 1:
        raise Exception('Single-type rule violated {0}: family has {1} types (expected exactly 1 "{2}")'
                        .format(stage, size, TYPE_NAME))


# =====================================================================================
#  FAMILY LOAD OPTIONS (overwrite existing family + parameter values)
# =====================================================================================
class OverwriteFamilyLoadOptions(IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        try:
            overwriteParameterValues.Value = True
        except Exception:
            pass
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        try:
            source.Value = FamilySource.Family
            overwriteParameterValues.Value = True
        except Exception:
            pass
        return True


# =====================================================================================
#  FAMILY BUILDER
# =====================================================================================
class BendFamilyBuilder(object):

    def __init__(self, app, template_path, spec, out_dir):
        self.app = app
        self.template_path = template_path
        self.spec = spec
        self.kind = spec['kind']
        self.out_dir = out_dir

        self.doc = None
        self.fm = None
        self.factory = None
        self.plan_view = None
        self.elev_view = None
        self.sketch_plane = None
        self.material_id = ElementId.InvalidElementId

        self.params = {}          # name -> FamilyParameter
        self.planes = {}          # name -> ReferencePlane
        self.plane_specs = {}     # name -> (unit normal XYZ, origin XYZ)   (design position)

        self.body = None
        self.void = None
        self.cover = None
        self.tabs = []
        self.centerlines = []
        self.host_plates = []
        self.conn1 = None
        self.conn2 = None

        # design values (mm) used while drawing at the default size 100 x 100
        self.W = DEFAULT_W
        self.H = DEFAULT_H
        self.STUB = DEFAULT_STUB
        self.FL = DEFAULT_FLANGE
        self.T = wall_thickness_mm(self.W, self.H)

        self.stats = {
            'planes': 0, 'dimensions': 0, 'alignments_ok': 0, 'alignments_failed': 0,
            'unmatched_lines': 0, 'z_lock': '', 'connector_host': '', 'warnings': [],
            'centerline_lock': '',
        }
        self.flex_rows = []
        self.flex_all_ok = False
        self.saved_path = None
        self.error = None

    # ----------------------------------------------------------------- orchestration
    def run(self):
        self.doc = self.app.NewFamilyDocument(self.template_path)
        if self.doc is None:
            raise Exception('NewFamilyDocument returned None for template: ' + self.template_path)
        try:
            self.fm = self.doc.FamilyManager
            self.factory = self.doc.FamilyCreate
            self._tx('Setup family, parameters', self._setup)
            self._tx('Reference planes, dimensions', self._datums)
            self._tx('Geometry, connectors', self._geometry)
            self._tx('Flex validation (single type)', self._flex)
            assert_single_type(self.fm, 'before SaveAs')
            self._save()
        finally:
            try:
                self.doc.Close(False)
            except Exception:
                pass
        return self

    def _tx(self, name, action):
        t = Transaction(self.doc, name)
        t.Start()
        try:
            action()
            t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise

    def _warn(self, text):
        self.stats['warnings'].append(text)
        logger.warning('[{0}] {1}'.format(self.spec['file'], text))

    def _collapse_to_one_type(self):
        """Delete every family type except the one named "Standard".

        A deleted FamilyType is a dead proxy, so its Name is read before the
        delete, never after.
        """
        while self.fm.Types.Size > 1:
            victim = None
            for candidate in self.fm.Types:
                if str(candidate.Name) != TYPE_NAME:
                    victim = candidate
                    break
            if victim is None:
                break
            self.fm.CurrentType = victim
            self.fm.DeleteCurrentType()
        for candidate in self.fm.Types:
            if str(candidate.Name) == TYPE_NAME:
                self.fm.CurrentType = candidate
                break

    # ----------------------------------------------------------------- 1. setup
    def _setup(self):
        doc = self.doc
        family = doc.OwnerFamily

        cat = Category.GetCategory(doc, BuiltInCategory.OST_CableTrayFitting)
        if cat is not None:
            current = family.FamilyCategory
            if current is None or current.Id.Value != cat.Id.Value:
                family.FamilyCategory = cat

        part_type = family.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
        if part_type is not None and not part_type.IsReadOnly:
            part_type.Set(int(PartType.Elbow))
        else:
            self._warn('FAMILY_CONTENT_PART_TYPE is read-only in this template; set Part Type = Elbow manually')

        # exactly ONE type named "Standard". The Metric Cable Tray Fitting
        # template ships three, so the extras are deleted instead of assumed away.
        if self.fm.Types.Size == 0:
            self.fm.NewType(TYPE_NAME)           # the one and only type of this family
        else:
            if str(self.fm.CurrentType.Name) != TYPE_NAME:
                try:
                    self.fm.RenameCurrentType(TYPE_NAME)
                except Exception:
                    pass
            self._collapse_to_one_type()
        assert_single_type(self.fm, 'after setup')

        self._find_views()
        self._find_center_planes()
        self.sketch_plane = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
        self._create_material()
        self._create_parameters()
        self._set_identity()

    def _find_views(self):
        plan = None
        elevations = []
        for view in FilteredElementCollector(self.doc).OfClass(View):
            try:
                if view.IsTemplate:
                    continue
                vtype = view.ViewType
            except Exception:
                continue
            if vtype == ViewType.FloorPlan and plan is None:
                plan = view
            elif vtype == ViewType.Elevation and abs(view.ViewDirection.Z) < 1e-6:
                elevations.append(view)
        if plan is None:
            raise Exception('No floor plan view (Ref. Level) found in the family template')
        # prefer Front / Back (looking along Y) so the X axis is horizontal on screen
        elevations.sort(key=lambda v: 0 if abs(v.ViewDirection.Y) > 0.9 else 1)
        self.plan_view = plan
        self.elev_view = elevations[0] if elevations else None
        if self.elev_view is None:
            self._warn('No elevation view in template: Z faces will be driven by Extrusion Start/End parameters')

    def _register_plane(self, name, plane, normal, origin):
        self.planes[name] = plane
        self.plane_specs[name] = (normal, origin)
        self.stats['planes'] += 1
        return plane

    def _find_center_planes(self):
        """Locate the template origin planes by geometry (locale independent)."""
        tol = mm(0.01)
        best_lr = None
        best_fb = None
        for rp in FilteredElementCollector(self.doc).OfClass(ReferencePlane):
            try:
                n = rp.Normal
                o = rp.GetPlane().Origin
            except Exception:
                continue
            if abs(abs(n.X) - 1.0) < 1e-6 and abs(o.X) < tol:
                if best_lr is None or (rp.Pinned and not best_lr.Pinned):
                    best_lr = rp
            elif abs(abs(n.Y) - 1.0) < 1e-6 and abs(o.Y) < tol:
                if best_fb is None or (rp.Pinned and not best_fb.Pinned):
                    best_fb = rp
        if best_lr is None:
            best_lr = self._new_vplane('Center (Left/Right)', 'x', 0.0, register=False)
            best_lr.Pinned = True
        if best_fb is None:
            best_fb = self._new_vplane('Center (Front/Back)', 'y', 0.0, register=False)
            best_fb.Pinned = True
        self._register_plane('Center_LR', best_lr, XYZ.BasisX, XYZ.Zero)
        self._register_plane('Center_FB', best_fb, XYZ.BasisY, XYZ.Zero)

    def _create_material(self):
        name = 'Galvanized Steel - Trunking'
        for mat in FilteredElementCollector(self.doc).OfClass(Material):
            if mat.Name == name:
                self.material_id = mat.Id
                return
        mat_id = Material.Create(self.doc, name)
        mat = self.doc.GetElement(mat_id)
        try:
            mat.Color = Color(176, 184, 192)
            mat.Shininess = 96
            mat.Smoothness = 80
        except Exception:
            pass
        self.material_id = mat_id

    def _find_param(self, name):
        """Family parameter by name.

        FamilyManager.GetParameter() only takes a ForgeTypeId in Revit 2027, so
        the name has to be looked up by scanning the collection.
        """
        for parameter in self.fm.Parameters:
            try:
                if str(parameter.Definition.Name) == name:
                    return parameter
            except Exception:
                continue
        return None

    def _add_param(self, name, group, spec_type, value=None, formula=None):
        p = self._find_param(name)
        if p is None:
            p = self.fm.AddParameter(name, group, spec_type, True)      # is_instance = True
        elif not p.IsInstance:
            self.fm.MakeInstance(p)
        if formula is not None:
            self.fm.SetFormula(p, formula)
        elif value is not None:
            self.fm.Set(p, value)
        self.params[name] = p
        return p

    def _create_parameters(self):
        g_dim = resolve_group('Dimensions', 'Geometry')      # UI group "Dimensions" == GroupTypeId.Geometry
        g_vis = GroupTypeId.Visibility
        g_id = resolve_group('IdentityData', 'Geometry')
        g_mat = resolve_group('Materials', 'Geometry')
        length = SpecTypeId.Length

        # --- user inputs (all instance) ---
        self._add_param('Width', g_dim, length, value=mm(self.W))
        self._add_param('Height', g_dim, length, value=mm(self.H))
        self._add_param('Angle', g_dim, SpecTypeId.Angle, value=math.radians(90.0))
        self._add_param('Stub', g_dim, length, value=mm(self.STUB))
        self._add_param('Flange_Length', g_dim, length, value=mm(self.FL))

        # --- derived (formula driven, all instance) ---
        self._add_param('CenterToEnd', g_dim, length, formula='Width / 2 + Stub')
        self._add_param('Half_Width', g_dim, length, formula='Width / 2')
        self._add_param('Half_Height', g_dim, length, formula='Height / 2')
        self._add_param('WallThickness', g_dim, length, formula=WALL_THICKNESS_FORMULA)
        self._add_param('Z_Bottom', g_dim, length, formula='0 mm - Half_Height')
        self._add_param('Z_Floor', g_dim, length, formula='Z_Bottom + WallThickness')
        self._add_param('Z_Cover_Top', g_dim, length, formula='Half_Height + WallThickness')
        self._add_param('Z_Tab_Bottom', g_dim, length, formula='Z_Floor + {0} mm'.format(TAB_CLEARANCE))
        self._add_param('Z_Tab_Top', g_dim, length, formula='Half_Height - {0} mm'.format(TAB_CLEARANCE))
        self._add_param('A_Length', g_dim, length, formula='Width + Stub')
        self._add_param('B_Length', g_dim, length, formula='Width + Stub')
        self._add_param('C_Length', g_dim, length, formula=self.spec['c_formula'])
        if self.kind == 'mitre':
            self._add_param('Mitre_Offset', g_dim, length, formula='(Width + Stub) / sqrt(2)')

        # --- visibility / identity / material ---
        self._add_param('Show_Cover', g_vis, SpecTypeId.Boolean.YesNo, value=1)
        self._add_param('Show_Flanges', g_vis, SpecTypeId.Boolean.YesNo, value=1)
        self._add_param('Cover_Type', g_id, SpecTypeId.String.Text, value='QT')
        self._add_param('Material_Galvanized', g_mat, SpecTypeId.Reference.Material, value=self.material_id)

    def _set_identity(self):
        # these are Family (type) parameters, not FamilyManager ones: the
        # Parameter returned by Family.get_Parameter takes the text directly.
        owner = self.doc.OwnerFamily
        for bip, text in ((BuiltInParameter.ALL_MODEL_DESCRIPTION, self.spec['description']),
                          (BuiltInParameter.ALL_MODEL_TYPE_COMMENTS,
                           'Single type "Standard" drives all sizes (instance parameters Width / Height)')):
            try:
                parameter = owner.get_Parameter(bip)
                if parameter is not None and not parameter.IsReadOnly:
                    parameter.Set(text)
            except Exception:
                pass

    # ----------------------------------------------------------------- 2. datums
    def _new_vplane(self, name, axis, offset_mm, register=True):
        """Vertical reference plane in the plan view: axis 'x' -> normal X at x=offset, 'y' -> normal Y."""
        half_len = mm(PLANE_HALF_LEN)
        off = mm(offset_mm)
        if axis == 'x':
            bubble, free = XYZ(off, -half_len, 0.0), XYZ(off, half_len, 0.0)
            normal, origin = XYZ.BasisX, XYZ(off, 0.0, 0.0)
        else:
            bubble, free = XYZ(-half_len, off, 0.0), XYZ(half_len, off, 0.0)
            normal, origin = XYZ.BasisY, XYZ(0.0, off, 0.0)
        rp = self.factory.NewReferencePlane(bubble, free, XYZ.BasisZ, self.plan_view)
        try:
            rp.Name = name
        except Exception:
            pass
        if register:
            self._register_plane(name, rp, normal, origin)
        return rp

    def _new_diag_plane(self, name, c_mm):
        """Reference plane  x + y = c  (normal (1,1,0)/sqrt2) used for the mitre chamfer."""
        half_len = mm(PLANE_HALF_LEN * 0.5)
        c = mm(c_mm)
        bubble = XYZ(c / 2.0 + half_len, c / 2.0 - half_len, 0.0)
        free = XYZ(c / 2.0 - half_len, c / 2.0 + half_len, 0.0)
        rp = self.factory.NewReferencePlane(bubble, free, XYZ.BasisZ, self.plan_view)
        try:
            rp.Name = name
        except Exception:
            pass
        normal = XYZ(1.0, 1.0, 0.0).Normalize()
        return self._register_plane(name, rp, normal, XYZ(c / 2.0, c / 2.0, 0.0))

    def _new_hplane(self, name, z_mm):
        """Horizontal reference plane created in the elevation view."""
        view = self.elev_view
        right = view.RightDirection
        z = mm(z_mm)
        half_len = mm(PLANE_HALF_LEN)
        bubble = right.Multiply(-half_len).Add(XYZ(0.0, 0.0, z))
        free = right.Multiply(half_len).Add(XYZ(0.0, 0.0, z))
        rp = self.factory.NewReferencePlane(bubble, free, view.ViewDirection, view)
        try:
            rp.Name = name
        except Exception:
            pass
        return self._register_plane(name, rp, XYZ.BasisZ, XYZ(0.0, 0.0, z))

    def _dim(self, name_a, name_b, axis, offset_mm, label):
        """Labelled linear dimension between two parallel reference planes.

        A reference taken from a plane created in the same transaction is not
        usable until the document has regenerated ("The references are not
        geometric references"), and the view matters too, so this regenerates,
        retries in the active view, and records a warning instead of aborting
        the whole family on one bad dimension.
        """
        rp_a, rp_b = self.planes[name_a], self.planes[name_b]
        oa = self.plane_specs[name_a][1]
        ob = self.plane_specs[name_b][1]
        off = mm(offset_mm)
        if axis == 'x':
            view = self.plan_view
            pa, pb = XYZ(oa.X, off, 0.0), XYZ(ob.X, off, 0.0)
        elif axis == 'y':
            view = self.plan_view
            pa, pb = XYZ(off, oa.Y, 0.0), XYZ(off, ob.Y, 0.0)
        elif axis == 'z':
            view = self.elev_view
            right = view.RightDirection
            pa = right.Multiply(off).Add(XYZ(0.0, 0.0, oa.Z))
            pb = right.Multiply(off).Add(XYZ(0.0, 0.0, ob.Z))
        else:   # 'diag' : line through both plane origins (direction (1,1,0))
            view = self.plan_view
            pa, pb = oa, ob

        views = [view]
        try:
            active = self.doc.ActiveView
            if active is not None and active.Id.Value != view.Id.Value:
                views.append(active)
        except Exception:
            pass

        line = Line.CreateBound(pa, pb)
        last_error = None
        for candidate in views:
            for _attempt in (1, 2):
                try:
                    self.doc.Regenerate()
                except Exception:
                    pass
                try:
                    refs = ReferenceArray()
                    refs.Append(rp_a.GetReference())
                    refs.Append(rp_b.GetReference())
                    dim = self.factory.NewDimension(candidate, line, refs)
                    dim.FamilyLabel = self.params[label]
                    self.stats['dimensions'] += 1
                    return dim
                except Exception as ex:
                    last_error = ex
        self._warn('Dimension {0} -> {1} ({2}) skipped: {3}'.format(name_a, name_b, label, last_error))
        return None

    def _datums(self):
        W, H, T, S, FL = self.W, self.H, self.T, self.STUB, self.FL
        h = W / 2.0
        cte = h + S

        for name, x in (('Outer_X', -h), ('Outer_X_In', -h + T), ('Outer_X_In2', -h + 2 * T),
                        ('Inner_X_In2', h - 2 * T), ('Inner_X_In', h - T), ('Inner_X', h),
                        ('Port1_End', cte), ('Port1_Tab_End', cte + FL)):
            self._new_vplane(name, 'x', x)
        for name, y in (('Outer_Y', -h), ('Outer_Y_In', -h + T), ('Outer_Y_In2', -h + 2 * T),
                        ('Inner_Y_In2', h - 2 * T), ('Inner_Y_In', h - T), ('Inner_Y', h),
                        ('Port2_End', cte), ('Port2_Tab_End', cte + FL)):
            self._new_vplane(name, 'y', y)

        # width / length chain (anchored on the pinned template centre planes)
        self._dim('Center_LR', 'Outer_X', 'x', -h - 70, 'Half_Width')
        self._dim('Center_LR', 'Inner_X', 'x', -h - 90, 'Half_Width')
        self._dim('Center_FB', 'Outer_Y', 'y', -h - 70, 'Half_Width')
        self._dim('Center_FB', 'Inner_Y', 'y', -h - 90, 'Half_Width')
        self._dim('Center_LR', 'Port1_End', 'x', -h - 110, 'CenterToEnd')
        self._dim('Center_FB', 'Port2_End', 'y', -h - 110, 'CenterToEnd')
        self._dim('Port1_End', 'Port1_Tab_End', 'x', -h - 130, 'Flange_Length')
        self._dim('Port2_End', 'Port2_Tab_End', 'y', -h - 130, 'Flange_Length')

        # wall thickness chain (automatic T10 / T12 / T14 / T16)
        self._dim('Outer_X', 'Outer_X_In', 'x', cte + 30, 'WallThickness')
        self._dim('Outer_X_In', 'Outer_X_In2', 'x', cte + 50, 'WallThickness')
        self._dim('Inner_X_In', 'Inner_X', 'x', cte + 30, 'WallThickness')
        self._dim('Inner_X_In2', 'Inner_X_In', 'x', cte + 50, 'WallThickness')
        self._dim('Outer_Y', 'Outer_Y_In', 'y', cte + 30, 'WallThickness')
        self._dim('Outer_Y_In', 'Outer_Y_In2', 'y', cte + 50, 'WallThickness')
        self._dim('Inner_Y_In', 'Inner_Y', 'y', cte + 30, 'WallThickness')
        self._dim('Inner_Y_In2', 'Inner_Y_In', 'y', cte + 50, 'WallThickness')

        # mitre chamfer planes:  x + y = W + Stub  (outer face)  and  x + y = W + Stub - T*sqrt2 (inner face)
        if self.kind == 'mitre':
            c = W + S
            anchor = self._new_diag_plane('Diag_Origin', 0.0)
            anchor.Pinned = True
            self._new_diag_plane('Mitre_Plane', c)
            self._new_diag_plane('Mitre_In', c - T * math.sqrt(2.0))
            self._dim('Diag_Origin', 'Mitre_Plane', 'diag', 0.0, 'Mitre_Offset')
            self._dim('Mitre_Plane', 'Mitre_In', 'diag', 0.0, 'WallThickness')

        # height planes (elevation)
        if self.elev_view is not None:
            center_z = self._new_hplane('Center_Z', 0.0)
            center_z.Pinned = True
            self._new_hplane('Top', H / 2.0)
            self._new_hplane('Bottom', -H / 2.0)
            self._dim('Center_Z', 'Top', 'z', -h - 70, 'Half_Height')
            self._dim('Center_Z', 'Bottom', 'z', -h - 90, 'Half_Height')

    # ----------------------------------------------------------------- 3. geometry helpers
    def _profile(self, loops):
        prof = CurveArrArray()
        for loop in loops:
            arr = CurveArray()
            n = len(loop)
            for i in range(n):
                a = loop[i]
                b = loop[(i + 1) % n]
                arr.Append(Line.CreateBound(pt(a[0], a[1]), pt(b[0], b[1])))
            prof.Append(arr)
        return prof

    def _set_z_range(self, ext, z0, z1):
        """Set Extrusion Start / End (internal units) keeping start < end at every step."""
        if z0 < ext.StartOffset:
            ext.StartOffset = z0
            ext.EndOffset = z1
        else:
            ext.EndOffset = z1
            ext.StartOffset = z0

    def _new_extrusion(self, loops, is_solid, z0_mm, z1_mm):
        depth = mm(max(z1_mm - z0_mm, 1.0))
        ext = self.factory.NewExtrusion(is_solid, self._profile(loops), self.sketch_plane, depth)
        self._set_z_range(ext, mm(z0_mm), mm(z1_mm))
        return ext

    def _associate(self, element, bip, param_name):
        p = element.get_Parameter(bip)
        if p is None:
            raise Exception('Parameter {0} not found on element {1}'.format(bip, element.Id.Value))
        self.fm.AssociateElementParameterToFamilyParameter(p, self.params[param_name])

    def _associate_z(self, ext, start_param, end_param):
        self._associate(ext, BuiltInParameter.EXTRUSION_START_PARAM, start_param)
        self._associate(ext, BuiltInParameter.EXTRUSION_END_PARAM, end_param)

    def _set_visibility(self, element, coarse, medium, fine):
        # Revit 2027 has FamilyElementVisibility(VisibilityType), not the older
        # FamilyElementVisibilitySettings; the axis flags default to off.
        settings = FamilyElementVisibility(FamilyElementVisibilityType.Model)
        settings.IsShownInCoarse = coarse
        settings.IsShownInMedium = medium
        settings.IsShownInFine = fine
        settings.IsShownInTopBottom = True
        settings.IsShownInFrontBack = True
        settings.IsShownInLeftRight = True
        element.SetVisibility(settings)

    def _sketch_curve_refs(self, ext):
        """[(Curve, Reference)] for every sketch line of an extrusion."""
        result = []
        sketch = ext.Sketch
        try:
            for element_id in sketch.GetAllElements():
                el = self.doc.GetElement(element_id)
                if isinstance(el, CurveElement):
                    gc = el.GeometryCurve
                    if gc is not None and gc.Reference is not None:
                        result.append((gc, gc.Reference))
        except Exception:
            result = []
        if not result:
            for arr in sketch.Profile:
                for curve in arr:
                    if curve.Reference is not None:
                        result.append((curve, curve.Reference))
        return result

    def _align_sketch(self, ext, plane_names, view=None, quiet_unmatched=False):
        """Lock every sketch line onto the reference plane it was drawn on (NewAlignment)."""
        view = view or self.plan_view
        tol = mm(MATCH_TOL_MM)
        specs = [(n, self.planes[n], self.plane_specs[n]) for n in plane_names if n in self.planes]
        for curve, ref in self._sketch_curve_refs(ext):
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            matched = False
            for name, rp, (normal, origin) in specs:
                if abs(p0.Subtract(origin).DotProduct(normal)) < tol and \
                   abs(p1.Subtract(origin).DotProduct(normal)) < tol:
                    matched = True
                    try:
                        self.factory.NewAlignment(view, rp.GetReference(), ref)
                        self.stats['alignments_ok'] += 1
                    except Exception as ex:
                        self.stats['alignments_failed'] += 1
                        self._warn('Alignment failed: line {0}-{1} -> {2}: {3}'
                                   .format(fmt_xyz(p0), fmt_xyz(p1), name, ex))
                    break
            if not matched and not quiet_unmatched:
                self.stats['unmatched_lines'] += 1
                self._warn('Sketch line {0}-{1} matched no reference plane'.format(fmt_xyz(p0), fmt_xyz(p1)))

    def _find_planar_face(self, element, normal):
        """Planar face of the element whose normal equals `normal`, farthest along that normal."""
        opt = Options()
        opt.ComputeReferences = True
        opt.IncludeNonVisibleObjects = True
        opt.DetailLevel = ViewDetailLevel.Fine
        geo = element.get_Geometry(opt)
        best = None
        best_d = None
        if geo is None:
            return None
        solids = []
        for obj in geo:
            if isinstance(obj, Solid):
                solids.append(obj)
            elif isinstance(obj, GeometryInstance):
                for inner in obj.GetInstanceGeometry():
                    if isinstance(inner, Solid):
                        solids.append(inner)
        for solid in solids:
            if solid.Faces.Size == 0:
                continue
            for face in solid.Faces:
                if not isinstance(face, PlanarFace):
                    continue
                if face.FaceNormal.DotProduct(normal) < 0.999:
                    continue
                d = face.Origin.DotProduct(normal)
                if best is None or d > best_d:
                    best, best_d = face, d
        return best

    # ----------------------------------------------------------------- 3. geometry
    def _geometry(self):
        self._create_body()
        self._lock_body_z()
        self._create_cavity_void()
        self._create_connectors()
        self._create_cover()
        self._create_tabs()
        self._create_centerlines()

    def _create_body(self):
        W, H, S = self.W, self.H, self.STUB
        outline = outline_vertices(self.kind, W, S)
        self.body = self._new_extrusion([outline], True, -H / 2.0, H / 2.0)
        self.doc.Regenerate()
        self._align_sketch(self.body, ['Outer_X', 'Outer_Y', 'Inner_X', 'Inner_Y',
                                       'Port1_End', 'Port2_End', 'Mitre_Plane'])
        self._set_visibility(self.body, False, True, True)      # coarse: centre line only
        self._associate(self.body, BuiltInParameter.MATERIAL_ID_PARAM, 'Material_Galvanized')

    def _lock_body_z(self):
        """Lock the top / bottom faces onto the Top / Bottom reference planes (driven by Half_Height).
        Falls back to associating Extrusion Start / End when the alignment cannot be created."""
        if self.elev_view is not None and 'Top' in self.planes and 'Bottom' in self.planes:
            made = []
            try:
                self.doc.Regenerate()
                top_face = self._find_planar_face(self.body, XYZ.BasisZ)
                bottom_face = self._find_planar_face(self.body, XYZ.BasisZ.Negate())
                if top_face is None or bottom_face is None:
                    raise Exception('top / bottom face not found')
                made.append(self.factory.NewAlignment(self.elev_view, self.planes['Top'].GetReference(),
                                                      top_face.Reference))
                made.append(self.factory.NewAlignment(self.elev_view, self.planes['Bottom'].GetReference(),
                                                      bottom_face.Reference))
                self.stats['alignments_ok'] += 2
                self.stats['z_lock'] = 'NewAlignment: top/bottom faces -> Top/Bottom planes (Half_Height)'
                return
            except Exception as ex:
                for d in made:
                    try:
                        self.doc.Delete(d.Id)
                    except Exception:
                        pass
                self._warn('Face alignment to Top/Bottom failed ({0}); using Extrusion Start/End association'
                           .format(ex))
        self._associate_z(self.body, 'Z_Bottom', 'Half_Height')
        self.stats['z_lock'] = 'Extrusion Start/End <- Z_Bottom / Half_Height'

    def _create_cavity_void(self):
        W, H, T, S = self.W, self.H, self.T, self.STUB
        cavity = cavity_vertices(self.kind, W, S, T)
        # void from the top of the floor plate to the top of the walls -> U channel open at both ports
        self.void = self._new_extrusion([cavity], False, -H / 2.0 + T, H / 2.0)
        self.doc.Regenerate()
        self._align_sketch(self.void, ['Outer_X_In', 'Outer_Y_In', 'Inner_X_In', 'Inner_Y_In',
                                       'Port1_End', 'Port2_End', 'Mitre_In'])
        self._associate_z(self.void, 'Z_Floor', 'Half_Height')

    def _connector_expected(self, port):
        cte = self.W / 2.0 + self.STUB
        return pt(cte, 0.0) if port == 1 else pt(0.0, cte)

    def _connector_centered(self, conn, port):
        try:
            return conn.Origin.DistanceTo(self._connector_expected(port)) < mm(TOL_MM)
        except Exception:
            return False

    def _create_host_plate(self, port):
        """Invisible 1 mm plate flush with the port face; only used if Revit does not centre the
        connector on the U-shaped end face.  Fully constrained (planes + locked dimension)."""
        W, H, S = self.W, self.H, self.STUB
        h = W / 2.0
        cte = h + S
        if port == 1:
            rect = [(cte - 1.0, -h), (cte, -h), (cte, h), (cte - 1.0, h)]
            planes = ['Port1_End', 'Outer_Y', 'Inner_Y']
            port_plane, axis = self.planes['Port1_End'], 'x'
        else:
            rect = [(-h, cte - 1.0), (h, cte - 1.0), (h, cte), (-h, cte)]
            planes = ['Port2_End', 'Outer_X', 'Inner_X']
            port_plane, axis = self.planes['Port2_End'], 'y'
        plate = self._new_extrusion([rect], True, -H / 2.0, H / 2.0)
        self.doc.Regenerate()
        self._align_sketch(plate, planes, quiet_unmatched=True)
        # back line: locked 1 mm behind the port plane
        for curve, ref in self._sketch_curve_refs(plate):
            p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
            coord0 = p0.X if axis == 'x' else p0.Y
            coord1 = p1.X if axis == 'x' else p1.Y
            if abs(coord0 - mm(cte - 1.0)) < mm(MATCH_TOL_MM) and abs(coord1 - mm(cte - 1.0)) < mm(MATCH_TOL_MM):
                refs = ReferenceArray()
                refs.Append(port_plane.GetReference())
                refs.Append(ref)
                if axis == 'x':
                    line = Line.CreateBound(pt(cte, -h - 20.0), pt(cte - 1.0, -h - 20.0))
                else:
                    line = Line.CreateBound(pt(-h - 20.0, cte), pt(-h - 20.0, cte - 1.0))
                try:
                    dim = self.factory.NewDimension(self.plan_view, line, refs)
                    dim.IsLocked = True
                    self.stats['dimensions'] += 1
                except Exception as ex:
                    self._warn('Host plate back line lock failed: {0}'.format(ex))
                break
        self._associate_z(plate, 'Z_Bottom', 'Half_Height')
        try:
            plate.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM).Set(0)
        except Exception:
            pass
        self.host_plates.append(plate)
        return plate

    def _bind_connector(self, conn):
        self._associate(conn, BuiltInParameter.CONNECTOR_WIDTH, 'Width')
        self._associate(conn, BuiltInParameter.CONNECTOR_HEIGHT, 'Height')
        try:
            self._associate(conn, BuiltInParameter.CONNECTOR_ANGLE, 'Angle')
        except Exception as ex:
            self._warn('CONNECTOR_ANGLE association skipped: {0}'.format(ex))

    def _create_connectors(self):
        """Two rectangular cable tray connectors on the port faces (+X and +Y), normals pointing out."""
        self.doc.Regenerate()
        face1 = self._find_planar_face(self.body, XYZ.BasisX)
        face2 = self._find_planar_face(self.body, XYZ.BasisY)
        if face1 is None or face2 is None:
            raise Exception('Port end faces (+X / +Y) not found on the body extrusion')
        self.conn1 = ConnectorElement.CreateCableTrayConnector(self.doc, face1.Reference)
        self.conn2 = ConnectorElement.CreateCableTrayConnector(self.doc, face2.Reference)
        self.doc.Regenerate()
        self.stats['connector_host'] = 'body port faces (U section)'

        if not (self._connector_centered(self.conn1, 1) and self._connector_centered(self.conn2, 2)):
            self._warn('Connector not centred on the open U face; re-hosting on invisible full-size port plates')
            for conn in (self.conn1, self.conn2):
                try:
                    self.doc.Delete(conn.Id)
                except Exception:
                    pass
            plate1 = self._create_host_plate(1)
            plate2 = self._create_host_plate(2)
            self.doc.Regenerate()
            face1 = self._find_planar_face(plate1, XYZ.BasisX)
            face2 = self._find_planar_face(plate2, XYZ.BasisY)
            self.conn1 = ConnectorElement.CreateCableTrayConnector(self.doc, face1.Reference)
            self.conn2 = ConnectorElement.CreateCableTrayConnector(self.doc, face2.Reference)
            self.doc.Regenerate()
            self.stats['connector_host'] = 'invisible full-size port plates'

        self._bind_connector(self.conn1)
        self._bind_connector(self.conn2)
        self.conn1.SetLinkedConnectorElement(self.conn2)
        try:
            if not self.conn1.IsPrimary:
                self.conn1.AssignAsPrimary()
        except Exception:
            pass

    def _create_cover(self):
        W, H, T, S = self.W, self.H, self.T, self.STUB
        outline = outline_vertices(self.kind, W, S)
        self.cover = self._new_extrusion([outline], True, H / 2.0, H / 2.0 + T)
        self.doc.Regenerate()
        self._align_sketch(self.cover, ['Outer_X', 'Outer_Y', 'Inner_X', 'Inner_Y',
                                        'Port1_End', 'Port2_End', 'Mitre_Plane'])
        self._associate_z(self.cover, 'Half_Height', 'Z_Cover_Top')
        self._associate(self.cover, BuiltInParameter.IS_VISIBLE_PARAM, 'Show_Cover')
        self._associate(self.cover, BuiltInParameter.MATERIAL_ID_PARAM, 'Material_Galvanized')
        self._set_visibility(self.cover, False, True, True)

    def _create_tabs(self):
        W, H, T, S, FL = self.W, self.H, self.T, self.STUB, self.FL
        z0 = -H / 2.0 + T + TAB_CLEARANCE
        z1 = H / 2.0 - TAB_CLEARANCE
        plane_sets = {
            1: ['Port1_End', 'Port1_Tab_End', 'Outer_Y_In', 'Outer_Y_In2', 'Inner_Y_In', 'Inner_Y_In2'],
            2: ['Port2_End', 'Port2_Tab_End', 'Outer_X_In', 'Outer_X_In2', 'Inner_X_In', 'Inner_X_In2'],
        }
        for port in (1, 2):
            tab = self._new_extrusion(tab_rectangles(port, W, S, T, FL), True, z0, z1)
            self.doc.Regenerate()
            self._align_sketch(tab, plane_sets[port])
            self._associate_z(tab, 'Z_Tab_Bottom', 'Z_Tab_Top')
            self._associate(tab, BuiltInParameter.IS_VISIBLE_PARAM, 'Show_Flanges')
            self._associate(tab, BuiltInParameter.MATERIAL_ID_PARAM, 'Material_Galvanized')
            self._set_visibility(tab, False, False, True)      # fine only
            self.tabs.append(tab)

    def _create_centerlines(self):
        """Coarse detail level: 2D centre line  port1 -> origin -> port2 (model lines)."""
        cte = self.W / 2.0 + self.STUB
        specs = ((pt(cte, 0.0), XYZ.Zero, 'Center_FB', 'Center_LR', 'x'),
                 (pt(0.0, cte), XYZ.Zero, 'Center_LR', 'Center_FB', 'y'))
        locked = 0
        for p_end, p_origin, on_plane, from_plane, axis in specs:
            line = self.factory.NewModelCurve(Line.CreateBound(p_end, p_origin), self.sketch_plane)
            self.centerlines.append(line)
            self.doc.Regenerate()
            try:
                self._set_visibility(line, True, False, False)
            except Exception as ex:
                self._warn('Centre line visibility settings not applied: {0}'.format(ex))
            # keep the line on the centre plane
            try:
                self.factory.NewAlignment(self.plan_view, self.planes[on_plane].GetReference(),
                                          line.GeometryCurve.Reference)
                self.stats['alignments_ok'] += 1
            except Exception as ex:
                self._warn('Centre line alignment skipped: {0}'.format(ex))
            # drive the port end of the line with CenterToEnd (dimension to the curve end point)
            try:
                refs = ReferenceArray()
                refs.Append(self.planes[from_plane].GetReference())
                refs.Append(line.GeometryCurve.GetEndPointReference(0))
                if axis == 'x':
                    dim_line = Line.CreateBound(pt(0.0, -20.0), pt(cte, -20.0))
                else:
                    dim_line = Line.CreateBound(pt(-20.0, 0.0), pt(-20.0, cte))
                dim = self.factory.NewDimension(self.plan_view, dim_line, refs)
                dim.FamilyLabel = self.params['CenterToEnd']
                self.stats['dimensions'] += 1
                locked += 1
            except Exception as ex:
                self._warn('Centre line end-point dimension skipped: {0}'.format(ex))
        self.stats['centerline_lock'] = '{0}/2 end points driven by CenterToEnd'.format(locked)

    # ----------------------------------------------------------------- 4. flexing
    def _flex(self):
        P = self.params
        rows = []
        all_ok = True
        for (w, h) in STANDARD_SIZES + EXTRA_SIZES:
            exp = expected_values(self.kind, w, h, self.STUB)
            self.fm.Set(P['Width'], mm(w))
            self.fm.Set(P['Height'], mm(h))
            error = None
            try:
                self.doc.Regenerate()
            except Exception as ex:
                error = str(ex)

            checks = []
            size_a = size_b = size_h = float('nan')
            try:
                bb = self.body.get_BoundingBox(None)
                size_a = to_mm(bb.Max.X - bb.Min.X)
                size_b = to_mm(bb.Max.Y - bb.Min.Y)
                size_h = to_mm(bb.Max.Z - bb.Min.Z)
                checks.append(abs(size_a - exp['A']) < TOL_MM)
                checks.append(abs(size_b - exp['B']) < TOL_MM)
                checks.append(abs(size_h - h) < TOL_MM)
                checks.append(abs(to_mm(bb.Min.X) + w / 2.0) < TOL_MM)       # outer corner at (-W/2, -W/2)
                checks.append(abs(to_mm(bb.Min.Y) + w / 2.0) < TOL_MM)
                checks.append(abs(to_mm(bb.Max.X) - exp['CenterToEnd']) < TOL_MM)
                checks.append(abs(to_mm(bb.Max.Y) - exp['CenterToEnd']) < TOL_MM)
            except Exception as ex:
                checks.append(False)
                error = error or str(ex)

            current = self.fm.CurrentType
            t_act = to_mm(current.AsDouble(P['WallThickness']))
            c_act = to_mm(current.AsDouble(P['C_Length']))
            cte_act = to_mm(current.AsDouble(P['CenterToEnd']))
            checks.append(abs(t_act - exp['T']) < 0.01)
            checks.append(abs(c_act - exp['C']) < 0.01)
            checks.append(abs(cte_act - exp['CenterToEnd']) < 0.01)

            conn_txt = []
            for port, conn in ((1, self.conn1), (2, self.conn2)):
                try:
                    origin = conn.Origin
                    expected = pt(exp['CenterToEnd'], 0.0) if port == 1 else pt(0.0, exp['CenterToEnd'])
                    ok_c = origin.DistanceTo(expected) < mm(TOL_MM)
                    checks.append(ok_c)
                    conn_txt.append(fmt_xyz(origin) + ('' if ok_c else ' !!'))
                except Exception as ex:
                    checks.append(False)
                    conn_txt.append('n/a ({0})'.format(ex))

            types = self.fm.Types.Size
            checks.append(types == 1)
            ok = (error is None) and all(checks)
            all_ok = all_ok and ok
            rows.append([
                '{0} x {1}'.format(w, h),
                '{0:.0f} / {1:.2f}'.format(exp['A'], size_a),
                '{0:.0f} / {1:.2f}'.format(exp['B'], size_b),
                '{0:.0f} / {1:.2f}'.format(h, size_h),
                '{0:.2f} / {1:.2f}'.format(exp['C'], c_act),
                '{0:.1f} / {1:.2f}'.format(exp['T'], t_act),
                '{0:.1f} / {1:.2f}'.format(exp['CenterToEnd'], cte_act),
                conn_txt[0] if conn_txt else '',
                conn_txt[1] if len(conn_txt) > 1 else '',
                str(types),
                'PASS' if ok else 'FAIL' + (' (' + error + ')' if error else ''),
            ])

        # reset the single type back to 100 x 100 before saving
        self.fm.Set(P['Width'], mm(DEFAULT_W))
        self.fm.Set(P['Height'], mm(DEFAULT_H))
        self.doc.Regenerate()
        assert_single_type(self.fm, 'after flexing')
        self.flex_rows = rows
        self.flex_all_ok = all_ok

    # ----------------------------------------------------------------- 5. save
    def _save(self):
        path = os.path.join(self.out_dir, self.spec['file'] + '.rfa')
        opts = SaveAsOptions()
        opts.OverwriteExistingFile = True
        opts.Compact = True
        opts.MaximumBackups = 1
        self.doc.SaveAs(path, opts)
        self.saved_path = path
        logger.info('Saved: ' + path)


# =====================================================================================
#  TEMPLATE / FOLDER SELECTION
# =====================================================================================
def find_template(app):
    roots = []
    try:
        if app.FamilyTemplatePath and os.path.isdir(app.FamilyTemplatePath):
            roots.append(app.FamilyTemplatePath)
    except Exception:
        pass
    if os.path.isdir(TEMPLATE_ROOT):
        roots.append(TEMPLATE_ROOT)

    candidates = []
    for root in roots:
        for folder, _dirs, files in os.walk(root):
            for file_name in files:
                if not file_name.lower().endswith('.rft'):
                    continue
                stem = os.path.splitext(file_name)[0]
                stem_lower = stem.lower()
                for rank, keyword in enumerate(TEMPLATE_KEYWORDS):
                    if keyword.lower() in stem_lower:
                        penalty = 100 if 'imperial' in stem_lower else 0
                        candidates.append((rank + penalty, os.path.join(folder, file_name)))
                        break
    if candidates:
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1]

    override = os.environ.get('TRUNKING_TEMPLATE')
    if override and os.path.isfile(override):
        return override
    _alert(u'找不到公制電纜橋架管件樣板（Metric Cable Tray Fitting.rft）。\n'
           u'CPython 引擎不支援檔案選擇對話框，請把 TRUNKING_TEMPLATE 設成 .rft 的完整路徑，'
           u'例如 C:\\ProgramData\\Autodesk\\RVT 2027\\Family Templates\\Traditional Chinese\\'
           u'Metric Cable Tray Fitting.rft', title='Family template')
    raise Exception('family template not found: set TRUNKING_TEMPLATE')


def load_into_project(project_doc, path):
    """Load a saved .rfa into the active project (overwrite existing family)."""
    name = os.path.splitext(os.path.basename(path))[0]
    t = Transaction(project_doc, 'Load family ' + name)
    t.Start()
    try:
        loaded = False
        family = None
        try:
            family_ref = clr.Reference[Family]()
            loaded = project_doc.LoadFamily(path, OverwriteFamilyLoadOptions(), family_ref)
            family = family_ref.Value
        except Exception:
            loaded = project_doc.LoadFamily(path)
        if family is None:
            for fam in FilteredElementCollector(project_doc).OfClass(Family):
                if fam.Name == name:
                    family = fam
                    break
        t.Commit()
        symbol_count = 0
        if family is not None:
            family = project_doc.GetElement(eid(family.Id.Value))      # round trip through ElementId(Int64)
            symbol_count = len(list(family.GetFamilySymbolIds()))
        return loaded, family, symbol_count
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise


# =====================================================================================
#  MAIN
# =====================================================================================
def main():
    uiapp = __revit__
    app = uiapp.Application
    project_doc = revit.doc

    env_file = _load_env_file()
    if env_file:
        output.print_md(u'Settings: `{0}`'.format(env_file))

    output.print_md(u'# Cable Trunking 90\xb0 Bend Family Generator (Front Opening)')
    output.print_md(u'Revit **{0}** build {1}  |  target {2}  |  pyRevit single-type parametric families'
                    .format(app.VersionNumber, app.VersionBuild, TARGET_REVIT_VERSION))
    if app.VersionNumber != TARGET_REVIT_VERSION:
        logger.warning('Script is written for Revit {0}; running on {1}'.format(TARGET_REVIT_VERSION,
                                                                                app.VersionNumber))

    template = find_template(app)
    output.print_md(u'Template: `{0}`'.format(template))

    out_dir = _output_folder()
    output.print_md(u'Output: `{0}`'.format(out_dir))

    builders = []
    for spec in FAMILY_SPECS:
        builder = BendFamilyBuilder(app, template, spec, out_dir)
        try:
            builder.run()
        except Exception:
            builder.error = traceback.format_exc()
            logger.error(builder.error)
        builders.append(builder)

    # ---------------- report ----------------
    columns = ['Size W x H', 'A exp/act', 'B exp/act', 'H exp/act', 'C exp/act', 'T exp/act',
               'CenterToEnd exp/act', 'Conn1 origin (mm)', 'Conn2 origin (mm)', 'Types', 'Result']
    for b in builders:
        output.print_md(u'## {0}'.format(b.spec['title']))
        if b.error:
            output.print_md(u'**FAILED**\n```\n{0}\n```'.format(b.error))
            continue
        output.print_table(table_data=b.flex_rows, title='Single-type flexing report: ' + b.spec['file'],
                           columns=columns)
        summary = [
            ['Saved file', b.saved_path],
            ['Family types', '1 (Standard)'],
            ['Reference planes / dimensions', '{0} / {1}'.format(b.stats['planes'], b.stats['dimensions'])],
            ['Sketch alignments ok / failed / unmatched', '{0} / {1} / {2}'.format(
                b.stats['alignments_ok'], b.stats['alignments_failed'], b.stats['unmatched_lines'])],
            ['Z lock method', b.stats['z_lock']],
            ['Connector host', b.stats['connector_host']],
            ['Coarse centre line', b.stats['centerline_lock']],
            ['Flex result', 'ALL PASS' if b.flex_all_ok else 'CHECK TABLE'],
            ['Warnings', '\n'.join(b.stats['warnings']) if b.stats['warnings'] else 'none'],
        ]
        output.print_table(table_data=summary, title='Build summary', columns=['Item', 'Value'])

    saved = [b for b in builders if b.saved_path]
    failed = [b for b in builders if b.error]
    msg = u'已建立 {0} / {1} 個族。\n'.format(len(saved), len(FAMILY_SPECS))
    for b in saved:
        msg += u'  - {0}  [{1}]\n'.format(os.path.basename(b.saved_path),
                                          'flex PASS' if b.flex_all_ok else 'flex CHECK')
    if failed:
        msg += u'失敗: ' + ', '.join(b.spec['file'] for b in failed) + u'\n'

    if not saved:
        _alert(msg + u'\n沒有可載入的族，請查看輸出視窗。', title='Trunking bends')
        return

    if project_doc is None or project_doc.IsFamilyDocument:
        _alert(msg + u'\n目前沒有開啟的專案文件，請手動載入 .rfa。', title='Trunking bends')
        return

    if os.environ.get('TRUNKING_LOAD') != '1':
        _alert(msg + u'\n已存檔，未自動載入專案。'
                     u'\n（CPython 引擎不支援詢問對話框；設 TRUNKING_LOAD=1 可自動載入）',
               title='Trunking bends')
        return

    load_rows = []
    for b in saved:
        try:
            loaded, family, symbols = load_into_project(project_doc, b.saved_path)
            load_rows.append([os.path.basename(b.saved_path), 'yes' if loaded else 'already loaded / skipped',
                              str(family.Id.Value) if family is not None else '-', str(symbols)])
        except Exception as ex:
            load_rows.append([os.path.basename(b.saved_path), 'ERROR: {0}'.format(ex), '-', '-'])
    output.print_table(table_data=load_rows, title='Loaded into ' + project_doc.Title,
                       columns=['Family', 'Loaded', 'Family Id (Int64)', 'Types'])
    _alert(u'載入完成。請於「電纜架類型 > 佈線首選項 > 水平彎頭」指定此族（唯一類型 Standard）。',
           title='Done')


if __name__ == '__main__':
    main()
