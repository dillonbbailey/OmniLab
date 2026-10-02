"""Run with MoonRay's Python / OpenImageIO environment."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import OpenImageIO as oiio

from omnilab.render.exr_image import display_exr, inspect_exr, PixelReader
from omnilab.render.exr_channels import channel_inventory, resolve_selection
from omnilab.render.texture_thumbnail import make_thumbnail


class ExrTests(unittest.TestCase):
    def test_texture_thumbnail_float_color_raw_and_original_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path, preview = Path(directory) / "texture.exr", Path(directory) / "thumbnail.png"
            spec = oiio.ImageSpec(600, 300, 4, oiio.FLOAT)
            spec.channelnames = ["R", "G", "B", "A"]
            writer = oiio.ImageOutput.create(str(path))
            writer.open(str(path), spec)
            writer.write_image(np.full((300, 600, 4), [.25, .5, .75, .5], dtype=np.float32))
            writer.close()
            original = path.read_bytes()
            result = make_thumbnail(str(path), preview)
            self.assertEqual((result["width"], result["height"]), (600, 300))
            image = oiio.ImageBuf(str(preview))
            self.assertEqual((image.spec().width, image.spec().height), (256, 128))
            np.testing.assert_allclose(image.get_pixels(oiio.UINT8)[10, 10], [136, 187, 224], atol=1)
            make_thumbnail(str(path), preview, raw=True)
            np.testing.assert_allclose(oiio.ImageBuf(str(preview)).get_pixels(oiio.UINT8)[10, 10], [63, 127, 191], atol=1)
            enlarged = Path(directory) / "selected.png"
            make_thumbnail(str(path), enlarged, size=2048)
            image = oiio.ImageBuf(str(enlarged))
            self.assertEqual((image.spec().width, image.spec().height), (600, 300))
            self.assertEqual(path.read_bytes(), original)

    def test_layer_components_custom_mattes_and_source_float_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            path, preview = Path(directory) / "channels.exr", Path(directory) / "display.png"
            spec = oiio.ImageSpec(8, 4, 8, oiio.FLOAT)
            spec.channelnames = ["R", "G", "B", "A", "mattes.hard", "normal.X", "normal.Y", "normal.Z"]
            spec.x, spec.y = 10, -5
            spec.attribute("compression", "zip")
            pixels = np.full((4, 8, 8), [.2, .4, .6, 1., .5, -1., 0., 4.], dtype=np.float32)
            pixels[1, 1, 6] = np.nan
            pixels[1, 1, 7] = np.inf
            writer = oiio.ImageOutput.create(str(path))
            self.assertTrue(writer.open(str(path), spec))
            self.assertTrue(writer.write_image(pixels))
            writer.close()
            original = path.read_bytes()
            metadata = inspect_exr(path)
            layers, scalars = channel_inventory(metadata)
            self.assertEqual([layer["name"] for layer in layers], ["rgba", "mattes", "normal"])
            self.assertEqual(len(scalars), 8)
            selection = dict(layer=[0, "rgba"], component="A", matte=[0, "mattes.hard"])
            info = display_exr(path, preview, selection=selection, metadata=metadata)
            np.testing.assert_array_equal(oiio.ImageBuf(str(preview)).get_pixels(oiio.UINT8)[0, 0], [127] * 3)
            selection.update(component="RGB", overlay=True)
            display_exr(path, preview, display="raw", selection=selection, metadata=metadata)
            np.testing.assert_array_equal(oiio.ImageBuf(str(preview)).get_pixels(oiio.UINT8)[0, 0], [102, 76, 114])
            # Aliases and scalar component routing do not apply a color transfer.
            selection.update(layer=[0, "normal"], component="B", overlay=False)
            info = display_exr(path, preview, selection=selection, metadata=metadata, exposure=-2)
            np.testing.assert_array_equal(oiio.ImageBuf(str(preview)).get_pixels(oiio.UINT8)[0, 0], [255] * 3)
            probe = PixelReader()
            sampled = probe.sample(str(path), 10, -5, info["probe_channels"])
            self.assertEqual([v["value"] for v in sampled["values"]], [-1., 0., 4., .5])
            sampled = probe.sample(str(path), 11, -4, info["probe_channels"])
            self.assertEqual([v["value"] for v in sampled["values"]], [-1., "nan", "inf", .5])
            self.assertEqual(info["x"], 10)
            self.assertEqual(info["y"], -5)
            self.assertEqual(path.read_bytes(), original)

    def test_cross_part_matte_aligns_pixel_windows_and_missing_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            path, preview = Path(directory) / "parts.exr", Path(directory) / "preview.png"
            specs = [oiio.ImageSpec(4, 4, 3, oiio.FLOAT), oiio.ImageSpec(2, 2, 1, oiio.FLOAT)]
            specs[0].channelnames = ["rgba.red", "rgba.green", "rgba.blue"]
            specs[1].channelnames = ["mask"]
            specs[1].x = specs[1].y = 1
            for spec, name in zip(specs, ("beauty", "mattes")):
                spec.full_width = spec.full_height = 4
                spec.attribute("oiio:subimagename", name)
            writer = oiio.ImageOutput.create(str(path))
            self.assertTrue(writer.open(str(path), specs), writer.geterror())
            writer.write_image(np.ones((4, 4, 3), dtype=np.float32))
            self.assertTrue(writer.open(str(path), specs[1], "AppendSubimage"), writer.geterror())
            writer.write_image(np.ones((2, 2, 1), dtype=np.float32))
            writer.close()
            metadata = inspect_exr(path)
            self.assertEqual(channel_inventory(metadata)[0][0]["label"], "beauty / rgba")
            selection = dict(layer=[0, "rgba"], component="A", matte=[1, "mask"])
            info = display_exr(path, preview, selection=selection, metadata=metadata)
            pixels = oiio.ImageBuf(str(preview)).get_pixels(oiio.UINT8)
            np.testing.assert_array_equal(pixels[0, 0], [0] * 3)
            np.testing.assert_array_equal(pixels[1, 1], [255] * 3)
            values = PixelReader().sample(str(path), 0, 0, info["probe_channels"])
            self.assertEqual(values["values"][-1]["value"], 0.)
            selection["matte"] = "auto"
            info = display_exr(path, preview, selection=selection, metadata=metadata)
            self.assertIn("No matte", info["warning"])
            self.assertFalse(oiio.ImageBuf(str(preview)).get_pixels().any())
            missing = resolve_selection(metadata, dict(layer=[0, "absent"], component="B"))
            self.assertEqual(missing["layer"]["name"], "rgba")

    def test_multipart_channels_display_and_original_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multipart.exr"
            specs = [oiio.ImageSpec(8, 4, 4, oiio.FLOAT), oiio.ImageSpec(8, 4, 3, oiio.FLOAT)]
            specs[0].channelnames = ["R", "G", "B", "A"]
            specs[1].channelnames = ["normal.X", "normal.Y", "normal.Z"]
            for spec, name in zip(specs, ("beauty", "normals")):
                spec.attribute("oiio:subimagename", name)
            writer = oiio.ImageOutput.create(str(path))
            self.assertTrue(writer.open(str(path), specs), writer.geterror())
            self.assertTrue(writer.write_image(np.full((4, 8, 4), [.1, .25, 4.0, 1.0], dtype=np.float32)))
            self.assertTrue(writer.open(str(path), specs[1], "AppendSubimage"), writer.geterror())
            self.assertTrue(writer.write_image(np.full((4, 8, 3), [-1, 0, 1], dtype=np.float32)))
            writer.close()
            original = path.read_bytes()
            manifest = inspect_exr(path)
            self.assertEqual(len(manifest["parts"]), 2)
            view = next(v for v in manifest["views"] if v["label"] == "normals / normal")
            output = Path(directory) / "normal.png"
            display_exr(path, output, view)
            pixels = oiio.ImageBuf(str(output)).get_pixels(oiio.UINT8)
            np.testing.assert_array_equal(pixels[0, 0], [0, 127, 255])
            view = next(v for v in manifest["views"] if v["label"] == "beauty / G")
            display_exr(path, output, view, "raw", 1)
            pixels = oiio.ImageBuf(str(output)).get_pixels(oiio.UINT8)
            np.testing.assert_array_equal(pixels[0, 0], [127, 127, 127])
            self.assertEqual(path.read_bytes(), original)
            with self.assertRaises(ValueError):
                display_exr(path, output, dict(part=0, channels=[100]))


if __name__ == "__main__":
    unittest.main()
