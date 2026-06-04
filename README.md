# Aero Auto SDK

An intent-driven build engine, minimalist compiler pipeline, and high-performance stack-based virtual machine distribution . The Aero Auto SDK lets developers write clean, declarative software recipes, lower them automatically into intermediate script statements, compile them to structured bytecode files, and run them deterministically on an accelerated virtual stack interpreter .

---

## ⚙️ Architecture Tour

The toolchain processes high-level configuration targets down to low-level virtual machine state transitions across three primary components:

```
   [ Declarative Recipe ] (.txt/.ini)
             │
             ▼
     ( meta_compiler ) ────► Schedules tasks, purges targets, resolves out-of-tree builds
             │
             ▼
      [ Aero Source ] (.aero)
             │
             ▼
        ( Lexer ) ─────────► Slices character streams & evaluates backslash escapes
             │
             ▼
       ( Parser ) ─────────► Builds AST nodes via precedence-climbing expressions
             │
             ▼
       ( Codegen ) ────────► Lowers AST & hardwires optimized native macros
             │
             ▼
     [ Bytecode Asset ] (.aeroc)
             │
             ▼
         ( AeroVM ) ───────► Executes stacks & records real-time opcode telemetry

```

### 1. The Meta-Compiler Automation Framework

The `meta_compiler.py` workspace utility manages execution pipelines by reading declarative INI task models and compiling them into sequential statements :

* **Topological Graph Sorting**: Analyzes task dependency chains via an internal graph tracking matrix to ensure prerequisite steps execute first .


* **Automated Workspace Sanitation (`--clean`)**: Purges destination build paths automatically prior to code emission, ensuring legacy assets never bleed into fresh builds.
* **Global Path Autonomy**: Supports out-of-tree processing paths, enabling developers to maintain recipes and build targets completely decoupled from the core SDK tree.
* **Parallel Task Graph Scheduling**: Leverages an integrated thread pool executor loop (`execute_recipe_parallel`) to identify independent, non-conflicting build branches and route them to parallel worker threads concurrently.

### 2. The Frontend Compiler Pipeline

Contained inside the clean `aero_sdk/compiler/` package layer, the pipeline lowers human-readable source formats down to raw, linear virtual engine instruction structures:

* **Lexer Code Scanner (`lexer.py`)**: Slices files into classified token sets against keywords, booleans, and operator tables . Features an escape sequence module to handle literal character tokens (`\n`, `\t`, `\"`, `\'`, `\\`) inside string slices .


* **Parser Expression Engine (`parser.py`)**: Consumes lookahead streams via recursive-descent parsing to construct valid Abstract Syntax Tree statements, conditional branches, and iteration loops .


* **Code Generator Frontend (`codegen.py`)**: Generates optimized assembly tuples from AST outputs . Intercepts standard FFI operations (`print`, `create_dir`, `write_file`, `read_file`, `compile_source`, `save_binary`, `get_timestamp`) at compile time and injects accelerated `OpCode.CALL_DIRECT` macro operations to completely skip runtime lookup cycles .



### 3. The Virtual Machine Container

Housed inside `aero_sdk/vm/machine.py`, the runtime engine executes binaries deterministically:

* **Dual Stack Layout**: Isolates arithmetic logic operations on a dynamically sized operand stack while tracking stack local frame variable arrays within nested call contexts .


* **Macro Dispatch Decoder**: Intercepts `CALL_DIRECT` micro-opcodes on the hot path, immediately routing arguments directly to host-side operating system system calls to accelerate intensive file I/O operations .


* **Opcode Usage Telemetry**: Counts every single instruction execution loop pass, exporting real-time execution weight matrices out to a profile log (`vm_profile.json`) upon reaching a `HALT` command instruction .



---

## 🛠️ Usage Specifications

### Blueprint Blueprint Syntax

Construct complex, multi-stage compilation workflows inside a standard declarative recipe file:

```ini
[project]
name = global_enterprise_deploy
output = /absolute/path/to/external/workspace/build_sandbox/recipes/release.aeroc
version_tag = 2.4.0

[task:banner]
op = print
text = === Commencing Global Deployment Pipeline for Release v${version_tag} ===

[task:scaffold]
op = call
fn = create_dir
args = "/absolute/path/to/external/workspace/build_sandbox/production_target"
needs = banner

[task:evaluate_complex_math]
op = compute
name = thread_allocation_matrix
expr = (1024 * 4) / (2 + 2)
needs = scaffold

[task:initialize_loop]
op = set
name = loop_ticks
value = 0

[task:process_nodes]
op = while
condition = loop_ticks < 3
body = print("Sending telemetry validation packet payload down to node coordinates:")
       print(loop_ticks)
       let loop_ticks = loop_ticks + 1
needs = evaluate_expression_matrices, initialize_loop

```

### Command Line Core Execution

#### 1. Running Standard Multi-Stage Recipes

Manage, evaluate, clear, or execute your declarative recipe structures using `meta_compiler.py`:

```bash
# Compile a configuration recipe down to bytecode binaries
python meta_compiler.py enterprise_recipe.txt -o build_sandbox/recipes/release.aeroc

# Display intermediate lowered code structures directly on the terminal
python meta_compiler.py enterprise_recipe.txt --show

# Compile, optimize, and instantly run a recipe on the stack VM interpreter
python meta_compiler.py enterprise_recipe.txt --run

# Automatically purge targeted build output frames before compiling
python meta_compiler.py enterprise_recipe.txt --clean --run

```

#### 2. Driving the Core Compiler Utility Bootstrap

Directly invoke compile, build, or execution steps over raw script assets using `aero.py`:

```bash
# Regenerate language tables from specifications and execute the local toolchain script
python aero.py build

# Execute a custom .aero script through the self-hosted build channel
python aero.py build -s target_script.aero

# Directly compile and execute any raw intermediate Aero file on the VM
python aero.py run src/app.aero

```
