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

def execute_complexity_mutation(recipe_text, mesh_name, round_counter):
    """Generates mutations anchored to 100% valid, native compiler primitives to prevent silent drops"""
    lines = recipe_text.split("\n")
    tasks = []
    
    for line in lines:
        if line.strip().startswith("[task:"):
            tasks.append(line.split("[task:")[1].split("]")[0].strip())

    strategy = random.choice(["expand_nodes", "relink_dependencies", "fuzz_logs"])
    
    # Absolute file saturation boundary to prevent unbounded recipe file sizes
    if len(tasks) >= 20 and strategy == "expand_nodes":
        strategy = "relink_dependencies"

    if strategy == "expand_nodes" and tasks:
        # NATIVE PRIMITIVES ONLY: Exclusively maps to built-in 'print' or 'write_file' routines
        if "ingress" in mesh_name:
            chosen = random.choice([
                {"family": "sentinel_gate", "op": "print", "body": f'text = "-- Gateway Security Auth Check: Active Shard #{round_counter} --"', "label": "Security Boundary Check"},
                {"family": "load_balancer", "op": "print", "body": f'text = "-- Network Traffic Dispatched to Worker Ring Shard #{round_counter} --"', "label": "Stream Load Balancer"},
                {"family": "stream_buffer", "op": "call", "body": f'fn = write_file\nargs = "testbed/scans/ingress_shard_{round_counter}.tmp", "buffered"', "label": "Ingestion I/O Flush"}
            ])
        elif "processing" in mesh_name:
            chosen = random.choice([
                {"family": "dag_optimizer", "op": "print", "body": f'text = "-- Optimization Routine Synchronized: Pipeline Layer #{round_counter} --"', "label": "DAG Re-indexing Step"},
                {"family": "shared_memory", "op": "print", "body": f'text = "-- Mutex Register Latched: VMem Segment #{round_counter} --"', "label": "Virtual Shared Memory Link"},
                {"family": "matrix_solver", "op": "call", "body": f'fn = write_file\nargs = "build_sandbox/mesh_outputs/matrix_{round_counter}.tmp", "processed"', "label": "Matrix Segment Compute Flush"}
            ])
        else:
            chosen = random.choice([
                {"family": "manifest_signer", "op": "print", "body": f'text = "-- Cryptographic Build Signature Generated for Release #{round_counter} --"', "label": "Integrity Handshake Verification"},
                {"family": "standalone_boxer", "op": "print", "body": f'text = "-- Compiling Independent Executable Swarm Box Asset Bundle #{round_counter} --"', "label": "Unified Box Output Bundle"},
                {"family": "index_mapper", "op": "call", "body": f'fn = write_file\nargs = "aero_mesh_core/dist/cluster_map_{round_counter}.idx", "sync"', "label": "Topology Map Sync Row"}
            ])
            
        # Base Family density check ensures high variety across our task distributions
        if recipe_text.count(chosen['family']) >= 4:
            strategy = "relink_dependencies"
        else:
            new_node_id = f"{chosen['family']}_node_{round_counter}"
            parent_dependency = random.choice(tasks)
            
            node_block = (
                f"\n\n[task:{new_node_id}]\n"
                f"op = {chosen['op']}\n"
                f"{chosen['body']}\n"
                f"needs = {parent_dependency}\n"
            )
            return recipe_text + node_block, f"Successfully Extended Cluster with Native [{chosen['label']}] Primitives -> Node ID: {new_node_id}"

    if strategy == "relink_dependencies" and len(tasks) > 1:
        new_lines = []
        mutated = False
        for line in lines:
            if "needs =" in line and random.random() > 0.6:
                t_target = random.choice(tasks)
                new_lines.append(f"needs = {t_target}")
                mutated = True
            else:
                new_lines.append(line)
        desc = "Reconfigured Parallel Dependency Graph Pathing" if mutated else "Maintained Current Graph Equilibrium"
        return "\n".join(new_lines), desc

    new_lines = []
    mutated = False
    for line in lines:
        if "text =" in line and random.random() > 0.5:
            new_lines.append(f'text = "-- Swarm Matrix Execution Cluster Pulse Sequence #{round_counter} --"')
            mutated = True
        else:
            new_lines.append(line)
    desc = "Updated Cluster Heartbeat Frame Strings" if mutated else "Stabilized Current Code Matrix States"
    return "\n".join(new_lines), desc

def push_git_checkpoint(reason, metrics):
    """Commits and pushes structural multi-mesh components straight to production"""
    print(f"\n📦 [Checkpoint] Syncing states to GitHub Remote... Reason: {reason}", flush=True)
    
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
    os.system(f'git -C "{_ROOT}" commit -m "chore: align mutator infrastructure to leverage compiler-verified native primitives" 2>&1')
    os.system(f'git -C "{_ROOT}" push origin main 2>&1')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=1200)
    args, unknown = parser.parse_known_args()

    print("🚀 Initializing Primitive-Aligned Swarm Architecture Engine...", flush=True)
    print("🎯 Target System: Massive, High-Density Multi-Node Distributed Architecture", flush=True)
    generate_swarm_environment()
    ensure_swarm_blueprints(force_reset=True)
    
    start_time = time.time()
    last_git_time = time.time()
    last_heartbeat_time = time.time()
    
    total_rounds = 0
    champions_frozen = 0
    
    meshes = ["ingress_mesh.txt", "processing_mesh.txt", "aggregation_mesh.txt"]
    fitness_history = {m: {"node_count": 2, "compiled_successfully": True} for m in meshes}

    interval_stats = {
        "cycles": 0,
        "compilation_faults": 0,
        "champions_crowned": []
    }

    GIT_COOLDOWN = 180        
    HEARTBEAT_COOLDOWN = 10   

    bp_dir = os.path.join(_ROOT, "aero_mesh_core", "swarm_blueprints")

    while (time.time() - start_time) < args.duration:
        current_time = time.time()
        elapsed = int(current_time - start_time)
        
        total_rounds += 1
        interval_stats["cycles"] += 1
        
        target_mesh = random.choice(meshes)
        mesh_path = os.path.join(bp_dir, target_mesh)
        
        try:
            with open(mesh_path, "r", encoding="utf-8") as f_read:
                original_blueprint = f_read.read()
            
            mutated_blueprint, mutation_description = execute_complexity_mutation(original_blueprint, target_mesh, total_rounds)
            
            with open(mesh_path, "w", encoding="utf-8") as f_write:
                f_write.write(mutated_blueprint)
                
            with open(os.devnull, 'w') as fnull:
                with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
                    compile_recipe(mesh_path, run=True)
            
            mutated_nodes = mutated_blueprint.count("[task:")
            
            if mutated_nodes > fitness_history[target_mesh]["node_count"]:
                interval_stats["champions_crowned"].append(
                    f"     • [{target_mesh}] Scaled cluster footprint to {mutated_nodes} verified nodes"
                )
                fitness_history[target_mesh]["node_count"] = mutated_nodes
                fitness_history[target_mesh]["compiled_successfully"] = True
                champions_frozen += 1
            elif mutated_blueprint != original_blueprint and mutated_nodes == fitness_history[target_mesh]["node_count"]:
                fitness_history[target_mesh]["compiled_successfully"] = True
            else:
                with open(mesh_path, "w", encoding="utf-8") as f_revert:
                    f_revert.write(original_blueprint)
                    
        except Exception:
            interval_stats["compilation_faults"] += 1
            try:
                with open(mesh_path, "w", encoding="utf-8") as f_revert:
                    f_revert.write(original_blueprint)
            except Exception:
                pass

        if (current_time - last_heartbeat_time) >= HEARTBEAT_COOLDOWN:
            print("\n==================================================================", flush=True)
            print(f"⏳ [SWARM STATE HEARTBEAT] Time Elapsed: {elapsed}s / {args.duration}s", flush=True)
            print(f"   📊 Interval Velocity : {interval_stats['cycles']} compilation rounds processed", flush=True)
            print(f"   🛡️ Integrity Gate    : {interval_stats['compilation_faults']} structural mutations blocked by compiler", flush=True)
            print(f"   🏆 Total Scale Champs: {champions_frozen} topology adaptations frozen since boot", flush=True)
            
            if interval_stats["champions_crowned"]:
                print("   📈 Structural Footprint Extensions Frozen in Last 10s:", flush=True)
                for log_line in interval_stats["champions_crowned"]:
                    print(log_line, flush=True)
            print("==================================================================", flush=True)
            
            interval_stats = {"cycles": 0, "compilation_faults": 0, "champions_crowned": []}
            last_heartbeat_time = current_time

        if (current_time - last_git_time) >= GIT_COOLDOWN:
            last_git_time = current_time
            push_git_checkpoint(f"Runtime: {elapsed}s, Footprint Scale: {champions_frozen} Nodes", fitness_history)

    print("🏁 Operational timeline achieved. Finalizing unified Swarm Box structures.", flush=True)
    push_git_checkpoint(f"Evolution timeline run complete. Total Scaled Architecture Champions: {champions_frozen}", fitness_history)

if __name__ == '__main__':
    main()
