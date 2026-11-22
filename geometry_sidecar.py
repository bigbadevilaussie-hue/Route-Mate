"""Collector sidecar persistence and board-local 2.5D *assumption* audit.

No per-project or component-label exceptions. The collector owns the profiles,
this module binds them to one exact project snapshot and applies the saved
component's actual pin geometry (including flexible end positions/rotations).
Both independent 2.5D engines must agree. These are conditional engineering
estimates, not measured clearance or a safety certification.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from board_geometry import BUILTIN_DEFS, component_geometry, resolve_definition
from collector_geometry import build_assumed_geometry
from placement_policy import is_off_board_component
from solve.clearance_25d import classify_jumper
from solve.clearance_25d_verify import verify_jumper_25d

PITCH = 2.54
SCHEMA = "route-mate/project-geometry-sidecar/1"


def sidecar_path(source_path: str | Path) -> Path:
    file = Path(source_path)
    return file.with_name(f"{file.stem}.routemate-geometry.json")


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _collector_campaign_geometry(project: dict, source_path: str | Path):
    """Read collector's actual campaign sidecar, if one belongs to this file.

    Normal campaign path: <output>/projects/<id>.json with
    <output>/physical_geometry.json and <output>/manifest.json. Check the
    source project identifier and sidecar digest before trusting it.
    """
    project_file = Path(source_path)
    if project_file.parent.name != "projects":
        return None
    root = project_file.parent.parent
    physical = root / "physical_geometry.json"
    manifest_file = root / "manifest.json"
    if not physical.exists() or not manifest_file.exists():
        return None
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if Path(manifest.get("campaign_project", "")).resolve() != project_file.resolve():
        return None
    raw = physical.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.get("physical_geometry_sidecar_sha256"):
        raise ValueError("collector campaign geometry sidecar SHA-256 mismatch")
    model = json.loads(raw)
    expected = build_assumed_geometry(project)
    if model != expected:
        raise ValueError("collector campaign geometry sidecar differs from project or preset")
    return model


def load_or_create(project: dict, source_path: str | Path, *, persist=True) -> dict:
    """Fail closed on an out-of-date sidecar; never silently accept stale geometry.

    The project hash covers positions, wiring, values and footprint overrides.
    If the project changed, rebuild from the collector's authoritative presets.
    """
    dest = sidecar_path(source_path)
    campaign_model = _collector_campaign_geometry(project, source_path)
    expected = campaign_model if campaign_model is not None else build_assumed_geometry(project)
    signature = _hash(project)
    if dest.exists():
        existing = json.loads(dest.read_text(encoding="utf-8"))
        if (isinstance(existing, dict) and existing.get("schema") == SCHEMA
                and existing.get("project_sha256") == signature
                and existing.get("geometry") == expected
                and existing.get("geometry_sha256") == _hash(expected)):
            return existing
    document = {
        "schema": SCHEMA,
        "project_sha256": signature,
        "geometry_sha256": _hash(expected),
        "geometry": expected,
        "geometry_origin": ("collector_campaign" if campaign_model is not None
                            else "collector_profile_generated_for_gui"),
    }
    if persist:
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_text(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False)
                       + "\n", encoding="utf-8")
        tmp.replace(dest)
    return document


def _definition(part, defs):
    definition = resolve_definition(part, defs)
    if definition is None:
        return None
    return definition


def _installed_shape(part: dict, definition: dict, entry: dict) -> dict | None:
    """Place one saved local-profile shape at the actual physical pin centroid.

    Shape centre comes from exact solved pin coordinates, not from guessed
    rotation origin. For 2-lead passives, orient rectangle long axis along the
    actual pin vector, including flexibleEndPos.
    """
    bodies = entry.get("body_solids") or []
    if not bodies:
        return None
    pins, _ = component_geometry(part, definition)
    if not pins:
        return None
    xs = [float(pin["col"]) * PITCH for pin in pins]
    ys = [float(pin["row"]) * PITCH for pin in pins]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    raw = bodies[0]
    if raw["shape"] == "circle":
        shape = {"shape": "circle", "center_mm": [cx, cy],
                 "radius_mm": raw["radius_mm"]}
    elif raw["shape"] == "rectangle":
        w = raw["x_max_mm"] - raw["x_min_mm"]
        h = raw["y_max_mm"] - raw["y_min_mm"]
        # Local long dimension follows actual two-terminal direction.
        if len(pins) == 2 and abs(ys[1] - ys[0]) > abs(xs[1] - xs[0]):
            w, h = min(w, h), max(w, h)
        elif len(pins) == 2:
            w, h = max(w, h), min(w, h)
        elif int(part.get("rotation", 0) or 0) % 180 == 90:
            w, h = h, w
        shape = {"shape": "rectangle", "x_min_mm": cx - w / 2,
                 "x_max_mm": cx + w / 2, "y_min_mm": cy - h / 2,
                 "y_max_mm": cy + h / 2}
    else:
        raise ValueError("unsupported collector body shape")
    shape.update({
        "id": str(part["id"]), "z_min_mm": raw["assumed_z_min_mm"],
        "z_max_mm": raw["assumed_z_max_mm"],
        # An assumption is a user-selected *design hypothesis*, never measured.
        # The independent engines return CONDITIONAL where the hypothesis
        # permits an under-body path; physically uncertified until measured.
        "z_min_source": "user_declared",
    })
    return shape


def assess_saved_board(project: dict, document: dict) -> dict:
    """Independent per-jumper 2.5D comparison using sidecar as source of truth."""
    if document.get("schema") != SCHEMA or document.get("project_sha256") != _hash(project):
        raise ValueError("geometry sidecar does not match project snapshot")
    model = document["geometry"]
    if document.get("geometry_sha256") != _hash(model):
        raise ValueError("geometry sidecar integrity mismatch")
    settings = model["clearance_assumptions"]
    defs = dict(BUILTIN_DEFS)
    defs.update({str(d["id"]): d for d in project.get("componentDefs", [])
                 if isinstance(d, dict) and d.get("id")})
    parts = {str(p["id"]): p for p in project.get("components", [])
             if isinstance(p, dict) and p.get("id") and not is_off_board_component(p)}
    solids = []
    unknown = []
    for entry in model["components"]:
        cid = entry["id"]
        if cid not in parts:
            continue
        definition = _definition(parts[cid], defs)
        if definition is None or not entry.get("body_solids"):
            unknown.append(entry.get("label") or cid)
            continue
        solid = _installed_shape(parts[cid], definition, entry)
        if solid is None:
            unknown.append(entry.get("label") or cid)
        else:
            solids.append(solid)
    findings = []
    by_wire = []
    counts = {"PASS": 0, "CONDITIONAL": 0, "FAIL_UNVERIFIED": 0,
              "FAIL_PROVEN": 0}
    for index, wire in enumerate(project.get("board", {}).get("wires", [])):
        a, b = wire["from"], wire["to"]
        case = {
            "jumper": {"from_mm": [a["col"] * PITCH, a["row"] * PITCH],
                       "to_mm": [b["col"] * PITCH, b["row"] * PITCH]},
            "settings": settings,
            "body_solids": solids,
            # Saved profile pin radii are assumed too; unknown hardware access
            # remains uncertified. Existing hard pad/endpoint rules still apply.
            "leads": [],
        }
        router = classify_jumper(case)
        independent = verify_jumper_25d(case)
        if router["verdict"] != independent["verdict"] or router["findings"] != independent["findings"]:
            raise ValueError(f"independent 2.5D disagreement on {wire.get('id', index)}")
        verdict = independent["verdict"]
        counts[verdict] += 1
        by_wire.append({"id": str(wire.get("id", index)), "verdict": verdict,
                        "findings": independent["findings"]})
        for finding in independent["findings"]:
            findings.append({"wire": str(wire.get("id", index)), **finding})
    # A design-estimate PASS cannot be a physical PASS. Even a geometrically
    # unobstructed wire is conditional upon the actual package size/wiring.
    if counts["FAIL_PROVEN"]:
        status = "ASSUMED_CONFLICT"
    elif counts["FAIL_UNVERIFIED"] or unknown:
        status = "UNVERIFIED"
    else:
        status = "ASSUMED_CLEARANCE_PASS"
    return {
        "status": status,
        "counts": counts,
        "wire_results": by_wire,
        "findings": findings,
        "unknown_bodies": sorted(unknown),
        "profile": model["preset"],
        "physical_signoff": False,
        "scope": "assumed-body-geometry-only; pad legality and cut access separately checked",
    }


__all__ = ["sidecar_path", "load_or_create", "assess_saved_board"]
