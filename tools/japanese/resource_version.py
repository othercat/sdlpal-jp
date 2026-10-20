"""Resource identity and SLF target tags shared by the Japanese entry points."""
import json
from pathlib import Path

from verify_baseline import METADATA, check_inputs

TAG = "ResourceVersion=WIN95\n"


def checked_win_inputs(gamepath, saturnpath, encoding):
    baseline = json.loads(METADATA.read_text("utf-8"))["baseline"]
    if encoding != baseline["pc_encoding"]:
        raise ValueError("This reviewed Win mapping requires GBK; use makemessage_dos.py for PAL_DOS (CP950).")
    return {
        "win": check_inputs(Path(gamepath), baseline["pc_resource_sha256"], "Win",
                            baseline["unsupported_dos_sss_sha256"]),
        "saturn": check_inputs(Path(saturnpath), baseline["saturn_resource_sha256"], "Saturn"),
    }


def without_win_tag(text):
    """Allow exactly the new preamble tag when checking the historical #6 body edit."""
    marker = "[BEGIN SETTING]\n" + TAG
    if text.count(TAG) != 1 or text.count(marker) != 1:
        raise ValueError("Expected one WIN95 resource tag at the start of SETTING")
    return text.replace(marker, "[BEGIN SETTING]\n", 1)
