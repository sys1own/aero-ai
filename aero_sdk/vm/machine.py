"""
Aero VM — Stack-Based Bytecode Interpreter
===========================================

Executes compiled Aero bytecode instructions on a virtual stack machine.

Architecture:
    - Operand stack (dynamically sized)
    - Call stack (frames with local variable slots)
    - Constant pool (shared across all frames)
    - Program counter per frame
"""

import json
import os
import time

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from aero_sdk.compiler.codegen import CompiledProgram, CompiledFunction, OpCode


@dataclass
class CallFrame:
    code: list
    pc: int = 0
    locals: Dict[int, Any] = field(default_factory=dict)
    base_pointer: int = 0


class VMError(Exception):
    pass


class AeroVM:
    MAX_STACK_SIZE = 4096
    MAX_CALL_DEPTH = 256

    def __init__(self, program: CompiledProgram):
        self._program = program
        self._stack: List[Any] = []
        self._call_stack: List[CallFrame] = []
        self._fn_table: Dict[str, CompiledFunction] = {
            fn.name: fn for fn in program.functions
        }
        self._builtins: Dict[str, Any] = {
            "print": self._builtin_print,
            "len": self._builtin_len,
            "int": self._builtin_int,
        }
        self._output: List[str] = []
        # --- VM TELEMETRY RUNTIME PROFILE TRACKER ---
        self._opcode_profile_counts = {}
        # --------------------------------------------

        # Native function registry (FFI bridge).
        # When an Aero script calls one of these names, the VM dispatches
        # directly to the host Python callable instead of looking up a
        # compiled Aero function.  Additional natives can be registered at
        # runtime via ``register_native``.
        self.native_functions: Dict[str, Callable] = {
            "print":          self._native_print,
            "create_dir":     self._native_create_dir,
            "write_file":     self._native_write_file,
            "read_file":      self._native_read_file,
            "compile_source": self._native_compile_source,
            "save_binary":    self._native_save_binary,
            "get_timestamp":  self._native_get_timestamp,
        }

    @property
    def output(self) -> List[str]:
        return self._output

    def run(self) -> Any:
        frame = CallFrame(code=self._program.main_code)
        self._call_stack.append(frame)
        return self._execute()

    def _execute(self) -> Any:
        while self._call_stack:
            frame = self._call_stack[-1]

            if frame.pc >= len(frame.code):
                self._call_stack.pop()
                continue

            instr = frame.code[frame.pc]
            frame.pc += 1
            op = instr[0]
            # Record opcode dispatch ticks live on the hot execution path
            op_name = op.name if hasattr(op, 'name') else str(op)
            self._opcode_profile_counts[op_name] = self._opcode_profile_counts.get(op_name, 0) + 1

            if op == OpCode.CALL_DIRECT:


                # Optimized macro-dispatch execution path


                callee = self._pop()


                argc = instr[1]


                args = [self._pop() for _ in range(argc)]


                args.reverse()


                if isinstance(callee, str) and callee in self.native_functions:


                    result = self.native_functions[callee](args)


                    self._push(result if result is not None else 0)


                continue



            if op == OpCode.PUSH_INT:
                self._push(instr[1])
            elif op == OpCode.PUSH_FLOAT:
                self._push(self._program.constants[instr[1]])
            elif op == OpCode.PUSH_STRING:
                self._push(self._program.constants[instr[1]])
            elif op == OpCode.PUSH_BOOL:
                self._push(bool(instr[1]))
            elif op == OpCode.LOAD:
                slot = instr[1]
                if slot not in frame.locals:
                    raise VMError(f"undefined local variable at slot {slot}")
                self._push(frame.locals[slot])
            elif op == OpCode.STORE:
                slot = instr[1]
                frame.locals[slot] = self._pop()
            elif op == OpCode.ADD:
                b, a = self._pop(), self._pop()
                self._push(a + b)
            elif op == OpCode.SUB:
                b, a = self._pop(), self._pop()
                self._push(a - b)
            elif op == OpCode.MUL:
                b, a = self._pop(), self._pop()
                self._push(a * b)
            elif op == OpCode.DIV:
                b, a = self._pop(), self._pop()
                if b == 0:
                    raise VMError("division by zero")
                self._push(a / b if isinstance(a, float) or isinstance(b, float) else a // b)
            elif op == OpCode.MOD:
                b, a = self._pop(), self._pop()
                if b == 0:
                    raise VMError("modulo by zero")
                self._push(a % b)
            elif op == OpCode.EQ:
                b, a = self._pop(), self._pop()
                self._push(a == b)
            elif op == OpCode.NEQ:
                b, a = self._pop(), self._pop()
                self._push(a != b)
            elif op == OpCode.LT:
                b, a = self._pop(), self._pop()
                self._push(a < b)
            elif op == OpCode.GT:
                b, a = self._pop(), self._pop()
                self._push(a > b)
            elif op == OpCode.LTE:
                b, a = self._pop(), self._pop()
                self._push(a <= b)
            elif op == OpCode.GTE:
                b, a = self._pop(), self._pop()
                self._push(a >= b)
            elif op == OpCode.AND:
                b, a = self._pop(), self._pop()
                self._push(bool(a and b))
            elif op == OpCode.OR:
                b, a = self._pop(), self._pop()
                self._push(bool(a or b))
            elif op == OpCode.NOT:
                self._push(not self._pop())
            elif op == OpCode.NEG:
                self._push(-self._pop())
            elif op == OpCode.JUMP:
                frame.pc = instr[1]
            elif op == OpCode.JUMP_IF_FALSE:
                cond = self._pop()
                if not cond:
                    frame.pc = instr[1]
            elif op == OpCode.CALL:
                argc = instr[1]
                callee = self._pop()
                args = [self._pop() for _ in range(argc)]
                args.reverse()

                if isinstance(callee, str) and callee in self.native_functions:
                    result = self.native_functions[callee](args)
                    self._push(result if result is not None else 0)
                elif isinstance(callee, str) and callee in self._builtins:
                    result = self._builtins[callee](args)
                    self._push(result)
                elif isinstance(callee, str) and callee in self._fn_table:
                    fn = self._fn_table[callee]
                    if len(args) != len(fn.params):
                        raise VMError(
                            f"function '{callee}' expects {len(fn.params)} args, got {len(args)}"
                        )
                    if len(self._call_stack) >= self.MAX_CALL_DEPTH:
                        raise VMError("maximum call depth exceeded")
                    new_frame = CallFrame(code=fn.code, base_pointer=len(self._stack))
                    for i, arg in enumerate(args):
                        new_frame.locals[i] = arg
                    self._call_stack.append(new_frame)
                else:
                    raise VMError(f"cannot call: {callee!r}")
            elif op == OpCode.RETURN:
                self._call_stack.pop()
                # Return value is top of stack (if any)
            elif op == OpCode.POP:
                self._pop()
            elif op == OpCode.HALT:
                # Dump runtime profiling reports out to disk before closing the stack machine container
                try:
                    profile_dump_route = "config/vm_profile.json" if os.path.exists("config") else "aero_auto_sdk/config/vm_profile.json"
                    with open(profile_dump_route, "w") as pf:
                        json.dump(self._opcode_profile_counts, pf, indent=2)
                except Exception:
                    pass
                return self._stack[-1] if self._stack else None
            else:
                raise VMError(f"unknown opcode: {op}")

        # Dump runtime profiling reports out to disk before closing the stack machine container
                try:
                    profile_dump_route = "config/vm_profile.json" if os.path.exists("config") else "aero_auto_sdk/config/vm_profile.json"
                    with open(profile_dump_route, "w") as pf:
                        json.dump(self._opcode_profile_counts, pf, indent=2)
                except Exception:
                    pass
                return self._stack[-1] if self._stack else None

    def _push(self, value: Any) -> None:
        if len(self._stack) >= self.MAX_STACK_SIZE:
            raise VMError("stack overflow")
        self._stack.append(value)

    def _pop(self) -> Any:
        if not self._stack:
            raise VMError("stack underflow")
        return self._stack.pop()

    # ── Builtins ─────────────────────────────────────────────────────────

    def _builtin_print(self, args: List[Any]) -> None:
        text = " ".join(str(a) for a in args)
        self._output.append(text)
        return None

    def _builtin_len(self, args: List[Any]) -> int:
        if len(args) != 1:
            raise VMError("len() takes exactly 1 argument")
        return len(args[0])

    def _builtin_int(self, args: List[Any]) -> int:
        if len(args) != 1:
            raise VMError("int() takes exactly 1 argument")
        return int(args[0])

    # ── Native FFI Primitives (system call bridge) ────────────────────────

    def register_native(self, name: str, func: Callable) -> None:
        """Register a host-side callable so Aero scripts can invoke it by name."""
        self.native_functions[name] = func

    def _native_print(self, args: List[Any]) -> None:
        """Output build statuses cleanly to the console."""
        text = " ".join(str(a) for a in args)
        self._output.append(text)
        print(text)
        return None

    def _native_create_dir(self, args: List[Any]) -> int:
        """Programmatically create a new project directory folder."""
        if len(args) != 1:
            raise VMError("create_dir() takes exactly 1 argument")
        path = str(args[0])
        os.makedirs(path, exist_ok=True)
        return 0

    def _native_write_file(self, args: List[Any]) -> int:
        """Write a code file string or compiled binary payload out to disk."""
        if len(args) != 2:
            raise VMError("write_file() takes exactly 2 arguments")
        path, content = str(args[0]), str(args[1])
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return 0

    def _native_read_file(self, args: List[Any]) -> str:
        """Read a local script file's contents into a string block."""
        if len(args) != 1:
            raise VMError("read_file() takes exactly 1 argument")
        path = str(args[0])
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _native_get_timestamp(self, args: List[Any]) -> int:
        """Return the current wall-clock time in integer milliseconds.

        Aero scripts subtract two timestamps to measure execution durations
        down to the millisecond, e.g.::

            let t0 = get_timestamp();
            // ... work ...
            let elapsed_ms = get_timestamp() - t0;
        """
        if args:
            raise VMError("get_timestamp() takes no arguments")
        return int(time.time() * 1000)

    # ── Compiler Pipeline Natives ─────────────────────────────────────────

    def _native_compile_source(self, args: List[Any]) -> CompiledProgram:
        """Compile an Aero source string through lexer → parser → codegen."""
        if len(args) != 1:
            raise VMError("compile_source() takes exactly 1 argument")
        source = str(args[0])
        from aero_sdk.compiler.lexer import tokenize
        from aero_sdk.compiler.parser import Parser
        from aero_sdk.compiler.codegen import Codegen
        tokens = tokenize(source)
        ast = Parser(tokens).parse()
        return Codegen().compile(ast)

    def _native_save_binary(self, args: List[Any]) -> int:
        """Serialize a CompiledProgram to a wrapped .aeroc binary on disk."""
        if len(args) != 2:
            raise VMError("save_binary() takes exactly 2 arguments")
        path, bytecode_obj = str(args[0]), args[1]
        if not isinstance(bytecode_obj, CompiledProgram):
            raise VMError(
                f"save_binary() arg 2 must be a CompiledProgram, got {type(bytecode_obj).__name__}"
            )
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = _serialize_program(bytecode_obj)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return 0


# ── Serialization helpers ─────────────────────────────────────────────────

def _serialize_instruction(instr: tuple) -> list:
    """Convert a bytecode instruction tuple to a JSON-safe list."""
    out: List[Any] = []
    for item in instr:
        if isinstance(item, OpCode):
            out.append(item.name)
        else:
            out.append(item)
    return out


def _serialize_program(prog: CompiledProgram) -> dict:
    """Convert a CompiledProgram to a JSON-serializable dict."""
    return {
        "format": "aeroc",
        "version": 1,
        "main_code": [_serialize_instruction(i) for i in prog.main_code],
        "functions": [
            {
                "name": fn.name,
                "params": list(fn.params),
                "code": [_serialize_instruction(i) for i in fn.code],
            }
            for fn in prog.functions
        ],
        "constants": list(prog.constants),
    }
