"""Run with the renderer Python: typed transforms, animation, and native lighting."""
from pathlib import Path
import tempfile
import unittest

from pxr import Gf, Usd, UsdGeom

from omnilab.usd.usd_editing import StageEdits
from omnilab.usd.usd_transforms import transform_basis, transform_info


class TransformTests(unittest.TestCase):
    def setUp(self):
        self.stage = Usd.Stage.CreateInMemory()
        self.prim = UsdGeom.Cube.Define(self.stage, "/World/Cube").GetPrim()
        self.edits = StageEdits(self.stage)

    def apply(self, **values):
        self.edits.set_transform(dict(path=str(self.prim.GetPath()), values=values))

    def test_float_trs_normalized_quaternion_undo_export(self):
        self.edits.set_edit_target(self.stage.GetSessionLayer().identifier)
        source = self.stage.GetRootLayer().ExportToString()
        self.apply(translate=[1.25, 2, 3], orient=[2, 0, 0, 2], scale=[2, 3, 4])
        self.assertEqual(str(self.prim.GetAttribute("xformOp:translate").GetTypeName()), "float3")
        self.assertEqual(str(self.prim.GetAttribute("xformOp:orient").GetTypeName()), "quatf")
        self.assertEqual(str(self.prim.GetAttribute("xformOp:scale").GetTypeName()), "float3")
        self.assertAlmostEqual(self.prim.GetAttribute("xformOp:orient").Get().GetLength(), 1, places=6)
        matrix = UsdGeom.Xformable(self.prim).GetLocalTransformation()
        self.assertTrue(Gf.IsClose(matrix.Transform(Gf.Vec3d(1, 0, 0)), Gf.Vec3d(1.25, 4, 3), 1e-5))
        self.assertEqual(len(self.edits.undo), 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "trs.usda"
            self.edits.export(path)
            saved = Usd.Stage.Open(str(path))
            self.assertTrue(Gf.IsClose(UsdGeom.Xformable(saved.GetPrimAtPath("/World/Cube")).GetLocalTransformation(), matrix, 1e-6))
        self.edits.restore()
        self.assertEqual(UsdGeom.Xformable(self.prim).GetOrderedXformOps(), [])
        self.edits.restore(redo=True)
        self.assertTrue(Gf.IsClose(UsdGeom.Xformable(self.prim).GetLocalTransformation(), matrix, 1e-6))
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), source)

    def test_existing_double_samples_and_other_frames_survive(self):
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            translate = UsdGeom.Xformable(self.prim).AddTranslateOp()
            translate.Set(Gf.Vec3d(1, 2, 3), 1)
            translate.Set(Gf.Vec3d(4, 5, 6), 48)
        self.edits.set_transform(dict(path=str(self.prim.GetPath()), values=dict(translate=[9, 8, 7]), time="frame", frame=24.5))
        self.assertEqual(translate.GetTimeSamples(), [1, 24.5, 48])
        self.assertEqual(translate.Get(1), Gf.Vec3d(1, 2, 3))
        self.assertEqual(translate.Get(48), Gf.Vec3d(4, 5, 6))
        self.assertEqual(str(translate.GetAttr().GetTypeName()), "double3")
        self.assertEqual(transform_info(self.prim, 24.5)["time"], "frame")
        self.edits.restore()
        self.assertEqual(translate.GetTimeSamples(), [1, 48])

    def test_complex_stack_parent_and_reset_preserved(self):
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            parent = UsdGeom.Xform.Define(self.stage, "/World")
            parent.AddTranslateOp().Set(Gf.Vec3d(10, 0, 0))
            xform = UsdGeom.Xformable(self.prim)
            original = xform.AddRotateYOp()
            original.Set(24, 1)
            original.Set(90, 48)
        before = xform.GetLocalTransformation(1)
        self.apply(translate=[1, 0, 0], orient=[1, 0, 0, 0], scale=[1, 1, 1])
        info = transform_info(self.prim, 1)
        self.assertTrue(info["adjustment"])
        self.assertEqual(info["channels"]["orient"]["samples"], 0)
        original_info = next(op for op in info["xform_ops"] if op["name"] == "xformOp:rotateY")
        self.assertEqual(original_info["samples"], 2)
        self.assertTrue(original_info["has_sample"])
        self.assertEqual(original_info["channel"], "orient")
        self.assertEqual(original.GetTimeSamples(), [1, 48])
        self.assertEqual(original.Get(48), 90)
        self.assertEqual([str(op.GetOpName()) for op in xform.GetOrderedXformOps()],
                         ["xformOp:rotateY", "xformOp:translate:studio", "xformOp:orient:studio", "xformOp:scale:studio"])
        pivot, basis = transform_basis(self.prim, Usd.TimeCode(1))
        self.assertTrue(Gf.IsClose(pivot, before.Transform(Gf.Vec3d(1, 0, 0)) + Gf.Vec3d(10, 0, 0), 1e-6))
        self.assertTrue(Gf.IsClose(basis.TransformDir(Gf.Vec3d(1, 0, 0)), before.TransformDir(Gf.Vec3d(1, 0, 0)), 1e-6))
        xform.SetResetXformStack(True)
        self.apply(scale=[2, 1, 1])
        self.assertTrue(xform.GetResetXformStack())
        pivot, _ = transform_basis(self.prim, Usd.TimeCode(1))
        self.assertTrue(Gf.IsClose(pivot, before.Transform(Gf.Vec3d(1, 0, 0)), 1e-6))

    def test_sample_metadata_and_keying_individual_channels(self):
        with Usd.EditContext(self.stage, self.stage.GetRootLayer()):
            xform = UsdGeom.Xformable(self.prim)
            translate = xform.AddTranslateOp()
            rotate = xform.AddOrientOp(UsdGeom.XformOp.PrecisionFloat)
            scale = xform.AddScaleOp()
            for t in (1, 24.5, 48):
                translate.Set(Gf.Vec3d(t, 0, 0), t)
            for t in (12, 36):
                rotate.Set(Gf.Quatf(1), t)
            scale.Set(Gf.Vec3f(1), 18)
        info = transform_info(self.prim, 24.5)
        self.assertEqual([info["channels"][name]["samples"] for name in ("translate", "orient", "scale")], [3, 2, 1])
        self.assertTrue(info["channels"]["translate"]["has_sample"])
        self.assertFalse(info["channels"]["orient"]["has_sample"])
        self.assertFalse(info["channels"]["scale"]["has_sample"])
        self.edits.set_transform(dict(path=str(self.prim.GetPath()), values=dict(translate=[9, 8, 7]), time="frame", frame=20))
        self.assertEqual(translate.GetTimeSamples(), [1, 20, 24.5, 48])
        self.assertEqual(rotate.GetTimeSamples(), [12, 36])
        self.assertEqual(scale.GetTimeSamples(), [18])
        self.edits.restore()
        self.assertEqual(transform_info(self.prim, 20)["channels"]["translate"]["samples"], 3)

    def test_invalid_transform_rolls_back_and_non_xforms_are_readonly(self):
        before = self.edits.layer.ExportToString()
        for values in (dict(orient=[0, 0, 0, 0]), dict(translate=[1, 2, float("nan")]),
                       dict(scale=[1, 2, 1e40]), dict(translate=[True, 0, 0])):
            with self.assertRaises(ValueError):
                self.apply(**values)
            self.assertEqual(self.edits.layer.ExportToString(), before)
        self.assertFalse(transform_info(None, 1)["editable"])
        self.assertFalse(transform_info(self.stage.GetPseudoRoot(), 1)["editable"])



if __name__ == "__main__":
    unittest.main()
