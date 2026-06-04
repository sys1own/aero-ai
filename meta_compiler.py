import re
"""
Aero Meta-Compiler — Intent-Driven Build Engine
===============================================

Lets you describe a build as a high-level, declarative *recipe* (an INI
file) and compiles it all the way down to verified ``.aeroc`` bytecode —
without writing a line of Aero by hand.

Pipeline:

    recipe.ini  ->  generate_aero()  ->  .aero source
                ->  tokenize / parse / codegen  (the local SDK)
                ->  CompiledProgram  ->  serialized .aeroc artifact

Recipe format
-------------
A ``[project]`` section plus one ``[task:NAME]`` section per step::

    [project]
    name   = hello
    output = build_sandbox/recipes/hello.aeroc

    [task:greet]
    op   = print
    text = Building ${name}

    [task:base]
    op    = set
    name  = base
    value = 21

    [task:total]
    op    = compute       ; declarative arithmetic, no Aero syntax needed
    name  = total
    a     = base
    op_kind = mul         ; add | sub | mul | div | mod  (or a +-*/% symbol)
    b     = 2
    needs = base

    [task:show]
    op    = print
    value = total         ; print a value/expression directly
    needs = total, greet

Supported ops: ``comment``, ``print`` (``text`` or ``value``), ``set``
(alias ``let``), ``compute`` (``a``/``op_kind``/``b``), ``call``
(``fn``/``args``), ``func`` (``params``/``returns``). Tasks are ordered by
their ``needs`` dependencies (a stable topological sort).

CLI::

    python meta_compiler.py RECIPE [-o OUT.aeroc] [--show] [--run]
"""

import argparse
import configparser
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from aero_sdk.compiler.lexer import tokenize
from aero_sdk.compiler.parser import Parser
from aero_sdk.compiler.codegen import Codegen
from aero_sdk.vm.machine import AeroVM, _serialize_program

# Word aliases so recipe authors never have to type an Aero operator.
_WORD_OPS = {
    "add": "+", "plus": "+", "sum": "+",
    "sub": "-", "minus": "-",
    "mul": "*", "times": "*", "product": "*",
    "div": "/", "over": "/",
    "mod": "%", "rem": "%",
}
_SYMBOL_OPS = {"+", "-", "*", "/", "%"}


class RecipeError(Exception):
    """Raised when a recipe is malformed or cannot be lowered to Aero."""


# ── Recipe parsing ────────────────────────────────────────────────────────

def load_recipe(path):
    """Parse an INI recipe file into a structured dict."""
    if not os.path.isfile(path):
        raise RecipeError(f"recipe not found: {path}")
    parser = configparser.ConfigParser()
    # Preserve key case so e.g. function param names survive untouched.
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise RecipeError(f"invalid INI syntax: {exc}") from exc

    project = dict(parser["project"]) if parser.has_section("project") else {}

    tasks = []
    for section in parser.sections():
        if not section.startswith("task:"):
            continue
        name = section[len("task:"):].strip()
        if not name:
            raise RecipeError(f"empty task name in section [{section}]")
        fields = dict(parser[section])
        op = fields.pop("op", None)
        if not op:
            raise RecipeError(f"task {name!r} is missing an 'op'")
        needs = [d.strip() for d in fields.pop("needs", "").split(",") if d.strip()]
        tasks.append({"name": name, "op": op.strip().lower(), "needs": needs, "fields": fields})

    return {"project": project, "tasks": tasks}


def _resolve_order(tasks):
    """Stable topological sort: dependencies emitted before dependents."""
    by_name = {t["name"]: t for t in tasks}
    for t in tasks:
        for dep in t["needs"]:
            if dep not in by_name:
                raise RecipeError(f"task {t['name']!r} needs unknown task {dep!r}")

    order, state = [], {}  # state: 1=visiting, 2=done
    def visit(t):
        s = state.get(t["name"], 0)
        if s == 2:
            return
        if s == 1:
            raise RecipeError(f"dependency cycle involving task {t['name']!r}")
        state[t["name"]] = 1
        for dep in t["needs"]:
            visit(by_name[dep])
        state[t["name"]] = 2
        order.append(t)

    for t in tasks:  # declaration order drives tie-breaks
        visit(t)
    return order


# ── Lowering: recipe -> Aero source ───────────────────────────────────────

def _interpolate(text, variables):
    out = text
    for key, value in variables.items():
        out = out.replace("${" + key + "}", str(value))
    return out


def _aero_string(s):
    """Quote a string as an Aero literal (the lexer has no escape sequences)."""
    s = s.replace("\r", " ").replace("\n", " ")
    if '"' not in s:
        return '"' + s + '"'
    if "'" not in s:
        return "'" + s + "'"
    return '"' + s.replace('"', "'") + '"'  # both quotes present: fold to '


def _require(task, *keys):
    missing = [k for k in keys if not task["fields"].get(k, "").strip()]
    if missing:
        raise RecipeError(
            f"task {task['name']!r} (op={task['op']}) missing field(s): "
            + ", ".join(missing)
        )


def _lower_task(task, variables):
    op, f = task["op"], task["fields"]

    if op == "comment":
        return "// " + _interpolate(f.get("text", "").strip(), variables)

    if op == "print":
        if f.get("value", "").strip():
            return f"print({f['value'].strip()});"
        _require(task, "text")
        return f"print({_aero_string(_interpolate(f['text'], variables))});"

    if op in ("set", "let"):
        _require(task, "name", "value")
        return f"let {f['name'].strip()} = {f['value'].strip()};"

    if op == "compute":
        if "expr" in f:
            return f"let {f['name'].strip()} = {f['expr'].strip()};"
        _require(task, "name", "a", "op_kind", "b")
        _require(task, "name", "a", "op_kind", "b")
        raw = f["op_kind"].strip()
        symbol = raw if raw in _SYMBOL_OPS else _WORD_OPS.get(raw.lower())
        if symbol is None:
            raise RecipeError(
                f"task {task['name']!r}: unknown op_kind {raw!r} "
                f"(use one of {sorted(_WORD_OPS)} or {sorted(_SYMBOL_OPS)})"
            )
        return f"let {f['name'].strip()} = {f['a'].strip()} {symbol} {f['b'].strip()};"

    if op == "call":
        _require(task, "fn")
        return f"{f['fn'].strip()}({f.get('args', '').strip()});"

    if op == "while":
        _require(task, "condition", "body")
        # Upgraded block compiler: handles clean newlines and optional semicolons inside INI task blocks
        body_statements = "; ".join(line.strip().rstrip(';') for line in re.split(r'[\n;]+', f["body"]) if line.strip()) + ";"
        return f"while {f['condition'].strip()} {{ {body_statements} }}"

    if op == "func":
        _require(task, "name")
        params = ", ".join(p.strip() for p in f.get("params", "").split(",") if p.strip())
        body = f.get("returns", "").strip() or "0"
        return f"fn {f['name'].strip()}({params}) {{ return {body}; }}"

    raise RecipeError(f"task {task['name']!r}: unsupported op {op!r}")


def generate_aero(recipe):
    """Lower a parsed recipe into a complete Aero source string."""
    project = recipe["project"]
    name = project.get("name", "unnamed")
    order = _resolve_order(recipe["tasks"])

    lines = [
        "// ============================================================",
        f"// AUTO-GENERATED by meta_compiler.py from recipe: {name}",
        "// Do not edit by hand — edit the recipe and regenerate.",
        "// ============================================================",
    ]
    # Functions hoist in Aero, but emit them first for human readability.
    funcs = [t for t in order if t["op"] == "func"]
    body = [t for t in order if t["op"] != "func"]
    for t in funcs:
        lines.append(_lower_task(t, project))
    if funcs:
        lines.append("")
    for t in body:
        lines.append(_lower_task(t, project))
    return "\n".join(lines) + "\n"


# ── Full pipeline: recipe -> .aeroc ───────────────────────────────────────

def compile_recipe(path, out_path=None, run=False):
    """Generate, compile and (optionally) execute a recipe.

    Returns a dict with the generated source, the CompiledProgram, the
    written artifact path and any VM output. Raises on any failure, so a
    clean return means syntactically flawless Aero that compiled cleanly.
    """
    recipe = load_recipe(path)
    source = generate_aero(recipe)

    # The compile itself is the correctness gate: lexer/parser/codegen raise
    # on any malformed construct.
    tokens = tokenize(source)
    ast = Parser(tokens).parse()
    program = Codegen().compile(ast)

    if out_path is None:
        project_name = recipe["project"].get("name", "recipe")
        out_path = os.path.join(_HERE, "build_sandbox", "recipes", f"{project_name}.aeroc")
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(_serialize_program(program), fh, indent=2)

    vm_output = None
    if run:
        vm = AeroVM(program)
        vm.run()
        vm_output = list(vm.output)

    return {
        "recipe": recipe,
        "source": source,
        "program": program,
        "aeroc_path": out_path,
        "vm_output": vm_output,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="meta_compiler",
        description="Compile a declarative Aero build recipe to .aeroc bytecode.",
    )
    ap.add_argument("recipe", help="path to the INI recipe file")
    ap.add_argument("-o", "--out", default=None, help="output .aeroc path")
    ap.add_argument("--show", action="store_true", help="print the generated Aero")
    ap.add_argument("--run", action="store_true", help="execute the program on the VM")
    ap.add_argument("--clean", action="store_true", help="automatically purge targeted build output frames before compiling")
    args = ap.parse_args(argv)

    if args.clean:
        import shutil
        recipe_data = load_recipe(args.recipe)
        out_target = recipe_data.get("project", {}).get("output", "")
        if out_target:
            parent_sandbox = os.path.dirname(os.path.dirname(out_target))
            if parent_sandbox and os.path.exists(parent_sandbox) and "build_sandbox" in parent_sandbox:
                print(f"🧹 Core Sanitation: Purging stale assets from {parent_sandbox}...")
                shutil.rmtree(parent_sandbox, ignore_errors=True)

    try:
        result = compile_recipe(args.recipe, out_path=args.out, run=args.run)
    except RecipeError as exc:
        print(f"meta_compiler: {exc}", file=sys.stderr)
        return 2

    if args.show:
        print("----- generated .aero -----")
        print(result["source"], end="")
        print("---------------------------")
    prog = result["program"]
    print(
        f"OK: compiled {os.path.relpath(args.recipe)} -> "
        f"{os.path.relpath(result['aeroc_path'])} "
        f"({len(prog.main_code)} main ops, {len(prog.functions)} fns, "
        f"{len(prog.constants)} constants)"
    )
    if result["vm_output"] is not None:
        print("VM output:", result["vm_output"])
    return 0



# ── Concurrent Dependency Graph Execution Scheduler ───────────────────────

def execute_recipe_parallel(recipe_path, max_workers=4):
    """Parses a build recipe configuration file and schedules independent tasks concurrently."""
    import concurrent.futures
    
    recipe_data = load_recipe(recipe_path)
    tasks = recipe_data["tasks"]
    project_config = recipe_data["project"]
    
    # Track completion states and dependencies dynamically
    completed_tasks = set()
    running_futures = {}
    
    task_lookup = {t["name"]: t for t in tasks}
    dependencies = {t["name"]: set(t["needs"]) for t in tasks}
    
    print(f"🧵 Initializing Parallel Orchestration Runner with {max_workers} thread pool workers...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        while len(completed_tasks) < len(tasks):
            # Launch tasks that have all dependencies met and are not already running
            for t_name, deps in list(dependencies.items()):
                if t_name not in completed_tasks and t_name not in running_futures:
                    if deps.issubset(completed_tasks):
                        # Lower the single target task to an isolated executable Aero statement block
                        task_obj = task_lookup[t_name]
                        aero_statement = _lower_task(task_obj, project_config)
                        
                        # Define a contained lambda wrapper to process the task statement safely on the VM
                        def execution_wrapper(stmt=aero_statement, name=t_name):
                            from aero_sdk.compiler.lexer import tokenize
                            from aero_sdk.compiler.parser import Parser
                            from aero_sdk.compiler.codegen import Codegen
                            from aero_sdk.vm.machine import AeroVM
                            
                            tokens = tokenize(stmt)
                            ast = Parser(tokens).parse()
                            prog = Codegen().compile(ast)
                            vm = AeroVM(prog)
                            vm.run()
                            return name
                            
                        future = executor.submit(execution_wrapper)
                        running_futures[future] = t_name
                        print(f"  🚀 Dispatched concurrent task thread worker: [task:{t_name}]")
            
            # Block until at least one thread completes its worker run loop segment
            if running_futures:
                done, _ = concurrent.futures.wait(running_futures.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
                for finished_future in done:
                    completed_task_name = running_futures.pop(finished_future)
                    completed_tasks.add(completed_task_name)
                    print(f"  🏁 Worker thread execution resolved: [task:{completed_task_name}]")
                    
    print("✅ Parallel build recipe schedule processing complete.")
    return True

if __name__ == "__main__":
    sys.exit(main())
