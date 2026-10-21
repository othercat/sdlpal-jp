"""Verify #9 config save/restart/opt-out on copied resources, without gameplay.

Only Test binaries accept these commands. Never writes to the original resources
or to a user's active config. SDL2 renders; SDL1 exercises file roundtrips only.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from PIL import Image, ImageDraw, ImageFont

from verify_portrait_colors import check_scales
from verify_portrait_rendering import (
    BACKGROUND, FRAME_BYTES, mkf_chunks, native_plane, nearest, overlay,
    read_pack, require, rgb_image,
)

FIXTURES = [("upper-day", 55, 0, 0, 0, 1), ("upper-night", 55, 0, 0, 1, 1),
            ("lower-day", 55, 1, 0, 0, 1), ("lower-night", 55, 1, 0, 1, 1)]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_config(data):
    result = {}
    for line in data.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        require(key not in result, "Duplicate evidence config key")
        result[key] = value
    return result


def check_saved(original, saved, clear=False):
    expected, actual = parse_config(original), parse_config(saved)
    for key, value in expected.items():
        if key == "PortraitFileName" and clear:
            require(key not in actual, "Portrait opt-out was not persisted")
        else:
            require(actual.get(key) == value, f"Saved config changed {key}")
    if clear:
        require("PortraitFileName" not in actual, "Opt-out retained a portrait pack")


def exact_outputs(left, right):
    def files(root):
        return {p.name: digest(p) for p in root.iterdir()
                if p.suffix in (".bin", ".bmp", ".csv")}
    a, b = files(left), files(right)
    require("portrait-frames.bin" in a and "portrait-rgb.bin" in a and "portraits.csv" in a,
            "Missing source frames")
    require(a == b, f"Source output changed: {left.name}/{right.name}")
    return len(a)


def check_backend(log, backend):
    versions = re.findall(r"^Config backend: SDL (\d+)\.(\d+)\.(\d+)\r?$", log, flags=re.M)
    require(len(versions) == 1 and int(versions[0][0]) == int(backend[-1]),
            "Config executable SDL version does not match its backend label")
    return ".".join(versions[0])


def bind_frame_images(directory, name, indices, palette, expected_rgb):
    with Image.open(directory / (name + ".bmp")) as indexed:
        require(indexed.mode == "P" and indexed.size == (320, 200) and
                indexed.tobytes() == indices and bytes(indexed.getpalette()) == palette,
                "Published indexed BMP is not its independently verified frame")
    with Image.open(directory / (name + "-rgb.bmp")) as rgb:
        require(rgb.size == (320, 200) and rgb.convert("RGB").tobytes() == expected_rgb.tobytes(),
                "Published RGB BMP is not its independently verified frame")


def verify_frames(directory, resource, pack, version, adapted):
    colors, entries = read_pack(pack, version)
    native = native_plane(mkf_chunks((resource / "RGM.MKF").read_bytes())[55])
    pat = mkf_chunks((resource / "PAT.MKF").read_bytes())[0]
    raw = (directory / "portrait-frames.bin").read_bytes()
    rgb = (directory / "portrait-rgb.bin").read_bytes()
    with (directory / "portraits.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 16 and len(raw) == 16 * FRAME_BYTES and len(rgb) == 16 * 192000,
            "Incomplete config source evidence")
    for index, row in enumerate(rows):
        name, face, location, palette_num, night, publish = FIXTURES[index // 4]
        stage = index % 4
        width, height = native[:2]
        x, y = ((270 - width // 2, 144 - height // 2) if location else
                (max(0, 48 - width // 2), max(0, 55 - height // 2)))
        expected_row = dict(name=name, face=face, location=location, palette=palette_num,
                            night=night, width=width, height=height, x=x, y=y,
                            offset=index * FRAME_BYTES, stage=stage, initial_black=0)
        require(row == {key: str(value) for key, value in expected_row.items()}, "Frame order changed")
        palette = bytes(c << 2 for c in pat[night * 768:(night + 1) * 768])
        plane = entries[face] if adapted else native
        require(plane[:2] == native[:2], "Portrait extent changed")
        indices = overlay(BACKGROUND, plane, x, y, nearest(colors, palette) if adapted else None)
        if stage == 1:
            palette = palette[:747] + palette[750:765] + palette[747:750] + palette[765:]
        elif stage == 2:
            palette = bytes(c // 2 for c in palette)
        elif stage == 3:
            palette = bytes(768)
        require(raw[index * FRAME_BYTES:(index + 1) * FRAME_BYTES] == indices + palette,
                "Config source indices or palette differ from resource oracle")
        expected_rgb = rgb_image(indices, palette)
        if adapted:
            source_colors = colors if stage < 2 else bytes(c // 2 for c in colors) if stage == 2 else bytes(768)
            portrait = rgb_image(plane[2], source_colors, plane[:2])
            expected_rgb.paste(portrait, (x, y), Image.frombytes("L", plane[:2], plane[3]))
        require(rgb[index * 192000:(index + 1) * 192000] == expected_rgb.tobytes(),
                "Config source RGB differs from independent portrait formula")
        if stage == 0:
            bind_frame_images(directory, name, indices, palette, expected_rgb)
    check_scales(directory, [f[0] for f in FIXTURES])
    return dict(logical_frames=16, complete_integer_scale_readbacks=8, fractional_size_checks=4)


def run(command, cwd, label, records):
    env = os.environ.copy()
    env["SDL_STDIO_REDIRECT"] = "0"
    started = time.monotonic()
    reason = None
    log = cwd / (label + ".log")
    with log.open("wb") as stream:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        while process.poll() is None:
            time.sleep(0.1)
            logs = b"".join(p.read_bytes() for p in (log, cwd / "sdlpal.log", cwd / "stderr.txt") if p.exists())
            if time.monotonic() - started > 60 or b"FATAL ERROR" in logs:
                reason = "timeout" if time.monotonic() - started > 60 else "fatal log"
                process.terminate()
                process.wait(timeout=10)
    record = dict(command=command, cwd=str(cwd), exit=process.returncode, terminated=reason,
                  log=str(log), log_sha256=digest(log), seconds=round(time.monotonic() - started, 3))
    records.append(record)
    require(process.returncode == 0 and reason is None, f"Failed {label}: {log}")
    return log.read_text("utf-8", errors="replace")


def preview(output, font):
    image = Image.new("RGB", (1320, 586), "#eef2f7")
    draw = ImageDraw.Draw(image)
    heading = ImageFont.truetype(str(font), 22)
    label = ImageFont.truetype(str(font), 17)
    for row, version in enumerate(("win", "dos")):
        directory = output / f"{version}-absolute"
        for col, (state, text) in enumerate((("before", "保存前：土星头像"),
                                            ("after", "保存并重启：像素相同"),
                                            ("disabled", "关闭后重启：恢复 PC 头像"))):
            x, y = 12 + col * 436, 12 + row * 270
            draw.text((x, y), version.upper() + "  " + text, fill="#18324f", font=heading)
            with Image.open(directory / state / "upper-night-rgb.bmp") as frame:
                # Crop the same real source rectangle; no pixel repainting.
                image.paste(frame.convert("RGB").crop((0, 0, 145, 110)).resize((290, 220), Image.Resampling.NEAREST),
                            (x + 67, y + 34))
    draw.text((12, 552), "源码夹具 · 夜景 · Japanese 16px · 不透明 RGB · 实机待统一验收", fill="#18324f", font=label)
    path = output / "config-restart.png"
    image.save(path)
    return {"path": str(path), "sha256": digest(path)}


def verify(args):
    require(not args.output.exists(), "Use a new output directory")
    args.output.mkdir(parents=True)
    report = dict(scope="Source config save/restart/opt-out; no live acceptance", runs=[], cases={})
    report["executables"] = {name: {"path": str(path), "sha256": digest(path)}
                             for name, path in (("sdl1", args.sdl1), ("sdl2", args.sdl2))}
    original_inputs = {}
    for version, original in (("win", args.win), ("dos", args.dos)):
        for style in ("relative", "absolute"):
            case = args.output / f"{version}-{style}"
            case.mkdir()
            resource = case / ("resource" if style == "relative" else "中文资源")
            resource.mkdir()
            copied_inputs = {}
            for source in original.iterdir():
                if source.is_file() and source.suffix.lower() in (".mkf", ".msg", ".dat", ".fon", ".desc"):
                    destination = resource / source.name.upper()
                    shutil.copy2(source, destination)
                    original_inputs[str(source)] = digest(source)
                    require(digest(destination) == digest(source), "Resource copy differs")
                    copied_inputs[destination] = digest(source)
            slf = args.text / "after" / f"paljpn-{version}.slf"
            pack = args.portraits / f"generated-{version}" / f"paljpn-{version}.por"
            slf_copy = resource / ("messages.slf" if style == "relative" else "日文对白.slf")
            pack_copy = resource / ("portraits.por" if style == "relative" else "土星头像.por")
            for source, destination in ((slf, slf_copy), (pack, pack_copy)):
                shutil.copy2(source, destination)
                original_inputs[str(source)] = digest(source)
                require(digest(destination) == digest(source), "Translation/portrait copy differs")
                copied_inputs[destination] = digest(source)
            paths = {"GamePath": "resource/" if style == "relative" else resource.as_posix() + "/",
                     "MessageFileName": slf_copy.name if style == "relative" else slf_copy.as_posix(),
                     "PortraitFileName": pack_copy.name if style == "relative" else pack_copy.as_posix()}
            common = ("WindowWidth=640\nWindowHeight=400\nTextureWidth=320\nTextureHeight=200\n"
                      "EnableGLSL=0\nEnableHDR=0\nUseTouchOverlay=0\nFullScreen=0\n"
                      "KeepAspectRatio=1\nScaleQuality=0\nLaunchSetting=0\n")
            native_config = common + "".join(f"{k}={v}\n" for k, v in paths.items() if k != "PortraitFileName")
            adapted_config = native_config + "PortraitFileName=" + paths["PortraitFileName"] + "\n"
            config = case / "sdlpal.cfg"
            configurations = {}
            checks = {}

            def set_config(content, name):
                if config.exists():
                    shutil.copy2(config, case / (name + "-previous.cfg"))
                config.write_text(content, encoding="utf-8", newline="\n")

            def render(state, adapted):
                destination = case / state
                destination.mkdir()
                with (destination / "portrait-fixtures.csv").open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(("name", "face", "location", "palette", "night", "publish"))
                    writer.writerows(FIXTURES)
                mode = "jp-portraits-rgb" if version == "win" else "dos-portraits-rgb"
                log = run([str(args.sdl2), "--render-evidence", "@config", "@config", str(destination), mode],
                          case, "render-" + state, report["runs"])
                config_line = (f"Config-only inputs: GamePath={paths['GamePath']}; "
                               f"MessageFileName={paths['MessageFileName']}; PortraitFileName=" +
                               (paths['PortraitFileName'] if adapted else "(none)"))
                require(config_line in log and "Renderer: direct3d" in log,
                        "Missing actual config-only renderer evidence")
                configurations[state] = config.read_text("utf-8")
                checks[state] = verify_frames(destination, resource, pack_copy, version, adapted)

            set_config(native_config, "native")
            render("native", False)
            set_config(adapted_config, "adapted")
            render("before", True)
            for backend in ("sdl1", "sdl2"):
                # Each backend reads the same isolated config; preserve the bytes
                # before every production save, including the reset between them.
                set_config(adapted_config, backend + "-initial")
                shutil.copy2(config, case / (backend + "-before.cfg"))
                log = run([str(getattr(args, backend)), "--config-roundtrip-evidence", "keep"],
                          case, backend + "-keep", report["runs"])
                require("Config save/reload passed: keep" in log, "No same-process reload evidence")
                check_backend(log, backend)
                saved = config.read_bytes()
                check_saved(adapted_config.encode("utf-8"), saved)
                shutil.copy2(config, case / (backend + "-saved.cfg"))
                if backend == "sdl2":
                    render("after", True)
                log = run([str(getattr(args, backend)), "--config-roundtrip-evidence", "clear-portrait"],
                          case, backend + "-clear", report["runs"])
                check_backend(log, backend)
                check_saved(saved, config.read_bytes(), clear=True)
                shutil.copy2(config, case / (backend + "-disabled.cfg"))
                if backend == "sdl2":
                    render("disabled", False)
            matches = {"save_restart": exact_outputs(case / "before", case / "after"),
                       "opt_out_native": exact_outputs(case / "native", case / "disabled")}
            changed = sum(a != b for a, b in zip((case / "before/portrait-rgb.bin").read_bytes(),
                                                (case / "native/portrait-rgb.bin").read_bytes()))
            require(changed > 0, "Enabled pack must visibly differ from the native control")
            require(all(digest(path) == value for path, value in copied_inputs.items()), "Copied input changed")
            report["cases"][case.name] = dict(configurations=configurations, checks=checks,
                equal_output_files=matches, enabled_vs_native_changed_rgb_bytes=changed,
                files={p.relative_to(case).as_posix(): digest(p) for p in case.rglob("*") if p.is_file()})
            (args.output / "verification-in-progress.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{case.name}: config roundtrips, 64 source frames and opt-out passed", flush=True)
    require(all(digest(Path(path)) == value for path, value in original_inputs.items()), "Original input changed")
    report["original_inputs"] = original_inputs
    report["original_inputs_preserved"] = True
    report["summary"] = dict(config_roundtrips=16, source_processes=16, logical_frames=256,
                             integer_scale_readbacks=128, fractional_scale_size_checks=64,
                             live_acceptance="pending")
    report["preview"] = preview(args.output, args.font)
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sdl2", "sdl1", "win", "dos", "portraits", "text", "output", "font"):
        parser.add_argument(name, type=lambda value: Path(value).resolve())
    result = verify(parser.parse_args())
    print(json.dumps(result["summary"], ensure_ascii=False))
