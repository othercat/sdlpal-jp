"""Verify Issue #2 rollback using real Steam copies and source-rendered panels.

Requires the pre-R3 tools directory, the R2 Test renderer, Pillow and NumPy.
Original game resources are read-only inputs and are never redistributed.
"""
import argparse
import contextlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from verify_steam_conversion import digest, expected_files, records, render, require
import steam_to_legacy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from test_japanese_conversion_tools import gui_callbacks
from test_resource_transaction import fail_publication


def fingerprints(directory):
    return {p.name: digest(p) for p in sorted(directory.iterdir()) if p.is_file()}


def write_inputs(source, target, encoding, faulty=False):
    target.mkdir()
    suffix = "chs" if encoding == "gbk" else "cht"
    for name in ("SSS.MKF", f"MSG_{suffix}.txt", f"WORD_{suffix}.txt"):
        shutil.copyfile(source / name, target / name)
    if faulty:
        name = f"MSG_{suffix}.txt"
        messages = records(target / name)
        require("１００" in messages[6], "Unexpected source for MSG 6")
        messages[6] = messages[6].replace("１００", "９００")
        (target / name).write_bytes(("\ufeff" + "\n".join(f"{i}:{text}" for i, text in messages.items())
                                    + "\n").encode("utf-16-le"))
        with (target / f"WORD_{suffix}.txt").open("ab") as stream:
            stream.write("\n0:ABCDEFGHIJK\n".encode("utf-16-le"))


def cli(converter, source, target, encoding, log, expected_exit):
    command = [sys.executable, "-B", "-X", "utf8", str(converter), "all", str(source), str(target), encoding]
    with log.open("wb") as stream:
        process = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, cwd=log.parent, timeout=120)
    require(process.returncode == expected_exit, f"Unexpected CLI exit; see {log}")
    return {"argv": command, "exit_code": process.returncode, "log": str(log),
            "log_fingerprint": digest(log), "outputs": fingerprints(target)}


def gui(script, source, encoding, log, failure=False):
    messages, commands = [], []
    ui = gui_callbacks(messages, commands, source=script, pc_path=str(source),
                       saturn_path=str(source.parent / "not-used-saturn"),
                       output_path=str(source / "existing.slf"), pc_encoding=encoding)
    if failure:
        ui["generate"]()
        require("Resource preparation failed" in "".join(messages), "GUI did not stop preparation")
        require(len(commands) == 2 and all("steam_to_legacy.py" in " ".join(c) for c in commands),
                "GUI unexpectedly launched the language generator")
    else:
        messages.extend(ui["prepare_resources"](str(source), encoding))
        require(len(commands) == 2, "Expected both real Steam converters")
    log.write_text("".join(messages), encoding="utf-8", newline="\n")
    return {"commands": commands, "log": str(log), "log_fingerprint": digest(log),
            "files_after": fingerprints(source), "tk_widgets": "headless test doubles"}


def pixels(path):
    return np.array(Image.open(path).convert("RGB"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("steam", type=Path)
    parser.add_argument("before_tools", type=Path)
    parser.add_argument("renderer", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source, before, exe, out = (p.resolve() for p in
                               (args.steam, args.before_tools, args.renderer, args.output))
    require(not out.exists() and not out.is_relative_to(source), "Use a new external output directory")
    out.mkdir(parents=True)
    inputs = {p.name: digest(p) for p in source.iterdir() if p.suffix.lower() in (".mkf", ".txt", ".dat")}
    tools = ROOT / "tools/japanese"
    record = {"date": "2026-10-21", "base": "e1a41d68215f3684f149ea94dbdeb25623e31c98",
              "inputs": inputs, "renderer": digest(exe), "before_tools": fingerprints(before),
              "sources": {str(p.relative_to(ROOT)): digest(p) for p in (
                  tools / "resource_transaction.py", tools / "steam_to_legacy.py", tools / "rungui.py",
                  Path(__file__), tools / "verify_steam_conversion.py",
                  ROOT / "tests/test_resource_transaction.py", ROOT / "tests/test_japanese_conversion_tools.py")},
              "cases": {}}
    for encoding in ("gbk", "big5"):
        expected, offsets = expected_files(source, encoding)
        suffix = "chs" if encoding == "gbk" else "cht"
        complete = out / (encoding + "-complete")
        complete.mkdir()
        write_inputs(source, complete / "input", encoding)
        source_before = fingerprints(complete / "input")
        case = {"runs": {}}
        for version, directory in (("before", before), ("after", tools)):
            target = complete / version
            target.mkdir()
            # Success must still replace both preexisting CLI output files.
            for name in expected:
                (target / name).write_bytes(b"preexisting " + name.encode())
            result = cli(directory / "steam_to_legacy.py", complete / "input", target,
                         encoding, complete / f"{version}.log", 0)
            require(all((target / name).read_bytes() == data for name, data in expected.items()),
                    "Complete CLI output differs from independent layout")
            require(not list(target.glob(".sdlpal-prepare-*")), "Staging files remain after success")
            result["render"] = render(exe, source, target, complete / f"{version}-render",
                                      encoding, expected, offsets)
            case["runs"][version] = result
        write_inputs(source, complete / "gui", encoding)
        gui_inputs = fingerprints(complete / "gui")
        case["gui"] = gui(tools / "rungui.py", complete / "gui", encoding, complete / "gui.log")
        for name, data in expected.items():
            cache = f"M_{suffix}.msg" if name == "M.MSG" else f"Word_{suffix}.dat"
            require((complete / "gui" / name).read_bytes() == data and
                    (complete / "gui" / cache).read_bytes() == data, "GUI output or cache differs")
        require(all(digest(complete / "gui" / name) == item for name, item in gui_inputs.items()),
                "GUI changed source inputs")
        require(not list((complete / "gui").glob(".sdlpal-prepare-*")), "GUI success left staging")
        require(fingerprints(complete / "input") == source_before, "CLI changed input copy")
        case["independent_full_file_match"] = True
        for kind in ("msg", "word"):
            require(np.array_equal(pixels(complete / "before-render" / f"steam-{kind}.bmp"),
                                   pixels(complete / "after-render" / f"steam-{kind}.bmp")),
                    "Successful preparation changed source-rendered pixels")
        case["success_changed_pixels"] = 0
        record["cases"][encoding + "-complete"] = case

        faulty = out / (encoding + "-word-failure")
        faulty.mkdir()
        write_inputs(source, faulty / "input", encoding, faulty=True)
        faulty_inputs = fingerprints(faulty / "input")
        case = {"injected_input_changes": ["MSG ID 6: fullwidth 100 -> 900", "WORD ID 0: 11-byte overflow"],
                "input_copy": faulty_inputs, "runs": {}}
        for version, directory in (("before", before), ("after", tools)):
            target = faulty / version
            target.mkdir()
            for name, data in expected.items():
                (target / name).write_bytes(data)
            previous = fingerprints(target)
            result = cli(directory / "steam_to_legacy.py", faulty / "input", target,
                         encoding, faulty / f"{version}.log", 1)
            preserved = fingerprints(target) == previous
            require(preserved == (version == "after"), "Unexpected CLI rollback result")
            require((target / "WORD.DAT").read_bytes() == expected["WORD.DAT"], "Old word file changed")
            raw = (target / "M.MSG").read_bytes()[offsets[6]:offsets[7]]
            wanted = "９００" if version == "before" else "１００"
            require(wanted in raw.decode("cp950" if encoding == "big5" else encoding), "Wrong retained message")
            require(not list(target.glob(".sdlpal-prepare-*")), "Failure left unexpected staging")
            result["existing_pair_preserved"] = preserved
            result["render"] = render(exe, source, target, faulty / f"{version}-render",
                                      encoding, expected, offsets)
            case["runs"][version] = result
            gui_source = faulty / (version + "-gui")
            shutil.copytree(faulty / "input", gui_source)
            (gui_source / "existing.slf").write_bytes(b"existing language file")
            other = "M_cht.msg" if encoding == "gbk" else "M_chs.msg"
            (gui_source / other).write_bytes(b"other encoding cache")
            previous = fingerprints(gui_source)
            result_gui = gui(directory / "rungui.py", gui_source, encoding, faulty / f"{version}-gui.log", True)
            require(all(digest(gui_source / name) == data for name, data in previous.items()),
                    "GUI failure changed an existing input, cache or SLF")
            additions = sorted(set(fingerprints(gui_source)) - set(previous))
            require(additions == (sorted(["M.MSG", f"M_{suffix}.msg"]) if version == "before" else []),
                    "Unexpected GUI partial outputs")
            require(not list(gui_source.glob(".sdlpal-prepare-*")), "GUI failure left staging")
            result_gui["partial_outputs"] = additions
            case["runs"][version]["gui"] = result_gui
        require(fingerprints(faulty / "input") == faulty_inputs, "Failure changed source input copy")
        for kind in ("msg", "word"):
            old = pixels(faulty / "before-render" / f"steam-{kind}.bmp")
            new = pixels(faulty / "after-render" / f"steam-{kind}.bmp")
            changed = int(np.any(old != new, axis=2).sum())
            require((changed > 0) == (kind == "msg"), "Unexpected rollback image difference")
            require(np.array_equal(new, pixels(complete / "after-render" / f"steam-{kind}.bmp")),
                    "Rollback render differs from preserved reference")
            case[kind + "_changed_pixels"] = changed
        record["cases"][encoding + "-word-failure"] = case

        # Inject an OS publication error after all real conversion work succeeds.
        for kind, position in (("cli", 2), ("gui", 4)):
            target = out / f"{encoding}-{kind}-publish-failure"
            write_inputs(source, target, encoding)
            if kind == "cli":
                for name in expected:
                    (target / name).write_bytes(b"old " + name.encode())
            previous = fingerprints(target)
            log = io.StringIO()
            try:
                with fail_publication(position), contextlib.redirect_stdout(log):
                    if kind == "cli":
                        steam_to_legacy.convert_all(str(target), str(target), encoding)
                    else:
                        messages = []
                        try:
                            gui_callbacks(messages, [])["prepare_resources"](str(target), encoding)
                        finally:
                            log.write("".join(messages))
            except PermissionError as failure:
                require("injected publication failure" in str(failure), "Unexpected publication error")
            else:
                raise ValueError("Publication failure was not raised")
            require(fingerprints(target) == previous, "Publication rollback did not restore original state")
            require(not list(target.glob(".sdlpal-prepare-*")), "Publication failure left staging")
            log_path = target.parent / (target.name + ".log")
            log_path.write_text(log.getvalue(), encoding="utf-8", newline="\n")
            record["cases"][target.name] = {"fail_at_publish": position, "original_state_restored": True,
                "files_before_and_after": previous, "log": str(log_path), "log_fingerprint": digest(log_path)}

    previews = out / "previews"
    previews.mkdir()
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 20)
    for case, kind, labels in (
        ("word-failure", "msg", ("Before: failed batch leaks 900", "After: original 100 preserved")),
        ("complete", "msg", ("Before: successful conversion", "After: identical messages")),
        ("complete", "word", ("Before: successful conversion", "After: identical names"))):
        pair = Image.new("RGB", (1312, 460), "#ededed")
        draw = ImageDraw.Draw(pair)
        for column, version in enumerate(("before", "after")):
            x = 8 + column * 656
            draw.text((x, 8), labels[column], font=font, fill="#101010")
            panel = Image.open(out / f"gbk-{case}" / f"{version}-render" / f"steam-{kind}-640.bmp").convert("RGB")
            pair.paste(panel, (x, 44))
        pair.save(previews / f"prepare-{case}-{kind}.png", optimize=True)
    require(inputs == {name: digest(source / name) for name in inputs}, "Original Steam resources changed")
    record["original_inputs_unchanged"] = True
    record["previews"] = fingerprints(previews)
    record["summary"] = {"cases": len(record["cases"]), "cli_subprocesses": 8,
        "gui_preparations": 8, "source_renders": 8, "rendered_records": 64,
        "base_panels": 16, "scaled_panels": 48}
    record["limitations"] = ["Controlled source record panels, not natural gameplay or Tk acceptance",
        "Failure fixture modifies working-copy MSG 6 and WORD 0 only; no translation change",
        "All rendered files retain full length; no EOF padding is used in this R3 verification",
        "2x/3x pixels exact; 2.5x dimensions only; GUI success files match CLI byte for byte",
        "Handled failures only: no crash/power-loss or concurrent-process transaction guarantee",
        "SLF generation is a separate later phase; no Steam-to-Japanese input certification",
        "All live acceptance deferred until the end"]
    (out / "verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8", newline="\n")
    print(json.dumps(record["summary"]))


if __name__ == "__main__":
    main()
