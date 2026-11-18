"""Deterministic first-fit component placement for Route-Mate."""
from __future__ import annotations
from typing import Any
from render._geometry import component_geometry, resolve_definition

def _excluded(c):
    return c.get("offBoard") is True or c.get("boardExcluded") is True

def _shape(component, definition, rotation):
    probe = {**component, "boardPos": {"row": 0, "col": 0}, "rotation": rotation}
    pins, body = component_geometry(probe, definition)
    cells = {(int(p["row"]), int(p["col"])) for p in pins}
    cells.update((int(r), int(c)) for r, c in body)
    return cells

def quick_place(project: dict[str, Any]) -> dict[str, Any]:
    """Place included components deterministically, largest footprints first.

    Existing placements marked locked=True are reserved and preserved.
    Other included components are placed afresh. The input is not modified.
    """
    import copy
    result = copy.deepcopy(project)
    board, components = result.get("board"), result.get("components")
    if not isinstance(board, dict) or not isinstance(components, list):
        return {"status":"FAIL","project":result,"errors":["project needs board and components"],"placed":0}
    try:
        rows, cols = int(board["rows"]), int(board["cols"])
        if rows < 1 or cols < 1: raise ValueError
    except (KeyError, TypeError, ValueError):
        return {"status":"FAIL","project":result,"errors":["board rows and cols must be positive integers"],"placed":0}
    defs = {str(d["id"]):d for d in result.get("componentDefs",[]) if isinstance(d,dict) and d.get("id")}
    occupied, errors, pending = set(), [], []
    for c in components:
        if not isinstance(c,dict) or _excluded(c): continue
        label = str(c.get("label") or c.get("id") or "unnamed")
        definition = resolve_definition(c, defs)
        if definition is None:
            errors.append(f"{label}: no footprint definition")
            continue
        if c.get("locked") is True and isinstance(c.get("boardPos"),dict):
            try:
                shape = _shape(c, definition, int(c.get("rotation",0) or 0)%360)
                pos = c["boardPos"]
                cells = {(int(pos.get("row",0))+r,int(pos.get("col",0))+col) for r,col in shape}
                if any(not(0<=r<rows and 0<=col<cols) for r,col in cells):
                    errors.append(f"{label}: locked footprint extends outside board")
                elif occupied.intersection(cells):
                    errors.append(f"{label}: locked footprint overlaps another locked footprint")
                else: occupied.update(cells)
            except (TypeError,ValueError,KeyError) as exc:
                errors.append(f"{label}: invalid locked footprint: {exc}")
        else:
            c["boardPos"] = None
            c.pop("flexibleEndPos", None)
            try: area = int(definition.get("width",1))*int(definition.get("height",1))
            except (TypeError,ValueError): area = len(definition.get("pins") or [])+len(definition.get("bodyCells") or [])
            pending.append((max(1,area),label,c,definition))
    if errors:
        return {"status":"FAIL","project":result,"errors":errors,"placed":0}
    pending.sort(key=lambda x:(-x[0],x[1]))
    placed = sum(1 for c in components if isinstance(c,dict) and not _excluded(c)
                 and c.get("locked") is True and isinstance(c.get("boardPos"),dict))
    for _area,label,c,definition in pending:
        try: current = int(c.get("rotation",0) or 0)%360
        except (TypeError,ValueError): current = 0
        rotations = [current]+[r for r in (0,90,180,270) if r != current]
        found = None
        for rotation in rotations:
            try: shape = _shape(c,definition,rotation)
            except (TypeError,ValueError,KeyError) as exc:
                errors.append(f"{label}: invalid footprint geometry: {exc}")
                break
            if not shape:
                errors.append(f"{label}: footprint has no physical cells")
                break
            minr,minc = min(r for r,col in shape),min(col for r,col in shape)
            maxr,maxc = max(r for r,col in shape),max(col for r,col in shape)
            height,width = maxr-minr+1,maxc-minc+1
            if height>rows or width>cols: continue
            for top in range(rows-height+1):
                for left in range(cols-width+1):
                    cells={(top+r-minr,left+col-minc) for r,col in shape}
                    if not occupied.intersection(cells):
                        found=(top-minr,left-minc,rotation,cells)
                        break
                if found: break
            if found: break
        if not found:
            errors.append(f"{label}: no non-overlapping placement fits on {rows}x{cols} board")
            break
        row,col,rotation,cells=found
        c["boardPos"]={"row":row,"col":col}
        c["rotation"]=rotation
        occupied.update(cells)
        placed+=1
    return {"status":"FAIL" if errors else "PASS","project":result,"errors":errors,
            "placed":placed,"excluded":sum(1 for c in components if isinstance(c,dict) and _excluded(c))}

__all__=["quick_place"]
