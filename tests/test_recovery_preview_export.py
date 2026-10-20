"""Prevent invisible source evidence caused by transparent GPU readback."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "previews", Path(__file__).resolve().parents[1] / "tools/export_recovery_previews.py")
previews = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previews)


class PreviewExport(unittest.TestCase):
    def test_rejects_invisible_and_partially_transparent_colored_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory) / name for name in ("source.png", "target.png"))
            for alpha in (0, 127):
                with self.subTest(alpha=alpha):
                    Image.new("RGBA", (2, 2), (255, 128, 64, alpha)).save(source)
                    with self.assertRaisesRegex(ValueError, "Non-opaque"):
                        previews.export_preview(source, target)
                    self.assertFalse(target.exists())

    def test_png_preserves_rgb_and_composites_identically_on_any_background(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory) / name for name in ("source.png", "target.png"))
            for mode in ("RGB", "RGBA"):
                with self.subTest(mode=mode):
                    original = Image.new(mode, (2, 2), (0, 0, 0) if mode == "RGB" else (0, 0, 0, 255))
                    original.putpixel((1, 1), (255, 128, 64) if mode == "RGB" else (255, 128, 64, 255))
                    original.save(source)
                    previews.export_preview(source, target)
                    with Image.open(target) as result:
                        self.assertEqual(result.mode, "RGB")
                        for background in ("white", "#181818"):
                            composite = Image.alpha_composite(
                                Image.new("RGBA", result.size, background), result.convert("RGBA"))
                            self.assertEqual(composite.convert("RGB").tobytes(), original.convert("RGB").tobytes())


if __name__ == "__main__":
    unittest.main()
