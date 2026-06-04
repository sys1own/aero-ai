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
    """Generates deeply nested, highly advanced multi-node task frameworks for industrial architectures"""
    lines = recipe_text.split("\n")
    tasks = []
    
    for line in lines:
        if line.strip().startswith("[task:"):
            t_name = line.split("[task:")[1].split("]")[0].strip()
            tasks.append(t_name)

    # Infinite Architectural Primitives Factory Pools
    ingress_templates = [
        {"prefix": "sentinel_gate", "op": "call", "fn": "verify_crypto", "args": '"sha256_handshake"', "label": "Security Boundary"},
        {"prefix": "load_balancer", "op": "call", "fn": "distribute_load", "args": '"worker_mesh_pool"', "label": "Traffic Director"},
        {"prefix": "stream_buffer", "op": "call", "fn": "write_file", "args": '"testbed/scans/stream.io", "async"', "label": "I/O Buffer Allocation"},
        {"prefix": "telemetry_ping", "op": "print", "fn": "none", "args": '""', "label": "Pulse Heartbeat Link"}
    ]
    
    processing_templates = [
        {"prefix": "dag_optimizer", "op": "call", "fn": "unroll_loops", "args": '"execution_graph"', "label": "DAG Compilation Optimizer"},
        {"prefix": "shared_memory_ring", "op": "call", "fn": "mutex_lock", "args": '"aero_shared_vmem"', "label": "Shared Ring Memory Interlock"},
        {"prefix": "matrix_solver", "op": "call", "fn": "compute_weights", "args": '"testbed/scans/weights.dat"', "label": "Parallel Matrix Math Cluster"},
        {"prefix": "interim_checkpoint", "op": "call", "fn": "write_file", "args": '"aero_mesh_core/dist/state.bak", "snap"', "label": "State Recovery Snap"}
    ]
    
    aggregation_templates = [
        {"prefix": "manifest_signer", "op": "call", "fn": "sign_package", "args": '"rsa_secure_private"', "label": "Cryptographic Integrity Stamp"},
        {"prefix": "standalone_boxer", "op": "call", "fn": "create_archive", "args": '"build_sandbox/swarm_box.zip"', "label": "Unified Box Distribution Packer"},
        {"prefix": "garbage_collector", "op": "print", "fn": "none", "args": '""', "label": "Memory Sandbox Scrub"},
        {"prefix": "index_mapper", "op": "call", "fn": "write_file", "args": '"aero_mesh_core/dist/map.idx", "sync"', "label": "Topology Index Map Consolidation"}
    ]

    # Bias heavily toward functional node additions (75% probability) to ensure continuous scale growth
    strategy = random.choices(["expand_nodes", "relink_dependencies", "fuzz_logs"], weights=[75, 15, 10], k=1)[0]
    
    if strategy == "expand_nodes" and tasks:
        if "ingress" in mesh_name:
            pool = ingress_templates
        elif "processing" in mesh_name:
            pool = processing_templates
        else:
            pool = aggregation_templates
            
        chosen = random.choice(pool)
        new_node_id = f"{chosen['prefix']}_node_{round_counter}"
        parent_dependency = random.choice(tasks)
        
        node_block = (
            f"\n\n[task:{new_node_id}]\n"
            f"op = {chosen['op']}\n"
        )
        if chosen['fn'] != "none":
            node_block += f"fn = {chosen['fn']}\n"
            node_block += f"args = {chosen['args']}\n"
        else:
            node_block += f"text = \"-- Cluster Operation Status: Executing {chosen['label']} --\"\n"
            
        node_block += f"needs = {parent_dependency}\n"
        return recipe_text + node_block, f"Instantiated brand new [{chosen['label']}] node -> ID: {new_node_id}"

    elif strategy == "relink_dependencies" and len(tasks) > 1:
        # Re-route task graph edges to grow deeper parallel chains
        new_lines = []
        mutated = False
        for line in lines:
            if "needs =" in line and random.random() > 0.6:
                t_target = random.choice(tasks)
                new_lines.append(f"needs = {t_target}")
                mutated = True
            else:
                new_lines.append(line)
        desc = "Reconfigured topological graph routing paths" if mutated else "Skipped layer adjustment"
        return "\n".join(new_lines), desc

    else:
        new_lines = []
        mutated = False
        for line in lines:
            if "text =" in line and random.random() > 0.5:
                new_lines.append(f'text = "-- Swarm Scale Monitor Event Checkpoint #{round_counter} --"')
                mutated = True
            else:
                new_lines.append(line)
        desc = "Updated distributed console logging frames" if mutated else "Skipped structural touch"
        return "\n".join(new_lines), desc

def push_git_checkpoint(reason, metrics):
    """Commits and pushes the structural multi-mesh assets straight to your production repository"""
    print(f"📦 [Checkpoint] Pushing Evolved Swarm Core to GitHub: {reason}", flush=True)
    
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
    
    os.system(f'git -C "{_ROOT}" commit -m "chore: expand multi-node architecture footprint [autonomous growth]" 2>&1')
    os.system(f'git -C "{_ROOT}" push origin main 2>&1')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=1200)
    args, unknown = parser.parse_known_args()

    print("🚀 Initializing High-Velocity Complexity-Scaling Swarm Architecture Engine...", flush=True)
    print("🎯 Target System: Massive, High-Density Multi-Node Distributed Architecture", flush=True)
    generate_swarm_environment()
    ensure_swarm_blueprints(force_reset=True)
    
    start_time = time.time()
    last_git_time = time.time()
    last_heartbeat_time = time.time()
    
    total_rounds = 0
    rounds_in_interval = 0
    champions_frozen = 0
    
    meshes = ["ingress_mesh.txt", "processing_mesh.txt", "aggregation_mesh.txt"]
    fitness_history = {m: {"node_count": 2, "compiled_successfully": True, "total_executions": 0} for m in meshes}

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
            
            # Execute complexity-focused macro-mesh architecture mutation passes
            mutated_blueprint, mutation_description = execute_complexity_mutation(original_blueprint, target_mesh, total_rounds)
            
            with open(mesh_path, "w", encoding="utf-8") as f_write:
                f_write.write(mutated_blueprint)
                
            # Perform clean compilation validation check inside our deterministic static SDK compiler
            with open(os.devnull, 'w') as fnull:
                with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
                    compile_recipe(mesh_path, run=True)
            
            # Extract structural complexity markers (Total structural task node count allocation)
            mutated_nodes = mutated_blueprint.count("[task:")
            
            # CRITICAL 6-HOUR CONTINUOUS SELECTION SEED FILTER: Reward network architecture scaling!
            # If the change compiles with zero errors and increases total structural node depth, lock it in permanently!
            if mutated_nodes > fitness_history[target_mesh]["node_count"]:
                print(f"📈 [Swarm Expansion Champion] Component [{target_mesh}] scaled out cleanly!", flush=True)
                print(f"   ↳ Action: {mutation_description}", flush=True)
                print(f"   ↳ Topology Node Depth Increased: {fitness_history[target_mesh]['node_count']} nodes -> {mutated_nodes} nodes", flush=True)
                
                fitness_history[target_mesh]["node_count"] = mutated_nodes
                fitness_history[target_mesh]["compiled_successfully"] = True
                fitness_history[target_mesh]["total_executions"] += 1
                champions_frozen += 1
            elif mutated_blueprint != original_blueprint and mutated_nodes == fitness_history[target_mesh]["node_count"]:
                # Accept non-destructive logging updates and valid graph link edge tweaks to maintain variety
                fitness_history[target_mesh]["compiled_successfully"] = True
            else:
                # Instantly discard any structural changes that degrade node scale or count parameters
                with open(mesh_path, "w", encoding="utf-8") as f_revert:
                    f_revert.write(original_blueprint)
                    
        except Exception:
            # Revert instantly if a structural edge routing mutation breaks the compiler parser rules
            try:
                with open(mesh_path, "w", encoding="utf-8") as f_revert:
                    f_revert.write(original_blueprint)
            except Exception:
                pass

        if (current_time - last_heartbeat_time) >= HEARTBEAT_COOLDOWN:
            print(f"⏳ [Heartbeat] Processing. Instantiations in last 10s: {rounds_in_interval}. Global Passes: {total_rounds}. Swarm Scale Champions: {champions_frozen}. Elapsed: {elapsed}s", flush=True)
            rounds_in_interval = 0
            last_heartbeat_time = current_time

        if (current_time - last_git_time) >= GIT_COOLDOWN:
            last_git_time = current_time
            push_git_checkpoint(f"Swarm network thriving and scaling at {elapsed}s mark. Structural nodes verified.", fitness_history)

    print("🏁 Operational timeline achieved. Finalizing unified Swarm Box structures.", flush=True)
    push_git_checkpoint(f"Evolution timeline run complete. Total Scaled Architecture Champions: {champions_frozen}", fitness_history)

if __name__ == '__main__':
    main()
