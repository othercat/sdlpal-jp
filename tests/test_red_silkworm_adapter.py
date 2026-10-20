"""Input drift and file-preservation checks; rendering is tested with resources."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from adapt_red_silkworm_description import adapt, adapt_file


BODY = "血のビタミンを吸う蚕。服用した者\nは完全に体力復帰する。\n"
BLOCK = ("[BEGIN MESSAGE] 12920\n" + BODY + "[END MESSAGE] 12921\n").encode()


class RedSilkwormAdapter(unittest.TestCase):
    def test_only_target_break_moves_in_lf_and_crlf_files(self):
        # Identical prose in an unrelated block must remain byte-for-byte intact.
        neighbor = BLOCK.replace(b"12920", b"9990").replace(b"12921", b"9991")
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                original = (b"\xef\xbb\xbf# header\n" + neighbor + BLOCK + b"# tail\n")
                original = original.replace(b"\n", newline)
                expected = original.replace(
                    ("[BEGIN MESSAGE] 12920\n" + BODY).encode().replace(b"\n", newline),
                    ("[BEGIN MESSAGE] 12920\n" +
                     "血のビタミンを吸う蚕。服用した\n者は完全に体力復帰する。\n")
                    .encode().replace(b"\n", newline), 1)
                self.assertEqual(adapt(original), expected)
                self.assertEqual(len(original), len(expected))
                self.assertEqual(adapt(expected), expected)

    def test_rejects_wrong_mapping_or_text_without_guessing(self):
        for invalid in (
            BLOCK + BLOCK,
            BLOCK.replace(b"12920", b"12922"),
            BLOCK.replace(b"12921", b"12922"),
            BLOCK.replace("蚕".encode(), "薬".encode()),
            BLOCK.replace("者\n".encode(), "者\r\n".encode()),
            BLOCK.decode().encode("shift_jis"),
        ):
            with self.subTest(invalid=invalid[:25]):
                with self.assertRaises(ValueError):
                    adapt(invalid)

    def test_source_and_existing_output_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ("source.slf", "out.slf"))
            source.write_bytes(BLOCK)
            with self.assertRaises(ValueError):
                adapt_file(source, source)
            report = adapt_file(source, output)
            self.assertTrue(report["changed"])
            self.assertEqual(source.read_bytes(), BLOCK)
            with self.assertRaises(FileExistsError):
                adapt_file(source, output)
            self.assertEqual(output.read_bytes(), adapt(BLOCK))
            source.write_bytes(b"invalid")
            rejected = Path(directory) / "rejected.slf"
            with self.assertRaises(ValueError):
                adapt_file(source, rejected)
            self.assertFalse(rejected.exists())


if __name__ == "__main__":
    unittest.main()
