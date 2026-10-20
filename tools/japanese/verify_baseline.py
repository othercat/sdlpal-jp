"""Reproduce the pinned Win/Saturn conversion without modifying input files."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parent
METADATA = TOOL_DIR / "upstream.json"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_inputs(directory, expected, label, dos_hash=None):
    """Resolve names case-insensitively and reject unsupported or changed data."""
    if not directory.is_dir():
        raise ValueError(f"{label} resource directory does not exist: {directory}")
    found = {}
    for name, digest in expected.items():
        matches = [p for p in directory.iterdir() if p.name.casefold() == name.casefold()]
        if len(matches) != 1 or not matches[0].is_file():
            raise ValueError(f"{label}: expected exactly one readable {name}")
        path = matches[0]
        actual = sha256(path)
        if actual == dos_hash:
            raise ValueError("PAL_DOS resources are not the Win mapping baseline; see Issue #7.")
        if actual != digest:
            raise ValueError(f"{label} {name}: unsupported version or changed input; SHA256 {actual}")
        found[name] = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}
    return found


def slf_summary(path):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    starts = re.findall(r"^\[BEGIN MESSAGE\] (\d+)\r?$", text, re.M)
    ends = re.findall(r"^\[END MESSAGE\] (\d+)\r?$", text, re.M)
    if len(starts) != len(ends):
        raise ValueError("Unbalanced SLF message block markers")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "lf_sha256": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
            "blocks": len(starts), "unique_keys": len(set(zip(starts, ends)))}


def reproduce(pc_dir, saturn_dir, output_dir, encoding="gbk"):
    metadata = json.loads(METADATA.read_text("utf-8"))
    baseline = metadata["baseline"]
    if encoding != baseline["pc_encoding"]:
        raise ValueError("This pinned Win baseline requires GBK; BIG5/DOS is not interchangeable.")
    pc_dir, saturn_dir, output_dir = (p.resolve() for p in (pc_dir, saturn_dir, output_dir))
    if any(output_dir == p or p in output_dir.parents for p in (pc_dir, saturn_dir)):
        raise ValueError("Output directory must be outside both input resource directories.")
    if output_dir.exists():
        raise ValueError(f"Output directory already exists; use a new directory: {output_dir}")
    inputs = {
        "pc": check_inputs(pc_dir, baseline["pc_resource_sha256"], "Win", baseline["unsupported_dos_sss_sha256"]),
        "saturn": check_inputs(saturn_dir, baseline["saturn_resource_sha256"], "Saturn"),
    }
    script = TOOL_DIR / "makemessage_j.py"
    script_hash = sha256(script)
    output_dir.mkdir(parents=True)
    output = output_dir / "paljpn-win.slf"
    command = [sys.executable, "-B", "-X", "utf8", str(script),
               str(pc_dir), str(saturn_dir), str(output), encoding, "--upstream-baseline"]
    result = subprocess.run(command, cwd=output_dir, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    (output_dir / "converter.log").write_text(result.stdout + result.stderr, "utf-8")
    # Some upstream read-error branches return zero, so exit status alone is
    # insufficient. Require a new output and compare its full content below.
    if result.returncode != 0 or not output.is_file() or "OK!" not in result.stdout:
        raise ValueError(f"Conversion failed (exit {result.returncode}); see {output_dir / 'converter.log'}")
    actual = slf_summary(output)
    expected = baseline["slf"]
    for field in ("lf_sha256", "blocks", "unique_keys"):
        if actual[field] != expected[field]:
            raise ValueError(f"SLF baseline mismatch: {field}: {actual[field]}")
    if os.name == "nt" and actual["sha256"] != expected["windows_sha256"]:
        raise ValueError("Windows SLF bytes differ from the audited CRLF baseline")
    for group in inputs.values():
        for record in group.values():
            if sha256(Path(record["path"])) != record["sha256"]:
                raise ValueError(f"Input was modified: {record['path']}")
    report = {
        "scope": "Exact upstream Win output via --upstream-baseline; interactive acceptance is deferred.",
        "python": {"executable": sys.executable, "version": sys.version,
                   "prefix": sys.prefix, "base_prefix": sys.base_prefix},
        "command": command, "working_directory": str(output_dir), "exit_code": result.returncode,
        "converter_sha256": script_hash,
        "upstream_converter_sha256": metadata["assets"][script.name]["sha256"],
        "inputs": inputs, "inputs_unchanged": True,
        "output": actual, "baseline_matches": True,
        "known_mapping_problems": "Preserved for Issues #3/#4/#6/#7/#8; this is not the final translated release.",
    }
    (output_dir / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pc_dir", type=Path)
    parser.add_argument("saturn_dir", type=Path)
    parser.add_argument("output_dir", type=Path, help="New output directory outside the inputs")
    parser.add_argument("--encoding", choices=("gbk", "big5"), default="gbk")
    args = parser.parse_args()
    try:
        result = reproduce(args.pc_dir, args.saturn_dir, args.output_dir, args.encoding)
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {result['output']['blocks']} message blocks, "
          f"{result['output']['unique_keys']} unique keys; inputs unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
