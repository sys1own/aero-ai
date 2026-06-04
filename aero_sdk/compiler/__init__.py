"""
Aero Language Compiler
======================

A minimalist compiler pipeline for the Aero stack-based VM language.

Stages:
    1. Lexer   — tokenizes Aero source into a stream of typed tokens
    2. Parser  — builds an AST from the token stream
    3. Codegen — emits Aero VM bytecode from the AST
"""

__version__ = "0.1.0"
