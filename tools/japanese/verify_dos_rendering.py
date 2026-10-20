"""Run the Test-only DOS source renderer, validate lookups, and export opaque PNGs."""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops

from verify_baseline import sha256
from verify_restored_dialogues import blocks, require


def codepoints(value):
    return "".join(chr(int(c, 16)) for c in value.split())


def verify(executable, generated, dos_dir, win_dir, output_dir):
    executable, generated, dos_dir, win_dir, output_dir = (
        p.resolve() for p in (executable, generated, dos_dir, win_dir, output_dir))
    require(not output_dir.exists(), "Use a new render output directory")
    require(all(p.is_file() for p in (executable, generated / "generation.json")), "Missing generated inputs")
    inputs = [p for directory in (dos_dir, win_dir) for p in directory.iterdir()
              if p.is_file() and p.suffix.lower() in (".mkf", ".msg", ".dat", ".rpg", ".fon", ".asc")]
    digests = {str(p): sha256(p) for p in inputs}
    output_dir.mkdir(parents=True)
    runs = []
    for name, mode, slf, resources, expected_exit in (
        ("wrong-win", "dos-before", "audit-wrong-win.slf", dos_dir, 0),
        ("dos", "dos", "paljpn-dos.slf", dos_dir, 0),
        ("old-layout", "dos-layout-before", "paljpn-dos.slf", dos_dir, 0),
        ("reject-win-on-dos", "dos", "paljpn-win.slf", dos_dir, 1),
        ("reject-dos-on-win", "jp-translation", "paljpn-dos.slf", win_dir, 1),
    ):
        directory = output_dir / name
        directory.mkdir()
        for fixture in ("recovery-fixtures.csv", "dos-objects.csv"):
            shutil.copyfile(generated / fixture, directory / fixture)
        command = [str(executable), "--render-evidence", str(resources) + "/",
                   str(generated / slf), str(directory), mode]
        process = subprocess.run(command, cwd=output_dir, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=120)
        log = process.stdout + process.stderr
        (directory / "render.log").write_text(log, "utf-8")
        require(process.returncode == expected_exit, f"{name}: exit {process.returncode}\n{log}")
        if expected_exit:
            require("Cannot load game text" in log, f"{name}: failed for an unrelated reason\n{log}")
        runs.append({"name": name, "command": command, "exit_code": process.returncode, "log": log})
        print(name, log.strip(), flush=True)
    actual = {}
    with (output_dir / "dos/effective-text.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = int(row["first"]), int(row["last"])
            lines = actual.setdefault(key, [])
            require(int(row["order"]) == len(lines), "Engine message order changed")
            lines.append("[CLEAR MESSAGE]" if row["codepoints"] == "CLEAR" else codepoints(row["codepoints"]))
    expected = {tuple(r["key"]): r["text"] for r in json.loads(
        (generated / "expected-text.json").read_text("utf-8"))}
    require(actual == expected and len(actual) == 4476, "DOS engine lookup differs from reviewed text")
    wrong_map = {(s, e): text for s, e, text in blocks(generated / "audit-wrong-win.slf")}
    wrong_actual = {}
    with (output_dir / "wrong-win/effective-text.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = int(row["first"]), int(row["last"])
            wrong_actual.setdefault(key, []).append(
                "[CLEAR MESSAGE]" if row["codepoints"] == "CLEAR" else codepoints(row["codepoints"]))
    require(wrong_actual == {key: wrong_map[key] for key in expected if key in wrong_map},
            "Wrong-version baseline does not reflect the actual engine lookup")
    require(wrong_actual[(0, 0)] != actual[(0, 0)], "Expected key-0 collision not reproduced")
    description_expected = {int(k): "*".join(lines) for k, lines in json.loads(
        (generated / "expected-descriptions.json").read_text("utf-8")).items()}
    descriptions = {}
    for name in ("dos", "old-layout"):
        with (output_dir / name / "dos-descriptions.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        require({int(r["object_id"]): codepoints(r["codepoints"]) for r in rows} == description_expected,
                "Object description lookup differs from expected hexadecimal IDs/text")
        descriptions[name] = {
            "objects": len(rows), "drawn": sum(int(r["drawn"]) for r in rows),
            "overflow_ink": sum(int(r["overflow_ink"]) for r in rows),
            "clipped_objects": [int(r["object_id"]) for r in rows if int(r["overflow_ink"])],
            "production_menu_ink_assertions": "passed for all 10 rendered menus",
        }
    require(descriptions["dos"]["overflow_ink"] == 0 and descriptions["dos"]["objects"] == 296,
            "DOS descriptions still clip")
    require(descriptions["old-layout"]["clipped_objects"] == [306, 370, 374, 377, 394] and
            descriptions["old-layout"]["overflow_ink"] > 0, "Legacy clipping was not reproduced")
    png_dir = output_dir / "png"
    png_dir.mkdir()
    images, scales = [], []
    for stage in ("wrong-win", "dos", "old-layout"):
        for bmp in sorted((output_dir / stage).glob("*-640.bmp")):
            stem = bmp.stem[:-4]
            with Image.open(bmp) as source:
                rgb = source.convert("RGB")
                require(rgb.size == (640, 400), "Unexpected source render dimensions")
                filename = stage + "-" + stem + ".png"
                png = png_dir / filename
                rgb.save(png, optimize=True)
            with Image.open(png) as restored:
                require(restored.mode == "RGB" and "transparency" not in restored.info and
                        ImageChops.difference(rgb, restored).getbbox() is None,
                        "PNG pixels or opacity changed")
            with Image.open(bmp.with_name(stem + ".bmp")) as small:
                small = small.convert("RGB")
                require(ImageChops.difference(rgb, small.resize((640, 400), Image.Resampling.NEAREST)).getbbox() is None,
                        "2x GPU rendering differs from the source framebuffer")
                for width in (800, 960):
                    with Image.open(bmp.with_name(stem + f"-{width}.bmp")) as scaled:
                        # 2.5x nearest uses SDL's pixel-center rule; compare the
                        # supported integral scale exactly and record both sizes.
                        require(scaled.size == (width, width * 5 // 8), "Bad GPU output dimensions")
                        if width == 960:
                            require(ImageChops.difference(scaled.convert("RGB"),
                                small.resize(scaled.size, Image.Resampling.NEAREST)).getbbox() is None,
                                "3x GPU rendering differs from source")
            images.append({"file": "png/" + filename, "sha256": sha256(png), "bytes": png.stat().st_size,
                           "mode": "RGB", "size": [640, 400], "unique_colors": len(rgb.getcolors(256) or [])})
            scales.append({"stage": stage, "stem": stem, "2x_3x_exact": True, "2_5x_dimensions": [800, 500]})
    require(all(sha256(Path(path)) == digest for path, digest in digests.items()), "A source resource changed")
    report = {
        "scope": "Source engine lookup/rendering only; no game route or interactive acceptance.",
        "executable_sha256": sha256(executable), "generation_sha256": sha256(generated / "generation.json"),
        "resource_sha256": digests, "resources_unchanged": True, "runs": runs,
        "dos_keys": len(actual), "dos_entries": sum(map(len, actual.values())), "all_effective_text_matches": True,
        "wrong_win_present": len(wrong_actual), "wrong_win_missing": len(actual) - len(wrong_actual),
        "descriptions": descriptions, "images": images, "scales": scales,
    }
    (output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "generated", "dos_dir", "win_dir", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        result = verify(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: {result['dos_keys']} DOS keys, 296 descriptions, {len(result['images'])} opaque PNGs")
