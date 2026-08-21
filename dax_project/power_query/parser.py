from __future__ import annotations

import re
from typing import Iterable, Optional

from .model import MDiagnostic, MStep


_FUNCTION_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\s*\(")
_HASH_FUNCTION_RE = re.compile(r"\B(#(?:table|date|datetime|datetimezone|duration|time))\s*\(", re.IGNORECASE)


def _blank_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if ch == '"' and nxt == '"':
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            out.extend("  ")
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            out.extend("  ")
            i += 2
            while i < len(text):
                if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                    out.extend("  ")
                    i += 2
                    break
                out.append("\n" if text[i] in "\r\n" else " ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _blank_comments_and_string_contents(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                out.extend("  ")
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append('"')
            else:
                out.append(" ")
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append('"')
            i += 1
            continue
        if ch == "/" and nxt == "/":
            out.extend("  ")
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and nxt == "*":
            out.extend("  ")
            i += 2
            while i < len(text):
                if text[i] == "*" and i + 1 < len(text) and text[i + 1] == "/":
                    out.extend("  ")
                    i += 2
                    break
                out.append("\n" if text[i] in "\r\n" else " ")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _keyword_positions(text: str, keyword: str) -> list[int]:
    clean = _blank_comments(text)
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])", re.IGNORECASE)
    return [m.start() for m in pattern.finditer(clean)]


def _split_top_level(text: str, delimiter: str = ",") -> list[tuple[str, int, int]]:
    parts: list[tuple[str, int, int]] = []
    start = 0
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        elif ch == delimiter and depth == 0:
            parts.append((text[start:i].strip(), start, i))
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        parts.append((tail, start, len(text)))
    return parts


def _split_binding(text: str) -> Optional[tuple[str, str]]:
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        elif ch == "=" and depth == 0:
            return text[:i].strip(), text[i + 1 :].strip()
        i += 1
    return None


def _top_level_equals_index(text: str) -> int | None:
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        elif ch == "=" and depth == 0:
            return i
        i += 1
    return None


def _top_level_keyword_index(text: str, keyword: str) -> int | None:
    clean = _blank_comments(text)
    depth = 0
    in_string = False
    i = 0
    needle = keyword.lower()
    while i < len(clean):
        ch = clean[i]
        nxt = clean[i + 1] if i + 1 < len(clean) else ""
        if in_string:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        elif depth == 0 and clean[i : i + len(needle)].lower() == needle:
            before = clean[i - 1] if i > 0 else ""
            after = clean[i + len(needle)] if i + len(needle) < len(clean) else ""
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return None


def _normalize_identifier(raw: str) -> str:
    val = raw.strip()
    if val.startswith('#"') and val.endswith('"'):
        return val[2:-1].replace('""', '"')
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    return val


def _functions_in_expression(expression: str) -> list[str]:
    clean = _blank_comments_and_string_contents(expression)
    names = {m.group(1) for m in _FUNCTION_RE.finditer(clean)}
    names.update(m.group(1).lower() for m in _HASH_FUNCTION_RE.finditer(clean))
    return sorted(names, key=str.upper)


def _first_function_in_expression(expression: str) -> Optional[str]:
    clean = _blank_comments_and_string_contents(expression)
    candidates: list[tuple[int, str]] = []
    candidates.extend((m.start(), m.group(1)) for m in _FUNCTION_RE.finditer(clean))
    candidates.extend((m.start(), m.group(1).lower()) for m in _HASH_FUNCTION_RE.finditer(clean))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _operation_for_expression(expression: str) -> str:
    first_func = _first_function_in_expression(expression)
    if first_func:
        return first_func
    if re.search(r"\{\s*\[", expression):
        return "Navigation"
    if expression.strip().startswith("["):
        return "Record"
    if expression.strip().startswith("{"):
        return "List"
    return "Expression"


def _dependencies_for_expression(expression: str, prior_step_ids: Iterable[str]) -> list[str]:
    deps: list[str] = []
    for step_id in prior_step_ids:
        quoted = '#"' + step_id.replace('"', '""') + '"'
        if quoted in expression or re.search(rf"(?<![A-Za-z0-9_]){re.escape(step_id)}(?![A-Za-z0-9_])", expression):
            deps.append(step_id)
    return deps


def _line_col(text: str, offset: int) -> tuple[int, int]:
    prefix = text[: max(0, offset)]
    line = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    column = offset + 1 if last_newline < 0 else offset - last_newline
    return line, column


def parse_m_query(raw_m: str) -> tuple[list[MStep], Optional[str], list[str], list[MDiagnostic]]:
    """Parse a conservative Power Query M step inventory.

    This is not a full M parser. It is a lossless inventory parser used until
    PQ-02 integrates a complete spec parser. It deliberately returns diagnostics
    instead of dropping raw M when the expression is too complex.
    """

    diagnostics: list[MDiagnostic] = []
    text = raw_m or ""
    if not text.strip():
        return [], None, [], [MDiagnostic("warning", "Power Query M expression is empty.", code="PQ_EMPTY")]

    lets = _keyword_positions(text, "let")
    ins = _keyword_positions(text, "in")
    if not lets or not ins or ins[-1] <= lets[0]:
        funcs = _functions_in_expression(text)
        diagnostics.append(
            MDiagnostic(
                "warning",
                "M expression does not use a parseable top-level let/in block; preserving as a single expression.",
                code="PQ_NO_LET_IN",
            )
        )
        return [
            MStep(
                id="Expression",
                expression=text.strip(),
                operation=_operation_for_expression(text),
                functions=funcs,
                compatibility_level="C1",
                source_span={"start": 0, "end": len(text)},
            )
        ], None, funcs, diagnostics

    let_start = lets[0] + 3
    in_start = ins[-1]
    body = text[let_start:in_start]
    result_expression = text[in_start + 2 :].strip()
    steps: list[MStep] = []
    all_functions: set[str] = set()
    prior_ids: list[str] = []

    for binding_text, rel_start, rel_end in _split_top_level(body):
        binding = _split_binding(binding_text)
        abs_start = let_start + rel_start
        abs_end = let_start + rel_end
        if binding is None:
            line, col = _line_col(text, abs_start)
            diagnostics.append(
                MDiagnostic(
                    "warning",
                    "Could not split M binding into name and expression.",
                    code="PQ_BINDING_PARSE",
                    line=line,
                    column=col,
                )
            )
            continue
        raw_name, expression = binding
        step_id = _normalize_identifier(raw_name)
        funcs = _functions_in_expression(expression)
        all_functions.update(funcs)
        deps = _dependencies_for_expression(expression, prior_ids)
        steps.append(
            MStep(
                id=step_id,
                expression=expression,
                operation=_operation_for_expression(expression),
                dependencies=deps,
                functions=funcs,
                compatibility_level="C1",
                source_span={"start": abs_start, "end": abs_end},
            )
        )
        prior_ids.append(step_id)

    all_functions.update(_functions_in_expression(result_expression))
    if not steps:
        diagnostics.append(MDiagnostic("warning", "No M steps were detected.", code="PQ_NO_STEPS"))
    return steps, result_expression or None, sorted(all_functions, key=str.upper), diagnostics


def replace_m_step_expression(raw_m: str, step_id: str, new_expression: str) -> str:
    """Return raw M with one top-level applied-step expression replaced.

    This is a formatting-preserving draft helper for Transform Studio. It only
    patches the expression part of a parsed top-level binding and leaves query
    persistence to the explicit save endpoint.
    """

    target = _normalize_identifier(step_id).strip().upper()
    if not target:
        raise ValueError("step_id is required")
    replacement = (new_expression or "").strip()
    if not replacement:
        raise ValueError("new_expression must be a non-empty M expression")
    steps, _result_expression, _functions, _diagnostics = parse_m_query(raw_m)
    step = next((item for item in steps if item.id.strip().upper() == target), None)
    if step is None:
        raise ValueError(f"Unknown M step: {step_id!r}")
    span = step.source_span or {}
    start = int(span.get("start", -1))
    end = int(span.get("end", -1))
    if start < 0 or end <= start or end > len(raw_m):
        raise ValueError(f"M step {step_id!r} has no editable source span")
    binding_text = raw_m[start:end]
    equals_idx = _top_level_equals_index(binding_text)
    if equals_idx is None:
        raise ValueError(f"M step {step_id!r} has no editable binding expression")
    expr_start = start + equals_idx + 1
    expr_text = raw_m[expr_start:end]
    leading = re.match(r"\s*", expr_text).group(0)
    trailing_match = re.search(r"\s*$", expr_text)
    trailing = trailing_match.group(0) if trailing_match else ""
    return raw_m[:expr_start] + leading + replacement + trailing + raw_m[end:]


def _format_identifier(name: str) -> str:
    ident = _normalize_identifier(str(name or "").strip())
    if not ident:
        raise ValueError("step id must be non-empty")
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", ident) and ident.lower() not in {"let", "in", "each", "as", "meta", "type"}:
        return ident
    return '#"' + ident.replace('"', '""') + '"'


def _replace_identifier_references(expression: str, old_step_id: str, new_step_id: str) -> str:
    old_name = _normalize_identifier(old_step_id)
    new_ident = _format_identifier(new_step_id)
    text = str(expression or "")
    text = text.replace(_format_identifier(old_name), new_ident)
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", old_name):
        text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old_name)}(?![A-Za-z0-9_])", new_ident, text)
    return text


def _canonical_let_query(bindings: list[tuple[str, str]], result_expression: str | None) -> str:
    if not bindings:
        raise ValueError("M query must contain at least one step")
    result = (result_expression or bindings[-1][0]).strip()
    lines = ["let"]
    for idx, (name, expression) in enumerate(bindings):
        comma = "," if idx < len(bindings) - 1 else ""
        lines.append(f"    {_format_identifier(name)} = {str(expression or '').strip()}{comma}")
    lines.append("in")
    lines.append(f"    {result}")
    return "\n".join(lines)


def _parsed_binding_pairs(raw_m: str) -> tuple[list[tuple[str, str]], str | None]:
    steps, result_expression, _functions, _diagnostics = parse_m_query(raw_m)
    if not steps:
        raise ValueError("M query must contain a parseable let/in step list")
    return [(step.id, step.expression) for step in steps], result_expression


def add_m_step_expression(
    raw_m: str,
    step_id: str,
    expression: str,
    *,
    after_step_id: str | None = None,
    make_result: bool = True,
) -> str:
    new_step_id = _normalize_identifier(step_id)
    replacement = (expression or "").strip()
    if not replacement:
        raise ValueError("expression must be a non-empty string")
    bindings, result_expression = _parsed_binding_pairs(raw_m)
    existing = {name.strip().upper() for name, _expr in bindings}
    if new_step_id.strip().upper() in existing:
        raise ValueError(f"M step already exists: {new_step_id!r}")
    insert_at = len(bindings)
    if after_step_id:
        after = _normalize_identifier(after_step_id).strip().upper()
        matches = [idx for idx, (name, _expr) in enumerate(bindings) if name.strip().upper() == after]
        if not matches:
            raise ValueError(f"Unknown M step: {after_step_id!r}")
        insert_at = matches[0] + 1
    bindings.insert(insert_at, (new_step_id, replacement))
    return _canonical_let_query(bindings, _format_identifier(new_step_id) if make_result else result_expression)


def delete_m_step_expression(raw_m: str, step_id: str) -> str:
    target = _normalize_identifier(step_id).strip().upper()
    bindings, result_expression = _parsed_binding_pairs(raw_m)
    index = next((idx for idx, (name, _expr) in enumerate(bindings) if name.strip().upper() == target), None)
    if index is None:
        raise ValueError(f"Unknown M step: {step_id!r}")
    if len(bindings) == 1:
        raise ValueError("Cannot delete the only M step")
    deleted_name = bindings[index][0]
    del bindings[index]
    result = result_expression
    if result and _normalize_identifier(result).strip().upper() == deleted_name.strip().upper():
        result = _format_identifier(bindings[min(index, len(bindings) - 1)][0])
    return _canonical_let_query(bindings, result)


def rename_m_step_expression(raw_m: str, step_id: str, new_step_id: str) -> str:
    target = _normalize_identifier(step_id).strip().upper()
    replacement = _normalize_identifier(new_step_id)
    bindings, result_expression = _parsed_binding_pairs(raw_m)
    if any(name.strip().upper() == replacement.strip().upper() for name, _expr in bindings):
        raise ValueError(f"M step already exists: {replacement!r}")
    found = False
    renamed: list[tuple[str, str]] = []
    for name, expression in bindings:
        new_name = replacement if name.strip().upper() == target else name
        found = found or name.strip().upper() == target
        renamed.append((new_name, _replace_identifier_references(expression, step_id, replacement)))
    if not found:
        raise ValueError(f"Unknown M step: {step_id!r}")
    result = _replace_identifier_references(result_expression or "", step_id, replacement) if result_expression else replacement
    return _canonical_let_query(renamed, result)


def reorder_m_step_expression(
    raw_m: str,
    step_id: str,
    *,
    before_step_id: str | None = None,
    after_step_id: str | None = None,
) -> str:
    if before_step_id and after_step_id:
        raise ValueError("Provide only one of before_step_id or after_step_id")
    target = _normalize_identifier(step_id).strip().upper()
    bindings, result_expression = _parsed_binding_pairs(raw_m)
    index = next((idx for idx, (name, _expr) in enumerate(bindings) if name.strip().upper() == target), None)
    if index is None:
        raise ValueError(f"Unknown M step: {step_id!r}")
    item = bindings.pop(index)
    if before_step_id:
        before = _normalize_identifier(before_step_id).strip().upper()
        insert_at = next((idx for idx, (name, _expr) in enumerate(bindings) if name.strip().upper() == before), None)
        if insert_at is None:
            raise ValueError(f"Unknown M step: {before_step_id!r}")
    elif after_step_id:
        after = _normalize_identifier(after_step_id).strip().upper()
        match = next((idx for idx, (name, _expr) in enumerate(bindings) if name.strip().upper() == after), None)
        if match is None:
            raise ValueError(f"Unknown M step: {after_step_id!r}")
        insert_at = match + 1
    else:
        insert_at = len(bindings)
    bindings.insert(insert_at, item)
    return _canonical_let_query(bindings, result_expression)


def replace_m_parameter_value_expression(raw_m: str, new_expression: str) -> str:
    """Return raw M with a top-level parameter value expression replaced.

    Power Query parameters are commonly encoded as `<value> meta [...]`. This
    helper preserves the metadata record and save-only flow while letting the UI
    stage a new value expression in the draft script.
    """

    replacement = (new_expression or "").strip()
    if not replacement:
        raise ValueError("new_expression must be a non-empty M expression")
    source = raw_m or ""
    if not source.strip():
        raise ValueError("raw_m must be a non-empty M expression")
    meta_idx = _top_level_keyword_index(source, "meta")
    if meta_idx is None:
        leading = re.match(r"\s*", source).group(0)
        trailing_match = re.search(r"\s*$", source)
        trailing = trailing_match.group(0) if trailing_match else ""
        return leading + replacement + trailing
    value_text = source[:meta_idx]
    leading = re.match(r"\s*", value_text).group(0)
    trailing_match = re.search(r"\s*$", value_text)
    trailing = trailing_match.group(0) if trailing_match else ""
    return leading + replacement + trailing + source[meta_idx:]
