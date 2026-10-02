"""Run using the native OpenUSD Python environment."""
from pathlib import Path
import tempfile
import unittest

from pxr import Usd, UsdGeom

from omnilab.usd.usd_new_stage import create_stage
from omnilab.usd.usd_project import capture_stage, restore_stage


class NewStageTests(unittest.TestCase):
    def test_memory_stage_can_be_edited_and_saved_in_project(self):
        stage, source = create_stage()
        self.assertTrue(stage.GetRootLayer().anonymous)
        self.assertEqual(source, stage.GetRootLayer().identifier)
        self.assertFalse(list(stage.Traverse()))
        self.assertEqual(UsdGeom.GetStageUpAxis(stage), "Y")
        self.assertEqual(UsdGeom.GetStageMetersPerUnit(stage), 1)
        UsdGeom.Cube.Define(stage, "/Cube")
        restored, layers, target = restore_stage(capture_stage(stage))
        self.assertTrue(restored.GetPrimAtPath("/Cube"))
        self.assertTrue(layers and target)

    def test_disk_formats_and_existing_file_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            for suffix, magic in ((".usda", b"#usda"), (".usdc", b"PXR-USDC")):
                path = Path(folder) / ("new" + suffix)
                stage, source = create_stage(path)
                self.assertEqual(source, str(path))
                self.assertFalse(stage.GetRootLayer().anonymous)
                self.assertTrue(path.read_bytes().startswith(magic))
                UsdGeom.Cube.Define(stage, "/Keep")
                stage.GetRootLayer().Save()
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "already exists"):
                    create_stage(path)
                self.assertEqual(path.read_bytes(), before)
                replacement, _ = create_stage(path, overwrite=True)
                self.assertFalse(replacement.GetPrimAtPath("/Keep"))
                self.assertTrue(Usd.Stage.Open(str(path)))
            with self.assertRaises(ValueError):
                create_stage(Path(folder) / "bad.usdz")
            with self.assertRaises(OSError):
                create_stage(Path(folder) / "missing" / "stage.usda")
            self.assertFalse(list(Path(folder).glob(".usd-new-*")))
