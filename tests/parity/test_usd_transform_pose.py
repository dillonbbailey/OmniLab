"""Renderer-runtime tests for local/world editing and matrix preservation."""
import unittest

from pxr import Gf, Usd, UsdGeom

from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_transform_pose import MATRIX_NAME, manipulated_world, pose_info, rows, write_local_matrix
from omnilab.usd.usd_transforms import quaternion_from_euler


class PoseTests(unittest.TestCase):
    def setUp(self):
        self.stage = Usd.Stage.CreateInMemory()
        self.parent = UsdGeom.Xform.Define(self.stage, "/Parent")
        self.parent.AddTranslateOp().Set((10, -2, 3))
        self.parent.AddRotateZOp().Set(90)
        self.prim = UsdGeom.Cube.Define(self.stage, "/Parent/Cube").GetPrim()
        self.xform = UsdGeom.Xformable(self.prim)
        self.edits = StageEdits(self.stage)

    def apply(self, values, space="local", representation="trs", **kwargs):
        self.edits.set_transform(dict(path=str(self.prim.GetPath()), values=values,
                                     space=space, representation=representation, **kwargs))

    def world(self, time=Usd.TimeCode.Default()):
        return self.xform.ComputeLocalToWorldTransform(time)

    def test_local_and_world_translation_under_rotated_parent(self):
        self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
        source = self.stage.GetRootLayer().ExportToString()
        self.apply(dict(translate=[2, 0, 0]))
        self.assertTrue(Gf.IsClose(self.world().ExtractTranslation(), Gf.Vec3d(10, 0, 3), 1e-6))
        local = pose_info(self.prim, 0, space="local")
        self.assertEqual(local["values"]["translate"], [2, 0, 0])
        self.assertTrue(Gf.IsClose(Gf.Vec3d(*pose_info(self.prim, 0)["values"]["translate"]), Gf.Vec3d(10, 0, 3), 1e-6))
        before = self.world()
        self.apply(dict(translate=[5, 6, 7]), space="world")
        self.assertTrue(Gf.IsClose(self.world().ExtractTranslation(), Gf.Vec3d(5, 6, 7), 1e-6))
        self.assertEqual(str(self.prim.GetAttribute("xformOp:translate").GetTypeName()), "float3")
        self.edits.restore()
        self.assertTrue(Gf.IsClose(self.world(), before, 1e-6))
        self.edits.restore(redo=True)
        self.assertTrue(Gf.IsClose(self.world().ExtractTranslation(), Gf.Vec3d(5, 6, 7), 1e-6))
        self.assertEqual(source, self.stage.GetRootLayer().ExportToString())

    def test_matrix_roundtrip_preserves_imported_ops_shear_and_parent(self):
        self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            op = self.xform.AddRotateYOp()
            op.Set(20, 1)
            op.Set(70, 48)
            self.parent.AddScaleOp().Set((2, 3, 4))
        source = self.stage.GetRootLayer().ExportToString()
        before = {t: self.world(t) for t in (1, 48)}
        target = Gf.Matrix4d(1)
        target[0] = Gf.Vec4d(1, .25, .5, 0)
        target.SetTranslateOnly((3.123456789012345, 4, 5))
        self.apply(dict(matrix=rows(target)), "world", "matrix", time="frame", frame=24)
        self.assertTrue(Gf.IsClose(self.world(24), target, 1e-12))
        for t in (1, 48):
            self.assertTrue(Gf.IsClose(self.world(t), before[t], 1e-12))
        info = pose_info(self.prim, 24, space="world", representation="matrix")
        self.assertTrue(info["has_shear"] and info["matrix_authored"])
        self.assertEqual(info["channels"]["matrix"]["samples"], 3)
        self.assertEqual(str(self.prim.GetAttribute(MATRIX_NAME).GetTypeName()), "matrix4d")
        self.assertEqual(op.GetTimeSamples(), [1, 48])
        self.assertEqual(source, self.stage.GetRootLayer().ExportToString())
        exported = Usd.Stage.Open(self.stage.Flatten())
        self.assertTrue(Gf.IsClose(UsdGeom.Xformable(exported.GetPrimAtPath(self.prim.GetPath())).ComputeLocalToWorldTransform(24), target, 1e-12))
        self.edits.restore()
        self.assertFalse(self.prim.GetAttribute(MATRIX_NAME))
        self.edits.restore(redo=True)
        self.assertTrue(Gf.IsClose(self.world(24), target, 1e-12))

    def test_reset_stack_and_matrix_sample_maps(self):
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            self.xform.SetResetXformStack(True)
        self.apply(dict(matrix=rows(Gf.Matrix4d().SetTranslate((2, 3, 4)))), "world", "matrix")
        self.assertTrue(self.xform.GetResetXformStack())
        self.assertTrue(Gf.IsClose(self.world().ExtractTranslation(), Gf.Vec3d(2, 3, 4), 1e-12))
        for frame in (1, 10, 20):
            self.apply(dict(translate=[frame, 0, 0]), time="frame", frame=frame)
        attr = self.prim.GetAttribute(MATRIX_NAME)
        self.assertEqual(attr.GetTimeSamples(), [1, 10, 20])
        self.assertTrue(Gf.IsClose(self.world(10).ExtractTranslation(), Gf.Vec3d(10, 0, 0), 1e-12))

    def test_gesture_spaces_and_pivot_for_all_three_tools(self):
        world = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), 90))
        world.SetTranslateOnly((10, 20, 30))
        a = manipulated_world(world, "translate", 0, 2, "world")
        b = manipulated_world(world, "translate", 0, 2, "local")
        self.assertTrue(Gf.IsClose(a.ExtractTranslation(), Gf.Vec3d(12, 20, 30), 1e-12))
        self.assertTrue(Gf.IsClose(b.ExtractTranslation(), Gf.Vec3d(10, 22, 30), 1e-12))
        for tool, amount in (("orient", 45), ("scale", 2)):
            a = manipulated_world(world, tool, 0, amount, "world")
            b = manipulated_world(world, tool, 0, amount, "local")
            self.assertFalse(Gf.IsClose(a, b, 1e-6))
            self.assertTrue(Gf.IsClose(a.ExtractTranslation(), world.ExtractTranslation(), 1e-12))
            self.assertTrue(Gf.IsClose(b.ExtractTranslation(), world.ExtractTranslation(), 1e-12))
        self.assertAlmostEqual(manipulated_world(world, "scale", 0, 2, "local").TransformDir(Gf.Vec3d(1, 0, 0)).GetLength(), 2)

    def test_invalid_matrix_and_singular_parent_roll_back(self):
        before = self.edits.layer.ExportToString()
        invalid = [[], [[0]*4]*3, [[float("nan")]*4]*4,
                   [[1, 0, 0, .1], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]]
        for matrix in invalid:
            with self.assertRaises(ValueError):
                self.apply(dict(matrix=matrix), representation="matrix")
            self.assertEqual(before, self.edits.layer.ExportToString())
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            self.parent.AddScaleOp().Set((0, 1, 1))
        before = self.edits.layer.ExportToString()
        with self.assertRaisesRegex(ValueError, "parent transform.*singular"):
            self.apply(dict(translate=[1, 2, 3]), "world")
        self.assertEqual(before, self.edits.layer.ExportToString())

    def test_querying_spaces_and_modes_does_not_author(self):
        before = self.edits.layer.ExportToString()
        for space in ("world", "local"):
            for representation in ("trs", "euler", "matrix"):
                info = pose_info(self.prim, 1, space=space, representation=representation)
                self.assertTrue(info["editable"])
        self.assertEqual(before, self.edits.layer.ExportToString())

    def test_euler_rotation_is_typed_and_retains_authored_turns(self):
        self.apply(dict(translate=[1, 2, 3], rotateXYZ=[450, 30, -20], scale=[2, 3, 4]), representation="euler")
        rotation = self.prim.GetAttribute("xformOp:rotateXYZ")
        self.assertEqual(str(rotation.GetTypeName()), "float3")
        self.assertEqual(tuple(rotation.Get()), (450., 30., -20.))
        info = pose_info(self.prim, 0, space="local", representation="euler")
        self.assertFalse(info["adjustment"])
        self.assertEqual(info["values"]["rotateXYZ"], [450., 30., -20.])
        self.assertEqual(info["channels"]["rotateXYZ"]["name"], "xformOp:rotateXYZ")
        before = self.xform.GetLocalTransformation()
        self.apply(dict(orient=info["values"]["orient"]))
        self.assertEqual([str(op.GetOpName()) for op in self.xform.GetOrderedXformOps()],
                         ["xformOp:translate", "xformOp:orient", "xformOp:scale"])
        self.assertTrue(Gf.IsClose(self.xform.GetLocalTransformation(), before, 1e-6))
        self.edits.restore()
        self.assertEqual(tuple(rotation.Get()), (450., 30., -20.))
        self.assertTrue(Gf.IsClose(self.xform.GetLocalTransformation(), before, 1e-6))

    def test_euler_conversion_preserves_quaternion_key_poses_and_source(self):
        self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            rotation = self.xform.AddOrientOp(UsdGeom.XformOp.PrecisionDouble)
            for time, angles in ((Usd.TimeCode.Default(), [10, 20, 30]), (1, [0, 0, 170]), (48, [0, 0, 190])):
                q = quaternion_from_euler(angles)
                rotation.Set(Gf.Quatd(q[0], Gf.Vec3d(*q[1:])), time)
        source = self.stage.GetRootLayer().ExportToString()
        before = {t: self.world(t) for t in (1, 48)}
        self.apply(dict(rotateXYZ=[5, 15, 180]), representation="euler", frame=24, time="frame")
        euler = self.prim.GetAttribute("xformOp:rotateXYZ")
        self.assertEqual(str(euler.GetTypeName()), "double3")
        self.assertEqual(euler.GetTimeSamples(), [1., 24., 48.])
        self.assertLess(abs(euler.Get(48)[2] - euler.Get(1)[2]), 30)
        for t in before:
            self.assertTrue(Gf.IsClose(self.world(t), before[t], 1e-6))
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), source)
        # Switching back replaces inactive samples instead of reviving an older curve.
        self.apply(dict(orient=quaternion_from_euler([5, 15, 180])), frame=24, time="frame")
        self.assertEqual(rotation.GetTimeSamples(), [1., 24., 48.])
        for t in before:
            self.assertTrue(Gf.IsClose(self.world(t), before[t], 1e-6))
        exported = Usd.Stage.Open(self.stage.Flatten())
        self.assertTrue(Gf.IsClose(UsdGeom.Xformable(exported.GetPrimAtPath(self.prim.GetPath())).GetLocalTransformation(24), self.xform.GetLocalTransformation(24), 1e-6))

    def test_world_euler_and_gizmo_preserve_euler_operation(self):
        self.apply(dict(rotateXYZ=[20, 30, 40]), space="world", representation="euler")
        expected = Gf.Transform()
        q = quaternion_from_euler([20, 30, 40])
        expected.SetRotation(Gf.Rotation(Gf.Quatd(q[0], Gf.Vec3d(*q[1:]))))
        self.assertTrue(Gf.IsClose(self.world().ExtractRotationMatrix(), expected.GetMatrix().ExtractRotationMatrix(), 1e-6))
        target = manipulated_world(self.world(), "orient", 1, 25, "local")
        local = target * self.xform.ComputeParentToWorldTransform(Usd.TimeCode.Default()).GetInverse()
        write_local_matrix(self.prim, local, 0, "default", "euler")
        self.assertTrue(Gf.IsClose(self.world(), target, 1e-6))
        self.assertEqual([op.GetOpType() for op in self.xform.GetOrderedXformOps() if op.GetOpType() in
                          (UsdGeom.XformOp.TypeOrient, UsdGeom.XformOp.TypeRotateXYZ)], [UsdGeom.XformOp.TypeRotateXYZ])

    def test_mirrored_scale_keeps_pose_when_keying_and_rotating(self):
        self.apply(dict(orient=quaternion_from_euler([20, 30, 40]), scale=[-1, 2, 3]))
        before = self.world()
        info = pose_info(self.prim, 0, space="local", representation="euler")
        self.assertEqual(info["values"]["scale"], [-1, 2, 3])
        self.apply(dict(rotateXYZ=info["values"]["rotateXYZ"]), representation="euler")
        self.assertTrue(Gf.IsClose(self.world(), before, 1e-6))
        target = manipulated_world(before, "orient", 2, 15, "world")
        local = target * self.xform.ComputeParentToWorldTransform(Usd.TimeCode.Default()).GetInverse()
        write_local_matrix(self.prim, local, 0, "default", "euler")
        self.assertTrue(Gf.IsClose(self.world(), target, 1e-6))

    def test_matrix_key_preserves_parent_animation_at_existing_keys(self):
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            parent_translate = self.parent.GetPrim().GetAttribute("xformOp:translate")
            parent_translate.Set(Gf.Vec3d(1, 2, 3), 1)
            parent_translate.Set(Gf.Vec3d(9, 8, 7), 48)
        before = {t: self.world(t) for t in (1, 48)}
        self.assertEqual(pose_info(self.prim, 24)["time"], "frame")
        self.apply(dict(matrix=rows(Gf.Matrix4d().SetTranslate((3, 4, 5)))), "world", "matrix", time="frame", frame=24)
        for t in (1, 48):
            self.assertTrue(Gf.IsClose(self.world(t), before[t], 1e-12))
        self.assertEqual(self.prim.GetAttribute(MATRIX_NAME).GetTimeSamples(), [1, 24, 48])


if __name__ == "__main__":
    unittest.main()
