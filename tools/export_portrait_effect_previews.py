"""Export opaque comparisons from fingerprinted Issue 9 source effect frames."""
import argparse
import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent / "japanese"))
from verify_portrait_effects import load, sha, split


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", type=Path, required=True)
    args = parser.parse_args()
    report_path = args.artifacts / "effects-verification.json"
    report = json.loads(report_path.read_text("utf-8"))
    for check in report["checks"].values():
        for name, expected in check["files"].items():
            assert sha(Path(name)) == expected, name
    assert not args.output.exists(), "Use a new preview directory"
    args.output.mkdir(parents=True)
    title = ImageFont.truetype(str(args.font), 24)
    label = ImageFont.truetype(str(args.font), 20)
    samples = [
        ("win-gradient.png", "Win：颜色渐变与红色渐变", "win",
         [("color-to", 15, "向指定颜色渐变 / 第 16 帧"), ("red", 15, "向红色渐变 / 第 16 帧")]),
        ("win-index-effects.png", "Win：波浪与索引溶解", "win",
         [("wave", 15, "波浪 / 相位 15"), ("dissolve", 35, "溶解 / 第 36 帧")]),
        ("dos-effects.png", "DOS：红色渐变与索引溶解", "dos",
         [("red", 15, "向红色渐变 / 第 16 帧"), ("dissolve", 35, "溶解 / 第 36 帧")]),
        ("win-transition-endpoint.png", "Win：溶解终点与 FBP 切换", "win",
         [("dissolve", 71, "溶解 / 第 72 帧（最终条带）"), ("fbp", 31, "FBP / 第 32 帧")]),
    ]
    exports = []
    for filename, heading, version, rows in samples:
        before, bg = load(args.artifacts / "effects" / f"before-{version}-adapted")
        after, ag = load(args.artifacts / "effects" / f"after-{version}-adapted")
        sheet = Image.new("RGB", (1308, 996), "#e9edf1")
        draw = ImageDraw.Draw(sheet)
        draw.text((12, 8), heading + "（真实源码渲染，非实机截图）", font=title, fill="#182535")
        draw.text((12, 44), "左：R2 修前     右：R3 修后；同资源、字体、头像包及特效阶段", font=label, fill="#334557")
        for n, (effect, frame, caption) in enumerate(rows):
            y = 78+n*450
            draw.text((12, y), caption, font=label, fill="#182535")
            draw.text((12, y+26), "修前", font=label, fill="#7f302d")
            draw.text((666, y+26), "修后", font=label, fill="#1b603a")
            for x, data, groups in ((12, before, bg), (666, after, ag)):
                rgb = split(data[groups[effect][frame]])[2]
                image = Image.fromarray(rgb).resize((640, 400), Image.Resampling.NEAREST)
                sheet.paste(image, (x, y+50))
        path = args.output / filename
        sheet.save(path, optimize=True)
        exports.append({"file": filename, "sha256": sha(path), "bytes": path.stat().st_size,
                        "samples": rows, "mode": sheet.mode, "size": sheet.size})
    (args.output / "previews.json").write_text(json.dumps({
        "verification_sha256": sha(report_path), "font_sha256": sha(args.font),
        "method": "Captured RGB frames; opaque RGB PNG; labels and nearest-neighbor scale only",
        "exports": exports}, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(len(exports), "opaque comparison PNGs exported")


if __name__ == "__main__":
    main()
