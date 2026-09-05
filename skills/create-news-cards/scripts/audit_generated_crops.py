from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def crop_geometry(raw_size, plan, final_size):
    width, height = raw_size
    if plan.get("cropping_applied") is False:
        crop_width, crop_height = width, height
        left, top = 0, 0
    else:
        crop_width, crop_height = int(plan["crop_width"]), int(plan["crop_height"])
        left, top = int(plan["x_offset"]), int(plan["y_offset"])
    if min(crop_width, crop_height) <= 0 or min(left, top) < 0 or left + crop_width > width or top + crop_height > height:
        raise ValueError("crop rectangle is outside the actual backend raw image")
    return {
        "raw_size": list(raw_size),
        "final_size": list(final_size),
        "crop_box": [left, top, left + crop_width, top + crop_height],
        "removed_top_px": top,
        "removed_bottom_px": height - top - crop_height,
        "removed_left_px": left,
        "removed_right_px": width - left - crop_width,
        "removed_area_fraction": round(1 - crop_width * crop_height / (width * height), 6),
        "visual_review_required": True,
    }


def audit(work, direction):
    plan = json.loads((work / "generation-plan.json").read_text(encoding="utf-8"))
    jobs = [record for record in plan["jobs"] if record["direction_id"] == direction]
    if len(jobs) != int(plan["card_count"]):
        raise ValueError("selected direction is not a complete card set")
    output = work / "crop-audit" / direction
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for job in jobs:
        manifest_path = Path(job["job"]).parent / "output" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("dry_run") or len(manifest.get("images", [])) != 1:
            raise ValueError("a completed single-image backend manifest is required")
        generated = manifest["images"][0]
        raw_path = Path(generated["backend_raw"]["path"])
        final_path = work / "candidates" / direction / f"card-{job['card_index']:02d}.png"
        raw_hash, final_hash = digest(raw_path), digest(final_path)
        if raw_hash != generated["backend_raw"]["sha256"] or final_hash != generated["sha256"]:
            raise ValueError("raw/candidate hash differs from its generation manifest")
        with Image.open(raw_path) as raw_image, Image.open(final_path) as final_image:
            declared_raw = generated["raw_size"]
            if raw_image.size != (declared_raw["width"], declared_raw["height"]):
                raise ValueError("declared raw size differs from the actual image")
            geometry = crop_geometry(raw_image.size, generated["postprocess_plan"], final_image.size)
            raw_preview = raw_image.convert("RGB")
            ImageDraw.Draw(raw_preview).rectangle(geometry["crop_box"], outline="#00cc70", width=5)
            raw_preview.thumbnail((440, 620))
            final_preview = final_image.convert("RGB")
            final_preview.thumbnail((440, 620))
        sheet = Image.new("RGB", (920, 680), "#222222")
        drawing = ImageDraw.Draw(sheet)
        drawing.text((16, 12), "RAW: green rectangle survives crop", fill="white")
        drawing.text((472, 12), "FINAL: inspect title, photo, table last row", fill="white")
        sheet.paste(raw_preview, (16, 42))
        sheet.paste(final_preview, (472, 42))
        preview_path = output / f"card-{job['card_index']:02d}.jpg"
        sheet.save(preview_path, quality=88)
        records.append({"card_index": job["card_index"], "raw_path": str(raw_path),
                        "final_path": str(final_path.resolve()), "raw_sha256": raw_hash,
                        "final_sha256": final_hash, "preview": str(preview_path.resolve()), **geometry})
    report = {"direction_id": direction, "status": "visual_review_required", "pixel_modification": False, "cards": records}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Compare actual backend raw images with final center crops; never approve content automatically.")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--direction", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(audit(args.work_dir, args.direction), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
