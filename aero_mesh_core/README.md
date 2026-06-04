# Aero-Mesh core (Part 1 — scaffolding)

A parallel scan / link / aggregate topology built on top of the existing
`aero_auto_sdk` toolchain (`meta_compiler.py` + the `aero_sdk` compiler/VM).
This directory currently contains **only the local, code-side scaffolding** —
no LLM integration, no optimization loop, no network access.

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

## Scope & safety (Part 1)

* The generator is standard-library only, deterministic for a given `--seed`,
  performs **no deletion** and **no network I/O**, and validates every write
  path to stay inside `testbed/`.
* All recipe file I/O is confined to `aero_mesh_core/dist/`.
