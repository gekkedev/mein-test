from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BG_COLOR = "#ffffff"
FG_COLOR = "#111111"
TEXT = "M"
SIZES = [512, 192, 180, 152, 144, 128, 96, 72, 48, 32, 24, 16]
OUTPUT_DIR = Path("icons")
FONT_PATH = Path("assets/fonts/UnifrakturMaguntia-Book.ttf")


def load_font(size: int, ratio: float = 0.7) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"Font not found at {FONT_PATH!s}. Generate icons after fetching project assets.")
    return ImageFont.truetype(str(FONT_PATH), int(size * ratio))


def draw_base(size: int) -> Image.Image:
    return Image.new("RGBA", (size, size), BG_COLOR)


def add_glyph(img: Image.Image, ratio: float = 0.7) -> Image.Image:
    size = img.size[0]
    draw = ImageDraw.Draw(img)
    scales = [ratio, ratio * 0.9, ratio * 0.82, ratio * 0.74, ratio * 0.66]
    font = load_font(size, ratio=scales[-1])
    bbox = draw.textbbox((0, 0), TEXT, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    # Try progressively smaller font sizes until the glyph fits with enough padding.
    for scale in scales:
        candidate = load_font(size, ratio=scale)
        candidate_bbox = draw.textbbox((0, 0), TEXT, font=candidate)
        cand_width = candidate_bbox[2] - candidate_bbox[0]
        cand_height = candidate_bbox[3] - candidate_bbox[1]
        if cand_width <= size * 0.86 and cand_height <= size * 0.86:
            font = candidate
            bbox = candidate_bbox
            text_width = cand_width
            text_height = cand_height
            break
    x = (size - text_width) / 2 - bbox[0]
    y = (size - text_height) / 2 - bbox[1]
    draw.text((x, y), TEXT, font=font, fill=FG_COLOR)
    return img


def save_png(size: int, suffix: str = "") -> Path:
    img = draw_base(size)
    img = add_glyph(img)
    name = f"icon-{size}{suffix}.png"
    out_path = OUTPUT_DIR / name
    img.save(out_path, format="PNG")
    return out_path


def save_maskable(size: int) -> Path:
    img = draw_base(size)
    img = add_glyph(img, ratio=0.58)
    out_path = OUTPUT_DIR / f"icon-{size}-maskable.png"
    img.save(out_path, format="PNG")
    return out_path


def save_favicon() -> Path:
    base = draw_base(256)
    base = add_glyph(base)
    ico_path = OUTPUT_DIR / "favicon.ico"
    sizes = [(size, size) for size in (16, 24, 32, 48)]
    base.save(ico_path, format="ICO", sizes=sizes)
    return ico_path


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for size in SIZES:
        save_png(size)
    for size in (512, 192):
        save_maskable(size)
    save_favicon()


if __name__ == "__main__":
    main()
