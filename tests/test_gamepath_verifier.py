"""Resource-free negative checks for the GamePath pixel comparison oracle."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/japanese"))
from verify_gamepath import compare


class GamePathPixelComparison(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("SDLPAL_PATH_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.reference, self.candidate = (Path(self.temp.name) / n for n in ("reference", "candidate"))
        self.frame = Image.new("P", (320, 200))
        self.frame.putpalette([channel for value in range(256)
                               for channel in (value, value * 37 % 256, value * 97 % 256)])
        for point in ((35, 106), (36, 106), (1, 1)):
            self.frame.putpixel(point, 249)
        for directory in (self.reference, self.candidate):
            directory.mkdir()
            (directory / "clipped-ink.csv").write_bytes(b"object_id,clipped_ink\n377,0\n")
            self.frame.save(directory / "magic-377.bmp")

    def check(self):
        self.frame.save(self.candidate / "magic-377.bmp")
        return compare(self.reference, self.candidate)["magic-377.bmp"]

    def test_identical_pixels(self):
        self.assertEqual(self.check()["different_pixels"], 0)

    def test_only_uniform_selected_label_phase_can_change(self):
        for point in ((35, 106), (36, 106)):
            self.frame.putpixel(point, 250)
        result = self.check()
        self.assertEqual(result["different_pixels"], 2)
        self.assertEqual(result["selected_animation_index_pixels"], 2)

    def test_moved_glyph_is_rejected(self):
        self.frame.putpixel((35, 106), 0)
        self.frame.putpixel((37, 106), 250)
        with self.assertRaisesRegex(RuntimeError, "Non-animation index"):
            self.check()

    def test_same_color_range_outside_selected_label_is_rejected(self):
        self.frame.putpixel((1, 1), 250)
        with self.assertRaisesRegex(RuntimeError, "Non-animation index"):
            self.check()

    def test_description_ink_is_rejected(self):
        self.frame.putpixel((70, 3), 46)
        with self.assertRaisesRegex(RuntimeError, "Non-animation index"):
            self.check()

    def test_nonuniform_phase_is_rejected(self):
        self.frame.putpixel((35, 106), 250)
        self.frame.putpixel((36, 106), 251)
        with self.assertRaisesRegex(RuntimeError, "not uniform"):
            self.check()

    def test_partial_phase_change_is_rejected(self):
        self.frame.putpixel((35, 106), 250)
        with self.assertRaisesRegex(RuntimeError, "not uniform"):
            self.check()

    def test_palette_change_is_rejected(self):
        palette = self.frame.getpalette()
        palette[42 * 3] = 100
        self.frame.putpalette(palette)
        with self.assertRaisesRegex(RuntimeError, "palette changed"):
            self.check()


if __name__ == "__main__":
    unittest.main()
