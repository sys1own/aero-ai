"""
Aero CLI — Bootstrap runner for the self-hosted build tool.

Usage:
    python aero.py build              # Run the Aero build script
    python aero.py build -s FILE      # Run a custom .aero build script
    python aero.py run FILE           # Compile and run any .aero file
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from aero_sdk.compiler.lexer import tokenize
from aero_sdk.compiler.parser import Parser
from aero_sdk.compiler.codegen import Codegen
from aero_sdk.vm.machine import AeroVM
from aero_sdk.optimizer import generator
from aero_sdk.optimizer import language_spec as spec_io

DEFAULT_BUILD_SCRIPT = os.path.join(_HERE, "aero_build.aero")
CONFIG_SPEC = os.path.join(_HERE, "config", "language_spec.json")
ROOT_LEXER = os.path.join(_HERE, "aero_sdk", "compiler", "lexer.py")


def regenerate_lexer():
    """Spec-driven compiler-compiler step: regenerate lexer.py from the spec.

    Makes good on the lexer's documented contract — its language-tables block
    is produced deterministically from ``config/language_spec.json``. Only the
    tables are swapped; the proven scanning logic in the skeleton is preserved
    (and the longest-match-first operator invariant is asserted by the
    generator). The operation is idempotent: if the lexer already matches the
    spec, the bytes are unchanged.

    Returns True if regeneration ran, False if no spec was found (e.g. a
    stripped-down sandbox copy), so the build can proceed regardless.
    """
    if not os.path.exists(CONFIG_SPEC):
        return False
    spec = spec_io.load_spec(CONFIG_SPEC)
    generator.render_lexer_file(spec, ROOT_LEXER, ROOT_LEXER)
    return True


def _compile_and_run(script_path):
    """Load an .aero file, compile it, and execute it on the VM."""
    if not os.path.exists(script_path):
        print(f"aero: script not found: {script_path}", file=sys.stderr)
        return 1

    with open(script_path, "r", encoding="utf-8") as f:
        source = f.read()

    tokens = tokenize(source)
    ast = Parser(tokens).parse()
    program = Codegen().compile(ast)
    vm = AeroVM(program)
    vm.run()
    return 0


def cmd_build(args):
    """Regenerate the lexer from the spec, then run the self-hosted build."""
    if regenerate_lexer():
        print("aero: regenerated lexer.py from config/language_spec.json")
    script = args.script or DEFAULT_BUILD_SCRIPT
    return _compile_and_run(script)


def cmd_run(args):
    """Compile and run an arbitrary .aero file."""
    return _compile_and_run(args.file)


def main():
    parser = argparse.ArgumentParser(
        prog="aero",
        description="Aero Language CLI — compile and run .aero scripts.",
    )
    sub = parser.add_subparsers(dest="command")

    build_p = sub.add_parser("build", help="Run the self-hosted Aero build script")
    build_p.add_argument(
        "-s", "--script", default=None,
        help="Path to a custom .aero build script (default: aero_build.aero)",
    )

    run_p = sub.add_parser("run", help="Compile and run any .aero file")
    run_p.add_argument("file", help="Path to the .aero source file")

    args = parser.parse_args()

    if args.command == "build":
        return cmd_build(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
