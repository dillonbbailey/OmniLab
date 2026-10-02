"""Run with the native USD runtime; publishing never edits the source stage."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

from omnilab.usd.usd_asset_publish import publish_asset


class AssetPublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.stage = Usd.Stage.CreateNew(str(self.folder / "source.usda"))
        UsdGeom.SetStageMetersPerUnit(self.stage, 1)
        UsdGeom.SetStageUpAxis(self.stage, "Z")
        self.world = UsdGeom.Xform.Define(self.stage, "/World")
        self.world.AddTranslateOp().Set((10, 20, 30))
        self.root = UsdGeom.Xform.Define(self.stage, "/World/Group/Chair")
        self.root.AddTranslateOp().Set((2, 3, 4))
        self.cube = UsdGeom.Cube.Define(self.stage, "/World/Group/Chair/Seat")
        self.cube.AddTranslateOp().Set((0, 0, 2))
        self.material = UsdShade.Material.Define(self.stage, "/Looks/Wood")
        self.shader = UsdShade.Shader.Define(self.stage, "/Looks/Wood/Surface")
        self.shader.CreateIdAttr("UsdPreviewSurface")
        self.shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        self.material.CreateSurfaceOutput().ConnectToSource(self.shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(self.world.GetPrim()).Bind(self.material)

    def tearDown(self):
        self.stage = None
        self.temporary.cleanup()

    def publish(self, path="/World/Group/Chair", name="ChairAsset", **kwargs):
        before = {layer.identifier: layer.ExportToString() for layer in self.stage.GetUsedLayers()}
        rules = self.stage.GetLoadRules().GetRules()
        result = publish_asset(self.stage, path, self.folder, name, **kwargs)
        self.assertEqual(before, {layer.identifier: layer.ExportToString() for layer in self.stage.GetUsedLayers()})
        self.assertEqual(rules, self.stage.GetLoadRules().GetRules())
        return Usd.Stage.Open(result["path"]), result

    def test_nested_prim_portable_structure_bindings_and_unloaded_interface(self):
        out, result = self.publish()
        target = self.folder / "ChairAsset"
        self.assertEqual(out.GetDefaultPrim().GetPath(), Sdf.Path("/ChairAsset"))
        self.assertEqual(Usd.ModelAPI(out.GetDefaultPrim()).GetKind(), "component")
        self.assertEqual(UsdGeom.GetStageMetersPerUnit(out), 1)
        self.assertEqual(UsdGeom.GetStageUpAxis(out), "Z")
        self.assertFalse(out.GetPrimAtPath("/World"))
        mesh = out.GetPrimAtPath("/ChairAsset/Geometry/Chair/Seat")
        material, _ = UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()
        self.assertEqual(str(material.GetPath()), "/ChairAsset/Materials/Wood")
        self.assertEqual(UsdGeom.XformCache().GetLocalToWorldTransform(mesh).ExtractTranslation(), Gf.Vec3d(0, 0, 2))
        self.assertEqual((target / "payload/geometry.usdc").read_bytes()[:8], b"PXR-USDC")
        geometry = Sdf.Layer.FindOrOpen(str(target / "payload/geometry.usdc"))
        self.assertNotIn("material:binding", geometry.ExportToString())
        self.assertNotIn("Shader", geometry.ExportToString())
        bindings = Sdf.Layer.FindOrOpen(str(target / "payload/bindings.usda"))
        self.assertIn("material:binding", bindings.ExportToString())
        self.assertNotIn("xformOp", bindings.ExportToString())
        out.Unload()
        root = out.GetDefaultPrim()
        self.assertTrue(root and not root.IsLoaded())
        self.assertEqual(list(UsdGeom.ModelAPI(root).GetExtentsHint()), [Gf.Vec3f(-1, -1, 1), Gf.Vec3f(1, 1, 3)])
        self.assertEqual(list(root.GetChildren()), [])
        # Reference and relocate the publication independently from the source.
        moved = self.folder / "moved"
        shutil.move(target, moved)
        assembly = Usd.Stage.CreateInMemory()
        instance = UsdGeom.Xform.Define(assembly, "/Scene/Chair").GetPrim()
        instance.GetReferences().AddReference(str(moved / "ChairAsset.usda"))
        self.assertTrue(assembly.GetPrimAtPath("/Scene/Chair/Geometry/Chair/Seat"))
        bound, _ = UsdShade.MaterialBindingAPI(assembly.GetPrimAtPath("/Scene/Chair/Geometry/Chair/Seat")).ComputeBoundMaterial()
        self.assertEqual(str(bound.GetPath()), "/Scene/Chair/Materials/Wood")

    def test_world_placement_inherited_primvars_and_animation(self):
        self.stage.SetStartTimeCode(1)
        self.stage.SetEndTimeCode(2)
        translation = self.world.GetOrderedXformOps()[0]
        translation.Set((10, 20, 30), 1)
        translation.Set((20, 20, 30), 2)
        color = UsdGeom.PrimvarsAPI(self.world).CreatePrimvar("tint", Sdf.ValueTypeNames.Color3f, "constant")
        color.Set((.2, .3, .4))
        local, _ = self.publish(frame=1)
        world, _ = self.publish(name="WorldAsset", placement="world", frame=1)
        for stage, path, x in ((local, "/ChairAsset/Geometry/Chair/Seat", 10),
                               (world, "/WorldAsset/Geometry/Chair/Seat", 22)):
            prim = stage.GetPrimAtPath(path)
            self.assertEqual(UsdGeom.XformCache(2).GetLocalToWorldTransform(prim).ExtractTranslation()[0], x)
            self.assertEqual(UsdGeom.PrimvarsAPI(prim).FindPrimvarWithInheritance("tint").Get(), Gf.Vec3f(.2, .3, .4))
            self.assertEqual(stage.GetEndTimeCode(), 2)

    def test_leaf_geometry_and_instance_proxy(self):
        leaf, _ = self.publish(path="/World/Group/Chair/Seat", name="Seat")
        prim = leaf.GetPrimAtPath("/Seat/Geometry/Seat")
        self.assertTrue(prim.IsA(UsdGeom.Cube))
        self.assertEqual(UsdGeom.XformCache().GetLocalToWorldTransform(prim), Gf.Matrix4d(1))
        self.stage.DefinePrim("/Instance").GetReferences().AddInternalReference("/World/Group/Chair")
        self.stage.GetPrimAtPath("/Instance").SetInstanceable(True)
        self.assertTrue(self.stage.GetPrimAtPath("/Instance/Seat").IsInstanceProxy())
        instance, _ = self.publish(path="/Instance/Seat", name="Proxy")
        self.assertTrue(instance.GetPrimAtPath("/Proxy/Geometry/Seat").IsA(UsdGeom.Cube))
        self.assertFalse(instance.GetPrimAtPath("/Proxy/Geometry/Seat").IsInstanceProxy())

    def test_internal_materials_connections_and_name_collisions(self):
        internal = UsdShade.Material.Define(self.stage, "/World/Group/Chair/Looks/Wood")
        shader = UsdShade.Shader.Define(self.stage, str(internal.GetPath()) + "/Surface")
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        internal.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(self.cube.GetPrim()).Bind(internal)
        UsdGeom.Cube.Define(self.stage, "/World/Group/Chair/Other")
        out, _ = self.publish()
        materials = [p for p in out.Traverse() if p.IsA(UsdShade.Material)]
        self.assertEqual(len(materials), 2)
        for material in materials:
            self.assertEqual(material.GetPath().GetParentPath(), Sdf.Path("/ChairAsset/Materials"))
            self.assertTrue(UsdShade.Material(material).GetSurfaceOutput().GetConnectedSource())

    def test_copies_textures_udim_arrays_and_time_samples(self):
        textures = self.folder / "source_textures"
        textures.mkdir()
        for name in ("color.tx", "tile.1001.exr", "tile.1002.exr", "other.tx"):
            (textures / name).write_bytes(name.encode())
        self.shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath("./source_textures/color.tx"))
        self.shader.CreateInput("udim", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath("./source_textures/tile.<UDIM>.exr"))
        self.shader.CreateInput("files", Sdf.ValueTypeNames.AssetArray).Set([Sdf.AssetPath("./source_textures/color.tx"), Sdf.AssetPath("./source_textures/other.tx")])
        animated = self.shader.CreateInput("animated", Sdf.ValueTypeNames.Asset)
        animated.Set(Sdf.AssetPath("./source_textures/color.tx"), 1)
        animated.Set(Sdf.AssetPath("./source_textures/other.tx"), 2)
        out, result = self.publish()
        self.assertEqual(result["dependency_count"], 3)
        root = self.folder / "ChairAsset"
        manifest = json.loads((root / "publish.json").read_text())
        self.assertTrue(all(path.startswith("textures/") for path in manifest["resources"]))
        self.assertEqual(len(list((root / "textures").rglob("*.exr"))), 2)
        shader = UsdShade.Shader(out.GetPrimAtPath("/ChairAsset/Materials/Wood/Surface"))
        self.assertTrue(shader.GetInput("file").Get().resolvedPath)
        self.assertIn("<UDIM>", shader.GetInput("udim").Get().path)
        self.assertEqual(shader.GetInput("animated").GetAttr().GetTimeSamples(), [1, 2])
        out = None
        shutil.rmtree(textures)
        relocated = self.folder / "relocated"
        shutil.move(root, relocated)
        out = Usd.Stage.Open(str(relocated / "ChairAsset.usda"))
        shader = UsdShade.Shader(out.GetPrimAtPath("/ChairAsset/Materials/Wood/Surface"))
        self.assertEqual(Path(shader.GetInput("file").Get().resolvedPath).read_bytes(), b"color.tx")

    def test_missing_dependencies_and_existing_destinations_leave_no_partial_asset(self):
        self.shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath("./missing.tx"))
        with self.assertRaisesRegex(ValueError, "Missing asset file"):
            self.publish()
        self.assertFalse((self.folder / "ChairAsset").exists())
        self.assertFalse(list(self.folder.glob(".*-publish-*")))
        self.shader.GetPrim().RemoveProperty("inputs:file")
        target = self.folder / "ChairAsset"
        target.mkdir()
        (target / "keep.txt").write_text("unchanged")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.publish()
        self.assertEqual((target / "keep.txt").read_text(), "unchanged")
        with self.assertRaisesRegex(ValueError, "active, defined prim"):
            self.publish(path="/", name="Root")

    def test_variants_snapshot_and_unloaded_payload_rejection(self):
        variants = self.root.GetPrim().GetVariantSets().AddVariantSet("shape")
        for name, size in (("large", 4), ("small", 1)):
            variants.AddVariant(name)
            variants.SetVariantSelection(name)
            with variants.GetVariantEditContext():
                UsdGeom.Cube(self.stage.GetPrimAtPath(self.cube.GetPath())).CreateSizeAttr(size)
        variants.SetVariantSelection("large")
        out, _ = self.publish()
        self.assertEqual(UsdGeom.Cube(out.GetPrimAtPath("/ChairAsset/Geometry/Chair/Seat")).GetSizeAttr().Get(), 4)
        payload = Usd.Stage.CreateNew(str(self.folder / "payload.usda"))
        payload.SetDefaultPrim(UsdGeom.Cube.Define(payload, "/Cube").GetPrim())
        payload.GetRootLayer().Save()
        prim = self.stage.DefinePrim("/World/Group/Chair/Payload")
        prim.GetPayloads().AddPayload(str(self.folder / "payload.usda"))
        prim.Unload()
        with self.assertRaisesRegex(ValueError, "Load the payload"):
            self.publish(name="Unloaded")
        self.assertFalse(prim.IsLoaded())

    def test_reset_transform_can_be_placed_as_a_reference(self):
        xform = UsdGeom.Xformable(self.cube)
        xform.SetResetXformStack(True)
        out, result = self.publish(placement="world")
        assembly = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Xform.Define(assembly, "/Placed")
        prim.AddTranslateOp().Set((100, 0, 0))
        prim.GetPrim().GetReferences().AddReference(result["path"])
        cube = assembly.GetPrimAtPath("/Placed/Geometry/Chair/Seat")
        self.assertEqual(UsdGeom.XformCache().GetLocalToWorldTransform(cube).ExtractTranslation(), Gf.Vec3d(100, 0, 2))

    def test_failed_copy_leaves_no_partial_asset(self):
        texture = self.folder / "color.tx"
        texture.write_bytes(b"texture")
        self.shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(texture)))
        with patch("omnilab.usd.usd_asset_publish.shutil.copy2", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.publish()
        self.assertFalse((self.folder / "ChairAsset").exists())
        self.assertFalse(list(self.folder.glob(".*-publish-*")))

    def test_scope_keeps_world_transform_without_changing_its_type(self):
        scope = UsdGeom.Scope.Define(self.stage, "/World/Group/Container")
        UsdGeom.Cube.Define(self.stage, str(scope.GetPath()) + "/Cube")
        out, _ = self.publish(path=str(scope.GetPath()), placement="world")
        scope = out.GetPrimAtPath("/ChairAsset/Geometry/Container/Container")
        self.assertTrue(scope.IsA(UsdGeom.Scope))
        self.assertEqual(UsdGeom.XformCache().GetLocalToWorldTransform(scope).ExtractTranslation(), Gf.Vec3d(10, 20, 30))

    def test_materialx_string_textures_become_assets_and_editor_links_are_removed(self):
        texture = self.folder / "color.tx"
        texture.write_bytes(b"texture")
        self.shader.CreateIdAttr("ND_image_color3")
        self.shader.CreateInput("file", Sdf.ValueTypeNames.String).Set(str(texture))
        self.shader.GetPrim().SetCustomDataByKey("editor:usdTransform", dict(scene="previous.usda", path="/Projector", follow=True))
        self.shader.GetPrim().SetCustomDataByKey("editor:nodeId", "retained-layout-id")
        self.material.GetPrim().SetCustomDataByKey("moonrayEditor:materialSync", "old graph and paths")
        out, _ = self.publish()
        shader = UsdShade.Shader(out.GetPrimAtPath("/ChairAsset/Materials/Wood/Surface"))
        self.assertEqual(shader.GetInput("file").GetTypeName(), Sdf.ValueTypeNames.Asset)
        self.assertTrue(Path(shader.GetInput("file").Get().resolvedPath).is_file())
        self.assertFalse(shader.GetPrim().GetCustomDataByKey("editor:usdTransform"))
        self.assertEqual(shader.GetPrim().GetCustomDataByKey("editor:nodeId"), "retained-layout-id")
        self.assertFalse(out.GetPrimAtPath("/ChairAsset/Materials/Wood").GetCustomDataByKey("moonrayEditor:materialSync"))

    def test_packaged_file_dependency_is_extracted(self):
        archive = self.folder / "textures.usdz"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
            package.writestr("root.usda", "#usda 1.0\n")
            package.writestr("textures/color.png", b"packaged image")
        self.shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(archive) + "[textures/color.png]"))
        out, _ = self.publish()
        value = out.GetPrimAtPath("/ChairAsset/Materials/Wood/Surface").GetAttribute("inputs:file").Get()
        self.assertEqual(Path(value.resolvedPath).read_bytes(), b"packaged image")

    def test_collection_binding_is_resolved_into_direct_assignments(self):
        other = UsdGeom.Cube.Define(self.stage, "/World/Group/Chair/Other")
        collection = Usd.CollectionAPI.Apply(self.world.GetPrim(), "seat")
        collection.CreateIncludesRel().AddTarget(self.cube.GetPath())
        red = UsdShade.Material.Define(self.stage, "/Looks/Red")
        UsdShade.MaterialBindingAPI.Apply(self.world.GetPrim()).Bind(collection, red, "seat")
        out, _ = self.publish()
        for name, expected in (("Seat", "Red"), ("Other", "Wood")):
            material, _ = UsdShade.MaterialBindingAPI(out.GetPrimAtPath("/ChairAsset/Geometry/Chair/" + name)).ComputeBoundMaterial()
            self.assertEqual(material.GetPrim().GetName(), expected)

    def test_external_camera_dependency_and_missing_connection(self):
        camera = UsdGeom.Camera.Define(self.stage, "/World/Projector")
        self.shader.GetPrim().CreateRelationship("projector").AddTarget(camera.GetPath())
        out, _ = self.publish()
        shader = out.GetPrimAtPath("/ChairAsset/Materials/Wood/Surface")
        target = shader.GetRelationship("projector").GetTargets()[0]
        self.assertEqual(target, Sdf.Path("/ChairAsset/Dependencies/Projector"))
        self.assertTrue(out.GetPrimAtPath(target).IsA(UsdGeom.Camera))
        self.shader.CreateInput("missing", Sdf.ValueTypeNames.Float).GetAttr().SetConnections(["/Missing.outputs:value"])
        with self.assertRaisesRegex(ValueError, "Missing prim dependency"):
            self.publish(name="Broken")

    def test_concurrent_destination_is_not_replaced(self):
        from omnilab.usd.usd_asset_publish import Publisher
        original = Publisher.write
        def write(publisher):
            result = original(publisher)
            target = self.folder / "ChairAsset"
            target.mkdir()
            (target / "keep.txt").write_text("other publisher")
            return result
        with patch.object(Publisher, "write", write):
            with self.assertRaises(FileExistsError):
                self.publish()
        self.assertEqual((self.folder / "ChairAsset/keep.txt").read_text(), "other publisher")
        self.assertFalse(list(self.folder.glob(".*-publish-*")))

    def test_section_payloads_cross_links_unloading_and_relocation(self):
        other = UsdGeom.Cube.Define(self.stage, "/World/Group/Chair/Other")
        self.cube.GetPrim().CreateRelationship("proxyPrim").SetTargets([other.GetPath()])
        other.CreatePurposeAttr("proxy")
        a = self.cube.GetPrim().CreateAttribute("user:value", Sdf.ValueTypeNames.Float)
        b = other.GetPrim().CreateAttribute("user:value", Sdf.ValueTypeNames.Float)
        b.Set(3)
        a.SetConnections([b.GetPath()])
        out, result = self.publish(layout="sections")
        root = self.folder / "ChairAsset"
        manifest = json.loads((root / "publish.json").read_text())
        self.assertEqual(len(manifest["sections"]), 2)
        seat = out.GetPrimAtPath("/ChairAsset/Geometry/Chair/Seat")
        self.assertTrue(seat.HasPayload())
        self.assertEqual(seat.GetRelationship("proxyPrim").GetTargets(), [Sdf.Path("/ChairAsset/Geometry/Chair/Other")])
        self.assertEqual(seat.GetAttribute("user:value").GetConnections(), [Sdf.Path("/ChairAsset/Geometry/Chair/Other.user:value")])
        for entry in manifest["sections"]:
            self.assertEqual((root / entry["file"]).read_bytes()[:8], b"PXR-USDC")
        out.Unload(seat.GetPath())
        self.assertFalse(seat.IsLoaded())
        self.assertTrue(out.GetPrimAtPath("/ChairAsset/Geometry/Chair/Other").IsLoaded())
        self.assertTrue(out.GetPrimAtPath("/ChairAsset/Materials/Wood/Surface"))
        moved = self.folder / "moved"
        shutil.move(root, moved)
        assembly = Usd.Stage.CreateInMemory()
        assembly.DefinePrim("/Placed").GetReferences().AddReference(str(moved / "ChairAsset.usda"))
        seat = assembly.GetPrimAtPath("/Placed/Geometry/Chair/Seat")
        self.assertEqual(seat.GetRelationship("proxyPrim").GetTargets(), [Sdf.Path("/Placed/Geometry/Chair/Other")])
        material, _ = UsdShade.MaterialBindingAPI(seat).ComputeBoundMaterial()
        self.assertEqual(str(material.GetPath()), "/Placed/Materials/Wood")
        self.assertFalse(assembly.GetCompositionErrors())

    def test_flatten_copy_is_bounded_and_expands_nested_instances_privately(self):
        from omnilab.usd.usd_asset_publish import Publisher
        self.stage.DefinePrim("/Unrelated").GetReferences().AddInternalReference("/World/Group/Chair")
        instance = self.stage.DefinePrim("/World/Group/Chair/Nested")
        prototype = UsdGeom.Cube.Define(self.stage, "/Template")
        prototype.CreateSizeAttr(3)
        instance.GetReferences().AddInternalReference("/Template")
        instance.SetInstanceable(True)
        before = self.stage.GetRootLayer().ExportToString()
        publisher = Publisher(self.stage, "/World/Group/Chair", "ChairAsset", self.folder,
                              placement="world", frame=0, progress=lambda text: None)
        publisher.gather()
        snapshot = publisher.snapshot()
        self.assertFalse(snapshot.GetPrimAtPath("/Unrelated"))
        self.assertFalse(snapshot.GetPrimAtPath("/Template"))
        self.assertFalse(snapshot.GetPrototypes())
        self.assertEqual(UsdGeom.Cube(snapshot.GetPrimAtPath(instance.GetPath())).GetSizeAttr().Get(), 3)
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), before)
        self.assertTrue(instance.IsInstance())

    def test_snapshot_respects_muted_layers_and_session_overrides(self):
        weak = Sdf.Layer.CreateAnonymous("muted.usda")
        self.stage.GetRootLayer().subLayerPaths.append(weak.identifier)
        with Usd.EditContext(self.stage, weak):
            self.cube.CreateSizeAttr(9)
        self.stage.MuteLayer(weak.identifier)
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            self.root.GetPrim().CreateAttribute("user:version", Sdf.ValueTypeNames.Int).Set(3)
        out, _ = self.publish(layout="sections")
        cube = UsdGeom.Cube(out.GetPrimAtPath("/ChairAsset/Geometry/Chair/Seat"))
        self.assertEqual(cube.GetSizeAttr().Get(), 2)
        self.assertEqual(out.GetPrimAtPath("/ChairAsset/Geometry/Chair").GetAttribute("user:version").Get(), 3)
        self.assertEqual(self.stage.GetMutedLayers(), [weak.identifier])

    def test_geometry_dependencies_also_use_binary_section_payloads(self):
        external = UsdGeom.Cube.Define(self.stage, "/ExternalGeometry")
        self.cube.GetPrim().CreateRelationship("user:geometry").SetTargets([external.GetPath()])
        out, result = self.publish(layout="sections")
        dependency = out.GetPrimAtPath("/ChairAsset/Dependencies/ExternalGeometry")
        self.assertTrue(dependency.HasPayload())
        rel = out.GetPrimAtPath("/ChairAsset/Geometry/Chair/Seat").GetRelationship("user:geometry")
        self.assertEqual(rel.GetTargets(), [dependency.GetPath()])
        self.assertEqual(UsdGeom.Cube(dependency).GetSizeAttr().Get(), 2)


if __name__ == "__main__":
    unittest.main()
