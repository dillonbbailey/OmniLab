"""Variant edits, composition strength, nested sets and rollback in native USD."""
import unittest

from pxr import Sdf, Usd

from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_variants import edit_variant, variant_choices


class VariantTests(unittest.TestCase):
    def setUp(self):
        self.stage = Usd.Stage.CreateInMemory()
        self.prim = self.stage.DefinePrim("/Asset", "Xform")
        self.variant = self.prim.GetVariantSets().AddVariantSet("shape")
        for name, kind in (("cube", "Cube"), ("sphere", "Sphere")):
            self.variant.AddVariant(name)
            self.variant.SetVariantSelection(name)
            with self.variant.GetVariantEditContext():
                self.stage.DefinePrim("/Asset/Shape", kind)
        self.variant.SetVariantSelection("cube")
        self.edits = StageEdits(self.stage)

    def edit(self, operation, name="shape", variant=""):
        return edit_variant(self.edits, "/Asset", operation, name, variant)

    def test_selection_undo_redo_and_selected_layer(self):
        source = self.stage.GetRootLayer().ExportToString()
        self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
        self.edit("select", variant="sphere")
        self.assertEqual(self.stage.GetPrimAtPath("/Asset/Shape").GetTypeName(), "Sphere")
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), source)
        self.edits.restore()
        self.assertEqual(self.variant.GetVariantSelection(), "cube")
        self.edits.restore(redo=True)
        self.assertEqual(self.variant.GetVariantSelection(), "sphere")

    def test_create_empty_set_add_variant_and_undo(self):
        self.edit("create", "look")
        self.assertIn(dict(name="look", selection="", variants=[]), variant_choices(self.prim))
        self.edit("add", "look", "warm-red")
        self.assertEqual(self.prim.GetVariantSet("look").GetVariantSelection(), "warm-red")
        self.assertEqual(self.stage.GetPrimAtPath("/Asset/Shape").GetTypeName(), "Cube")
        self.edits.restore()
        self.assertEqual(self.prim.GetVariantSet("look").GetVariantNames(), [])
        self.edits.restore()
        self.assertNotIn("look", self.prim.GetVariantSets().GetNames())

    def test_nested_sets_appear_only_in_current_composition(self):
        self.variant.SetVariantSelection("sphere")
        with self.variant.GetVariantEditContext():
            nested = self.prim.GetVariantSets().AddVariantSet("finish")
            nested.AddVariant("matte")
            nested.SetVariantSelection("matte")
        self.assertIn("finish", [s["name"] for s in variant_choices(self.prim)])
        self.edit("select", variant="cube")
        self.assertNotIn("finish", [s["name"] for s in variant_choices(self.prim)])
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            self.edit("add", "finish", "glossy")

    def test_stronger_selection_and_invalid_edits_roll_back(self):
        weak = Sdf.Layer.CreateAnonymous()
        self.stage.GetRootLayer().subLayerPaths.append(weak.identifier)
        self.edits.set_edit_target(weak.identifier)
        before = weak.ExportToString()
        for operation, name, variant in (("select", "shape", "sphere"), ("add", "shape", "new")):
            with self.assertRaisesRegex(ValueError, "stronger edit target"):
                self.edit(operation, name, variant)
            self.assertEqual(weak.ExportToString(), before)
        self.assertEqual(self.edits.undo, [])
        for operation, name, variant in (("create", "shape", ""), ("create", "bad name", ""),
                                          ("add", "shape", "cube"), ("select", "shape", "gone"),
                                          ("add", "shape", "")):
            with self.assertRaises(ValueError):
                self.edit(operation, name, variant)
            self.assertEqual(weak.ExportToString(), before)
        weak.SetPermissionToEdit(False)
        with self.assertRaisesRegex(ValueError, "permit editing"):
            self.edit("create", "look")

    def test_instance_roots_work_but_proxies_and_stage_root_are_read_only(self):
        instance = self.stage.DefinePrim("/Instance")
        instance.GetReferences().AddInternalReference("/Asset")
        instance.SetInstanceable(True)
        edit_variant(self.edits, "/Instance", "select", "shape", "sphere")
        self.assertEqual(self.stage.GetPrimAtPath("/Instance/Shape").GetTypeName(), "Sphere")
        self.assertEqual(self.variant.GetVariantSelection(), "cube")
        for path in ("/", "/Instance/Shape", "/Missing"):
            with self.assertRaisesRegex(ValueError, "editable prim"):
                edit_variant(self.edits, path, "create", "look")

    def test_usd_names_and_invalid_variant_rollback(self):
        self.edit("create", "look_dev")
        self.edit("add", "look_dev", "2026-warm")
        self.assertEqual(self.prim.GetVariantSet("look_dev").GetVariantSelection(), "2026-warm")
        before = self.stage.GetRootLayer().ExportToString()
        for name in ("bad name", "bad/name", "x}Other{look=y"):
            with self.assertRaisesRegex(ValueError, "valid USD variant name"):
                self.edit("add", "look_dev", name)
            self.assertEqual(self.stage.GetRootLayer().ExportToString(), before)


if __name__ == "__main__":
    unittest.main()
