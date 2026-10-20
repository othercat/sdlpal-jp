"""Export opaque Issue 9 R2 previews from verified source-rendered RGB frames."""
import argparse
import csv
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent / "japanese"))
from verify_portrait_colors import digest, load_rgb
from verify_portrait_rendering import BACKGROUND, read_pack, require, rgb_image


def export(render, r1, output):
    require(not output.exists(), "Use a new output directory")
    report = json.loads((render / "verification.json").read_text("utf-8"))
    require(report["resources_unchanged"], "Incomplete verification")
    output.mkdir(parents=True)
    font = ImageFont.load_default(size=18)
    records = []

    def verified(path):
        require(digest(path) == report["images"][path.relative_to(render).as_posix()],
                "Image differs from verified output")
        return load_rgb(path)

    def save(image, name, purpose):
        require(image.mode == "RGB", "Expected opaque RGB")
        path = output / name
        image.save(path, optimize=True)
        require(load_rgb(path).tobytes() == image.tobytes(), "PNG roundtrip differs")
        records.append(dict(file=name, purpose=purpose, sha256=digest(path),
                            dimensions=image.size, bytes=path.stat().st_size, mode="RGB"))

    pack = r1 / "generated-win/paljpn-win.por"
    require(digest(pack) == report["versions"]["win"]["pack_sha256"], "Reference pack changed")
    colors, entries = read_pack(pack, "win")
    metadata = render / "win-adapted/portraits.csv"
    check = next(c for c in report["versions"]["win"]["checks"] if c["style"] == "adapted")
    require(digest(metadata) == check["metadata_sha256"], "Portrait metadata changed")
    with metadata.open(newline="") as stream:
        rows = {row["name"]: row for row in csv.DictReader(stream) if row["stage"] == "0"}
    canvas = Image.new("RGB", (1040, 890), "#ededed")
    draw = ImageDraw.Draw(canvas)
    titles = ("R1 indexed / night", "Saturn RGB / fitted", "R2 RGB / night", "R2 RGB / day")
    for col, title in enumerate(titles):
        draw.text((col * 260 + 8, 14), title, font=font, fill="#111111")
    for line, face in enumerate((55, 37, 70)):
        name = f"face-{face}-p0-n1-l0"
        row = rows[name]
        require(tuple(int(row[k]) for k in ("face", "palette", "night", "location", "stage")) ==
                (face, 0, 1, 0, 0), "Wrong preview portrait/palette/location/stage")
        w, h, x, y = (int(row[k]) for k in ("width", "height", "x", "y"))
        require((w, h) == entries[face][:2], "Preview dimensions differ from fitted pack")
        night_file = render / "win-adapted" / (name + ".bmp")
        legacy = verified(night_file).crop((x, y, x+w, y+h))
        with Image.open(night_file) as indexed:
            palette = indexed.getpalette()
        reference = rgb_image(BACKGROUND, palette).crop((x, y, x+w, y+h))
        reference.paste(rgb_image(entries[face][2], colors, (w, h)), (0, 0),
                        Image.frombytes("L", (w, h), entries[face][3]))
        night = verified(night_file.with_name(name + "-rgb.bmp")).crop((x, y, x+w, y+h))
        day = verified(night_file.with_name(f"face-{face}-p0-n0-l0-rgb.bmp")).crop((x, y, x+w, y+h))
        for col, image in enumerate((legacy, reference, night, day)):
            top = 58 + line * 274
            draw.text((col*260 + 8, top), f"Face {face}", font=font, fill="#111111")
            canvas.paste(image.resize((w*2, h*2), Image.Resampling.NEAREST),
                         (col*260 + (260-w*2)//2, top+30))
    save(canvas, "night-portrait-colors.png",
         "Engine crops before/after; fitted decoded Saturn RGB reference is separately labelled.")
    for version, key in (("win", 7583), ("win", 12078), ("dos", 8166)):
        directory = render / f"{version}-dialogue-adapted-night"
        check = report["night_checks"][f"{directory.name}/dialogue-{key}-page-1"]
        require(check["palette_matches_original_pat"] and check["indices_match_independent_day_remapping"],
                "Night dialogue has no independent palette/background check")
        before = verified(directory / f"dialogue-{key}-page-1.bmp")
        after = verified(directory / f"dialogue-{key}-page-1-640.bmp")
        canvas = Image.new("RGB", (1280, 446), "#ededed")
        draw = ImageDraw.Draw(canvas)
        canvas.paste(before.resize((640, 400), Image.Resampling.NEAREST), (0, 46))
        canvas.paste(after, (640, 46))
        draw.text((14, 12), f"{version.upper()} / indexed fallback / night", font=font, fill="#111111")
        draw.text((654, 12), f"{version.upper()} / source RGB composition / night", font=font, fill="#111111")
        save(canvas, f"{version}-night-dialogue-{key}.png",
             "Same production dialogue: retained indexed fallback versus verified SDL RGB output; not gameplay.")
    (output / "previews.json").write_text(json.dumps({
        "verification_sha256": digest(render / "verification.json"), "images": records,
    }, indent=2) + "\n", "utf-8")
    print(f"Exported {len(records)} opaque RGB previews")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("render", "r1", "output"):
        parser.add_argument(name, type=Path)
    export(**vars(parser.parse_args()))
