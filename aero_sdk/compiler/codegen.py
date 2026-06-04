"""
Aero Codegen — AST → Stack Bytecode
===================================

Lowers the parser's AST into the flat instruction format executed by
``vm.machine.AeroVM``. Each instruction is a tuple ``(OpCode, *args)``:

    PUSH_INT v        immediate int
    PUSH_BOOL 0|1     immediate bool
    PUSH_FLOAT idx    constant-pool index (float)
    PUSH_STRING idx   constant-pool index (string / callee name)
    LOAD slot         read local variable slot
    STORE slot        pop -> local variable slot
    JUMP target       set pc
    JUMP_IF_FALSE t   pop; if falsey set pc
    CALL argc         pop callee name, then argc args
    ADD/SUB/.../NOT   pop operand(s), push result
    POP / RETURN / HALT

Public contract (do not rename): ``Codegen``, ``OpCode``, ``CompiledProgram``,
``CompiledFunction`` (the VM imports the latter three).
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, List

from aero_sdk.compiler.parser import (
    Program, LetStmt, FnDecl, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    Binary, Unary, IntLiteral, FloatLiteral, StringLiteral, BoolLiteral,
    Identifier, Call,
)


class OpCode(Enum):
    PUSH_INT = auto()
    PUSH_FLOAT = auto()
    PUSH_STRING = auto()
    PUSH_BOOL = auto()
    LOAD = auto()
    STORE = auto()
    ADD = auto()
    SUB = auto()
    MUL = auto()
    DIV = auto()
    MOD = auto()
    EQ = auto()
    NEQ = auto()
    LT = auto()
    GT = auto()
    LTE = auto()
    GTE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    NEG = auto()
    JUMP = auto()
    JUMP_IF_FALSE = auto()
    CALL = auto()
    RETURN = auto()
    POP = auto()
    HALT = auto()
    # --- OPTIMIZED MACRO OPCODES ---
    CALL_DIRECT = auto()


_BINARY_OPS = {
    "+": OpCode.ADD, "-": OpCode.SUB, "*": OpCode.MUL, "/": OpCode.DIV,
    "%": OpCode.MOD, "==": OpCode.EQ, "!=": OpCode.NEQ, "<": OpCode.LT,
    ">": OpCode.GT, "<=": OpCode.LTE, ">=": OpCode.GTE, "&&": OpCode.AND,
    "||": OpCode.OR,
}


@dataclass
class CompiledFunction:
    name: str
    params: List[str]
    code: List[Any]


@dataclass
class CompiledProgram:
    main_code: List[Any]
    functions: List[CompiledFunction] = field(default_factory=list)
    constants: List[Any] = field(default_factory=list)


class CodegenError(Exception):
    """Raised when the AST cannot be lowered (e.g. an undefined variable)."""


class _Scope:
    """Maps local variable names to stack slots within one frame."""

    def __init__(self):
        self._slots = {}

    def define(self, name: str) -> int:
        if name not in self._slots:
            self._slots[name] = len(self._slots)
        return self._slots[name]

    def resolve(self, name: str):
        return self._slots.get(name)


class Codegen:
    def __init__(self):
        self.constants: List[Any] = []
        self.functions: List[CompiledFunction] = []

    # -- constant pool --

    def _const(self, value: Any) -> int:
        for idx, existing in enumerate(self.constants):
            if type(existing) is type(value) and existing == value:
                return idx
        self.constants.append(value)
        return len(self.constants) - 1

    # -- entry point --

    def compile(self, program: Program) -> CompiledProgram:
        main_code: List[Any] = []
        main_scope = _Scope()
        for stmt in program.statements:
            if isinstance(stmt, FnDecl):
                self._compile_function(stmt)
            else:
                self._compile_statement(stmt, main_code, main_scope)
        main_code.append((OpCode.HALT,))
        return CompiledProgram(
            main_code=main_code, functions=self.functions, constants=self.constants
        )

    def _compile_function(self, fn: FnDecl) -> None:
        scope = _Scope()
        for param in fn.params:
            scope.define(param)
        code: List[Any] = []
        for stmt in fn.body:
            self._compile_statement(stmt, code, scope)
        # Guarantee every path leaves exactly one value and returns.
        code.append((OpCode.PUSH_INT, 0))
        code.append((OpCode.RETURN,))
        self.functions.append(CompiledFunction(fn.name, list(fn.params), code))

    # -- statements --

    def _compile_statement(self, stmt, code: List[Any], scope: _Scope) -> None:
        if isinstance(stmt, LetStmt):
            self._compile_expr(stmt.value, code, scope)
            code.append((OpCode.STORE, scope.define(stmt.name)))

        elif isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._compile_expr(stmt.value, code, scope)
            else:
                code.append((OpCode.PUSH_INT, 0))
            code.append((OpCode.RETURN,))

        elif isinstance(stmt, IfStmt):
            self._compile_expr(stmt.condition, code, scope)
            jump_if_false = len(code)
            code.append((OpCode.JUMP_IF_FALSE, None))
            for inner in stmt.then_branch:
                self._compile_statement(inner, code, scope)
            if stmt.else_branch is not None:
                jump_end = len(code)
                code.append((OpCode.JUMP, None))
                code[jump_if_false] = (OpCode.JUMP_IF_FALSE, len(code))
                for inner in stmt.else_branch:
                    self._compile_statement(inner, code, scope)
                code[jump_end] = (OpCode.JUMP, len(code))
            else:
                code[jump_if_false] = (OpCode.JUMP_IF_FALSE, len(code))

        elif isinstance(stmt, WhileStmt):
            loop_start = len(code)
            self._compile_expr(stmt.condition, code, scope)
            jump_if_false = len(code)
            code.append((OpCode.JUMP_IF_FALSE, None))
            for inner in stmt.body:
                self._compile_statement(inner, code, scope)
            code.append((OpCode.JUMP, loop_start))
            code[jump_if_false] = (OpCode.JUMP_IF_FALSE, len(code))

        elif isinstance(stmt, ExprStmt):
            self._compile_expr(stmt.expr, code, scope)
            code.append((OpCode.POP,))

        elif isinstance(stmt, FnDecl):
            # Nested declaration: register globally; emit nothing here.
            self._compile_function(stmt)

        else:
            raise CodegenError(f"cannot compile statement: {stmt!r}")

    # -- expressions --

    def _compile_expr(self, expr, code: List[Any], scope: _Scope) -> None:
        if isinstance(expr, IntLiteral):
            code.append((OpCode.PUSH_INT, expr.value))

        elif isinstance(expr, FloatLiteral):
            code.append((OpCode.PUSH_FLOAT, self._const(expr.value)))

        elif isinstance(expr, StringLiteral):
            code.append((OpCode.PUSH_STRING, self._const(expr.value)))

        elif isinstance(expr, BoolLiteral):
            code.append((OpCode.PUSH_BOOL, 1 if expr.value else 0))

        elif isinstance(expr, Identifier):
            slot = scope.resolve(expr.name)
            if slot is None:
                raise CodegenError(f"undefined variable '{expr.name}'")
            code.append((OpCode.LOAD, slot))

        elif isinstance(expr, Binary):
            op = _BINARY_OPS.get(expr.op)
            if op is None:
                raise CodegenError(f"unknown binary operator '{expr.op}'")
            self._compile_expr(expr.left, code, scope)
            self._compile_expr(expr.right, code, scope)
            code.append((op,))

        elif isinstance(expr, Unary):
            self._compile_expr(expr.operand, code, scope)
            if expr.op == "-":
                code.append((OpCode.NEG,))
            elif expr.op == "!":
                code.append((OpCode.NOT,))
            else:
                raise CodegenError(f"unknown unary operator '{expr.op}'")

        elif isinstance(expr, Call):
            # Push args first, then the callee name (popped first by the VM).
            for arg in expr.args:
                self._compile_expr(arg, code, scope)
            code.append((OpCode.PUSH_STRING, self._const(expr.callee)))
            if expr.callee in ("print", "create_dir", "write_file", "read_file", "compile_source", "save_binary", "get_timestamp"):
                code.append((OpCode.CALL_DIRECT, len(expr.args)))
            else:
                code.append((OpCode.CALL, len(expr.args)))

        else:
            raise CodegenError(f"cannot compile expression: {expr!r}")
