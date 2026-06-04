"""
Aero Parser — Token Stream → AST
================================

Recursive-descent parser with precedence-climbing expressions. Consumes the
``Token`` list produced by ``compiler.lexer.tokenize`` and produces a ``Program``
of statement nodes that ``compiler.codegen`` lowers to bytecode.

Public contract (do not rename): ``Parser``, ``ParseError``, ``Program``,
``LetStmt``, ``FnDecl`` (plus the remaining node types used by codegen).
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional

from aero_sdk.compiler.lexer import TokenType


class ParseError(Exception):
    """Raised when the token stream does not match the Aero grammar."""


# ── AST node types ────────────────────────────────────────────────────────────

@dataclass
class Program:
    statements: List[Any] = field(default_factory=list)


@dataclass
class LetStmt:
    name: str
    value: Any


@dataclass
class FnDecl:
    name: str
    params: List[str]
    body: List[Any]


@dataclass
class IfStmt:
    condition: Any
    then_branch: List[Any]
    else_branch: Optional[List[Any]] = None


@dataclass
class WhileStmt:
    condition: Any
    body: List[Any]


@dataclass
class ReturnStmt:
    value: Optional[Any] = None


@dataclass
class ExprStmt:
    expr: Any


@dataclass
class Binary:
    op: str
    left: Any
    right: Any


@dataclass
class Unary:
    op: str
    operand: Any


@dataclass
class IntLiteral:
    value: int


@dataclass
class FloatLiteral:
    value: float


@dataclass
class StringLiteral:
    value: str


@dataclass
class BoolLiteral:
    value: bool


@dataclass
class Identifier:
    name: str


@dataclass
class Call:
    callee: str
    args: List[Any]


# ── Parser ────────────────────────────────────────────────────────────────────

class Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0

    # -- token cursor helpers --

    def _peek(self):
        return self.tokens[self.pos]

    def _at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _advance(self):
        tok = self.tokens[self.pos]
        if not self._at_end():
            self.pos += 1
        return tok

    def _check(self, type_, value=None) -> bool:
        tok = self._peek()
        if tok.type != type_:
            return False
        return value is None or tok.value == value

    def _match(self, type_, value=None):
        if self._check(type_, value):
            return self._advance()
        return None

    def _expect(self, type_, value=None):
        if self._check(type_, value):
            return self._advance()
        tok = self._peek()
        want = value if value is not None else type_.name
        raise ParseError(
            f"expected {want!r} but got {tok.value!r} ({tok.type.name}) at line {tok.line}"
        )

    # -- entry point --

    def parse(self) -> Program:
        statements = []
        while not self._at_end():
            statements.append(self._statement())
        return Program(statements)

    # -- statements --

    def _block(self) -> List[Any]:
        self._expect(TokenType.PUNCTUATION, "{")
        stmts = []
        while not self._check(TokenType.PUNCTUATION, "}") and not self._at_end():
            stmts.append(self._statement())
        self._expect(TokenType.PUNCTUATION, "}")
        return stmts

    def _statement(self):
        if self._check(TokenType.KEYWORD, "let"):
            return self._let_stmt()
        if self._check(TokenType.KEYWORD, "fn"):
            return self._fn_decl()
        if self._check(TokenType.KEYWORD, "if"):
            return self._if_stmt()
        if self._check(TokenType.KEYWORD, "while"):
            return self._while_stmt()
        if self._check(TokenType.KEYWORD, "return"):
            return self._return_stmt()
        expr = self._expression()
        self._expect(TokenType.PUNCTUATION, ";")
        return ExprStmt(expr)

    def _let_stmt(self) -> LetStmt:
        self._expect(TokenType.KEYWORD, "let")
        name = self._expect(TokenType.IDENTIFIER).value
        self._expect(TokenType.OPERATOR, "=")
        value = self._expression()
        self._expect(TokenType.PUNCTUATION, ";")
        return LetStmt(name, value)

    def _fn_decl(self) -> FnDecl:
        self._expect(TokenType.KEYWORD, "fn")
        name = self._expect(TokenType.IDENTIFIER).value
        self._expect(TokenType.PUNCTUATION, "(")
        params: List[str] = []
        if not self._check(TokenType.PUNCTUATION, ")"):
            params.append(self._expect(TokenType.IDENTIFIER).value)
            while self._match(TokenType.PUNCTUATION, ","):
                params.append(self._expect(TokenType.IDENTIFIER).value)
        self._expect(TokenType.PUNCTUATION, ")")
        body = self._block()
        return FnDecl(name, params, body)

    def _if_stmt(self) -> IfStmt:
        self._expect(TokenType.KEYWORD, "if")
        condition = self._expression()
        then_branch = self._block()
        else_branch = None
        if self._match(TokenType.KEYWORD, "else"):
            else_branch = self._block()
        return IfStmt(condition, then_branch, else_branch)

    def _while_stmt(self) -> WhileStmt:
        self._expect(TokenType.KEYWORD, "while")
        condition = self._expression()
        body = self._block()
        return WhileStmt(condition, body)

    def _return_stmt(self) -> ReturnStmt:
        self._expect(TokenType.KEYWORD, "return")
        value = None
        if not self._check(TokenType.PUNCTUATION, ";"):
            value = self._expression()
        self._expect(TokenType.PUNCTUATION, ";")
        return ReturnStmt(value)

    # -- expressions (precedence climbing, lowest to highest) --

    def _expression(self):
        return self._logic_or()

    def _binary_level(self, next_level, operators):
        left = next_level()
        while any(self._check(TokenType.OPERATOR, op) for op in operators):
            op = self._advance().value
            right = next_level()
            left = Binary(op, left, right)
        return left

    def _logic_or(self):
        return self._binary_level(self._logic_and, ("||",))

    def _logic_and(self):
        return self._binary_level(self._equality, ("&&",))

    def _equality(self):
        return self._binary_level(self._comparison, ("==", "!="))

    def _comparison(self):
        return self._binary_level(self._term, ("<", ">", "<=", ">="))

    def _term(self):
        return self._binary_level(self._factor, ("+", "-"))

    def _factor(self):
        return self._binary_level(self._unary, ("*", "/", "%"))

    def _unary(self):
        if self._check(TokenType.OPERATOR, "!") or self._check(TokenType.OPERATOR, "-"):
            op = self._advance().value
            return Unary(op, self._unary())
        return self._primary()

    def _primary(self):
        tok = self._peek()

        if tok.type == TokenType.INT_LITERAL:
            self._advance()
            return IntLiteral(int(tok.value))
        if tok.type == TokenType.FLOAT_LITERAL:
            self._advance()
            return FloatLiteral(float(tok.value))
        if tok.type == TokenType.STRING_LITERAL:
            self._advance()
            return StringLiteral(tok.value)
        if tok.type == TokenType.BOOL_LITERAL:
            self._advance()
            return BoolLiteral(tok.value == "true")
        if tok.type == TokenType.IDENTIFIER:
            self._advance()
            if self._check(TokenType.PUNCTUATION, "("):
                return self._finish_call(tok.value)
            return Identifier(tok.value)
        if self._match(TokenType.PUNCTUATION, "("):
            expr = self._expression()
            self._expect(TokenType.PUNCTUATION, ")")
            return expr

        raise ParseError(
            f"unexpected token {tok.value!r} ({tok.type.name}) at line {tok.line}"
        )

    def _finish_call(self, callee: str) -> Call:
        self._expect(TokenType.PUNCTUATION, "(")
        args: List[Any] = []
        if not self._check(TokenType.PUNCTUATION, ")"):
            args.append(self._expression())
            while self._match(TokenType.PUNCTUATION, ","):
                args.append(self._expression())
        self._expect(TokenType.PUNCTUATION, ")")
        return Call(callee, args)
