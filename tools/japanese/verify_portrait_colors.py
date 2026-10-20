"""Check Issue 9 RGB composition against the independently verified R1 frames.

Uses the same indexed frames, original portrait packs, resource hashes and
fixtures as R1. New RGB frames must preserve every background pixel and equal
the fitted Saturn RGB at every covered portrait pixel (including black fades).
This is source rendering, not a Saturn/PC gameplay acceptance run.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil

from PIL import Image

from verify_portrait_rendering import (
    FRAME_BYTES, compare_native_menu, load_glyphs, menu_masks, mkf_chunks, nearest,
    read_pack, require, rgb_image, run_renderer, ROOT,
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_rgb(path):
    with Image.open(path) as image:
        return image.convert("RGB")


def check_scales(directory, names):
    expected = {name + suffix + ".bmp" for name in names
                for suffix in ("", "-rgb", "-640", "-800", "-960")}
    require({p.name for p in directory.glob("*.bmp")} == expected, "BMP set differs")
    for name in names:
        base = load_rgb(directory / (name + "-rgb.bmp"))
        require(base.size == (320, 200), "Wrong composed view dimensions")
        for width in (640, 800, 960):
            image = load_rgb(directory / f"{name}-{width}.bmp")
            require(image.size == (width, width * 5 // 8), "Wrong output size")
            if width != 800:
                require(image.tobytes() == base.resize(image.size, Image.Resampling.NEAREST).tobytes(),
                        f"SDL output differs from CPU RGB composition: {name}/{width}")


def check_night_indices(day, night, colors, portrait, selected_ink):
    """Derive night indices from a hash-bound R1 day frame, not the new frame."""
    expected = bytearray(day.tobytes())
    if portrait is not None:
        (w, h, pixels, mask), x, y = portrait
        before_map, after_map = nearest(colors, bytes(day.getpalette())), nearest(colors, night[1])
        for yy in range(h):
            for xx in range(w):
                at = yy*w+xx
                if mask[at] and 0 <= x+xx < 320 and 0 <= y+yy < 200:
                    target = (y+yy)*320+x+xx
                    # Later text/icon writes remain unchanged. Same-index
                    # overwrites are also covered independently by C++ tests.
                    if expected[target] == before_map[pixels[at]]:
                        expected[target] = after_map[pixels[at]]
    phases, changed = set(), 0
    for pos, (a, b) in enumerate(zip(expected, night[0])):
        if a != b:
            require(pos in selected_ink and 249 <= a <= 254 and 249 <= b <= 254,
                    f"Night indices differ from independent day remapping at {pos}")
            phases.add((b-a) % 6)
            changed += 1
    if changed:
        require(changed == len(selected_ink) and len(phases) == 1 and
                len({expected[i] for i in selected_ink}) ==
                len({night[0][i] for i in selected_ink}) == 1,
                "Night menu selected-name phase is not uniform")
    return changed


def verify(executable, r1, text_r2, win, dos, output, check_existing=False):
    old_root = r1 / "verification-final2"
    old_report = json.loads((old_root / "verification.json").read_text("utf-8"))
    old = json.loads((output / "verification.json").read_text("utf-8")) if check_existing else None
    if old:
        require(old["executable_sha256"] == digest(executable), "Existing binary changed")
    else:
        require(not output.exists(), "Use a new output directory")
        output.mkdir(parents=True)
    resources = {name: digest(Path(name)) for name in old_report["resources"]}
    require(resources == old_report["resources"], "R1 original resources changed")
    require(digest(r1 / "build/sdlpal.exe") == old_report["executable_sha256"], "R1 binary changed")
    runs, versions = (old["runs"] if old else []), {}
    night_checks = {}
    glyphs = load_glyphs(ROOT, win)
    for version, resource in (("win", win), ("dos", dos)):
        pack = r1 / f"generated-{version}/paljpn-{version}.por"
        require(digest(pack) == old_report["versions"][version]["pack_sha256"], "R1 pack changed")
        colors, entries = read_pack(pack, version)
        pat = resource / "PAT.MKF"
        require(str(pat).lower() in {p.lower() for p in resources},
                "Palette resource is outside the fingerprinted R1 inputs")
        palette0 = mkf_chunks(pat.read_bytes())[0]
        require(len(palette0) == 1536, "Expected day/night palette 0")
        night_palette = bytes(c << 2 for c in palette0[768:])
        slf = text_r2 / f"after/paljpn-{version}.slf"
        require(digest(slf) == old_report["slf_sha256"][version], "SLF changed")
        views = {}
        checks = []
        for style in ("native", "adapted"):
            previous = old_root / f"{version}-{style}"
            destination = output / f"{version}-{style}"
            previous_check = next(c for c in old_report["versions"][version]["probe_checks"]
                                  if c["stage"] == style)
            require(digest(previous / "portrait-frames.bin") == previous_check["frames_sha256"]
                    and digest(previous / "portraits.csv") == previous_check["metadata_sha256"],
                    "R1 indexed evidence changed")
            if not old:
                destination.mkdir()
                shutil.copyfile(previous / "portrait-fixtures.csv", destination / "portrait-fixtures.csv")
                runs.append(run_renderer(executable, resource, slf, destination,
                    "jp-portraits-rgb" if version == "win" else "dos-portraits-rgb",
                    pack if style == "adapted" else None))
            require((previous / "portrait-fixtures.csv").read_bytes() ==
                    (destination / "portrait-fixtures.csv").read_bytes(), "Fixtures changed")
            require((previous / "portraits.csv").read_bytes() ==
                    (destination / "portraits.csv").read_bytes(), "Frame order/metadata changed")
            with (previous / "portrait-fixtures.csv").open(newline="") as stream:
                published = {row["name"] for row in csv.DictReader(stream) if int(row["publish"])}
            with (destination / "portraits.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            count = 0
            with (previous / "portrait-frames.bin").open("rb") as before, \
                 (destination / "portrait-frames.bin").open("rb") as after, \
                 (destination / "portrait-rgb.bin").open("rb") as rgbs:
                for row in rows:
                    a, b, rgb = before.read(FRAME_BYTES), after.read(FRAME_BYTES), rgbs.read(192000)
                    require(len(a) == FRAME_BYTES and b == a, "Indexed frame/palette changed")
                    require(len(rgb) == 192000, "Missing composed frame")
                    expected = rgb_image(a[:64000], a[64000:])
                    face, phase = int(row["face"]), int(row["stage"])
                    if style == "adapted" and face in entries:
                        w, h, pixels, mask = entries[face]
                        level = 0 if phase == 3 or int(row["initial_black"]) and phase < 2 else (
                            32 if phase == 2 else 64)
                        palette = bytes(c * level // 64 for c in colors)
                        portrait = rgb_image(pixels, palette, (w, h))
                        expected.paste(portrait, (int(row["x"]), int(row["y"])),
                                       Image.frombytes("L", (w, h), mask))
                    require(rgb == expected.tobytes(),
                            f"RGB/background/fade mismatch: {version}/{style}/{row}")
                    if phase == 0 and row["name"] in published:
                        path = destination / (row["name"] + "-rgb.bmp")
                        require(load_rgb(path).tobytes() == rgb, "Published RGB is not verified frame")
                        with Image.open(destination / (row["name"] + ".bmp")) as indexed:
                            require(indexed.mode == "P" and indexed.tobytes() == a[:64000] and
                                    bytes(indexed.getpalette()) == a[64000:], "Indexed BMP changed")
                    count += 1
                require(not before.read(1) and not after.read(1) and not rgbs.read(1),
                        "Unexpected trailing frames")
            require(count == previous_check["frames"], "Frame count changed")
            check_scales(destination, published)
            checks.append(dict(style=style, frames=count, indexed_sha256=digest(destination/"portrait-frames.bin"),
                               rgb_sha256=digest(destination/"portrait-rgb.bin"),
                               metadata_sha256=digest(destination/"portraits.csv"),
                               all_rgb_pixels_exact=True, all_indexed_pixels_and_palettes_unchanged=True))
            print(f"{version}/{style}: {count} indexed + RGB frames exact", flush=True)

        # Same actual message lookup, pagination and descriptions as the R1 run.
        # Night dialogue uses the same indexed fallback as the R1 mapper; its
        # 8-bit and composed outputs are kept separately and labelled explicitly.
        selected = menu_masks(version, slf, text_r2 / "verification" / version, glyphs)
        for style, night in (("native", False), ("adapted", False), ("adapted", True)):
            name = f"{version}-dialogue-{style}" + ("-night" if night else "")
            destination = output / name
            previous = old_root / f"{version}-dialogue-{style}"
            if not old:
                destination.mkdir()
                for path in (text_r2 / "verification" / version).glob("*.csv"):
                    shutil.copyfile(path, destination / path.name)
                mode = ("jp-translation" if version == "win" else "dos") + (
                    "-night-rgb" if night else "-rgb")
                runs.append(run_renderer(executable, resource, slf, destination, mode,
                                         pack if style == "adapted" else None))
            expected_csvs = {p.name for p in previous.glob("*.csv")}
            require({p.name for p in destination.glob("*.csv")} == expected_csvs, "CSV set changed")
            for filename in expected_csvs:
                require((destination / filename).read_bytes() == (previous / filename).read_bytes(),
                        f"Lookup/pagination changed: {filename}")
            prior_bmps = {Path(p).name for p in old_report["image_sha256"]
                          if Path(p).parent.as_posix() == previous.name and p.endswith(".bmp")}
            require(prior_bmps and {p.name for p in previous.glob("*.bmp")} == prior_bmps,
                    "R1 dialogue BMP set differs from the verified report")
            base_names = {Path(p).stem for p in prior_bmps
                          if not re.search(r"-(640|800|960)\.bmp$", p)}
            check_scales(destination, base_names)
            with (destination / "recovery-fixtures.csv").open(newline="") as stream:
                fixture = {int(row[0]): tuple(map(int, row[5:9])) for row in csv.reader(stream) if int(row[4])}
            changed, phases = [], []
            for base in sorted(base_names):
                indexed_path = destination / (base + ".bmp")
                with Image.open(indexed_path) as indexed:
                    require(indexed.mode == "P" and indexed.size == (320, 200),
                            "Expected complete indexed dialogue/menu frame")
                    indices, palette = indexed.tobytes(), bytes(indexed.getpalette())
                    fallback = indexed.convert("RGB")
                prior_path = previous / (base + ".bmp")
                require(digest(prior_path) == old_report["image_sha256"][prior_path.relative_to(old_root).as_posix()],
                        "R1 dialogue image changed")
                match = re.match(r"dialogue-(\d+)-page-", base)
                portrait = None
                if style == "adapted" and match:
                    op, face, _, _ = fixture[int(match[1])]
                    if face in entries:
                        w, h, pixels, mask = entries[face]
                        x, y = (max(0, 48-w//2), max(0, 55-h//2)) if op == 60 else (270-w//2, 144-h//2)
                        portrait = entries[face], x, y
                if night:
                    require(palette == night_palette, "Night view does not use original PAT night colors")
                    with Image.open(prior_path) as day:
                        phase = check_night_indices(day, (indices, night_palette), colors, portrait,
                                                    selected.get(base + ".bmp", set()))
                    night_checks[f"{name}/{base}"] = dict(palette_matches_original_pat=True,
                        indices_match_independent_day_remapping=True, selected_ink_phase_pixels=phase)
                if not night:
                    if base.startswith(("item-", "magic-")):
                        phases.append(compare_native_menu(prior_path, indexed_path, selected[base + ".bmp"]))
                    else:
                        with Image.open(prior_path) as prior:
                            require(prior.tobytes() == indices and bytes(prior.getpalette()) == palette,
                                    "Indexed dialogue changed")
                actual = load_rgb(destination / (base + "-rgb.bmp"))
                expected = fallback.copy()
                covered = 0
                if portrait is not None:
                    (w, h, pixels, mask), x, y = portrait
                    mapping = nearest(colors, palette)
                    visible = bytearray(mask)
                    # A later text/icon write owns its pixel. Exact same-index
                    # overwrites are separately exercised by C++ coverage tests.
                    for yy in range(h):
                        for xx in range(w):
                            at = yy*w+xx
                            if not (0 <= x+xx < 320 and 0 <= y+yy < 200) or (
                                indices[(y+yy)*320+x+xx] != mapping[pixels[at]]):
                                visible[at] = 0
                    covered = sum(bool(v) for v in visible)
                    expected.paste(rgb_image(pixels, colors, (w, h)), (x, y),
                                   Image.frombytes("L", (w, h), bytes(visible)))
                require(actual.tobytes() == expected.tobytes(), f"Dialogue RGB/mask changed: {name}/{base}")
                changed.append({"name": base, "source_color_pixels": covered})
            views[name] = {"base_views": len(base_names), "csvs_unchanged": True,
                           "menu_phase_pixels": phases, "rgb_checks": changed}
            print(f"{name}: {len(base_names)} views and all CSVs checked", flush=True)
        versions[version] = dict(pack_sha256=digest(pack), slf_sha256=digest(slf), checks=checks,
                                 views=views, normal_palette_source_rgb_rmse=0,
                                 r1_palette_rmse=old_report["versions"][version]["color_rmse"])
    require(all(digest(Path(p)) == h for p, h in resources.items()), "Resources changed during rendering")
    report = dict(scope="Source RGB composition and SDL output; no real gameplay or Saturn video acceptance.",
                  executable_sha256=digest(executable), prior_report_sha256=digest(old_root/"verification.json"),
                  resources=resources, resources_unchanged=True, runs=runs, versions=versions,
                  night_checks=night_checks,
                  csvs={p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*.csv")},
                  verifier_sha256=digest(Path(__file__)),
                  images={p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*.bmp")})
    if old:
        require(report["images"] == old["images"] and report["versions"] == old["versions"],
                "Previously verified evidence changed")
        if "csvs" in old:
            require(report["csvs"] == old["csvs"], "Previously verified CSV evidence changed")
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print("Portrait RGB verification passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "r1", "text_r2", "win", "dos", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--check-existing", action="store_true")
    verify(**vars(parser.parse_args()))
