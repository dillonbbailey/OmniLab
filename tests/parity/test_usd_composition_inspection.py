"""Inspect real composed USD opinions without changing or flattening the stage."""
from pathlib import Path
import tempfile
import unittest

from pxr import Sdf, Usd, UsdGeom

from omnilab.usd.usd_composition_inspection import inspect_composition


class CompositionInspectionTests(unittest.TestCase):
    def setUp(self):
        self.asset = Usd.Stage.CreateInMemory("asset.usda")
        self.sphere = UsdGeom.Sphere.Define(self.asset, "/Asset/Shape")
        self.sphere.GetRadiusAttr().Set(3)
        self.stage = Usd.Stage.CreateInMemory("scene.usda")
        model = self.stage.DefinePrim("/World/Model", "Xform")
        model.GetReferences().AddReference(self.asset.GetRootLayer().identifier, "/Asset")
        self.path = "/World/Model/Shape"
        self.prim = self.stage.GetPrimAtPath(self.path)

    def inspect(self, mode, **kwargs):
        return inspect_composition(self.stage, kwargs.pop("path", self.path), mode,
                                   Usd.TimeCode(kwargs.pop("frame", 1)), **kwargs)

    def test_specs_layers_and_ancestral_reference_are_read_only(self):
        weak = Sdf.Layer.CreateAnonymous("weak.usda")
        self.asset.GetRootLayer().subLayerPaths.append(weak.identifier)
        with Usd.EditContext(self.asset, weak):
            self.sphere.GetRadiusAttr().Set(5)
        self.stage.GetPrimAtPath(self.path).SetMetadata("documentation", "Local note")
        before = {l.identifier: l.ExportToString() for l in self.stage.GetUsedLayers()}
        target = self.stage.GetEditTarget()
        specs = self.inspect("specs")
        self.assertEqual([r["cells"][2] for r in specs["rows"]], ["over", "def", "over"])
        self.assertEqual(specs["rows"][0]["cells"][3], self.path)
        self.assertEqual(specs["rows"][1]["cells"][3], "/Asset/Shape")
        layers = self.inspect("layers")
        self.assertTrue(any("weak.usda" in r["cells"][2] for r in layers["rows"]))
        self.assertTrue(any("Reference" in r["cells"][0] for r in layers["rows"]))
        arcs = self.inspect("arcs")
        reference = next(r for r in arcs["rows"] if r["cells"][1] == "Reference")
        self.assertIn("Ancestral: Yes", reference["details"])
        self.assertIn("Introduced at: /World/Model", reference["details"])
        self.assertEqual(before, {l.identifier: l.ExportToString() for l in self.stage.GetUsedLayers()})
        self.assertEqual(self.stage.GetEditTarget(), target)

    def test_value_resolution_skips_metadata_only_and_tracks_overrides_and_blocks(self):
        attr = self.prim.GetAttribute("radius")
        attr.SetMetadata("documentation", "Metadata-only stronger opinion")
        report = self.inspect("values", name="radius")
        self.assertEqual([r["winner"] for r in report["rows"]], [False, True])
        self.assertIn("3.0", report["resolved"])
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            attr.Set(11)
        report = self.inspect("values", name="radius")
        self.assertTrue(report["rows"][0]["winner"])
        self.assertIn("11.0", report["resolved"])
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            attr.Block()
        report = self.inspect("values", name="radius")
        self.assertIn("Blocked", report["summary"])
        # A block removes authored values but can still resolve a schema fallback.
        self.assertIn("Schema fallback", report["summary"])
        self.assertEqual(report["resolved"], "Resolved value:\n1.0")
        self.assertTrue(report["rows"][0]["winner"])
        fallback = self.inspect("values", name="orientation")
        self.assertIn("Schema fallback", fallback["summary"])
        self.assertFalse(fallback["rows"])

    def test_samples_and_cumulative_offsets_in_references_and_stage_layers(self):
        self.sphere.GetRadiusAttr().Set(2, 1)
        self.sphere.GetRadiusAttr().Set(6, 3)
        self.stage.GetPrimAtPath("/World/Model").GetReferences().SetReferences([
            Sdf.Reference(self.asset.GetRootLayer().identifier, "/Asset", Sdf.LayerOffset(10, 2))])
        report = self.inspect("values", name="radius", frame=14)
        self.assertIn("Time samples", report["summary"])
        self.assertEqual(report["resolved"], "Resolved value:\n4.0")
        self.assertIn("1: 2.0", report["rows"][0]["cells"][3])
        self.assertIn("3: 6.0", report["rows"][0]["cells"][3])
        self.assertIn("Current layer time: 2", report["rows"][0]["details"])
        weak = Sdf.Layer.CreateAnonymous("offset.usda")
        self.stage.GetRootLayer().subLayerPaths.append(weak.identifier)
        self.stage.GetRootLayer().subLayerOffsets[0] = Sdf.LayerOffset(5, 3)
        report = self.inspect("layers", path="/")
        self.assertIn("Offset 5, scale 3", report["rows"][-1]["cells"])

    def test_inherit_specialize_variant_payload_and_relationship_targets(self):
        cls = self.stage.CreateClassPrim("/_class_Shared")
        cls.CreateAttribute("user:setting", Sdf.ValueTypeNames.Float).Set(2)
        self.prim.GetInherits().AddInherit(cls.GetPath())
        base = self.stage.CreateClassPrim("/_class_Base")
        self.prim.GetSpecializes().AddSpecialize(base.GetPath())
        variants = self.prim.GetVariantSets().AddVariantSet("look")
        variants.AddVariant("red")
        variants.SetVariantSelection("red")
        with variants.GetVariantEditContext():
            self.prim.GetAttribute("radius").Set(8)
        self.prim.GetPayloads().AddPayload(self.asset.GetRootLayer().identifier, "/Asset/Shape")
        kinds = {r["cells"][1] for r in self.inspect("arcs")["rows"]}
        self.assertTrue({"Inherit", "Specialize", "Variant", "Reference", "Payload"} <= kinds)
        rel = self.prim.CreateRelationship("user:targets")
        rel.SetTargets(["/World/Model"])
        report = self.inspect("values", name="user:targets", group="Relationships")
        self.assertIn("/World/Model", report["resolved"])
        self.assertFalse(any(r["winner"] for r in report["rows"]))
        self.stage.Unload(self.path)
        loaded = self.stage.GetLoadSet()
        for mode in ("specs", "layers", "arcs"):
            self.inspect(mode)
        self.assertEqual(self.stage.GetLoadSet(), loaded)

    def test_value_clips_are_identified_without_false_ordinary_layer_winner(self):
        with tempfile.TemporaryDirectory() as folder:
            clip = Usd.Stage.CreateNew(str(Path(folder) / "clip.usda"))
            sphere = UsdGeom.Sphere.Define(clip, "/Clip")
            sphere.GetRadiusAttr().Set(4, 1)
            sphere.GetRadiusAttr().Set(8, 2)
            clip.GetRootLayer().Save()
            stage = Usd.Stage.CreateInMemory()
            prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
            clips = Usd.ClipsAPI(prim)
            clips.SetClipAssetPaths([Sdf.AssetPath(clip.GetRootLayer().identifier)])
            clips.SetClipPrimPath("/Clip")
            clips.SetClipActive([(1, 0)])
            clips.SetClipTimes([(1, 1), (2, 2)])
            report = inspect_composition(stage, "/Sphere", "values", Usd.TimeCode(1.5), name="radius")
            self.assertIn("Value clips", report["summary"])
            self.assertIn("6.0", report["resolved"])
            self.assertFalse(any(r["winner"] for r in report["rows"]))

    def test_saved_project_layer_names_retain_disk_sources(self):
        source = {self.asset.GetRootLayer().identifier: "/assets/hero.usda"}
        report = self.inspect("specs", sources=source)
        self.assertEqual(report["rows"][0]["cells"][1], "hero.usda")
        self.assertIn("Source file: /assets/hero.usda", report["rows"][0]["details"])
        with self.assertRaises(ValueError):
            self.inspect("specs", path="/Missing")

    def test_hierarchy_tracks_nested_arcs_sublayers_and_spec_owners(self):
        nested = Usd.Stage.CreateInMemory("nested.usda")
        UsdGeom.Sphere.Define(nested, "/Nested/Shape").GetRadiusAttr().Set(7)
        self.asset.GetPrimAtPath("/Asset").GetReferences().AddReference(nested.GetRootLayer().identifier, "/Nested")
        sub = Sdf.Layer.CreateAnonymous("sub.usda")
        deep = Sdf.Layer.CreateAnonymous("deep.usda")
        self.asset.GetRootLayer().subLayerPaths.append(sub.identifier)
        sub.subLayerPaths.append(deep.identifier)
        self.asset.GetRootLayer().subLayerOffsets[0] = Sdf.LayerOffset(5, 2)
        sub.subLayerOffsets[0] = Sdf.LayerOffset(3, 4)
        with Usd.EditContext(self.asset, deep):
            self.sphere.GetRadiusAttr().Set(9)
        arcs = self.inspect("arcs")["rows"]
        references = [r for r in arcs if r["cells"][1] == "Reference"]
        self.assertEqual(len(references), 2)
        self.assertEqual(references[1]["parent"], references[0]["id"])
        layers = self.inspect("layers")
        sub_row = next(r for r in layers["rows"] if r["cells"][2] == "anon:sub.usda")
        deep_row = next(r for r in layers["rows"] if r["cells"][2] == "anon:deep.usda")
        self.assertEqual(deep_row["parent"], sub_row["id"])
        self.assertEqual(deep_row["cells"][3], "Offset 11, scale 8")
        for mode in ("specs", "values"):
            report = self.inspect(mode, name="radius")
            groups = {g["id"]: g for g in report["groups"]}
            for row in report["rows"]:
                self.assertIn(row["parent"], groups)
                self.assertIn("Containing prim spec:", groups[row["parent"]]["details"])
        self.stage.MuteLayer(sub.identifier)
        report = self.inspect("layers")
        self.assertFalse(any(r["cells"][2] in ("anon:sub.usda", "anon:deep.usda") for r in report["rows"]))

    def test_class_instance_proxy_prototype_inactive_and_stage_root(self):
        self.stage.CreateClassPrim("/_class_Shared")
        self.stage.GetPrimAtPath("/World/Model").SetInstanceable(True)
        prototype = self.stage.GetPrimAtPath("/World/Model").GetPrototype()
        for path in ("/", "/_class_Shared", self.path, str(prototype.GetPath())):
            for mode in ("specs", "layers", "arcs"):
                with self.subTest(path=path, mode=mode):
                    self.inspect(mode, path=path)
        self.stage.GetPrimAtPath("/World/Model").SetActive(False)
        for mode in ("specs", "layers", "arcs"):
            self.inspect(mode, path="/World/Model")


if __name__ == "__main__":
    unittest.main()
