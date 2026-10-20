"""Independent RGB oracle for the real engine's portrait effect traces.

Input frames contain 64000 indexed bytes, 768 palette bytes, then 192000 RGB
bytes observed after upload. The source palette/masks come from the reviewed
portrait pack, never from the candidate RGB. Original and changed executables
must use the same Test harness; inputs and all evidence are fingerprinted.
"""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from verify_portrait_rendering import read_pack, mkf_chunks, require

SIZE = 64000 + 768 + 192000
TIMED = {"red-to-black", "black-to-palette5"}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(directory):
    with (directory / "effects.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    require((directory / "effects.bin").stat().st_size == len(rows) * SIZE, "Trace size")
    data = np.memmap(directory / "effects.bin", dtype=np.uint8, mode="r", shape=(len(rows), SIZE))
    groups = defaultdict(list)
    for sequence, row in enumerate(rows):
        require(sequence == int(row["sequence"]), "Trace order")
        group = groups[row["effect"]]
        require(len(group) == int(row["frame"]), "Effect frame order")
        group.append(sequence)
    return data, groups


def split(row):
    return (row[:64000].reshape(200, 320), row[64000:64768].reshape(256, 3),
            row[64768:].reshape(200, 320, 3))


def placed(entry, lower):
    w, h, data, _ = entry
    x = 270-w//2 if lower else 0 if w > 96 else 48-w//2
    y = 144-h//2 if lower else 0 if h > 110 else 55-h//2
    out = np.zeros((200, 320), np.uint8)
    pixels = np.frombuffer(data, np.uint8).reshape(h, w)
    out[max(0, y):min(200, y+h), max(0, x):min(320, x+w)] = pixels[
        max(0, -y):min(h, 200-y), max(0, -x):min(w, 320-x)]
    return out


def approach(start, target, amount):
    return start + np.clip(target-start, -amount, amount)


def composed(row, plane, colors):
    idx, pal, _ = split(row)
    out = pal[idx].copy()
    mask = plane != 0
    out[mask] = colors[plane[mask]]
    return out


def check_pixels(actual, expected, context):
    if not np.array_equal(actual, expected):
        wrong = np.any(actual != expected, axis=2)
        y, x = np.argwhere(wrong)[0]
        raise AssertionError(f"{context}: {int(wrong.sum())} pixels differ; "
            f"({x},{y}) actual={actual[y,x].tolist()} expected={expected[y,x].tolist()}")


def verify(before, after, pack, version, resource):
    before_run = json.loads((before / "run.json").read_text("utf-8"))
    after_run = json.loads((after / "run.json").read_text("utf-8"))
    for run in (before_run, after_run):
        require(run["exit_code"] == 0 and sha(Path(run["command"][0])) == run["executable_sha256"],
                "Unverified executable")
        require(sha(Path(run["command"][3])) == run["slf_sha256"], "Text input changed")
    for key in ("harness_sha256", "slf_sha256", "portrait_sha256"):
        require(before_run[key] == after_run[key], "Comparison input/harness changed")
    require(before_run["command"][2:4] == after_run["command"][2:4] and
            before_run["command"][5:] == after_run["command"][5:], "Resource/config mismatch")
    require(after_run["portrait_sha256"] in (None, sha(pack)), "Portrait input changed")
    old, old_groups = load(before)
    new, groups = load(after)
    require(old_groups.keys() == groups.keys(), "Effect set changed")
    counts = {"initial": 1, "target": 1, "color-to": 65, "color-from": 65,
              "red": 33, "night-to-day": 32, "day-to-night": 32, "red-to-night": 32,
              "wave": 32, "switch": 7, "dissolve": 73, "dissolve-shake": 73,
              "fbp": 97, "battle": 73, "scene-in": 4, "scene-out": 4}
    require(set(groups) == set(counts) | TIMED, "Incomplete effect set")
    for effect, count in counts.items():
        require(len(groups[effect]) == count, f"Incomplete {effect}")
    palette, entries = read_pack(pack, version)
    colors = np.frombuffer(palette, np.uint8).reshape(256, 3).astype(np.int32)
    enabled = after.name.endswith("-adapted")
    a = placed(entries[55], False) if enabled else np.zeros((200, 320), np.uint8)
    b = placed(entries[70], True) if enabled else a.copy()
    union = (a != 0) | (b != 0)
    initial = new[groups["initial"][0]]
    target = new[groups["target"][0]]
    start_rgb = composed(initial, a, colors).astype(np.int32)
    target_rgb = composed(target, b, colors).astype(np.int32)
    night = split(initial)[1].astype(np.int32)
    solid = night[0x7f]
    red = np.zeros((256, 3), np.int32)
    red[:, 0] = colors.sum(axis=1)//4+64
    pat5 = np.frombuffer(mkf_chunks((resource / "PAT.MKF").read_bytes())[5][:768],
                        np.uint8).astype(np.int32).reshape(256, 3)*4
    red_scene = split(new[groups["red"][-1]])[1].astype(np.int32)
    stage_order = np.argsort(np.array([0, 3, 1, 5, 2, 4]))
    residues = np.arange(64000).reshape(200, 320) % 6
    report, changed = {}, 0
    for effect, sequences in groups.items():
        originals = old_groups[effect]
        if effect not in TIMED:
            require(len(sequences) == len(originals), f"Frame count {effect}")
        compared, differences, levels = 0, 0, []
        for frame, sequence in enumerate(sequences):
            row = new[sequence]
            idx, pal, actual = split(row)
            if effect in TIMED:
                scale_base = red_scene if effect == "red-to-black" else pat5
                levels_here = [n for n in range(65) if np.array_equal(scale_base*n//64, pal)]
                require(len(levels_here) == 1, f"Ambiguous timed fade level {effect}/{frame}")
                level = levels_here[0]
                levels.append(level)
                candidates = [o for o in originals if np.array_equal(old[o, :64768], row[:64768])]
                # Wall-clock loops may skip different levels. The palette must
                # still equal the independently reconstructed original effect.
                compare = old[candidates[0]] if candidates else None
                require(np.array_equal(idx, split(new[groups["red"][-1]])[0]),
                        "Timed fade changed indices")
            else:
                compare = old[originals[frame]]
                require(np.array_equal(compare[:64768], row[:64768]),
                        f"Native indices/palette changed {effect}/{frame}")
            expected = pal[idx].copy()
            if effect in {"initial", "target", "color-to", "color-from", "red",
                          "red-to-black", "black-to-palette5", "night-to-day", "day-to-night",
                          "red-to-night"}:
                source_colors = colors
                if effect == "color-to":
                    source_colors = approach(colors, solid, 4*(frame+1))
                elif effect == "color-from":
                    source_colors = approach(np.broadcast_to(solid, colors.shape), colors, 4*(frame+1))
                elif effect == "red":
                    source_colors = approach(colors, red, 8*frame)
                elif effect in TIMED:
                    source_colors = (red if effect == "red-to-black" else colors)*level//64
                elif effect == "red-to-night":
                    source_colors = (red*(31-frame)+colors*frame)//31
                plane = b if effect == "target" else a
                mask = plane != 0
                expected[mask] = source_colors[plane[mask]]
            elif effect == "wave":
                wave = []
                displacement = 0
                for n in range(16):
                    displacement += 60-8*n
                    wave.append(displacement*64//256)
                wave += [320-offset for offset in wave]
                expected = np.empty((200, 320, 3), np.uint8)
                for y in range(200):
                    offset = wave[(frame+y) % 32]
                    expected[y] = np.roll(start_rgb[y], -offset, axis=0)
                    require(np.array_equal(idx[y], np.roll(split(initial)[0][y], -offset)),
                            "Wave geometry changed")
            elif effect in {"switch", "dissolve", "dissolve-shake", "battle", "fbp"}:
                steps = 1 if effect == "switch" else 16 if effect == "fbp" else 12
                if frame < steps*6:
                    progress = (frame//6 + (stage_order[residues] <= frame % 6))[..., None]
                    end = (split(new[sequences[-1]])[1][split(new[sequences[-1]])[0]]
                           if effect == "fbp" else target_rgb)
                    blend = (start_rgb*(steps-progress)+end.astype(np.int32)*progress)//steps
                    mask = a != 0 if effect == "fbp" else union
                    expected[mask] = blend[mask]
                elif effect != "fbp":
                    mask = b != 0
                    expected[mask] = target_rgb[mask]
                if effect == "dissolve-shake" and frame < 72:
                    unshifted = expected.copy()
                    expected[:] = 0
                    if frame % 2:
                        expected[:-3] = unshifted[3:]
                    else:
                        expected[3:] = unshifted[:-3]
            elif effect not in {"scene-out", "scene-in"}:
                raise AssertionError("Unhandled effect " + effect)
            check_pixels(actual, expected, f"{after.name}/{effect}/{frame}")
            if compare is not None:
                compared += 1
                different = int(np.any(split(compare)[2] != actual, axis=2).sum())
                if not enabled:
                    require(different == 0, f"Native RGB changed {effect}/{frame}")
                differences += different
        if effect in TIMED:
            require(levels[-1] == (0 if effect == "red-to-black" else 64) and
                    any(0 < n < 60 for n in levels), "Timed fade lacks endpoint/intermediate")
        report[effect] = {"frames": len(sequences), "before_frames": len(originals),
                          "identical_index_palette_pairs": compared,
                          "changed_rgb_pixels": differences}
        if levels:
            report[effect]["observed_levels"] = levels
        changed += differences
    gpu_checks = 0
    for directory, data, mapping in ((before, old, old_groups), (after, new, groups)):
        for effect, sequences in mapping.items():
            for frame, sequence in enumerate(sequences):
                gpu = directory / f"{effect}-{frame}-640.bmp"
                if frame in {0, 15, 31, 71, 95}:
                    require(gpu.exists(), f"Missing SDL readback {gpu.name}")
                    with Image.open(gpu) as image:
                        check_pixels(np.asarray(image.convert("RGB")),
                            np.repeat(np.repeat(split(data[sequence])[2], 2, 0), 2, 1),
                            f"SDL texture {gpu.name}")
                    gpu_checks += 1
    require(not enabled or changed > 0, "No before/after color difference")
    return {"frames": len(new), "before_frames": len(old), "effects": report,
            "sdl_readbacks": gpu_checks,
            "changed_rgb_pixels": changed, "files": {
                str(p): sha(p) for directory in (before, after)
                for p in sorted(directory.iterdir()) if p.suffix in {".bin", ".csv", ".bmp", ".json"}}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifacts", "r1", "win", "dos"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--version", choices=["win", "dos"])
    parser.add_argument("--style", choices=["native", "adapted"])
    args = parser.parse_args()
    checks = {}
    for version in ([args.version] if args.version else ["win", "dos"]):
        for style in ([args.style] if args.style else ["native", "adapted"]):
            name = version + "-" + style
            checks[name] = verify(args.artifacts / "effects" / ("before-" + name),
                args.artifacts / "effects" / ("after-" + name),
                args.r1 / f"generated-{version}/paljpn-{version}.por", version, getattr(args, version))
            print(name, checks[name]["frames"], "frames: independent RGB, indices/palette, SDL readback passed")
    report = {"scope": "Source render; no gameplay or Saturn hardware equivalence claimed",
              "checks": checks}
    (args.artifacts / ("effects-verification" + ("-" + args.version if args.version else "") +
        ("-" + args.style if args.style else "") + ".json")).write_text(
            json.dumps(report, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
