#!/usr/bin/env python3
"""Build one horizontal contact sheet per visual direction."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow가 필요하다: python -m pip install Pillow") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        outputs = []
        for direction in sorted((args.work_dir / "candidates").glob("direction-*")):
            cards = sorted(direction.glob("card-*.png"))
            if len(cards) not in (3, 4):
                raise ValueError(f"{direction.name}은 완결된 3~4장 세트가 아니다.")
            thumbs = []
            for path in cards:
                with Image.open(path) as image:
                    thumb = image.convert("RGB")
                    thumb.thumbnail((270, 338))
                    thumbs.append(thumb.copy())
            sheet = Image.new("RGB", (len(thumbs) * 290 + 20, 410), "#111111")
            draw = ImageDraw.Draw(sheet)
            draw.text((20, 12), direction.name, fill="white", font=ImageFont.load_default())
            for index, thumb in enumerate(thumbs):
                sheet.paste(thumb, (20 + index * 290, 50))
            output = args.work_dir / "contact-sheets" / f"{direction.name}.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(output)
            outputs.append(str(output.resolve()))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": {"contact_sheets": outputs}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

