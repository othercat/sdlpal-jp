"""Verify the four Issue #6 R2 edits across raw Win/DOS/Saturn and both SLFs."""
import argparse
import json
import re
from pathlib import Path

from makemessage_dos import MANIFEST, read_dos
from verify_baseline import check_inputs, sha256, slf_summary
from verify_restored_dialogues import blocks, duplicates, groups, read_sources, require
from verify_translations import CONTROLS

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "docs/evidence/issue-6-followup-review.json"
TARGETS = {(12078, 12083), (2396, 2399), (3447, 3448), (7583, 7589)}
BEFORE_LF_SHA256 = {
    "win": "5672bfbfdbc913900b50e54af667c07dc11c1bb116216030b87359358c6e3b92",
    "dos": "6bf198b3027bdf84f2668e2659ac6feefeb7b9c755963a84b0d596770b89da5d",
}


def unchanged_except_bodies(before, after, replacements):
    """Preserve original newline bytes, section headers, order and every other byte."""
    newline = b"\r\n" if b"\r\n" in before else b"\n"
    pattern = re.compile(rb"(^\[BEGIN MESSAGE\] (\d+)\r?\n)(.*?)(^\[END MESSAGE\] (\d+)\r?$)",
                         re.M | re.S)
    seen = set()

    def replace(match):
        key = (int(match[2]), int(match[5]))
        if key not in replacements:
            return match[0]
        require(key not in seen, f"Duplicate followup target: {key}")
        seen.add(key)
        return match[1] + newline.join(t.encode("utf-8") for t in replacements[key]) + newline + match[4]

    require(pattern.sub(replace, before) == after and seen == set(replacements),
            "Output differs outside the four reviewed MESSAGE bodies")


def verify(win_dir, dos_dir, saturn_dir, before_dir, after_dir, output_dir):
    require(not output_dir.exists(), "Use a new verification directory")
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    inputs = {name: check_inputs(path, manifest["inputs"][name], name) for name, path in
              (("win", win_dir), ("dos", dos_dir), ("saturn", saturn_dir))}
    win, saturn = read_sources(inputs["win"], inputs["saturn"])
    sources = {"win": win, "dos": read_dos(inputs["dos"]), "saturn": saturn}
    scanned = {name: {g["script_start"]: g for g in groups(source, consecutive=name != "saturn")}
               for name, source in sources.items()}
    review = json.loads(REVIEW.read_text("utf-8"))
    pairs = review["groups"]
    require(len(pairs) == 4 and {tuple(p["win_key"]) for p in pairs} == TARGETS,
            "Incomplete four-group review")
    edits, commands, texts, summaries = {}, {}, {}, {}
    for version in ("win", "dos"):
        old_file, new_file = (directory / f"paljpn-{version}.slf" for directory in (before_dir, after_dir))
        require(slf_summary(old_file)["lf_sha256"] == BEFORE_LF_SHA256[version],
                f"Not the pinned post-Issue #7 {version} baseline")
        old, new = blocks(old_file), blocks(new_file)
        old_map, new_map = ({(a, b): lines for a, b, lines in rows} for rows in (old, new))
        count = 4766 if version == "win" else 4476
        require(len(old_map) == len(new_map) == count and old_map.keys() == new_map.keys() and
                set(new_map) == {(g["sid"], g["eid"]) for g in scanned[version].values()},
                f"{version} runtime coverage changed")
        require(duplicates(old) == duplicates(new) and not any(d["conflict"] for d in duplicates(new)),
                f"{version} duplicate conflict changed")
        edits[version], commands[version] = {}, {}
        for pair in pairs:
            for name, source in pair["sources"].items():
                actual = scanned[name].get(source["script_start"])
                require(actual == {k: source[k] for k in (
                    "script_start", "script_end", "sid", "eid", "ids", "text")},
                    f"Raw {name} source differs: {pair['win_key']}")
            key = tuple(pair["sources"][version][k] for k in ("sid", "eid"))
            replacement = pair["recommended_japanese"]
            require(pair["decision"] == "correct inherited Saturn translation in Win output and derived DOS bridge" and
                    pair["rationale"] and
                    old_map[key] == pair["before_japanese"] == pair["sources"]["saturn"]["text"],
                    f"Original Japanese or review differs: {key}")
            require(replacement != old_map[key] and new_map[key] == replacement and
                    len(replacement) == len(old_map[key]) and
                    all(t and "\ufffd" not in t and "\n" not in t for t in replacement) and
                    CONTROLS.findall("\n".join(replacement)) == CONTROLS.findall("\n".join(old_map[key])),
                    f"Replacement/control sequence differs: {key}")
            command = pair["render_commands"][version]
            if command["script"] is not None:
                require(list(sources[version]["scripts"][command["script"]]) == command["words"],
                        f"Raw render command changed: {key}")
            else:
                require(command["words"] == [60, 0, 0, 0] and
                        tuple(pair["win_key"]) in {(2396, 2399), (3447, 3448)},
                        "Unexpected default dialogue fixture")
            edits[version][key] = replacement
            commands[version][key] = command["words"]
        unchanged_except_bodies(old_file.read_bytes(), new_file.read_bytes(), edits[version])
        texts[version] = old_map, new_map
        summaries[version] = {
            "before": slf_summary(old_file), "after": slf_summary(new_file),
            "changed_keys": [list(k) for k in sorted(edits[version])],
            "unchanged_blocks": len(old) - 4, "unchanged_unique_keys": count - 4,
            "all_other_bytes_unchanged": True, "controls_and_line_counts_preserved": True,
            "duplicates": duplicates(new),
        }
    for pair in pairs:
        keys = {v: tuple(pair["sources"][v][k] for k in ("sid", "eid")) for v in ("win", "dos")}
        require(texts["win"][1][keys["win"]] == texts["dos"][1][keys["dos"]],
                "Win/DOS followup translations differ")
    for context in review["qing_name_evidence"]["contexts"]:
        for message in context.get("saturn_messages", []):
            require(saturn["messages"][message["id"]] == message["text"], "Queen name context differs")

    # Keep existing renderer coverage contracts: four edits + one Win witness,
    # and four edits + four DOS witnesses. No new product/render mode is needed.
    r1 = json.loads((ROOT / "docs/evidence/issue-6-translation-review.json").read_text("utf-8"))
    witness = next(p for p in r1["corrections"] if p["win"]["sid"] == 9207)
    c = witness["render_command"]
    require(list(win["scripts"][c["script"]]) == c["instruction"], "Win witness command changed")
    commands["win"][(9207, 9208)] = c["instruction"]
    for first in (0, 1741, 3296, 9449):
        row = next(r for r in manifest["groups"] if r["dos"][2] == first)
        command = row["render_command"]
        if command["script"] is not None:
            require(list(sources["dos"]["scripts"][command["script"]]) == command["words"],
                    "DOS witness command changed")
        commands["dos"][tuple(row["dos"][2:])] = command["words"]
    require((before_dir / "dos-objects.csv").read_bytes() == (after_dir / "dos-objects.csv").read_bytes() and
            (before_dir / "expected-descriptions.json").read_bytes() ==
            (after_dir / "expected-descriptions.json").read_bytes(),
            "DOS description fixtures/text changed")
    for files in inputs.values():
        for item in files.values():
            require(sha256(Path(item["path"])) == item["sha256"], "Input resource changed")
    output_dir.mkdir(parents=True)
    for version in ("win", "dos"):
        directory = output_dir / version
        directory.mkdir()
        old, new = texts[version]
        fixtures = [",".join(map(str, [*key, len(old[key]), len(new[key]), int(key in commands[version]),
                    *commands[version].get(key, [60, 0, 0, 0])])) for key in sorted(new)]
        (directory / "recovery-fixtures.csv").write_text("\n".join(fixtures) + "\n", "ascii")
    (output_dir / "win/translation-objects.csv").write_text("\n".join(
        f"{o['id']},{int(o['kind'] == 'item')}" for o in r1["render_objects"]) + "\n", "ascii")
    (output_dir / "dos/dos-objects.csv").write_bytes((after_dir / "dos-objects.csv").read_bytes())
    report = {
        "scope": "Four reviewed groups, no full-script or gameplay acceptance.",
        "inputs": inputs, "inputs_unchanged": True, "review_sha256": sha256(REVIEW),
        "versions": summaries, "four_translations_equal_across_versions": True,
        "description_text_unchanged": True,
        "render_keys": {v: [list(k) for k in sorted(commands[v])] for v in commands},
    }
    (output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("win_dir", "dos_dir", "saturn_dir", "before_dir", "after_dir", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        verify(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, IndexError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print("PASS: four Win/DOS edits, original sources and all other SLF bytes verified")
