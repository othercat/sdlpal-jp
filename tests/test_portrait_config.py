"""Resource-free negative checks for configuration persistence evidence."""
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/japanese"))
from verify_portrait_config import bind_frame_images, check_backend, check_saved, exact_outputs


class PortraitConfigEvidence(unittest.TestCase):
    def test_backend_cannot_be_renamed_or_omitted(self):
        self.assertEqual("1.2.15", check_backend("Config backend: SDL 1.2.15\n", "sdl1"))
        self.assertEqual("2.0.10", check_backend("Config backend: SDL 2.0.10\n", "sdl2"))
        for invalid in ("", "Config backend: SDL 2.0.10\n", "Config backend: SDL 1.2.15\n" * 2):
            with self.assertRaisesRegex(ValueError, "backend label"):
                check_backend(invalid, "sdl1")

    def test_published_rgb_and_indexed_pixels_must_match_the_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            indexed = Image.new("P", (320, 200), 1)
            palette = bytes(channel for value in range(256) for channel in (value, value // 2, value // 3))
            indexed.putpalette(palette)
            expected = indexed.convert("RGB")
            indexed.save(root / "frame.bmp")
            expected.save(root / "frame-rgb.bmp")
            bind_frame_images(root, "frame", indexed.tobytes(), palette, expected)
            changed = expected.copy()
            changed.putpixel((0, 0), (2, 1, 1))
            changed.save(root / "frame-rgb.bmp")
            with self.assertRaisesRegex(ValueError, "RGB BMP"):
                bind_frame_images(root, "frame", indexed.tobytes(), palette, expected)
            expected.save(root / "frame-rgb.bmp")
            changed = indexed.copy()
            changed.putpixel((0, 0), 2)
            changed.save(root / "frame.bmp")
            with self.assertRaisesRegex(ValueError, "indexed BMP"):
                bind_frame_images(root, "frame", indexed.tobytes(), palette, expected)

    def test_save_may_add_defaults_but_preserves_explicit_inputs(self):
        source = "GamePath=中文/\nMessageFileName=日文.slf\nPortraitFileName=头像.por\n".encode()
        check_saved(source, source + b"EnableGLSL=0\n")
        for key in (b"GamePath", b"MessageFileName", b"PortraitFileName"):
            with self.assertRaises(ValueError):
                check_saved(source, source.replace(key + b"=", key + b"=changed-"))

    def test_clear_requires_absence_and_preserves_other_saved_values(self):
        source = b"GamePath=resource/\nPortraitFileName=portraits.por\nEnableGLSL=0\n"
        check_saved(source, b"GamePath=resource/\nEnableGLSL=0\n", clear=True)
        for invalid in (source, source.replace(b"portraits.por", b""), b"GamePath=changed/\nEnableGLSL=0\n"):
            with self.assertRaises(ValueError):
                check_saved(source, invalid, clear=True)

    def test_duplicate_keys_cannot_hide_a_stale_portrait_value(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            check_saved(b"PortraitFileName=a.por\n", b"PortraitFileName=old.por\nPortraitFileName=a.por\n")

    def test_empty_missing_or_changed_source_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            left, right = Path(directory) / "left", Path(directory) / "right"
            left.mkdir(); right.mkdir()
            with self.assertRaisesRegex(ValueError, "Missing"):
                exact_outputs(left, right)
            for root in (left, right):
                for name in ("portrait-frames.bin", "portrait-rgb.bin", "portraits.csv"):
                    (root / name).write_bytes(b"verified-frame")
            self.assertEqual(3, exact_outputs(left, right))
            (right / "portrait-rgb.bin").write_bytes(b"changed-frame")
            with self.assertRaisesRegex(ValueError, "changed"):
                exact_outputs(left, right)
            (right / "portrait-rgb.bin").unlink()
            with self.assertRaisesRegex(ValueError, "changed"):
                exact_outputs(left, right)


if __name__ == "__main__":
    unittest.main()
