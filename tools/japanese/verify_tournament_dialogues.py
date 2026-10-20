"""Verify the ten Issue #4 replacements against raw sources and a reviewed record."""
import argparse
import json
import re
import struct
from pathlib import Path

from verify_baseline import METADATA, check_inputs, sha256, slf_summary
from verify_restored_dialogues import blocks, duplicates, groups, read_sources, require


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/evidence/issue-4-dialogue-review.json"
BEFORE_LF_SHA256 = "210f9e5772062c19b6af7e1f589288f2809c8d997dc9ed9d47780afad8c25027"
TARGETS = {(2714, 2715), (2716, 2717), (2718, 2719), (2720, 2722), (2723, 2726),
           (2860, 2861), (2862, 2863), (2864, 2867), (2868, 2871), (2872, 2874)}


def verify(pc_dir, saturn_dir, before, after, output_dir):
    require(not output_dir.exists(), "Use a new verification directory")
    baseline = json.loads(METADATA.read_text("utf-8"))["baseline"]
    inputs = {
        "pc": check_inputs(pc_dir, baseline["pc_resource_sha256"], "Win",
                           baseline["unsupported_dos_sss_sha256"]),
        "saturn": check_inputs(saturn_dir, baseline["saturn_resource_sha256"], "Saturn"),
    }
    require(slf_summary(before)["lf_sha256"] == BEFORE_LF_SHA256,
            "Before SLF is not the pinned post-Issue #3 output")
    win, jp = read_sources(inputs["pc"], inputs["saturn"])
    runtime = groups(win, consecutive=True)
    win_groups = {g["script_start"]: g for g in runtime}
    jp_groups = {g["script_start"]: g for g in groups(jp)}
    review = json.loads(REVIEW.read_text("utf-8"))
    pairs = review["pairs"]
    require(len(pairs) == 10 and {(p["win"]["sid"], p["win"]["eid"]) for p in pairs} == TARGETS,
            "Review must cover exactly the ten Issue #4 keys")
    old, new = blocks(before), blocks(after)
    old_map = {(first, last): text for first, last, text in old}
    new_map = {(first, last): text for first, last, text in new}
    expected_bodies, correct_keys = {}, set()
    sss = Path(inputs["pc"]["sss.mkf"]["path"]).read_bytes()
    offsets = struct.unpack_from("<6I", sss)
    events = list(struct.iter_unpack("<16H", sss[offsets[0]:offsets[1]]))
    scenes = list(struct.iter_unpack("<4H", sss[offsets[1]:offsets[2]]))
    for pair in pairs:
        w, j = pair["win"], pair["incorrect_saturn_source"]
        key = (w["sid"], w["eid"])
        require(win_groups.get(w["script_start"]) == w, f"Win source differs: {key}")
        require(jp_groups.get(j["script_start"]) == j, f"Incorrect Saturn source differs: {key}")
        require(old_map.get(key) == j["text"], f"Before text differs: {key}")
        require(pair["translation_source"] == "new_translation_from_win",
                f"Replacement must identify its actual source: {key}")
        text = pair["replacement"]
        require(text and all(line and "\ufffd" not in line and "\n" not in line for line in text),
                f"Empty or invalid replacement: {key}")
        require(text[0].endswith("：") and len(text) > 1, f"Missing speaker or dialogue: {key}")
        require(not any(c in line for line in text for c in "[]\\'@\"()-"),
                f"Unreviewed SLF or dialogue control in replacement: {key}")
        require(new_map.get(key) == text and text != j["text"], f"Replacement differs: {key}")
        expected_bodies[key] = text
        actual_events = [n + 1 for n, event in enumerate(events) if event[4] == w["script_start"]]
        require(actual_events == [e["event"] for e in pair["event_context"]],
                f"Event reference set differs: {key}")
        for context in pair["event_context"]:
            event, scene = events[context["event"] - 1], scenes[context["scene"] - 1]
            require(scene[0] == context["map"] and scene[1] == context["scene_entry"] and
                    scene[3] < context["event"] <= scenes[context["scene"]][3] and
                    event[4] == context["trigger"], f"Event/scene anchor differs: {key}")
        require(pair["render_command"]["script"] is None and
                pair["render_command"]["instruction"] == [0x003c, 0, 0, 0] and
                win["scripts"][w["script_start"]][0] == 0xffff,
                f"Expected direct event entry/default upper dialogue: {key}")
        for original in pair["valid_win_uses_of_same_saturn_text"]:
            original = tuple(original)
            require(original not in TARGETS and old_map.get(original) == j["text"] and
                    new_map.get(original) == j["text"], f"Correct original NPC changed: {original}")
            correct_keys.add(original)

    # Replace only reviewed MESSAGE bodies in the pinned input. Full byte equality
    # also protects comments, settings, descriptions, order and duplicate blocks.
    before_bytes = before.read_bytes()
    newline = b"\r\n" if b"\r\n" in before_bytes else b"\n"
    seen = set()
    pattern = re.compile(rb"(^\[BEGIN MESSAGE\] (\d+)\r?\n)(.*?)(^\[END MESSAGE\] (\d+)\r?$)",
                         re.M | re.S)

    def replace(match):
        key = (int(match[2]), int(match[5]))
        if key not in TARGETS:
            return match[0]
        require(key not in seen, f"Duplicate target block: {key}")
        seen.add(key)
        body = newline.join(line.encode("utf-8") for line in expected_bodies[key]) + newline
        return match[1] + body + match[4]

    expected = pattern.sub(replace, before_bytes)
    require(seen == TARGETS and after.read_bytes() == expected,
            "Output differs outside the ten reviewed MESSAGE body replacements")
    require(len(old) == len(new) == 4773 and len(new_map) == 4766,
            "Message coverage count changed")
    require(set(new_map) == {(g["sid"], g["eid"]) for g in runtime},
            "Output keys differ from raw Win runtime keys")
    require(duplicates(old) == duplicates(new), "Existing duplicate/conflict set changed")
    recovered = json.loads((ROOT / "docs/evidence/issue-3-dialogue-review.json").read_text("utf-8"))
    for pair in recovered["pairs"]:
        key = (pair["win"]["sid"], pair["win"]["eid"])
        require(new_map[key] == pair["jp"]["text"], f"Issue #3 recovered group changed: {key}")
    require(len(recovered["pairs"]) == 119 and len(correct_keys) == 5,
            "Incomplete adjacent/recovered coverage")
    fixtures = []
    for key in sorted(new_map):
        fields = [*key, len(old_map[key]), len(new_map[key]), int(key in TARGETS), 0x003c, 0, 0, 0]
        fixtures.append(",".join(map(str, fields)))
    for category in inputs.values():
        for record in category.values():
            require(sha256(Path(record["path"])) == record["sha256"], "Source input changed")
    report = {
        "scope": "Ten reviewed Win-based translations; source/engine checks, not gameplay acceptance.",
        "inputs": inputs, "inputs_unchanged": True, "review_sha256": sha256(REVIEW),
        "before": slf_summary(before), "after": slf_summary(after),
        "changed_keys": [list(k) for k in sorted(TARGETS)],
        "changed_win_ids": sum(last - first + 1 for first, last in TARGETS),
        "unchanged_blocks": len(new) - len(TARGETS), "unchanged_unique_keys": len(new_map) - len(TARGETS),
        "all_other_bytes_unchanged": True, "recovered_119_groups_unchanged": True,
        "correct_original_npc_keys_unchanged": [list(k) for k in sorted(correct_keys)],
        "duplicates_unchanged": duplicates(new), "engine_fixture_keys": len(fixtures),
        "rendered_groups": len(TARGETS),
    }
    output_dir.mkdir(parents=True)
    (output_dir / "recovery-fixtures.csv").write_text("\n".join(fixtures) + "\n", "ascii")
    (output_dir / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pc_dir", "saturn_dir", "before", "after", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        result = verify(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: 10 corrected groups; {result['unchanged_blocks']} other blocks and all other bytes unchanged")


if __name__ == "__main__":
    main()
