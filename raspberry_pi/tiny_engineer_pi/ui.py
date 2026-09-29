from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


def _draw_battery(draw: ImageDraw.ImageDraw, level: int, charging: bool) -> None:
    if level < 0:
        draw.text((190, 13), "BAT --", fill=(128, 128, 128), font=ImageFont.load_default())
        return
    x, y = 194, 12
    width, height = 26, 14
    color = (52, 211, 81) if charging else (255, 255, 255)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=3, outline="white", width=2)
    draw.rectangle((x + 2, y + 2, x + width - 2, y + height - 2), fill=color)
    draw.rectangle((x + width, y + 4, x + width + 2, y + 9), fill="white")
    text = str(level)
    font = ImageFont.load_default()
    box = font.getbbox(text)
    text_width = box[2] - box[0]
    draw.text((x + (width - text_width) // 2, y + 2), text, fill="black", font=font)


def render_ui(mode: str, next_mode: str, battery: tuple[int, bool]) -> Image.Image:
    """Simple daemon UI: action selector only, plus PiSugar battery status."""
    image = Image.new("RGB", (240, 280), (7, 12, 22))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    level, charging = battery

    draw.text((14, 14), "TINY ENGINEER", fill=(126, 218, 255), font=font)
    _draw_battery(draw, level, charging)
    draw.line((14, 38, 226, 38), fill=(41, 68, 91), width=1)

    draw.text((14, 65), "CURRENT ACTION", fill=(103, 135, 160), font=font)
    label = mode.upper()
    box = font.getbbox(label)
    draw.rounded_rectangle((14, 87, 226, 157), radius=14, fill=(21, 55, 82), outline=(74, 157, 202), width=2)
    draw.text(((240 - (box[2] - box[0])) // 2, 116), label, fill="white", font=font)

    draw.text((14, 181), "NEXT", fill=(103, 135, 160), font=font)
    draw.text((62, 181), next_mode.upper(), fill=(255, 190, 85), font=font)

    draw.rounded_rectangle((14, 216, 226, 263), radius=10, outline=(46, 77, 103), width=2)
    draw.text((28, 228), "CLICK", fill=(126, 218, 255), font=font)
    draw.text((78, 228), "next action", fill=(205, 217, 227), font=font)
    draw.text((28, 246), "4 CLICKS", fill=(126, 218, 255), font=font)
    draw.text((92, 246), "exit", fill=(205, 217, 227), font=font)
    return image
