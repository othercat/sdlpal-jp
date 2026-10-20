"""Compose opaque previews from verified Issue #9 engine frames and source RGB."""
import argparse
import csv
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent / "japanese"))
from verify_portrait_rendering import read_pack, rgb_image
from convert_portraits import require, sha


def export(render, pack_root, output):
    require(not output.exists(), "Use a new preview directory")
    report = json.loads((render / "verification.json").read_text("utf-8"))
    require(report["resources_unchanged"], "Incomplete rendering verification")
    output.mkdir(parents=True)
    font = ImageFont.load_default(size=18)
    records = []

    def verified_image(path):
        require(sha(path.read_bytes()) == report["image_sha256"][path.relative_to(render).as_posix()],
                f"Image changed since pixel verification: {path}")
        with Image.open(path) as image:
            return image.convert("RGB")

    def save(picture, name, purpose):
        picture = picture.convert("RGB")
        path = output / name
        picture.save(path, optimize=True)
        # Explicit opaque RGB export; don't carry SDL target-texture alpha.
        with Image.open(path) as image:
            require(image.mode == "RGB" and image.tobytes() == picture.tobytes(), "PNG altered")
            require(len(set(image.tobytes())) > 16, "Blank export")
        records.append({"file": name, "purpose": purpose, "size": picture.size,
                        "mode": "RGB", "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())})

    for version, key in (("win", 12078), ("dos", 442), ("win", 7583), ("dos", 8166)):
        canvas = Image.new("RGB", (1280, 446), "#ededed")
        draw = ImageDraw.Draw(canvas)
        for index, stage in enumerate(("native", "adapted")):
            path = render / f"{version}-{stage}-dialogue-{key}-page-1.png"
            image = verified_image(path)
            require(image.size == (640, 400), "Unexpected dialogue scale")
            canvas.paste(image, (index*640, 46))
            draw.text((index*640+14, 12), f"{version.upper()} / " +
                      ("PC portraits (default)" if stage == "native" else "Saturn pack enabled"),
                      font=font, fill="#111111")
        save(canvas, f"{version}-dialogue-{key}-comparison.png",
             "Two real source-rendered dialogue frames; labels only added.")
    # Extract source-rendered portrait rectangles without repainting their pixels.
    version = "win"
    pack = pack_root / "generated-win/paljpn-win.por"
    require(sha(pack.read_bytes()) == report["versions"]["win"]["pack_sha256"],
            "Reference pack differs from the source-rendered pack")
    palette, entries = read_pack(pack, "win")
    rows = {}
    for stage in ("native", "adapted"):
        checks = next(c for c in report["versions"]["win"]["probe_checks"] if c["stage"] == stage)
        require(sha((render / f"win-{stage}/portraits.csv").read_bytes()) == checks["metadata_sha256"] and
                sha((render / f"win-{stage}/portrait-frames.bin").read_bytes()) == checks["frames_sha256"],
                "Portrait frame/metadata changed after verification")
    with (render / "win-adapted/portraits.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row["stage"] == "0":
                rows[row["name"]] = row
    canvas = Image.new("RGB", (1040, 890), "#ededed")
    draw = ImageDraw.Draw(canvas)
    titles = ("PC original / day", "Saturn RGB / fitted", "SDLPAL remap / day", "SDLPAL remap / night")
    for column, title in enumerate(titles):
        draw.text((column*260+8, 14), title, font=font, fill="#111111")
    for index, face in enumerate((55, 37, 70)):
        name = f"face-{face}-p0-n0-l0"
        row = rows[name]
        w, h, x, y = (int(row[k]) for k in ("width", "height", "x", "y"))
        pictures = []
        for stage, night in (("native", 0), ("adapted", 0), ("adapted", 1)):
            image = verified_image(render / f"win-{stage}" / f"face-{face}-p0-n{night}-l0.bmp")
            pictures.append(image.crop((x, y, x+w, y+h)))
        # Reference is decoded source palette, fitted to the same PC extent;
        # it is explicitly not an engine output or an original live screenshot.
        with (render / "win-native/portrait-frames.bin").open("rb") as stream:
            stream.seek(int(row["offset"]))
            frame = stream.read(64768)
        background = bytes((xx//4+yy//3)&255 for yy in range(200) for xx in range(320))
        reference = rgb_image(background, frame[64000:]).crop((x, y, x+w, y+h))
        source = rgb_image(entries[face][2], palette, (w, h))
        reference.paste(source, (0, 0), Image.frombytes("L", (w, h), entries[face][3]))
        pictures.insert(1, reference)
        for column, picture in enumerate(pictures):
            top = 58 + index*274
            draw.text((column*260+8, top), f"Face {face}", font=font, fill="#111111")
            picture = picture.resize((w*2, h*2), Image.Resampling.NEAREST)
            canvas.paste(picture, (column*260+(260-picture.width)//2, top+30))
    save(canvas, "win-portrait-palette-comparison.png",
         "Engine crops for PC/day/night; separately labelled decoded Saturn RGB reference. No live screenshot.")
    result = {"render_verification_sha256": sha((render/"verification.json").read_bytes()),
              "images": records}
    (output / "previews.json").write_text(json.dumps(result, indent=2)+"\n", "utf-8")
    print(f"Exported {len(records)} opaque RGB comparison images")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("render", "pack_root", "output"):
        parser.add_argument(name, type=Path)
    export(**vars(parser.parse_args()))
