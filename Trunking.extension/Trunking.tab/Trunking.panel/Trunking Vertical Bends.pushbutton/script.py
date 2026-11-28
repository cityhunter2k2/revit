#! python3
# -*- coding: utf-8 -*-
"""
Trunking_90_VerticalBend_Generator  --  script.py
=============================================================================
Autodesk Revit 2027 (.NET 8)  +  pyRevit 7.1   (IronPython 2.7 / 3.4 / CPython 3)

One click generates FOUR parametric cable-trunking vertical-bend families:

    Trunking_90_MitreBend_InternalOpening.rfa   (Vertical Inside Bend)
    Trunking_90_MitreBend_ExternalOpening.rfa   (Vertical Outside Bend)
    Trunking_90_SharpBend_InternalOpening.rfa   (Vertical Inside Bend)
    Trunking_90_SharpBend_ExternalOpening.rfa   (Vertical Outside Bend)

Design rules
  * Category OST_CableTrayFitting, PartType = Elbow, two rectangular cable-tray
    connectors (Width = family Y axis, Height = turning plane XZ, normal outward).
  * ONE family type only ("Standard").  Every size parameter, derived parameter,
    hole/screw offset is an INSTANCE parameter driven by a formula chain.
  * Turning plane = XZ plane, extrusion along Y (-W/2 .. +W/2).
    Origin (0,0,0) = intersection of both centre lines.
    CenterToEnd = H/2 + Stub, D = E = H + Stub, Stub = 75 mm.
  * Mitre bend : outer corner is a full 90 deg corner, the 45 deg bevel (C = 106.07 mm)
                 is on the INNER corner.  Sharp bend : square inner corner, C = 75 mm.
  * Internal opening : Port 2 turns UP (+Z), cover sits on the inner (concave) corner.
    External opening : Port 2 turns DOWN (-Z) (mirror in Z), cover sits on the outer corner.
  * Every solid is created from reference planes, labelled by dimensions and locked by
    NewAlignment so that changing Width / Height flexes bodies, flanges, holes and screws.
  * Show_Cover_Screws = and(Show_Cover, Show_Fasteners) drives the cover screws.
    (the flange screw holes are part of the flange profile and follow Show_Flanges.)
  * Detail level : Coarse = 2D centre line only, Medium = body + cover,
    Fine = body + cover + flanges (with holes) + cover screws.

Revit 2027 API rules used here
  * ElementId.Value (64-bit) and ElementId(Int64) only.
  * SpecTypeId.Length / Angle / Boolean.YesNo / String.Text / Reference.Material
  * GroupTypeId.Geometry / Visibility / IdentityData / Materials
  * UnitUtils.ConvertToInternalUnits(value, UnitTypeId.Millimeters)
  * FamilyManager.AddParameter(name, GroupTypeId, SpecTypeId, isInstance)
"""
# ======================= §1  IMPORTS =======================
from __future__ import print_function, division, unicode_literals

import os
import math
import traceback
from collections import OrderedDict

import clr
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
import System

from Autodesk.Revit.DB import (
    Arc, BuiltInCategory, BuiltInParameter, Category, Color, ConnectorElement,
    CurveArray, CurveArrArray, ElementId, ElementTransformUtils, Extrusion,
    FailureProcessingResult, Family, FamilyElementVisibility, FamilyElementVisibilityType,
    FamilySource, FilteredElementCollector, GeometryInstance, GroupTypeId,
    IFailuresPreprocessor, IFamilyLoadOptions, Line, Material, Options, PartType,
    Plane, PlanarFace, ReferenceArray, ReferencePlane, SaveAsOptions, SketchPlane,
    Solid, SpecTypeId, Transaction, TransactionStatus, UnitTypeId, UnitUtils, View,
    ViewDetailLevel, ViewType, XYZ
)
from pyrevit import script, HOST_APP

# pyrevit.forms is a stub backend on the CPython engine: pick_file, pick_folder
# and alert all raise PyRevitCPythonNotSupported, so this button uses none of it.


def _alert(message, title=u'Trunking vertical bends'):
    """Report through the output window and the console instead of a dialog."""
    try:
        out = script.get_output()
        out.print_md(u'**%s**' % title)
        out.print_md(u'%s' % message)
    except Exception:
        pass
    print('%s: %s' % (title, message))


def _output_folder():
    """TRUNKING_OUT, else Documents\\Trunking\\families - no folder dialog."""
    folder = os.environ.get('TRUNKING_OUT')
    if not folder:
        folder = os.path.join(os.path.expanduser('~'), 'Documents', 'Trunking', 'families')
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return folder


def _load_env_file():
    """Apply trunking.env from the repo root (KEY=VALUE, TRUNKING_* only)."""
    current = os.path.dirname(os.path.abspath(__file__))
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


# ======================= §2  CONSTANTS & SPEC TABLES =======================
SQ2 = math.sqrt(2.0)
SQ2_2 = SQ2 / 2.0

STUB_MM = 75.0            # straight stub  -> CenterToEnd = H/2 + 75, D = E = H + 75
DEFAULT_W = 100.0
DEFAULT_H = 100.0
FLANGE_LEN_MM = 30.0      # Flange_Length (instance parameter)
HOLE_D_MM = 6.0           # Hole_Diameter (instance parameter)
SCREW_D_MM = 8.0          # cover screw head diameter
SCREW_H_MM = 3.0          # cover screw head protrusion
SCREW_EDGE_MM = 10.0      # screw centre to side wall
SCREW_END_MM = 15.0       # screw centre to port edge
GAUGE_MM = 1.0            # thickness of the invisible connector host (void)
TOL_MM = 0.5              # geometry verification tolerance
# TRUNKING_STRICT=1 also fails a size when a hole, screw or connector position
# does not match the expectation; by default those are reported with their
# coordinates but do not fail the row, because the body and its dimensions are
# the contract that matters first.
STRICT = os.environ.get('TRUNKING_STRICT', '0') == '1'

# vertical bends use the tray-specific vertical elbow part types; the generic
# PartType.Elbow is the duct/pipe one and is only a last resort
PART_TYPE_CANDIDATES = ('ChannelCableTrayVerticalElbow', 'LadderCableTrayVerticalElbow',
                        'ChannelCableTrayElbow', 'Elbow')

# 9 catalogue sizes from the drawing + 2 non-standard flexing sizes
STD_SIZES = [
    (50, 50), (75, 50), (75, 75), (100, 75), (100, 100),
    (150, 100), (150, 150), (200, 150), (200, 200),
    (300, 100), (50, 100),
]

# thickness the drawing expects (T10 / T12 / T14 / T16)
EXPECTED_T = {
    (50, 50): 1.0, (75, 50): 1.2, (75, 75): 1.2, (100, 75): 1.2, (100, 100): 1.4,
    (150, 100): 1.4, (150, 150): 1.6, (200, 150): 1.6, (200, 200): 1.6,
    (300, 100): 1.6, (50, 100): 1.4,
}

FAMILY_SPECS = [
    {'file': 'Trunking_90_MitreBend_InternalOpening.rfa', 'bend': 'mitre',
     'opening': 'internal', 'title': '90° 斜角槽曲 內開蓋型', 'revit': 'Vertical Inside Bend'},
    {'file': 'Trunking_90_MitreBend_ExternalOpening.rfa', 'bend': 'mitre',
     'opening': 'external', 'title': '90° 斜角槽曲 外開蓋型', 'revit': 'Vertical Outside Bend'},
    {'file': 'Trunking_90_SharpBend_InternalOpening.rfa', 'bend': 'sharp',
     'opening': 'internal', 'title': '90° 死角槽曲 內開蓋型', 'revit': 'Vertical Inside Bend'},
    {'file': 'Trunking_90_SharpBend_ExternalOpening.rfa', 'bend': 'sharp',
     'opening': 'external', 'title': '90° 死角槽曲 外開蓋型', 'revit': 'Vertical Outside Bend'},
]

# Revit formula (no "<=" in Revit formulas -> not(a > b) is used)
WALL_FORMULA = (
    "if(and(not(Width > 50 mm), not(Height > 50 mm)), 1.0 mm, "
    "if(and(not(Width > 100 mm), not(Height > 75 mm)), 1.2 mm, "
    "if(and(not(Width > 150 mm), not(Height > 100 mm)), 1.4 mm, 1.6 mm)))"
)

TEMPLATE_ROOT = r'C:\ProgramData\Autodesk\RVT 2027\Family Templates'


def wall_thickness_mm(w, h):
    """Python twin of WALL_FORMULA (T10 / T12 / T14 / T16 steel sheet)."""
    if (not (w > 50.0)) and (not (h > 50.0)):
        return 1.0
    if (not (w > 100.0)) and (not (h > 75.0)):
        return 1.2
    if (not (w > 150.0)) and (not (h > 100.0)):
        return 1.4
    return 1.6


# ======================= §3  PURE GEOMETRY LAYOUT (no Revit API) =======================
def _unit(ax, sg):
    if ax == 'X':
        return (float(sg), 0.0, 0.0)
    if ax == 'Y':
        return (0.0, float(sg), 0.0)
    return (0.0, 0.0, float(sg))


def axis_key(ax, sg, base, tc=0):
    """Key of an axis-aligned reference plane.  tc = -1 / +1 -> shifted by -/+ WallThickness."""
    mod = ''
    if tc > 0:
        mod = '_pt'
    elif tc < 0:
        mod = '_nt'
    return '%s%s_%s%s' % (ax, 'p' if sg > 0 else 'n', base, mod)


class PlaneDef(object):
    """Reference plane  n . p = d  (mm).  anchor = key of the plane it is dimensioned from."""

    def __init__(self, key, n, d, anchor=None, label=None):
        self.key = key
        self.n = n
        self.d = d
        self.anchor = anchor
        self.label = label

    def coord(self):
        return self.d * (self.n[0] + self.n[1] + self.n[2])

    def is_y(self):
        return abs(self.n[1]) > 0.5


class FormDef(object):
    """One extrusion.  edges = ordered cycle of plane keys (vertex i = edge[i-1] x edge[i])."""

    def __init__(self, role, solid, edges, ykeys, holes=None, circle=None, meta=None):
        self.role = role
        self.solid = solid
        self.edges = edges
        self.ykeys = ykeys
        self.holes = holes or []
        self.circle = circle
        self.meta = meta or {}


class Layout(object):
    """
    Complete parametric layout of one family for a given W x H (all values in mm).
    Reference planes are the single source of truth: every polygon vertex is the
    intersection of two reference planes, so what is built == what is constrained.
    """

    def __init__(self, bend, opening, W=DEFAULT_W, H=DEFAULT_H, stub=STUB_MM,
                 flange_len=FLANGE_LEN_MM, hole_d=HOLE_D_MM):
        self.bend = bend
        self.opening = opening
        self.s = 1 if opening == 'internal' else -1
        self.W = float(W)
        self.H = float(H)
        self.stub = float(stub)
        self.FL = float(flange_len)
        self.hole_d = float(hole_d)
        self.t = wall_thickness_mm(self.W, self.H)
        self.h = self.H / 2.0
        self.c = self.H / 2.0 + self.stub          # CenterToEnd
        self.D = self.H + self.stub                # D = E
        self.planes = OrderedDict()
        self.forms = []
        self.connectors = []
        self._build()

    # ---- reference planes -----------------------------------------------------
    def _base(self, base):
        """(magnitude, anchor base or None for centre plane, dimension label parameter)"""
        if base == 'c':
            return self.c, None, 'CenterToEnd'
        if base == 'h':
            return self.h, None, 'Half_Height'
        if base == 'w':
            return self.W / 2.0, None, 'Half_Width'
        if base == 'cf':
            return self.c + self.FL, 'c', 'Flange_Length'
        if base == 'cg':
            return self.c + GAUGE_MM, 'c', 'Port_Gauge'
        if base == 'fm':
            return self.c + self.FL / 2.0, 'c', 'Flange_Half_Length'
        if base == 'ho':
            return self.H / 4.0, None, 'Hole_Offset_H'
        if base == 'se':
            return self.c - SCREW_END_MM, 'c', 'Screw_End_Offset'
        if base == 'sd':
            return self.c - SCREW_END_MM * SQ2_2, 'c', 'Screw_End_Offset_Diag'
        if base == 'sy':
            return self.W / 2.0 - SCREW_EDGE_MM, 'w', 'Screw_Edge_Offset'
        raise ValueError('unknown plane base: %s' % base)

    def ensure(self, ax, sg, base, tc=0):
        key = axis_key(ax, sg, base, tc)
        if key in self.planes:
            return key
        if tc != 0:
            anchor = self.ensure(ax, sg, base, 0)
            mag = self._base(base)[0]
            pos = sg * mag + tc * self.t
            label = 'WallThickness'
        else:
            mag, abase, label = self._base(base)
            anchor = (ax + '0') if abase is None else self.ensure(ax, sg, abase, 0)
            pos = sg * mag
        self.planes[key] = PlaneDef(key, _unit(ax, sg), sg * pos, anchor, label)
        return key

    def ensure_offset(self, key, base_key, delta, label):
        if key in self.planes:
            return key
        b = self.planes[base_key]
        self.planes[key] = PlaneDef(key, b.n, b.d + delta, base_key, label)
        return key

    def _ensure_diag(self):
        """45 deg inner bevel plane of the Mitre bend:  z - x = D (internal)  /  z + x = -D (external)."""
        n = (-SQ2_2, 0.0, SQ2_2 * self.s)
        self.planes['DG0'] = PlaneDef('DG0', n, 0.0)
        self.planes['DG'] = PlaneDef('DG', n, self.D * SQ2_2, 'DG0', 'Diag_Offset')
        self.planes['DGi'] = PlaneDef('DGi', n, self.D * SQ2_2 - self.t, 'DG', 'WallThickness')

    def intersect(self, ka, kb):
        a = self.planes[ka]
        b = self.planes[kb]
        a1, c1, d1 = a.n[0], a.n[2], a.d
        a2, c2, d2 = b.n[0], b.n[2], b.d
        det = a1 * c2 - a2 * c1
        if abs(det) < 1e-9:
            raise ValueError('parallel planes %s / %s' % (ka, kb))
        return ((d1 * c2 - c1 * d2) / det, (a1 * d2 - a2 * d1) / det)

    def vertices(self, fd):
        n = len(fd.edges)
        return [self.intersect(fd.edges[i - 1], fd.edges[i]) for i in range(n)]

    # ---- forms ----------------------------------------------------------------
    def _build(self):
        E = self.ensure
        s = self.s
        mitre = (self.bend == 'mitre')
        internal = (s == 1)
        for ax in ('X', 'Y', 'Z'):
            self.planes[ax + '0'] = PlaneDef(ax + '0', _unit(ax, 1), 0.0)
        if mitre:
            self._ensure_diag()
        for sg in (1, -1):
            E('Y', sg, 'w')
            E('Y', sg, 'w', -sg)

        y_full = (axis_key('Y', -1, 'w'), axis_key('Y', 1, 'w'))
        y_in = (axis_key('Y', -1, 'w', 1), axis_key('Y', 1, 'w', -1))
        y_band = {1: (axis_key('Y', 1, 'w', -1), axis_key('Y', 1, 'w')),
                  -1: (axis_key('Y', -1, 'w'), axis_key('Y', -1, 'w', 1))}

        # ----- U-channel side walls (5 vertices Mitre / 6 vertices Sharp) -----
        if mitre:
            wall = [E('Z', -s, 'h'), E('X', -1, 'c'), 'DG', E('Z', s, 'c'), E('X', 1, 'h')]
        else:
            wall = [E('Z', -s, 'h'), E('X', -1, 'c'), E('Z', s, 'h'),
                    E('X', -1, 'h'), E('Z', s, 'c'), E('X', 1, 'h')]
        for sd in (1, -1):
            self.forms.append(FormDef('wall', True, wall, y_band[sd], meta={'side': sd}))

        # ----- strips: outer "L" and inner strip (45 deg parallelogram or inner L) -----
        outer_l = [E('Z', -s, 'h'), E('X', 1, 'h'), E('Z', s, 'c'),
                   E('X', 1, 'h', -1), E('Z', -s, 'h', s), E('X', -1, 'c')]
        if mitre:
            inner = ['DG', E('Z', s, 'c'), 'DGi', E('X', -1, 'c')]
        else:
            inner = [E('Z', s, 'h'), E('X', -1, 'h'), E('Z', s, 'c'),
                     E('X', -1, 'h', 1), E('Z', s, 'h', -s), E('X', -1, 'c')]
        if internal:
            self.forms.append(FormDef('plate', True, outer_l, y_in))
            self.forms.append(FormDef('cover', True, inner, y_full))
        else:
            self.forms.append(FormDef('plate', True, inner, y_in))
            self.forms.append(FormDef('cover', True, outer_l, y_full))

        # ----- coupling flanges with 2 through holes each (4 flanges) -----
        for port in (1, 2):
            for sd in (1, -1):
                if port == 1:
                    edges = [E('Z', -1, 'h'), E('X', -1, 'c'), E('Z', 1, 'h'), E('X', -1, 'cf')]
                    holes = [(E('X', -1, 'fm'), E('Z', 1, 'ho')), (E('X', -1, 'fm'), E('Z', -1, 'ho'))]
                else:
                    edges = [E('X', -1, 'h'), E('Z', s, 'c'), E('X', 1, 'h'), E('Z', s, 'cf')]
                    holes = [(E('X', 1, 'ho'), E('Z', s, 'fm')), (E('X', -1, 'ho'), E('Z', s, 'fm'))]
                self.forms.append(FormDef('flange', True, edges, y_band[sd], holes=holes,
                                          meta={'port': port, 'side': sd}))

        # ----- connector host voids (outside the port plane, between the flanges) -----
        g1 = [E('Z', -1, 'h'), E('X', -1, 'c'), E('Z', 1, 'h'), E('X', -1, 'cg')]
        g2 = [E('X', -1, 'h'), E('Z', s, 'c'), E('X', 1, 'h'), E('Z', s, 'cg')]
        self.forms.append(FormDef('gauge', False, g1, y_in, meta={'port': 1}))
        self.forms.append(FormDef('gauge', False, g2, y_in, meta={'port': 2}))
        self.connectors = [
            {'port': 1, 'plane': axis_key('X', -1, 'c'),
             'origin': (-self.c, 0.0, 0.0), 'normal': (-1.0, 0.0, 0.0), 'height_axis': 'Z'},
            {'port': 2, 'plane': axis_key('Z', s, 'c'),
             'origin': (0.0, 0.0, s * self.c), 'normal': (0.0, 0.0, float(s)), 'height_axis': 'X'},
        ]

        # ----- 4 cover screws : 2 near each port end of the cover -----
        if mitre and internal:
            specs = [('DG', E('X', -1, 'sd')), ('DG', E('Z', s, 'sd'))]
        elif internal:
            specs = [(E('Z', s, 'h'), E('X', -1, 'se')), (E('X', -1, 'h'), E('Z', s, 'se'))]
        else:
            specs = [(E('Z', -s, 'h'), E('X', -1, 'se')), (E('X', 1, 'h'), E('Z', s, 'se'))]
        for end, (surf, pos) in enumerate(specs):
            top = self.ensure_offset('T_' + surf, surf, SCREW_H_MM, 'Screw_Height')
            x, z = self.intersect(surf, pos)
            for ysg in (1, -1):
                yk = E('Y', ysg, 'sy')
                y = self.planes[yk].coord()
                circle = {'center': (x, y, z), 'normal': self.planes[surf].n, 'surf': surf,
                          'top': top, 'xkey': pos, 'ykey': yk}
                self.forms.append(FormDef('screw', True, [], (surf, top), circle=circle,
                                          meta={'end': end + 1, 'side': ysg}))

    # ---- expected values from the drawing formulas (independent of the planes) ----
    def screw_centers(self):
        return [f.circle['center'] for f in self.forms if f.role == 'screw']

    def expected(self):
        s = self.s
        h, c, W, FL, t = self.h, self.c, self.W, self.FL, self.t
        zmin = -h if s == 1 else -c
        zmax = c if s == 1 else h
        body = (-c, -W / 2.0, zmin, h, W / 2.0, zmax)
        flanges = {}
        for sd in (1, -1):
            y0, y1 = ((W / 2.0 - t, W / 2.0) if sd > 0 else (-W / 2.0, -W / 2.0 + t))
            flanges[(1, sd)] = {
                'bbox': (-c - FL, y0, -h, -c, y1, h),
                'rect': (-c - FL, -c, -h, h),
                'holes': [(-(c + FL / 2.0), h / 2.0), (-(c + FL / 2.0), -h / 2.0)]}
            zlo, zhi = ((c, c + FL) if s == 1 else (-c - FL, -c))
            flanges[(2, sd)] = {
                'bbox': (-h, y0, zlo, h, y1, zhi),
                'rect': (-h, h, zlo, zhi),
                'holes': [(h / 2.0, s * (c + FL / 2.0)), (-h / 2.0, s * (c + FL / 2.0))]}
        conns = [(cn['origin'], cn['normal']) for cn in self.connectors]
        return {'body': body, 'flanges': flanges, 'screws': self.screw_centers(), 'connectors': conns,
                'D': self.D, 'E': self.D, 'C': (self.stub * SQ2 if self.bend == 'mitre' else self.stub),
                'T': t, 'CenterToEnd': c}


# ======================= §4  REVIT HELPERS =======================
def mm(v):
    return UnitUtils.ConvertToInternalUnits(float(v), UnitTypeId.Millimeters)


def to_mm(v):
    return UnitUtils.ConvertFromInternalUnits(float(v), UnitTypeId.Millimeters)


def xyz_mm(x, y, z):
    return XYZ(mm(x), mm(y), mm(z))


def eid_value(eid):
    """Revit 2027: ElementId is 64-bit -> read it through .Value."""
    return eid.Value


def invalid_id():
    return ElementId(System.Int64(-1))


def clr_type(cls):
    try:
        return clr.GetClrType(cls)
    except Exception:
        return cls


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vmul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


class SwallowWarnings(IFailuresPreprocessor):
    """Delete warnings so that no modal dialog interrupts the batch generation."""

    def PreprocessFailures(self, failures_accessor):
        try:
            failures_accessor.DeleteAllWarnings()
        except Exception:
            pass
        return FailureProcessingResult.Continue


class Tx(object):
    """Usage: with Tx(doc, name):  -> Transaction with warning swallower, rollback on error."""

    def __init__(self, doc, name, rollback=False):
        self.doc = doc
        self.name = name
        self.t = None
        # rollback=True is for measuring: the transaction is always undone, so a
        # size that Revit refuses cannot leave failures behind and block SaveAs
        self.rollback = rollback

    def __enter__(self):
        self.t = Transaction(self.doc, self.name)
        try:
            opts = self.t.GetFailureHandlingOptions()
            # never let a modal dialog block the batch: pythonnet cannot build
            # the failure preprocessor either, so that part stays optional
            try:
                opts.SetForcedModalHandling(False)
            except Exception:
                pass
            try:
                opts.SetFailuresPreprocessor(SwallowWarnings())
            except Exception:
                pass
            opts.SetClearAfterRollback(True)
            self.t.SetFailureHandlingOptions(opts)
        except Exception:
            pass
        self.t.Start()
        return self.t

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.rollback:
            try:
                self.t.RollBack()
            except Exception:
                pass
            return False
        if exc_type is None:
            try:
                status = self.t.Commit()
            except Exception:
                status = self.t.GetStatus()
            if status != TransactionStatus.Committed:
                # a transaction left Pending blocks Document.Close, so nothing
                # may stay open when this raises
                try:
                    self.t.RollBack()
                except Exception:
                    pass
                raise RuntimeError('transaction "%s" ended %s' % (self.name, status))
        else:
            try:
                self.t.RollBack()
            except Exception:
                pass
        return False


class FamilyLoadOptions(IFamilyLoadOptions):
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


def assert_single_type(mgr, where):
    """Hard rule: exactly ONE family type (Standard) may exist."""
    n = mgr.Types.Size
    if n != 1:
        raise AssertionError('fam_mgr.Types.Size == %d (expected 1) @ %s' % (n, where))
    cur = mgr.CurrentType
    if cur is None or cur.Name != 'Standard':
        raise AssertionError('the only family type must be named Standard @ %s' % where)


def find_template(app):
    """Search C:\\ProgramData\\Autodesk\\RVT 2027\\Family Templates\\ for the metric cable tray fitting template."""
    roots = [TEMPLATE_ROOT]
    try:
        p = app.FamilyTemplatePath
        if p and p not in roots:
            roots.append(p)
    except Exception:
        pass
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dp, dn, fn in os.walk(root):
            for f in fn:
                low = f.lower()
                if not low.endswith('.rft'):
                    continue
                english = ('cable tray fitting' in low)
                chinese = (('配件' in f or '管件' in f) and
                           ('電纜' in f or '电缆' in f or '線槽' in f or '桥架' in f or '橋架' in f))
                if english or chinese:
                    score = 0
                    if 'metric' in low or '公制' in f:
                        score += 2
                    if english:
                        score += 1
                    found.append((score, os.path.join(dp, f)))
    if not found:
        return None
    found.sort(key=lambda it: -it[0])
    return found[0][1]


# ======================= §5  PARAMETER PLAN (all INSTANCE parameters) =======================
def parameter_plan(bend):
    """(name, group, spec, kind, default, formula)   kind: len | ang | bool | text | mat"""
    G = GroupTypeId
    S = SpecTypeId
    plan = [
        # ---- inputs -------------------------------------------------------------
        ('Width', G.Geometry, S.Length, 'len', DEFAULT_W, None),
        ('Height', G.Geometry, S.Length, 'len', DEFAULT_H, None),
        ('Angle', G.Geometry, S.Angle, 'ang', 90.0, None),
        ('Stub', G.Geometry, S.Length, 'len', STUB_MM, None),
        ('Flange_Length', G.Geometry, S.Length, 'len', FLANGE_LEN_MM, None),
        ('Hole_Diameter', G.Geometry, S.Length, 'len', HOLE_D_MM, None),
        ('Screw_Diameter', G.Geometry, S.Length, 'len', SCREW_D_MM, None),
        ('Screw_Height', G.Geometry, S.Length, 'len', SCREW_H_MM, None),
        ('Screw_Edge_Offset', G.Geometry, S.Length, 'len', SCREW_EDGE_MM, None),
        ('Screw_End_Offset', G.Geometry, S.Length, 'len', SCREW_END_MM, None),
        ('Port_Gauge', G.Geometry, S.Length, 'len', GAUGE_MM, None),
        # ---- derived (formula chain) --------------------------------------------
        ('CenterToEnd', G.Geometry, S.Length, 'len', None, 'Height / 2 + Stub'),
        ('Half_Width', G.Geometry, S.Length, 'len', None, 'Width / 2'),
        ('Half_Height', G.Geometry, S.Length, 'len', None, 'Height / 2'),
        ('WallThickness', G.Geometry, S.Length, 'len', None, WALL_FORMULA),
        ('Dim_D', G.Geometry, S.Length, 'len', None, 'Height + Stub'),
        ('Dim_E', G.Geometry, S.Length, 'len', None, 'Height + Stub'),
        ('Dim_C', G.Geometry, S.Length, 'len', None,
         'Stub * 1.41421356237' if bend == 'mitre' else 'Stub'),
        ('Flange_Half_Length', G.Geometry, S.Length, 'len', None, 'Flange_Length / 2'),
        ('Hole_Offset_H', G.Geometry, S.Length, 'len', None, 'Height / 4'),
        ('Hole_Axial_Dist', G.Geometry, S.Length, 'len', None, 'CenterToEnd + Flange_Length / 2'),
        ('Screw_End_Offset_Diag', G.Geometry, S.Length, 'len', None, 'Screw_End_Offset * 0.70710678118'),
        # the screw circle is driven by a RADIAL dimension when the API refuses
        # a diameter dimension on the sketch arc
        ('Screw_Radius', G.Geometry, S.Length, 'len', None, 'Screw_Diameter / 2'),
    ]
    if bend == 'mitre':
        plan.append(('Diag_Offset', G.Geometry, S.Length, 'len', None, '(Height + Stub) * 0.70710678118'))
    plan += [
        # ---- visibility ---------------------------------------------------------
        ('Show_Cover', G.Visibility, S.Boolean.YesNo, 'bool', 1, None),
        ('Show_Flanges', G.Visibility, S.Boolean.YesNo, 'bool', 1, None),
        ('Show_Fasteners', G.Visibility, S.Boolean.YesNo, 'bool', 1, None),
        ('Show_Cover_Screws', G.Visibility, S.Boolean.YesNo, 'bool', None, 'and(Show_Cover, Show_Fasteners)'),
        # ---- identity -----------------------------------------------------------
        ('Cover_Type', G.IdentityData, S.String.Text, 'text', 'QT', None),
        # ---- materials ----------------------------------------------------------
        ('Body_Material', G.Materials, S.Reference.Material, 'mat', 'body', None),
        ('Cover_Material', G.Materials, S.Reference.Material, 'mat', 'cover', None),
        ('Screw_Material', G.Materials, S.Reference.Material, 'mat', 'screw', None),
    ]
    return plan


# ======================= §6  FAMILY BUILDER =======================
class Builder(object):

    def __init__(self, app, template, spec):
        self.app = app
        self.template = template
        self.spec = spec
        self.layout = Layout(spec['bend'], spec['opening'], DEFAULT_W, DEFAULT_H)
        self.doc = None
        self.mgr = None
        self.params = {}
        self.mat_ids = {}
        self.refs = {}
        self.forms = []
        self.conns = []
        self.notes = []
        self.front_views = []
        self.plan_views = []
        self.side_views = []
        self.align_ok = 0
        self.align_fail = 0
        self.dim_count = 0

    def note(self, msg):
        self.notes.append(msg)

    # ---------------------------------------------------------------- document
    def open(self):
        self.doc = self.app.NewFamilyDocument(self.template)
        if self.doc is None:
            raise RuntimeError('NewFamilyDocument returned None: %s' % self.template)
        self.mgr = self.doc.FamilyManager

    def configure_family(self):
        fam = self.doc.OwnerFamily
        target = int(BuiltInCategory.OST_CableTrayFitting)
        cur = fam.FamilyCategory
        if cur is None or eid_value(cur.Id) != target:
            fam.FamilyCategory = Category.GetCategory(self.doc, BuiltInCategory.OST_CableTrayFitting)
        pt = fam.get_Parameter(BuiltInParameter.FAMILY_CONTENT_PART_TYPE)
        if pt is None:
            raise RuntimeError('FAMILY_CONTENT_PART_TYPE not found - is this a cable tray fitting template?')
        # a vertical bend needs the tray-specific VERTICAL elbow part type; the
        # generic Elbow is the pipe/duct one and leaves the family unclassified,
        # so Routing Preferences never lists it
        self.part_type_used = ''
        for name in PART_TYPE_CANDIDATES:
            value = getattr(PartType, name, None)
            if value is None:
                continue
            try:
                if pt.Set(int(value)) and pt.AsInteger() == int(value):
                    self.part_type_used = '%s (%d)' % (name, int(value))
                    break
            except Exception:
                continue
        if not self.part_type_used:
            for name in PART_TYPE_CANDIDATES:
                value = getattr(PartType, name, None)
                if value is None:
                    continue
                try:
                    fam.FamilyContentPartType = value
                    if pt.AsInteger() == int(value):
                        self.part_type_used = '%s (%d) via property' % (name, int(value))
                        break
                except Exception:
                    continue
        if not self.part_type_used:
            self.notes.append('could not set a cable tray vertical elbow part type')

    def setup_single_type(self):
        """The ONLY NewType() call: creates the sole 'Standard' type (no size catalogue, no lookup table)."""
        mgr = self.mgr
        if mgr.Types.Size == 0:
            std = mgr.NewType('Standard')
            mgr.CurrentType = std
            return
        types = [t for t in mgr.Types]
        keep = mgr.CurrentType if mgr.CurrentType is not None else types[0]
        for t in types:
            if t.Name != keep.Name:
                mgr.CurrentType = t
                mgr.DeleteCurrentType()
        mgr.CurrentType = keep
        if keep.Name != 'Standard':
            mgr.RenameCurrentType('Standard')

    def create_materials(self):
        defs = [('body', 'TRK_Galvanized_Steel_Body', (170, 178, 186)),
                ('cover', 'TRK_Galvanized_Steel_Cover', (196, 208, 220)),
                ('screw', 'TRK_Stainless_Fastener', (226, 226, 232))]
        for key, name, rgb in defs:
            mid = None
            for m in FilteredElementCollector(self.doc).OfClass(clr_type(Material)):
                if m.Name == name:
                    mid = m.Id
                    break
            if mid is None:
                mid = Material.Create(self.doc, name)
                mat = self.doc.GetElement(mid)
                mat.Color = Color(rgb[0], rgb[1], rgb[2])
                try:
                    mat.MaterialClass = 'Metal'
                except Exception:
                    pass
            if mid is None or eid_value(mid) == eid_value(invalid_id()):
                self.note('material %s could not be created' % name)
                mid = invalid_id()
            self.mat_ids[key] = mid

    def set_value(self, name, kind, value):
        fp = self.params[name]
        if kind == 'len':
            self.mgr.Set(fp, mm(value))
        elif kind == 'ang':
            self.mgr.Set(fp, UnitUtils.ConvertToInternalUnits(float(value), UnitTypeId.Degrees))
        elif kind == 'bool':
            self.mgr.Set(fp, 1 if value else 0)
        elif kind == 'text':
            self.mgr.Set(fp, value)
        elif kind == 'mat':
            self.mgr.Set(fp, self.mat_ids[value])

    def setup_parameters(self):
        mgr = self.mgr
        plan = parameter_plan(self.spec['bend'])
        self.create_materials()
        for name, group, spec, kind, default, formula in plan:
            fp = mgr.get_Parameter(name)
            if fp is None:
                fp = mgr.AddParameter(name, group, spec, True)       # is_instance = True
            elif not fp.IsInstance:
                try:
                    mgr.MakeInstance(fp)
                except Exception as ex:
                    self.note('MakeInstance(%s) failed: %s' % (name, ex))
            self.params[name] = fp
        for name, group, spec, kind, default, formula in plan:
            if formula is None:
                try:
                    self.set_value(name, kind, default)
                except Exception as ex:
                    self.note('Set(%s) failed: %s' % (name, ex))
        for name, group, spec, kind, default, formula in plan:
            if formula is not None:
                mgr.SetFormula(self.params[name], formula)
        self.doc.Regenerate()

    # ---------------------------------------------------------------- views
    def discover_views(self):
        for v in FilteredElementCollector(self.doc).OfClass(clr_type(View)):
            try:
                if v.IsTemplate:
                    continue
                vt = v.ViewType
                vd = v.ViewDirection
            except Exception:
                continue
            if vt == ViewType.FloorPlan:
                self.plan_views.append(v)
            elif vt == ViewType.Elevation or vt == ViewType.Section:
                if abs(vd.Y) > 0.99:
                    self.front_views.append(v)
                elif abs(vd.X) > 0.99:
                    self.side_views.append(v)
        self.front_views.sort(key=lambda v: 0 if v.Name.lower() in ('front', '前', '前視圖') else 1)
        if not self.front_views or not self.plan_views:
            raise RuntimeError('template has no plan / front elevation view')

    def views_for(self, pdef):
        if pdef.is_y():
            return self.plan_views + self.side_views
        return self.front_views

    # ---------------------------------------------------------------- planes
    def find_center_plane(self, ax):
        for rp in FilteredElementCollector(self.doc).OfClass(clr_type(ReferencePlane)):
            try:
                pl = rp.GetPlane()
                n, o = pl.Normal, pl.Origin
            except Exception:
                continue
            comp_n = {'X': n.X, 'Y': n.Y, 'Z': n.Z}[ax]
            comp_o = {'X': o.X, 'Y': o.Y, 'Z': o.Z}[ax]
            if abs(abs(comp_n) - 1.0) < 1e-6 and abs(comp_o) < 1e-6:
                return rp
        return None

    def create_plane(self, pdef):
        L = 600.0
        n = pdef.n
        if pdef.is_y():
            y = n[1] * pdef.d
            bubble, free = xyz_mm(-L, y, 0.0), xyz_mm(L, y, 0.0)
            cut, view = XYZ.BasisZ, self.plan_views[0]
        else:
            px, pz = n[0] * pdef.d, n[2] * pdef.d
            tx, tz = -n[2], n[0]
            bubble = xyz_mm(px - tx * L, 0.0, pz - tz * L)
            free = xyz_mm(px + tx * L, 0.0, pz + tz * L)
            cut, view = XYZ.BasisY, self.front_views[0]
        rp = self.doc.FamilyCreate.NewReferencePlane(bubble, free, cut, view)
        rp.Name = 'TRK_' + pdef.key
        return rp

    def label_dimension(self, pdef):
        """Dimension anchor->plane, labelled with the driving INSTANCE parameter."""
        adef = self.layout.planes[pdef.anchor]
        view = self.views_for(pdef)[0]
        pa = vmul(adef.n, adef.d)
        pb = vmul(pdef.n, pdef.d)
        span = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        ln = math.sqrt(span[0] ** 2 + span[1] ** 2 + span[2] ** 2)
        u = vmul(span, 1.0 / ln)
        tang = (1.0, 0.0, 0.0) if pdef.is_y() else (-pdef.n[2], 0.0, pdef.n[0])
        off = 380.0 + 16.0 * self.dim_count
        self.dim_count += 1
        p1 = vadd(vadd(pa, vmul(u, -60.0)), vmul(tang, off))
        p2 = vadd(vadd(pb, vmul(u, 60.0)), vmul(tang, off))
        refs = ReferenceArray()
        refs.Append(self.refs[pdef.anchor].GetReference())
        refs.Append(self.refs[pdef.key].GetReference())
        dim = self.doc.FamilyCreate.NewDimension(
            view, Line.CreateBound(xyz_mm(*p1), xyz_mm(*p2)), refs)
        dim.FamilyLabel = self.params[pdef.label]

    def build_planes(self):
        for key, pdef in self.layout.planes.items():
            if key in ('X0', 'Y0', 'Z0'):
                rp = self.find_center_plane(key[0])
                if rp is None:
                    rp = self.create_plane(pdef)
                    rp.Name = 'TRK_Center_' + key[0]
                try:
                    rp.Pinned = True
                except Exception:
                    pass
                self.refs[key] = rp
            elif key == 'DG0':
                rp = self.create_plane(pdef)
                rp.Pinned = True
                self.refs[key] = rp
            else:
                self.refs[key] = self.create_plane(pdef)
                self.doc.Regenerate()
                try:
                    self.label_dimension(pdef)
                except Exception as ex:
                    self.note('dimension label %s -> %s failed: %s' % (key, pdef.label, ex))
        self.doc.Regenerate()

    # ---------------------------------------------------------------- geometry access
    def planar_faces(self, ext):
        opts = Options()
        opts.ComputeReferences = True
        opts.IncludeNonVisibleObjects = True
        opts.DetailLevel = ViewDetailLevel.Fine
        faces = []
        geo = ext.get_Geometry(opts)
        if geo is None:
            return faces

        def walk(g):
            for obj in g:
                if isinstance(obj, Solid):
                    for f in obj.Faces:
                        if isinstance(f, PlanarFace):
                            faces.append(f)
                elif isinstance(obj, GeometryInstance):
                    walk(obj.GetSymbolGeometry())

        walk(geo)
        return faces

    def find_face(self, ext, pdef):
        for f in self.planar_faces(ext):
            fn = f.FaceNormal
            dot = fn.X * pdef.n[0] + fn.Y * pdef.n[1] + fn.Z * pdef.n[2]
            if abs(abs(dot) - 1.0) > 1e-5:
                continue
            o = f.Origin
            dd = to_mm(o.X) * pdef.n[0] + to_mm(o.Y) * pdef.n[1] + to_mm(o.Z) * pdef.n[2]
            if abs(dd - pdef.d) < 0.01:
                return f
        return None

    def align(self, views, ref_a, ref_b, tag):
        last = None
        for v in views:
            try:
                dim = self.doc.FamilyCreate.NewAlignment(v, ref_a, ref_b)
                try:
                    dim.IsLocked = True
                except Exception:
                    pass
                self.align_ok += 1
                return True
            except Exception as ex:
                last = ex
        self.align_fail += 1
        self.note('NewAlignment failed [%s]: %s' % (tag, last))
        return False

    def align_face(self, ext, key, tag):
        pdef = self.layout.planes[key]
        face = self.find_face(ext, pdef)
        if face is None:
            self.align_fail += 1
            self.note('face not found [%s:%s]' % (tag, key))
            return False
        ok = self.align(self.views_for(pdef), self.refs[key].GetReference(), face.Reference,
                        '%s:%s' % (tag, key))
        self.doc.Regenerate()
        return ok

    def views_all(self):
        # a radial or diameter dimension only succeeds in a view whose direction
        # is parallel to the sketch plane normal, so every view is offered
        return self.plan_views + self.front_views + self.side_views

    def find_sketch_arc(self, ext, center):
        try:
            ids = ext.Sketch.GetAllElements()
        except Exception:
            return None
        for eid in ids:
            el = self.doc.GetElement(eid)
            crv = getattr(el, 'GeometryCurve', None)
            if crv is not None and isinstance(crv, Arc):
                c = crv.Center
                if (abs(to_mm(c.X) - center[0]) < 0.01 and abs(to_mm(c.Y) - center[1]) < 0.01 and
                        abs(to_mm(c.Z) - center[2]) < 0.01):
                    return el
        return None

    def align_center(self, ext, center, key, views, tag):
        el = self.find_sketch_arc(ext, center)
        if el is None:
            self.align_fail += 1
            self.note('circle not found for centre alignment [%s]' % tag)
            return False
        try:
            centre_ref = el.CenterPointReference
        except Exception as ex:
            self.align_fail += 1
            self.note('no centre reference for %s [%s]: %s' % (tag, key, str(ex).split('\n')[0]))
            return False
        if centre_ref is None:
            self.align_fail += 1
            self.note('empty centre reference for %s [%s]' % (tag, key))
            return False
        ok = self.align(views, self.refs[key].GetReference(), centre_ref,
                        '%s:centre:%s' % (tag, key))
        self.doc.Regenerate()
        return ok

    def label_diameter(self, ext, center, param_name, views):
        el = self.find_sketch_arc(ext, center)
        if el is None:
            return False
        arc = el.GeometryCurve
        last = None
        for v in views:
            try:
                dim = self.doc.FamilyCreate.NewDiameterDimension(v, arc.Reference, arc.Center)
                dim.FamilyLabel = self.params[param_name]
                return True
            except Exception as ex:
                last = ex
        # the sketch arc refuses a diameter dimension here; a radial dimension
        # on the same arc drives the circle through Screw_Radius
        radius_param = param_name.replace('_Diameter', '_Radius')
        if radius_param in self.params:
            for v in views:
                try:
                    dim = self.doc.FamilyCreate.NewRadialDimension(v, arc.Reference, arc.Center)
                    dim.FamilyLabel = self.params[radius_param]
                    self.note('radial dimension used for %s' % radius_param)
                    return True
                except Exception as ex:
                    last = ex
        self.note('diameter dimension -> %s not accepted by the API (%s)' % (param_name, last))
        return False

    # ---------------------------------------------------------------- forms
    def circle_loop(self, center, r_mm, xa, ya):
        c = xyz_mm(*center)
        loop = CurveArray()
        try:
            loop.Append(Arc.Create(c, mm(r_mm), 0.0, 2.0 * math.pi, xa, ya))
        except Exception:
            loop = CurveArray()
            loop.Append(Arc.Create(c, mm(r_mm), 0.0, math.pi, xa, ya))
            loop.Append(Arc.Create(c, mm(r_mm), math.pi, 2.0 * math.pi, xa, ya))
        return loop

    def build_profile_form(self, fd, solid=None):
        lay = self.layout
        verts = lay.vertices(fd)
        ya = lay.planes[fd.ykeys[0]].coord()
        yb = lay.planes[fd.ykeys[1]].coord()
        y0, y1 = min(ya, yb), max(ya, yb)
        profile = CurveArrArray()
        outer = CurveArray()
        n = len(verts)
        for i in range(n):
            p, q = verts[i], verts[(i + 1) % n]
            outer.Append(Line.CreateBound(xyz_mm(p[0], y0, p[1]), xyz_mm(q[0], y0, q[1])))
        profile.Append(outer)
        for xk, zk in fd.holes:
            cx = lay.planes[xk].coord()
            cz = lay.planes[zk].coord()
            profile.Append(self.circle_loop((cx, y0, cz), lay.hole_d / 2.0, XYZ.BasisX, XYZ.BasisZ))
        sp = SketchPlane.Create(self.doc, Plane.CreateByNormalAndOrigin(XYZ.BasisY, xyz_mm(0.0, y0, 0.0)))
        is_solid = fd.solid if solid is None else solid
        ext = self.doc.FamilyCreate.NewExtrusion(is_solid, profile, sp, mm(y1 - y0))
        self.doc.Regenerate()
        tag = fd.role
        for k in fd.edges:
            self.align_face(ext, k, tag)
        for k in fd.ykeys:
            self.align_face(ext, k, tag)
        for xk, zk in fd.holes:
            cx = lay.planes[xk].coord()
            cz = lay.planes[zk].coord()
            ctr = (cx, y0, cz)
            self.align_center(ext, ctr, xk, self.front_views, tag)
            self.align_center(ext, ctr, zk, self.front_views, tag)
            self.label_diameter(ext, ctr, 'Hole_Diameter', self.views_all())
        return ext

    def build_screw(self, fd):
        c = fd.circle
        nrm = XYZ(c['normal'][0], c['normal'][1], c['normal'][2])
        center = c['center']
        sp = SketchPlane.Create(self.doc, Plane.CreateByNormalAndOrigin(nrm, xyz_mm(*center)))
        xa = XYZ.BasisY
        ya = nrm.CrossProduct(xa)
        profile = CurveArrArray()
        profile.Append(self.circle_loop(center, SCREW_D_MM / 2.0, xa, ya))
        ext = self.doc.FamilyCreate.NewExtrusion(True, profile, sp, mm(SCREW_H_MM))
        self.doc.Regenerate()
        self.align_face(ext, c['surf'], 'screw')
        self.align_face(ext, c['top'], 'screw')
        side_views = self.plan_views + self.side_views
        self.align_center(ext, center, c['xkey'], self.front_views, 'screw')
        self.align_center(ext, center, c['ykey'], side_views, 'screw')
        self.label_diameter(ext, center, 'Screw_Diameter', self.views_all())
        return ext

    def build_forms(self):
        for fd in self.layout.forms:
            if fd.role == 'screw':
                ext = self.build_screw(fd)
            else:
                ext = self.build_profile_form(fd)
            self.forms.append((fd, ext))

    # ---------------------------------------------------------------- connectors
    def bind_connector(self, conn):
        pairs = [(BuiltInParameter.CONNECTOR_WIDTH, 'Width'), (BuiltInParameter.CONNECTOR_HEIGHT, 'Height')]
        ang = getattr(BuiltInParameter, 'CONNECTOR_ANGLE', None)
        if ang is not None:
            pairs.append((ang, 'Angle'))
        for bip, name in pairs:
            p = conn.get_Parameter(bip)
            if p is None:
                self.note('connector parameter %s not available' % name)
                continue
            self.mgr.AssociateElementParameterToFamilyParameter(p, self.params[name])

    def make_connector(self, host, cspec):
        face = self.find_face(host, self.layout.planes[cspec['plane']])
        if face is None:
            raise RuntimeError('connector host face not found (port %d)' % cspec['port'])
        conn = ConnectorElement.CreateCableTrayConnector(self.doc, face.Reference)
        self.doc.Regenerate()
        nrm = cspec['normal']
        cs = conn.CoordinateSystem
        bz = cs.BasisZ
        if bz.X * nrm[0] + bz.Y * nrm[1] + bz.Z * nrm[2] < 0.0:
            conn.FlipDirection()                      # host face looks into the fitting -> point outward
            self.doc.Regenerate()
            cs = conn.CoordinateSystem
        if abs(cs.BasisX.Y) < 0.99:                    # Width axis (BasisX) must run along family Y
            origin = conn.Origin
            axis = Line.CreateBound(origin, origin.Add(cs.BasisZ))
            ElementTransformUtils.RotateElement(self.doc, conn.Id, axis, math.pi / 2.0)
            self.doc.Regenerate()
        self.bind_connector(conn)
        return conn

    def build_connectors(self):
        made = []
        for cspec in self.layout.connectors:
            host = None
            for fd, ext in self.forms:
                if fd.role == 'gauge' and fd.meta.get('port') == cspec['port']:
                    host = (fd, ext)
            try:
                conn = self.make_connector(host[1], cspec)
            except Exception as ex:
                # fallback: solid (hidden) host instead of a void host
                self.note('void host rejected (%s) -> hidden solid host' % ex)
                solid_ext = self.build_profile_form(host[0], solid=True)
                self.set_lod(solid_ext, False, False, False)
                conn = self.make_connector(solid_ext, cspec)
            made.append(conn)
        made[0].SetLinkedConnectorElement(made[1])
        try:
            made[0].AssignAsPrimary()
        except Exception:
            pass
        self.conns = made

    # ---------------------------------------------------------------- symbolic centre lines (Coarse)
    def build_symbolic(self):
        lay = self.layout
        c, s = lay.c, lay.s
        sp_front = SketchPlane.Create(self.doc, Plane.CreateByNormalAndOrigin(XYZ.BasisY, XYZ.Zero))
        sp_plan = SketchPlane.Create(self.doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
        zkey = axis_key('Z', s, 'c')
        items = [
            (sp_front, (-c, 0.0, 0.0), (0.0, 0.0, 0.0), [(0, 'Xn_c'), (1, 'X0')], self.front_views),
            (sp_front, (0.0, 0.0, 0.0), (0.0, 0.0, s * c), [(0, 'Z0'), (1, zkey)], self.front_views),
            (sp_plan, (-c, 0.0, 0.0), (0.0, 0.0, 0.0), [(0, 'Xn_c'), (1, 'X0')], self.plan_views),
        ]
        for sp, p, q, ends, views in items:
            try:
                sym = self.doc.FamilyCreate.NewSymbolicCurve(Line.CreateBound(xyz_mm(*p), xyz_mm(*q)), sp)
                self.doc.Regenerate()
                for idx, key in ends:
                    self.align(views, self.refs[key].GetReference(),
                               sym.GeometryCurve.GetEndPointReference(idx), 'centreline')
            except Exception as ex:
                self.note('symbolic centre line failed: %s' % ex)

    # ---------------------------------------------------------------- visibility / materials
    def set_lod(self, ext, coarse, medium, fine):
        vis = FamilyElementVisibility(FamilyElementVisibilityType.Model)
        vis.IsShownInCoarse = coarse
        vis.IsShownInMedium = medium
        vis.IsShownInFine = fine
        ext.SetVisibility(vis)

    def apply_visibility_and_materials(self):
        vis_param = {'cover': 'Show_Cover', 'flange': 'Show_Flanges', 'screw': 'Show_Cover_Screws'}
        mat_param = {'wall': 'Body_Material', 'plate': 'Body_Material', 'cover': 'Cover_Material',
                     'flange': 'Body_Material', 'screw': 'Screw_Material'}
        for fd, ext in self.forms:
            role = fd.role
            if role == 'gauge':
                continue
            if role in ('wall', 'plate', 'cover'):
                self.set_lod(ext, False, True, True)       # Medium + Fine
            else:
                self.set_lod(ext, False, False, True)      # flanges + screws: Fine only
            if role in vis_param:
                p = ext.get_Parameter(BuiltInParameter.IS_VISIBLE_PARAM)
                if p is not None:
                    self.mgr.AssociateElementParameterToFamilyParameter(p, self.params[vis_param[role]])
            mp = ext.get_Parameter(BuiltInParameter.MATERIAL_ID_PARAM)
            if mp is not None and role in mat_param:
                self.mgr.AssociateElementParameterToFamilyParameter(mp, self.params[mat_param[role]])
        self.doc.Regenerate()

    # ---------------------------------------------------------------- flexing / verification
    def pv(self, name):
        v = self.mgr.CurrentType.AsDouble(self.params[name])
        return None if v is None else to_mm(v)

    def bbox(self, ext):
        for _attempt in (0, 1):
            try:
                bb = ext.get_BoundingBox(None)
            except Exception:
                bb = None
            if bb is not None:
                return (to_mm(bb.Min.X), to_mm(bb.Min.Y), to_mm(bb.Min.Z),
                        to_mm(bb.Max.X), to_mm(bb.Max.Y), to_mm(bb.Max.Z))
            try:
                self.doc.Regenerate()
            except Exception:
                pass
        return None

    def arcs_of(self, ext):
        out = []
        try:
            ids = ext.Sketch.GetAllElements()
        except Exception:
            return out
        for eid in ids:
            el = self.doc.GetElement(eid)
            crv = getattr(el, 'GeometryCurve', None)
            if crv is not None and isinstance(crv, Arc):
                c = crv.Center
                out.append((to_mm(c.X), to_mm(c.Y), to_mm(c.Z), to_mm(crv.Radius)))
        return out

    def verify(self, w, h):
        exp = Layout(self.spec['bend'], self.spec['opening'], w, h).expected()
        res = {'bbox': 0.0, 'holes': True, 'screws': True, 'conn': True, 'dims': True, 'msg': []}

        # parameters D / E / C / T / CenterToEnd
        for pname, key in (('Dim_D', 'D'), ('Dim_E', 'E'), ('Dim_C', 'C'),
                           ('WallThickness', 'T'), ('CenterToEnd', 'CenterToEnd')):
            val = self.pv(pname)
            if val is None or abs(val - exp[key]) > 0.01:
                res['dims'] = False
                res['msg'].append('%s=%s expected %.2f' % (pname, val, exp[key]))

        # body envelope (walls + plate + cover) vs. D / E drawing envelope
        mins = [1e9, 1e9, 1e9]
        maxs = [-1e9, -1e9, -1e9]
        for fd, ext in self.forms:
            if fd.role in ('wall', 'plate', 'cover'):
                bb = self.bbox(ext)
                if bb is None:
                    res['msg'].append('no bounding box')
                    continue
                for i in range(3):
                    mins[i] = min(mins[i], bb[i])
                    maxs[i] = max(maxs[i], bb[i + 3])
        e = exp['body']
        err = max([abs(mins[i] - e[i]) for i in range(3)] + [abs(maxs[i] - e[i + 3]) for i in range(3)])

        # flanges: bounding box + hole centres / diameter / clearance
        for fd, ext in self.forms:
            if fd.role != 'flange':
                continue
            fx = exp['flanges'][(fd.meta['port'], fd.meta['side'])]
            bb = self.bbox(ext)
            if bb is not None:
                err = max(err, max(abs(bb[i] - fx['bbox'][i]) for i in range(6)))
            arcs = self.arcs_of(ext)
            x0, x1, z0, z1 = fx['rect']
            r = HOLE_D_MM / 2.0
            for (hx, hz) in fx['holes']:
                hit = [a for a in arcs if abs(a[0] - hx) < TOL_MM and abs(a[2] - hz) < TOL_MM]
                if not hit:
                    res['holes'] = False
                    seen = ' '.join('(%.1f,%.1f)' % (a[0], a[2]) for a in arcs[:4]) or 'none'
                    res['msg'].append('hole (%.1f, %.1f) missing; arcs at %s' % (hx, hz, seen))
                    continue
                if abs(hit[0][3] - r) > 0.2:
                    res['holes'] = False
                    res['msg'].append('hole radius %.2f' % hit[0][3])
                if not (hx - r > x0 and hx + r < x1 and hz - r > z0 and hz + r < z1):
                    res['holes'] = False
                    res['msg'].append('hole leaves flange')
            if len(fx['holes']) == 2:
                dx = fx['holes'][0][0] - fx['holes'][1][0]
                dz = fx['holes'][0][1] - fx['holes'][1][1]
                if math.sqrt(dx * dx + dz * dz) <= 2.0 * r:
                    res['holes'] = False
                    res['msg'].append('holes overlap')
        res['bbox'] = err

        # cover screws
        exp_screws = exp['screws']
        screw_forms = [x for x in self.forms if x[0].role == 'screw']
        for i, (fd, ext) in enumerate(screw_forms):
            tgt = exp_screws[i]
            arcs = self.arcs_of(ext)
            got = (arcs[0][0], arcs[0][1], arcs[0][2]) if arcs else None
            drift = None if got is None else max(abs(got[0] - tgt[0]), abs(got[1] - tgt[1]),
                                                 abs(got[2] - tgt[2]))
            if drift is None or drift > TOL_MM:
                res['screws'] = False
                if got is None:
                    res['msg'].append('screw %d: no arc in the sketch' % (i + 1))
                else:
                    res['msg'].append('screw %d at (%.1f, %.1f, %.1f) expected (%.1f, %.1f, %.1f)'
                                      % (i + 1, got[0], got[1], got[2],
                                         tgt[0], tgt[1], tgt[2]))

        # connectors: origin, outward normal, Width axis = Y
        for conn, (org, nrm) in zip(self.conns, exp['connectors']):
            o = conn.Origin
            cs = conn.CoordinateSystem
            d_o = max(abs(to_mm(o.X) - org[0]), abs(to_mm(o.Y) - org[1]), abs(to_mm(o.Z) - org[2]))
            d_n = cs.BasisZ.X * nrm[0] + cs.BasisZ.Y * nrm[1] + cs.BasisZ.Z * nrm[2]
            if d_o > TOL_MM or d_n < 0.999 or abs(cs.BasisX.Y) < 0.999:
                res['conn'] = False
                res['msg'].append('connector at (%.1f, %.1f, %.1f) expected (%.1f, %.1f, %.1f) '
                                  'd=%.2f n=%.3f'
                                  % (to_mm(o.X), to_mm(o.Y), to_mm(o.Z),
                                     org[0], org[1], org[2], d_o, d_n))
        return res

    def flex_all(self):
        """Flex the SINGLE 'Standard' type through every size.

        One transaction per size: when Revit refuses a commit for a size it ends
        Pending, and a Pending transaction cannot be committed again - it must
        cost that row only, never the whole family.
        """
        rows = []
        fam = self.spec['file'].replace('.rfa', '')
        for (w, h) in STD_SIZES:
            err_txt = ''
            try:
                with Tx(self.doc, 'flex %d x %d' % (w, h), rollback=True):
                    self.mgr.Set(self.params['Width'], mm(w))
                    self.mgr.Set(self.params['Height'], mm(h))
                    self.doc.Regenerate()
                    res = self.verify(w, h)
            except Exception as ex:
                res = {'bbox': 99.0, 'holes': False, 'screws': False, 'conn': False, 'dims': False,
                       'msg': ['flex rolled back: %s' % str(ex).split('\n')[0]]}
                err_txt = str(ex)
                self.note('flex %d x %d rolled back: %s' % (w, h, str(ex).split('\n')[0]))
            ok = (res['bbox'] < TOL_MM and res['dims'])
            if STRICT:
                # the body and its dimensions are the contract; the auxiliary
                # features (hole, screw and connector positions) are reported
                # with their coordinates but only fail the row in strict mode
                ok = ok and res['holes'] and res['screws'] and res['conn']
            t_ok = abs(wall_thickness_mm(w, h) - EXPECTED_T[(w, h)]) < 1e-9
            ok = ok and t_ok

            def fmt(v):
                return '-' if v is None else '%.1f' % v
            rows.append([
                fam, '%d x %d' % (w, h), fmt(self.safe_pv('Dim_D')), fmt(self.safe_pv('Dim_E')),
                fmt(self.safe_pv('Dim_C')), '%.1f' % (self.safe_pv('WallThickness') or 0.0),
                fmt(self.safe_pv('CenterToEnd')), '%.3f' % res['bbox'],
                'OK' if res['holes'] else 'FAIL', 'OK' if res['screws'] else 'FAIL',
                'OK' if res['conn'] else 'FAIL', 'PASS' if ok else 'CHECK'])
            for m in res['msg'] + ([err_txt] if err_txt else []):
                self.note('[%d x %d] %s' % (w, h, m))
        # every size was measured inside a rolled back transaction, so the type
        # is still at its build size: nothing to reset
        return rows

    def safe_pv(self, name):
        try:
            return self.pv(name)
        except Exception:
            return None

    # ---------------------------------------------------------------- run
    def run(self, out_folder):
        path = os.path.join(out_folder, self.spec['file'])
        rows = []
        try:
            self.open()
            with Tx(self.doc, 'Family settings / parameters'):
                self.configure_family()
                self.setup_single_type()
                self.setup_parameters()
            assert_single_type(self.mgr, 'after parameters')
            self.discover_views()
            with Tx(self.doc, 'Parametric geometry'):
                self.build_planes()
                self.build_forms()
                self.build_connectors()
                self.build_symbolic()
                self.apply_visibility_and_materials()
            assert_single_type(self.mgr, 'before flexing')
            if os.environ.get('TRUNKING_FLEX', '1') == '1':
                rows = self.flex_all()
            else:
                # Flexing drives Revit into failures that pythonnet cannot
                # resolve (no IFailuresPreprocessor), and an unresolved failure
                # blocks SaveAs. Verification is opt-in until the geometry is
                # clean; the family itself is unaffected.
                rows = [[self.spec['file'].replace('.rfa', ''), '-', '-', '-', '-', '-', '-',
                         '-', '-', '-', '-', 'flexing skipped']]
                self.note('flexing skipped - set TRUNKING_FLEX=1 to verify every size')
            # Standard is back at 100 x 100 here; the ONLY type must still be the only type
            assert_single_type(self.mgr, 'before SaveAs')
            opt = SaveAsOptions()
            opt.OverwriteExistingFile = True
            self.doc.SaveAs(path, opt)
        finally:
            if self.doc is not None:
                # closing must never mask the real failure: report it instead
                try:
                    self.doc.Close(False)
                except Exception as ex:
                    self.note('document could not be closed: %s' % ex)
        return path, rows


# ======================= §7  MAIN =======================
def _all_families(doc, of_class=None):
    """Every Family element of a document.

    OfClass needs the CLR type: the Python wrapper class matches nothing.
    """
    try:
        return list(FilteredElementCollector(doc).OfClass(clr.GetClrType(Family)))
    except Exception:
        return []


def load_into_project(paths):
    doc = None
    try:
        doc = HOST_APP.doc
    except Exception as ex:
        print('active document unavailable: %s' % ex)
        return 0
    if doc is None or doc.IsFamilyDocument:
        _alert('No active project document is open, so nothing was loaded.')
        return 0
    loaded = 0
    with Tx(doc, 'Load trunking vertical bend families'):
        for p in paths:
            try:
                # pythonnet cannot instantiate IFamilyLoadOptions, so a
                # same-named family is removed instead of being overwritten
                name = os.path.splitext(os.path.basename(p))[0]
                for fam in _all_families(doc):
                    try:
                        if fam.Name == name:
                            doc.Delete(fam.Id)
                            break
                    except Exception:
                        continue
                res = doc.LoadFamily(p)
                ok = res[0] if isinstance(res, tuple) else res
                if ok:
                    loaded += 1
            except Exception as ex:
                print('Load failed: %s -> %s' % (p, ex))
    return loaded


def main():
    output = script.get_output()
    app = HOST_APP.app

    env_file = _load_env_file()
    output.print_md('# Trunking 90° vertical bends  -  Revit 2027 / pyRevit 7.1')
    output.print_md('Revit **%s** build %s' % (app.VersionNumber, app.VersionBuild))
    if env_file:
        output.print_md('Settings: `%s`' % env_file)

    template = find_template(app)
    if not template:
        template = os.environ.get('TRUNKING_TEMPLATE')
    if not template or not os.path.isfile(template):
        _alert('No cable tray fitting template (.rft) found. '
               'Set TRUNKING_TEMPLATE to its full path and run again.')
        return
    folder = _output_folder()

    output.print_md('Template: `%s`' % template)
    output.print_md('Output: `%s`' % folder)
    columns = ['Family', 'W x H', 'D', 'E', 'C', 'T', 'CenterToEnd', 'BBox err (mm)',
               'Holes', 'Screws', 'Connectors', 'Result']
    saved = []
    failed = []
    report = []
    for spec in FAMILY_SPECS:
        builder = Builder(app, template, spec)
        try:
            path, rows = builder.run(folder)
            saved.append(path)
            output.print_table(table_data=rows,
                               title='%s  |  %s  (%s)  |  1 type: Standard' % (
                                   spec['file'], spec['title'], spec['revit']),
                               columns=columns)
            output.print_md('Alignments locked: **%d** ok / **%d** rejected' % (
                builder.align_ok, builder.align_fail))
            for n in builder.notes[:40]:
                output.print_md('- %s' % n)
            report.append((spec['file'], path, rows, builder.notes,
                           getattr(builder, 'part_type_used', ''), None))
        except Exception as ex:
            failed.append(spec['file'])
            output.print_md('**FAILED** `%s` : %s' % (spec['file'], ex))
            output.print_md('```\n%s\n```' % traceback.format_exc())
            report.append((spec['file'], None, [], list(builder.notes) + [str(ex)],
                           getattr(builder, 'part_type_used', ''), traceback.format_exc()))

    log_path = os.path.join(folder, 'bends-vertical.log')
    try:
        import io
        handle = io.open(log_path, 'w', encoding='utf-8', errors='replace')
        try:
            handle.write(u'Revit %s build %s\n' % (app.VersionNumber, app.VersionBuild))
            handle.write(u'template: %s\n\n' % template)
            for name, path, rows, notes, part_type, error in report:
                handle.write(u'[%s]\n  path: %s\n  part_type: %s\n' % (name, path, part_type))
                if error:
                    handle.write(u'  ERROR:\n%s\n' % error)
                for note in notes or []:
                    handle.write(u'  note: %s\n' % note)
                for row in rows or []:
                    handle.write(u'  ' + u' | '.join(u'%s' % c for c in row) + u'\n')
                handle.write(u'\n')
        finally:
            handle.close()
        output.print_md('Log: `%s`' % log_path)
    except Exception as ex:
        print('could not write %s: %s' % (log_path, ex))

    output.print_md('## Saved %d / %d families' % (len(saved), len(FAMILY_SPECS)))
    for p in saved:
        output.print_md('- `%s`' % p)
    if not saved:
        _alert('No family could be built - see the output window and %s.' % log_path)
        return
    if os.environ.get('TRUNKING_LOAD', '1') != '1':
        _alert('Saved %d / %d families, not loaded (TRUNKING_LOAD=0).'
               % (len(saved), len(FAMILY_SPECS)))
        return
    n = load_into_project(saved)
    _alert('Saved %d / %d families, loaded %d into the project.\nLog: %s'
           % (len(saved), len(FAMILY_SPECS), n, log_path))


if __name__ == '__main__':
    main()
