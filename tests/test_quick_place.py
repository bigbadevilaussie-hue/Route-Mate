"""Quick placement regression tests against both real project fixtures."""
from __future__ import annotations
import json
import unittest
from pathlib import Path
from collect import validate_project
from solve.quick_place import quick_place
from solve.verify import verify_project
from render._geometry import component_geometry, resolve_definition
ROOT=Path(__file__).resolve().parents[1]

def load(name):
    return validate_project(json.loads((ROOT/"benchmarks"/name/f"{name}.json").read_text(encoding="utf-8")))

class QuickPlaceTests(unittest.TestCase):
    def test_audio_places_all_included_components_deterministically(self):
        source=load("audio")
        a,b=quick_place(source),quick_place(source)
        self.assertEqual(a["status"],"PASS",a["errors"])
        self.assertEqual(a["placed"],14)
        self.assertEqual(a["excluded"],5)
        signature=lambda p:[(c["id"],c.get("boardPos"),c.get("rotation")) for c in p["components"]]
        self.assertEqual(signature(a["project"]),signature(b["project"]))
        self.assertTrue(all(c.get("boardPos") is None for c in source["components"]))

    def test_audio_footprint_cells_do_not_overlap(self):
        result=quick_place(load("audio"))
        self.assertEqual(result["status"],"PASS",result["errors"])
        p=result["project"]
        defs={str(d["id"]):d for d in p["componentDefs"]}
        occupied={}
        for c in p["components"]:
            if c.get("offBoard") or c.get("boardExcluded"): continue
            pins,body=component_geometry(c,resolve_definition(c,defs))
            cells={(x["row"],x["col"]) for x in pins}|set(body)
            for cell in cells:
                self.assertNotIn(cell,occupied,f"{c.get('label')} overlaps {occupied.get(cell)} at {cell}")
                occupied[cell]=c.get("label")

    def test_moto_places_then_verifies(self):
        result=quick_place(load("moto"))
        self.assertEqual(result["status"],"PASS",result["errors"])
        self.assertEqual(result["placed"],33)
        report=verify_project(result["project"])
        self.assertEqual(report["status"],"PASS",report["errors"])

    def test_locked_component_is_preserved(self):
        p={"board":{"rows":4,"cols":6},"componentDefs":[{"id":"two","width":2,"height":1,
           "pins":[{"id":"1","offsetRow":0,"offsetCol":0},{"id":"2","offsetRow":0,"offsetCol":1}],"bodyCells":[]}],
           "components":[{"id":"fixed","label":"Fixed","defId":"two","locked":True,"boardPos":{"row":2,"col":3}},
                         {"id":"free","label":"Free","defId":"two","boardPos":None}]}
        result=quick_place(p)
        self.assertEqual(result["status"],"PASS",result["errors"])
        fixed=next(c for c in result["project"]["components"] if c["id"]=="fixed")
        self.assertEqual(fixed["boardPos"],{"row":2,"col":3})

    def test_oversized_footprint_fails(self):
        p={"board":{"rows":2,"cols":2},"componentDefs":[{"id":"large","width":3,"height":3,
           "pins":[{"id":"1","offsetRow":0,"offsetCol":0}],"bodyCells":[]}],
           "components":[{"id":"large1","label":"Large","defId":"large"}]}
        result=quick_place(p)
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any("no non-overlapping placement" in e for e in result["errors"]))

if __name__=="__main__": unittest.main()
