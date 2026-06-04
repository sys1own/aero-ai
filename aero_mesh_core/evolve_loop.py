"""
Aero-Mesh evolve loop — local, human-in-the-loop schedule optimizer
==================================================================

Drives time-bounded tuning of the parallel build topology:

    measure (parallel run + VM telemetry)
        -> ask the LLM for a *constrained* proposal
        -> validate it through the real lexer/parser/codegen
        -> (optionally) apply it to local files, with a backup
        -> repeat until the duration window closes

Scope / safety (deliberate)
---------------------------
* **Local only.** This script never runs git, never pushes, never deletes
  itself or other sources, and only edits two files: the target recipe and
  ``config/language_spec.json`` — each backed up before any write. It produces
  a report + diffs for a human to review and commit. There is no autonomous
  push-to-``main`` and no opaque-artifact step here.
* **The LLM is boxed in.** It may only return strict JSON proposing:
  (a) ``needs_overrides`` — new dependency lists for *existing* tasks, using
  *existing* task names, and (b) ``preference_levels`` — integer weights for
  *known* operators. Anything else is dropped. The model cannot introduce new
  tasks, file paths, or commands, so corpus content can't escalate into an
  arbitrary write. We also send only the dependency graph + metrics to the
  model, never raw testbed text.
* **Validation gate.** Every proposal is lowered + compiled before use; a
  failure triggers a single bounded correction round, otherwise the proposal
  is discarded and the last-known-good config is kept.

Conservative defaults: without ``--tune`` no LLM is called; without ``--apply``
no file is modified (proposals are only reported). Running with no flags does a
single measured pass and prints telemetry.

    python aero_mesh_core/evolve_loop.py --duration 300            # measure-only
    python aero_mesh_core/evolve_loop.py --duration 300 --tune     # propose, don't write
    python aero_mesh_core/evolve_loop.py --duration 300 --tune --apply
"""

import argparse
import copy
import json
import os
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)            # repo root (where meta_compiler.py lives)
for _p in (_ROOT, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import meta_compiler  # noqa: E402  (uses _ROOT on sys.path)
from aero_sdk.compiler.lexer import tokenize  # noqa: E402
from aero_sdk.compiler.parser import Parser  # noqa: E402
from aero_sdk.compiler.codegen import Codegen  # noqa: E402
import llm_client  # noqa: E402  (same directory)

DEFAULT_RECIPE = os.path.join(_HERE, "recipes", "seed_topology.txt")
SPEC_PATH = os.path.join(_ROOT, "config", "language_spec.json")
VM_PROFILE_CANDIDATES = [
    os.path.join(_ROOT, "config", "vm_profile.json"),
    os.path.join(_ROOT, "aero_auto_sdk", "config", "vm_profile.json"),
]
REPORT_PATH = os.path.join(_HERE, "dist", "evolve_report.json")
BACKUP_DIR = os.path.join(_HERE, "dist", "backups")

_SYSTEM_PROMPT = (
    "You optimize a parallel build schedule. You are given a task dependency "
    "graph and timing/opcode telemetry. Respond with STRICT JSON only (no prose, "
    "no code fences) of the form: "
    '{"needs_overrides": {"<task>": ["<dep>", ...]}, '
    '"preference_levels": {"<operator>": <int>}}. '
    "Only reference task names and operators that already exist. Reducing the "
    "critical-path depth of independent tasks improves thread utilization."
)


# ── Telemetry ──────────────────────────────────────────────────────────────

def load_vm_profile():
    for path in VM_PROFILE_CANDIDATES:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return {}
    return {}


def measure(recipe_path, workers):
    """Time a full parallel run and snapshot opcode telemetry.

    NOTE: this actually executes the parallel scheduler — only called inside an
    explicit run, never at import time.
    """
    t0 = time.time()
    meta_compiler.execute_recipe_parallel(recipe_path, max_workers=workers)
    wall_ms = int((time.time() - t0) * 1000)
    return {"wall_ms": wall_ms, "opcodes": load_vm_profile()}


# ── Recipe (de)serialization & validation ──────────────────────────────────

def recipe_to_ini(recipe):
    """Serialize a parsed recipe dict back to INI text.

    Only structural fields are written; source comments are not preserved, so
    we always keep a backup of the human-authored original before overwriting.
    """
    lines = ["[project]"]
    for k, v in recipe["project"].items():
        lines.append(f"{k} = {v}")
    lines.append("")
    for t in recipe["tasks"]:
        lines.append(f"[task:{t['name']}]")
        lines.append(f"op = {t['op']}")
        for k, v in t["fields"].items():
            lines.append(f"{k} = {v}")
        if t["needs"]:
            lines.append(f"needs = {', '.join(t['needs'])}")
        lines.append("")
    return "\n".join(lines) + "\n"


def validate(recipe):
    """Lower + compile a recipe dict. Returns (ok, error_str)."""
    try:
        source = meta_compiler.generate_aero(recipe)  # raises on cycle/unknown dep
        Codegen().compile(Parser(tokenize(source)).parse())
        return True, None
    except Exception as exc:  # RecipeError / Lexer / Parser / Codegen errors
        return False, f"{type(exc).__name__}: {exc}"


# ── Proposal handling (the LLM's blast radius lives here) ───────────────────

def known_operators():
    try:
        with open(SPEC_PATH, "r", encoding="utf-8") as fh:
            return set(json.load(fh).get("operators", []))
    except (OSError, ValueError):
        return set()


def graph_summary(recipe):
    return {t["name"]: list(t["needs"]) for t in recipe["tasks"]}


def parse_proposal(text, valid_tasks, valid_ops):
    """Extract + sanitize the model's JSON. Drops anything outside the schema."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    raw = json.loads(text[start:end + 1])

    needs = {}
    for task, deps in (raw.get("needs_overrides") or {}).items():
        if task in valid_tasks and isinstance(deps, list):
            clean = [d for d in deps if d in valid_tasks and d != task]
            needs[task] = clean
    prefs = {}
    for op, lvl in (raw.get("preference_levels") or {}).items():
        if op in valid_ops and isinstance(lvl, int):
            prefs[op] = lvl
    return {"needs_overrides": needs, "preference_levels": prefs}


def apply_needs(recipe, overrides):
    new = copy.deepcopy(recipe)
    for t in new["tasks"]:
        if t["name"] in overrides:
            t["needs"] = list(overrides[t["name"]])
    return new


def backup_file(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"{os.path.basename(path)}.{stamp}.bak")
    shutil.copy2(path, dest)
    return dest


def apply_preference_levels(prefs):
    """Write numeric operator weights into the spec (safe, bounded fields only).

    NOTE: today this is runtime-inert — the live lexer tables are only rebuilt
    from the spec via aero_sdk.optimizer.generator, which is not present in the
    repo. We still back up and validate JSON so the lever is ready once that
    regeneration path exists.
    """
    try:
        with open(SPEC_PATH, "r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"[evolve] cannot read spec, skipping preference update: {exc}")
        return False
    spec.setdefault("preference_levels", {}).update(prefs)
    backup_file(SPEC_PATH)
    with open(SPEC_PATH, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
    print(f"[evolve] updated preference_levels for: {sorted(prefs)}")
    return True


# ── Main loop ──────────────────────────────────────────────────────────────

def run(args):
    recipe = meta_compiler.load_recipe(args.recipe)
    valid_tasks = {t["name"] for t in recipe["tasks"]}
    valid_ops = known_operators()

    client = None
    if args.tune:
        client = llm_client.LLMClient(selection=args.selection)
        if not client.available():
            print("[evolve] --tune set but no providers configured; "
                  "continuing in measure-only mode")
            client = None

    deadline = time.time() + args.duration
    history, best = [], None
    cycle = 0

    while time.time() < deadline and cycle < args.max_cycles:
        cycle += 1
        remaining = int(deadline - time.time())
        print(f"\n=== cycle {cycle}/{args.max_cycles} "
              f"({remaining}s left) ===")

        metrics = measure(args.recipe, args.workers)
        print(f"[evolve] wall_ms={metrics['wall_ms']} "
              f"opcodes={len(metrics['opcodes'])} kinds")
        if best is None or metrics["wall_ms"] < best["wall_ms"]:
            best = {"cycle": cycle, "wall_ms": metrics["wall_ms"]}

        record = {"cycle": cycle, "metrics": metrics, "proposal": None,
                  "validated": None, "applied": False}

        if client is not None:
            proposal, ok, err = _propose_and_validate(
                client, recipe, valid_tasks, valid_ops, metrics)
            record["proposal"] = proposal
            record["validated"] = ok
            if ok and proposal:
                if args.apply:
                    _apply(args.recipe, recipe, proposal)
                    recipe = meta_compiler.load_recipe(args.recipe)
                    record["applied"] = True
                else:
                    print("[evolve] proposal valid (not applied; pass --apply to write)")
            elif not ok:
                print(f"[evolve] proposal discarded after validation: {err}")

        history.append(record)

    _write_report({"recipe": args.recipe, "cycles": history, "best": best})
    print(f"\n[evolve] done: {cycle} cycle(s); best wall_ms="
          f"{best['wall_ms'] if best else 'n/a'}; report -> "
          f"{os.path.relpath(REPORT_PATH)}")
    print("[evolve] no changes were committed or pushed — review the diffs/"
          "backups and merge manually.")


def _propose_and_validate(client, recipe, valid_tasks, valid_ops, metrics):
    prompt = json.dumps({"graph": graph_summary(recipe),
                         "wall_ms": metrics["wall_ms"],
                         "opcodes": metrics["opcodes"]}, indent=2)
    try:
        resp = client.complete(prompt, system=_SYSTEM_PROMPT)
    except llm_client.LLMError as exc:
        print(f"[evolve] LLM call failed: {exc}")
        return None, False, str(exc)

    try:
        proposal = parse_proposal(resp.text, valid_tasks, valid_ops)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, False, f"unparseable proposal: {exc}"

    candidate = apply_needs(recipe, proposal["needs_overrides"])
    ok, err = validate(candidate)
    if ok:
        return proposal, True, None

    # One bounded correction round — relay diagnostics, re-validate once.
    print(f"[evolve] validation failed ({err}); requesting one correction")
    try:
        resp = client.complete(
            f"Your previous JSON failed validation with: {err}\n"
            f"Return corrected STRICT JSON for graph:\n"
            f"{json.dumps(graph_summary(recipe))}",
            system=_SYSTEM_PROMPT)
        proposal = parse_proposal(resp.text, valid_tasks, valid_ops)
    except (llm_client.LLMError, ValueError, json.JSONDecodeError) as exc:
        return None, False, f"correction failed: {exc}"
    ok, err = validate(apply_needs(recipe, proposal["needs_overrides"]))
    return (proposal if ok else None), ok, err


def _apply(recipe_path, recipe, proposal):
    if proposal["needs_overrides"]:
        backup_file(recipe_path)
        new_recipe = apply_needs(recipe, proposal["needs_overrides"])
        with open(recipe_path, "w", encoding="utf-8") as fh:
            fh.write(recipe_to_ini(new_recipe))
        print(f"[evolve] applied needs_overrides for: "
              f"{sorted(proposal['needs_overrides'])} (backup saved)")
    if proposal["preference_levels"]:
        apply_preference_levels(proposal["preference_levels"])


def _write_report(report):
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Local Aero-Mesh schedule optimizer.")
    ap.add_argument("--duration", type=int, default=300,
                    help="max optimization window in seconds (default 300)")
    ap.add_argument("--max-cycles", type=int, default=5,
                    help="hard cap on iterations (default 5)")
    ap.add_argument("--recipe", default=DEFAULT_RECIPE, help="recipe to optimize")
    ap.add_argument("--workers", type=int, default=4, help="parallel workers")
    ap.add_argument("--tune", action="store_true",
                    help="call the LLM for proposals (default: measure-only)")
    ap.add_argument("--apply", action="store_true",
                    help="write validated proposals to disk (default: report-only)")
    ap.add_argument("--selection", choices=["round_robin", "random"],
                    default="round_robin", help="provider selection strategy")
    args = ap.parse_args(argv)

    if not os.path.exists(args.recipe):
        print(f"evolve_loop: recipe not found: {args.recipe}", file=sys.stderr)
        return 2
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
