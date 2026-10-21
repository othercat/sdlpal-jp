"""Opaque RGB previews from the source renderer's observed backend frames."""
import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent / "japanese"))
from verify_portrait_effects import load, split


def frame(root, case, effect, number=0):
    data, groups = load(root / "runs" / case)
    return Image.fromarray(split(data[groups[effect][number]])[2].copy(), "RGB")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(args.font), 20)
    small = ImageFont.truetype(str(args.font), 16)
    title = ImageFont.truetype(str(args.font), 26)
    for version in ("win", "dos"):
        canvas = Image.new("RGB", (1504, 774), "#f5f5f5")
        draw = ImageDraw.Draw(canvas)
        draw.text((16, 12), f"{version.upper()} · 同一资源／字体／土星头像包的源码输出", font=title, fill="#171717")
        draw.text((16, 51), "SDL1 为调色板近似色；SDL2 与中性双通道 GLSL 保留独立头像 RGB。", font=small, fill="#444444")
        for column, (backend, label) in enumerate((("sdl1", "SDL1 1.2.15 · 索引回退"),
                ("sdl2", "SDL2 · 独立 RGB"), ("glsl2", "GLSL · 双通道中性着色器"))):
            directory = args.artifacts / "runs" / f"validated-{backend}-{version}-adapted"
            for row, effect in enumerate(("initial", "red")):
                number = 0 if effect == "initial" else 15
                # Published backend panels come from physical surface/GL readbacks.
                image = Image.open(directory / f"{effect}-{number}-640.bmp").convert("RGB")
                image = image.resize((480, 300), Image.Resampling.NEAREST)
                x, y = 16 + column * 496, 98 + row * 334
                draw.text((x, y-26), label if not row else "红色渐变 · 中间阶段", font=font, fill="#171717")
                canvas.paste(image, (x, y))
        draw.text((16, 744), "隐藏／dummy 后端源码夹具，非实机验收；底部色条仅用于索引检查。", font=small, fill="#444444")
        canvas.save(args.output / f"{version}-backends.png", optimize=True)

    canvas = Image.new("RGB", (1312, 706), "#f5f5f5")
    draw = ImageDraw.Draw(canvas)
    draw.text((16, 12), "SDL1 640×400 · 向上震屏底边修复", font=title, fill="#171717")
    draw.text((16, 51), "同一逻辑帧的实际显示面 RGB 采样，按 2 倍最近邻放大；其余像素保持一致。", font=small, fill="#444444")
    for column, (case, label) in enumerate((("before-shake-win-adapted", "修前 · 底边残留上一帧"),
            ("validated-sdl1-win-adapted", "修后 · 底边正确清空"))):
        x = 8 + column * 656
        draw.text((x+8, 79), label, font=font, fill="#171717")
        image = frame(args.artifacts, case, "shake", 1)
        canvas.paste(image.resize((640, 400), Image.Resampling.NEAREST), (x, 110))
        draw.text((x+8, 520), "普通震屏：底部 12 行放大", font=small, fill="#444444")
        canvas.paste(image.crop((0, 188, 320, 200)).resize((640, 48), Image.Resampling.NEAREST), (x, 548))
        draw.text((x+8, 608), "溶解＋震屏：底部 12 行放大", font=small, fill="#444444")
        image = frame(args.artifacts, case, "dissolve-shake", 15)
        canvas.paste(image.crop((0, 188, 320, 200)).resize((640, 48), Image.Resampling.NEAREST), (x, 636))
    canvas.save(args.output / "sdl1-shake-before-after.png", optimize=True)


if __name__ == "__main__":
    main()
