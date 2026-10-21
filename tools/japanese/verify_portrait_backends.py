"""Check SDL1 indexed fallback and SDL2/GLSL source-evidence outputs.

Each run reuses the R3 independent effect oracle. Cross-backend index/palette
comparisons use the native SDL2 run; wall-clock fades are verified by the oracle
at their observed palette levels rather than forcing equal frame counts.
"""
import argparse
import json
from pathlib import Path
import re

import numpy as np

from verify_portrait_effects import TIMED, load, sha, split, verify
from verify_portrait_rendering import require


def check_backend(record, log, backend, version, style):
    require((record["backend"], record["version"], record["style"]) == (backend, version, style),
            "Backend label does not match executed case")
    glsl = backend.startswith("glsl")
    mode = ("jp" if version == "win" else "dos") + "-portrait-effects" + ("-glsl" if glsl else "")
    require(record["command"][1:3] == ["--render-evidence", "@config"] and record["command"][5] == mode,
            "Wrong rendering entry")
    require(len(record["command"]) == (7 if style == "adapted" else 6), "Wrong portrait setting")
    require(bool(record["portrait_sha256"]) == (style == "adapted"), "Wrong portrait fingerprint")
    if backend == "sdl1":
        require("Renderer: SDL1 dummy; indexed palette fallback; 640x400" in log, "SDL1 dummy not observed")
    else:
        require(re.search(r"^Renderer: \w+; flags=\d+; ScaleQuality=0; UseISOFont=0$", log, re.M),
                "No SDL2 renderer observed")
    if glsl:
        require("Renderer: opengl;" in log and "GLSL evidence: vendor=" in log, "No real OpenGL output")
        require(f"GLSL evidence: compiled passes={int(backend[-1])};" in log, "Wrong compiled shader count")
    else:
        require("GLSL evidence:" not in log, "Unexpected GLSL execution")


def check_inputs(directory, backend, version, style):
    record = json.loads((directory / "run.json").read_text("utf-8"))
    require(record["exit_code"] == 0 and record["terminated_by_runner"] is None,
            "Failed source renderer")
    require(record["inputs_preserved"], "Original resources changed")
    check_backend(record, (directory / "run.log").read_text("utf-8"), backend, version, style)
    build_path = Path(record["build_record"])
    require(sha(build_path) == record["build_record_sha256"], "Build record changed")
    build = json.loads(build_path.read_text("utf-8"))
    require(build["exit_code"] == 0 and build["exe_sha256"] == record["executable_sha256"],
            "Executable does not match successful build")
    require(build["backend"] == ("sdl1" if backend == "sdl1" else "sdl2"), "Wrong SDL build")
    for name, digest in record["harness_sha256"].items():
        require(build["sources"]["tests/" + name] == digest, "Harness does not match build")
    libraries = record["runtime_libraries"] if backend == "sdl1" else record["static_libraries"]
    require(any(Path(p).name.lower() == ("sdl.dll" if backend == "sdl1" else "sdl2.lib")
                for p in libraries), "Missing SDL library fingerprint")
    for path, digest in {**record["runtime_libraries"], **record["static_libraries"]}.items():
        require(sha(Path(path)) == digest, "SDL library changed")
    require(sha(directory / "sdlpal.cfg") == record["config_sha256"], "Config changed")
    require((directory / "sdlpal.cfg").read_text("utf-8") == record["config"], "Config metadata differs")
    config = dict(line.split("=", 1) for line in record["config"].splitlines() if "=" in line)
    require(Path(config["GamePath"]).resolve() == (directory / "resource").resolve(), "Wrong GamePath")
    shader = Path(config["Shader"])
    expected_shader = "portrait-identity-2.glslp" if backend == "glsl2" else "portrait-identity.glsl"
    require(shader.name == expected_shader, "Wrong shader fixture")
    for name, digest in record["shaders"].items():
        # Preserve measured input bytes across checkout/EOL changes. The archive
        # must match the digest recorded by the renderer run, not a fresh digest.
        saved = Path(record.get("shader_archive", {}).get(name, shader.parent / name))
        require(saved.name == name and sha(saved) == digest, "Shader changed")
    require({"portrait-identity.glsl", "portrait-identity-2.glslp"} <= record["shaders"].keys(),
            "Missing shader fingerprints")
    for name, source in record["resources"].items():
        require(sha(directory / "resource" / name) == source["sha256"], "Resource copy changed")
        require(sha(Path(source["source"])) == source["sha256"], "Original resource changed")
    return record


def compare(reference, candidate, indexed_only):
    old, old_groups = load(reference)
    new, groups = load(candidate)
    require("shake" in groups, "Missing normal shake regression")
    require(groups.keys() == old_groups.keys(), "Backend effect set changed")
    pairs = 0
    for effect, sequences in groups.items():
        if effect in TIMED:
            # Complete endpoints and intermediate levels are checked by verify().
            continue
        require(len(sequences) == len(old_groups[effect]), "Backend frame count changed")
        for a, b in zip(old_groups[effect], sequences):
            require(np.array_equal(old[a, :64768], new[b, :64768]),
                    f"Backend indices/palette differ: {candidate.name}/{effect}/{b}")
            if not indexed_only:
                require(np.array_equal(split(old[a])[2], split(new[b])[2]),
                        f"Backend RGB differs: {candidate.name}/{effect}/{b}")
            pairs += 1
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("portrait_artifacts", type=Path)
    args = parser.parse_args()
    results = {}
    for version in ("win", "dos"):
        pack = args.portrait_artifacts / f"generated-{version}/paljpn-{version}.por"
        for style in ("native", "adapted"):
            reference = args.artifacts / "runs" / f"validated-sdl2-{version}-{style}"
            reference_run = check_inputs(reference, "sdl2", version, style)
            for backend in ("sdl1", "sdl2", "glsl1", "glsl2"):
                key = f"validated-{backend}-{version}-{style}"
                directory = args.artifacts / "runs" / key
                run = check_inputs(directory, backend, version, style)
                for field in ("resources", "slf_sha256", "portrait_sha256", "harness_sha256"):
                    require(run[field] == reference_run[field], f"Different backend input: {field}")
                result = verify(directory, directory, pack, version, directory / "resource",
                    independent_portraits=backend != "sdl1" and style == "adapted",
                    require_color_change=False)
                # verify() visits both sides; the self-oracle has one set of frames/readbacks.
                result["sdl_readbacks"] //= 2
                result["cross_backend_pairs"] = compare(reference, directory, backend == "sdl1")
                result["run"] = run
                results[key] = result
                print(key, result["frames"], "frames;", result["sdl_readbacks"], "readbacks", flush=True)
    report = {"checks": results, "frames": sum(r["frames"] for r in results.values()),
              "readbacks": sum(r["sdl_readbacks"] for r in results.values()),
              "cross_backend_pairs": sum(r["cross_backend_pairs"] for r in results.values()),
              "live_acceptance": "pending; source-only rendering, no gameplay input"}
    (args.artifacts / "backend-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "checks"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
