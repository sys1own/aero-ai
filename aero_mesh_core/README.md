# Aero-Mesh core (Part 1 — scaffolding)

A parallel scan / link / aggregate topology built on top of the existing
`aero_auto_sdk` toolchain (`meta_compiler.py` + the `aero_sdk` compiler/VM).
It pairs the local, code-side scaffolding with a fully **local optimization
loop** (`evolve_loop.py`) — **no LLM integration and no network access**. The
loop drives evolution with a deterministic, rule-based Symbolic Topological
Mutation Engine instead of any cloud API.

## Layout

```
aero_mesh_core/
├── README.md              # this file
├── scaffold_testbed.py    # deterministic, local-only mock-corpus generator
├── recipes/
│   └── seed_topology.txt  # declarative parallel topology (scouts/linkers/aggregate)
├── testbed/               # generated corpus (git-ignored; regenerate on demand)
└── dist/                  # build outputs; *.aeroc git-ignored (.gitkeep tracked)
```

`testbed/` and `dist/*.aeroc` are **reproducible artifacts** and are
git-ignored on purpose — track the generator and the recipe, not their output.

## Regenerate everything

```bash
# 1) materialize the local benchmark corpus (writes only under testbed/)
python aero_mesh_core/scaffold_testbed.py --summary

# 2) lower the recipe through the real SDK and emit dist/seed_topology.aeroc
python meta_compiler.py aero_mesh_core/recipes/seed_topology.txt \
    -o aero_mesh_core/dist/seed_topology.aeroc --show
```

## SDK baseline alignment

The recipe and generator were verified against the actual SDK source:

* **Recipe ops** use only `print` / `call` / `comment`, which `meta_compiler`'s
  `_lower_task` lowers to valid Aero; the FFI calls (`create_dir`, `write_file`)
  are exactly the names `codegen.py` intercepts as `CALL_DIRECT` macros.
* **Topology** is expressed purely through `needs`, honored by the stable
  topological sort in both `compile_recipe` (sequential) and
  `execute_recipe_parallel` (concurrent).
* **Parallel-safety**: `execute_recipe_parallel` runs each task on its own
  fresh `AeroVM`, so tasks share no in-memory variables. Every task here is
  self-contained and coordinates through files — so it behaves identically
  under `--run` and the parallel runner.

## Evolution loop (local mutation engine)

`evolve_loop.py` upgrades the meshes without any cloud LLM. It:

1. **Ingests the swarm bytecode** — loads the four compiled `.aeroc` binaries
   (ingress / processing / aggregation / seed), validates them, and runs the
   runnable ones on the AeroVM as the operational foundation.
2. **Mutates** each mesh blueprint with strict, deterministic heuristics —
   *task splitting* (parallelize on a wall spike), *dependency flipping*
   (rewire `needs` within safe data-dependency constraints), and *dead-code
   pruning* (drop unconsumed value tasks). Every candidate must pass a
   topological + data-dependency validity check.
3. **Selects on fitness** — each candidate goes through the deterministic
   `meta_compiler` gate; syntax faults are discarded instantly; survivors run
   on the VM and are timed. A champion must beat both the all-time best and a
   freshly re-measured baseline (noise-resistant), and is then written to disk
   and recorded in `dist/swarm_metrics.json` / `dist/evolve_report.json`.

```bash
# Evolve locally for 60s (deterministic; nothing is pushed)
python aero_mesh_core/evolve_loop.py --duration 60 --seed 1337

# Same, but commit + push accepted champions to a dedicated branch
python aero_mesh_core/evolve_loop.py --duration 60 --push --push-branch evolution/auto-champions
```

Pushing is **opt-in** (`--push`, off by default) and targets the current
branch (or `--push-branch`) — never `main` implicitly. All candidate execution
is sandboxed under `build_sandbox/_runtime/`, so evaluation never dirties
tracked files.

## Scope & safety (Part 1)

* The generator is standard-library only, deterministic for a given `--seed`,
  performs **no deletion** and **no network I/O**, and validates every write
  path to stay inside `testbed/`.
* All recipe file I/O is confined to `aero_mesh_core/dist/`.
