"""
Aero-Mesh Evolution Loop — Local Symbolic Topological Mutation Engine
====================================================================

A fully local, deterministic replacement for the old cloud-LLM tuning loop.

The previous version asked an external LLM cluster (``call_live_llm_cluster``)
to rewrite each mesh blueprint over the network. That made every run
non-deterministic, dependent on third-party API keys, and impossible to
reproduce. This rewrite removes the cloud client entirely and drives evolution
with a small, rule-based **Symbolic Topological Mutation Engine** running
natively on top of the static Aero Auto SDK (``meta_compiler.py`` + ``aero_sdk``).

Pipeline (per the three upgrade steps)
--------------------------------------
1. **Ingest the swarm bytecode.** At startup we load the four compiled
   ``.aeroc`` binaries (ingress / processing / aggregation / seed), validate
   their structure, and run the runnable ones on the AeroVM as the operational
   foundation — pipeline execution, data-transform reading, archiving sweeps.

2. **Local heuristic mutator.** Instead of an LLM prompt we apply strict,
   non-probabilistic software-engineering transforms to the mesh INI files:
       * Task splitting — on a wall-clock spike, re-parent a task onto a
         shared ancestor so it runs as a parallel pathway.
       * Dependency flipping — systematically drop / re-point ``needs`` edges
         within safe architectural constraints to probe for faster graphs.
       * Dead-code pruning — strip tasks whose produced values are never
         consumed downstream (and which have no side effects).
   Every proposal must survive a topological + data-dependency validity check
   before it is ever evaluated.

3. **Hard fitness loop.** For every mutation: run it through the deterministic
   ``meta_compiler`` gate; on a syntax fault, discard and revert instantly; on
   success, execute the bytecode on the AeroVM and time it. A mutation is kept
   only if it beats the current baseline (``last_execution_wall_ms``) by a
   margin; champions are written to disk, recorded in the metrics manifest,
   and — only when ``--push`` is set — committed and pushed to the current
   branch (never silently to ``main``).

Everything here is standard-library only and performs **no network I/O**
except the optional, opt-in ``git push`` of accepted champions.
"""

import argparse
import contextlib
import copy
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from meta_compiler import compile_recipe, load_recipe, _resolve_order, RecipeError
from aero_sdk.compiler.codegen import OpCode, CompiledProgram, CompiledFunction
from aero_sdk.vm.machine import AeroVM


# ── Topology constants ─────────────────────────────────────────────────────

# Evolution operates on these editable mesh blueprints.
MESHES = ["ingress_mesh.txt", "processing_mesh.txt", "aggregation_mesh.txt"]

# The four compiled binaries that form the operational foundation, mapped to
# the role each plays in the swarm.
SWARM_BINARIES = {
    "ingress_mesh.aeroc":     "pipeline execution",
    "processing_mesh.aeroc":  "data transform reading",
    "aggregation_mesh.aeroc": "archiving validation sweeps",
    "aero_mesh_seed.aeroc":   "topology seed",
}

# Canonical blueprint definitions. Used to scaffold a fresh workspace and to
# restore a mesh if it is missing or has been corrupted into an uncompilable
# state. Evolution overwrites the on-disk copies with fitter champions.
DEFAULT_BLUEPRINTS = {
    "ingress_mesh.txt": (
        "[project]\nname = ingress_mesh\noutput = build_sandbox/recipes/ingress_mesh.aeroc\n\n"
        "[task:init]\nop = print\ntext = \"-- Initializing Ingress Nodes --\"\n\n"
        "[task:ingest]\nop = call\nfn = read_file\nargs = \"testbed/scans/raw_telemetry_0\"\nneeds = init\n"
    ),
    "processing_mesh.txt": (
        "[project]\nname = processing_mesh\noutput = build_sandbox/recipes/processing_mesh.aeroc\n\n"
        "[task:compute]\nop = print\ntext = \"-- Processing Parallel Computations --\"\n\n"
        "[task:transform]\nop = call\nfn = write_file\nargs = \"aero_mesh_core/aero_mesh_core/dist/interim.tmp\", \"processed\"\nneeds = compute\n"
    ),
    "aggregation_mesh.txt": (
        "[project]\nname = aggregation_mesh\noutput = build_sandbox/recipes/aggregation_mesh.aeroc\n\n"
        "[task:consolidate]\nop = print\ntext = \"-- Aggregating Distributed State --\"\n\n"
        "[task:freeze]\nop = call\nfn = write_file\nargs = \"aero_mesh_core/aero_mesh_core/dist/index_manifest.txt\", \"state complete\"\nneeds = consolidate\n"
    ),
}

# All VM file I/O during evaluation happens with the CWD set here, so candidate
# runs never dirty tracked files in the repository tree.
_RUNTIME = os.path.join(_ROOT, "build_sandbox", "_runtime")
_BP_DIR = os.path.join(_ROOT, "aero_mesh_core", "swarm_blueprints")
_DIST_DIR = os.path.join(_ROOT, "aero_mesh_core", "dist")
_RECIPE_OUT_DIR = os.path.join(_ROOT, "build_sandbox", "recipes")

# Opcodes that take no inline operand (used by the .aeroc deserializer).
_NO_ARG_OPS = {
    "POP", "RETURN", "HALT", "ADD", "SUB", "MUL", "DIV", "MOD", "EQ", "NEQ",
    "LT", "GT", "LTE", "GTE", "AND", "OR", "NOT", "NEG",
}


# ── Environment provisioning ───────────────────────────────────────────────

@contextlib.contextmanager
def _pushd(path):
    """Temporarily run with ``path`` as the working directory."""
    prev = os.getcwd()
    os.makedirs(path, exist_ok=True)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


@contextlib.contextmanager
def _quiet():
    """Silence stdout/stderr (mesh runs print build banners we don't need)."""
    with open(os.devnull, "w") as devnull:
        with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
            yield


def provision_environment():
    """Create the directory matrix and the local telemetry inputs the meshes
    read. This is explicit, up-front setup — it replaces the old reactive
    "self-healing factory" that fabricated mock files in response to arbitrary
    compiler errors (which silently masked real faults)."""
    for d in (_BP_DIR, _RECIPE_OUT_DIR, _DIST_DIR, os.path.join(_RUNTIME, "testbed", "scans")):
        os.makedirs(d, exist_ok=True)

    scans = os.path.join(_RUNTIME, "testbed", "scans")
    # Inputs consumed by the ingress mesh (raw_telemetry_*) and the seed
    # topology binary (heavy_node_*). Deterministic content -> reproducible.
    for i in range(5):
        with open(os.path.join(scans, f"raw_telemetry_{i}"), "w", encoding="utf-8") as f:
            f.write(f"PACKET_ID={1000 + i}\nPAYLOAD_HEX=0x{(0xA11CE + i):06x}\nMETRIC=STABLE\n")
    for i in range(3):
        with open(os.path.join(scans, f"heavy_node_{i}.txt"), "w", encoding="utf-8") as f:
            f.write(f"NODE_ID=heavy_{i}\nWEIGHT={100 + i}\nSTATE=READY\n")


def ensure_blueprints(reset=False):
    """Guarantee every mesh blueprint is present and compiles. A blueprint is
    restored from its canonical default if it is missing, unreadable, or has
    decayed into an uncompilable state (so a bad prior run can't wedge us)."""
    for name in MESHES:
        path = os.path.join(_BP_DIR, name)
        restore = reset or not os.path.exists(path)
        if not restore:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    ok, _ = compile_gate(f.read(), name[:-4])
                restore = not ok
            except OSError:
                restore = True
        if restore:
            with open(path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_BLUEPRINTS[name])


# ── Step 1: ingest the swarm bytecode ──────────────────────────────────────

def load_aeroc(path):
    """Deserialize a JSON ``.aeroc`` artifact back into a ``CompiledProgram``.

    The SDK ships ``_serialize_program`` but no loader; this reconstructs the
    ``(OpCode, *args)`` instruction tuples so precompiled binaries can run
    natively on the AeroVM."""
    with open(path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    if blob.get("format") != "aeroc":
        raise ValueError(f"{os.path.basename(path)}: not an aeroc artifact")

    def deser(instrs):
        out = []
        for item in instrs:
            if not item:
                raise ValueError("empty instruction")
            op = OpCode[item[0]]  # KeyError -> unknown opcode -> invalid binary
            out.append(tuple([op, *item[1:]]))
        return out

    functions = [
        CompiledFunction(fn["name"], list(fn["params"]), deser(fn["code"]))
        for fn in blob.get("functions", [])
    ]
    return CompiledProgram(
        main_code=deser(blob["main_code"]),
        functions=functions,
        constants=list(blob.get("constants", [])),
    )


def ingest_swarm_bytecode():
    """Load, structurally validate, and run the four compiled binaries as the
    swarm's operational foundation. Binaries that reference natives this VM
    does not provide are reported as validated-but-not-runnable rather than
    crashing the sweep."""
    print("🧩 [Foundation] Ingesting compiled swarm bytecode...", flush=True)
    report = {}
    for binary, role in SWARM_BINARIES.items():
        path = os.path.join(_RECIPE_OUT_DIR, binary)
        entry = {"role": role, "status": "missing", "main_ops": 0}
        if os.path.exists(path):
            try:
                program = load_aeroc(path)
                entry["main_ops"] = len(program.main_code)
                try:
                    with _pushd(_RUNTIME), _quiet():
                        AeroVM(program).run()
                    entry["status"] = "executed"
                except Exception as run_err:  # noqa: BLE001 - report, don't crash
                    entry["status"] = f"validated (not runnable: {type(run_err).__name__})"
            except Exception as load_err:  # noqa: BLE001
                entry["status"] = f"invalid ({type(load_err).__name__})"
        icon = "✅" if entry["status"] == "executed" else "🔎"
        print(f"   {icon} {binary:<24} [{role}] — {entry['status']} "
              f"({entry['main_ops']} ops)", flush=True)
        report[binary] = entry
    return report


# ── Recipe <-> INI round-trip ──────────────────────────────────────────────

def recipe_to_ini(recipe):
    """Serialize a parsed recipe dict back into a compiler-ready INI string."""
    lines = ["[project]"]
    for key, value in recipe["project"].items():
        lines.append(f"{key} = {value}")
    lines.append("")
    for task in recipe["tasks"]:
        lines.append(f"[task:{task['name']}]")
        lines.append(f"op = {task['op']}")
        for key, value in task["fields"].items():
            lines.append(f"{key} = {value}")
        if task["needs"]:
            lines.append("needs = " + ", ".join(task["needs"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── Validity: topology + data dependencies ─────────────────────────────────

def _arg_paths(task):
    """Extract the quoted path/string arguments of a ``call`` task, in order."""
    args = task["fields"].get("args", "")
    quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', args)
    if quoted:
        return quoted
    return [a.strip().strip('"').strip("'") for a in args.split(",") if a.strip()]


def _produces(task):
    """Filesystem paths a task makes available to later tasks."""
    if task["op"] != "call":
        return set()
    fn = task["fields"].get("fn", "").strip()
    paths = _arg_paths(task)
    if fn in ("write_file", "save_binary", "create_dir") and paths:
        return {paths[0]}
    return set()


def _consumes(task):
    """Filesystem paths a task reads from earlier tasks."""
    if task["op"] != "call":
        return set()
    if task["fields"].get("fn", "").strip() == "read_file":
        paths = _arg_paths(task)
        if paths:
            return {paths[0]}
    return set()


def validate_recipe(recipe):
    """Reject any mutation that breaks the build graph. Enforces two invariants:

    1. The ``needs`` graph is acyclic and references only real tasks
       (delegated to the compiler's own ``_resolve_order``).
    2. Data safety — for every file produced *and* consumed inside the recipe,
       all producers are ordered strictly before all consumers, so a mutation
       can never let a reader run ahead of its writer.
    """
    try:
        order = _resolve_order(recipe["tasks"])
    except RecipeError:
        return False

    position = {task["name"]: i for i, task in enumerate(order)}
    producers, consumers = {}, {}
    for task in recipe["tasks"]:
        i = position[task["name"]]
        for path in _produces(task):
            producers.setdefault(path, []).append(i)
        for path in _consumes(task):
            consumers.setdefault(path, []).append(i)

    for path, cons in consumers.items():
        prod = producers.get(path)
        if prod and max(prod) >= min(cons):
            return False
    return True


def _sig(recipe):
    """A hashable signature of a recipe's task topology — used to dedupe
    candidate mutations and remember which ones have already been tried."""
    return tuple((t["name"], t["op"], tuple(t["needs"])) for t in recipe["tasks"])


def _with_needs(recipe, task_name, new_needs):
    """Return a deep copy of ``recipe`` with one task's ``needs`` replaced."""
    trial = copy.deepcopy(recipe)
    for t in trial["tasks"]:
        if t["name"] == task_name:
            t["needs"] = new_needs
    return trial


# ── Step 2: the symbolic mutation heuristics ───────────────────────────────
#
# Each heuristic is a deterministic *enumerator*: it yields every valid,
# topology-changing candidate it can produce from a recipe. The driver dedupes
# and memoizes them, which guarantees the search space is finite and the loop
# actually converges instead of re-proposing the same rejected edit forever.

def iter_task_split(recipe):
    """Task splitting: re-parent a task that sits behind a single predecessor
    onto that predecessor's parent, so the two become parallel pathways
    instead of a serial chain."""
    by_name = {t["name"]: t for t in recipe["tasks"]}
    for task in recipe["tasks"]:
        if len(task["needs"]) != 1:
            continue
        parent = by_name.get(task["needs"][0])
        if not parent or not parent["needs"]:
            continue
        for gp in parent["needs"]:
            trial = _with_needs(recipe, task["name"],
                                [gp if d == parent["name"] else d for d in task["needs"]])
            if validate_recipe(trial):
                yield trial, (f"task-split: '{task['name']}' re-parented off "
                              f"'{parent['name']}' onto '{gp}' (parallel pathway)")


def iter_dependency_flip(recipe):
    """Dependency flipping: drop a ``needs`` edge or re-point it to a different
    earlier task, keeping only graphs that stay valid."""
    names = [t["name"] for t in recipe["tasks"]]
    index = {n: i for i, n in enumerate(names)}
    for task in recipe["tasks"]:
        if not task["needs"]:
            continue
        earlier = names[:index[task["name"]]]
        for dep in task["needs"]:
            # drop
            trial = _with_needs(recipe, task["name"],
                                [d for d in task["needs"] if d != dep])
            if validate_recipe(trial):
                yield trial, f"dependency-flip: task '{task['name']}' edge '{dep}' dropped"
            # re-point
            for target in earlier:
                if target == dep or target in task["needs"]:
                    continue
                trial = _with_needs(recipe, task["name"],
                                    [target if d == dep else d for d in task["needs"]])
                if validate_recipe(trial):
                    yield trial, (f"dependency-flip: task '{task['name']}' edge "
                                  f"'{dep}' re-pointed -> '{target}'")


def iter_dead_code_prune(recipe):
    """Dead-code pruning: remove a value-producing task (``set``/``compute``)
    whose output name is referenced nowhere and which nothing depends on. Tasks
    with observable side effects (print / call / loops) are never pruned."""
    needed = set()
    for task in recipe["tasks"]:
        needed.update(task["needs"])

    def name_used_elsewhere(varname, owner):
        pattern = re.compile(r"\b" + re.escape(varname) + r"\b")
        for task in recipe["tasks"]:
            if task["name"] == owner:
                continue
            for key, value in task["fields"].items():
                if key != "name" and pattern.search(value):
                    return True
        return False

    for task in recipe["tasks"]:
        if task["op"] not in ("set", "let", "compute") or task["name"] in needed:
            continue
        varname = task["fields"].get("name", "").strip()
        if varname and name_used_elsewhere(varname, task["name"]):
            continue
        trial = copy.deepcopy(recipe)
        trial["tasks"] = [t for t in trial["tasks"] if t["name"] != task["name"]]
        if validate_recipe(trial):
            yield trial, f"dead-code-prune: removed unused task '{task['name']}' (op={task['op']})"


def _is_spike(mesh_fitness):
    """A mesh "spikes" when its last wall time regresses well past its best."""
    best = mesh_fitness.get("best_wall_ms")
    last = mesh_fitness.get("last_execution_wall_ms")
    return bool(best and last and last > best * 1.5)


def propose_mutations(recipe, mesh_fitness, rng):
    """Enumerate all distinct, valid candidate mutations for a recipe. On a
    wall-clock spike the parallelizing splitter is offered first, as specified;
    otherwise the cheaper graph edits lead. Candidates are deduped by topology
    signature and shuffled within each heuristic group for reproducible variety."""
    groups = ([iter_task_split, iter_dependency_flip, iter_dead_code_prune]
              if _is_spike(mesh_fitness)
              else [iter_dependency_flip, iter_dead_code_prune, iter_task_split])

    base_sig = _sig(recipe)
    seen, ordered = set(), []
    for heuristic in groups:
        bucket = []
        for candidate, description in heuristic(recipe):
            sig = _sig(candidate)
            if sig == base_sig or sig in seen:
                continue
            seen.add(sig)
            bucket.append((candidate, description, sig))
        rng.shuffle(bucket)
        ordered.extend(bucket)
    return ordered


# ── Step 3: the deterministic compile + fitness gate ───────────────────────

def compile_gate(ini_text, project_name):
    """The syntax-fault gate. Returns ``(ok, error)`` — ``ok`` is False if the
    blueprint fails to lower/compile, in which case the mutation is discarded."""
    return _probe(ini_text, project_name, run=False, repeats=1)[:2]


def evaluate(ini_text, project_name, repeats):
    """Compile and execute a blueprint, returning the best wall time in ms over
    ``repeats`` runs. Raises if compilation or execution fails."""
    ok, error, wall = _probe(ini_text, project_name, run=True, repeats=repeats)
    if not ok:
        raise RuntimeError(error)
    return wall


def _probe(ini_text, project_name, run, repeats):
    """Write the candidate to an isolated temp recipe, run it through the real
    ``meta_compiler`` pipeline (optionally executing on the VM), and time it.
    All VM I/O is sandboxed under ``_RUNTIME`` so the repo tree stays clean."""
    os.makedirs(_RUNTIME, exist_ok=True)
    tmp_txt = os.path.join(_RUNTIME, f".cand_{project_name}.txt")
    tmp_aeroc = os.path.join(_RUNTIME, f".cand_{project_name}.aeroc")
    with open(tmp_txt, "w", encoding="utf-8") as f:
        f.write(ini_text)

    best = None
    try:
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            with _pushd(_RUNTIME), _quiet():
                compile_recipe(tmp_txt, out_path=tmp_aeroc, run=run)
            elapsed = (time.perf_counter() - t0) * 1000.0
            best = elapsed if best is None else min(best, elapsed)
    except Exception as exc:  # noqa: BLE001 - any failure means "discard"
        return False, f"{type(exc).__name__}: {exc}", None
    finally:
        for p in (tmp_txt, tmp_aeroc):
            with contextlib.suppress(OSError):
                os.remove(p)
    return True, None, round(best, 4)


def commit_champion_to_disk(mesh, ini_text):
    """Persist an accepted champion: overwrite the blueprint and regenerate its
    compiled ``.aeroc`` binary in the tracked recipes directory."""
    blueprint_path = os.path.join(_BP_DIR, mesh)
    with open(blueprint_path, "w", encoding="utf-8") as f:
        f.write(ini_text)
    aeroc_path = os.path.join(_RECIPE_OUT_DIR, mesh.replace(".txt", ".aeroc"))
    with _quiet():
        compile_recipe(blueprint_path, out_path=aeroc_path, run=False)
    return blueprint_path, aeroc_path


# ── Metrics + report manifests ─────────────────────────────────────────────

def write_manifest(fitness):
    os.makedirs(_DIST_DIR, exist_ok=True)
    manifest = {
        mesh: {
            "compiled_successfully": data["compiled_successfully"],
            "total_executions": data["total_executions"],
            "last_execution_wall_ms": data["last_execution_wall_ms"],
            "best_wall_ms": data["best_wall_ms"],
            "generation": data["generation"],
            "champion": data["champion"],
        }
        for mesh, data in fitness.items()
    }
    with open(os.path.join(_DIST_DIR, "swarm_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def write_report(fitness, foundation, iterations, accepted):
    report = {
        "engine": "local-symbolic-topological-mutation",
        "iterations": iterations,
        "champions_accepted": accepted,
        "foundation": foundation,
        "meshes": fitness,
    }
    with open(os.path.join(_DIST_DIR, "evolve_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


# ── Optional, opt-in git checkpointing ─────────────────────────────────────

def _git(*args):
    return subprocess.run(["git", "-C", _ROOT, *args], capture_output=True, text=True)


def current_branch():
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return branch if branch and branch != "HEAD" else None


def commit_champion(message, paths):
    """Stage the given paths and commit them with a local committer identity
    (no global git config is mutated)."""
    _git("add", "--", *paths)
    res = _git(
        "-c", "user.name=Aero Evolution Engine",
        "-c", "user.email=evolution@aero-auto-sdk.local",
        "commit", "-m", message,
    )
    return res.returncode == 0


def push_branch(branch):
    """Push the current HEAD to ``branch`` with exponential-backoff retries.
    Never targets ``main`` implicitly — the caller chooses the branch."""
    if not branch:
        print("   ⚠️ push skipped: no target branch (detached HEAD).", flush=True)
        return False
    for delay in (0, 2, 4, 8, 16):
        if delay:
            time.sleep(delay)
        res = _git("push", "-u", "origin", f"HEAD:{branch}")
        if res.returncode == 0:
            print(f"   ⬆️  pushed champions -> origin/{branch}", flush=True)
            return True
    print(f"   ❌ push to origin/{branch} failed after retries: "
          f"{res.stderr.strip()}", flush=True)
    return False


# ── The evolution loop ─────────────────────────────────────────────────────

def run_evolution(args):
    import random
    rng = random.Random(args.seed)

    # Baseline pass: time each blueprint as the champion to beat.
    fitness = {}
    for mesh in MESHES:
        with open(os.path.join(_BP_DIR, mesh), "r", encoding="utf-8") as f:
            text = f.read()
        wall = evaluate(text, mesh[:-4], repeats=args.repeats)
        fitness[mesh] = {
            "compiled_successfully": True,
            "total_executions": 1,
            "last_execution_wall_ms": wall,
            "best_wall_ms": wall,
            "generation": 0,
            "champion": "baseline",
        }
        print(f"   • baseline {mesh:<22} {wall:.4f} ms", flush=True)
    write_manifest(fitness)

    push_branch_name = args.push_branch or current_branch()
    if args.push:
        print(f"📦 Champions will be committed and pushed to "
              f"origin/{push_branch_name}", flush=True)

    start = time.time()
    last_push = start
    last_heartbeat = start
    iterations = 0
    accepted = 0
    stale_streak = 0
    # Candidate topologies already evaluated for each mesh. Cleared whenever a
    # mesh produces a champion (a new blueprint opens up a fresh search space).
    tried = {mesh: set() for mesh in MESHES}

    print(f"⚙️  Evolving for up to {args.duration}s "
          f"(seed={args.seed}, repeats={args.repeats})...", flush=True)

    while (time.time() - start) < args.duration:
        iterations += 1
        proposals_this_round = 0
        pending_commit = []

        for mesh in MESHES:
            path = os.path.join(_BP_DIR, mesh)
            with open(path, "r", encoding="utf-8") as f:
                current_text = f.read()
            recipe = load_recipe(path)

            # Pick the first candidate we have not already evaluated.
            candidate = next(
                (c for c in propose_mutations(recipe, fitness[mesh], rng)
                 if c[2] not in tried[mesh]),
                None,
            )
            if candidate is None:
                continue  # this mesh has exhausted its safe mutations
            cand_recipe, description, sig = candidate
            proposals_this_round += 1
            tried[mesh].add(sig)
            candidate_text = recipe_to_ini(cand_recipe)

            # Gate 1: deterministic compile. Syntax fault -> discard + revert.
            ok, error = compile_gate(candidate_text, mesh[:-4])
            if not ok:
                print(f"   ✗ {mesh}: discarded ({description}) — compile fault: {error}",
                      flush=True)
                continue

            # Gate 2: execute on the VM and time it.
            try:
                wall = evaluate(candidate_text, mesh[:-4], repeats=args.repeats)
            except Exception as exc:  # noqa: BLE001
                print(f"   ✗ {mesh}: discarded ({description}) — runtime fault: {exc}",
                      flush=True)
                continue

            # Re-measure the reigning champion back-to-back so the comparison is
            # made under the same conditions; a candidate must beat both the
            # all-time best and this fresh reading to win (noise-resistant).
            try:
                baseline_fresh = evaluate(current_text, mesh[:-4], repeats=args.repeats)
            except Exception:  # noqa: BLE001
                baseline_fresh = fitness[mesh]["best_wall_ms"]
            baseline = min(fitness[mesh]["best_wall_ms"], baseline_fresh)

            fitness[mesh]["total_executions"] += 1
            fitness[mesh]["last_execution_wall_ms"] = wall

            if wall + args.epsilon < baseline:
                # New champion — commit to disk, never just to memory.
                _, aeroc_path = commit_champion_to_disk(mesh, candidate_text)
                fitness[mesh]["best_wall_ms"] = wall
                fitness[mesh]["generation"] += 1
                fitness[mesh]["champion"] = description
                accepted += 1
                tried[mesh].clear()  # fresh blueprint -> re-open the search
                print(f"   🏆 {mesh}: champion gen {fitness[mesh]['generation']} "
                      f"{baseline:.4f} -> {wall:.4f} ms — {description}", flush=True)
                write_manifest(fitness)
                pending_commit.extend([path, aeroc_path])
            else:
                # Not faster — discard and revert (disk was never touched).
                print(f"   ↩️  {mesh}: reverted ({description}) — "
                      f"{wall:.4f} ms >= {baseline:.4f} ms baseline", flush=True)

        # Local commit of any champions accepted this round.
        if args.push and pending_commit:
            commit_champion(
                "chore(evolve): promote faster mesh champion(s) [local mutation engine]",
                sorted(set(pending_commit + [os.path.join(_DIST_DIR, "swarm_metrics.json")])),
            )

        # Periodic push so commits batch instead of one push per improvement.
        if args.push and (time.time() - last_push) >= args.push_cooldown:
            push_branch(push_branch_name)
            last_push = time.time()

        # Heartbeat.
        if (time.time() - last_heartbeat) >= args.heartbeat:
            elapsed = int(time.time() - start)
            print(f"⏳ [Heartbeat] iter={iterations} accepted={accepted} "
                  f"elapsed={elapsed}s remaining={max(0, args.duration - elapsed)}s",
                  flush=True)
            last_heartbeat = time.time()

        # Convergence: the search space of these meshes is finite. If no mesh
        # can produce a fresh valid mutation for several rounds, stop spinning.
        stale_streak = stale_streak + 1 if proposals_this_round == 0 else 0
        if stale_streak >= 3:
            print("🧭 Search space converged — no further safe mutations available.",
                  flush=True)
            break

    return fitness, iterations, accepted, push_branch_name


def main():
    parser = argparse.ArgumentParser(
        description="Local symbolic topological mutation engine for Aero-Mesh blueprints."
    )
    parser.add_argument("--duration", type=int, default=60,
                        help="maximum evolution wall-clock budget in seconds")
    parser.add_argument("--repeats", type=int, default=5,
                        help="timing samples per evaluation (best is kept — reduces noise)")
    parser.add_argument("--epsilon", type=float, default=0.05,
                        help="minimum ms improvement required to crown a champion")
    parser.add_argument("--seed", type=int, default=1337,
                        help="RNG seed for reproducible, deterministic mutation order")
    parser.add_argument("--reset", action="store_true",
                        help="restore blueprints to their canonical defaults before evolving")
    parser.add_argument("--push", action="store_true",
                        help="opt in to committing and pushing accepted champions to git")
    parser.add_argument("--push-branch", default=None,
                        help="branch to push champions to (default: current branch; never main implicitly)")
    parser.add_argument("--push-cooldown", type=int, default=180,
                        help="minimum seconds between pushes when --push is set")
    parser.add_argument("--heartbeat", type=int, default=10,
                        help="seconds between heartbeat log lines")
    args = parser.parse_args()

    # Resolve all blueprint/binary paths from the repo root regardless of where
    # the script was launched, so relative recipe paths line up.
    os.chdir(_ROOT)

    print("🚀 Aero-Mesh Local Evolution Engine "
          "(Symbolic Topological Mutation — no cloud, no network)", flush=True)
    provision_environment()
    ensure_blueprints(reset=args.reset)
    foundation = ingest_swarm_bytecode()

    fitness, iterations, accepted, branch = run_evolution(args)

    write_manifest(fitness)
    write_report(fitness, foundation, iterations, accepted)
    print(f"🏁 Done. iterations={iterations} champions={accepted}. "
          f"Metrics -> aero_mesh_core/dist/swarm_metrics.json", flush=True)

    if args.push:
        commit_champion(
            "chore(evolve): finalize evolution run metrics [local mutation engine]",
            [os.path.join(_DIST_DIR, "swarm_metrics.json"),
             os.path.join(_DIST_DIR, "evolve_report.json")],
        )
        push_branch(branch)


if __name__ == "__main__":
    main()
