"""Check a generated test font against every exported engine bitmap using GDI.

Uses a memory DC, not a game window. No UI input or screenshot capture.
The font is loaded privately for this process and removed in finally.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path

from export_japanese_font import FAMILY, load_glyphs


class LOGFONT(C.Structure):
    _fields_ = [(name, W.LONG) for name in ("height", "width", "escapement", "orientation", "weight")]
    _fields_ += [(name, C.c_ubyte) for name in ("italic", "underline", "strikeout", "charset",
                                           "outprecision", "clipprecision", "quality", "pitch")]
    _fields_ += [("face", W.WCHAR * 32)]


class TEXTMETRIC(C.Structure):
    _fields_ = [(name, W.LONG) for name in ("height", "ascent", "descent", "internalLeading",
        "externalLeading", "averageWidth", "maxWidth", "weight", "overhang", "aspectX", "aspectY")]
    _fields_ += [(name, W.WCHAR) for name in ("firstChar", "lastChar", "defaultChar", "breakChar")]
    _fields_ += [(name, C.c_ubyte) for name in ("italic", "underlined", "struckOut", "pitch", "charset")]


class GLYPHMETRICS(C.Structure):
    _fields_ = [("width", W.UINT), ("height", W.UINT), ("origin", W.POINT),
                ("advanceX", C.c_short), ("advanceY", C.c_short)]


class FIXED(C.Structure):
    _fields_ = [("fraction", W.WORD), ("value", C.c_short)]


class MAT2(C.Structure):
    _fields_ = [(name, FIXED) for name in ("m11", "m12", "m21", "m22")]


def gdi_api():
    gdi = C.WinDLL("gdi32", use_last_error=True)
    declarations = {
        "AddFontResourceExW": ([W.LPCWSTR, W.DWORD, W.LPVOID], C.c_int),
        "RemoveFontResourceExW": ([W.LPCWSTR, W.DWORD, W.LPVOID], W.BOOL),
        "CreateCompatibleDC": ([W.HDC], W.HDC),
        "CreateFontIndirectW": ([C.POINTER(LOGFONT)], W.HANDLE),
        "SelectObject": ([W.HDC, W.HANDLE], W.HANDLE),
        "DeleteObject": ([W.HANDLE], W.BOOL), "DeleteDC": ([W.HDC], W.BOOL),
        "GetTextFaceW": ([W.HDC, C.c_int, W.LPWSTR], C.c_int),
        "GetTextMetricsW": ([W.HDC, C.POINTER(TEXTMETRIC)], W.BOOL),
        "GetGlyphIndicesW": ([W.HDC, W.LPCWSTR, C.c_int, C.POINTER(W.WORD),
                              W.DWORD], W.DWORD),
        "GetGlyphOutlineW": ([W.HDC, W.UINT, W.UINT, C.POINTER(GLYPHMETRICS),
                              W.DWORD, W.LPVOID, C.POINTER(MAT2)], W.DWORD),
    }
    for name, (arguments, result) in declarations.items():
        getattr(gdi, name).argtypes, getattr(gdi, name).restype = arguments, result
    return gdi


def verify(font, resources, repo):
    data = load_glyphs(repo, resources)
    gdi = gdi_api()
    if not gdi.AddFontResourceExW(str(font.resolve()), 0x10, None):
        raise RuntimeError("Private font load failed")
    dc = handle = previous = None
    try:
        dc = gdi.CreateCompatibleDC(None)
        lf = LOGFONT()
        lf.height, lf.weight, lf.charset, lf.quality, lf.face = 16, 400, 134, 3, FAMILY
        handle = gdi.CreateFontIndirectW(C.byref(lf))
        if not dc or not handle:
            raise RuntimeError("Memory font/DC creation failed")
        previous = gdi.SelectObject(dc, handle)
        if not previous or previous == C.c_void_p(-1).value:
            previous = None
            raise RuntimeError("Font selection into memory DC failed")
        face = C.create_unicode_buffer(64)
        if not gdi.GetTextFaceW(dc, len(face), face):
            raise RuntimeError("Cannot read selected font face")
        metric = TEXTMETRIC()
        if not gdi.GetTextMetricsW(dc, C.byref(metric)) or face.value != FAMILY:
            raise RuntimeError(f"Unexpected resolved font: {face.value}")
        if (metric.height, metric.ascent, metric.descent, metric.internalLeading) != (16, 16, 0, 0):
            raise RuntimeError("GDI cell metrics do not match the 16-row engine bitmap")
        matrix = MAT2(FIXED(0, 1), FIXED(0, 0), FIXED(0, 0), FIXED(0, 1))
        differences = []
        for cp, (width, pixels, origin) in data.items():
            index = W.WORD()
            # Blank source characters must not pass by falling back to .notdef.
            if (gdi.GetGlyphIndicesW(dc, chr(cp), 1, C.byref(index), 1) == 0xffffffff
                    or index.value in (0, 0xffff)):
                raise RuntimeError(f"Missing mapped glyph U+{cp:04X}")
            gm = GLYPHMETRICS()
            size = gdi.GetGlyphOutlineW(dc, cp, 1, C.byref(gm), 0, None, C.byref(matrix))
            if size == 0xffffffff:
                raise RuntimeError(f"GDI glyph failure U+{cp:04X}")
            actual = set()
            if size:
                buffer = C.create_string_buffer(size)
                if gdi.GetGlyphOutlineW(
                        dc, cp, 1, C.byref(gm), size, buffer, C.byref(matrix)) != size:
                    raise RuntimeError(f"Cannot read glyph bitmap U+{cp:04X}")
                bits = buffer.raw
                pitch = ((gm.width + 31) // 32) * 4
                actual = {(gm.origin.x + x, metric.ascent - gm.origin.y + y)
                          for y in range(gm.height) for x in range(gm.width)
                          if bits[y * pitch + x // 8] & (0x80 >> (x % 8))}
            if actual != pixels or gm.advanceX != width:
                differences.append({"codepoint": f"U+{cp:04X}", "origin": origin,
                    "pixel_difference": len(actual ^ pixels),
                    "advance_expected": width, "advance_actual": gm.advanceX})
        return {
            "method": "GDI GetGlyphOutlineW GGO_BITMAP at 16px, memory DC; not a game screenshot",
            "font_sha256": hashlib.sha256(font.read_bytes()).hexdigest(),
            "requested_face": FAMILY, "resolved_face": face.value,
            "logfont": {"height": 16, "width": 0, "weight": 400, "charset": 134, "quality": 3},
            "metrics": {name: getattr(metric, name) for name in (
                "height", "ascent", "descent", "internalLeading", "externalLeading",
                "averageWidth", "maxWidth", "weight", "charset")},
            "glyphs_checked": len(data), "all_glyph_indices_present": True,
            "differences": differences,
            "passed": not differences,
        }
    finally:
        if previous:
            gdi.SelectObject(dc, previous)
        if handle:
            gdi.DeleteObject(handle)
        if dc:
            gdi.DeleteDC(dc)
        if not gdi.RemoveFontResourceExW(str(font.resolve()), 0x10, None):
            raise RuntimeError("Private font cleanup failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path)
    parser.add_argument("resources", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = verify(args.font, args.resources, Path(__file__).resolve().parents[1])
    args.report.write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "differences"}, indent=2))
    print(f"Differing glyphs: {len(report['differences'])}")
    raise SystemExit(0 if report["passed"] else 1)
