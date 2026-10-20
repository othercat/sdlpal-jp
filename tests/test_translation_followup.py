"""Protect non-target SLF bytes and the newly reviewed source anchors."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/japanese"))
from makemessage_j import TRANSLATION_FOLLOWUPS, corrected_translation
from verify_translation_followup import unchanged_except_bodies


class TranslationFollowup(unittest.TestCase):
    def test_only_reviewed_body_may_change_with_original_newlines(self):
        for newline in (b"\n", b"\r\n"):
            before = newline.join((b"# keep", b"[BEGIN MESSAGE] 1", b"old",
                                   b"[END MESSAGE] 2", b"[BEGIN MESSAGE] 3",
                                   b"unreviewed", b"[END MESSAGE] 3", b""))
            after = before.replace(b"old", "修訂".encode())
            unchanged_except_bodies(before, after, {(1, 2): ["修訂"]})
            for bad in (after.replace(b"# keep", b"# changed"),
                        after.replace(b"unreviewed", b"different"),
                        after.replace(newline, b"\r\n" if newline == b"\n" else b"\n", 1)):
                with self.subTest(newline=newline, bad=bad):
                    with self.assertRaisesRegex(ValueError, "outside the four"):
                        unchanged_except_bodies(before, bad, {(1, 2): ["修訂"]})

    def test_missing_or_duplicate_target_is_rejected(self):
        before = b"[BEGIN MESSAGE] 1\nold\n[END MESSAGE] 2\n"
        with self.assertRaisesRegex(ValueError, "outside the four"):
            unchanged_except_bodies(before, before, {(3, 3): ["new"]})
        with self.assertRaisesRegex(ValueError, "Duplicate followup target"):
            unchanged_except_bodies(before * 2, before.replace(b"old", b"new") * 2, {(1, 2): ["new"]})

    def test_followup_anchors_and_original_bodies_cannot_drift(self):
        for key, record in TRANSLATION_FOLLOWUPS.items():
            anchors, body = record[:4], "\n".join(record[4]) + "\n"
            self.assertEqual(corrected_translation(key, *anchors, body), "\n".join(record[5]) + "\n")
            for index in range(4):
                changed = list(anchors)
                changed[index] += 1
                with self.subTest(key=key, anchor=index):
                    with self.assertRaisesRegex(ValueError, "Issue #6 source differs"):
                        corrected_translation(key, *changed, body)
            with self.subTest(key=key, body=True):
                with self.assertRaisesRegex(ValueError, "Issue #6 source differs"):
                    corrected_translation(key, *anchors, body.replace("：", ":", 1))


if __name__ == "__main__":
    unittest.main()
