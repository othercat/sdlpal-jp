"""Adapt one Saturn message break to SDLPAL's 249px item description area.

Run after makemessage_j.py, on its Win SLF. The original Saturn resources and
all other SLF bytes are preserved. See docs/japanese-red-silkworm-layout.md.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


ORIGINAL = ("血のビタミンを吸う蚕。服用した者", "は完全に体力復帰する。")
ADAPTED = ("血のビタミンを吸う蚕。服用した", "者は完全に体力復帰する。")
# Issue #6 corrects the meaning and already fits the same two-line layout.
CORRECTED = ("血を吸って生きる毒虫。", "服用すると体力が全回復する。")


def adapt(data):
    data.decode("utf-8-sig")  # Reject other encodings before touching the output.
    starts = list(re.finditer(rb"(?m)^\[BEGIN MESSAGE\][ \t]+12920[ \t]*\r?$", data))
    if len(starts) != 1:
        raise ValueError("Expected exactly one Win message block starting at 12920")
    start = starts[0]
    newline = b"\r\n" if data[start.end() - 1:start.end()] == b"\r" else b"\n"
    body_start = start.end() + 1
    end = re.compile(rb"(?m)^\[END MESSAGE\][ \t]+(\d+)[ \t]*\r?$").search(data, body_start)
    if end is None or end[1] != b"12921":
        raise ValueError("Expected message block 12920-12921; input mapping has changed")
    before = newline.join(line.encode("utf-8") for line in ORIGINAL) + newline
    after = newline.join(line.encode("utf-8") for line in ADAPTED) + newline
    corrected = newline.join(line.encode("utf-8") for line in CORRECTED) + newline
    body = data[body_start:end.start()]
    if body == corrected:
        return data
    if body not in (before, after):
        raise ValueError("Unexpected red silkworm text or line endings; inspect the input")
    return data[:body_start] + after + data[end.start():]


def adapt_file(source, destination):
    if source.resolve() == destination.resolve():
        raise ValueError("Use a separate output path; the source SLF is evidence")
    original = source.read_bytes()
    adapted = adapt(original)
    # Exclusive creation also protects existing outputs and aliases to the input.
    with destination.open("xb") as stream:
        stream.write(adapted)
    return {
        "message_range": [12920, 12921],
        "changed": original != adapted,
        "input_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(adapted).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        report = adapt_file(args.source, args.destination)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report, indent=2))
