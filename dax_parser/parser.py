from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .ast import (
    AstNode,
    BinaryOpNode,
    ColumnRefNode,
    FuncCallNode,
    LiteralNode,
    MeasureRefNode,
    ParenNode,
    UnaryOpNode,
    SetLiteralNode,
    VarRefNode,
    LetNode,
)
from .tokenizer import Token, tokenize


_PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "IN": 3,
    "=": 3,
    "<>": 3,
    "<": 3,
    "<=": 3,
    ">": 3,
    ">=": 3,
    "+": 4,
    "-": 4,
    "&": 4,
    "*": 5,
    "/": 5,
}


class DaxExpressionParser:
    def __init__(self, text: str):
        self.text = text
        self.tokens: List[Token] = tokenize(text)
        self.i = 0

    def _cur(self) -> Token:
        return self.tokens[self.i]

    def _eat(self, kind: str, value: Optional[str] = None) -> Token:
        tok = self._cur()
        if tok.kind != kind:
            raise ValueError(f"Expected {kind} at {tok.pos}, got {tok.kind}")
        if value is not None and tok.value.upper() != value.upper():
            raise ValueError(f"Expected {value} at {tok.pos}, got {tok.value}")
        self.i += 1
        return tok

    def _match(self, kind: str, value: Optional[str] = None) -> bool:
        tok = self._cur()
        if tok.kind != kind:
            return False
        if value is not None and tok.value.upper() != value.upper():
            return False
        return True

    def parse(self) -> AstNode:
        # Support VAR ... RETURN ... blocks
        if self._match("IDENT") and self._cur().value.upper() == "VAR":
            return self._parse_let()
        expr = self._parse_expr(0)
        if not self._match("EOF"):
            tok = self._cur()
            raise ValueError(f"Unexpected token {tok.kind}:{tok.value} at {tok.pos}")
        return expr

    def _parse_let(self) -> AstNode:
        bindings: List[tuple[str, AstNode]] = []
        while self._match("IDENT") and self._cur().value.upper() == "VAR":
            self.i += 1
            name_tok = self._eat("IDENT")
            self._eat("OP", "=")
            value_expr = self._parse_expr(0)
            bindings.append((name_tok.value, value_expr))
        if not (self._match("IDENT") and self._cur().value.upper() == "RETURN"):
            tok = self._cur()
            raise ValueError(f"Expected RETURN after VAR bindings at {tok.pos}")
        self.i += 1
        body = self._parse_expr(0)
        if not self._match("EOF"):
            tok = self._cur()
            raise ValueError(f"Unexpected token {tok.kind}:{tok.value} at {tok.pos}")
        return LetNode(bindings=bindings, body=body)

    def _parse_expr(self, min_prec: int) -> AstNode:
        left = self._parse_prefix()

        while True:
            tok = self._cur()
            if tok.kind != "OP":
                break
            op = tok.value
            prec = _PRECEDENCE.get(op)
            if prec is None or prec < min_prec:
                break
            # left-associative
            self.i += 1
            right = self._parse_expr(prec + 1)
            left = BinaryOpNode(op=op, left=left, right=right)

        return left

    def _parse_prefix(self) -> AstNode:
        tok = self._cur()

        # Set literal { ... }
        if tok.kind == "LBRACE":
            self.i += 1
            values: List[AstNode] = []
            if not self._match("RBRACE"):
                while True:
                    v = self._parse_expr(0)
                    if not isinstance(v, (LiteralNode, SetLiteralNode)):
                        raise ValueError("Set literals must contain only literal values or nested set literals")
                    values.append(v)
                    if self._match("COMMA"):
                        self.i += 1
                        continue
                    break
            self._eat("RBRACE")
            return SetLiteralNode(values=values)

        # Unary operators
        if tok.kind == "OP" and tok.value == "-":
            self.i += 1
            expr = self._parse_expr(6)
            return UnaryOpNode(op="-", expr=expr)

        if tok.kind == "IDENT" and tok.value.upper() == "NOT":
            self.i += 1
            expr = self._parse_expr(6)
            return UnaryOpNode(op="NOT", expr=expr)

        if tok.kind == "NUMBER":
            self.i += 1
            raw = tok.value
            if any(c in raw for c in (".", "e", "E")):
                return LiteralNode(float(raw))
            return LiteralNode(int(raw))

        if tok.kind == "STRING":
            self.i += 1
            return LiteralNode(tok.value)

        if tok.kind == "LPAREN":
            self.i += 1
            inner = self._parse_expr(0)
            self._eat("RPAREN")
            return ParenNode(inner=inner)

        if tok.kind == "QUOTED_IDENT":
            # 'Table Name'[Column Name]  OR  standalone 'Table Name'
            # Power BI always single-quotes table names in DAX expressions.
            self.i += 1
            table = tok.value
            if self._match("BRACKET"):
                col = self._eat("BRACKET").value
                return ColumnRefNode(table=table, column=col)
            # Standalone quoted table ref: ALL('Product'), COUNTROWS('Date')
            return VarRefNode(name=table)

        if tok.kind == "BRACKET":
            self.i += 1
            name = tok.value
            if not name:
                raise ValueError(f"Empty measure name at {tok.pos}")
            return MeasureRefNode(name=name)

        if tok.kind == "IDENT":
            ident = tok.value
            self.i += 1

            # Table[Column]
            if self._match("BRACKET"):
                col = self._eat("BRACKET").value
                if not col:
                    raise ValueError(f"Empty column name at {tok.pos}")
                return ColumnRefNode(table=ident, column=col)

            # Function call
            if self._match("LPAREN"):
                self.i += 1
                args: List[AstNode] = []
                if not self._match("RPAREN"):
                    while True:
                        args.append(self._parse_expr(0))
                        if self._match("COMMA"):
                            self.i += 1
                            continue
                        break
                self._eat("RPAREN")
                # TRUE()/FALSE()/BLANK() → literal nodes
                name_up = ident.upper()
                if name_up in {"TRUE", "FALSE", "BLANK"} and not args:
                    if name_up == "TRUE":
                        return LiteralNode(True)
                    if name_up == "FALSE":
                        return LiteralNode(False)
                    return LiteralNode(None)
                return FuncCallNode(name=ident, args=args)

            # Bare identifiers → variable reference (VAR/RETURN)
            return VarRefNode(name=ident)

        raise ValueError(f"Unexpected token {tok.kind}:{tok.value} at {tok.pos}")


def parse_expression(text: str) -> AstNode:
    return DaxExpressionParser(text).parse()
