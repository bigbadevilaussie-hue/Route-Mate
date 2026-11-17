# Solver experiments

## stripboard-py fixture probe

`stripboard_py_probe.py` runs the Route-Mate Moto and Audio fixtures through the
upstream Python stripboard solver. It is an experiment harness only; it does not
change Route-Mate's solver or claim that the resulting partial netlists are buildable.

### Install

Requires Python 3.12+ and the upstream MIT package:

```bash
python3 -m pip install "stripboard @ git+https://github.com/Stocko-2073/stripboard-py.git@dev"
```

### Run

From the repository root:

```bash
python3 experiments/stripboard_py_probe.py --project both --seeds 0 1 2
```

A single fixture or seed can be isolated:

```bash
python3 experiments/stripboard_py_probe.py --project moto --seeds 0
python3 experiments/stripboard_py_probe.py --project audio --seeds 0 1 2 3
```

Search effort can be changed explicitly:

```bash
python3 experiments/stripboard_py_probe.py --project moto --seeds 0 1 2 --iterations 1200 --attempts 4
```

Each output line is one JSON record. Compare seeds on the same machine-independent
work budget (iterations and placement attempts), not elapsed time.

### Adapter rules and known limitations

- Route-Mate board `rows × cols` maps to solver `height × width`; solver copper strips
  run along the horizontal `x` axis.
- Built-in and project custom definitions are resolved through Route-Mate's current
  `render._geometry` registry.
- Route-Mate's sparse `bodyCells` are preserved as one-cell keep-outs, not bounding boxes.
- Route-Mate rotations (0/90/180/270) are transformed into local pin/body coordinates
  before the solver is called. The upstream solver itself only offers translation and
  180-degree flipping during placement.
- Repeated physical holes representing the same logical pin ID are assigned unique
  solver pin IDs and tied internally.
- Off-board components are omitted. Assignments to them are counted and named in the
  report. Any net with off-board terminals is consequently incomplete in this experiment.
- Flexible two-terminal footprints use their declared default pin offsets. A manually
  stretched `flexibleEndPos` is not currently represented.
- The upstream solver synthesizes singleton nets for unassigned physical pins.
- The solver's placement model reserves body keep-outs but permits copper strips through
  those keep-outs. This is an upstream model rule, not a Route-Mate decision.

**Do not interpret `ok: true` as a Route-Mate buildability result.** It means only that
the upstream solver completed and validated the converted, on-board-only model. Route-Mate
still needs its own physical rules, off-board terminal allocation and independent verifier.

### Upstream provenance

Fetched directly from the upstream repositories, not from copies in Route-Mate:

- `Stocko-2073/stripboard-py`, branch `dev`, tree commit
  `346efd8425cc13cbde22ab8261df6c8cbd817973`, MIT.
- Router model blob: `3265a8ae9b100f89fc99a3b3cfc31eea634be01d`.
- Placement blob: fetched from the same upstream branch during this experiment.
- Router specification: `docs/router-spec.md` from the same branch.

The install command tracks the upstream `dev` branch. For a fully frozen repeat,
replace `@dev` with the exact tree commit above.
