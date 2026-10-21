"""Check Issue #2 Windows GamePath handling against identical PAL98 resources.

Requires Pillow, a Test build, and the archived pre-fix reproduction directory
(reproduction.json, before-ascii BMPs, runtime-ascii, and the Chinese copy).
The original resources are read-only. Output must be a new directory.
"""
import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(renderer, directory, gamepath, slf, config=None):
    directory.mkdir()
    if config is not None:
        (directory / "sdlpal.cfg").write_bytes(config)
    command = [str(renderer), "--render-evidence", gamepath, str(slf), str(directory), "jp"]
    log = directory / "render.log"
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    stopped = None
    started = time.monotonic()
    with log.open("wb") as stream:
        process = subprocess.Popen(command, cwd=directory, stdout=stream,
                                   stderr=subprocess.STDOUT, startupinfo=startup)
        while process.poll() is None:
            if b"FATAL ERROR:" in log.read_bytes():
                stopped = "fatal resource error; terminated this Test child before its dialog wait"
            elif time.monotonic() - started > 60:
                stopped = "timeout"
            if stopped:
                process.kill()
                break
            time.sleep(0.05)
        process.wait()
    record = {"argv": command, "cwd": str(directory), "exit_code": process.returncode,
              "stopped": stopped, "log_sha256": digest(log),
              "log_text": log.read_text("utf-8", errors="replace"),
              "images_sha256": {p.name: digest(p) for p in sorted(directory.glob("*.bmp"))}}
    if config is not None:
        record["config_hex"] = config.hex()
        record["config_sha256"] = digest(directory / "sdlpal.cfg")
        require((directory / "sdlpal.cfg").read_bytes() == config, "Renderer rewrote configuration")
    require(process.returncode == 0 and stopped is None, f"Render failed: {log}")
    require(len(record["images_sha256"]) == 12, f"Expected twelve source-rendered images: {log}")
    return record


def compare(reference, candidate):
    expected = sorted(p.name for p in reference.glob("*.bmp"))
    require(expected == sorted(p.name for p in candidate.glob("*.bmp")), "Different image sets")
    result = {}
    for name in expected:
        with Image.open(reference / name) as left, Image.open(candidate / name) as right:
            require(left.mode == right.mode == "P" and left.getpalette() == right.getpalette(),
                    f"Indexed format or resource palette changed: {name}")
            indexes = (left.tobytes(), right.tobytes())
            a, b = left.convert("RGB"), right.convert("RGB")
        require(a.size == b.size == (320, 200), f"Unexpected image size: {name}")
        # The production selected-label color cycles through F9..FE using
        # SDL_GetTicks (ui.h). Allow only that color substitution, only within
        # the selected 8-fullwidth-character label. Glyph masks, shadows, other
        # labels, descriptions and backgrounds must retain identical indexes.
        bounds = None
        if name.startswith("magic-"):
            ids = [306, 307, 308, 311, 370, 374, 377, 390, 393, 394]
            selected = ids.index(int(name[6:-4]))
            x, y = 35 + selected % 2 * 139, 70 + min(selected // 2, 2) * 18
            bounds = (x, y, x + 128, y + 16)
        elif name == "item-149.bmp":
            bounds = (15, 12, 143, 28)
        animation_pixels = 0
        color_pairs = set()
        for pos, (old, new) in enumerate(zip(*indexes)):
            x, y = pos % 320, pos // 320
            in_label = bounds and bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]
            if in_label and 0xf9 <= old <= 0xfe and 0xf9 <= new <= 0xfe:
                color_pairs.add((old, new))
            if old == new:
                continue
            require(in_label and 0xf9 <= old <= 0xfe and 0xf9 <= new <= 0xfe,
                    f"Non-animation index changed: {name} at {x},{y}: {old}->{new}")
            animation_pixels += 1
        require(len(color_pairs) <= 1, f"Selected-label color is not uniform: {name}")
        raw_a, raw_b = a.tobytes(), b.tobytes()
        changed = sum(raw_a[i:i+3] != raw_b[i:i+3] for i in range(0, len(raw_a), 3))
        result[name] = {"rgb_sha256": hashlib.sha256(b.tobytes()).hexdigest(),
                        "different_pixels": changed, "selected_animation_index_pixels": animation_pixels,
                        "selected_color_pairs": sorted(color_pairs), "unexplained_pixels": 0}
    require((reference / "clipped-ink.csv").read_bytes() ==
            (candidate / "clipped-ink.csv").read_bytes(), "Description clipping report changed")
    return result


def preview(left, right, target, title, font_path):
    font = ImageFont.truetype(str(font_path), 22) if font_path else ImageFont.load_default()
    canvas = Image.new("RGB", (1320, 500), "#f1f3f7")
    draw = ImageDraw.Draw(canvas)
    draw.text((20, 10), title, fill="#202b3d", font=font)
    draw.text((20, 44), "ASCII GamePath / UTF-8 config", fill="#202b3d", font=font)
    draw.text((680, 44), "Chinese GamePath / UTF-8 config", fill="#202b3d", font=font)
    for path, x in ((left, 20), (right, 680)):
        with Image.open(path) as source:
            canvas.paste(source.convert("RGB").resize((640, 400), Image.Resampling.NEAREST), (x, 80))
    canvas.save(target)
    with Image.open(target) as reopened:
        require(reopened.mode == "RGB" and reopened.tobytes() == canvas.tobytes(),
                "Published preview must be opaque and lossless")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("renderer", type=Path)
    parser.add_argument("reproduction", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--caption-font", type=Path)
    args = parser.parse_args()
    require(os.name == "nt", "This verification targets the Windows file-opening chain")
    exe, base, out = (p.resolve() for p in (args.renderer, args.reproduction, args.output))
    before = json.loads((base / "reproduction.json").read_text("utf-8"))
    original = Path(before["resource_source"])
    require(not out.exists() and not out.is_relative_to(original), "Use a new external output directory")
    paths = {"ascii": base / "runtime-ascii", "chinese": base / "中文资源-仙剑98", "original": original}
    expected = before["resources_sha256"]
    for directory in paths.values():
        require(all(digest(directory / name) == value for name, value in expected.items()),
                f"Input fingerprint differs: {directory}")
    slf = base / "paljpn-win.slf"
    require(digest(slf) == before["slf_sha256"], "SLF differs from baseline")
    require(digest(base / "before/build/sdlpal.exe") == before["exe_sha256"], "Baseline executable changed")
    for name, value in before["runs"]["ascii"]["images"].items():
        require(digest(base / "before-ascii" / name) == value, f"Baseline image changed: {name}")
    require(len(before["runs"]["ascii"]["images"]) == 12, "Incomplete baseline images")
    require("File open error(2): fbp.mkf!" in before["runs"]["chinese"]["log_text"]
            and not before["runs"]["chinese"]["images"], "Expected the recorded Chinese-path failure")
    acp = ctypes.windll.kernel32.GetACP()
    out.mkdir(parents=True)
    record = {"base": before["base"], "system_acp": acp, "resource_source": str(original),
              "resources_sha256": expected, "slf_sha256": digest(slf), "executable_sha256": digest(exe),
              "verifier_sha256": digest(Path(__file__)), "reproduction_sha256": digest(base / "reproduction.json"),
              "baseline": before, "runs": {}, "previews": {}, "live_acceptance": "deferred"}
    cases = [("argv-ascii", "ascii", None), ("argv-chinese", "chinese", None),
             ("config-ascii-utf8", "ascii", "utf-8"), ("config-chinese-utf8", "chinese", "utf-8"),
             ("config-chinese-acp", "chinese", f"cp{acp}"), ("config-original-utf8", "original", "utf-8")]
    for name, path_key, encoding in cases:
        # Config uses native backslashes without a trailing separator; argv uses
        # forward slashes with one. Both enter production path resolution.
        path = paths[path_key]
        config = ("GamePath=" + str(path) + "\n").encode(encoding) if encoding else None
        record["runs"][name] = run(exe, out / name, "@config" if encoding else path.as_posix() + "/", slf, config)
    reference = out / "config-ascii-utf8"
    record["baseline_ascii_comparison"] = compare(base / "before-ascii", reference)
    for name, _, _ in cases:
        record["runs"][name]["rgb_comparison"] = compare(reference, out / name)
    for image, name, title in (
        ("aunt-dialogue.bmp", "dialogue.png", "Source-rendered dialogue / same resources and glyphs"),
        ("item-149.bmp", "red-silkworm.png", "Source-rendered item 149 / same text; selection color animates"),
        ("magic-377.bmp", "magic.png", "Source-rendered magic 377 / same text; selection color animates"),
    ):
        preview(reference / image, out / "config-chinese-utf8" / image, out / name, title, args.caption_font)
        record["previews"][name] = digest(out / name)
    require(all(digest(original / name) == value for name, value in expected.items()), "Original resource changed")
    record["original_resources_unchanged"] = True
    (out / "verification.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8", newline="\n")
    changed = {name: sum(p["different_pixels"] for p in result["rgb_comparison"].values())
               for name, result in record["runs"].items()}
    print(json.dumps({"runs": len(cases), "frames": 12 * len(cases), "raw_different_pixels": changed,
                      "unexplained_pixels": 0, "baseline_ascii_frames_compared": 12, "system_acp": acp,
                      "previews": list(record["previews"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
