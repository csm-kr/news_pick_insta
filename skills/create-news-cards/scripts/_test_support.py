"""테스트 전용 합성 이미지 도우미. 실제 사진처럼 모서리가 많은 도형 그림을 결정적으로 만든다."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw


def synthetic_photo(seed: int, size: tuple[int, int] = (640, 480), shapes: int = 160) -> Image.Image:
    """seed별로 다른 도형 사진을 만든다. ORB 특징점이 충분히 잡히도록 사각형·타원을 많이 그린다."""
    rng = random.Random(seed)
    width, height = size
    image = Image.new("RGB", size, (rng.randint(30, 90), rng.randint(30, 90), rng.randint(30, 90)))
    draw = ImageDraw.Draw(image)
    for _ in range(shapes):
        x0 = rng.randint(0, width - 20)
        y0 = rng.randint(0, height - 20)
        x1 = min(width - 1, x0 + rng.randint(8, 90))
        y1 = min(height - 1, y0 + rng.randint(8, 90))
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        if rng.random() < 0.5:
            draw.rectangle((x0, y0, x1, y1), fill=color, outline=(255 - color[0], 255 - color[1], 255 - color[2]))
        else:
            draw.ellipse((x0, y0, x1, y1), fill=color)
    return image


def cropped_rescaled(image: Image.Image, keep: float = 0.8, scale: float = 0.75) -> Image.Image:
    """같은 장면을 다른 매체가 다른 crop·해상도로 전재한 상황을 흉내 낸다."""
    width, height = image.size
    dx, dy = int(width * (1 - keep) / 2), int(height * (1 - keep) / 2)
    crop = image.crop((dx, dy, width - dx, height - dy))
    return crop.resize((max(32, int(crop.width * scale)), max(32, int(crop.height * scale))), Image.Resampling.LANCZOS)


def save(path: Path, image: Image.Image) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path
