"""Verify Issue #8 source anchors and only two changed MESSAGE bodies."""
import argparse
import collections
import json
import re
import struct
from pathlib import Path

from verify_baseline import METADATA, check_inputs, sha256, slf_summary
from verify_restored_dialogues import blocks, duplicates, groups, read_sources, require


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/evidence/issue-8-source-review.json"
BEFORE_LF_SHA256 = "c2fb3ad19f91da5306074f66fde09c62aa049fb7a9bc0589575fde1dad520849"
TARGETS = {(4931, 4931), (4932, 4933), (4934, 4935), (5107, 5108),
           (12352, 12352), (12368, 12368)}
CANONICAL_JP = {(12352, 12352): 15746, (12368, 12368): 15762}


def verify(pc_dir, saturn_dir, before, after, output_dir):
    require(not output_dir.exists(), "Use a new verification directory")
    baseline = json.loads(METADATA.read_text("utf-8"))["baseline"]
    inputs = {
        "pc": check_inputs(pc_dir, baseline["pc_resource_sha256"], "Win",
                           baseline["unsupported_dos_sss_sha256"]),
        "saturn": check_inputs(saturn_dir, baseline["saturn_resource_sha256"], "Saturn"),
    }
    require(slf_summary(before)["lf_sha256"] == BEFORE_LF_SHA256,
            "Before SLF is not the pinned post-Issue #4 output")
    win, jp = read_sources(inputs["pc"], inputs["saturn"])
    runtime = groups(win, consecutive=True)
    jp_groups = {g["script_start"]: g for g in groups(jp)}
    review = json.loads(REVIEW.read_text("utf-8"))
    require(len(review["keys"]) == 6 and {tuple(r["key"]) for r in review["keys"]} == TARGETS,
            "Review must cover exactly the six reused keys")
    old, new = blocks(before), blocks(after)
    old_map = {(s, e): text for s, e, text in old}
    new_map = {(s, e): text for s, e, text in new}
    sss = Path(inputs["pc"]["sss.mkf"]["path"]).read_bytes()
    offsets = struct.unpack_from("<6I", sss)
    events = list(struct.iter_unpack("<16H", sss[offsets[0]:offsets[1]]))
    scenes = list(struct.iter_unpack("<4H", sss[offsets[1]:offsets[2]]))
    checked_scripts, checked_events, direct_events, dynamic_events = set(), set(), set(), set()

    def anchors(value, source, label):
        if isinstance(value, list):
            for child in value:
                anchors(child, source, label)
        elif isinstance(value, dict):
            if "script" in value and "raw" in value:
                require(list(source["scripts"][value["script"]]) == value["raw"],
                        f"{label} instruction differs: {value['script']}")
                checked_scripts.add((label, value["script"]))
            if "event" in value and "raw" in value:
                event, scene = events[value["event"] - 1], scenes[value["scene"] - 1]
                require(list(event) == value["raw"] and scene[0] == value["map"] and
                        scene[1] == value["scene_on_enter"] and scene[2] == value["scene_on_teleport"] and
                        scene[3] < value["event"] <= scenes[value["scene"]][3],
                        f"Event/scene differs: {value['event']}")
                checked_events.add(value["event"])
            for child in value.values():
                anchors(child, source, label)

    canonical, uses, message_ids = {}, 0, set()
    for record in review["keys"]:
        key = tuple(record["key"])
        raw_uses = [g for g in runtime if (g["sid"], g["eid"]) == key]
        require(raw_uses == [u["group"] for u in record["win_uses"]],
                f"Win use set differs: {key}")
        uses += len(raw_uses)
        message_ids.update(range(key[0], key[1] + 1))
        actual_blocks = [{"zero_based_block_index": i, "text": text}
                         for i, (s, e, text) in enumerate(old) if (s, e) == key]
        require(actual_blocks == record["before_slf_blocks"], f"Before occurrences differ: {key}")
        for use in record["win_uses"]:
            chain = use["call_chain"]
            anchors(chain, win, "Win")
            if chain["kind"] == "initial_event_trigger":
                actual = [n + 1 for n, e in enumerate(events) if e[4] == chain["trigger_entry"]]
                require(actual == [e["event"] for e in chain["events"]],
                        f"Direct event set differs: {key}")
                direct_events.update(actual)
                require(win["scripts"][use["group"]["script_start"] - 1] == (0x003e, 0, 0, 0),
                        f"Acquisition dialog command differs: {key}")
            else:
                dynamic_events.add(chain["event"]["event"])
        for item in record["saturn_sources"]:
            group = item["group"]
            require(jp_groups.get(group["script_start"]) == group, f"Saturn source differs: {key}")
            anchors(item["context"], jp, "Saturn")
            if key in CANONICAL_JP and group["sid"] == CANONICAL_JP[key]:
                canonical[key] = group["text"]
    anchors(review["dispatch_context"], win, "Win")
    require(uses == 13 and len(direct_events) == 16 and len(dynamic_events) == 5,
            "Incomplete reused-script/event coverage")
    require(sum(op == 0xffff and mid in message_ids for op, mid, _, _ in win["scripts"]) == 20,
            "Raw FFFF reference count changed")
    require(set(canonical) == set(CANONICAL_JP), "Missing existing Saturn acquisition source")

    # Compare the entire file, including comments/settings, not only parsed blocks.
    raw = before.read_bytes()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    occurrences, changed = collections.Counter(), []
    pattern = re.compile(rb"(^\[BEGIN MESSAGE\] (\d+)\r?\n)(.*?)(^\[END MESSAGE\] (\d+)\r?$)",
                         re.M | re.S)

    def replace(match):
        key = (int(match[2]), int(match[5]))
        if key not in canonical:
            return match[0]
        occurrences[key] += 1
        body = newline.join(line.encode("utf-8") for line in canonical[key]) + newline
        if body != match[3]:
            changed.append(list(key))
        return match[1] + body + match[4]

    expected = pattern.sub(replace, raw)
    require(occurrences == collections.Counter({key: 2 for key in CANONICAL_JP}) and
            sorted(changed) == [list(k) for k in sorted(CANONICAL_JP)] and
            after.read_bytes() == expected, "Output differs outside the two acquisition bodies")
    require(len(old) == len(new) == 4773 and len(new_map) == 4766 and
            set(new_map) == {(g["sid"], g["eid"]) for g in runtime}, "Runtime key coverage changed")
    require(duplicates(new) == [dict(d, conflict=False) for d in duplicates(old)] and
            {tuple(d["key"]) for d in duplicates(new)} == TARGETS,
            "Unexpected duplicate set or conflicting text")
    for number, field in ((3, "jp"), (4, "replacement")):
        name = f"issue-{number}-dialogue-review.json"
        for pair in json.loads((ROOT / "docs/evidence" / name).read_text("utf-8"))["pairs"]:
            key = (pair["win"]["sid"], pair["win"]["eid"])
            text = pair[field]["text"] if number == 3 else pair[field]
            require(new_map[key] == text, f"Issue #{number} text changed: {key}")
    fixtures = []
    for key in sorted(new_map):
        # Guards have no explicit dialog command on the reviewed event path:
        # use the engine's upper/no-portrait default; acquisitions use actual 003e.
        op = 0x003e if key in CANONICAL_JP else 0x003c
        fields = [*key, len(old_map[key]), len(new_map[key]), int(key in TARGETS), op, 0, 0, 0]
        fixtures.append(",".join(map(str, fields)))
    for category in inputs.values():
        for record in category.values():
            require(sha256(Path(record["path"])) == record["sha256"], "Source input changed")
    result = {
        "scope": "Two acquisition bodies normalized to existing Saturn text; no gameplay acceptance.",
        "inputs": inputs, "inputs_unchanged": True, "review_sha256": sha256(REVIEW),
        "before": slf_summary(before), "after": slf_summary(after),
        "changed_bodies": changed, "unchanged_blocks": 4771, "unchanged_effective_keys": 4764,
        "all_other_bytes_unchanged": True, "issue3_and_issue4_text_unchanged": True,
        "duplicates_before": duplicates(old), "duplicates_after": duplicates(new),
        "raw_use_groups": uses, "raw_FFFF_references": 20,
        "direct_pickup_events": sorted(direct_events), "dynamic_guard_events": sorted(dynamic_events),
        "checked_event_records": sorted(checked_events), "checked_script_anchors": sorted(checked_scripts),
        "canonical": [{"key": list(k), "jp_message": CANONICAL_JP[k], "text": canonical[k]}
                      for k in sorted(canonical)],
        "engine_fixture_keys": len(fixtures), "prepared_render_groups": 6,
    }
    output_dir.mkdir(parents=True)
    (output_dir / "recovery-fixtures.csv").write_text("\n".join(fixtures) + "\n", "ascii")
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pc_dir", "saturn_dir", "before", "after", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        result = verify(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: 2 corrected bodies; {result['unchanged_blocks']} blocks and all other bytes unchanged")


if __name__ == "__main__":
    main()
