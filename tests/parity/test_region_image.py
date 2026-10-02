"""Run under the MoonRay OpenImageIO runtime."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import OpenImageIO as oiio

from omnilab.render.render_region import merge_region, preserve_display_region


def write(path, parts):
    output = oiio.ImageOutput.create(str(path))
    assert output.open(str(path), [spec for spec, _ in parts]), output.geterror()
    for index, (spec, pixels) in enumerate(parts):
        if index:
            assert output.open(str(path), spec, "AppendSubimage"), output.geterror()
        assert output.write_image(pixels), output.geterror()
    assert output.close(), output.geterror()


def part(name, channels, width, height, val, x=0, y=0):
    spec = oiio.ImageSpec(width, height, len(channels), oiio.FLOAT)
    spec.channelnames = channels
    spec.x, spec.y = x, y
    spec.full_width, spec.full_height = 8, 6
    spec.attribute("oiio:subimagename", name)
    spec.attribute("compression", "zip")
    return spec, np.full((height, width, len(channels)), val, dtype=np.float32)


class RegionImageTests(unittest.TestCase):
    def test_display_pixels_stay_unchanged_outside_downsampled_region(self):
        with tempfile.TemporaryDirectory() as folder:
            base, new = Path(folder)/"base.png", Path(folder)/"new.png"
            before = np.arange(8 * 6 * 3, dtype=np.uint8).reshape((6, 8, 3))
            after = np.full_like(before, 245)
            for path, pixels in ((base, before), (new, after)):
                output = oiio.ImageOutput.create(str(path))
                self.assertTrue(output.open(str(path), oiio.ImageSpec(8, 6, 3, oiio.UINT8)))
                self.assertTrue(output.write_image(pixels))
                output.close()
            preserve_display_region(new, base, [3, 2, 10, 8], stride=2)
            pixels = oiio.ImageInput.open(str(new))
            actual = pixels.read_image(format=oiio.UINT8)
            pixels.close()
            expected = before.copy()
            expected[1:4, 2:5] = after[1:4, 2:5]
            np.testing.assert_array_equal(actual, expected)

    def test_multipart_crop_preserves_matching_channels_and_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            base, new = Path(folder)/"base.exr", Path(folder)/"new.exr"
            originals = [part("beauty", ["R", "G", "B"], 8, 6, [.13, .27, .49]),
                         part("data", ["normal.X", "normal.Y", "depth"], 8, 6, [-1, .5, 10])]
            write(base, originals)
            original_file = base.read_bytes()
            # New part/channel order must not swap AOV values. A new channel
            # has no baseline and must remain zero outside the rendered crop.
            updates = [part("data", ["depth", "new_mask", "normal.X"], 3, 2, [2, 1, -2], 2, 1),
                       part("beauty", ["R", "G", "B"], 3, 2, [4, 2, 1], 2, 1)]
            updates[0][0].attribute("shot", "region-test")
            write(new, updates)
            merge_region(new, base, [2, 1, 5, 3], 8, 6)
            data = oiio.ImageBuf(str(new), 0, 0)
            names = list(data.spec().channelnames)
            pixels = data.get_pixels(oiio.FLOAT)
            self.assertEqual(pixels.shape, (6, 8, 3))
            self.assertEqual(data.spec().get_string_attribute("shot"), "region-test")
            np.testing.assert_array_equal(pixels[0, 0, [names.index(n) for n in ["depth", "new_mask", "normal.X"]]], [10, 0, -1])
            np.testing.assert_array_equal(pixels[1, 2, [names.index(n) for n in ["depth", "new_mask", "normal.X"]]], [2, 1, -2])
            beauty = oiio.ImageBuf(str(new), 1, 0).get_pixels(oiio.FLOAT)
            outside = np.ones((6, 8), dtype=bool)
            outside[1:3, 2:5] = False
            np.testing.assert_array_equal(beauty[outside], originals[0][1][outside])
            self.assertEqual(base.read_bytes(), original_file)

    def test_no_baseline_and_resolution_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            base, new = Path(folder)/"base.exr", Path(folder)/"new.exr"
            write(new, [part("beauty", ["R", "G", "B"], 3, 2, 1, 2, 1)])
            merge_region(new, None, [2, 1, 5, 3], 8, 6)
            image = oiio.ImageBuf(str(new)).get_pixels(oiio.FLOAT)
            self.assertEqual(float(image.sum()), 18.)
            write(base, [part("beauty", ["R", "G", "B"], 4, 4, 1)])
            before = new.read_bytes()
            with self.assertRaisesRegex(ValueError, "different resolution"):
                merge_region(new, base, [2, 1, 5, 3], 8, 6)
            self.assertEqual(new.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
