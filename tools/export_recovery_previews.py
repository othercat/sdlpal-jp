"""Export opaque Issue #3 source-rendered previews and verify their RGB pixels."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image


def opaque_rgb(path):
    with Image.open(path) as source:
        rgba = source.convert("RGBA")
        if rgba.getchannel("A").getextrema() != (255, 255):
            raise ValueError(f"Non-opaque source image: {path}; rebuild the source renderer")
        return source.convert("RGB")


def export_preview(source, destination):
    pixels = opaque_rgb(source)
    pixels.save(destination, optimize=True)
    # Reopen the actual PNG; viewing RGB alone previously missed alpha=0.
    with Image.open(destination) as encoded:
        if encoded.mode != "RGB" or encoded.convert("RGBA").getchannel("A").getextrema() != (255, 255):
            raise ValueError(f"PNG is not opaque RGB: {destination}")
        if encoded.tobytes() != pixels.tobytes():
            raise ValueError(f"PNG pixels differ from source: {destination}")
    return {"file": destination.name, "mode": "RGB", "effective_alpha": [255, 255],
            "size": list(pixels.size), "rgb_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "bytes": destination.stat().st_size}


def export(before_dir, after_dir, output_dir):
    if output_dir.exists():
        raise ValueError(f"Use a new output directory: {output_dir}")
    sources = []
    for stage, directory in (("before", before_dir), ("after", after_dir)):
        with (directory / "recovery.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        drawn = [row for row in rows if int(row["drawn"])]
        if len(rows) != 4766 or len({(r["first"], r["last"]) for r in rows}) != 4766 or len(drawn) != 8:
            raise ValueError(f"Incomplete recovery CSV: {directory}")
        expected = {f'dialogue-{row["first"]}-page-{page}-640.bmp'
                    for row in drawn for page in range(1, int(row["pages"]) + 1)}
        if expected != {p.name for p in directory.glob("*-640.bmp")}:
            raise ValueError(f"Preview set differs from recovery CSV: {directory}")
        for name in sorted(expected):
            path = directory / name
            if opaque_rgb(path).size != (640, 400):
                raise ValueError(f"Expected 640x400: {path}")
            sources.append((path, stage + "-" + path.stem + ".png"))
    if len(sources) != 18:
        raise ValueError("Expected eight before and ten after preview pages")
    output_dir.mkdir(parents=True)
    report = [export_preview(source, output_dir / name) for source, name in sources]
    (output_dir / "previews.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before_dir", "after_dir", "output_dir"):
        parser.add_argument(name, type=Path)
    try:
        result = export(**vars(parser.parse_args()))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"ERROR: {error}\n")
    print(f"PASS: {len(result)} opaque RGB previews, source pixels unchanged")


if __name__ == "__main__":
    main()
