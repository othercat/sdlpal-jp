"""Check Issue #3 against raw Win/Saturn scripts, then prepare engine probes."""
import argparse
import collections
import json
import re
import struct
from pathlib import Path

from verify_baseline import METADATA, check_inputs, sha256, slf_summary


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/evidence/issue-3-dialogue-review.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_sources(pc, saturn):
    sss = Path(pc["sss.mkf"]["path"]).read_bytes()
    begin, end, stop = struct.unpack_from("<3I", sss, 12)
    offsets = [v[0] for v in struct.iter_unpack("<I", sss[begin:end])]
    raw = Path(pc["m.msg"]["path"]).read_bytes()
    win = {
        "scripts": list(struct.iter_unpack("<4H", sss[end:stop])),
        "messages": [raw[a:b].decode("gbk", "replace") for a, b in zip(offsets, offsets[1:])],
    }
    prog = Path(saturn["PROG.BIN"]["path"]).read_bytes()
    offsets, wrap = [], 0
    for (value,) in struct.iter_unpack(">H", prog[358868:393212]):
        if offsets and value + wrap < offsets[-1]:
            wrap += 65536
        offsets.append(value + wrap)
    raw = Path(saturn["JM.MSG"]["path"]).read_bytes().replace(b"\0", b"")
    scripts = b"".join(Path(saturn[n]["path"]).read_bytes() for n in ("JM.SEC", "JM.NOR"))
    jp = {
        "scripts": list(struct.iter_unpack(">4H", scripts)),
        "messages": [raw[a:b].decode("shift_jis") for a, b in zip(offsets, offsets[1:])],
    }
    return win, jp


def groups(source, consecutive=False):
    """Independently scan raw FFFF/008E sequences, including runtime ID splits."""
    result, pos = [], 0
    scripts = source["scripts"]
    while pos < len(scripts):
        if scripts[pos][0] != 0xffff:
            pos += 1
            continue
        start, ids, text = pos, [], []
        while pos < len(scripts):
            op, first, _, _ = scripts[pos]
            if op == 0xffff and (not consecutive or not ids or first == ids[-1] + 1):
                ids.append(first)
                text.append(source["messages"][first])
            elif op == 0x008e:
                text.append("[CLEAR MESSAGE]")
            else:
                break
            pos += 1
        result.append({"script_start": start, "script_end": pos - 1,
                       "ids": ids, "text": text, "sid": ids[0], "eid": ids[-1]})
    return result


def blocks(path):
    text = path.read_text("utf-8")
    return [(int(s), int(e), body.splitlines()) for s, body, e in re.findall(
        r"^\[BEGIN MESSAGE\] (\d+)\n(.*?)^\[END MESSAGE\] (\d+)$", text, re.M | re.S)]


def duplicates(rows):
    bykey = collections.defaultdict(list)
    for first, last, text in rows:
        bykey[first, last].append(text)
    return [{"key": list(key), "count": len(texts),
             "conflict": len({tuple(t) for t in texts}) > 1}
            for key, texts in bykey.items() if len(texts) > 1]


def verify(pc_dir, saturn_dir, before, after, output_dir):
    require(not output_dir.exists(), "Use a new verification directory")
    baseline = json.loads(METADATA.read_text("utf-8"))["baseline"]
    inputs = {
        "pc": check_inputs(pc_dir, baseline["pc_resource_sha256"], "Win",
                           baseline["unsupported_dos_sss_sha256"]),
        "saturn": check_inputs(saturn_dir, baseline["saturn_resource_sha256"], "Saturn"),
    }
    require(slf_summary(before)["lf_sha256"] == baseline["slf"]["lf_sha256"],
            "Before SLF is not the pinned upstream output")
    require(after.read_bytes().startswith(before.read_bytes()),
            "Existing output was changed; Issue #3 must only append recovered groups")
    suffix = after.read_bytes()[before.stat().st_size:].decode("utf-8").replace("\r\n", "\n")
    remainder = re.sub(r"^\[BEGIN MESSAGE\] \d+\n.*?^\[END MESSAGE\] \d+$",
                       "", suffix, flags=re.M | re.S)
    require(all(not line.strip() or line.startswith("#") for line in remainder.splitlines()),
            "Unexpected content outside recovered MESSAGE blocks")
    win, jp = read_sources(inputs["pc"], inputs["saturn"])
    runtime = groups(win, consecutive=True)
    jp_groups = {g["script_start"]: g for g in groups(jp)}
    win_groups = {g["script_start"]: g for g in runtime}
    old, new = blocks(before), blocks(after)
    old_map = {(s, e): text for s, e, text in old}
    new_map = {(s, e): text for s, e, text in new}
    missing_before = [g for g in runtime if (g["sid"], g["eid"]) not in old_map]
    review = json.loads(REVIEW.read_text("utf-8"))
    require(len(review["pairs"]) == len(missing_before) == 119, "Unexpected omitted group set")
    expected = []
    for pair in review["pairs"]:
        for label, source in (("win", win_groups), ("jp", jp_groups)):
            anchor = pair[label]
            require(source.get(anchor["script_start"]) == anchor,
                    f"{label} source differs at script {anchor['script_start']}")
        w, j = pair["win"], pair["jp"]
        require(not any("\ufffd" in text for text in w["text"] + j["text"]),
                f"Recovery source has a decoding replacement: {w['sid']}")
        require(pair["mapping_review"] == "confirmed", f"Unreviewed mapping: {w['sid']}")
        command = pair.get("render_command")
        if command and command["script"] is not None:
            require(list(win["scripts"][command["script"]]) == command["instruction"],
                    f"Render dialogue command differs: {w['sid']}")
        expected.append((w["sid"], w["eid"], j["text"]))
    require(new[:len(old)] == old and new[len(old):] == expected,
            "Recovered output order, text or CLEAR markers differ from reviewed sources")
    require({(s, e) for s, e, _ in expected} ==
            {(g["sid"], g["eid"]) for g in missing_before}, "Recovery keys differ from missing keys")
    require(len(new_map) == len(old_map) + 119, "New duplicate mapping key")
    require(duplicates(old) == duplicates(new), "Existing duplicate/conflict set changed")
    missing_after = [g for g in runtime if (g["sid"], g["eid"]) not in new_map]
    require(not missing_after, "Runtime message ranges still missing")
    require(set(new_map) == {(g["sid"], g["eid"]) for g in runtime},
            "Output contains a key outside the Win runtime ranges")
    recovered_jp = {i for pair in review["pairs"] for i in pair["jp"]["ids"]}
    for excluded in review["other_unselected_saturn"]:
        actual = jp_groups[excluded["script_start"]]
        require(actual["ids"] == excluded["ids"], "Excluded Saturn source changed")
        require(recovered_jp.isdisjoint(actual["ids"]), "Extra Saturn-only group imported")
    # Fixtures are generated from the independently checked SLFs. Probe every
    # runtime key via PAL_GetMsgNum; draw only the reviewed representative groups.
    selected = {tuple(p["win"][k] for k in ("sid", "eid")): p["render_command"]
                for p in review["pairs"] if "render_command" in p}
    fixtures = []
    for key in sorted(new_map):
        command = selected.get(key)
        fields = [*key, len(old_map.get(key, [])), len(new_map[key]), int(command is not None),
                  *(command["instruction"] if command else [0x003c, 0, 0, 0])]
        fixtures.append(",".join(map(str, fields)))
    require(len(fixtures) == 4766, "Unexpected engine probe count")
    for group in inputs.values():
        for record in group.values():
            require(sha256(Path(record["path"])) == record["sha256"], "Source input changed")
    report = {
        "scope": "Static mapping/content and engine fixture preparation; no gameplay acceptance.",
        "inputs": inputs, "inputs_unchanged": True, "review_sha256": sha256(REVIEW),
        "win_decode_replacements_full_source": sum(t.count("\ufffd") for t in win["messages"]),
        "recovered_source_decode_replacements": 0,
        "before": slf_summary(before), "after": slf_summary(after),
        "original_output_byte_prefix_unchanged": True,
        "runtime_groups": len(runtime), "unique_runtime_keys": len(new_map),
        "missing_before": len(missing_before), "missing_after": missing_after,
        "restored_groups": len(expected),
        "restored_win_ids": len({i for p in review["pairs"] for i in p["win"]["ids"]}),
        "restored_jp_ids": len(recovered_jp),
        "restored_clear_markers": sum(t == "[CLEAR MESSAGE]" for _, _, ts in expected for t in ts),
        "existing_duplicates_unchanged": duplicates(new),
        "other_saturn_groups_not_imported": review["other_unselected_saturn"],
        "engine_fixture_keys": len(fixtures), "rendered_representatives": len(selected),
    }
    output_dir.mkdir(parents=True)
    (output_dir / "recovery-fixtures.csv").write_text("\n".join(fixtures) + "\n", "ascii")
    (output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pc_dir", "saturn_dir", "before", "after", "output_dir"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        result = verify(**vars(args))
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: {result['restored_groups']} groups restored; "
          f"{result['missing_before']} -> 0 missing; original blocks/conflicts unchanged")


if __name__ == "__main__":
    main()
