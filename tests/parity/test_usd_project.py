"""Native USD project round trips: composition, assets, samples and isolation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt

from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_project import capture_stage, restore_stage


class ProjectStageTests(unittest.TestCase):
    def test_restored_asset_and_new_reference_to_original_keep_separate_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.usda"
            asset = Usd.Stage.CreateNew(str(path))
            sphere = UsdGeom.Sphere.Define(asset, "/Ball")
            sphere.CreateRadiusAttr(2)
            asset.GetRootLayer().Save()
            stage = Usd.Stage.CreateInMemory()
            stage.DefinePrim("/First").GetReferences().AddReference(str(path), "/Ball")
            restored, retained, _ = restore_stage(capture_stage(stage))
            cloned = next(layer for layer in retained if retained.sources.get(layer.identifier) == str(path))
            edited_asset = Usd.Stage.Open(cloned)
            edited_asset.GetPrimAtPath("/Ball").GetAttribute("radius").Set(5)
            restored.DefinePrim("/Second").GetReferences().AddReference(str(path), "/Ball")
            again, owned, _ = restore_stage(capture_stage(restored, retained))
            self.assertEqual(again.GetPrimAtPath("/First").GetAttribute("radius").Get(), 5)
            self.assertEqual(again.GetPrimAtPath("/Second").GetAttribute("radius").Get(), 2)

    def test_loaded_asset_is_embedded_if_its_file_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.usda"
            asset = Usd.Stage.CreateNew(str(path))
            UsdGeom.Sphere.Define(asset, "/Ball")
            asset.GetRootLayer().Save()
            stage = Usd.Stage.CreateInMemory()
            stage.DefinePrim("/Model").GetReferences().AddReference(str(path), "/Ball")
            restored, owned, _ = restore_stage(capture_stage(stage))
            path.unlink()
            for current, retained in ((stage, []), (restored, owned)):
                snapshot = capture_stage(current, retained)
                self.assertTrue(all("text" in record for record in snapshot["layers"]))
                again, kept, _ = restore_stage(snapshot)
                self.assertEqual(again.GetPrimAtPath("/Model").GetTypeName(), "Sphere")

    def test_clean_binary_assets_stay_external_and_legacy_projects_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.usdc"
            asset = Usd.Stage.CreateNew(str(path))
            mesh = UsdGeom.Mesh.Define(asset, "/Asset")
            mesh.CreatePointsAttr(Vt.Vec3fArray([Gf.Vec3f(i, i / 10, 0) for i in range(10000)]))
            asset.SetDefaultPrim(mesh.GetPrim())
            asset.GetRootLayer().Save()
            stage = Usd.Stage.CreateInMemory()
            stage.DefinePrim("/Model").GetPayloads().AddPayload(str(path))
            data = capture_stage(stage)
            record = next(item for item in data["layers"] if item["identifier"] == str(path))
            self.assertEqual(record["external"], str(path))
            self.assertLess(len(json.dumps(data)), 3000)
            legacy = capture_stage(stage, inline=(str(path),))
            legacy.pop("version")
            for record in legacy["layers"]:
                record.pop("source", None)
            restored, retained, _ = restore_stage(legacy)
            upgraded = capture_stage(restored, retained)
            self.assertLess(len(json.dumps(upgraded)), 3000)
            again, owned, _ = restore_stage(upgraded)
            self.assertEqual(len(again.GetPrimAtPath("/Model").GetAttribute("points").Get()), 10000)
            self.assertTrue(again.GetPrimAtPath("/Model").HasPayload())
            path.unlink()
            with self.assertRaisesRegex(ValueError, "dependency"):
                restore_stage(upgraded)

    def test_composition_arcs_and_variant_choices_survive_repeated_project_saves(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            asset_path = folder / "asset.usda"
            asset = Usd.Stage.CreateNew(str(asset_path))
            asset.SetDefaultPrim(asset.DefinePrim("/Asset", "Xform"))
            UsdGeom.Sphere.Define(asset, "/Asset/ReferencedBall")
            asset.GetRootLayer().Save()
            stage = Usd.Stage.CreateNew(str(folder / "scene.usda"))
            stage.SetDefaultPrim(stage.DefinePrim("/World", "Xform"))
            base = stage.CreateClassPrim("/_Base")
            base.CreateAttribute("inherited", Sdf.ValueTypeNames.Int).Set(12)
            special = stage.CreateClassPrim("/_Special")
            special.CreateAttribute("specialized", Sdf.ValueTypeNames.Int).Set(24)
            model = stage.DefinePrim("/World/Model", "Xform")
            model.GetReferences().AddReference("asset.usda", "/Asset", Sdf.LayerOffset(3, 2))
            model.GetInherits().AddInherit("/_Base")
            model.GetSpecializes().AddSpecialize("/_Special")
            model.SetInstanceable(True)
            payload = stage.DefinePrim("/World/Payload", "Xform")
            payload.GetPayloads().AddPayload("asset.usda", "/Asset", Sdf.LayerOffset(7, 3))
            variant_prim = stage.DefinePrim("/World/Variant", "Xform")
            variants = variant_prim.GetVariantSets().AddVariantSet("shape")
            for name, schema in (("sphere", UsdGeom.Sphere), ("cube", UsdGeom.Cube)):
                variants.AddVariant(name)
                variants.SetVariantSelection(name)
                with variants.GetVariantEditContext():
                    schema.Define(stage, "/World/Variant/Shape")
            variants.SetVariantSelection("sphere")
            stage.GetRootLayer().Save()
            before = {path: path.read_bytes() for path in folder.iterdir()}
            stage.Unload("/World/Payload")
            layers = []
            for cycle in range(3):
                data = capture_stage(stage, layers)
                stage, layers, _ = restore_stage(data)
                root_text = stage.GetRootLayer().ExportToString()
                # Authored arcs and unselected variants remain in the saved
                # layer; referenced geometry must not be baked into it.
                self.assertIn("references =", root_text)
                self.assertIn("payload =", root_text)
                self.assertIn("inherits =", root_text)
                self.assertIn("specializes =", root_text)
                self.assertNotIn('def Sphere "ReferencedBall"', root_text)
                model = stage.GetPrimAtPath("/World/Model")
                self.assertTrue(model.IsInstance())
                self.assertTrue(stage.GetPrimAtPath("/World/Model/ReferencedBall"))
                self.assertEqual(model.GetAttribute("inherited").Get(), 12)
                self.assertEqual(model.GetAttribute("specialized").Get(), 24)
                self.assertEqual(model.GetMetadata("references").prependedItems[0].layerOffset, Sdf.LayerOffset(3, 2))
                self.assertEqual(model.GetMetadata("inheritPaths").prependedItems, [Sdf.Path("/_Base")])
                self.assertEqual(model.GetMetadata("specializes").prependedItems, [Sdf.Path("/_Special")])
                payload = stage.GetPrimAtPath("/World/Payload")
                self.assertTrue(payload.HasAuthoredPayloads())
                self.assertFalse(payload.IsLoaded())
                self.assertEqual(payload.GetMetadata("payload").prependedItems[0].layerOffset, Sdf.LayerOffset(7, 3))
                variants = stage.GetPrimAtPath("/World/Variant").GetVariantSet("shape")
                self.assertEqual(set(variants.GetVariantNames()), {"sphere", "cube"})
                variants.SetVariantSelection("cube")
                self.assertEqual(stage.GetPrimAtPath("/World/Variant/Shape").GetTypeName(), "Cube")
                variants.SetVariantSelection("sphere")
            self.assertTrue(all(path.read_bytes() == content for path, content in before.items()))

    def test_nested_layers_session_samples_binding_and_assets_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "assets").mkdir()
            leaf = folder / "assets/leaf.usda"
            leaf.write_text('#usda 1.0\ndef Sphere "Ball" {\n asset texture = @texture.<UDIM>.exr@\n}\n')
            branch = folder / "branch.usda"
            branch.write_text('#usda 1.0\n(subLayers = [@assets/leaf.usda@ (offset = 10; scale = 2)])\n')
            root = folder / "root.usda"
            root.write_text('#usda 1.0\n(startTimeCode = 1\nendTimeCode = 40\nsubLayers = [@branch.usda@])\n')
            originals = {p: p.read_bytes() for p in (leaf, branch, root)}
            stage = Usd.Stage.Open(str(root))
            edits = StageEdits(stage)
            edits.set_edit_target(stage.GetSessionLayer().identifier)
            edits.add_prim("/", "SessionPrim", "Xform")
            material = UsdShade.Material.Define(stage, "/Materials/Gold")
            UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath("/Ball")).Bind(material)
            edits.set_edit_target(str(leaf))
            edits.set_property(dict(path="/Ball", group="Attributes", name="radius", value=3.0, time="frame", frame=24))
            edits.set_edit_target(str(root))
            edits.add_prim("/", "RootPrim", "Xform")
            edits.set_edit_target(str(leaf))
            snapshot = capture_stage(stage)
            restored, owned, target = restore_stage(snapshot)
            self.assertTrue(restored.GetPrimAtPath("/SessionPrim"))
            self.assertTrue(restored.GetPrimAtPath("/RootPrim"))
            self.assertEqual(len(restored.GetLayerStack()), 4)
            self.assertEqual(target.ListTimeSamplesForPath("/Ball.radius"), [7.0])
            self.assertEqual(restored.GetPrimAtPath("/Ball").GetAttribute("radius").GetTimeSamples(), [24.0])
            self.assertEqual(restored.GetPrimAtPath("/Ball").GetAttribute("texture").Get().path, str(folder / "assets/texture.<UDIM>.exr"))
            bound, _ = UsdShade.MaterialBindingAPI(restored.GetPrimAtPath("/Ball")).ComputeBoundMaterial()
            self.assertEqual(str(bound.GetPath()), "/Materials/Gold")
            self.assertEqual(restored.GetEditTarget().GetLayer(), target)
            restored.GetPrimAtPath("/Ball").GetAttribute("radius").Set(9, 24)
            self.assertEqual(stage.GetPrimAtPath("/Ball").GetAttribute("radius").Get(24), 3)
            again, kept, again_target = restore_stage(capture_stage(restored, owned))
            self.assertEqual(again.GetPrimAtPath("/Ball").GetAttribute("radius").Get(24), 9)
            self.assertEqual(again_target.ListTimeSamplesForPath("/Ball.radius"), [7.0])
            self.assertTrue(all(p.read_bytes() == text for p, text in originals.items()))

    def test_unloaded_embedded_payload_survives_resave_without_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.usda"
            path.write_text('#usda 1.0\n(defaultPrim = "Asset")\ndef Xform "Asset" {\n def Sphere "Ball" {}\n}\n')
            stage = Usd.Stage.CreateInMemory()
            stage.DefinePrim("/Model").GetPayloads().AddPayload(str(path))
            self.assertTrue(stage.GetPrimAtPath("/Model/Ball"))
            # Unsaved edits to an asset must remain embedded, even when its
            # payload is subsequently unloaded and the source is unavailable.
            asset = Usd.Stage.Open(Sdf.Layer.FindOrOpen(str(path)))
            UsdGeom.Sphere(asset.GetPrimAtPath("/Asset/Ball")).CreateRadiusAttr(7)
            restored, owned, _ = restore_stage(capture_stage(stage))
            restored.Unload("/Model")
            snapshot = capture_stage(restored, owned)
            path.unlink()
            again, keep, _ = restore_stage(snapshot)
            self.assertFalse(again.GetPrimAtPath("/Model").IsLoaded())
            again.Load("/Model")
            self.assertTrue(again.GetPrimAtPath("/Model/Ball"))

    def test_invalid_restore_preserves_source_stage(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(stage, "/Cube")
        snapshot = capture_stage(stage)
        for change in (dict(target="missing"), dict(load_rules=[["relative", "none"]])):
            bad = copy.deepcopy(snapshot)
            bad.update(change)
            with self.assertRaises(ValueError):
                restore_stage(bad)
        self.assertTrue(stage.GetPrimAtPath("/Cube"))


if __name__ == "__main__":
    unittest.main()
