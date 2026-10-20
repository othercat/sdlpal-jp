"""Build an opt-in Win/DOS portrait pack from the reviewed Saturn disc files.

No original game file is changed. The engine remaps the saved source RGB palette
at dialogue start; this converter does not bake the daytime PC palette into art.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct

MANIFEST = Path(__file__).with_name("portrait-map.json")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_inputs(directory, expected):
    files = {}
    for name, digest in expected.items():
        matches = [p for p in directory.iterdir() if p.is_file() and p.name.lower() == name.lower()]
        require(len(matches) == 1, f"Missing/ambiguous input: {name}")
        data = matches[0].read_bytes()
        require(sha(data) == digest, f"Unreviewed input: {name}")
        files[name] = data
    return files


def mkf_chunks(data):
    require(len(data) >= 4, "Short MKF")
    first = struct.unpack_from("<I", data)[0]
    require(first >= 8 and first % 4 == 0 and first <= len(data), "Invalid MKF table")
    offsets = struct.unpack_from(f"<{first // 4}I", data)
    require(offsets[0] == first and offsets[-1] == len(data) and
            all(a <= b for a, b in zip(offsets, offsets[1:])), "Invalid MKF bounds")
    return [data[a:b] for a, b in zip(offsets, offsets[1:])]


def decode_saturn(chunk):
    require(len(chunk) == 0x2800, "Wrong Saturn slot size")
    width, height = struct.unpack_from(">HH", chunk)
    if width == height == 0:
        require(not any(chunk), "Nonempty zero-sized slot")
        return 0, 0, b"", 4
    require(0 < width <= 256 and 0 < height <= 200, "Unsupported Saturn dimensions")
    pixels = bytearray(width * height)
    pos = 4
    for y in range(height):
        x = 0
        while x < width:
            require(pos < len(chunk), "Truncated RLE command")
            op = chunk[pos]
            pos += 1
            count = op - 0x80 if op >= 0x80 else op
            require(count > 0 and x + count <= width, "Invalid/cross-row RLE run")
            if op < 0x80:
                require(pos + count <= len(chunk), "Truncated RLE literal")
                literal = chunk[pos:pos+count]
                # All reviewed literals are nonzero. Zero in the pack is
                # reserved exclusively for the original transparent skip runs.
                require(0 not in literal, "Unreviewed opaque zero index")
                pixels[y*width+x:y*width+x+count] = literal
                pos += count
            x += count
    # Original decoder stops at height; some slots retain one nonzero tail byte.
    require(not any(chunk[pos+1:]), "Unreviewed RLE trailing data")
    return width, height, bytes(pixels), pos


def pc_dimensions(chunk):
    if chunk[:4] == b"\x02\x00\x00\x00":
        chunk = chunk[4:]
    require(len(chunk) >= 4, "Missing native portrait")
    w, h = struct.unpack_from("<HH", chunk)
    require(0 < w <= 320 and 0 < h <= 200, "Unsupported PC portrait bounds")
    return w, h


def fit_pixels(pixels, width, height, target_width, target_height):
    """Aspect-fit inside the unchanged PC rectangle, using integer sampling."""
    require(len(pixels) == width * height and width > 0 and height > 0, "Bad source plane")
    ratio = min(Fraction(target_width, width), Fraction(target_height, height), Fraction(1))
    w = max(1, width * ratio.numerator // ratio.denominator)
    h = max(1, height * ratio.numerator // ratio.denominator)
    left, top = (target_width - w) // 2, (target_height - h) // 2
    result = bytearray(target_width * target_height)
    for y in range(h):
        for x in range(w):
            result[(top+y)*target_width+left+x] = pixels[(y*height//h)*width + x*width//w]
    return bytes(result), {"scaled_width": w, "scaled_height": h, "left": left, "top": top,
                           "method": "aspect-fit, no enlargement, floor nearest sample"}


def convert(resources, saturn, output, target, manifest_path=MANIFEST):
    require(target in ("win", "dos"), "Explicit target required")
    require(not output.exists(), "Output directory already exists; choose a new directory")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    require(manifest["format"] == 1, "Unsupported mapping manifest")
    pc = read_inputs(resources, manifest["inputs"][target])
    ss = read_inputs(saturn, manifest["inputs"]["saturn"])
    source = ss["RGM.JOE"]
    require(len(source) == 99 * 0x2800, "Unexpected Saturn archive size")
    bank = ss["ALLDAT.NEW"][0x600:0x800]
    require(sha(bank) == manifest["palette_be555_sha256"], "Palette bank changed")
    palette = bytes(component for word in struct.unpack(">256H", bank)
                    for component in ((word & 31) << 3, ((word >> 5) & 31) << 3,
                                      ((word >> 10) & 31) << 3))
    require(sha(palette) == manifest["palette_rgb24_sha256"], "Palette expansion changed")
    ids = manifest["identity_ids"]
    require(len(ids) == len(set(ids)) == 86 and 38 not in ids and
            all(0 < i < 99 for i in ids), "Invalid reviewed ID set")
    native = mkf_chunks(pc["RGM.MKF"])
    packed = bytearray(b"PALJPOR1" + struct.pack("<4H", 1, target == "win", len(ids), 0) + palette)
    entries = []
    for face in ids:
        chunk = source[face*0x2800:(face+1)*0x2800]
        w, h, pixels, used = decode_saturn(chunk)
        require(w > 0 and face < len(native), f"Unavailable reviewed portrait {face}")
        tw, th = pc_dimensions(native[face])
        fitted, layout = fit_pixels(pixels, w, h, tw, th)
        packed += struct.pack("<4H", face, tw, th, 0) + fitted
        entries.append({"id": face, "source_width": w, "source_height": h,
                        "width": tw, "height": th, "rle_used_bytes": used,
                        "source_indices_sha256": sha(pixels), "fitted_indices_sha256": sha(fitted),
                        "native_chunk_sha256": sha(native[face]), "layout": layout,
                        "opaque_pixels": sum(p != 0 for p in fitted)})
    result = {
        "target": target, "manifest_sha256": sha(manifest_path.read_bytes()),
        "inputs": manifest["inputs"], "entries": entries,
        "source_palette_rgb24_sha256": sha(palette),
        "output_sha256": sha(packed), "output_bytes": len(packed),
        "fallback_ids": [i for i, chunk in enumerate(native) if chunk and i not in ids],
        "method": "Optional palette-bearing pack; per-scene runtime RGB quantization, no global palette change.",
        "limitations": "8-bit color approximation, not lossless Saturn RGB composition; gameplay acceptance pending.",
    }
    output.mkdir(parents=True)
    (output / f"paljpn-{target}.por").write_bytes(packed)
    (output / "generation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=Path)
    parser.add_argument("saturn", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target", required=True, choices=("win", "dos"))
    args = parser.parse_args()
    try:
        report = convert(args.resources.resolve(), args.saturn.resolve(), args.output.resolve(), args.target)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Portrait conversion rejected: {error}\n")
    print(json.dumps({k: report[k] for k in ("target", "output_sha256", "output_bytes", "fallback_ids")}))
