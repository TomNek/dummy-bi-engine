from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


_OPERATORS = {
    "&&",
    "||",
    "<=",
    ">=",
    "<>",
    "=",
    "<",
    ">",
    "+",
    "-",
    "*",
    "/",
    "&",
}

_SINGLE = {
    "(": "LPAREN",
    ")": "RPAREN",
    ",": "COMMA",
    "{": "LBRACE",
    "}": "RBRACE",
}


def tokenize(text: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    n = len(text)

    def peek(k: int = 0) -> str:
        j = i + k
        return text[j] if 0 <= j < n else ""

    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue

        # Line comment: -- ... (to end of line)
        if text[i : i + 2] == "--":
            i += 2
            while i < n and text[i] not in {"\n", "\r"}:
                i += 1
            continue

        # Block comment: /* ... */
        if text[i : i + 2] == "/*":
            start = i
            i += 2
            closed = False
            while i < n:
                if text[i : i + 2] == "*/":
                    i += 2
                    closed = True
                    break
                i += 1
            if not closed:
                raise ValueError(f"Unterminated block comment at {start}")
            continue

        # String literal: "..." with "" escape
        if ch == '"':
            start = i
            i += 1
            out: List[str] = []
            while i < n:
                c = text[i]
                if c == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        out.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                out.append(c)
                i += 1
            else:
                raise ValueError(f"Unterminated string literal at {start}")
            tokens.append(Token("STRING", "".join(out), start))
            continue

        # Quoted identifier: 'Table Name'
        if ch == "'":
            start = i
            i += 1
            out: List[str] = []
            while i < n:
                c = text[i]
                if c == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        out.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                out.append(c)
                i += 1
            else:
                raise ValueError(f"Unterminated quoted identifier at {start}")
            tokens.append(Token("QUOTED_IDENT", "".join(out).strip(), start))
            continue

        # Bracketed name: [ ... ]
        if ch == "[":
            start = i
            i += 1
            out: List[str] = []
            while i < n:
                c = text[i]
                if c == "]":
                    i += 1
                    break
                out.append(c)
                i += 1
            else:
                raise ValueError(f"Unterminated bracket name at {start}")
            tokens.append(Token("BRACKET", "".join(out).strip(), start))
            continue

        # Number
        if ch.isdigit() or (ch == "." and peek(1).isdigit()):
            start = i
            has_dot = False
            if ch == ".":
                has_dot = True
                i += 1
            while i < n and text[i].isdigit():
                i += 1
            if i < n and text[i] == ".":
                has_dot = True
                i += 1
                while i < n and text[i].isdigit():
                    i += 1
            # Exponent
            if i < n and text[i] in {"e", "E"}:
                j = i + 1
                if j < n and text[j] in {"+", "-"}:
                    j += 1
                if j < n and text[j].isdigit():
                    i = j + 1
                    while i < n and text[i].isdigit():
                        i += 1
            tokens.append(Token("NUMBER", text[start:i], start))
            continue

        # Ident (including dot for IF.EAGER)
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] in {"_", "."}):
                i += 1
            ident = text[start:i]
            upper = ident.upper()
            # Treat IN as an operator for precedence parsing
            if upper == "IN":
                tokens.append(Token("OP", upper, start))
            else:
                tokens.append(Token("IDENT", ident, start))
            continue

        # Operators (2-char first)
        two = text[i : i + 2]
        if two in _OPERATORS:
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        if ch in _OPERATORS:
            tokens.append(Token("OP", ch, i))
            i += 1
            continue

        # Punctuation
        if ch in _SINGLE:
            tokens.append(Token(_SINGLE[ch], ch, i))
            i += 1
            continue

        raise ValueError(f"Unexpected character {ch!r} at {i}")

    tokens.append(Token("EOF", "", n))
    return tokens
