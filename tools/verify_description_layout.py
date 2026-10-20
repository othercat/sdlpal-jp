"""Recount Japanese description ink on the 320x200 logical screen.

Input: description-render-layouts.json from the localization audit and its SLF.
This is a static glyph audit, not a gameplay screenshot or a UI acceptance test.
"""
import argparse
import hashlib
import json
import re
from itertools import combinations
from pathlib import Path


def verify(layout_file, slf_file, repo):
    font_file, jp_file = repo / "fontglyph.h", repo / "fontglyph_jp.h"
    font, japanese = font_file.read_text("utf-8"), jp_file.read_text("utf-8")
    body = re.search(r"unicode_font\[\]\[32\]\s*=\s*\{(.*?)\};", font, re.S)[1]
    glyphs = [bytes(map(int, re.findall(r"\d+", s)))
              for s in re.findall(r"\{([^{}]+)\}", body)]
    widths = list(map(int, re.findall(r"\d+", re.search(
        r"font_width\[\]\s*=\s*\{(.*?)\};", font, re.S)[1])))
    jp = {int(cp, 16): bytes(int(v, 16) for v in re.findall(r"0x[\da-fA-F]+", s))
          for cp, s in re.findall(r"\{\s*(0x[\da-fA-F]+),\s*\{([^{}]+)\}", japanese)}
    layout = re.search(r"\[BEGIN LAYOUT\](.*?)\[END LAYOUT\]",
                       slf_file.read_text("utf-8"), re.S)[1]
    match = re.search(r"(?m)^87\s*=\s*(\d+)\s*,\s*(\d+)", layout)
    if not match or int(match[2]) != 0:
        raise ValueError("Expected layout 87=x,0 for this upstream layout contract")
    magic_x = int(match[1])
    objects = json.loads(layout_file.read_text("utf-8"))
    rows = [row for obj in objects for row in obj["lines"]]

    def render(row, x):
        ink, shadow, chars = set(), set(), []
        if "line" not in row or "\\" in row["line"] or "\0" in row["line"]:
            raise ValueError("Unsupported script/escaped text; inspect before counting")
        for char in row["line"]:
            cp = ord(char)
            if 0xD800 <= cp < 0xF900 or cp >= 0xFFFE:
                raise ValueError("Unsupported codepoint")
            index = cp - 0x2100 if cp >= 0xF900 else cp
            width, glyph = (16, jp[cp]) if cp in jp else (widths[index] >> 1, glyphs[index])
            if width not in (8, 16):
                raise ValueError("Unsupported glyph width")
            points = {(x + xx, row["y"] + yy)
                      for yy in range(16) for xx in range(width)
                      if glyph[yy * (width // 8) + xx // 8] & (1 << (7 - xx % 8))}
            ink |= points
            shadow |= {(px + 1, py + dy) for px, py in points for dy in (0, 1)}
            chars.append((char, points))
            x += width
        return ink, shadow - ink, ink | shadow, chars

    def outside(point):
        return not (0 <= point[0] < 320 and 0 <= point[1] < 200)

    masks = {stage: [render(row, row["x"] if stage == "before" else
                            magic_x if row["kind"] == "magic" else row["x"])
                     for row in rows] for stage in ("before", "after")}
    result = {
        "method": "static Japanese glyph ink and (1,0)/(1,1) shadows; not gameplay",
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (layout_file, slf_file, font_file, jp_file)},
        "objects": len(objects), "lines": len(rows), "magic_x_after": magic_x,
        "stages": {}, "original_clipped_lines": [],
    }
    for stage, rendered in masks.items():
        clipped = [i for i, mask in enumerate(rendered) if any(map(outside, mask[0]))]
        offset = ink_overlap = footprint_overlap = overlap_pairs = 0
        for obj in objects:
            subset = rendered[offset:offset + len(obj["lines"])]
            offset += len(subset)
            for first, second in combinations(subset, 2):
                overlap_pairs += bool(first[2] & second[2])
                ink_overlap += len(first[0] & second[0])
                footprint_overlap += len(first[2] & second[2])
        magic = [mask for row, mask in zip(rows, rendered) if row["kind"] == "magic"]
        result["stages"][stage] = {
            "clipped_objects": len({rows[i]["object_id"] for i in clipped}),
            "clipped_lines": len(clipped),
            "clipped_ink_shadow_union": [sum(sum(map(outside, mask[k])) for mask in rendered)
                                         for k in (0, 1, 2)],
            "magic_rightmost_ink_and_shadow": [max(x for mask in magic for x, y in mask[k])
                                               for k in (0, 2)],
            "magic_pixels_at_or_below_menu_y58": sum(y >= 58 for mask in magic for x, y in mask[2]),
            "overlap_pairs_ink_and_union_pixels": [overlap_pairs, ink_overlap, footprint_overlap],
        }
    for i, row in enumerate(rows):
        if not any(map(outside, masks["before"][i][0])):
            continue
        entry = {key: row[key] for key in ("object_id", "object", "sid", "y", "kind")}
        for stage in masks:
            mask = masks[stage][i]
            entry[stage] = {
                "clipped_ink": sum(map(outside, mask[0])),
                "clipped_shadow": sum(map(outside, mask[1])),
                "rightmost_ink": max(x for x, y in mask[0]),
                "clipped_characters": "".join(char for char, pts in mask[3] if any(map(outside, pts))),
            }
        result["original_clipped_lines"].append(entry)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout_json", type=Path)
    parser.add_argument("slf", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.layout_json, args.slf, Path(__file__).resolve().parents[1]),
                     ensure_ascii=False, indent=2))
