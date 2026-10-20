"""Run the opt-in C++ renderer and archive lossless, integer-scaled evidence.

Requires the Test executable and Pillow. Does not draw/reimplement game text.
Each mode runs in a fresh process because the engine mutates its font arrays.
"""
import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

from PIL import Image


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(executable, resources, slf, output):
    repo = Path(__file__).resolve().parents[1]
    result = {
        "method": "engine software rendering; no window capture; PNG previews use 2x nearest-neighbor",
        "logical_size": [320, 200],
        "preview_size": [640, 400],
        "palette": "PAT.MKF chunk 0, daytime",
        "executable_sha256": sha256(executable),
        "slf_sha256": sha256(slf),
        "resource_sha256": {p.name: sha256(p) for p in sorted(resources.iterdir())
                            if p.suffix.lower() in (".mkf", ".msg", ".dat")},
        "source_sha256": {name: sha256(repo / name) for name in
                          ("tests/render_evidence.cpp", "fontglyph.h", "fontglyph_cn.h", "fontglyph_jp.h")},
        "modes": {},
    }
    for mode in ("cn", "cn-jp-font", "jp-legacy", "jp"):
        directory = output / mode
        directory.mkdir(parents=True, exist_ok=True)
        run = subprocess.run([str(executable), "--render-evidence", str(resources),
                              str(slf), str(directory), mode], cwd=repo,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (directory / "render.log").write_bytes(run.stdout)
        if run.returncode:
            raise RuntimeError(f"{mode} failed ({run.returncode}): see {directory / 'render.log'}")
        with (directory / "clipped-ink.csv").open() as stream:
            counts = {row["object_id"]: int(row["clipped_ink"]) for row in csv.DictReader(stream)}
        images = {}
        for bitmap in sorted(directory.glob("*.bmp")):
            with Image.open(bitmap) as source:
                if source.size != (320, 200):
                    raise ValueError(f"Unexpected logical size: {bitmap}")
                pixels = source.convert("RGB")
                preview = pixels.resize((640, 400), Image.Resampling.NEAREST)
                png = bitmap.with_suffix(".png")
                preview.save(png, optimize=True)
                # Verify the published image retains every source pixel.
                with Image.open(png) as saved:
                    if saved.resize((320, 200), Image.Resampling.NEAREST).tobytes() != pixels.tobytes():
                        raise ValueError(f"PNG pixel roundtrip failed: {png}")
                images[png.name] = {"sha256": sha256(png), "bytes": png.stat().st_size}
        if len(images) != 12:
            raise ValueError(f"Expected 12 images in {directory}, got {len(images)}")
        result["modes"][mode] = {
            "renderer_log": run.stdout.decode("utf-8").strip(),
            "clipped_ink_by_object": counts,
            "clipped_ink_total": sum(counts.values()), "images": images,
        }

    expected = json.loads((repo / "docs/evidence/issue-5-description-pixels.json").read_text("utf-8"))
    for mode, stage in (("jp-legacy", "before"), ("jp", "after")):
        counts = {}
        for row in expected["original_clipped_lines"]:
            key = str(row["object_id"])
            counts[key] = counts.get(key, 0) + row[stage]["clipped_ink"]
        if counts != result["modes"][mode]["clipped_ink_by_object"]:
            raise ValueError(f"Actual engine ink differs from independent static audit: {mode}")
    result["checks"] = {
        "all_48_png_pixel_roundtrips": "pass",
        "all_11_object_counts_match_independent_static_audit_before_and_after": "pass",
        "item149_before_after_identical":
            sha256(output / "jp-legacy/item-149.bmp") == sha256(output / "jp/item-149.bmp"),
    }
    if not result["checks"]["item149_before_after_identical"]:
        raise ValueError("Unexpected item layout difference")
    (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "resources", "slf", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    report = collect(*(getattr(args, key).resolve() for key in ("executable", "resources", "slf", "output")))
    print(json.dumps({"checks": report["checks"], "clipped_ink": {
        mode: data["clipped_ink_total"] for mode, data in report["modes"].items()}}, indent=2))
