"""Resource-free CLI and real GUI-callback regression checks (no Tk window)."""
import ast
import hashlib
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/japanese"
spec = importlib.util.spec_from_file_location("japanese_baseline", TOOLS / "verify_baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def steam_fixture(path, encoding="gbk"):
    path.mkdir()
    suffix = "chs" if encoding == "gbk" else "cht"
    # Three offsets describe two messages of 2 and 3 bytes.
    (path / "SSS.MKF").write_bytes(struct.pack("<6I", 24, 24, 24, 24, 36, 36)
                                 + struct.pack("<3I", 0, 2, 5))
    (path / f"MSG_{suffix}.txt").write_bytes("0:A\n1:xy\n2:\n".encode("utf-16-le"))
    (path / f"WORD_{suffix}.txt").write_bytes("0:甲\n1:A:B\n".encode("utf-16-le"))
    return b"A xy ", "甲".encode(encoding) + b" " * 8 + b"A:B" + b" " * 7


def gui_callbacks(messages, commands, **values):
    # Execute the actual handler definitions, excluding the upstream top-level
    # Tk creation/widgets/mainloop. UI values/output are test doubles.
    source = TOOLS / "rungui.py"
    tree = ast.parse(source.read_text("utf-8"))
    names = {"find_file", "prepare_resources", "generate"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(functions) != 3:
        raise AssertionError("GUI handlers changed; review the headless fixture")

    def popen(command, **kwargs):
        commands.append(command)
        return subprocess.Popen(command, **kwargs)

    import shutil
    namespace = {
        "__file__": str(source), "os": os, "sys": sys, "shutil": shutil,
        "subprocess": SimpleNamespace(Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT),
        "write_output": messages.append, "show_license": lambda: None,
        "output_text": SimpleNamespace(delete=lambda *args: None),
        "tk": SimpleNamespace(END="end"),
        "messagebox": SimpleNamespace(showerror=lambda title, message: messages.append(message)),
    }
    for name in ("pc_path", "saturn_path", "output_path", "pc_encoding"):
        namespace[name] = SimpleNamespace(get=lambda name=name: values.get(name, ""))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


class ConversionTools(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdlpal-tools-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_tool(self, name, *arguments):
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(TOOLS / name),
                               *map(str, arguments)], cwd=self.root, capture_output=True,
                              text=True, encoding="utf-8", timeout=30)

    def test_steam_all_modes_and_encodings(self):
        for encoding in ("gbk", "big5"):
            with self.subTest(encoding=encoding):
                data = self.root / encoding
                msg, word = steam_fixture(data, encoding)
                output = self.root / (encoding + "-out")
                output.mkdir()
                result = self.run_tool("steam_to_legacy.py", "all", data, output, encoding)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual((output / "M.MSG").read_bytes(), msg)
                self.assertEqual((output / "WORD.DAT").read_bytes(), word)

    def test_steam_rejects_message_and_word_overflow_without_output(self):
        data = self.root / "overflow"
        steam_fixture(data)
        (data / "MSG_chs.txt").write_bytes("0:ABC\n1:xy\n2:\n".encode("utf-16-le"))
        (data / "WORD_chs.txt").write_bytes("0:ABCDEFGHIJK\n".encode("utf-16-le"))
        for mode in ("msg", "word"):
            with self.subTest(mode=mode):
                output = self.root / (mode + ".bin")
                result = self.run_tool("steam_to_legacy.py", mode, data, output, "gbk")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR", result.stdout)
                self.assertFalse(output.exists())

    def test_cli_help_and_invalid_encoding_or_mode(self):
        help_result = self.run_tool("makemessage_j.py", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("saturnpath", help_result.stdout)
        invalid = self.run_tool("makemessage_j.py", self.root, self.root, self.root / "bad.slf", "utf16")
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid choice", invalid.stderr)
        for mode, encoding, message in (("bad", "gbk", "MODE must"), ("all", "utf16", "Encoding must")):
            result = self.run_tool("steam_to_legacy.py", mode, self.root, self.root, encoding)
            self.assertEqual(result.returncode, 1)
            self.assertIn(message, result.stdout)

    def test_gui_prepares_resources_from_unrelated_working_directory(self):
        messages, commands = [], []
        ui = gui_callbacks(messages, commands)
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            for encoding in ("gbk", "big5"):
                data = self.root / ("GUI 日本語 " + encoding)
                msg, word = steam_fixture(data, encoding)
                ui["prepare_resources"](str(data), encoding)
                self.assertEqual((data / "M.MSG").read_bytes(), msg)
                self.assertEqual((data / "WORD.DAT").read_bytes(), word)
        finally:
            os.chdir(previous)
        self.assertEqual(len(commands), 4)
        for command in commands:
            self.assertEqual(command[0], sys.executable)
            self.assertTrue(Path(next(a for a in command if a.endswith(".py"))).is_absolute())

    def test_gui_stops_generation_when_resource_preparation_fails(self):
        data = self.root / "missing-steam-input"
        data.mkdir()
        messages, commands = [], []
        ui = gui_callbacks(messages, commands, pc_path=str(data), saturn_path=str(self.root),
                           output_path=str(self.root / "should-not-exist.slf"), pc_encoding="gbk")
        ui["generate"]()
        self.assertEqual(len(commands), 1)
        self.assertEqual(Path(next(a for a in commands[0] if a.endswith(".py"))).name, "steam_to_legacy.py")
        self.assertIn("Resource preparation failed", "".join(messages))
        self.assertFalse((self.root / "should-not-exist.slf").exists())

    def test_gui_missing_fields_do_not_launch_child(self):
        messages, commands = [], []
        gui_callbacks(messages, commands)["generate"]()
        self.assertEqual(commands, [])
        self.assertIn("Please select PC resource directory.", messages)

    def test_gui_stops_after_word_conversion_failure(self):
        data = self.root / "word-failure"
        steam_fixture(data)
        (data / "WORD_chs.txt").write_bytes("0:ABCDEFGHIJK\n".encode("utf-16-le"))
        messages, commands = [], []
        ui = gui_callbacks(messages, commands, pc_path=str(data), saturn_path=str(self.root),
                           output_path=str(self.root / "no.slf"), pc_encoding="gbk")
        ui["generate"]()
        self.assertEqual(len(commands), 2)
        self.assertTrue(all("steam_to_legacy.py" in " ".join(command) for command in commands))
        self.assertIn("Resource preparation failed", "".join(messages))
        self.assertTrue((data / "M.MSG").exists())  # Upstream preparation is staged, not transactional.
        self.assertFalse((data / "WORD.DAT").exists())
        self.assertFalse((self.root / "no.slf").exists())

    def test_baseline_rejects_wrong_encoding_or_existing_output_without_writes(self):
        output = self.root / "output"
        with self.assertRaisesRegex(ValueError, "requires GBK"):
            baseline.reproduce(self.root, self.root, output, "big5")
        self.assertFalse(output.exists())
        other = self.root / "inputs"
        other.mkdir()
        output.mkdir()
        sentinel = output / "keep"
        sentinel.write_bytes(b"preserve")
        with self.assertRaisesRegex(ValueError, "already exists"):
            baseline.reproduce(other, other, output)
        self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_input_guard_rejects_dos_changed_and_missing_inputs(self):
        known = self.root / "known"
        known.mkdir()
        (known / "SSS.MKF").write_bytes(b"DOS")
        dos_hash = hashlib.sha256(b"DOS").hexdigest()
        with self.assertRaisesRegex(ValueError, "PAL_DOS"):
            baseline.check_inputs(known, {"sss.mkf": "win-digest"}, "Win", dos_hash)
        with self.assertRaisesRegex(ValueError, "unsupported version"):
            baseline.check_inputs(known, {"sss.mkf": "win-digest"}, "Win")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            baseline.check_inputs(known, {"m.msg": "missing"}, "Win")


class DuplicateMessageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("message_converter", TOOLS / "makemessage_j.py")
        cls.converter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.converter)

    def test_identical_reuse_and_different_spans(self):
        seen = {}
        for script in (100, 200, 300):
            self.converter.check_message_body(seen, (1, 1), script, "same\n")
        self.converter.check_message_body(seen, (1, 2), 400, "different span\n")
        self.assertEqual(len(seen), 2)

    def test_conflicting_reuse_is_rejected_in_both_orders(self):
        for bodies in (("取得\n", "採集\n"), ("採集\n", "取得\n")):
            with self.subTest(bodies=bodies):
                seen = {}
                self.converter.check_message_body(seen, (1, 1), 100, bodies[0])
                with self.assertRaisesRegex(ValueError, "MESSAGE 1-1 at Win scripts 100/200"):
                    self.converter.check_message_body(seen, (1, 1), 200, bodies[1])
                self.assertEqual(seen[(1, 1)], (100, bodies[0]))

    def test_control_marker_difference_is_not_ignored(self):
        seen = {}
        self.converter.check_message_body(seen, (1, 2), 100, "first\n[CLEAR MESSAGE]\nsecond\n")
        with self.assertRaisesRegex(ValueError, "Conflicting MESSAGE"):
            self.converter.check_message_body(seen, (1, 2), 200, "first\nsecond\n")

    def test_translation_rejects_source_anchor_and_body_drift(self):
        key = (1, 4)
        record = self.converter.TRANSLATION_CORRECTIONS[key]
        anchors, body = record[:4], "\n".join(record[4]) + "\n"
        for index in range(4):
            changed = list(anchors)
            changed[index] += 1
            with self.subTest(anchor=index):
                with self.assertRaisesRegex(ValueError, "Issue #6 source differs"):
                    self.converter.corrected_translation(key, *changed, body)
        for changed in (
            body.replace("[CLEAR MESSAGE]\n", ""),
            body.replace("~60", "~30"),
            body.replace("殺してやる", "助けてやる"),
        ):
            with self.subTest(body=changed):
                with self.assertRaisesRegex(ValueError, "Issue #6 source differs"):
                    self.converter.corrected_translation(key, *anchors, changed)


if __name__ == "__main__":
    unittest.main()
