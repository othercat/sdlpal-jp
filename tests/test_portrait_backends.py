"""Reject mislabeled source-render evidence before checking its pixels."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/japanese"))
from verify_portrait_backends import check_backend


class BackendEvidence(unittest.TestCase):
    def fixture(self, backend="glsl2"):
        glsl = backend.startswith("glsl")
        record = {"backend": backend, "version": "win", "style": "adapted",
                  "portrait_sha256": "verified-pack",
                  "command": ["test.exe", "--render-evidence", "@config", "win.slf", "out",
                              "jp-portrait-effects" + ("-glsl" if glsl else ""), "win.por"]}
        log = "Renderer: opengl; flags=14; ScaleQuality=0; UseISOFont=0\n"
        if glsl:
            log += "GLSL evidence: vendor=test; renderer=test\n"
            log += f"GLSL evidence: compiled passes={backend[-1]}; preset=identity\n"
        return record, log

    def test_valid_single_and_double_pass_evidence(self):
        for backend in ("glsl1", "glsl2"):
            check_backend(*self.fixture(backend), backend, "win", "adapted")

    def test_native_output_cannot_be_renamed_as_glsl(self):
        record, log = self.fixture("sdl2")
        with self.assertRaisesRegex(ValueError, "label"):
            check_backend(record, log, "glsl2", "win", "adapted")

    def test_changed_label_alone_cannot_fake_shader_execution(self):
        record, _ = self.fixture()
        _, native_log = self.fixture("sdl2")
        with self.assertRaisesRegex(ValueError, "OpenGL"):
            check_backend(record, native_log, "glsl2", "win", "adapted")

    def test_wrong_pass_count_resource_version_and_portrait_setting_rejected(self):
        record, log = self.fixture()
        with self.assertRaisesRegex(ValueError, "shader count"):
            check_backend(record, log.replace("passes=2", "passes=1"), "glsl2", "win", "adapted")
        with self.assertRaisesRegex(ValueError, "label"):
            check_backend(record, log, "glsl2", "dos", "adapted")
        without_pack = copy.deepcopy(record)
        without_pack["command"].pop()
        with self.assertRaisesRegex(ValueError, "portrait setting"):
            check_backend(without_pack, log, "glsl2", "win", "adapted")


if __name__ == "__main__":
    unittest.main()
