"""Native metadata authoring, composition, validation, and persistence."""
from pathlib import Path
import tempfile
import unittest

from pxr import Sdf, Usd, UsdGeom

from omnilab.usd.usd_composition import new_sublayer
from omnilab.usd.usd_editing import StageEdits, property_info
from omnilab.usd.usd_inspection import property_rows
from omnilab.usd.usd_new_stage import create_stage
from omnilab.usd.usd_project import capture_stage, restore_stage
from omnilab.usd.usd_stage_metadata import stage_metadata

METADATA = dict(upAxis="Z", metersPerUnit=0.01, startTimeCode=-10.5, endTimeCode=80.25,
                framesPerSecond=30, timeCodesPerSecond=60, comment="Working scene", documentation="Asset notes")


class StageMetadataTests(unittest.TestCase):
    def test_new_stage_and_sublayer_memory_and_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            for path in ("", str(Path(folder) / "stage.usdc")):
                stage, _ = create_stage(path, metadata=METADATA)
                self.assertEqual(stage_metadata(stage), METADATA)
                if path:
                    self.assertEqual(stage_metadata(Usd.Stage.Open(path)), METADATA)
            for options in (dict(storage="memory", name="metadata"),
                            dict(storage="disk", path=str(Path(folder) / "layer.usda"))):
                layer, _ = new_sublayer(dict(options, metadata=METADATA))
                self.assertEqual(stage_metadata(Usd.Stage.Open(layer)), METADATA)
            stage, _ = create_stage()
            self.assertEqual(UsdGeom.GetStageUpAxis(stage), "Y")
            self.assertEqual(UsdGeom.GetStageMetersPerUnit(stage), 1)
            self.assertFalse(stage.HasAuthoredTimeCodeRange())
            layer, _ = new_sublayer(dict(storage="memory", name="default"))
            self.assertEqual(layer.pseudoRoot.GetInfo("upAxis"), "Y")
            self.assertEqual(layer.pseudoRoot.GetInfo("metersPerUnit"), 1)
            self.assertFalse(layer.HasStartTimeCode())

    def test_session_edit_with_sublayer_target_undo_and_persistence(self):
        stage, _ = create_stage()
        UsdGeom.Cube.Define(stage, "/Keep")
        stage.SetDefaultPrim(stage.GetPrimAtPath("/Keep"))
        stage.GetRootLayer().customLayerData = {"keep": "me"}
        editing = StageEdits(stage)
        identifier = editing.create_sublayer(dict(identifier=stage.GetRootLayer().identifier,
            expected=[], storage="memory", name="child", metadata=METADATA))
        child = Sdf.Layer.Find(identifier)
        self.assertEqual(UsdGeom.GetStageUpAxis(stage), "Y")
        self.assertEqual(UsdGeom.GetStageMetersPerUnit(stage), 1)
        editing.set_edit_target(identifier)
        root_before, child_before = stage.GetRootLayer().ExportToString(), child.ExportToString()
        editing.set_stage_metadata(METADATA)
        self.assertEqual(stage_metadata(stage), METADATA)
        self.assertEqual(editing.layer, child)
        self.assertEqual(stage.GetRootLayer().ExportToString(), root_before)
        self.assertEqual(child.ExportToString(), child_before)
        editing.restore()
        self.assertEqual(UsdGeom.GetStageUpAxis(stage), "Y")
        self.assertEqual(UsdGeom.GetStageMetersPerUnit(stage), 1)
        editing.restore(redo=True)
        self.assertEqual(stage_metadata(stage), METADATA)
        rows = {row["name"]: row for row in property_rows(stage.GetPseudoRoot(), Usd.TimeCode.Default())}
        self.assertTrue(rows["upAxis"]["editable"])
        self.assertIn("customLayerData", rows)
        self.assertFalse(rows["defaultPrim"]["editable"])
        self.assertEqual(property_info(stage.GetPseudoRoot(), "Metadata", "upAxis", Usd.TimeCode(0))["options"], ["Y", "Z"])
        restored, layers, target = restore_stage(capture_stage(stage))
        self.assertEqual(stage_metadata(restored), METADATA)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "export.usda"
            editing.export(path)
            reopened = Usd.Stage.Open(str(path))
            self.assertEqual(stage_metadata(reopened), METADATA)
            self.assertTrue(reopened.GetRootLayer().subLayerPaths)
            self.assertTrue(reopened.GetPrimAtPath("/Keep"))

    def test_invalid_metadata_does_not_create_files_or_change_stage(self):
        invalid = [dict(upAxis="X"), dict(metersPerUnit=0), dict(metersPerUnit=-1),
                   dict(metersPerUnit=float("nan")), dict(metersPerUnit=float("inf")),
                   dict(framesPerSecond=0), dict(timeCodesPerSecond=-1),
                   dict(startTimeCode=100, endTimeCode=1), dict(endTimeCode=2**32),
                   dict(comment=1), dict(unknown="value")]
        stage, _ = create_stage()
        edits = StageEdits(stage)
        before = stage.GetSessionLayer().ExportToString()
        with tempfile.TemporaryDirectory() as folder:
            for values in invalid:
                with self.subTest(values=values):
                    path = Path(folder) / "invalid.usda"
                    with self.assertRaises(ValueError):
                        create_stage(path, metadata=values)
                    with self.assertRaises(ValueError):
                        new_sublayer(dict(storage="disk", path=str(path), metadata=values))
                    with self.assertRaises(ValueError):
                        edits.set_stage_metadata(values)
                    self.assertFalse(path.exists())
                    self.assertEqual(stage.GetSessionLayer().ExportToString(), before)
                    self.assertFalse(edits.undo)
        stage.GetSessionLayer().SetPermissionToEdit(False)
        with self.assertRaises(ValueError):
            edits.set_stage_metadata(dict(upAxis="Z"))
        stage.GetSessionLayer().SetPermissionToEdit(True)
        edits.set_property(dict(path="/", group="Metadata", name="upAxis", value="Z"))
        self.assertEqual(UsdGeom.GetStageUpAxis(stage), "Z")


if __name__ == "__main__":
    unittest.main()
