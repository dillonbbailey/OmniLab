"""Ordinary USD saves retain composition; flattening requires explicit opt-in."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pxr import Sdf, Usd, UsdGeom
from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_project import capture_stage, restore_stage


class ExportTests(unittest.TestCase):
    def test_edited_dependency_remaps_clean_ancestors_without_overwriting_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            leaf = folder / "leaf.usda"
            leaf.write_text('#usda 1.0\ndef Sphere "Ball" {\n asset texture = @texture.<UDIM>.exr@\n}\n')
            branch = folder / "branch.usda"
            branch.write_text('#usda 1.0\n(subLayers = [@leaf.usda@ (offset = 10; scale = 2)])\n')
            root = folder / "root.usda"
            root.write_text('#usda 1.0\n(defaultPrim = "Ball"\nsubLayers = [@branch.usda@])\n')
            originals = {p: p.read_bytes() for p in (root, branch, leaf)}
            stage = Usd.Stage.Open(str(root))
            edits = StageEdits(stage)
            edits.set_edit_target(str(leaf))
            edits.set_property(dict(path="/Ball", group="Attributes", name="radius", value=4.0, time="frame", frame=24))
            edits.set_frame_range(2, 48)
            output = folder / "export/scene.usda"
            output.parent.mkdir()
            edits.export(output)
            saved = Usd.Stage.Open(str(output))
            self.assertEqual(saved.GetDefaultPrim().GetPath(), Sdf.Path("/Ball"))
            self.assertEqual((saved.GetStartTimeCode(), saved.GetEndTimeCode()), (2, 48))
            self.assertEqual(saved.GetPrimAtPath("/Ball").GetAttribute("radius").Get(24), 4)
            self.assertEqual(saved.GetPrimAtPath("/Ball").GetAttribute("radius").GetTimeSamples(), [24])
            texture = saved.GetPrimAtPath("/Ball").GetAttribute("texture").Get()
            self.assertTrue(texture.path.endswith("texture.<UDIM>.exr"))
            self.assertEqual(len(saved.GetLayerStack()), 5)  # session + wrapper + root + branch + leaf
            self.assertTrue(all(p.read_bytes() == text for p, text in originals.items()))
            self.assertNotIn("anon:", output.read_text())
            self.assertFalse(edits.state()["dirty"])

    def test_reference_variants_instances_and_project_restore_save(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            asset = Usd.Stage.CreateNew(str(folder / "asset.usdc"))
            UsdGeom.Sphere.Define(asset, "/Asset/Ball")
            asset.SetDefaultPrim(asset.GetPrimAtPath("/Asset"))
            asset.GetRootLayer().Save()
            stage = Usd.Stage.CreateInMemory()
            prim = stage.DefinePrim("/Model")
            prim.GetReferences().AddReference(asset.GetRootLayer().identifier)
            prim.SetInstanceable(True)
            variants = prim.GetVariantSets().AddVariantSet("look")
            for name in ("red", "blue"):
                variants.AddVariant(name)
            variants.SetVariantSelection("red")
            restored, retained, _ = restore_stage(capture_stage(stage))
            edits = StageEdits(restored)
            path = folder / "out.usda"
            edits.export(path, retained)
            saved = Usd.Stage.Open(str(path))
            model = saved.GetPrimAtPath("/Model")
            self.assertTrue(model.IsInstance() and model.HasAuthoredReferences())
            self.assertEqual(model.GetVariantSet("look").GetVariantNames(), ["blue", "red"])
            self.assertNotIn('def Sphere "Ball"', path.read_text())
            self.assertFalse((folder / "out_layers").exists())
            edits.add_prim("/", "New", "Xform")
            flattened = folder / "flattened.usda"
            edits.export(flattened, retained, flattened=True)
            self.assertTrue(edits.state()["dirty"])
            flat_stage = Usd.Stage.Open(str(flattened))
            # USD preserves instancing using generated internal prototypes.
            self.assertTrue(all(not reference.assetPath for reference in
                                flat_stage.GetRootLayer().GetPrimAtPath("/Model").referenceList.GetAppliedItems()))
            self.assertEqual(flat_stage.GetPrimAtPath("/Model").GetVariantSets().GetNames(), [])

    def test_in_place_save_and_failed_write_preserve_previous_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.usda"
            stage = Usd.Stage.CreateNew(str(path))
            UsdGeom.Sphere.Define(stage, "/Ball")
            stage.GetRootLayer().Save()
            edits = StageEdits(stage)
            edits.add_prim("/", "New", "Xform")
            edits.export(path)
            fresh = Usd.Stage.Open(Sdf.Layer.OpenAsAnonymous(str(path)))
            self.assertTrue(fresh.GetPrimAtPath("/New"))
            before = path.read_bytes()
            edits.set_frame_range(5, 25)
            with patch("omnilab.usd.usd_export.os.replace", side_effect=OSError("write failed")):
                with self.assertRaises(OSError):
                    edits.export(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(edits.state()["dirty"])
            self.assertFalse(list(Path(directory).glob("scene_layers/save-*")))


if __name__ == "__main__":
    unittest.main()
