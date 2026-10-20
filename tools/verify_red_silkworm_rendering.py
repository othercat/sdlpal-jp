"""Compare original/adapted Win SLFs with the real engine and the glyph audit.

Requires the existing SDL2 Test renderer, owned game resources, audit layout JSON
and Pillow. Writes evidence to a new directory, without replacing input files.
"""
import argparse
import copy
import csv
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageChops

from adapt_red_silkworm_description import ADAPTED, ORIGINAL, adapt
from collect_render_evidence import sha256
from verify_description_layout import verify


def collect(executable, resources, original, adapted, layout, output):
    repo = Path(__file__).resolve().parents[1]
    if adapted.read_bytes() != adapt(original.read_bytes()):
        raise ValueError("Adapted SLF must contain exactly the guarded line-break change")
    objects = json.loads(layout.read_text("utf-8"))
    if len(objects) != 296 or sum(len(obj["lines"]) for obj in objects) != 793:
        raise ValueError("Expected the complete 296-object / 793-line audit")
    updated = copy.deepcopy(objects)
    target = [obj for obj in updated if obj["object_id"] == 149]
    if len(target) != 1 or tuple(row["line"] for row in target[0]["lines"]) != ORIGINAL:
        raise ValueError("Unexpected original object-149 audit rows")
    for row, line in zip(target[0]["lines"], ADAPTED):
        row["line"] = line
        row["width"] = len(line) * 16  # This guarded description is entirely full-width.
        row["ending_x"] = row["x"] + row["width"]
        row["screen_overflow"] = row["ending_x"] > 320

    output.mkdir(parents=True, exist_ok=False)
    updated_layout = output / "adapted-description-layouts.json"
    updated_layout.write_text(json.dumps(updated, ensure_ascii=False, indent=2), "utf-8")
    result = {
        "method": "same engine binary, real item/magic/dialogue drawing; only SLF break changes",
        "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "executable_sha256": sha256(executable),
        "input_sha256": {str(p): sha256(p) for p in (original, adapted, layout)},
        "resource_sha256": {p.name: sha256(p) for p in sorted(resources.iterdir())
                            if p.suffix.lower() in (".mkf", ".msg", ".dat")},
        "source_sha256": {name: sha256(repo / name) for name in (
            "tests/render_evidence.cpp", "fontglyph.h", "fontglyph_jp.h",
            "tools/adapt_red_silkworm_description.py",
            "tools/verify_description_layout.py", "tools/verify_red_silkworm_rendering.py")},
        "static": {}, "engine": {},
    }
    for stage, slf, layout_path in (
        ("before", original, layout), ("after", adapted, updated_layout)
    ):
        audit = verify(layout_path, slf, repo)
        # "after" here means the existing 83-87 layout, for BOTH SLF inputs.
        result["static"][stage] = {
            "objects": audit["objects"], "lines": audit["lines"],
            **audit["stages"]["after"],
        }
        (output / f"static-{stage}.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", "utf-8")
        directory = output / stage
        directory.mkdir()
        run = subprocess.run([str(executable), "--render-evidence", str(resources),
                              str(slf), str(directory), "jp"], cwd=repo,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (directory / "render.log").write_bytes(run.stdout)
        if run.returncode:
            raise RuntimeError(f"Engine failed: see {directory / 'render.log'}")
        with (directory / "clipped-ink.csv").open() as stream:
            counts = {row["object_id"]: int(row["clipped_ink"]) for row in csv.DictReader(stream)}
        bitmaps = sorted(directory.glob("*.bmp"))
        if len(bitmaps) != 12 or len(counts) != 11:
            raise ValueError("Expected 12 engine images and 11 clipping probes")
        if sum(counts.values()) != audit["stages"]["after"]["clipped_ink_shadow_union"][0]:
            raise ValueError("Engine clipping disagrees with the independent glyph audit")
        images = {}
        for bitmap in bitmaps:
            with Image.open(bitmap) as source:
                if source.size != (320, 200):
                    raise ValueError("Unexpected engine resolution")
                pixels = source.convert("RGB")
                png = bitmap.with_suffix(".png")
                pixels.resize((640, 400), Image.Resampling.NEAREST).save(png, optimize=True)
                with Image.open(png) as saved:
                    if saved.resize(pixels.size, Image.Resampling.NEAREST).tobytes() != pixels.tobytes():
                        raise ValueError("PNG pixel roundtrip failed")
                images[png.name] = {"sha256": sha256(png), "bytes": png.stat().st_size}
        result["engine"][stage] = {
            "log": run.stdout.decode("utf-8").strip(),
            "clipped_ink_by_object": counts, "images": images,
        }

    unchanged = []
    for before in sorted((output / "before").glob("*.bmp")):
        after = output / "after" / before.name
        if before.name == "item-149.bmp":
            with Image.open(before) as old, Image.open(after) as new:
                bounds = ImageChops.difference(old.convert("RGB"), new.convert("RGB")).getbbox()
            if not bounds or not (71 <= bounds[0] < bounds[2] <= 320 and 119 <= bounds[1] < bounds[3] <= 152):
                raise ValueError(f"Changes outside the two description rows: {bounds}")
            result["item149_changed_bounds_exclusive"] = list(bounds)
        else:
            if before.read_bytes() != after.read_bytes():
                raise ValueError(f"Unrelated engine image changed: {before.name}")
            unchanged.append(before.name)
    if result["static"]["after"]["clipped_ink_shadow_union"] != [0, 0, 0]:
        raise ValueError("Some description ink/shadows still clip")
    result["checks"] = {
        "only_guarded_slf_break_changed": True,
        "all_24_png_pixel_roundtrips": True,
        "engine_matches_static_audit": True,
        "unchanged_engine_images": unchanged,
        "all_296_objects_no_clipped_ink_or_shadow": True,
    }
    (output / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "resources", "original", "adapted", "layout", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    report = collect(*(getattr(args, key).resolve() for key in (
        "executable", "resources", "original", "adapted", "layout", "output")))
    print(json.dumps({key: report[key] for key in ("static", "checks")}, indent=2))
