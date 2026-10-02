"""Native USD duplication: independent authored copies and shared instances."""
import unittest
from pxr import Sdf, Usd, UsdGeom, UsdShade
from omnilab.usd.usd_editing import StageEdits


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.stage = Usd.Stage.CreateInMemory()
        self.root = UsdGeom.Xform.Define(self.stage, "/World/Model")
        self.root.AddTranslateOp().Set((1, 2, 3))
        self.ball = UsdGeom.Sphere.Define(self.stage, "/World/Model/Ball")
        self.ball.CreateRadiusAttr(2)
        self.edits = StageEdits(self.stage)

    def test_copy_layers_variants_samples_targets_and_undo(self):
        stage = self.stage
        session = stage.GetSessionLayer()
        with Usd.EditContext(stage, session):
            self.ball.GetRadiusAttr().Set(4, 20)
        self.root.GetPrim().CreateRelationship("pick").SetTargets([self.ball.GetPath()])
        self.root.GetPrim().CreateAttribute("link", Sdf.ValueTypeNames.Float).SetConnections(["/World/Model/Ball.radius"])
        variants = self.ball.GetPrim().GetVariantSets().AddVariantSet("look")
        for name in ("red", "blue"):
            variants.AddVariant(name)
        variants.SetVariantSelection("red")
        self.edits.set_edit_target(session.identifier)
        path = self.edits.duplicate_prim("/World/Model", "copy")
        copied = stage.GetPrimAtPath(path)
        self.assertEqual(path, "/World/Model_1")
        self.assertFalse(copied.IsInstanceable())
        self.assertEqual(copied.GetRelationship("pick").GetTargets(), [Sdf.Path(path + "/Ball")])
        self.assertEqual(copied.GetAttribute("link").GetConnections(), [Sdf.Path(path + "/Ball.radius")])
        ball = stage.GetPrimAtPath(path + "/Ball")
        self.assertEqual(ball.GetAttribute("radius").Get(20), 4)
        self.assertEqual(ball.GetVariantSet("look").GetVariantNames(), ["blue", "red"])
        self.assertEqual(len(self.edits.undo), 1)
        self.edits.restore()
        self.assertFalse(stage.GetPrimAtPath(path))
        self.edits.restore(redo=True)
        self.assertEqual(stage.GetPrimAtPath(path + "/Ball").GetAttribute("radius").Get(20), 4)
        self.ball.GetRadiusAttr().Set(9, 20)
        self.assertEqual(stage.GetPrimAtPath(path + "/Ball").GetAttribute("radius").Get(20), 4)
        self.assertEqual(self.edits.duplicate_prim("/World/Model", "copy"), "/World/Model_2")

    def test_instances_share_contents_but_keep_placement(self):
        first = self.edits.duplicate_prim("/World/Model", "instance")
        second = self.edits.duplicate_prim("/World/Model", "instance")
        a, b = self.stage.GetPrimAtPath(first), self.stage.GetPrimAtPath(second)
        self.assertTrue(a.IsInstance() and b.IsInstance())
        self.assertEqual(a.GetPrototype(), b.GetPrototype())
        self.ball.GetRadiusAttr().Set(7)
        self.root.GetOrderedXformOps()[0].Set((8, 8, 8))
        self.assertEqual(self.stage.GetPrimAtPath(first + "/Ball").GetAttribute("radius").Get(), 7)
        self.assertEqual(tuple(a.GetAttribute("xformOp:translate").Get()), (1, 2, 3))
        self.edits.restore()
        self.assertFalse(self.stage.GetPrimAtPath(second))
        self.edits.restore(redo=True)
        self.assertTrue(self.stage.GetPrimAtPath(second).IsInstance())
        plain = UsdGeom.Xform.Define(self.stage, "/Plain")
        path = self.edits.duplicate_prim("/Plain", "instance")
        plain.AddTranslateOp().Set((5, 5, 5))
        self.assertEqual(list(self.stage.GetPrimAtPath(path).GetAttribute("xformOpOrder").Get()), [])

    def test_reference_and_payload_arcs_are_preserved_in_copies(self):
        asset = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(asset, "/Asset/Cube")
        asset.SetDefaultPrim(asset.GetPrimAtPath("/Asset"))
        model = self.stage.GetPrimAtPath("/World/Model")
        model.GetReferences().AddReference(asset.GetRootLayer().identifier)
        model.GetPayloads().AddPayload(asset.GetRootLayer().identifier)
        self.stage.Unload(model.GetPath())
        before_rules = self.stage.GetLoadRules().GetRules()
        path = self.edits.duplicate_prim(str(model.GetPath()), "copy")
        copied = self.stage.GetPrimAtPath(path)
        self.assertTrue(copied.HasAuthoredReferences() and copied.HasPayload())
        self.assertFalse(copied.IsLoaded())
        self.assertIsNone(self.stage.GetRootLayer().GetPrimAtPath(path + "/Cube"))
        self.edits.restore()
        self.assertEqual(self.stage.GetLoadRules().GetRules(), before_rules)
        self.edits.restore(redo=True)
        self.assertFalse(self.stage.GetPrimAtPath(path).IsLoaded())

    def test_new_prim_clears_instanceability_in_stronger_layers(self):
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            self.root.GetPrim().SetInstanceable(True)
        path = self.edits.duplicate_prim("/World/Model", "copy")
        self.assertFalse(self.stage.GetPrimAtPath(path).IsInstanceable())
        self.assertTrue(self.stage.GetPrimAtPath("/World/Model").IsInstanceable())

    def test_nested_referenced_child_keeps_asset_and_local_overrides(self):
        asset = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(asset, "/Asset/Child/Ball")
        sphere.CreateRadiusAttr(3)
        material = UsdShade.Material.Define(asset, "/Asset/Looks/Material")
        UsdShade.MaterialBindingAPI.Apply(sphere.GetPrim()).Bind(material)
        asset.SetDefaultPrim(asset.GetPrimAtPath("/Asset"))
        model = self.stage.DefinePrim("/Referenced")
        model.GetReferences().AddReference(asset.GetRootLayer().identifier, "/Asset", Sdf.LayerOffset(3, 2))
        self.stage.GetPrimAtPath("/Referenced/Child/Ball").GetAttribute("radius").Set(5)
        path = self.edits.duplicate_prim("/Referenced/Child", "copy")
        copied = self.stage.GetPrimAtPath(path)
        self.assertTrue(copied.HasAuthoredReferences())
        self.assertEqual(copied.GetMetadata("references").appendedItems[0].layerOffset, Sdf.LayerOffset(3, 2))
        self.assertEqual(self.stage.GetPrimAtPath(path + "/Ball").GetAttribute("radius").Get(), 5)
        bound = UsdShade.MaterialBindingAPI(self.stage.GetPrimAtPath(path + "/Ball")).ComputeBoundMaterial()[0]
        self.assertEqual(str(bound.GetPath()), "/Referenced/Looks/Material")
        self.stage.GetPrimAtPath("/Referenced/Child/Ball").GetAttribute("radius").Set(8)
        self.assertEqual(self.stage.GetPrimAtPath(path + "/Ball").GetAttribute("radius").Get(), 5)

    def test_ancestor_variant_and_readonly_failure(self):
        variants = self.root.GetPrim().GetVariantSets().AddVariantSet("shape")
        variants.AddVariant("a")
        variants.SetVariantSelection("a")
        with variants.GetVariantEditContext():
            UsdGeom.Cube.Define(self.stage, "/World/Model/Cube")
        path = self.edits.duplicate_prim("/World/Model/Cube", "copy")
        self.assertEqual(self.stage.GetPrimAtPath(path).GetTypeName(), "Cube")
        before = self.stage.GetRootLayer().ExportToString()
        self.stage.GetRootLayer().SetPermissionToEdit(False)
        self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
        with self.assertRaisesRegex(ValueError, "permit editing"):
            self.edits.duplicate_prim("/World/Model", "copy")
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), before)
        self.assertFalse(self.stage.GetPrimAtPath("/World/Model_1"))


if __name__ == "__main__":
    unittest.main()
