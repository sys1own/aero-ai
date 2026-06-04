import os
import sys
import time
import argparse
import json
import urllib.request
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
    
    # Switch to clean extension-free target datasets to eliminate syntax interpretation hazards
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

def clean_llm_response(text):
    """Bulletproof parsing layer to extract raw INI configurations from conversational markdown responses"""
    lines = text.split("\n")
    cleaned_lines = []
    inside_block = False
    has_code_fence = any(line.strip().startswith("```") for line in lines)
    
    for line in lines:
        cleaned_line = line.strip()
        if cleaned_line.startswith("```"):
            inside_block = not inside_block
            continue
        if has_code_fence:
            if inside_block:
                cleaned_lines.append(line)
        else:
            if cleaned_line.startswith("[") or "=" in cleaned_line or cleaned_line == "":
                cleaned_lines.append(line)
                
    result = "\n".join(cleaned_lines).strip()
    return result if result else text.strip()

def call_live_llm_cluster(mesh_name, current_recipe, fitness_report):
    """Zero-dependency API coordinator that instructs the LLM to creatively evolve the swarm"""
    keys = {
        "openrouter": os.environ.get("OPENROUTER_API_KEY"),
        "groq": os.environ.get("GROQ_API_KEY"),
        "gemini": os.environ.get("GEMINI_API_KEY")
    }
    providers = [p for p, k in keys.items() if k]
    random.shuffle(providers)
    if not providers:
        return current_recipe

    prompt = f"""You are the Swarm System Architect. Your absolute objective is to expand and optimize a multi-mesh execution framework.
You are currently tuning the component: [{mesh_name}].

CRITICAL COMPILER RULES:
1. Every task block must follow the format [task:name] with parameters like op, fn, args, or needs.
2. Ensure proper dependency mapping (tasks listed in 'needs' must actually exist).
3. NEVER write a literal period character (.) outside of an explicit double-quoted string. 
4. All file paths, names, extensions, or text strings MUST be enclosed in explicit double quotes (e.g., args = "file_name" or text = "Initializing"). Unquoted symbols will cause a LexerError compilation crash.
5. Output ONLY the raw, valid INI contents. Do not include markdown wraps, conversational descriptions, or block formatting.

CURRENT PERFORMANCE TRACKING STATISTICS:
{json.dumps(fitness_report, indent=2)}

CURRENT BLUEPRINT DEFINITION:
{current_recipe}"""

    for provider in providers:
        try:
            if provider == "openrouter":
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {keys['openrouter']}", "Content-Type": "application/json"},
                    data=json.dumps({"model": "google/gemini-2.5-flash", "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
                )
            elif provider == "groq":
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {keys['groq']}", "Content-Type": "application/json"},
                    data=json.dumps({"model": "llama3-70b-8192", "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
                )
            elif provider == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={keys['gemini']}"
                req = urllib.request.Request(
                    url,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
                )
            
            with urllib.request.urlopen(req, timeout=12) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                raw_output = res_data["choices"][0]["message"]["content"] if provider in ["openrouter", "groq"] else res_data["candidates"][0]["content"]["parts"][0]["text"]
                return clean_llm_response(raw_output)
        except Exception:
            continue
    return current_recipe

def push_git_checkpoint(reason, metrics):
    """Commits and pushes the evolving multi-mesh databases using targeted directory paths"""
    print(f"📦 [Checkpoint] Pushing Evolved Swarm State: {reason}", flush=True)
    
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
    
    os.system(f'git -C "{_ROOT}" commit -m "chore: optimize distributed swarm infrastructure assets [metrics updated]" 2>&1')
    os.system(f'git -C "{_ROOT}" push origin main 2>&1')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=1200)
    args = parser.parse_args()

    print("🚀 Initializing Autonomous Distributed Swarm Architecture Engine...", flush=True)
    generate_swarm_environment()
    ensure_swarm_blueprints(force_reset=True)
    
    start_time = time.time()
    last_llm_time = 0
    last_git_time = time.time()
    last_heartbeat_time = time.time()
    
    total_rounds = 0
    rounds_in_interval = 0
    
    meshes = ["ingress_mesh.txt", "processing_mesh.txt", "aggregation_mesh.txt"]
    fitness_history = {m: {"compiled_successfully": True, "total_executions": 0, "last_execution_wall_ms": 0} for m in meshes}

    LLM_COOLDOWN = 120        
    GIT_COOLDOWN = 180        
    HEARTBEAT_COOLDOWN = 10   

    bp_dir = os.path.join(_ROOT, "aero_mesh_core", "swarm_blueprints")

    while (time.time() - start_time) < args.duration:
        current_time = time.time()
        elapsed = int(current_time - start_time)
        remaining = args.duration - elapsed
        
        total_rounds += 1
        rounds_in_interval += 1
        
        for mesh in meshes:
            mesh_path = os.path.join(bp_dir, mesh)
            try:
                t0 = time.perf_counter()
                with open(os.devnull, 'w') as fnull:
                    with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
                        compile_recipe(mesh_path, run=True)
                duration_ms = (time.perf_counter() - t0) * 1000
                
                fitness_history[mesh]["total_executions"] += 1
                fitness_history[mesh]["last_execution_wall_ms"] = round(duration_ms, 4)
                fitness_history[mesh]["compiled_successfully"] = True
            except Exception as ce:
                # DUMP AND TRACK WARNING DIAGNOSTICS: Expose the raw file contents causing the alert
                if fitness_history[mesh]["compiled_successfully"]:
                    print(f"⚠️ [Compiler Alert] Component [{mesh}] failed compilation check: {ce}", flush=True)
                    try:
                        with open(mesh_path, "r", encoding="utf-8") as ferr:
                            print(f"--- ACTIVE FILE RAW LAYER [{mesh}] ---\n{ferr.read()}\n--------------------------------------", flush=True)
                    except Exception:
                        pass
                fitness_history[mesh]["compiled_successfully"] = False

        if (current_time - last_llm_time) >= LLM_COOLDOWN:
            last_llm_time = current_time
            target_mesh = random.choice(meshes)
            target_path = os.path.join(bp_dir, target_mesh)
            
            print(f"🤖 [LLM Cluster Mode] Expanding Swarm System Architecture Layer -> [{target_mesh}] (Time Remaining: {remaining}s)", flush=True)
            try:
                with open(target_path, "r", encoding="utf-8") as rf:
                    old_recipe = rf.read()
                
                new_recipe = call_live_llm_cluster(target_mesh, old_recipe, fitness_history[target_mesh])
                
                if new_recipe and new_recipe != old_recipe and "[project]" in new_recipe:
                    with open(target_path, "w", encoding="utf-8") as wf:
                        wf.write(new_recipe)
                    print(f"⚡ Structural Adaptation Implemented: Refactored structural definitions inside {target_mesh}.", flush=True)
            except Exception as e:
                print(f"⚠️ Mutation hold: {e}", flush=True)

        if (current_time - last_heartbeat_time) >= HEARTBEAT_COOLDOWN:
            print(f"⏳ [Heartbeat] Processing Swarm. Cycles in last 10s: {rounds_in_interval}. Cumulative Swarm Cycles: {total_rounds}. Runtime: {elapsed}s", flush=True)
            rounds_in_interval = 0
            last_heartbeat_time = current_time

        if (current_time - last_git_time) >= GIT_COOLDOWN:
            last_git_time = current_time
            push_git_checkpoint(f"Swarm network stable at {elapsed}s mark", fitness_history)

    print("🏁 Operational timeline achieved. Finalizing unified Swarm Box structures.", flush=True)
    push_git_checkpoint("Evolution timeline run successfully completed.", fitness_history)

if __name__ == '__main__':
    main()
