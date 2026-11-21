"""Read-only PREPARE intelligence for every component and advisory board sizing.

No placement, routing, physical-clearance or source-project mutation occurs here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from board_geometry import BUILTIN_DEFS, resolve_definition, component_geometry
from pipeline.contracts import project_sha256
from placement_policy import is_off_board_component

SCHEMA = "route-mate-presolve"
VERSION = 1


def analyse_project(project: dict[str, Any]) -> dict[str, Any]:
    """Return uniform per-component records and a non-certifying board estimate."""
    board = project.get("board", {})
    if not isinstance(board, dict):
        raise ValueError("board must be an object")
    defs = {**BUILTIN_DEFS, **{
        str(d["id"]): d for d in project.get("componentDefs", [])
        if isinstance(d, dict) and d.get("id")
    }}
    assignments: dict[str, dict[str, str]] = defaultdict(dict)
    fanout: Counter[str] = Counter()
    for item in project.get("netAssignments", []):
        if not isinstance(item, dict):
            continue
        cid, pid, nid = (str(item.get(k, "")) for k in ("componentId", "pinId", "netId"))
        if cid and pid and nid:
            if pid in assignments[cid] and assignments[cid][pid] != nid:
                raise ValueError(f"pin {cid}/{pid} is assigned to multiple nets")
            assignments[cid][pid] = nid
            fanout[nid] += 1

    records = []
    unresolved = []
    placeable_area = 0
    largest_rows = largest_cols = 0
    for component in project.get("components", []):
        cid = str(component["id"])
        definition = resolve_definition(component, defs)
        off_board = is_off_board_component(component)
        net_by_pin = assignments[cid]
        record: dict[str, Any] = {
            "component_id": cid,
            "definition_id": str(component.get("defId") or component.get("componentDefId") or ""),
            "off_board": off_board,
            "geometry": {"resolved": definition is not None, "orientations": []},
            "electrical": {
                "assigned_pin_count": len(net_by_pin),
                "distinct_net_count": len(set(net_by_pin.values())),
                "net_ids": sorted(set(net_by_pin.values())),
                "net_fanout": {n: fanout[n] for n in sorted(set(net_by_pin.values()))},
            },
            "placement": {
                "locked": bool(component.get("locked", False)),
                "existing_board_pos": component.get("boardPos"),
                "candidate_status": "advisory_only",
            },
            "warnings": [],
        }
        if definition is None:
            record["warnings"].append("unresolved_footprint")
            unresolved.append(cid)
        else:
            orientations = [int(component.get("rotation", 0) or 0) % 360] if (
                component.get("locked") and component.get("boardPos") is not None
            ) else [0, 90, 180, 270]
            for rotation in orientations:
                # Use the shared geometry resolver; anchor at zero only for analysis.
                # FlexibleEndPos is absolute and therefore requires translation.
                temp = {**component, "boardPos": {"row": 0, "col": 0}, "rotation": rotation}
                end = component.get("flexibleEndPos")
                pos = component.get("boardPos")
                if isinstance(end, dict) and isinstance(pos, dict):
                    temp["flexibleEndPos"] = {
                        "row": int(end["row"]) - int(pos["row"]),
                        "col": int(end["col"]) - int(pos["col"]),
                    }
                elif isinstance(end, dict):
                    # Without an anchor, an absolute endpoint cannot be normalised.
                    temp.pop("flexibleEndPos", None)
                    record["warnings"].append("unanchored_flexible_endpoint")
                pins, body = component_geometry(temp, definition)
                cells = [(int(p["row"]), int(p["col"])) for p in pins] + list(body)
                min_row = min((r for r, _ in cells), default=0)
                min_col = min((c for _, c in cells), default=0)
                max_row = max((r for r, _ in cells), default=0)
                max_col = max((c for _, c in cells), default=0)
                rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for pin in pins:
                    rows[int(pin["row"])].append({
                        "pin_id": str(pin["id"]), "col": int(pin["col"]),
                        "net_id": net_by_pin.get(str(pin["id"])),
                    })
                conflicts = []
                for row, entries in sorted(rows.items()):
                    entries.sort(key=lambda p: (p["col"], p["pin_id"]))
                    for left, right in zip(entries, entries[1:]):
                        if left["net_id"] and right["net_id"] and left["net_id"] != right["net_id"]:
                            if left["col"] == right["col"]:
                                record["warnings"].append("different_nets_same_hole")
                            else:
                                conflicts.append({
                                    "row": row, "left_pin": left["pin_id"],
                                    "right_pin": right["pin_id"],
                                    "possible_cut_gaps": list(range(left["col"], right["col"])),
                                    "verified": False,
                                })
                record["geometry"]["orientations"].append({
                    "rotation": rotation,
                    "span_rows": max_row - min_row + 1,
                    "span_cols": max_col - min_col + 1,
                    "pins": [{**p, "net_id": net_by_pin.get(str(p["id"]))} for p in pins],
                    "body_cells": [{"row": r, "col": c} for r, c in body],
                    "pin_rows": [{"row": r, "pins": entries} for r, entries in sorted(rows.items())],
                    "different_net_pairs": conflicts,
                    "physical_clearance_verified": False,
                })
            if not off_board:
                area = min(o["span_rows"] * o["span_cols"] for o in record["geometry"]["orientations"])
                placeable_area += area
                largest_rows = max(largest_rows, min(o["span_rows"] for o in record["geometry"]["orientations"]))
                largest_cols = max(largest_cols, min(o["span_cols"] for o in record["geometry"]["orientations"]))
        records.append(record)

    rows = board.get("rows")
    cols = board.get("cols")
    locked_rows = bool(board.get("lockedRows", False))
    locked_cols = bool(board.get("lockedCols", False))
    existing_area = rows * cols if type(rows) is int and type(cols) is int and rows > 0 and cols > 0 else None
    return {
        "schema": SCHEMA, "schema_version": VERSION,
        "source_project_sha256": project_sha256(project),
        "components": records,
        "board": {
            "source_rows": rows, "source_cols": cols,
            "locked_rows": locked_rows, "locked_cols": locked_cols,
            "sum_min_footprint_bounding_areas": placeable_area,
            "largest_component_min_rows": largest_rows,
            "largest_component_min_cols": largest_cols,
            "source_area": existing_area,
            "source_area_vs_footprint_estimate": (
                "below_estimate" if existing_area is not None and existing_area < placeable_area
                else "not_below_estimate" if existing_area is not None else "unknown"
            ),
            "recommended_rows": None, "recommended_cols": None,
            "recommendation_status": "not_calculated_requires_routing_and_packing_model",
            "physical_fit_verified": False,
        },
        "warnings": [{"component_id": cid, "code": "unresolved_footprint"} for cid in unresolved],
    }
