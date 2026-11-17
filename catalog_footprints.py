#!/usr/bin/env python3
"""Build a flat CSV catalogue from a KiCad .pretty directory or ZIP.

The CSV keeps exact millimetre coordinates; it does not round pads to the
2.54 mm stripboard grid. One row is written per footprint. The pads_json
column contains every pad's number, type, shape, position, size and drill.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterable

NUM = r"-?(?:\d+(?:\.\d*)?|\.\d+)"


def extract_pads(text: str) -> list[dict]:
    pads = []
    # Pad records are single S-expression forms; this captures common KiCad
    # through-hole and SMD pad syntax without treating nested forms as pads.
    for match in re.finditer(
        rf'\(pad\s+"([^"]*)"\s+([^\s()]+)\s+([^\s()]+)(.*?)(?=\n\s*\(pad\s|\n\s*\)|\Z)',
        text, re.S
    ):
        number, pad_type, shape, body = match.groups()
        at = re.search(rf'\(at\s+({NUM})\s+({NUM})(?:\s+({NUM}))?\)', body)
        size = re.search(rf'\(size\s+({NUM})\s+({NUM})\)', body)
        drill = re.search(rf'\(drill\s+(?:oval\s+)?({NUM})(?:\s+({NUM}))?', body)
        if not at:
            continue
        pads.append({
            "number": number,
            "type": pad_type,
            "shape": shape,
            "x_mm": float(at.group(1)),
            "y_mm": float(at.group(2)),
            "rotation_deg": float(at.group(3) or 0),
            "width_mm": float(size.group(1)) if size else None,
            "height_mm": float(size.group(2)) if size else None,
            "drill_x_mm": float(drill.group(1)) if drill else None,
            "drill_y_mm": float(drill.group(2) or drill.group(1)) if drill else None,
        })
    return pads


def extract_outline_points(text: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    # Use fabrication and silkscreen primitives as the physical outline
    # candidates. Keep the bounds explicitly labelled as graphic bounds:
    # they are not guaranteed to be the component's true body dimensions.
    for kind in ("fp_rect", "fp_line", "fp_circle", "fp_arc", "fp_poly"):
        for item in re.finditer(rf'\({kind}\b(.*?)(?=\n\s*\(fp_|\n\s*\)|\Z)', text, re.S):
            body = item.group(1)
            for tag in ("start", "end", "center", "xy"):
                for xy in re.finditer(rf'\({tag}\s+({NUM})\s+({NUM})\)', body):
                    points.append((float(xy.group(1)), float(xy.group(2))))
    return points


def footprint_texts(source: Path) -> Iterable[tuple[str, str]]:
    if source.is_dir():
        for path in sorted(source.rglob("*.kicad_mod")):
            if not path.name.startswith("._"):
                yield path.stem, path.read_text(encoding="utf-8", errors="replace")
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for name in sorted(archive.namelist()):
                path = Path(name)
                if path.suffix == ".kicad_mod" and not path.name.startswith("._"):
                    yield path.stem, archive.read(name).decode("utf-8", errors="replace")
    else:
        raise ValueError(f"{source} is not a .pretty directory or ZIP archive")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="KiCad .pretty directory or ZIP")
    parser.add_argument("-o", "--out", type=Path, default=Path("footprints.csv"))
    args = parser.parse_args()
    if not args.source.exists():
        parser.error(f"source does not exist: {args.source}")

    rows = []
    for name, text in footprint_texts(args.source):
        pads = extract_pads(text)
        pts = extract_outline_points(text)
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            width, height = max(xs) - min(xs), max(ys) - min(ys)
        else:
            bbox, width, height = [], None, None
        rows.append({
            "footprint": name,
            "pad_count": len(pads),
            "through_hole_count": sum(p["type"] == "thru_hole" for p in pads),
            "body_graphic_width_mm": width,
            "body_graphic_height_mm": height,
            "body_graphic_bbox_mm": json.dumps(bbox, separators=(",", ":")),
            "pads_json": json.dumps(pads, separators=(",", ":")),
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "footprint", "pad_count", "through_hole_count",
        "body_graphic_width_mm", "body_graphic_height_mm",
        "body_graphic_bbox_mm", "pads_json",
    ]
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"CATALOGUED {len(rows)} footprints -> {args.out}")
    print("Pad coordinates and drill sizes are exact KiCad millimetres; body bounds are graphic bounds, not guaranteed body dimensions.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"catalogue: ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
