"""Verify cn-pages/jp-pages evidence against source glyphs and 320x200 pixels."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from export_japanese_font import load_glyphs


ROWS = [
    (1, 26, [("一二三四五六七八九十，。！？", 0x2D)]),
    (1, 44, [("黄色连续第二行", 0x2D)]),
    (1, 62, [("黄色连续第三行", 0x2D)]),
    (1, 80, [("黄色连续第四行", 0x2D)]),
    (2, 26, [("跨页仍为黄色", 0x2D), ("恢复", 0x4F)]),
    (2, 44, [("-'@\"()\\", 0x4F)]),
    (2, 62, [("红色", 0x1A), ("恢复", 0x4F), ("红色", 0x17), ("恢复", 0x4F)]),
    (2, 80, [("青色", 0x8D), ("恢复", 0x4F)]),
    (3, 26, [("第三页：结束。", 0x4F)]),
]


def verify(repo, resources, directory, language):
    glyphs = load_glyphs(repo, resources,
                        {ord(c) for _, _, spans in ROWS for text, _ in spans for c in text})
    ink, characters = 0, 0
    for page, top, spans in ROWS:
        with Image.open(directory / f"controls-page-{page}.bmp") as picture:
            if picture.mode != "P" or picture.size != (320, 200):
                raise ValueError("Expected indexed 320x200 evidence")
            x = 96
            for text, color in spans:
                for character in text:
                    width, pixels, _ = glyphs[ord(character)]
                    if width <= 0 or not pixels:
                        raise ValueError(f"Empty fixture glyph: {character!r}")
                    for dx, dy in pixels:
                        if not (0 <= x + dx < 320 and 0 <= top + dy < 200):
                            raise ValueError(f"Clipped glyph: {character!r}")
                        if picture.getpixel((x + dx, top + dy)) != color:
                            raise ValueError(f"Missing/wrong-color ink: {character!r}")
                    ink += len(pixels)
                    characters += 1
                    x += width
    # Compare RGB because the base BMP is indexed while GPU readback is ARGB.
    names = {"aunt-dialogue", *(f"controls-page-{i}" for i in range(1, 4)),
             "dialogue-1326-page-1", "dialogue-1326-page-2",
             *(f"dialogue-1333-page-{i}" for i in range(1, 3 if language == "cn" else 6))}
    expected_files = {f"{name}{suffix}.bmp" for name in names
                      for suffix in ("", "-640", "-960", "-800")}
    actual_files = {path.name for path in directory.glob("*.bmp")}
    if actual_files != expected_files:
        raise ValueError(f"Evidence set mismatch: missing={expected_files - actual_files}, "
                         f"unexpected={actual_files - expected_files}")
    checked = []
    for name in sorted(names):
        path = directory / f"{name}.bmp"
        with Image.open(path) as source:
            if source.size != (320, 200):
                raise ValueError(f"Expected 320x200 base image: {path}")
            source = source.convert("RGB")
        source_colors = {color for _, color in source.getcolors(320 * 200)}
        for width in (640, 960, 800):
            scaled_path = path.with_name(f"{path.stem}-{width}.bmp")
            with Image.open(scaled_path) as scaled:
                scaled = scaled.convert("RGB")
            if scaled.size != (width, width * 5 // 8):
                raise ValueError(f"Unexpected dimensions: {scaled_path}")
            scaled_colors = {color for _, color in scaled.getcolors(width * scaled.height)}
            if not scaled_colors <= source_colors:
                raise ValueError(f"Blended/non-source colors: {scaled_path}")
            factor = width / 320
            # At 2.5x, GPU nearest-neighbor tie handling need not match Pillow.
            # Every original pixel must survive at the center of its footprint.
            for y in range(200):
                for x in range(320):
                    if scaled.getpixel((int((x + .5) * factor), int((y + .5) * factor))) != source.getpixel((x, y)):
                        raise ValueError(f"Lost source pixel: {scaled_path} ({x},{y})")
            exact = None
            if width in (640, 960):
                exact = scaled.tobytes() == source.resize(scaled.size, Image.Resampling.NEAREST).tobytes()
                if not exact:
                    raise ValueError(f"Integer scaling differs: {scaled_path}")
            checked.append({"file": scaled_path.name, "pixels_preserved": 64000,
                            "new_colors": 0, "exact_integer_nearest": exact,
                            "sha256": hashlib.sha256(scaled_path.read_bytes()).hexdigest()})
    return {"directory": str(directory), "glyph_characters": characters,
            "expected_ink_pixels": ink, "missing_clipped_or_wrong_color_ink": 0,
            "scope": "Expected glyph ink only; does not reject extra pixels/background.",
            "scales": checked}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--language", choices=("cn", "jp"), required=True)
    args = parser.parse_args()
    result = verify(Path(__file__).resolve().parents[1], args.resources, args.directory, args.language)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"PASS: {result['glyph_characters']} characters, {result['expected_ink_pixels']} ink pixels, "
          f"{len(result['scales'])} scaled images")
