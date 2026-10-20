"""Load/unload an experiment font for this Windows session, without registry edits.

Unlike FR_PRIVATE, flags=0 allows the separate PAL.EXE process to use the font.
Pair each successful load with one unload after the game exits.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("load", "unload"))
    parser.add_argument("font", type=Path)
    args = parser.parse_args()
    font = args.font.resolve(strict=True)
    gdi = ctypes.WinDLL("gdi32")
    function = getattr(gdi, "AddFontResourceExW" if args.action == "load" else "RemoveFontResourceExW")
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    function.restype = ctypes.c_int
    result = function(str(font), 0, None)
    if not result:
        raise RuntimeError(f"Session font {args.action} failed: {font}")
    print(json.dumps({"action": args.action, "font": str(font), "flags": 0, "result": result,
                      "sha256": hashlib.sha256(font.read_bytes()).hexdigest()}, indent=2))
