"""Check jp-long-names images against JIS glyphs, UI sprites and source pixels."""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image

from export_japanese_font import load_glyphs


NAMES = {270: "紫金のひょうたん", 384: "霊ひょうたんの術"}


def ui_frame(resources, frame):
    """Decode the uncompressed DATA.MKF chunk 9 sprite (palette 0 is opaque)."""
    data = (resources / "DATA.MKF").read_bytes()
    start, end = struct.unpack_from("<II", data, 9 * 4)
    sprite = data[start:end]
    offset = struct.unpack_from("<H", sprite, frame * 2)[0] * 2
    if offset == 0x18444:
        offset &= 0xFFFF
    if sprite[offset:offset + 4] == b"\x02\0\0\0":
        offset += 4
    width, height = struct.unpack_from("<HH", sprite, offset)
    offset += 4
    position, pixels = 0, {}
    while position < width * height:
        count = sprite[offset]
        offset += 1
        if count & 0x80 and count <= 0x80 + width:
            position += count - 0x80
        else:
            for color in sprite[offset:offset + count]:
                pixels[(position % width, position // width)] = color
                position += 1
            offset += count
    if position != width * height or any(y >= height for _, y in pixels):
        raise ValueError("Invalid UI sprite RLE")
    return pixels


def check_pixels(picture, expected, label):
    for position, color in expected.items():
        x, y = position
        if not (0 <= x < 320 and 0 <= y < 200):
            raise ValueError(f"Off-canvas {label}: {position}")
        if picture.getpixel(position) != color:
            raise ValueError(f"Missing/wrong-color {label}: {position}")


def verify(repo, resources, directory):
    glyphs = load_glyphs(repo, resources, {ord(c) for s in NAMES.values() for c in s})
    cursor = ui_frame(resources, 69)
    names, checked, scaled_checks = set(), [], []
    for object_id, text in NAMES.items():
        item = object_id == 270
        for column in (0, 1):
            for selected in (True, False):
                name = (f"{'item' if item else 'magic'}-{object_id}-"
                        f"{'right' if column else 'left'}-"
                        f"{'selected' if selected else 'unselected'}")
                names.add(name)
                path = directory / f"{name}.bmp"
                with Image.open(path) as picture:
                    if picture.mode != "P" or picture.size != (320, 200):
                        raise ValueError(f"Expected indexed 320x200 image: {path}")
                    left, top = ((15 + 148 * column, 12) if item else
                                 (35 + 135 * column, 70))
                    ink, expected = set(), {}
                    advance = 0
                    for character in text:
                        width, dots, origin = glyphs[ord(character)]
                        if width != 16 or not dots or origin != "JIS":
                            raise ValueError(f"Expected nonempty JIS 16px glyph: {character}")
                        points = {(left + advance + x, top + y) for x, y in dots}
                        # PAL_DrawText draws two shadows, then ink, per character.
                        for dx, dy in ((1, 1), (1, 0)):
                            expected.update({(x + dx, y + dy): 0 for x, y in points})
                        expected.update({p: None for p in points})
                        ink.update(points)
                        advance += width
                    if len(text) != 8 or advance != 128:
                        raise ValueError("Fixture is not eight full-width characters")
                    name_right = max(x for x, _ in expected)
                    overlays = {(left + 40 + x, top + 10 + y): c
                                for (x, y), c in cursor.items()} if selected else {}
                    # Item 270 is usable; magic 384 is grey outside battle.
                    allowed = (range(0xF9, 0xFF) if selected else (0x4F,)) if item else (
                        (0x1F,) if selected else (0x1C,))
                    reference = min(ink - overlays.keys())
                    color = picture.getpixel(reference)
                    if color not in allowed:
                        raise ValueError(f"Unexpected menu color: {name}: {color}")
                    expected = {p: color if c is None else c for p, c in expected.items()}
                    covered = len(ink & overlays.keys())
                    if covered != ((7 if item else 4) if selected else 0):
                        raise ValueError("Cursor/glyph overlap differs from this resource fixture")
                    expected.update(overlays)
                    check_pixels(picture, expected, name)
                    numbers = {}
                    sprites = ([(65, 144 + column * 148, 17),
                                (65, 150 + column * 148, 17)] if item else
                               ([(21, 17, 14), (23, 23, 14), (39, 30, 14),
                                 (65, 37, 14), (65, 43, 14), (65, 49, 14)]
                                if selected else []))
                    for frame, x, y in sprites:
                        numbers.update({(x + dx, y + dy): c
                                        for (dx, dy), c in ui_frame(resources, frame).items()})
                    if item and (name_right >= 144 + column * 148 or expected.keys() & numbers.keys()):
                        raise ValueError("Name/shadow overlaps item quantity")
                    check_pixels(picture, numbers, f"{name} quantity/MP")
                    checked.append({"file": path.name, "object": object_id, "column": column,
                                    "selected": selected, "characters": 8, "advance": advance,
                                    "glyph_ink": len(ink), "cursor_overwritten_ink": covered,
                                    "checked_name_shadow_cursor_pixels": len(expected),
                                    "rightmost_name_shadow_x": name_right,
                                    "checked_quantity_or_mp_pixels": len(numbers),
                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    expected_files = {f"{name}{suffix}.bmp" for name in names
                      for suffix in ("", "-640", "-960", "-800")}
    actual_files = {p.name for p in directory.glob("*.bmp")}
    if actual_files != expected_files:
        raise ValueError(f"Unexpected image set: {actual_files ^ expected_files}")
    with (directory / "long-names.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected_rows = {(str(obj), str(col), str(int(sel)),
                      str(obj if sel else (149 if obj == 270 else (390 if col == 0 else 306))), "0")
                     for obj in NAMES for col in (0, 1) for sel in (True, False)}
    if len(rows) != 8 or {tuple(row.values()) for row in rows} != expected_rows:
        raise ValueError("Clipping report does not match all eight menu states")
    for name in sorted(names):
        with Image.open(directory / f"{name}.bmp") as original:
            source = original.convert("RGB")
        source_colors = {color for _, color in source.getcolors(320 * 200)}
        for width in (640, 960, 800):
            path = directory / f"{name}-{width}.bmp"
            with Image.open(path) as image:
                scaled = image.convert("RGB")
            if scaled.size != (width, width * 5 // 8):
                raise ValueError(f"Unexpected scaled size: {path}")
            if not {color for _, color in scaled.getcolors(width * scaled.height)} <= source_colors:
                raise ValueError(f"Blended/non-source colors: {path}")
            factor = width / 320
            for y in range(200):
                for x in range(320):
                    if scaled.getpixel((int((x + .5) * factor), int((y + .5) * factor))) != source.getpixel((x, y)):
                        raise ValueError(f"Lost source pixel: {path}: {(x, y)}")
            exact = None
            if width in (640, 960):
                exact = scaled.tobytes() == source.resize(scaled.size, Image.Resampling.NEAREST).tobytes()
                if not exact:
                    raise ValueError(f"Integer nearest-neighbour mismatch: {path}")
            scaled_checks.append({"file": path.name, "source_pixels_preserved": 64000,
                                  "new_colors": 0, "exact_integer_nearest": exact,
                                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return {"directory": str(directory), "menus": checked, "scales": scaled_checks,
            "missing_clipped_or_wrong_color_expected_pixels": 0,
            "scope": "Expected name ink/shadows, cursor and quantity/MP sprites; not all background pixels. "
                     "Selected cursor intentionally covers 7/4 name ink pixels. No interactive acceptance."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = verify(Path(__file__).resolve().parents[1], args.resources, args.directory)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"PASS: {len(result['menus'])} menu states, {len(result['scales'])} scaled images")
