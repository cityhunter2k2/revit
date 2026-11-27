"""Revit API shapes that only bite on a live release.

The first real Revit 2027 build died at the very first capability step because
``ElementId.IntegerValue`` no longer exists (``ElementId.Value`` replaced it in
2024). These tests drive the real method with a 2027-shaped document, so the
regression is caught without Revit.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trunking.model import SPEC_LENGTH, ParamDef  # noqa: E402
from trunking.revit_api import RevitApi, element_id_value  # noqa: E402

CATEGORY_ID = -2001000


class _ValueId(object):
    """Revit 2024+ ElementId."""

    def __init__(self, value):
        self.Value = value


class _LegacyId(object):
    """Pre-2024 ElementId, still accepted for older installs."""

    def __init__(self, value):
        self.IntegerValue = value


class _OpaqueId(object):
    pass


class _Category(object):
    def __init__(self, element_id, name="Cable Tray Fittings"):
        self.Id = element_id
        self.Name = name


class _Doc(object):
    def __init__(self, category):
        self.OwnerFamily = type("_OwnerFamily", (), {"FamilyCategory": category})()


class _DB(object):
    class BuiltInCategory(object):
        OST_CableTrayFitting = CATEGORY_ID


def _api():
    """A RevitApi without its constructor, which loads the Revit assemblies."""
    instance = RevitApi.__new__(RevitApi)
    instance.app = None
    instance._log = None
    instance._spec_by_name = {}
    instance._family_params = {}
    instance._transaction = None
    instance.DB = _DB
    return instance


class TestElementIdValue(unittest.TestCase):
    def test_reads_value(self):
        self.assertEqual(element_id_value(_ValueId(CATEGORY_ID)), CATEGORY_ID)

    def test_reads_the_legacy_integer_value(self):
        self.assertEqual(element_id_value(_LegacyId(CATEGORY_ID)), CATEGORY_ID)

    def test_large_int64_ids_survive(self):
        self.assertEqual(element_id_value(_ValueId(2 ** 40)), 2 ** 40)

    def test_refuses_an_unknown_shape(self):
        with self.assertRaises(AttributeError):
            element_id_value(_OpaqueId())


class TestCableTrayFittingCategory(unittest.TestCase):
    def test_accepts_the_2027_element_id(self):
        result = _api().ensure_cable_tray_fitting_category(_Doc(_Category(_ValueId(CATEGORY_ID))))
        self.assertTrue(result.ok, result.message)

    def test_accepts_the_legacy_element_id(self):
        result = _api().ensure_cable_tray_fitting_category(_Doc(_Category(_LegacyId(CATEGORY_ID))))
        self.assertTrue(result.ok, result.message)

    def test_reports_a_wrong_category(self):
        result = _api().ensure_cable_tray_fitting_category(
            _Doc(_Category(_ValueId(CATEGORY_ID + 1), "Generic Models"))
        )
        self.assertTrue(result.failed)
        self.assertIn("Generic Models", result.message)

    def test_missing_category_is_a_failure(self):
        result = _api().ensure_cable_tray_fitting_category(_Doc(None))
        self.assertTrue(result.failed)
        self.assertIn("no category", result.message)

    def test_unknown_element_id_is_a_failure_not_a_crash(self):
        result = _api().ensure_cable_tray_fitting_category(_Doc(_Category(_OpaqueId())))
        self.assertTrue(result.failed)
        self.assertIn("AttributeError", result.message)


class TestConnectorSizeBinding(unittest.TestCase):
    """2027 has no width/height overload; the size only follows the association."""

    def _doc(self):
        class _Manager(object):
            def __init__(self):
                self.associations = []

            def AssociateElementParameterToFamilyParameter(self, element_parameter, family_parameter):
                self.associations.append((element_parameter, family_parameter))

        class _FamilyDoc(object):
            def __init__(self):
                self.FamilyManager = _Manager()

        return _FamilyDoc()

    def _connector(self, available):
        class _Connector(object):
            def get_Parameter(self, bip):
                return "element-param:" + bip if bip in available else None

        return _Connector()

    def _api(self, parameter_names, bip_names):
        instance = _api()
        instance.DB = type("_DB", (), {"BuiltInParameter": type("_Bip", (), bip_names)})
        instance._param = lambda doc, name: parameter_names.get(name)
        return instance

    def test_binds_both_axes_with_the_2027_names(self):
        api = self._api(
            {"Width": "fam-width", "Height": "fam-height"},
            {"CONNECTOR_WIDTH": "cw", "CONNECTOR_HEIGHT": "ch"},
        )
        doc = self._doc()
        result = api.bind_connector_size(doc, self._connector({"cw", "ch"}), "Width", "Height")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(len(doc.FamilyManager.associations), 2)

    def test_accepts_the_legacy_rbs_names(self):
        api = self._api(
            {"Width": "fam-width", "Height": "fam-height"},
            {"RBS_CONNECTOR_WIDTH": "cw", "RBS_CONNECTOR_HEIGHT": "ch"},
        )
        doc = self._doc()
        result = api.bind_connector_size(doc, self._connector({"cw", "ch"}), "Width", "Height")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(len(doc.FamilyManager.associations), 2)

    def test_reports_a_missing_family_parameter(self):
        api = self._api(
            {"Width": "fam-width"},
            {"CONNECTOR_WIDTH": "cw", "CONNECTOR_HEIGHT": "ch"},
        )
        result = api.bind_connector_size(self._doc(), self._connector({"cw", "ch"}), "Width", "Height")
        self.assertEqual(result.status, "FALLBACK", result.message)
        self.assertIn("Height", result.message)

    def test_fails_when_no_axis_can_be_bound(self):
        api = self._api({}, {"CONNECTOR_WIDTH": "cw", "CONNECTOR_HEIGHT": "ch"})
        result = api.bind_connector_size(self._doc(), self._connector({"cw", "ch"}), "Width", "Height")
        self.assertTrue(result.failed, result.message)

    def test_partial_binding_is_a_fallback(self):
        api = self._api(
            {"Width": "fam-width", "Height": "fam-height"},
            {"CONNECTOR_WIDTH": "cw", "CONNECTOR_HEIGHT": "ch"},
        )
        # Height missing on the connector element: the build must keep going.
        result = api.bind_connector_size(self._doc(), self._connector({"cw"}), "Width", "Height")
        self.assertEqual(result.status, "FALLBACK", result.message)


class _TxDoc(object):
    def __init__(self):
        self.events = []

    def SaveAs(self, path, options):
        self.events.append("saveas")

    def Close(self, save):
        self.events.append("close")


class _FailureOptions(object):
    def __init__(self):
        self.forced_modal = None
        self.clear_after_rollback = None
        self.processor = None

    def SetForcedModalHandling(self, value):
        self.forced_modal = value

    def SetClearAfterRollback(self, value):
        self.clear_after_rollback = value

    def SetFailuresPreprocessor(self, processor):
        self.processor = processor


class _Transaction(object):
    def __init__(self, doc, name):
        self.doc = doc
        self.name = name
        self.committed = False
        self.applied = None

    def Start(self):
        self.doc.events.append("start")

    def Commit(self):
        self.committed = True
        self.doc.events.append("commit")

    def RollBack(self):
        self.doc.events.append("rollback")

    def GetStatus(self):
        return "committed"

    def GetFailureHandlingOptions(self):
        self.options = _FailureOptions()
        return self.options

    def SetFailureHandlingOptions(self, options):
        self.applied = options


class _SaveAsOptions(object):
    def __init__(self):
        self.OverwriteExistingFile = False


class _TxDB(object):
    Transaction = _Transaction
    SaveAsOptions = _SaveAsOptions

    class TransactionStatus(object):
        Committed = "committed"


def _tx_api():
    instance = _api()
    instance.DB = _TxDB
    return instance


class TestTransactionLifecycle(unittest.TestCase):
    """Every modification needs an open transaction, and the save needs a commit."""

    def test_open_starts_the_transaction(self):
        with tempfile.NamedTemporaryFile(suffix=".rft", delete=False) as handle:
            template = handle.name
        self.addCleanup(os.remove, template)
        doc = _TxDoc()
        api = _tx_api()
        api.app = type("_App", (), {"OpenDocumentFile": staticmethod(lambda path: doc)})()
        returned = api.open_family_template(template, "out.rfa")
        self.assertIs(returned, doc)
        self.assertEqual(doc.events, ["start"])

    def test_save_commits_before_saveas(self):
        doc = _TxDoc()
        api = _tx_api()
        api._begin_build_transaction(doc)
        result = api.save_family(doc, "out.rfa")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(doc.events, ["start", "commit", "saveas"])

    def test_save_without_a_transaction_fails(self):
        result = _tx_api().save_family(_TxDoc(), "out.rfa")
        self.assertTrue(result.failed)
        self.assertIn("no open transaction", result.message)

    def test_new_family_document_is_preferred(self):
        doc = _TxDoc()
        calls = []
        api = _tx_api()
        api.app = type(
            "_App",
            (),
            {
                "NewFamilyDocument": staticmethod(lambda path: calls.append("new") or doc),
                "OpenDocumentFile": staticmethod(lambda path: calls.append("open") or doc),
            },
        )()
        with tempfile.NamedTemporaryFile(suffix=".rft", delete=False) as handle:
            template = handle.name
        self.addCleanup(os.remove, template)
        api.open_family_template(template, "out.rfa")
        # OpenDocumentFile would hand back the template that is already open
        self.assertEqual(calls, ["new"])

    def test_falls_back_to_opening_the_file(self):
        doc = _TxDoc()
        calls = []

        def broken(path):
            raise RuntimeError("not supported here")

        api = _tx_api()
        api.app = type(
            "_App",
            (),
            {
                "NewFamilyDocument": staticmethod(broken),
                "OpenDocumentFile": staticmethod(lambda path: calls.append("open") or doc),
            },
        )()
        with tempfile.NamedTemporaryFile(suffix=".rft", delete=False) as handle:
            template = handle.name
        self.addCleanup(os.remove, template)
        api.open_family_template(template, "out.rfa")
        self.assertEqual(calls, ["open"])

    def test_the_parameter_cache_does_not_cross_documents(self):
        doc = _TxDoc()
        api = _tx_api()
        api._family_params = {"Width": _NamedParam("Width")}
        api._spec_by_name = {"Width": SPEC_LENGTH}
        api.app = type("_App", (), {"NewFamilyDocument": staticmethod(lambda path: doc)})()
        with tempfile.NamedTemporaryFile(suffix=".rft", delete=False) as handle:
            template = handle.name
        self.addCleanup(os.remove, template)
        api.open_family_template(template, "out.rfa")
        self.assertEqual(api._family_params, {})
        self.assertEqual(api._spec_by_name, {})

    def test_commit_disables_the_modal_dialog(self):
        doc = _TxDoc()
        api = _tx_api()
        api._begin_build_transaction(doc)
        transaction = api._transaction
        result = api.save_family(doc, "out.rfa")
        self.assertTrue(result.ok, result.message)
        self.assertIs(transaction.applied.forced_modal, False)
        self.assertIs(transaction.applied.clear_after_rollback, True)

    def test_commit_works_without_the_failure_interface(self):
        doc = _TxDoc()
        api = _tx_api()
        self.assertIsNone(api._failure_processor(doc))
        api._begin_build_transaction(doc)
        self.assertTrue(api.save_family(doc, "out.rfa").ok)

    def test_close_rolls_back_an_open_transaction(self):
        doc = _TxDoc()
        api = _tx_api()
        api._begin_build_transaction(doc)
        api.close_family(doc)
        self.assertEqual(doc.events, ["start", "rollback", "close"])

    def test_close_without_a_build_just_closes(self):
        doc = _TxDoc()
        _tx_api().close_family(doc)
        self.assertEqual(doc.events, ["close"])


class _Material(object):
    def __init__(self, name, element_id):
        self.Name = name
        self.Id = element_id


class _SetParam(object):
    def __init__(self):
        self.values = []

    def Set(self, value):
        self.values.append(value)


class TestMaterialHandling(unittest.TestCase):
    """Material.Create returns the id of the new material, not the material."""

    def _doc(self, material=None):
        class _Doc(object):
            def __init__(self):
                self.by_id = {42: material} if material is not None else {}

            def GetElement(self, element_id):
                return self.by_id.get(getattr(element_id, "Value", element_id))

        return _Doc()

    def _api(self, existing=()):
        class _Collector(object):
            def __init__(self, doc):
                pass

            def OfClass(self, klass):
                return list(existing)

        class _MaterialFactory(object):
            @staticmethod
            def Create(doc, name):
                return _ValueId(42)

        class _BuiltInParameter(object):
            MATERIAL_ID_PARAM = "material"

        class _DB(object):
            FilteredElementCollector = _Collector
            Material = _MaterialFactory
            BuiltInParameter = _BuiltInParameter

        instance = _api()
        instance.DB = _DB
        instance._param = lambda doc, name: None
        return instance

    def test_create_is_resolved_to_a_material(self):
        material = _Material("Galvanised Steel", _ValueId(42))
        api = self._api()
        resolved = api.ensure_material(self._doc(material), "Galvanised Steel")
        self.assertIs(resolved, material)

    def test_existing_material_is_reused(self):
        material = _Material("Galvanised Steel", _ValueId(42))
        api = self._api(existing=[material])
        self.assertIs(api.ensure_material(self._doc(), "Galvanised Steel"), material)

    def test_set_accepts_a_material(self):
        class _Element(object):
            def __init__(self):
                self.parameter = _SetParam()

            def get_Parameter(self, bip):
                return self.parameter

        element = _Element()
        material = _Material("Galvanised Steel", _ValueId(42))
        result = self._api().set_element_material(self._doc(), element, "Material", material)
        self.assertTrue(result.ok, result.message)
        self.assertEqual([v.Value for v in element.parameter.values], [42])
        self.assertIn("Galvanised Steel", result.message)

    def test_set_accepts_an_element_id(self):
        class _Element(object):
            def __init__(self):
                self.parameter = _SetParam()

            def get_Parameter(self, bip):
                return self.parameter

        element = _Element()
        material = _Material("Galvanised Steel", _ValueId(42))
        result = self._api().set_element_material(
            self._doc(material), element, "Material", _ValueId(42)
        )
        self.assertTrue(result.ok, result.message)
        self.assertEqual([v.Value for v in element.parameter.values], [42])
        self.assertIn("Galvanised Steel", result.message)


class _FamilyType(object):
    """A FamilyType whose Name dies with it, like the Revit proxy does."""

    def __init__(self, name):
        self._name = name
        self.deleted = False

    @property
    def Name(self):
        if self.deleted:
            raise RuntimeError("The family type does not exist in current document.")
        return self._name


class _TypeSet(object):
    def __init__(self, manager):
        self._manager = manager

    @property
    def Size(self):
        return len(self._manager.types)

    def __iter__(self):
        return iter(list(self._manager.types))


class _TypeManager(object):
    def __init__(self, names, fail_delete=False):
        self.types = [_FamilyType(name) for name in names]
        self.current = self.types[0] if self.types else None
        self.Types = _TypeSet(self)
        self.renamed = []
        self.fail_delete = fail_delete

    @property
    def CurrentType(self):
        return self.current

    @CurrentType.setter
    def CurrentType(self, value):
        self.current = value

    def DeleteCurrentType(self):
        if self.fail_delete:
            raise RuntimeError("delete refused")
        victim = self.current
        victim.deleted = True
        self.types.remove(victim)

    def RenameCurrentType(self, name):
        self.renamed.append(name)


def _type_doc(manager):
    return type("_Doc", (), {"FamilyManager": manager})()


class TestSingleType(unittest.TestCase):
    """The template ships three types; the delivered family has exactly one."""

    def test_reduces_three_types_to_one(self):
        manager = _TypeManager(["A", "B", "C"])
        result = _api().ensure_single_type(_type_doc(manager), "Standard")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(len(manager.types), 1)
        self.assertEqual(manager.renamed, ["Standard"])

    def test_reads_the_name_before_deleting_the_type(self):
        # _FamilyType.Name raises once the type is deleted, so this only passes
        # when the label is captured first.
        manager = _TypeManager(["A", "B"])
        result = _api().ensure_single_type(_type_doc(manager), "Standard")
        self.assertTrue(result.ok, result.message)
        self.assertIn("1 template type", result.message)

    def test_no_types_is_a_failure(self):
        result = _api().ensure_single_type(_type_doc(_TypeManager([])), "Standard")
        self.assertTrue(result.failed, result.message)

    def test_a_refused_delete_is_reported_not_raised(self):
        manager = _TypeManager(["A", "B"], fail_delete=True)
        result = _api().ensure_single_type(_type_doc(manager), "Standard")
        self.assertTrue(result.failed, result.message)
        self.assertIn("delete refused", result.message)


class _NamedParam(object):
    IsInstance = True

    def __init__(self, name):
        self.Definition = type("_Def", (), {"Name": name})()


class TestFormulaNames(unittest.TestCase):
    """Revit parses formulas against the names it stores, not ours."""

    def test_renames_known_parameters(self):
        api = _api()
        api._family_params = {"Width": _NamedParam("\u5bec\u5ea6"), "Height": _NamedParam("\u9ad8\u5ea6")}
        text = api.translated_formula("if(Width > Height, Width / 2, Height)")
        self.assertIn("\u5bec\u5ea6", text)
        self.assertIn("\u9ad8\u5ea6", text)
        self.assertNotIn("Width", text)

    def test_does_not_touch_a_substring(self):
        api = _api()
        api._family_params = {"Width": _NamedParam("\u5bec\u5ea6")}
        self.assertEqual(api.translated_formula("Half_Width + Width"), "Half_Width + \u5bec\u5ea6")

    def test_unchanged_when_names_match(self):
        api = _api()
        api._family_params = {"Width": _NamedParam("Width")}
        self.assertEqual(api.translated_formula("Width / 2"), "Width / 2")

    def test_no_parameters_means_no_change(self):
        self.assertEqual(_api().translated_formula("Width / 2"), "Width / 2")


class TestFormulaGuards(unittest.TestCase):
    """SetFormula on a name that is not in the family is what the crash fitted."""

    def _api(self, names):
        parameters = [_NamedParam(name) for name in names]
        formulas = []

        class _Manager(object):
            Parameters = parameters

            def SetFormula(self, parameter, formula):
                formulas.append((parameter, formula))

        manager = _Manager()
        doc = type("_Doc", (), {"FamilyManager": manager})()
        return _api(), doc, formulas

    def test_unknown_references_are_reported(self):
        api, doc, _ = self._api(["Half_Width", "Stub"])
        self.assertEqual(api._unknown_references(doc, "Width / 2"), ["Width"])
        self.assertEqual(api._unknown_references(doc, "Half_Width + Stub"), [])

    def test_units_and_keywords_are_not_references(self):
        api, doc, _ = self._api(["Half_Width"])
        self.assertEqual(api._unknown_references(doc, "if(Half_Width > 50 mm, 1 mm, 2 mm)"), [])

    def test_formula_with_a_missing_parameter_is_not_sent(self):
        api, doc, formulas = self._api(["Half_Width"])
        api._param = lambda doc, name: _NamedParam("Half_Width")
        result = api.set_formula(doc, "Half_Width", "Width / 2")
        self.assertTrue(result.failed, result.message)
        self.assertIn("Width", result.message)
        self.assertEqual(formulas, [])

    def test_a_resolvable_formula_is_sent(self):
        api, doc, formulas = self._api(["Half_Width", "Width"])
        api._param = lambda doc, name: _NamedParam("Half_Width")
        result = api.set_formula(doc, "Half_Width", "Width / 2")
        self.assertTrue(result.ok, result.message)
        self.assertEqual(len(formulas), 1)


class TestParameterNameCollision(unittest.TestCase):
    """A localised built-in owns the name; the family needs a suffixed twin."""

    def _api(self):
        class _SpecTypeId(object):
            Length = "spec:length"
            Angle = "spec:angle"

            class String(object):
                Text = "spec:text"

            class Boolean(object):
                YesNo = "spec:yesno"

            class Reference(object):
                Material = "spec:material"

        class _GroupTypeId(object):
            Geometry = "group:geometry"
            Data = "group:data"

        class _BuiltInParameterGroup(object):
            PG_GEOMETRY = "bip:geometry"
            PG_DATA = "bip:data"

        class _ParameterType(object):
            Length = "pt:length"

        class _DB(object):
            SpecTypeId = _SpecTypeId
            GroupTypeId = _GroupTypeId
            BuiltInParameterGroup = _BuiltInParameterGroup
            ParameterType = _ParameterType

        api = _api()
        api.DB = _DB
        return api

    def test_missing_group_falls_back_to_the_next_candidate(self):
        calls = []

        class _Manager(object):
            Parameters = []

            def AddParameter(self, name, group, spec, is_instance):
                calls.append((name, group))
                return _NamedParam(name)

        doc = type("_Doc", (), {"FamilyManager": _Manager()})()
        api = self._api()
        result = api.add_instance_parameter(doc, ParamDef("Width", SPEC_LENGTH, "Dimensions"))
        self.assertTrue(result.ok, result.message)
        # the fake DB has no GroupTypeId.Dimensions, only Geometry
        self.assertEqual(calls[0][1], "group:geometry")

    def test_collision_creates_a_suffixed_twin(self):
        created = []

        class _Manager(object):
            def __init__(self):
                self.Parameters = []

            def AddParameter(self, name, group, spec, is_instance):
                if name == "Width":
                    raise RuntimeError("The parameter name is already in use")
                parameter = _NamedParam(name)
                self.Parameters.append(parameter)
                created.append(name)
                return parameter

        manager = _Manager()
        doc = type("_Doc", (), {"FamilyManager": manager})()
        api = self._api()
        result = api.add_instance_parameter(doc, ParamDef("Width", SPEC_LENGTH, "Geometry"))
        self.assertEqual(result.status, "FALLBACK", result.message)
        self.assertIn("Width_TS", created)
        self.assertIn("Width", api._family_params)
        self.assertEqual(api.translated_formula("Width / 2"), "Width_TS / 2")


class TestFormulaNormalising(unittest.TestCase):
    def test_leading_minus_becomes_a_subtraction(self):
        self.assertEqual(RevitApi._normalise_formula("-(Half_Width + Cover_Overhang)"),
                         "0 - (Half_Width + Cover_Overhang)")
        self.assertEqual(RevitApi._normalise_formula("-Half_Height"), "0 - (Half_Height)")

    def test_ordinary_formulas_are_untouched(self):
        self.assertEqual(RevitApi._normalise_formula("Width / 2"), "Width / 2")
        self.assertEqual(RevitApi._normalise_formula("  Stub  "), "Stub")


class TestNoRemovedMembers(unittest.TestCase):
    def test_sources_do_not_use_element_id_integer_value(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for folder, dirs, files in os.walk(root):
            # Tests name removed members on purpose, so only production code counts.
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(folder, filename)
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                self.assertNotIn(
                    ".Id.IntegerValue",
                    source,
                    "%s still reads ElementId.IntegerValue, removed in Revit 2027"
                    % os.path.relpath(path, root),
                )


if __name__ == "__main__":
    unittest.main()
