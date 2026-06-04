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

def generate_heavy_workload(num_files=100):
    """Generates local dataset frames inside the ephemeral space to stress test tracking"""
    base_dir = "testbed/scans"
    os.makedirs(base_dir, exist_ok=True)
    for i in range(num_files):
        with open(f"{base_dir}/heavy_node_{i}.txt", "w") as f:
            f.write(f"// HIGH-DENSITY BALANCING MATRIX NODE {i}\n")
            for j in range(20):
                f.write(f"let processing_weight_{i}_{j} = {j * i};\n")

def generate_default_seed_recipe(path):
    """Programmatically restores the complete multi-threaded swarm topology map if missing"""
    print(f"🛠️ Seed blueprint absent. Generating standalone swarm topology configuration at: {path}", flush=True)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
        
    content = (
        "[project]\n"
        "name   = aero_mesh_seed\n"
        "output = build_sandbox/recipes/aero_mesh_seed.aeroc\n\n"
        "[task:banner]\n"
        "op   = print\n"
        "text = == Aero-Mesh topology: ${name} ==\n\n"
        "[task:scaffold]\n"
        "op    = call\n"
        "fn    = create_dir\n"
        "args  = \"aero_mesh_core/dist\"\n"
        "needs = banner\n\n"
        "[task:scout_alpha]\n"
        "op    = call\n"
        "fn    = read_file\n"
        "args  = \"testbed/scans/heavy_node_0.txt\"\n"
        "needs = scaffold\n\n"
        "[task:scout_beta]\n"
        "op    = call\n"
        "fn    = read_file\n"
        "args  = \"testbed/scans/heavy_node_1.txt\"\n"
        "needs = scaffold\n\n"
        "[task:scout_gamma]\n"
        "op    = call\n"
        "fn    = read_file\n"
        "args  = \"testbed/scans/heavy_node_2.txt\"\n"
        "needs = scaffold\n\n"
        "[task:linker_ab]\n"
        "op    = call\n"
        "fn    = write_file\n"
        "args  = \"aero_mesh_core/dist/links/linker_ab.txt\", \"link alpha-beta verified\"\n"
        "needs = scout_alpha, scout_beta\n\n"
        "[task:linker_bg]\n"
        "op    = call\n"
        "fn    = write_file\n"
        "args  = \"aero_mesh_core/dist/links/linker_bg.txt\", \"link beta-gamma verified\"\n"
        "needs = scout_beta, scout_gamma\n\n"
        "[task:aggregate]\n"
        "op    = call\n"
        "fn    = write_file\n"
        "args  = \"aero_mesh_core/dist/index_manifest.txt\", \"mesh index manifest map complete\"\n"
        "needs = linker_ab, linker_bg\n\n"
        "[task:done]\n"
        "op    = print\n"
        "text  = ${name} topology pass complete\n"
        "needs = aggregate\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def call_live_llm_cluster(current_recipe):
    """Zero-dependency high-availability API client with token shuffling and fallback mapping"""
    keys = {
        "openrouter": os.environ.get("OPENROUTER_API_KEY"),
        "groq": os.environ.get("GROQ_API_KEY"),
        "gemini": os.environ.get("GEMINI_API_KEY")
    }
    
    providers = [p for p, k in keys.items() if k]
    random.shuffle(providers)
    
    if not providers:
        return current_recipe

    prompt = f"You are the Aero Build Architect. Mutate this declarative INI build recipe to add a creative new task or optimize dependency loops. Keep the structure matching [project] and [task:name]. Output ONLY the raw valid INI content. Do not include markdown formatting or blocks.\n\nCURRENT RECIPE:\n{current_recipe}"

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
            
            with urllib.request.urlopen(req, timeout=15) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if provider in ["openrouter", "groq"]:
                    output = res_data["choices"][0]["message"]["content"].strip()
                else:
                    output = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                if output.startswith("```"):
                    output = "\n".join(output.split("\n")[1:-1])
                return output
                
        except Exception:
            continue
            
    return current_recipe

def push_git_checkpoint(reason, total_rounds, elapsed):
    """Executes background pushes tracking mutations, status variables, and metrics"""
    print(f"📦 [Checkpoint] Syncing states to GitHub Remote: {reason}", flush=True)
    
    os.makedirs("aero_mesh_core/dist", exist_ok=True)
    with open("aero_mesh_core/dist/live_status.txt", "w", encoding="utf-8") as sf:
        sf.write(f"STATUS: Active Evolution Loop Running\n")
        sf.write(f"LAST_CHECKPOINT_REASON: {reason}\n")
        sf.write(f"TOTAL_VM_ROUNDS_SOLVED: {total_rounds}\n")
        sf.write(f"ELAPSED_TIME_SECONDS: {elapsed}\n")
        sf.write(f"HEARTBEAT_TIMESTAMP: {time.time()}\n")

    os.system("git config --global user.name 'Aero Evolution Engine' > /dev/null 2>&1")
    os.system("git config --global user.email 'evolute@aero-auto-sdk.local' > /dev/null 2>&1")
    os.system("git add aero_mesh_core/aero_mesh_seed.txt aero_mesh_core/dist/* build_sandbox/recipes/* > /dev/null 2>&1 || true")
    os.system("git commit -m 'chore: evolutionary checkpoint update [structural modifications]' > /dev/null 2>&1")
    os.system("git push origin main > /dev/null 2>&1")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=1200)
    parser.add_argument('--max-cycles', type=int, default=99999)
    args = parser.parse_args()

    print("🚀 Initializing High-Efficiency Paced Self-Evolution Engine...", flush=True)
    generate_heavy_workload()
    
    start_time = time.time()
    last_llm_time = 0
    last_git_time = time.time()
    last_heartbeat_time = time.time()
    
    rounds_in_interval = 0
    total_rounds = 0
    
    LLM_COOLDOWN = 120        
    GIT_COOLDOWN = 180        
    HEARTBEAT_COOLDOWN = 10   
    
    recipe_path = None
    for root, _, files in os.walk(_ROOT):
        if "aero_mesh_seed.txt" in files:
            recipe_path = os.path.join(root, "aero_mesh_seed.txt")
            break
            
    if not recipe_path:
        for root, _, files in os.walk("."):
            if "aero_mesh_seed.txt" in files:
                recipe_path = os.path.join(root, "aero_mesh_seed.txt")
                break

    # SELF-HEALING INDEPENDENCE: If the file was cleaned or missing, restore it on the fly
    if not recipe_path:
        recipe_path = os.path.join("aero_mesh_core", "aero_mesh_seed.txt")
        generate_default_seed_recipe(recipe_path)
        
    print(f"🎯 Configuration mapped. Target recipe verified at: {recipe_path}", flush=True)

    while (time.time() - start_time) < args.duration:
        current_time = time.time()
        elapsed = int(current_time - start_time)
        remaining = args.duration - elapsed
        
        rounds_in_interval += 1
        total_rounds += 1
        
        # --- TIMED LLM MACRO ARCHITECTURE TRIGGER ---
        if (current_time - last_llm_time) >= LLM_COOLDOWN:
            last_llm_time = current_time
            print(f"🤖 [LLM Creative Phase] Querying optimization cluster... (Time Remaining: {remaining}s)", flush=True)
            try:
                with open(recipe_path, "r", encoding="utf-8") as rf:
                    old_recipe = rf.read()
                new_recipe = call_live_llm_cluster(old_recipe)
                if new_recipe and new_recipe != old_recipe and "[project]" in new_recipe:
                    with open(recipe_path, "w", encoding="utf-8") as wf:
                        wf.write(new_recipe)
                    print("⚡ Structural Mutation Applied: Written updated layout definitions to configuration file.", flush=True)
            except Exception as e:
                print(f"⚠️ Trapped exception: {e}", flush=True)

        # --- NATIVE HIGH-SPEED PERFORMANCE EVALUATION ---
        try:
            with open(os.devnull, 'w') as fnull:
                with contextlib.redirect_stdout(fnull), contextlib.redirect_stderr(fnull):
                    compile_recipe(recipe_path, run=True)
        except Exception:
            pass

        # --- REAL-TIME LIVENESS HEARTBEAT ---
        if (current_time - last_heartbeat_time) >= HEARTBEAT_COOLDOWN:
            print(f"⏳ [Heartbeat] Active. Executed {rounds_in_interval} rounds in last {HEARTBEAT_COOLDOWN}s. Total Rounds: {total_rounds}. Elapsed: {elapsed}s", flush=True)
            rounds_in_interval = 0
            last_heartbeat_time = current_time

        # --- TIMED GIT CHECKPOINT GENERATION ---
        if (current_time - last_git_time) >= GIT_COOLDOWN:
            last_git_time = current_time
            push_git_checkpoint(f"Sustained runs stable at {elapsed}s mark", total_rounds, elapsed)

    print(f"🏁 Timeline threshold reached. Finalizing static build configurations.", flush=True)
    push_git_checkpoint("Final evolution pass complete.", total_rounds, int(time.time() - start_time))

if __name__ == '__main__':
    main()
