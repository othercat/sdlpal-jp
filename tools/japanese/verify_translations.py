"""Verify Issue #6 source review, exact body edits and renderer fixtures."""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from verify_baseline import METADATA, check_inputs, sha256, slf_summary
from verify_restored_dialogues import blocks, duplicates, groups, read_sources, require


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/evidence/issue-6-translation-review.json"
BEFORE_LF_SHA256 = "a1012dbd24be730118274c56b87d1ad2fd3b0ed689c8090f69badfaa55ec58b0"
TARGETS = {(1, 4), (9207, 9208), (9211, 9212), (9324, 9325), (12053, 12056),
           (12660, 12661), (12920, 12921), (12945, 12946), (13436, 13436),
           (13438, 13439), (13442, 13443), (13444, 13445), (13453, 13454),
           (13455, 13456), (13457, 13457), (13466, 13467), (13468, 13468), (13469, 13469)}
DIALOGUES = {key for key in TARGETS if key[0] < 12300}
CONTROLS = re.compile(r"\[CLEAR MESSAGE\]|[$~]\d{2}|\\.|[-'@\"()]")


def verify(pc_dir, saturn_dir, before, after, output_dir):
    require(not output_dir.exists(), "Use a new verification directory")
    metadata = json.loads(METADATA.read_text("utf-8"))["baseline"]
    inputs = {
        "pc": check_inputs(pc_dir, metadata["pc_resource_sha256"], "Win",
                           metadata["unsupported_dos_sss_sha256"]),
        "saturn": check_inputs(saturn_dir, metadata["saturn_resource_sha256"], "Saturn"),
    }
    require(slf_summary(before)["lf_sha256"] == BEFORE_LF_SHA256,
            "Before SLF is not the pinned post-Issue #8 output")
    win, jp = read_sources(inputs["pc"], inputs["saturn"])
    wg = {g["script_start"]: g for g in groups(win, consecutive=True)}
    jg = {g["script_start"]: g for g in groups(jp)}
    old, new = blocks(before), blocks(after)
    old_map = {(s, e): t for s, e, t in old}
    new_map = {(s, e): t for s, e, t in new}
    review = json.loads(REVIEW.read_text("utf-8"))
    pairs = review["corrections"]
    require(len(pairs) == len(TARGETS) and
            {(p["win"]["sid"], p["win"]["eid"]) for p in pairs} == TARGETS,
            "Incomplete reviewed correction set")
    expected_bodies, commands = {}, {}
    sss = Path(inputs["pc"]["sss.mkf"]["path"]).read_bytes()
    offsets = struct.unpack_from("<6I", sss)
    objects = list(struct.iter_unpack("<7H", sss[offsets[2]:offsets[3]]))
    for pair in pairs:
        w, j = pair["win"], pair["saturn"]
        key = (w["sid"], w["eid"])
        require(wg.get(w["script_start"]) == w and jg.get(j["script_start"]) == j,
                f"Raw source group differs: {key}")
        require(old_map[key] == j["text"], f"Before text differs: {key}")
        text = pair["replacement"]
        require(text != j["text"] and all(line and "\ufffd" not in line and "\n" not in line for line in text),
                f"Empty, undecodable or unchanged replacement: {key}")
        require(CONTROLS.findall("\n".join(text)) == CONTROLS.findall("\n".join(j["text"])),
                f"Control sequence changed: {key}")
        require(new_map[key] == text, f"Reviewed translation differs: {key}")
        require(pair["reason"] and pair["decision"] == "correct", f"Missing review decision: {key}")
        expected_bodies[key] = text
        if key in DIALOGUES:
            command = pair["render_command"]
            if command["script"] is not None:
                require(list(win["scripts"][command["script"]]) == command["instruction"],
                        f"Dialog command differs: {key}")
            else:
                require(key == (12053, 12056) and command["instruction"] == [60, 0, 0, 0],
                        "Unexpected synthesized dialog command")
            commands[key] = command["instruction"]
        else:
            obj = pair["object"]
            require(list(objects[obj["id"]]) == obj["raw"] and
                    obj["raw"][5] == w["script_start"] - 1 and
                    win["scripts"][w["script_start"] - 1][0] == 0x00a7,
                    f"Object/description anchor differs: {key}")
    # Whole-file equality protects every unreviewed block, comment and setting.
    raw = before.read_bytes()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    pattern = re.compile(rb"(^\[BEGIN MESSAGE\] (\d+)\r?\n)(.*?)(^\[END MESSAGE\] (\d+)\r?$)",
                         re.M | re.S)
    seen = set()

    def replace(match):
        key = (int(match[2]), int(match[5]))
        if key not in TARGETS:
            return match[0]
        require(key not in seen, f"Duplicate correction target: {key}")
        seen.add(key)
        return match[1] + newline.join(s.encode("utf-8") for s in expected_bodies[key]) + newline + match[4]

    require(pattern.sub(replace, raw) == after.read_bytes() and seen == TARGETS,
            "Output differs outside reviewed MESSAGE bodies")
    require(len(old) == len(new) == 4773 and len(new_map) == 4766 and
            set(new_map) == {(g["sid"], g["eid"]) for g in wg.values()},
            "Win runtime mapping coverage changed")
    require(duplicates(old) == duplicates(new) and not any(d["conflict"] for d in duplicates(new)),
            "Duplicate key set changed or conflict reintroduced")
    preserved = []
    for number, field in ((3, "jp"), (4, "replacement")):
        prior = json.loads((ROOT / f"docs/evidence/issue-{number}-dialogue-review.json").read_text("utf-8"))
        for pair in prior["pairs"]:
            key = (pair["win"]["sid"], pair["win"]["eid"])
            if key in TARGETS:
                continue
            expected = pair[field]["text"] if number == 3 else pair[field]
            require(new_map[key] == expected, f"Unreviewed Issue #{number} text changed: {key}")
            preserved.append([number, *key])
    for retained in review["retained"]:
        key = tuple(retained["key"])
        require(retained["decision"] == "retain" and retained["reason"] and
                old_map[key] == new_map[key] == retained["text"],
                f"Retained review item differs: {key}")
    fixtures = [
        ",".join(map(str, [*key, len(old_map[key]), len(new_map[key]), int(key in DIALOGUES),
                          *commands.get(key, [60, 0, 0, 0])]))
        for key in sorted(new_map)
    ]
    menu_objects = review["render_objects"]
    require(len({o["id"] for o in menu_objects}) == len(menu_objects), "Duplicate menu fixture")
    for obj in menu_objects:
        require(list(objects[obj["id"]]) == obj["raw"], "Menu object differs")
    require({p["object"]["id"] for p in pairs if "object" in p} <= {o["id"] for o in menu_objects},
            "Corrected description missing from render fixtures")
    battle_path = REVIEW.parent / review["battle_review"]
    battle = json.loads(battle_path.read_text("utf-8"))
    require(battle["revision_count"] == 11 and len(battle["entries"]) == 17,
            "Incomplete battle review")
    checked_scripts = set()
    for entry in battle["entries"]:
        w, j = entry["win"], entry["saturn"]
        key = w["sid"], w["eid"]
        require(wg[w["script_start"]] == w and jg[j["script_start"]] == j and
                list(objects[entry["object_id"]]) == entry["object_raw_words"],
                f"Battle resource anchor differs: {key}")
        expected = entry["proposed_text"] or entry["baseline_slf_text"]
        require(new_map[key] == expected, f"Battle review translation differs: {key}")
        for instruction in entry["script_instructions"]:
            require(list(win["scripts"][instruction["script"]]) == instruction["words"],
                    f"Battle effect script differs: {instruction['script']}")
            checked_scripts.add(instruction["script"])
    for name, digest in battle["engine_lf_sha256"].items():
        actual = hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        require(actual == digest, f"Reviewed engine behavior changed: {name}")
    check_inputs(pc_dir, {"data.mkf": battle["inputs"]["data_mkf"]["sha256"]}, "Win mechanics")
    for category in inputs.values():
        for item in category.values():
            require(sha256(Path(item["path"])) == item["sha256"], "Source input changed")
    result = {
        "scope": "Reviewed sample only; not a complete script review or gameplay acceptance.",
        "inputs": inputs, "inputs_unchanged": True, "review_sha256": sha256(REVIEW),
        "before": slf_summary(before), "after": slf_summary(after),
        "changed_keys": [list(k) for k in sorted(TARGETS)], "unchanged_blocks": len(old) - len(TARGETS),
        "unchanged_unique_keys": len(new_map) - len(TARGETS), "all_other_bytes_unchanged": True,
        "controls_preserved": True, "duplicates": duplicates(new),
        "prior_groups_preserved": preserved, "engine_fixture_keys": len(fixtures),
        "dialogue_render_groups": len(DIALOGUES), "description_render_objects": len(menu_objects),
        "battle_review_sha256": sha256(battle_path), "battle_effect_scripts": sorted(checked_scripts),
        "battle_code_fingerprints_match": True,
    }
    output_dir.mkdir(parents=True)
    (output_dir / "recovery-fixtures.csv").write_text("\n".join(fixtures) + "\n", "ascii")
    (output_dir / "translation-objects.csv").write_text("\n".join(
        f"{o['id']},{int(o['kind'] == 'item')}" for o in menu_objects) + "\n", "ascii")
    (output_dir / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pc_dir", "saturn_dir", "before", "after", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        result = verify(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, IndexError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: {len(result['changed_keys'])} corrected groups; all other SLF bytes preserved")
