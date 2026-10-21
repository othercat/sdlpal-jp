"""Check real Steam conversion and render sparse-ID evidence on local copies.

No game files are redistributed. Requires Python 3.11, Pillow, NumPy, the
pre-fix converter and a Test build with the steam-records evidence entry.
"""
import argparse
import csv
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SPECIAL = {"\ue010": b"\xaa\xb1", "\ue16d": b"\xad\xf4", "\ue47e": b"\xfe\xb7",
           "\ue4c7": b"\xa1\x41", "\ue4c9": b"\xa1\x43"}
SAMPLES = {"msg": (5, 6, 7, 8), "word": (36, 37, 149, 150)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def records(path):
    result = {}
    for line in path.read_bytes().decode("utf-16-le").removeprefix("\ufeff").splitlines():
        if line and not line.startswith(";"):
            key, value = line.split(":", 1)
            result[int(key)] = value
    return result


def encode(value, encoding):
    result = b""
    for char in value:
        if char in SPECIAL:
            result += SPECIAL[char]
        else:
            # CP950 is the documented extension for the traditional source.
            result += char.encode("cp950" if encoding == "big5" else encoding)
    return result


def expected_files(source, encoding):
    data = (source / "SSS.MKF").read_bytes()
    start, end = struct.unpack_from("<II", data, 12)
    offsets = struct.unpack(f"<{(end - start) // 4}I", data[start:end])
    suffix = "chs" if encoding == "gbk" else "cht"
    messages = records(source / f"MSG_{suffix}.txt")
    words = records(source / f"WORD_{suffix}.txt")
    msg = b"".join(encode(messages.get(i, ""), encoding).ljust(b - a, b" ")
                   for i, (a, b) in enumerate(zip(offsets, offsets[1:])))
    word = b"".join(encode(words.get(i, ""), encoding).ljust(10, b" ")
                    for i in range(max(words) + 1))
    require(len(msg) == offsets[-1], "Source message overflow")
    require(len(word) == (max(words) + 1) * 10, "Source word overflow")
    return {"M.MSG": msg, "WORD.DAT": word}, offsets


def run(command, log, cwd):
    with log.open("wb") as stream:
        result = subprocess.run(list(map(str, command)), cwd=cwd, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=120)
    require(result.returncode == 0, f"Command failed ({result.returncode}); see {log}")
    return {"argv": list(map(str, command)), "cwd": str(cwd), "exit_code": result.returncode,
            "log": str(log), "log_fingerprint": digest(log)}


def render(exe, source, converted, directory, encoding, expected, offsets):
    directory.mkdir()
    runtime = directory / "runtime"
    runtime.mkdir()
    resources = {}
    for path in source.iterdir():
        if path.suffix.lower() == ".mkf":
            shutil.copyfile(path, runtime / path.name)
            resources[path.name] = digest(path)
    for name, correct in expected.items():
        raw = (converted / name).read_bytes()
        require(len(raw) <= len(correct), "Unexpected oversized conversion")
        # Old sparse M.MSG is too short for the engine's unguarded SSS reads.
        # Pad only the EOF tail for this before-image fixture. All displayed
        # spans precede that tail: their wrong offsets are left untouched.
        (runtime / name).write_bytes(raw.ljust(len(correct), b" "))
    suffix = "chs" if encoding == "gbk" else "cht"
    shutil.copyfile(source / f"desc_{suffix}.dat", runtime / "desc.dat")
    result = run([exe, "--render-evidence", str(runtime) + "/", "-", directory,
                  "steam-records"], directory / "render.log", directory)
    rows = list(csv.DictReader((directory / "steam-records.csv").open(encoding="utf-8")))
    require([(r["kind"], int(r["id"])) for r in rows] ==
            [(kind, key) for kind, ids in SAMPLES.items() for key in ids], "Wrong render records")
    for row in rows:
        kind, key = row["kind"], int(row["id"])
        name = "M.MSG" if kind == "msg" else "WORD.DAT"
        start, end = offsets[key:key + 2] if kind == "msg" else (key * 10, (key + 1) * 10)
        raw = (converted / name).read_bytes()
        require(end <= len(raw), "Sample overlaps synthetic EOF padding")
        text = raw[start:end].decode("cp950" if encoding == "big5" else "gbk")
        if kind == "word":
            text = text.rstrip(" ").split("\0", 1)[0]
        loaded = "".join(chr(int(n, 16)) for n in row["codepoints"].split())
        require(loaded == text, f"Engine lookup mismatch: {kind} {key}")
    images = {}
    for kind in SAMPLES:
        base = Image.open(directory / f"steam-{kind}.bmp").convert("RGB")
        require(base.size == (320, 200), "Wrong base render dimensions")
        require(len(base.getcolors(64000) or []) > 2, "Blank source render")
        for width in (640, 960, 800):
            path = directory / f"steam-{kind}-{width}.bmp"
            scaled = Image.open(path).convert("RGB")
            require(scaled.size == (width, width * 5 // 8), "Wrong scale dimensions")
            if width in (640, 960):
                require(np.array_equal(np.array(scaled), np.array(base.resize(scaled.size,
                        Image.Resampling.NEAREST))), "Integer scale pixels differ")
            images[path.name] = digest(path)
    result.update({"resources": resources, "rendered_rows": rows,
                   "eof_padding_for_safe_before_render": {
                       name: len(data) - (converted / name).stat().st_size
                       for name, data in expected.items()}, "images": images})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("steam", type=Path)
    parser.add_argument("before_converter", type=Path)
    parser.add_argument("renderer", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source, before, exe, out = (p.resolve() for p in
                               (args.steam, args.before_converter, args.renderer, args.output))
    require(not out.exists() and not out.is_relative_to(source), "Use a fresh external output directory")
    out.mkdir(parents=True)
    inputs = {p.name: digest(p) for p in source.iterdir()
              if p.suffix.lower() in (".mkf", ".txt", ".dat")}
    after = ROOT / "tools/japanese/steam_to_legacy.py"
    record = {"inputs": inputs, "before_converter": digest(before), "after_converter": digest(after),
              "renderer": digest(exe), "verifier": digest(Path(__file__)), "cases": {}}
    for encoding in ("gbk", "big5"):
        expected, offsets = expected_files(source, encoding)
        suffix = "chs" if encoding == "gbk" else "cht"
        for case in ("complete", "sparse", "bom-first-id"):
            key = f"{encoding}-{case}"
            current = out / key
            current.mkdir()
            staging = current / "input"
            staging.mkdir()
            shutil.copyfile(source / "SSS.MKF", staging / "SSS.MKF")
            for kind in ("MSG", "WORD"):
                name = f"{kind}_{suffix}.txt"
                if case == "complete":
                    shutil.copyfile(source / name, staging / name)
                else:
                    lines = records(source / name)
                    if case == "sparse":
                        del lines[0]
                    text = "\ufeff" + "\n".join(f"{i}:{value}" for i, value in lines.items()) + "\n"
                    # In the sparse case retain a comment after the BOM so the
                    # before run isolates the missing ID, not BOM parsing too.
                    if case == "sparse":
                        text = "\ufeff; sparse copy: removed ID 0\n" + text[1:]
                    (staging / name).write_bytes(text.encode("utf-16-le"))
            wanted, _ = expected_files(staging, encoding)
            entry = {"input_copy": {p.name: digest(p) for p in staging.iterdir()}, "runs": {}}
            for version, converter in (("before", before), ("after", after)):
                target = current / version
                target.mkdir()
                command = [sys.executable, "-B", "-X", "utf8", converter, "all", staging, target, encoding]
                result = run(command, current / f"{version}.log", out)
                result["outputs"] = {name: digest(target / name) for name in wanted}
                matches = all((target / name).read_bytes() == data for name, data in wanted.items())
                require(matches == (version == "after" or case == "complete"),
                        f"Unexpected byte comparison: {key} {version}")
                result["matches_independent_layout"] = matches
                result["render"] = render(exe, source, target, current / f"{version}-render",
                                          encoding, wanted, offsets)
                entry["runs"][version] = result
            for kind in SAMPLES:
                before_image = Image.open(current / "before-render" / f"steam-{kind}.bmp").convert("RGB")
                after_image = Image.open(current / "after-render" / f"steam-{kind}.bmp").convert("RGB")
                changed = int(np.any(np.array(before_image) != np.array(after_image), axis=2).sum())
                require((changed == 0) == (case == "complete"), "Unexpected visual comparison")
                entry[f"{kind}_changed_pixels"] = changed
                if case != "complete":
                    reference = Image.open(out / f"{encoding}-complete" / "after-render" /
                                           f"steam-{kind}.bmp").convert("RGB")
                    require(np.array_equal(np.array(after_image), np.array(reference)),
                            "Surviving IDs differ from complete-source render")
            record["cases"][key] = entry
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 20)
    previews = out / "previews"
    previews.mkdir()
    for kind in SAMPLES:
        pair = Image.new("RGB", (1312, 460), "#ededed")
        draw = ImageDraw.Draw(pair)
        for column, version in enumerate(("before", "after")):
            x = 8 + column * 656
            draw.text((x, 8), "Before: sparse IDs shift text" if column == 0 else
                      "After: original IDs preserved", font=font, fill="#101010")
            panel = Image.open(out / "gbk-sparse" / f"{version}-render" /
                               f"steam-{kind}-640.bmp").convert("RGB")
            pair.paste(panel, (x, 44))
        path = previews / f"steam-sparse-{kind}.png"
        pair.save(path, optimize=True)
    require(inputs == {name: digest(source / name) for name in inputs}, "Original inputs changed")
    record["original_inputs_unchanged"] = True
    record["previews"] = {p.name: digest(p) for p in previews.iterdir()}
    record["limitations"] = ["Source record panels, not natural gameplay screenshots",
        "Before render pads only the truncated EOF tail; displayed spans never intersect it",
        "2x/3x pixels verified, 2.5x dimensions only", "No Japanese SLF is generated for this Steam edition",
        "CLI all/GUI preparation remain nontransactional; live acceptance deferred"]
    (out / "verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"cases": len(record["cases"]), "renders": len(record["cases"]) * 2,
                      "verification": str(out / "verification.json"), "previews": record["previews"]}))


if __name__ == "__main__":
    main()
