"""Create an offline PAL98 Windows save copy for the Issue #10 font comparison.

Only role 0's MP/magic slots and the inventory change. The caller must supply a
known-good PAL98 save; this is not a save repair or general conversion tool.
Layout: SAVEDGAME_WIN / PLAYERROLES in global.c / global.h.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path


MAGICS = (306, 307, 308, 311, 370, 374, 377, 390, 393, 394)
ROLES_OFFSET = 508
INVENTORY_OFFSET = 1728


def create(source, output):
    if output.exists():
        raise FileExistsError(output)
    original = source.read_bytes()
    if len(original) != 176528 or struct.unpack_from("<H", original, 44)[0] != 0:
        raise ValueError("Expected a 176528-byte PAL98 Windows save led by role 0")
    data = bytearray(original)
    allowed = set()

    def replace(offset, payload):
        allowed.update(range(offset, offset + len(payload)))
        data[offset:offset + len(payload)] = payload

    for field in (8, 10):  # maximum/current MP, six WORDs per PLAYERROLES field
        replace(ROLES_OFFSET + field * 12, struct.pack("<H", 999))
    for slot in range(32):
        replace(ROLES_OFFSET + (32 + slot) * 12,
                struct.pack("<H", MAGICS[slot] if slot < len(MAGICS) else 0))
    inventory = bytearray(256 * 6)
    struct.pack_into("<HHH", inventory, 0, 149, 2, 0)
    struct.pack_into("<HHH", inventory, 6, 150, 2, 0)
    replace(INVENTORY_OFFSET, inventory)
    changed = [i for i, (before, after) in enumerate(zip(original, data)) if before != after]
    if not set(changed).issubset(allowed) or len(data) != len(original):
        raise AssertionError("Unexpected save mutation")
    output.write_bytes(data)
    report = {
        "purpose": "offline test state, not a naturally acquired inventory or magic list",
        "source": str(source),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "output": str(output),
        "output_sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "role": 0,
        "mp": 999,
        "max_mp": 999,
        "magics": list(MAGICS),
        "inventory": [{"object": 149, "amount": 2}, {"object": 150, "amount": 2}],
        "changed_byte_offsets": changed,
        "outside_declared_fields_unchanged": True,
    }
    output.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(create(args.source.resolve(), args.output.resolve()),
                     ensure_ascii=False, indent=2))
