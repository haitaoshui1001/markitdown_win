"""用 PIL 画一个应用图标并输出多尺寸 assets/app.ico。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
BLUE = (48, 118, 255, 255)
BLUE_DARK = (28, 84, 200, 255)
PAPER = (248, 249, 252, 255)
GREY = (126, 134, 152, 255)
OUT = Path(__file__).resolve().parents[1] / "assets" / "app.ico"


def _font(size: int):
    for name in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([6, 6, SIZE - 6, SIZE - 6], radius=104, fill=BLUE)

    # 纸张（右上角折角）
    d.rounded_rectangle([118, 74, 394, 322], radius=18, fill=PAPER)
    d.polygon([(344, 74), (394, 124), (344, 124)], fill=BLUE_DARK)
    for y in (140, 180, 220):
        d.rounded_rectangle([150, y, 300 if y < 220 else 250, y + 22], radius=11, fill=GREY)

    # 落地箭头
    d.rounded_rectangle([232, 318, 280, 386], radius=14, fill=PAPER)
    d.polygon([(196, 376), (316, 376), (256, 448)], fill=PAPER)

    d.text((256, 476), "Markdown", font=_font(40), fill=PAPER, anchor="mm")
    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    build().save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("写入", OUT)


if __name__ == "__main__":
    main()
