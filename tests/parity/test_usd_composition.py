"""Native USD composition authoring, validation and payload loading."""
from pathlib import Path
import tempfile
import unittest

from pxr import Sdf, Usd, UsdGeom

from omnilab.usd.usd_composition import set_payload_load, sublayer_entries
from omnilab.usd.usd_editing import StageEdits


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.asset_path = self.directory / "asset.usda"
        self.asset = Usd.Stage.CreateNew(str(self.asset_path))
        prim = UsdGeom.Xform.Define(self.asset, "/Asset").GetPrim()
        UsdGeom.Cube.Define(self.asset, "/Asset/Cube")
        self.asset.SetDefaultPrim(prim)
        self.asset.GetRootLayer().Save()
        self.original = self.asset_path.read_bytes()
        self.stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(self.stage, "/Model")
        self.edits = StageEdits(self.stage)

    def change_sublayers(self, layer, entries, **extra):
        self.edits.set_sublayers(dict(identifier=layer.identifier, expected=sublayer_entries(layer),
                                     sublayers=entries, **extra))

    def test_sublayers_add_remove_offsets_undo_and_target_fallback(self):
        root = self.stage.GetRootLayer()
        sub = Sdf.Layer.CreateAnonymous("animation.usda")
        root.subLayerPaths.append(sub.identifier)
        root.subLayerOffsets[0] = Sdf.LayerOffset(10, 2)
        self.edits = StageEdits(self.stage)
        self.edits.set_edit_target(sub.identifier)
        before = root.ExportToString()
        entries = sublayer_entries(root) + [dict(path=str(self.asset_path), offset=0, scale=1)]
        self.change_sublayers(root, entries)
        self.assertEqual(list(root.subLayerPaths), [sub.identifier, str(self.asset_path)])
        self.assertEqual(root.subLayerOffsets[0], Sdf.LayerOffset(10, 2))
        self.assertTrue(self.stage.GetPrimAtPath("/Asset/Cube"))
        self.assertEqual(self.edits.layer, sub)
        self.change_sublayers(root, entries[1:])
        self.assertEqual(self.edits.layer, root)
        self.edits.restore()
        self.assertEqual(root.subLayerOffsets[0], Sdf.LayerOffset(10, 2))
        self.edits.restore()
        self.assertEqual(root.ExportToString(), before)
        self.assertFalse(self.stage.GetPrimAtPath("/Asset"))
        self.assertFalse(self.edits.state()["dirty"])
        self.edits.restore(redo=True)
        self.assertTrue(self.stage.GetPrimAtPath("/Asset/Cube"))
        self.assertEqual(self.asset_path.read_bytes(), self.original)

    def test_invalid_sublayers_are_atomic_and_stale_lists_rejected(self):
        root = self.stage.GetRootLayer()
        cyclic = Sdf.Layer.CreateAnonymous("cycle.usda")
        cyclic.subLayerPaths = [root.identifier]
        before = root.ExportToString()
        for path in (root.identifier, cyclic.identifier, str(self.directory / "missing.usda")):
            with self.assertRaises(Exception):
                self.change_sublayers(root, [dict(path=path, offset=0, scale=1)])
            self.assertEqual(root.ExportToString(), before)
            self.assertFalse(self.edits.undo)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.edits.set_sublayers(dict(identifier=root.identifier, expected=[dict(path="old")], sublayers=[]))
        self.assertEqual(root.ExportToString(), before)
        # An unresolved existing path can still be removed.
        root.subLayerPaths = [str(self.directory / "missing.usda")]
        self.change_sublayers(root, [])
        self.assertEqual(list(root.subLayerPaths), [])

    def test_reference_and_payload_author_in_target_and_undo(self):
        for kind in ("reference", "payload"):
            with self.subTest(kind=kind):
                self.edits.set_edit_target(self.stage.GetRootLayer().identifier)
                self.edits.add_arc(dict(path="/Model", kind=kind, asset=str(self.asset_path), prim_path=""))
                self.assertTrue(self.stage.GetPrimAtPath("/Model/Cube"))
                self.assertIn("prepend " + ("references" if kind == "reference" else "payload"), self.edits.layer.ExportToString())
                self.assertNotIn(str(self.asset_path), self.stage.GetSessionLayer().ExportToString())
                self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
                self.edits.restore()
                self.assertFalse(self.stage.GetPrimAtPath("/Model/Cube"))
                self.edits.restore(redo=True)
                self.assertTrue(self.stage.GetPrimAtPath("/Model/Cube"))
                self.edits.restore()
        self.assertEqual(self.asset_path.read_bytes(), self.original)

    def test_payload_load_unload_is_view_state_and_recursive(self):
        self.stage.DefinePrim("/Model/Nested", "Xform")
        self.edits.add_arc(dict(path="/Model/Nested", kind="payload", asset=str(self.asset_path)))
        content = self.edits.layer.ExportToString()
        history = len(self.edits.undo)
        set_payload_load(self.stage, "/Model", False)
        self.assertTrue(self.stage.GetPrimAtPath("/Model/Nested").HasPayload())
        self.assertFalse(self.stage.GetPrimAtPath("/Model/Nested").IsLoaded())
        self.assertFalse(self.stage.GetPrimAtPath("/Model/Nested/Cube"))
        set_payload_load(self.stage, "/", True)
        self.assertTrue(self.stage.GetPrimAtPath("/Model/Nested/Cube"))
        self.assertEqual(self.edits.layer.ExportToString(), content)
        self.assertEqual(len(self.edits.undo), history)

    def test_asset_default_explicit_prim_and_invalid_arc_validation(self):
        self.asset.ClearDefaultPrim()
        before = self.edits.layer.ExportToString()
        for path, source in (("/", "/Asset"), ("/missing", "/Asset"), ("/Model", ""),
                             ("/Model", "/missing"), ("/Model", "/Asset.property")):
            with self.assertRaises(ValueError):
                self.edits.add_arc(dict(path=path, kind="reference", asset=str(self.asset_path), prim_path=source))
            self.assertEqual(self.edits.layer.ExportToString(), before)
        self.edits.add_arc(dict(path="/Model", kind="reference", asset=str(self.asset_path), prim_path="/Asset"))
        self.assertTrue(self.stage.GetPrimAtPath("/Model/Cube"))
        self.assertEqual(self.asset_path.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
