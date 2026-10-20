"""Verify optional portraits through the real Test engine, without gameplay.

The palette oracle and PC RLE decoder below are separate from the engine.
Saturn decoder outputs are checked against the independent original-disc audit.
"""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from PIL import Image

from convert_portraits import MANIFEST, decode_saturn, mkf_chunks, read_inputs, require, sha

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from export_japanese_font import load_glyphs
FRAME_BYTES = 320 * 200 + 768
BACKGROUND = bytes((x // 4 + y // 3) & 255 for y in range(200) for x in range(320))


def native_plane(chunk):
    pos = 4 if chunk[:4] == b"\x02\0\0\0" else 0
    width, height = struct.unpack_from("<HH", chunk, pos)
    pos += 4
    pixels, mask, at = bytearray(width * height), bytearray(width * height), 0
    while at < len(pixels):
        op = chunk[pos]
        pos += 1
        if op & 128 and op <= 128 + width:
            count = op - 128
        else:
            count = op
            require(pos + count <= len(chunk), "Short PC literal")
            pixels[at:at+count] = chunk[pos:pos+count]
            mask[at:at+count] = b"\xff" * count
            pos += count
        require(count > 0 and at + count <= width * height, "Bad PC RLE run")
        at += count
    return width, height, bytes(pixels), bytes(mask)


def read_pack(path, version):
    data = path.read_bytes()
    require(data[:8] == b"PALJPOR1", "Bad pack signature")
    revision, target, count, reserved = struct.unpack_from("<4H", data, 8)
    require((revision, target, count, reserved) == (1, version == "win", 86, 0), "Bad pack header")
    palette, pos, entries = data[16:784], 784, {}
    for _ in range(count):
        face, width, height, reserved = struct.unpack_from("<4H", data, pos)
        pos += 8
        pixels = data[pos:pos+width*height]
        require(face not in entries and reserved == 0 and len(pixels) == width*height, "Bad entry")
        entries[face] = (width, height, pixels, bytes(255 if p else 0 for p in pixels))
        pos += width * height
    require(pos == len(data), "Pack trailing data")
    return palette, entries


def rgb_image(indices, palette, size=(320, 200)):
    picture = Image.frombytes("P", size, indices)
    picture.putpalette(palette)
    return picture.convert("RGB")


def overlay(background, plane, left, top, mapping=None):
    width, height, pixels, mask = plane
    result = bytearray(background)
    for y in range(height):
        if not 0 <= top + y < 200:
            continue
        for x in range(width):
            if 0 <= left + x < 320 and mask[y*width+x]:
                value = pixels[y*width+x]
                result[(top+y)*320+left+x] = mapping[value] if mapping is not None else value
    return bytes(result)


def nearest(source, target):
    # Pair ordering makes ties select the smaller color index.
    return bytes(min((sum((source[i*3+k]-target[j*3+k])**2 for k in range(3)), j)
                     for j in range(256) if not 249 <= j <= 254)[1] for i in range(256))


def run_renderer(executable, resource, slf, directory, mode, pack=None):
    command = [str(executable), "--render-evidence", str(resource) + "/",
               str(slf), str(directory), mode] + ([str(pack)] if pack else [])
    process = subprocess.run(command, cwd=directory, capture_output=True, timeout=180)
    log = (process.stdout + process.stderr).decode("utf-8", "replace")
    (directory / "render.log").write_text(log, "utf-8")
    require(process.returncode == 0, f"Renderer failed: {log}")
    return {"command": command, "exit_code": process.returncode, "log": log}


def verify_scales(directory, expected_names):
    expected_files = {name + suffix + ".bmp" for name in expected_names
                      for suffix in ("", "-640", "-800", "-960")}
    require(expected_files and {p.name for p in directory.glob("*.bmp")} == expected_files,
            "Missing/extra BMP views")
    checked = []
    for path in directory.glob("*.bmp"):
        if re.search(r"-(640|800|960)\.bmp$", path.name):
            continue
        with Image.open(path) as image:
            base = image.convert("RGB")
        for width in (640, 960, 800):
            with Image.open(path.with_name(f"{path.stem}-{width}.bmp")) as image:
                scaled = image.convert("RGB")
            require(scaled.size == (width, width * 5 // 8), "Wrong scale dimensions")
            if width != 800:
                require(scaled.tobytes() == base.resize(scaled.size, Image.Resampling.NEAREST).tobytes(),
                        f"Integral GPU scale mismatch: {path}")
        checked.append(path.stem)
    return checked


def compare_native_menu(old, current, selected_ink):
    """Selected-name color is SDL_GetTicks()/100 % 6; its ink mask must agree."""
    with Image.open(old) as a, Image.open(current) as b:
        require(a.mode == b.mode == "P" and a.size == b.size == (320, 200), "Expected indexed menu")
        require(a.getpalette() == b.getpalette(), "Menu palette changed")
        before, after = a.tobytes(), b.tobytes()
    phase_pixels, phases = 0, set()
    for i, (x, y) in enumerate(zip(before, after)):
        if x == y:
            continue
        require(i in selected_ink and 249 <= x <= 254 and 249 <= y <= 254,
                "Menu geometry/nonanimated color changed")
        phases.add((y-x) % 6)
        phase_pixels += 1
    if phase_pixels:
        require(len(phases) == 1 and phase_pixels == len(selected_ink),
                "Selected-name phase is not uniform across the complete glyph mask")
        require(len({before[i] for i in selected_ink}) == len({after[i] for i in selected_ink}) == 1,
                "Inconsistent selected-name color")
    return phase_pixels


def menu_masks(version, slf, fixtures, glyphs):
    body = slf.read_text("utf-8").split("[BEGIN WORDS]\n")[1].split("[END WORDS]")[0]
    names = {int(k): v.strip() for k, v in re.findall(r"^(\d+)=(.*)$", body, re.M)}
    filename = "translation-objects.csv" if version == "win" else "dos-objects.csv"
    with (fixtures / filename).open(newline="") as stream:
        rows = [tuple(map(int, row)) for row in csv.reader(stream)]
    magic_ids = sorted(r[0] for r in rows if not r[1])
    result = {}
    for row in rows:
        face, item = row[:2]
        if version == "dos" and not row[2]:
            continue
        index = magic_ids.index(face) if not item and version == "win" else 0
        left, top = (15, 12) if item else (35+(index % 2)*139, 70+min(index//2, 2)*18)
        ink, advance = set(), 0
        for character in names[face]:
            width, dots, _ = glyphs[ord(character)]
            ink.update((top+y)*320+left+advance+x for x, y in dots)
            advance += width
        require(ink and all(0 <= p < 64000 for p in ink), "Invalid selected-name glyph mask")
        result[f"{'item' if item else 'magic'}-{face}.bmp"] = ink
    return result


def verify(executable, win_dir, dos_dir, saturn_dir, pack_root, previous_r2_dir, output_dir,
           check_existing=False):
    previous_report = None
    if check_existing:
        previous_report = json.loads((output_dir / "verification.json").read_text("utf-8"))
        require(previous_report["executable_sha256"] == sha(executable.read_bytes()),
                "Existing frames were rendered by a different binary")
    else:
        require(not output_dir.exists(), "Use a new verification output directory")
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    source = read_inputs(saturn_dir, manifest["inputs"]["saturn"])
    slot_review = ROOT / "docs/evidence/issue-9-portrait-slots.json"
    independent = json.loads(slot_review.read_text("utf-8"))
    require(len(independent) == 99, "Missing independent slot audit")
    for face, expected in enumerate(independent):
        width, height, pixels, consumed = decode_saturn(source["RGM.JOE"][face*10240:(face+1)*10240])
        require((width, height, sha(pixels), consumed) ==
                (expected["width"], expected["height"], expected["pixels_sha256"], expected["used_bytes"]),
                f"Independent Saturn decoding mismatch: {face}")
    output_dir.mkdir(parents=True, exist_ok=check_existing)
    runs, versions = (previous_report["runs"] if check_existing else []), {}
    glyphs = load_glyphs(ROOT, win_dir)
    published = (1, 37, 38, 55, 70, 84, 88)
    resource_hashes = {str(p): sha(p.read_bytes()) for directory in (win_dir, dos_dir)
                       for p in directory.iterdir() if p.is_file() and p.suffix.lower()
                       in (".mkf", ".msg", ".dat", ".rpg", ".fon", ".asc")}
    if check_existing:
        require(resource_hashes == previous_report["resources"], "Existing run resources changed")
    r2 = json.loads((previous_r2_dir / "verification/verification.json").read_text("utf-8"))
    slf_hashes = {}
    for version in ("win", "dos"):
        slf_hashes[version] = sha((previous_r2_dir / f"after/paljpn-{version}.slf").read_bytes())
        require(slf_hashes[version] == r2["versions"][version]["after"]["sha256"], "R2 SLF changed")
    for version, resource in (("win", win_dir), ("dos", dos_dir)):
        pc = read_inputs(resource, manifest["inputs"][version])
        native = {i: native_plane(c) for i, c in enumerate(mkf_chunks(pc["RGM.MKF"])) if c}
        pack = pack_root / f"generated-{version}" / f"paljpn-{version}.por"
        source_palette, entries = read_pack(pack, version)
        if check_existing:
            require(sha(pack.read_bytes()) == previous_report["versions"][version]["pack_sha256"],
                    "Existing frames used a different portrait pack")
        require(set(entries) == set(manifest["identity_ids"]), "Unreviewed identity in pack")
        require(sha(source_palette) == manifest["palette_rgb24_sha256"], "Wrong source palette")
        # Check fitted planes independently of converter's fit_pixels function.
        for face, (tw, th, pixels, mask) in entries.items():
            sw, sh, original, _ = decode_saturn(source["RGM.JOE"][face*10240:(face+1)*10240])
            require((tw, th) == native[face][:2], "Native layout extent changed")
            ratio = min(tw/sw, th/sh, 1)
            fw, fh = max(1, math.floor(sw*ratio+1e-10)), max(1, math.floor(sh*ratio+1e-10))
            left, top = (tw-fw)//2, (th-fh)//2
            expected = bytearray(tw*th)
            for y in range(fh):
                for x in range(fw):
                    expected[(top+y)*tw+left+x] = original[(y*sh//fh)*sw+x*sw//fw]
            require(bytes(expected) == pixels, f"Aspect-fit mismatch: {face}")
        palettes = {}
        for number, chunk in enumerate(mkf_chunks(pc["PAT.MKF"])):
            require(len(chunk) in (768, 1536), "Unreviewed PC palette")
            for night in range(len(chunk)//768):
                palettes[number, night] = bytes(v << 2 for v in chunk[night*768:(night+1)*768])
        lookup = {key: nearest(source_palette, colors) for key, colors in palettes.items()}
        fixtures = []
        for face in native:
            for number, night in palettes:
                for location in (0, 1):
                    name = f"face-{face}-p{number}-n{night}-l{location}"
                    publish = int(face in published and number == 0 and location == 0)
                    fixtures.append((name, face, location, number, night, publish))
        for face in (1, 72, 84):
            fixtures.append((f"black-face-{face}", face, 0, 0, 0, 2))
        expected_rows = []
        for name, face, location, number, night, publish in fixtures:
            width, height = native[face][:2]
            x, y = ((270-width//2, 144-height//2) if location else
                    (max(0, 48-width//2), max(0, 55-height//2)))
            for phase in range(4 if publish else 1):
                expected_rows.append(dict(name=name, face=face, location=location, palette=number, night=night,
                                          width=width, height=height, x=x, y=y,
                                          offset=len(expected_rows)*FRAME_BYTES,
                                          stage=phase, initial_black=int(publish == 2)))
        published_names = {r[0] for r in fixtures if r[5]}
        probe_checks = []
        for stage in ("native", "adapted"):
            directory = output_dir / f"{version}-{stage}"
            directory.mkdir(exist_ok=check_existing)
            if not check_existing:
                with (directory / "portrait-fixtures.csv").open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(("name", "face", "location", "palette", "night", "publish"))
                    writer.writerows(fixtures)
            else:
                with (directory / "portrait-fixtures.csv").open(newline="") as stream:
                    rows = list(csv.reader(stream))[1:]
                require(rows == [[str(v) for v in row] for row in fixtures], "Existing input fixtures changed")
            slf = previous_r2_dir / "after" / f"paljpn-{version}.slf"
            if not check_existing:
                runs.append(run_renderer(executable, resource, slf, directory,
                                         "jp-portraits" if version == "win" else "dos-portraits",
                                         pack if stage == "adapted" else None))
            frame_count = mapped_count = fallback_count = 0
            with (directory / "portraits.csv").open(newline="") as metadata, \
                 (directory / "portrait-frames.bin").open("rb") as frames:
                for row in csv.DictReader(metadata):
                    values = {k: int(v) for k, v in row.items() if k != "name"}
                    require(frame_count < len(expected_rows) and
                            dict(name=row["name"], **values) == expected_rows[frame_count],
                            "Unexpected/missing/out-of-order portrait metadata")
                    face, phase = values["face"], values["stage"]
                    palette_key = values["palette"], values["night"]
                    palette = palettes[palette_key]
                    use_pack = stage == "adapted" and face in entries
                    plane = entries[face] if use_pack else native[face]
                    require(plane[:2] == (values["width"], values["height"]), "Fixture dimensions changed")
                    expected = overlay(BACKGROUND, plane, values["x"], values["y"],
                                       lookup[palette_key] if use_pack else None)
                    actual = frames.read(FRAME_BYTES)
                    require(len(actual) == FRAME_BYTES and values["offset"] == frame_count * FRAME_BYTES,
                            "Missing/out-of-order frame")
                    require(actual[:64000] == expected, f"Pixel/mask/fallback mismatch: {version}/{stage}/{row}")
                    colors = palette
                    if phase == 3 or values["initial_black"] and phase < 2:
                        colors = bytes(768)
                    elif phase == 1:
                        colors = palette[:249*3] + palette[250*3:255*3] + palette[249*3:250*3] + palette[255*3:]
                    elif phase == 2:
                        colors = bytes(c//2 for c in palette)
                    require(actual[64000:] == colors, "Global palette or fade stage changed")
                    if phase == 0 and row["name"] in published_names:
                        with Image.open(directory / (row["name"]+".bmp")) as image:
                            require(image.size == (320, 200) and image.convert("RGB").tobytes() ==
                                    rgb_image(actual[:64000], actual[64000:]).tobytes(),
                                    "Published BMP does not match its verified indexed frame")
                    if use_pack:
                        require(all(not 249 <= lookup[palette_key][v] <= 254 for v in set(plane[2]) if v),
                                "Portrait uses rotating wait colors")
                        mapped_count += 1
                    else:
                        fallback_count += 1
                    frame_count += 1
                require(frames.read(1) == b"", "Trailing frame data")
                require(frame_count == len(expected_rows), "Missing portrait frames")
            probe_checks.append({"stage": stage, "fixtures": len(fixtures), "frames": frame_count,
                                 "mapped_frames": mapped_count, "native_frames": fallback_count,
                                 "all_indexed_pixels_and_palettes_exact": True,
                                 "initial_black_fixtures": 3, "backup_restore": True,
                                 "expected_frames": len(expected_rows), "published_frames_bound": True,
                                 "frames_sha256": sha((directory/"portrait-frames.bin").read_bytes()),
                                 "metadata_sha256": sha((directory/"portraits.csv").read_bytes()),
                                 "scaled_views": verify_scales(directory, published_names)})
            print(f"{version}/{stage}: {frame_count} full frames verified", flush=True)
        counts = Counter(v for plane in entries.values() for v in plane[2] if v)
        quality = []
        for key, palette in palettes.items():
            def rmse(mapping):
                return math.sqrt(sum(count * sum((source_palette[i*3+k]-palette[mapping[i]*3+k])**2
                                                 for k in range(3)) for i, count in counts.items()) /
                                 (sum(counts.values())*3))
            quality.append({"palette": key[0], "night": key[1],
                            "adapted_rmse": round(rmse(lookup[key]), 4),
                            "unmapped_source_indices_rmse": round(rmse(bytes(range(256))), 4)})
        # Real dialogue/description paths, compared with the prior R2 engine.
        actual_runs, menu_phases = {}, []
        selected_masks = menu_masks(version, previous_r2_dir / "after" / f"paljpn-{version}.slf",
                                    previous_r2_dir / "verification" / version, glyphs)
        old_directory = previous_r2_dir / "render" / f"{version}-after"
        expected_bmps = {p.name for p in old_directory.glob("*.bmp")}
        expected_csvs = {p.name for p in old_directory.glob("*.csv")}
        require(expected_bmps and expected_csvs, "Empty historical evidence")
        for stage in ("native", "adapted"):
            directory = output_dir / f"{version}-dialogue-{stage}"
            directory.mkdir(exist_ok=check_existing)
            for path in (previous_r2_dir / "verification" / version).glob("*.csv"):
                if not check_existing:
                    shutil.copyfile(path, directory / path.name)
                require(path.read_bytes() == (directory/path.name).read_bytes(), "Input dialogue fixture changed")
            if not check_existing:
                runs.append(run_renderer(executable, resource, previous_r2_dir / "after" / f"paljpn-{version}.slf",
                                         directory, "jp-translation" if version == "win" else "dos",
                                         pack if stage == "adapted" else None))
            actual_runs[stage] = directory
            require({p.name for p in directory.glob("*.bmp")} == expected_bmps and
                    {p.name for p in directory.glob("*.csv")} == expected_csvs,
                    "Dialogue/menu BMP or CSV coverage changed")
            for path in directory.glob("*.csv"):
                if path.name.endswith("fixtures.csv") or path.name == "translation-objects.csv":
                    continue
                old = previous_r2_dir / "render" / f"{version}-after" / path.name
                require(old.read_text() == path.read_text(), f"Lookup/pagination/description changed: {path.name}")
            if stage == "native":
                for path in directory.glob("*.bmp"):
                    if re.search(r"-(640|800|960)\.bmp$", path.name):
                        continue
                    old = previous_r2_dir / "render" / f"{version}-after" / path.name
                    if path.name.startswith(("item-", "magic-")):
                        menu_phases.append({"comparison": "prior_r2", "file": path.name,
                                            "phase_pixels": compare_native_menu(old, path, selected_masks[path.name])})
                    else:
                        with Image.open(old) as a, Image.open(path) as b:
                            require(a.convert("RGB").tobytes() == b.convert("RGB").tobytes(),
                                    f"Default native rendering regression: {path}")
            verify_scales(directory, {Path(n).stem for n in expected_bmps
                                      if not re.search(r"-(640|800|960)\.bmp$", n)})
        fixtures_by_key = {}
        with (actual_runs["native"] / "recovery-fixtures.csv").open(newline="") as stream:
            for row in csv.reader(stream):
                if int(row[4]):
                    fixtures_by_key[int(row[0])] = tuple(map(int, row[5:9]))
        differences = []
        for path in actual_runs["native"].glob("*.bmp"):
            if re.search(r"-(640|800|960)\.bmp$", path.name):
                continue
            if path.name.startswith(("item-", "magic-")):
                menu_phases.append({"comparison": "pack_enabled", "file": path.name,
                                    "phase_pixels": compare_native_menu(path, actual_runs["adapted"] / path.name,
                                                                       selected_masks[path.name])})
                differences.append({"file": path.name, "changed_pixels": 0,
                                    "menu_indexed_pixels_equal_except_selected_ink_phase": True})
                continue
            with Image.open(path) as image:
                a = image.convert("RGB")
            with Image.open(actual_runs["adapted"] / path.name) as image:
                b = image.convert("RGB")
            allowed = bytearray(64000)
            match = re.match(r"dialogue-(\d+)-page-", path.name)
            if match:
                op, face, _, _ = fixtures_by_key[int(match[1])]
                if face in entries:
                    width, height = native[face][:2]
                    left, top = (max(0, 48-width//2), max(0, 55-height//2)) if op == 60 else (
                        270-width//2, 144-height//2)
                    # Old art may be erased where the new art is transparent.
                    for plane in (native[face], entries[face]):
                        allowed = bytearray(overlay(allowed, (width, height, bytes([1])*(width*height),
                                                             plane[3]), left, top))
            before, after = a.tobytes(), b.tobytes()
            changed = [i for i in range(64000) if before[i*3:i*3+3] != after[i*3:i*3+3]]
            require(all(allowed[i] for i in changed), f"Nonportrait pixel changed: {path.name}")
            differences.append({"file": path.name, "changed_pixels": len(changed),
                                "only_portrait_masks_changed": True})
            if changed:
                for stage in ("native", "adapted"):
                    with Image.open(actual_runs[stage] / path.with_name(path.stem+"-640.bmp").name) as image:
                        image.convert("RGB").save(output_dir / f"{version}-{stage}-{path.stem}.png")
        versions[version] = {"pack_sha256": sha(pack.read_bytes()), "pack_bytes": pack.stat().st_size,
                             "mapped_ids": len(entries), "native_fallback_ids": sorted(set(native)-set(entries)),
                             "palettes": len(palettes), "probe_checks": probe_checks,
                             "color_rmse": quality, "dialogue_pixel_changes": differences,
                             "default_matches_prior_r2_except_menu_highlight_phase": True,
                             "menu_highlight_phase_checks": menu_phases,
                             "engine_csvs_match_prior_r2": True}
    require(all(sha(Path(p).read_bytes()) == digest for p, digest in resource_hashes.items()),
            "Input resources changed")
    report = {"scope": "Source rendering; no game-route or original Saturn live acceptance.",
              "executable_sha256": sha(executable.read_bytes()), "manifest_sha256": sha(MANIFEST.read_bytes()),
              "independent_slot_audit_sha256": sha(slot_review.read_bytes()),
              "saturn_slots_crosschecked": 99, "resources": resource_hashes, "resources_unchanged": True,
              "slf_sha256": slf_hashes,
              "versions": versions, "runs": runs,
              "rechecked_existing_frames_without_rerender": check_existing,
              "image_sha256": {p.relative_to(output_dir).as_posix(): sha(p.read_bytes())
                               for pattern in ("*.bmp", "*.png") for p in output_dir.rglob(pattern)},
              "limitations": "Scene-palette quantization, not lossless RGB. Palette stages are direct renderer probes."}
    (output_dir / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("executable", "win_dir", "dos_dir", "saturn_dir", "pack_root", "previous_r2_dir", "output_dir"):
        parser.add_argument(arg, type=lambda p: Path(p).resolve())
    parser.add_argument("--check-existing", action="store_true",
                        help="Recheck a completed run with the same binary/pack; do not invoke the renderer again")
    try:
        result = verify(**vars(parser.parse_args()))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        parser.exit(1, f"Portrait verification failed: {error}\n")
    print("PASS: Win/DOS portraits, palette stages, native fallback, dialogue and menu regression")
