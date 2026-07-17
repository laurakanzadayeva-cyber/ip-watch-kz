"""Создаёт иконку icon.ico для приложения."""
from PIL import Image, ImageDraw, ImageFont
import os

sizes = [256, 128, 64, 48, 32, 16]
images = []

for size in sizes:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Фон — тёмно-синий круг
    margin = size // 10
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=(15, 52, 96))

    # Буква "IP" белым
    font_size = int(size * 0.38)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    text = "IP"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - size // 16
    draw.text((x, y), text, fill="white", font=font)

    # Маленькая надпись "KZ"
    font_size2 = int(size * 0.20)
    try:
        font2 = ImageFont.truetype("arial.ttf", font_size2)
    except Exception:
        font2 = font
    text2 = "KZ"
    bbox2 = draw.textbbox((0, 0), text2, font=font2)
    tw2 = bbox2[2] - bbox2[0]
    x2 = (size - tw2) // 2
    y2 = y + th + size // 20
    draw.text((x2, y2), text2, fill=(100, 200, 255), font=font2)

    images.append(img)

out = os.path.join(os.path.dirname(__file__), "icon.ico")
images[0].save(out, format="ICO", sizes=[(s, s) for s in sizes])
print(f"Иконка создана: {out}")
