"""Generates the Huevonitis 4 app icon (PNG + ICO)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

SIZES = [16, 32,48, 64, 128, 256]

def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Gradient background circle
    cx = cy = size / 2
    r = size / 2 - 2
    for i in range(int(r), 0, -1):
        t = i / r
        red   = int(13  + (37  - 13)  * (1 - t))
        green = int(17  + (99  - 17)  * (1 - t))
        blue  = int(23  + (235 - 23)  * (1 - t))
        draw.ellipse(
            [cx - i, cy - i, cx + i, cy + i],
            fill=(red, green, blue, 255),
        )

    # White "H4" text
    font_size = int(size * 0.42)
    try:
        font = ImageFont.truetype("/usr/share/fonts/liberation/LiberationSans-Bold.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    text = "H4"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    # Orange accent dot bottom-right
    dot_r = int(size * 0.12)
    dot_cx = int(size * 0.78)
    dot_cy = int(size * 0.78)
    draw.ellipse([dot_cx - dot_r, dot_cy - dot_r,
                  dot_cx + dot_r, dot_cy + dot_r],
                 fill=(249, 115, 22, 255))

    return img


def main():
    out_dir = Path(__file__).parent.parent / "assets"
    out_dir.mkdir(exist_ok=True)

    # Save 256px PNG
    big = make_icon(256)
    big.save(out_dir / "icon.png")
    print(f"Saved icon.png (256x256)")

    # Save ICO with multiple sizes
    icons = [make_icon(s) for s in SIZES]
    icons[-1].save(
        out_dir / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=icons[:-1],
    )
    print(f"Saved icon.ico ({', '.join(str(s) for s in SIZES)}px)")


if __name__ == "__main__":
    main()
