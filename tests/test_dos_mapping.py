"""Failure and identity checks for the version-specific DOS mapping."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools/japanese"
sys.path.insert(0, str(TOOLS))
from makemessage_dos import MANIFEST, checked_group, text_hash
from resource_version import checked_win_inputs, without_win_tag


class DOSMapping(unittest.TestCase):
    def test_keys_are_dos_identity_not_win_ranges(self):
        manifest = json.loads(MANIFEST.read_text("utf-8"))
        rows = manifest["groups"]
        self.assertEqual(len({tuple(r["dos"][2:]) for r in rows}), 4476)
        first = rows[0]
        self.assertEqual(first["dos"], [26, 26, 0, 0])
        self.assertEqual(first["win"][2:], [12221, 12221])
        preserved = {tuple(r["dos"][2:]): r["text"] for r in rows if "win" not in r}
        self.assertEqual(preserved, {(1, 1): ["?(2)"], (2, 2): ["?(4)"],
            (3, 3): ["?(2)"], (4, 4): ["?(3)"], (5965, 5965): ["EGIN"]})
        speaker = next(r for r in rows if r["dos"][2:] == [1741, 1742])
        self.assertEqual(speaker["text"], ["秀蘭：", "あ・・・こんにちは。"])

    def test_raw_anchors_text_and_operations_are_checked(self):
        source = {"scripts": [(0xffff, 0, 0, 0), (0x008e, 0, 0, 0), (0xffff, 1, 0, 0)],
                  "messages": ["第一行", "第二行"]}
        text = ["第一行", "[CLEAR MESSAGE]", "第二行"]
        self.assertEqual(checked_group(source, [0, 2, 0, 1], text_hash(text)), text)
        for anchor, digest in (([0, 2, 1, 2], None), ([0, 1, 0, 1], None),
                               ([0, 2, 0, 1], text_hash(text[:-1]))):
            with self.assertRaises(ValueError):
                checked_group(source, anchor, digest)
        source["scripts"][1] = (0x0037, 40, 46, 8)
        with self.assertRaisesRegex(ValueError, "Unexpected operation"):
            checked_group(source, [0, 2, 0, 1], saturn_special=True)

    def test_win_metadata_cannot_strip_unrelated_settings(self):
        text = "[BEGIN SETTING]\nResourceVersion=WIN95\nFontFlavor=Japanese\n[END SETTING]\n"
        self.assertEqual(without_win_tag(text), text.replace("ResourceVersion=WIN95\n", ""))
        for bad in (text.replace("WIN95", "DOS"), text + "ResourceVersion=WIN95\n",
                    text.replace("[BEGIN SETTING]\n", "[BEGIN SETTING]\nUseISOFont=0\n")):
            with self.assertRaises(ValueError):
                without_win_tag(bad)

    def test_win_entry_rejects_wrong_encoding_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaisesRegex(ValueError, "requires GBK"):
                checked_win_inputs(path, path, "big5")
            output = path / "preserved.slf"
            output.write_bytes(b"keep")
            process = subprocess.run([sys.executable, "-B", str(TOOLS / "makemessage_j.py"),
                directory, directory, str(output), "big5"], capture_output=True, timeout=30)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
