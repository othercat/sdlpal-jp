"""Export the engine's Japanese flavor to a pixel-outline TrueType test font.

JIS overrides plus ASCII and every character used by the supplied GBK resources.
At 16px each outline rectangle covers exactly one source bitmap row run.
This is an experiment font, not a replacement for the engine's font loader.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable


FAMILY = "SDLPAL JP 16px"
UNIT = 64


def resource_characters(repo, resources):
    # Use the engine's CP936 table, including its '?' replacements for reserved
    # byte pairs, rather than Python's stricter GBK decoder.
    body = re.search(r"cptbl_gbk\[126\]\[192\]\s*=\s*\{(.*?)\};",
                     (repo / "codepage.h").read_text("utf-8"), re.S)[1]
    table = [int(value, 16) for value in re.findall(r"0x[0-9A-Fa-f]+", body)]
    if len(table) != 126 * 192:
        raise ValueError("Unexpected CP936 table")
    sss = (resources / "SSS.MKF").read_bytes()
    start, end = struct.unpack_from("<II", sss, 12)
    offsets = struct.unpack("<" + "I" * ((end - start) // 4), sss[start:end])
    messages = (resources / "M.MSG").read_bytes()
    words = (resources / "WORD.DAT").read_bytes()
    if offsets[-1] > len(messages) or list(offsets) != sorted(offsets) or len(words) % 10:
        raise ValueError("Expected PAL98 Windows root resources with 10-byte words")
    segments = [messages[a:b] for a, b in zip(offsets, offsets[1:])]
    segments.extend(words[i:i + 10] for i in range(0, len(words), 10))
    characters = set()
    for segment in segments:
        lead = None
        for byte in segment:
            if byte == 0:
                break
            if lead is not None:
                characters.add(0x3f if byte < 0x40 else table[(lead - 0x81) * 192 + byte - 0x40])
                lead = None
            elif byte < 0x80:
                characters.add(byte)
            elif byte in (0x80, 0xff):
                characters.add(0x20ac if byte == 0x80 else 0xf8f5)
            else:
                lead = byte
    return {cp for cp in characters if cp >= 32}


def load_glyphs(repo, resources):
    source = (repo / "fontglyph.h").read_text("utf-8")
    body = re.search(r"unicode_font\[\]\[32\]\s*=\s*\{(.*?)\};", source, re.S)[1]
    bitmaps = [bytes(map(int, re.findall(r"\d+", s)))
               for s in re.findall(r"\{([^{}]+)\}", body)]
    widths = list(map(int, re.findall(r"\d+", re.search(
        r"font_width\[\]\s*=\s*\{(.*?)\};", source, re.S)[1])))
    japanese = {int(cp, 16): bytes(int(v, 16) for v in re.findall(r"0x[\da-fA-F]+", s))
                for cp, s in re.findall(r"\{\s*(0x[\da-fA-F]+),\s*\{([^{}]+)\}",
                                        (repo / "fontglyph_jp.h").read_text("utf-8"))}
    characters = set(range(32, 127)) | set(japanese)
    characters.update(resource_characters(repo, resources))
    result = {}
    for cp in sorted(characters):
        if 0xD800 <= cp < 0xF900 or cp >= 0xFFFE:
            # PAL_CharWidth returns zero and PAL_DrawChar skips these, including
            # CP936 private-use mappings found in this resource's other messages.
            result[cp] = (0, set(), "not-rendered")
            continue
        index = cp - 0x2100 if cp >= 0xF900 else cp
        width, data, origin = ((16, japanese[cp], "JIS") if cp in japanese else
                               (widths[index] >> 1, bitmaps[index], "Unifont"))
        if width not in (8, 16):
            raise ValueError(f"Unsupported width: U+{cp:04X} = {width}")
        pixels = {(x, y) for y in range(16) for x in range(width)
                  if data[y * (width // 8) + x // 8] & (0x80 >> (x % 8))}
        result[cp] = (width, pixels, origin)
    return result


def build(repo, resources, output):
    if output.exists():
        raise FileExistsError(output)
    data = load_glyphs(repo, resources)
    names = {cp: f"uni{cp:04X}" for cp in data}
    builder = FontBuilder(16 * UNIT, isTTF=True)
    builder.setupGlyphOrder([".notdef", *names.values()])
    builder.setupCharacterMap(names)
    outlines = {".notdef": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (16 * UNIT, 0)}
    for cp, (width, pixels, origin) in data.items():
        pen = TTGlyphPen(None)
        for y in range(16):
            x = 0
            while x < width:
                if (x, y) not in pixels:
                    x += 1
                    continue
                start = x
                while x < width and (x, y) in pixels:
                    x += 1
                left, right = start * UNIT, x * UNIT
                bottom, top = (15 - y) * UNIT, (16 - y) * UNIT
                pen.moveTo((left, bottom))
                pen.lineTo((left, top))
                pen.lineTo((right, top))
                pen.lineTo((right, bottom))
                pen.closePath()
        outlines[names[cp]] = pen.glyph()
        metrics[names[cp]] = (width * UNIT, min((x for x, y in pixels), default=0) * UNIT)
    builder.setupGlyf(outlines)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=16 * UNIT, descent=0, lineGap=0)
    builder.setupNameTable({
        "familyName": FAMILY, "styleName": "Regular",
        "uniqueFontIdentifier": "sdlpal-jp-font-comparison-16px-v1",
        "fullName": FAMILY, "psName": "SDLPALJP16px",
        "version": "Version 1.000",
        "copyright": "Derived from SDLPAL Japanese JIS X0208 and GNU Unifont bitmap data.",
        "licenseDescription": "GPL-3.0-or-later; preserve source attribution. JIS component: public domain GNU intlfonts, Koichi Yasuoka.",
        "licenseInfoURL": "https://www.gnu.org/licenses/gpl-3.0.html",
        "description": "Pixel outlines for a same-source 16px rendering experiment.",
    })
    builder.setupOS2(sTypoAscender=16 * UNIT, sTypoDescender=0, sTypoLineGap=0,
                     usWinAscent=16 * UNIT, usWinDescent=0, usWeightClass=400,
                     xAvgCharWidth=8 * UNIT, ulCodePageRange1=(1 << 17) | (1 << 18) | 1,
                     ulCodePageRange2=0, fsType=0)
    builder.setupPost()
    builder.setupMaxp()
    builder.font["gasp"] = newTable("gasp")
    builder.font["gasp"].gaspRange = {65535: 0}
    builder.font["head"].created = builder.font["head"].modified = 2082844800
    builder.font.recalcTimestamp = False
    builder.save(output)
    report = {
        "family": FAMILY, "glyphs": len(data), "em_pixels": 16,
        "jis_glyphs": sum(origin == "JIS" for width, pixels, origin in data.values()),
        "fallback_glyphs": sum(origin == "Unifont" for width, pixels, origin in data.values()),
        "engine_skips": [f"U+{cp:04X}" for cp, (width, pixels, origin) in data.items()
                         if origin == "not-rendered"],
        "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            repo / "fontglyph.h", repo / "fontglyph_jp.h",
            repo / "codepage.h", resources / "SSS.MKF",
            resources / "M.MSG", resources / "WORD.DAT", output)},
    }
    output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.resources, args.output), indent=2))
