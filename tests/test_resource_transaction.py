"""Failure injection for the real CLI all / GUI preparation entry points."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_japanese_conversion_tools import TOOLS, gui_callbacks, steam_fixture
from resource_transaction import ResourceTransaction
import steam_to_legacy


def snapshot(directory):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in directory.iterdir() if p.is_file()}


def fail_publication(number, rollback=False):
    original = os.replace
    count = 0

    def replace(source, target):
        nonlocal count
        if Path(source).name.startswith("new-"):
            count += 1
            if count == number:
                raise PermissionError("injected publication failure")
        elif rollback and Path(source).name.startswith("old-"):
            raise PermissionError("injected rollback failure")
        return original(source, target)

    return patch("resource_transaction.os.replace", side_effect=replace)


class ResourcePreparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sdlpal-rollback-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def assert_clean(self, directory, expected):
        self.assertEqual(snapshot(directory), expected)
        self.assertEqual(list(directory.glob(".sdlpal-prepare-*")), [])

    def test_cli_word_failure_preserves_existing_and_missing_outputs(self):
        for encoding in ("gbk", "big5"):
            for existing in ((), ("M.MSG",), ("M.MSG", "WORD.DAT")):
                with self.subTest(encoding=encoding, existing=existing):
                    data = self.root / (encoding + str(len(existing)))
                    steam_fixture(data, encoding)
                    suffix = "chs" if encoding == "gbk" else "cht"
                    (data / f"WORD_{suffix}.txt").write_bytes("0:ABCDEFGHIJK\n".encode("utf-16-le"))
                    for name in existing:
                        (data / name).write_bytes(b"original " + name.encode())
                    before = snapshot(data)
                    result = subprocess.run([sys.executable, "-B", "-X", "utf8",
                                             str(TOOLS / "steam_to_legacy.py"), "all", str(data),
                                             str(data), encoding], capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assert_clean(data, before)

    def test_cli_publication_failure_restores_overwritten_and_removes_new_files(self):
        for existing in ((), ("M.MSG",), ("WORD.DAT",), ("M.MSG", "WORD.DAT")):
            with self.subTest(existing=existing):
                data = self.root / str(len(existing)) / ("-".join(existing) or "empty")
                data.parent.mkdir(exist_ok=True)
                steam_fixture(data)
                for name in existing:
                    (data / name).write_bytes(b"original " + name.encode())
                before = snapshot(data)
                with fail_publication(2), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(PermissionError, "publication"):
                        steam_to_legacy.convert_all(str(data), str(data), "gbk")
                self.assert_clean(data, before)

    def test_cli_success_replaces_pair_with_exact_bytes(self):
        for encoding in ("gbk", "big5"):
            data = self.root / encoding
            msg, word = steam_fixture(data, encoding)
            for name in ("M.MSG", "WORD.DAT"):
                (data / name).write_bytes(b"old")
            before = snapshot(data)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(steam_to_legacy.convert_all(str(data), str(data), encoding))
            self.assertEqual((data / "M.MSG").read_bytes(), msg)
            self.assertEqual((data / "WORD.DAT").read_bytes(), word)
            for name, contents in before.items():
                if name not in ("M.MSG", "WORD.DAT"):
                    self.assertEqual(snapshot(data)[name], contents)
            self.assertEqual(list(data.glob(".sdlpal-prepare-*")), [])

    def test_interrupt_after_os_replace_restores_already_published_file(self):
        original = os.replace
        for existing in (False, True):
            for position in (1, 2):
                with self.subTest(existing=existing, position=position):
                    data = self.root / f"{existing}-{position}"
                    steam_fixture(data)
                    if existing:
                        for name in ("M.MSG", "WORD.DAT"):
                            (data / name).write_bytes(b"old " + name.encode())
                    before = snapshot(data)
                    count = 0

                    def interrupted(source, target):
                        nonlocal count
                        original(source, target)
                        if Path(source).name.startswith("new-"):
                            count += 1
                            if count == position:
                                raise KeyboardInterrupt("after replacement completed")

                    with patch("resource_transaction.os.replace", side_effect=interrupted), \
                            contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaises(KeyboardInterrupt):
                            steam_to_legacy.convert_all(str(data), str(data), "gbk")
                    self.assert_clean(data, before)

    def test_preflight_backup_failure_changes_nothing(self):
        for name in ("M.MSG", "WORD.DAT"):
            (self.root / name).write_bytes(b"old " + name.encode())
        before = snapshot(self.root)
        original = shutil.copy2

        def copy(source, destination):
            if Path(source).name == "WORD.DAT":
                raise OSError("injected backup failure")
            return original(source, destination)

        with patch("resource_transaction.shutil.copy2", side_effect=copy):
            with self.assertRaisesRegex(OSError, "backup failure"):
                with ResourceTransaction(self.root) as transaction:
                    for name in before:
                        Path(transaction.stage(name)).write_bytes(b"new")
                    transaction.commit()
        self.assert_clean(self.root, before)

    def test_missing_staged_file_and_nonregular_target_publish_nothing(self):
        for mode in ("missing", "directory"):
            with self.subTest(mode=mode):
                data = self.root / mode
                data.mkdir()
                (data / "M.MSG").write_bytes(b"old")
                if mode == "directory":
                    (data / "WORD.DAT").mkdir()
                before = snapshot(data)
                with self.assertRaises((FileNotFoundError, ValueError)):
                    with ResourceTransaction(data) as transaction:
                        Path(transaction.stage("M.MSG")).write_bytes(b"new")
                        staged = Path(transaction.stage("WORD.DAT"))
                        if mode == "directory":
                            staged.write_bytes(b"new")
                        transaction.commit()
                self.assert_clean(data, before)

    def test_rollback_failure_retains_original_backup_and_recovery_manifest(self):
        (self.root / "M.MSG").write_bytes(b"original")
        with fail_publication(2, rollback=True):
            with self.assertRaisesRegex(RuntimeError, "rollback incomplete"):
                with ResourceTransaction(self.root) as transaction:
                    Path(transaction.stage("M.MSG")).write_bytes(b"new")
                    Path(transaction.stage("WORD.DAT")).write_bytes(b"new word")
                    transaction.commit()
        recovery = json.loads((transaction.staging / "recovery.json").read_text("utf-8"))
        self.assertEqual(Path(recovery["backups"]["M.MSG"]).read_bytes(), b"original")
        self.assertEqual(recovery["published"], ["M.MSG"])
        self.assertEqual(recovery["rollback_errors"][0]["name"], "M.MSG")
        self.assertFalse((self.root / "WORD.DAT").exists())

    def test_cleanup_failure_reports_remaining_temp_without_undoing_success(self):
        with patch("resource_transaction.shutil.rmtree", side_effect=PermissionError("busy")):
            with self.assertWarnsRegex(RuntimeWarning, "committed=True"):
                with ResourceTransaction(self.root) as transaction:
                    Path(transaction.stage("M.MSG")).write_bytes(b"new")
                    transaction.commit()
        self.assertEqual((self.root / "M.MSG").read_bytes(), b"new")
        self.assertTrue(transaction.staging.is_dir())

    def test_gui_publication_failures_remove_all_four_new_outputs(self):
        for position in range(1, 5):
            with self.subTest(position=position):
                data = self.root / str(position)
                steam_fixture(data)
                (data / "M_cht.msg").write_bytes(b"other encoding")
                (data / "existing.slf").write_bytes(b"keep language")
                before = snapshot(data)
                ui = gui_callbacks([], [])
                with fail_publication(position):
                    with self.assertRaisesRegex(PermissionError, "publication"):
                        ui["prepare_resources"](str(data), "gbk")
                self.assert_clean(data, before)

    def test_gui_existing_cache_copy_failure_preserves_cache_and_canonical_absence(self):
        (self.root / "m_ChS.MsG").write_bytes(b"existing messages")
        (self.root / "wOrD_ChS.DaT").write_bytes(b"existing words")
        before = snapshot(self.root)
        original = shutil.copyfile

        def copy(source, target):
            if Path(source).name.lower() == "word_chs.dat":
                raise OSError("injected cache copy failure")
            return original(source, target)

        with patch("shutil.copyfile", side_effect=copy):
            with self.assertRaisesRegex(OSError, "cache copy"):
                gui_callbacks([], [])["prepare_resources"](str(self.root), "gbk")
        self.assert_clean(self.root, before)

    def test_gui_word_failure_preserves_preexisting_canonical_or_cache(self):
        for existing in ("M.MSG", "M_chs.msg"):
            with self.subTest(existing=existing):
                data = self.root / existing
                steam_fixture(data)
                (data / existing).write_bytes(b"")  # Existing empty files still win.
                (data / "WORD_chs.txt").write_bytes("0:ABCDEFGHIJK\n".encode("utf-16-le"))
                before = snapshot(data)
                with self.assertRaisesRegex(RuntimeError, "word failed"):
                    gui_callbacks([], [])["prepare_resources"](str(data), "gbk")
                self.assert_clean(data, before)

    def test_gui_success_reuses_case_insensitive_caches_and_existing_canonical(self):
        (self.root / "m_ChS.MsG").write_bytes(b"cached msg")
        (self.root / "wOrD_ChS.DaT").write_bytes(b"cached word")
        before = snapshot(self.root)
        commands = []
        ui = gui_callbacks([], commands)
        ui["prepare_resources"](str(self.root), "gbk")
        self.assertEqual((self.root / "M.MSG").read_bytes(), b"cached msg")
        self.assertEqual((self.root / "WORD.DAT").read_bytes(), b"cached word")
        for name, contents in before.items():
            self.assertEqual(snapshot(self.root)[name], contents)
        before = snapshot(self.root)
        with patch("resource_transaction.tempfile.mkdtemp", side_effect=AssertionError("no staging needed")):
            ui["prepare_resources"](str(self.root), "big5")
        self.assert_clean(self.root, before)
        self.assertEqual(commands, [])

    def test_gui_new_target_appearing_during_preparation_is_not_overwritten(self):
        with self.assertRaises(FileExistsError):
            with ResourceTransaction(self.root, overwrite=False) as transaction:
                Path(transaction.stage("M.MSG")).write_bytes(b"prepared")
                (self.root / "M.MSG").write_bytes(b"appeared")
                transaction.commit()
        self.assertEqual((self.root / "M.MSG").read_bytes(), b"appeared")

    def test_gui_output_callback_failure_reaps_child_before_cleanup(self):
        steam_fixture(self.root / "input")
        data = self.root / "input"
        before = snapshot(data)
        ui = gui_callbacks([], [])
        children = []

        def popen(command, **kwargs):
            # A live child makes the cleanup ordering observable, independent
            # of how quickly the real converter finishes on a small fixture.
            child = subprocess.Popen([sys.executable, "-u", "-c",
                                      "import time; print('started'); time.sleep(30)"], **kwargs)
            children.append(child)
            return child

        def output(line):
            raise RuntimeError("injected UI callback failure")

        ui["subprocess"].Popen = popen
        ui["write_output"] = output
        with self.assertRaisesRegex(RuntimeError, "UI callback"):
            ui["prepare_resources"](str(data), "gbk")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assert_clean(data, before)

    def test_gui_reentry_and_input_changes_do_not_mix_batches_and_guard_releases(self):
        data = self.root / "input"
        msg, word = steam_fixture(data)
        messages, commands = [], []
        output = self.root / "no.slf"
        ui = gui_callbacks(messages, commands, pc_path=str(data), saturn_path=str(self.root),
                           output_path=str(output), pc_encoding="gbk")

        def on_output(line):
            messages.append(line)
            if line.startswith("Checking resources"):
                for name in ("pc_path", "saturn_path", "output_path", "pc_encoding"):
                    ui[name].get = lambda: "changed while processing events"
                ui["generate"]()

        ui["write_output"] = on_output
        ui["generate"]()
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[-1][-4:], [str(data), str(self.root), str(output), "gbk"])
        self.assertEqual((data / "M.MSG").read_bytes(), msg)
        self.assertEqual((data / "WORD.DAT").read_bytes(), word)
        self.assertIn("Generator failed", "".join(messages))  # Missing Saturn; preparation survives.
        self.assertFalse(ui["_generating"])
        ui["pc_path"].get = lambda: ""
        ui["generate"]()
        self.assertIn("Please select PC resource directory.", messages)
        self.assertFalse(ui["_generating"])

    def test_gui_post_commit_log_failure_is_not_reported_as_preparation_failure(self):
        data = self.root / "input"
        steam_fixture(data)
        messages, commands = [], []
        ui = gui_callbacks(messages, commands, pc_path=str(data), saturn_path=str(self.root),
                           output_path=str(self.root / "no.slf"), pc_encoding="gbk")

        def output(line):
            if line.startswith("PC Encoding:"):
                raise RuntimeError("post-commit log failure")
            messages.append(line)

        ui["write_output"] = output
        ui["generate"]()
        self.assertEqual(len(commands), 2)
        self.assertTrue((data / "M.MSG").exists())
        self.assertTrue((data / "WORD.DAT").exists())
        self.assertNotIn("Resource preparation failed", "".join(messages))
        self.assertIn("resources already prepared", "".join(messages))
        self.assertFalse(ui["_generating"])


if __name__ == "__main__":
    unittest.main()
