"""Render Issue #6 R2 Win/DOS before/after SLFs using the existing Test engine."""
import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

from verify_baseline import sha256
from verify_restored_dialogues import blocks, require
from verify_translation_followup import REVIEW, ROOT

sys.path.insert(0, str(ROOT / "tools"))
from export_japanese_font import load_glyphs
from export_recovery_previews import export_preview, opaque_rgb


def pages(lines, command):
    op, face, _, _ = command
    lower = op == 61
    title_x = (4 if face else 12) if lower else (80 if face else 12)
    body_x = (20 if face else 44) if lower else (96 if face else 44)
    title_y, body_y = (108, 126) if lower else (8, 26)
    result, rows, count, title = [], [], 0, None
    for text in lines:
        if text == "[CLEAR MESSAGE]" or count == 4:
            result.append(rows)
            rows, count = ([title] if title else []), 0
            if text == "[CLEAR MESSAGE]":
                continue
        if count == 0 and text.endswith("："):
            title = (text, title_x, title_y, 0x8c)
            rows.append(title)
        else:
            rows.append((re.sub(r"[$~]\d{2}|[()]", "", text), body_x, body_y + count * 18, 0x4f))
            count = 0 if "~" in text else count + 1
    return result + [rows]


def verify(executable, win_dir, dos_dir, before_dir, after_dir, verification_dir, output_dir):
    executable, win_dir, dos_dir, before_dir, after_dir, verification_dir, output_dir = (
        p.resolve() for p in (executable, win_dir, dos_dir, before_dir, after_dir, verification_dir, output_dir))
    require(not output_dir.exists(), "Use a new rendering directory")
    static = json.loads((verification_dir / "verification.json").read_text("utf-8"))
    require(static["review_sha256"] == sha256(REVIEW), "Review changed after static verification")
    review = json.loads(REVIEW.read_text("utf-8"))
    maps = {}
    for version in ("win", "dos"):
        for stage, directory in (("before", before_dir), ("after", after_dir)):
            slf = directory / f"paljpn-{version}.slf"
            require(sha256(slf) == static["versions"][version][stage]["sha256"], "Verified SLF changed")
            maps[version, stage] = {(a, b): t for a, b, t in blocks(slf)}
    glyphs = load_glyphs(ROOT, win_dir, {
        ord(c) for pair in review["groups"] for field in ("before_japanese", "recommended_japanese")
        for line in pair[field] for c in line})
    resources = {str(p): sha256(p) for directory in (win_dir, dos_dir) for p in directory.iterdir()
                 if p.is_file() and p.suffix.lower() in (".mkf", ".msg", ".dat", ".rpg", ".fon", ".asc")}
    output_dir.mkdir(parents=True)
    png_dir = output_dir / "png"
    png_dir.mkdir()
    runs, checks, images, differences, scales = [], [], [], [], []
    page_rows = {}

    def ink(text, left, top, color, picture=None):
        points, count, x = set(), 0, left
        for character in text:
            width, pixels, origin = glyphs[ord(character)]
            require(width > 0 and (pixels or character.isspace()), f"Missing glyph: {character}/{origin}")
            for dx, dy in pixels:
                point = x + dx, top + dy
                require(0 <= point[0] < 320 and 0 <= point[1] < 200, f"Clipped text: {text}")
                if picture is not None:
                    require(picture.getpixel(point) == color, f"Missing/covered ink: {text} at {point}")
                points.add(point)
            count += len(pixels)
            x += width
        return points, {"text": text, "characters": len(text), "ink": count,
                        "left": left, "top": top, "right_exclusive": x}

    for version, resources_dir in (("win", win_dir), ("dos", dos_dir)):
        for stage, generated in (("before", before_dir), ("after", after_dir)):
            directory = output_dir / f"{version}-{stage}"
            directory.mkdir()
            for fixture in (verification_dir / version).glob("*.csv"):
                shutil.copyfile(fixture, directory / fixture.name)
            mode = ("jp-translation-before" if stage == "before" else "jp-translation") if version == "win" else "dos"
            # DOS edits preserve entry counts, so its current mode loads both fixtures exactly.
            command = [str(executable), "--render-evidence", str(resources_dir) + "/",
                       str(generated / f"paljpn-{version}.slf"), str(directory), mode]
            process = subprocess.run(command, cwd=output_dir, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=120)
            log = process.stdout + process.stderr
            (directory / "render.log").write_text(log, "utf-8")
            require(process.returncode == 0, f"{version}/{stage} renderer failed:\n{log}")
            actual = {}
            with (directory / "effective-text.csv").open(newline="") as stream:
                for row in csv.DictReader(stream):
                    key = int(row["first"]), int(row["last"])
                    lines = actual.setdefault(key, [])
                    require(int(row["order"]) == len(lines), "Engine text order changed")
                    lines.append("[CLEAR MESSAGE]" if row["codepoints"] == "CLEAR" else
                                 "".join(chr(int(v, 16)) for v in row["codepoints"].split()))
            require(actual == maps[version, stage], "Engine text does not equal verified SLF")
            with (directory / "recovery.csv").open(newline="") as stream:
                lookup = {int(r["first"]): r for r in csv.DictReader(stream)}
            for pair in review["groups"]:
                key = tuple(pair["sources"][version][k] for k in ("sid", "eid"))
                expected = pages(actual[key], pair["render_commands"][version]["words"])
                require(int(lookup[key[0]]["pages"]) == len(expected), "Unexpected dialogue pagination")
                require(int(lookup[key[0]]["page_waits"]) == len(expected) - 1, "Page/CLEAR wait changed")
                for page, lines in enumerate(expected, 1):
                    name = f"dialogue-{key[0]}-page-{page}"
                    page_rows[version, stage, name] = lines
                    with Image.open(directory / (name + ".bmp")) as picture:
                        rows = [ink(*line, picture=picture)[1] for line in lines]
                    checks.append({"version": version, "stage": stage, "file": name + ".bmp", "lines": rows})
                    image = export_preview(directory / (name + "-640.bmp"),
                                           png_dir / f"{version}-{stage}-{name}.png")
                    with Image.open(png_dir / image["file"]) as picture:
                        for background in ("white", "#181818"):
                            blended = Image.alpha_composite(Image.new("RGBA", picture.size, background),
                                                            picture.convert("RGBA"))
                            require(blended.convert("RGB").tobytes() == picture.tobytes(), "Transparent PNG")
                    images.append(image)
            # All scaled views, including the unchanged witness menus.
            for small in directory.glob("*.bmp"):
                if re.search(r"-(640|800|960)\.bmp$", small.name):
                    continue
                source = opaque_rgb(small)
                for width in (640, 960, 800):
                    scaled = opaque_rgb(small.with_name(small.stem + f"-{width}.bmp"))
                    require(scaled.size == (width, width * 5 // 8), "Unexpected scale dimensions")
                    if width != 800:
                        require(scaled.tobytes() == source.resize(scaled.size, Image.Resampling.NEAREST).tobytes(),
                                "Integral GPU scale differs")
                scales.append({"version": version, "stage": stage, "view": small.stem,
                               "2x_3x_exact": True, "2_5x_dimensions_only": True})
            clip_name, clip_column = ("description-clipping.csv", "clipped_ink") if version == "win" else (
                "dos-descriptions.csv", "overflow_ink")
            with (directory / clip_name).open(newline="") as stream:
                clipping = list(csv.DictReader(stream))
            require(all(int(row[clip_column]) == 0 for row in clipping), "Description clipping regression")
            runs.append({"version": version, "stage": stage, "command": command, "exit_code": process.returncode,
                         "log": log, "keys": len(actual), "entries": sum(map(len, actual.values())),
                         "description_probe_rows": len(clipping), "clipped_ink": 0})
            print(f"{version}/{stage}: {len(actual)} keys; dialogue ink, pagination and scales passed", flush=True)
        before, after = output_dir / f"{version}-before", output_dir / f"{version}-after"
        require({p.name for p in before.glob("*.bmp")} == {p.name for p in after.glob("*.bmp")},
                "Before/after image set differs")
        for path in before.glob("*.bmp"):
            if re.search(r"-(640|800|960)\.bmp$", path.name):
                continue
            a, b = opaque_rgb(path), opaque_rgb(after / path.name)
            bounds = ImageChops.difference(a, b).getbbox()
            allowed = set()
            if (version, "before", path.stem) in page_rows:
                old, new = (page_rows[version, stage, path.stem] for stage in ("before", "after"))
                require(len(old) == len(new), "Line count changed within page")
                for old_line, new_line in zip(old, new):
                    if old_line != new_line:
                        for line in (old_line, new_line):
                            points, _ = ink(*line)
                            allowed.update((x + dx, y + dy) for x, y in points
                                           for dx, dy in ((0, 0), (1, 0), (1, 1)))
            require(bool(bounds) == bool(allowed), f"Missing or unexpected visual change: {path.name}")
            if bounds:
                require(all((x, y) in allowed for y in range(bounds[1], bounds[3])
                            for x in range(bounds[0], bounds[2]) if a.getpixel((x, y)) != b.getpixel((x, y))),
                        "Pixels changed outside corrected glyphs/shadows")
            differences.append({"version": version, "file": path.name, "changed_bounds": bounds,
                                "only_corrected_glyphs_and_shadows_changed": True})
    require(all(sha256(Path(p)) == digest for p, digest in resources.items()), "Resource input changed")
    report = {
        "scope": "Existing Test engine source renders; no natural game-route acceptance.",
        "binary_sha256": sha256(executable), "review_sha256": sha256(REVIEW),
        "resources": resources, "resources_unchanged": True, "runs": runs,
        "glyph_checks": checks, "images": images, "scales": scales, "pixel_changes": differences,
    }
    (output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "win_dir", "dos_dir", "before_dir", "after_dir", "verification_dir", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        report = verify(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: {len(report['images'])} opaque before/after PNGs; all changed glyphs and controls verified")
