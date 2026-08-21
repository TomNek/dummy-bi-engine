from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional


class AstNode:
    pass


@dataclass(frozen=True)
class LiteralNode(AstNode):
    value: Any


@dataclass(frozen=True)
class ColumnRefNode(AstNode):
    table: str
    column: str


@dataclass(frozen=True)
class MeasureRefNode(AstNode):
    name: str


@dataclass(frozen=True)
class FuncCallNode(AstNode):
    name: str
    args: List[AstNode]


@dataclass(frozen=True)
class UnaryOpNode(AstNode):
    op: str
    expr: AstNode


@dataclass(frozen=True)
class BinaryOpNode(AstNode):
    op: str
    left: AstNode
    right: AstNode


@dataclass(frozen=True)
class ParenNode(AstNode):
    inner: AstNode


@dataclass(frozen=True)
class SetLiteralNode(AstNode):
    values: List[LiteralNode]


@dataclass(frozen=True)
class VarRefNode(AstNode):
    name: str


@dataclass(frozen=True)
class LetNode(AstNode):
    bindings: List[tuple[str, AstNode]]
    body: AstNode
