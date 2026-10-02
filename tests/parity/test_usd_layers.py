"""Native USD layer targets, snapshots and cross-layer undo regressions."""
from pathlib import Path
import tempfile
import unittest

from pxr import Sdf, Usd, UsdGeom

from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_layers import layer_entries, layer_text


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.stage = Usd.Stage.CreateInMemory()
        self.root = self.stage.GetRootLayer()
        self.session = self.stage.GetSessionLayer()
        self.sub = Sdf.Layer.CreateAnonymous("animation.usda")
        self.root.subLayerPaths.append(self.sub.identifier)
        self.edits = StageEdits(self.stage)

    def test_default_target_is_root_and_session_remains_selectable(self):
        self.assertEqual(self.edits.layer, self.root)
        self.assertEqual([e["role"] for e in layer_entries(self.stage, self.edits) if e["active"]], ["Root"])
        self.edits.add_prim("/", "DefaultEdit", "Cube")
        self.assertTrue(self.root.GetPrimAtPath("/DefaultEdit"))
        self.assertFalse(self.session.GetPrimAtPath("/DefaultEdit"))
        self.edits.set_edit_target(self.session.identifier)
        self.edits.add_prim("/", "SessionEdit", "Sphere")
        self.assertTrue(self.session.GetPrimAtPath("/SessionEdit"))

    def test_nested_sublayer_links_resolve_relative_paths_and_shared_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            for name in ("a", "b"):
                folder = directory / name
                folder.mkdir()
                (folder / "leaf.usda").write_text(f'#usda 1.0\ndef Xform "{name}" {{}}\n')
            (directory / "a/branch.usda").write_text('#usda 1.0\n(subLayers = [@leaf.usda@])\n')
            (directory / "b/branch.usda").write_text('#usda 1.0\n(subLayers = [@../a/leaf.usda@, @leaf.usda@])\n')
            root = directory / "root.usda"
            root.write_text('#usda 1.0\n(subLayers = [@a/branch.usda@, @b/branch.usda@])\n')
            stage = Usd.Stage.Open(str(root))
            session_child = Sdf.Layer.CreateAnonymous("session-child.usda")
            stage.GetSessionLayer().subLayerPaths = [session_child.identifier]
            edits = StageEdits(stage)
            entries = {entry["identifier"]: entry for entry in layer_entries(stage, edits)}
            def children(identifier):
                return [child["identifier"] for child in entries[str(identifier)]["children"]]
            self.assertEqual(children(root), [str(directory / "a/branch.usda"), str(directory / "b/branch.usda")])
            self.assertEqual(children(directory / "a/branch.usda"), [str(directory / "a/leaf.usda")])
            self.assertEqual(children(directory / "b/branch.usda"), [str(directory / "a/leaf.usda"), str(directory / "b/leaf.usda")])
            self.assertEqual(children(stage.GetSessionLayer().identifier), [session_child.identifier])
            self.assertEqual(entries[str(directory / "b/branch.usda")]["sublayers"],
                             [dict(path="../a/leaf.usda", offset=0, scale=1), dict(path="leaf.usda", offset=0, scale=1)])

    def test_referenced_sublayers_remain_inspectable_children(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "geometry.usda").write_text('#usda 1.0\ndef Xform "Asset" {\n def Sphere "Ball" {}\n}\n')
            asset = directory / "asset.usda"
            asset.write_text('#usda 1.0\n(defaultPrim = "Asset"\nsubLayers = [@geometry.usda@])\n')
            self.stage.DefinePrim("/Ref").GetReferences().AddReference(str(asset))
            entries = {entry["identifier"]: entry for entry in layer_entries(self.stage, self.edits)}
            child_id = str(directory / "geometry.usda")
            self.assertEqual(entries[str(asset)]["children"][0]["identifier"], child_id)
            self.assertFalse(entries[child_id]["editable"])
            self.assertIn('Sphere "Ball"', layer_text(self.stage, child_id))

    def test_detached_file_layer_retains_edits_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            child = directory / "child.usda"
            child.write_text('#usda 1.0\ndef Sphere "Ball" {}\n')
            root = directory / "root.usda"
            root.write_text('#usda 1.0\n(subLayers = [@child.usda@])\n')
            stage = Usd.Stage.Open(str(root))
            edits = StageEdits(stage)
            edits.set_edit_target(str(child))
            edits.set_property(dict(path="/Ball", group="Attributes", name="radius", value=3.0))
            edits.set_sublayers(dict(identifier=str(root), expected=[dict(path="child.usda", offset=0, scale=1)], sublayers=[]))
            self.assertEqual(edits.layer, stage.GetRootLayer())
            self.assertTrue(edits.state()["dirty"])
            edits.restore()
            self.assertEqual(stage.GetPrimAtPath("/Ball").GetAttribute("radius").Get(), 3.0)
            edits.restore()
            self.assertFalse(edits.state()["dirty"])
            self.assertNotIn("radius", child.read_text())

    def test_exclusive_target_and_undo_redo_follow_original_layer(self):
        self.edits.set_edit_target(self.session.identifier)
        self.edits.add_prim("/", "SessionPrim", "Xform")
        self.edits.set_edit_target(self.root.identifier)
        self.edits.add_prim("/", "RootPrim", "Xform")
        self.edits.set_edit_target(self.sub.identifier)
        self.edits.add_prim("/", "SubPrim", "Xform")
        entries = layer_entries(self.stage, self.edits)
        self.assertEqual([e["role"] for e in entries], ["Session", "Root", "Sublayer"])
        self.assertEqual([e["identifier"] for e in entries if e["active"]], [self.sub.identifier])
        self.assertTrue(all(e["modified"] for e in entries))
        self.edits.set_edit_target(self.session.identifier)
        for layer, path in ((self.sub, "/SubPrim"), (self.root, "/RootPrim"), (self.session, "/SessionPrim")):
            self.edits.restore()
            self.assertFalse(layer.GetPrimAtPath(path))
            self.assertEqual(self.edits.layer, self.session)
        self.assertFalse(self.edits.state()["dirty"])
        for layer, path in ((self.session, "/SessionPrim"), (self.root, "/RootPrim"), (self.sub, "/SubPrim")):
            self.edits.restore(redo=True)
            self.assertTrue(layer.GetPrimAtPath(path))
            self.assertEqual(self.edits.layer, self.session)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "composed.usda"
            self.edits.export(path)
            saved = Usd.Stage.Open(str(path))
            self.assertTrue(all(saved.GetPrimAtPath(path) for path in ("/SessionPrim", "/RootPrim", "/SubPrim")))
            self.assertFalse(self.edits.state()["dirty"])
            self.edits.restore()
            self.assertTrue(self.edits.state()["dirty"])

    def test_target_maps_sublayer_time_offsets(self):
        self.root.subLayerOffsets[0] = Sdf.LayerOffset(10, 2)
        self.edits.set_edit_target(self.sub.identifier)
        self.edits.add_prim("/", "Ball", "Sphere")
        self.edits.set_property(dict(path="/Ball", group="Attributes", name="radius", value=3.0,
                                     time="frame", frame=24))
        self.assertEqual(self.sub.ListTimeSamplesForPath("/Ball.radius"), [7.0])
        self.assertEqual(self.stage.GetPrimAtPath("/Ball").GetAttribute("radius").GetTimeSamples(), [24.0])

    def test_readonly_and_reference_layers_inspection_and_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            asset_path = Path(directory) / "asset.usdc"
            asset = Usd.Stage.CreateNew(str(asset_path))
            UsdGeom.Sphere.Define(asset, "/Asset")
            asset.GetRootLayer().Save()
            original = asset_path.read_bytes()
            with Usd.EditContext(self.stage, self.root):
                self.stage.DefinePrim("/Ref").GetReferences().AddReference(str(asset_path), "/Asset")
            row = next(e for e in layer_entries(self.stage, self.edits) if e["identifier"] == str(asset_path))
            self.assertEqual(row["role"], "Referenced")
            self.assertFalse(row["editable"])
            text = layer_text(self.stage, str(asset_path))
            self.assertTrue(text.startswith("#usda 1.0"))
            self.assertIn('def Sphere "Asset"', text)
            for identifier in (str(asset_path), "missing.usda"):
                with self.assertRaises(ValueError):
                    self.edits.set_edit_target(identifier)
                self.assertEqual(self.edits.layer, self.root)
            self.sub.SetPermissionToEdit(False)
            try:
                self.assertFalse(next(e for e in layer_entries(self.stage, self.edits)
                                      if e["identifier"] == self.sub.identifier)["editable"])
                with self.assertRaises(ValueError):
                    self.edits.set_edit_target(self.sub.identifier)
                self.assertTrue(layer_text(self.stage, self.sub.identifier).startswith("#usda"))
            finally:
                self.sub.SetPermissionToEdit(True)
            with self.assertRaises(ValueError):
                layer_text(self.stage, "missing.usda")
            self.assertEqual(asset_path.read_bytes(), original)

    def test_edit_target_contents_are_authored_not_flattened_and_not_saved_to_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root_path = Path(directory) / "root.usda"
            self.root.Export(str(root_path))
            stage = Usd.Stage.Open(str(root_path))
            edits = StageEdits(stage)
            root = stage.GetRootLayer()
            before = root_path.read_bytes()
            self.assertEqual(edits.layer, root)
            edits.add_prim("/", "RootPrim", "Cube")
            edits.set_edit_target(stage.GetSessionLayer().identifier)
            edits.add_prim("/", "SessionPrim", "Sphere")
            text = layer_text(stage, root.identifier)
            self.assertIn('"RootPrim"', text)
            self.assertNotIn('"SessionPrim"', text)
            self.assertEqual(root_path.read_bytes(), before)
            edits.set_edit_target(root.identifier)
            original = root.ExportToString()
            def fail():
                stage.DefinePrim("/Failed")
                raise ValueError("Cannot finish")
            with self.assertRaisesRegex(ValueError, "Cannot finish"):
                edits.change("Fail", fail)
            self.assertEqual(root.ExportToString(), original)
            self.assertTrue(stage.GetSessionLayer().GetPrimAtPath("/SessionPrim"))


if __name__ == "__main__":
    unittest.main()
