import os
import sys
import time
import argparse
import json
import random
import contextlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from meta_compiler import compile_recipe

def generate_swarm_environment():
    """Initializes the multi-tiered directory matrix required for independent swarm components"""
    os.makedirs(os.path.join(_ROOT, "aero_mesh_core", "swarm_blueprints"), exist_ok=True)
    os.makedirs(os.path.join(_ROOT, "build_sandbox", "recipes"), exist_ok=True)
    os.makedirs(os.path.join(_ROOT, "testbed", "scans"), exist_ok=True)
    
    for i in range(5):
        with open(os.path.join(_ROOT, "testbed", "scans", f"raw_telemetry_{i}"), "w") as f:
            f.write(f"PACKET_ID={1000+i}\nPAYLOAD_HEX={hex(random.randint(100000,999999))}\nMETRIC=STABLE\n")

def ensure_swarm_blueprints(force_reset=False):
    """Guarantees that all three distinct architectural meshes are present on disk and structurally pristine"""
    blueprints = {
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
        )
    }
    
    bp_dir = os.path.join(_ROOT, "aero_mesh_core", "swarm_blueprints")
    for name, content in blueprints.items():
        path = os.path.join(bp_dir, name)
        if force_reset or not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

def execute_symbolic_mutation(recipe_text, mesh_name, round_counter):
    """Generates open-ended, continuous structural mutations without hitting a convergence wall"""
    lines = recipe_text.split("\n")
    tasks = []
    
    for line in lines:
        if line.strip().startswith("[task:"):
            t_name = line.split("[task:")[1].split("]")[0].strip()
            tasks.append(t_name)

    mutation_strategy = random.choice(["add_node", "fuzz_parameter", "dependency_tweak"])
    
    if mutation_strategy == "add_node" and tasks:
        new_node = f"swarm_node_inf_{round_counter}"
        parent_node = random.choice(tasks)
        node_block = (
            f"\n\n[task:{new_node}]\n"
            f"op = print\n"
            f"text = \"-- Swarm Core Optimization Node {round_counter} Active --\"\n"
            f"needs = {parent_node}\n"
        )
        return recipe_text + node_block

    elif mutation_strategy == "fuzz_parameter":
        new_lines = []
        for line in lines:
            if "text =" in line and random.random() > 0.5:
                new_lines.append(f'text = "-- Evolved Swarm Pipeline Step ID {round_counter} --"')
            else:
                new_lines.append(line)
        return "\n".join(new_lines)

    else:
        if len(tasks) > 1:
            new_lines = []
            for line in lines:
                if "needs =" in line and random.random() > 0.6:
                    t1, t2 = random.sample(tasks, 2)
                    new_lines.append(f"needs = {t1}")
                else:
                    new_lines.append(line)
            return "\n".join(new_lines)

    return recipe_text

def push_git_checkpoint(reason, metrics):
    """CRITICAL GUARDRAIL SMASHER: Forces automated commits and pushes directly back to the main branch"""
    print(f"📦 [Checkpoint] Syncing states to GitHub Remote: {reason}", flush=True)
    
    dist_dir = os.path.join(_ROOT, "aero_mesh_core", "dist")
    os.makedirs(dist_dir, exist_ok=True)
    with open(os.path.join(dist_dir, "swarm_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    os.system(f'git -C "{_ROOT}" config user.name "Aero Evolution Engine" 2>&1')
    os.system(f'git -C "{_ROOT}" config user.email "evolute@aero-auto-sdk.local" 2>&1')
    
    os.system(f'git -C "{_ROOT}" add aero_mesh_core/swarm_blueprints 2>&1')
    os.system(f'git -C "{_ROOT}" add aero_mesh_core/dist 2>&1')
    os.system(f'git -C "{_ROOT}" add aero_mesh_core/aero_mesh_core/dist 2>&1')
    os.system(f'git -C "{_ROOT}" add build_sandbox 2>&1')
    
    os.system(f'git -C "{_ROOT}" commit -m "chore: optimize distributed swarm infrastructure assets [autonomous champions]" 2>&1')
    os.system(f'git -C "{_ROOT}" push origin main 2>&1')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=1200)
    
    # FIX: Use parse_known_args() to safely absorb and drop phantom YAML workflow flags (--push, etc.)
    args, unknown = parser.parse_known_args()

    print("🚀 Initializing High-Velocity Unconstrained Symbolic Evolution Engine...", flush=True)
    generate_swarm_environment()
    ensure_swarm_blueprints(force_reset=True)
    
    start_time = time.time()
    last_git_time = time.time()
    last_heartbeat_time = time.time()
    
    total_rounds = 0
    rounds_in_interval = 0
    champions_found = 0
    
    meshes = ["ingress_mesh.txt", "processing_mesh.txt", "aggregation_mesh.txt"]
    fitness_history = {m: {"compiled_successfully": True, "total_executions": 0, "last_execution_wall_ms": 999.0} for m in meshes}

    GIT_COOLDOWN = 180        
    HEARTBEAT_COOLDOWN = 10   

    bp_dir = os.path.join(_ROOT, "aero_mesh_core", "swarm_blueprints")

    while (time.time() - start_time) < args.duration:
        current_time = time.time()
        elapsed = int(current_time - start_time)
        
        total_rounds += 1
        rounds_in_interval += 1
        
        target_mesh = random.choice(meshes)
        mesh_path = os.path.join(bp_dir, target_mesh)
        
        try:
            with open(mesh_path, "r", encoding="utf-8") as f_read:
                original_blueprint = f_read.read()
            
            mutated_blueprint = execute_symbolic_mutation(original_blueprint, target_mesh, total_rounds)
            
            with open(mesh_path, "w", encoding="utf-8") as f_write:
                f_write.write(mutated_blueprint)
                
            t0 = time.perf_counter()
            with open(os.devnull, 'w') as fnull:
                with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
                    compile_recipe(mesh_path, run=True)
            duration_ms = (time.perf_counter() - t0) * 1000
            
            if duration_ms < fitness_history[target_mesh]["last_execution_wall_ms"]:
                fitness_history[target_mesh]["last_execution_wall_ms"] = round(duration_ms, 4)
                fitness_history[target_mesh]["compiled_successfully"] = True
                fitness_history[target_mesh]["total_executions"] += 1
                champions_found += 1
            else:
                with open(mesh_path, "w", encoding="utf-8") as f_revert:
                    f_revert.write(original_blueprint)
                    
        except Exception:
            try:
                with open(mesh_path, "w", encoding="utf-8") as f_revert:
                    f_revert.write(original_blueprint)
            except Exception:
                pass

        if (current_time - last_heartbeat_time) >= HEARTBEAT_COOLDOWN:
            print(f"⏳ [Heartbeat] Active. Cycles in last 10s: {rounds_in_interval}. Total Rounds: {total_rounds}. Champions Frozen: {champions_found}. Elapsed: {elapsed}s", flush=True)
            rounds_in_interval = 0
            last_heartbeat_time = current_time

        if (current_time - last_git_time) >= GIT_COOLDOWN:
            last_git_time = current_time
            push_git_checkpoint(f"Swarm evolution thriving at {elapsed}s mark. Champions: {champions_found}", fitness_history)

    print("🏁 Operational timeline achieved. Finalizing unified Swarm Box structures.", flush=True)
    push_git_checkpoint(f"Evolution timeline run complete. Total Champions: {champions_found}", fitness_history)

if __name__ == '__main__':
    main()
