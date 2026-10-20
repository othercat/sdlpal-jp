import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/japanese"))
from convert_portraits import convert, decode_saturn, fit_pixels, MANIFEST, mkf_chunks, pc_dimensions


class PortraitConversion(unittest.TestCase):
    def slot(self, body, width=3, height=1):
        return (struct.pack(">HH", width, height) + body).ljust(0x2800, b"\0")

    def test_transparent_skip_and_decoder_height_boundary(self):
        w, h, pixels, used = decode_saturn(self.slot(b"\x81\x02\x07\x08\xAA"))
        self.assertEqual((3, 1, b"\0\x07\x08", 8), (w, h, pixels, used))
        for bad in (b"\0", b"\x80", b"\x84", b"\x04\1\2\3\4", b"\x03\0\1\2"):
            with self.assertRaises(ValueError):
                decode_saturn(self.slot(bad))
        with self.assertRaises(ValueError):
            decode_saturn(self.slot(b"\x83\x01\x02"))

    def test_aspect_fit_keeps_native_extent_and_transparent_padding(self):
        pixels, layout = fit_pixels(bytes(range(1, 13)), 4, 3, 8, 3)
        self.assertEqual({"scaled_width": 4, "scaled_height": 3, "left": 2, "top": 0,
                          "method": "aspect-fit, no enlargement, floor nearest sample"}, layout)
        self.assertEqual(b"\0\0\1\2\3\4\0\0", pixels[:8])
        pixels, layout = fit_pixels(bytes(range(1, 13)), 4, 3, 2, 2)
        self.assertEqual(b"\1\3\0\0", pixels)
        self.assertEqual(1, layout["scaled_height"])

    def test_reviewed_wide_and_tall_portraits(self):
        w, h, pixels, _ = decode_saturn(self.slot(b"\xFF\x86", width=133))
        self.assertEqual((133, 1, bytes(133)), (w, h, pixels))
        self.assertEqual((135, 131), pc_dimensions(b"\x02\0\0\0" + struct.pack("<HH", 135, 131)))
        fitted, _ = fit_pixels(bytes([7]) * 133 * 111, 133, 111, 135, 98)
        self.assertEqual(135 * 98, len(fitted))

    def test_mkf_rejects_nonmonotonic_and_out_of_file_offsets(self):
        self.assertEqual([b"abc"], mkf_chunks(struct.pack("<2I", 8, 11) + b"abc"))
        for data in (b"\0", struct.pack("<2I", 8, 100), struct.pack("<3I", 12, 11, 12)):
            with self.assertRaises(ValueError):
                mkf_chunks(data)

    def test_wrong_or_existing_input_cannot_write_or_overwrite_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource, saturn, output = root / "pc", root / "saturn", root / "output"
            resource.mkdir(); saturn.mkdir()
            # A correctly named but altered RGM must be rejected before output creation.
            (resource / "RGM.MKF").write_bytes(b"altered")
            with self.assertRaisesRegex(ValueError, "Unreviewed input"):
                convert(resource, saturn, output, "win")
            self.assertFalse(output.exists())
            output.mkdir()
            sentinel = output / "sentinel"
            sentinel.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "already exists"):
                convert(resource, saturn, output, "dos")
            self.assertEqual(b"keep", sentinel.read_bytes())
            manifest = json.loads(MANIFEST.read_text("utf-8"))
            self.assertNotIn(38, manifest["identity_ids"])


if __name__ == "__main__":
    unittest.main()
