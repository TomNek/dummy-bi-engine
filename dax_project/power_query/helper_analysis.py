from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .model import MStep


_BLOCKED_HELPER_FRAGMENTS = (
    "File.",
    "Folder.",
    "Sql.",
    "Odbc.",
    "OData.",
    "Web.",
    "SharePoint.",
    "Value.NativeQuery",
    "Table.Buffer",
    "Table.StopFolding",
    "DateTime.LocalNow",
    "DateTime.FixedLocalNow",
    "DateTimeZone.LocalNow",
    "DateTimeZone.UtcNow",
    "DateTimeZone.FixedLocalNow",
    "DateTimeZone.FixedUtcNow",
    "Number.Random",
    "Number.RandomBetween",
    "Text.NewGuid",
)


@dataclass(frozen=True)
class PureHelperDefinition:
    name: str
    parameters: list[str]
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": list(self.parameters), "body": self.body}


def _split_top_level_args(text: str) -> list[str]:
    items: list[str] = []
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
        elif ch == "," and depth == 0:
            item = text[start:i].strip()
            if item:
                items.append(item)
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        items.append(tail)
    return items


def _parse_parameter(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    if text.startswith("#\"") and text.endswith('"'):
        return text[2:-1].replace('""', '"')
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\b", text)
    return match.group(1) if match else None


def _parse_helper_definition(expression: str) -> tuple[list[str], str] | None:
    text = expression.strip()
    match = re.match(r"^\((?P<params>.*?)\)\s*(?:as\s+\w+\s*)?=>\s*(?P<body>.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        params = [_parse_parameter(item) for item in _split_top_level_args(match.group("params"))]
        clean_params = [item for item in params if item]
        return (clean_params, match.group("body").strip()) if clean_params else None
    match = re.match(r"^(?P<param>[A-Za-z_][A-Za-z0-9_]*)\s*(?:as\s+\w+\s*)?=>\s*(?P<body>.+)$", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return [match.group("param")], match.group("body").strip()


def _looks_source_bound_or_dynamic(body: str) -> bool:
    lowered = body.lower()
    return any(fragment.lower() in lowered for fragment in _BLOCKED_HELPER_FRAGMENTS)


def build_pure_helper_registry(steps: Sequence[MStep]) -> dict[str, PureHelperDefinition]:
    helpers: dict[str, PureHelperDefinition] = {}
    for step in steps:
        parsed = _parse_helper_definition(step.expression)
        if parsed is None:
            continue
        params, body = parsed
        if _looks_source_bound_or_dynamic(body):
            continue
        helpers[step.id] = PureHelperDefinition(name=step.id, parameters=params, body=body)
    return helpers


def _replace_identifier(text: str, identifier: str, replacement: str) -> str:
    pattern = re.compile(rf"(?<![\w.]){re.escape(identifier)}(?![\w])")
    return pattern.sub(f"({replacement})", text)


def _apply_helper(helper: PureHelperDefinition, args: Sequence[str]) -> str | None:
    if len(args) != len(helper.parameters):
        return None
    body = helper.body
    for parameter, arg in zip(helper.parameters, args, strict=True):
        body = _replace_identifier(body, parameter, arg)
    return body


def _replace_helper_call(expression: str, helper: PureHelperDefinition) -> tuple[str, bool]:
    pattern = re.compile(rf"(?<![#\w.])(?:{re.escape(helper.name)}|#\"{re.escape(helper.name)}\")\s*\(")
    pos = 0
    out: list[str] = []
    changed = False
    while True:
        match = pattern.search(expression, pos)
        if not match:
            out.append(expression[pos:])
            break
        out.append(expression[pos:match.start()])
        depth = 1
        in_string = False
        i = match.end()
        while i < len(expression):
            ch = expression[i]
            nxt = expression[i + 1] if i + 1 < len(expression) else ""
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
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            out.append(expression[match.start():])
            return "".join(out), changed
        args = _split_top_level_args(expression[match.end():i])
        replacement = _apply_helper(helper, args)
        if replacement is None:
            out.append(expression[match.start():i + 1])
        else:
            out.append(f"({replacement})")
            changed = True
        pos = i + 1
    return "".join(out), changed


def inline_pure_helper_calls(expression: str, helpers: Mapping[str, PureHelperDefinition], *, max_passes: int = 5) -> tuple[str, list[str]]:
    current = expression
    applied: list[str] = []
    for _ in range(max_passes):
        changed_this_pass = False
        for helper in helpers.values():
            current, changed = _replace_helper_call(current, helper)
            if changed:
                changed_this_pass = True
                if helper.name not in applied:
                    applied.append(helper.name)
        if not changed_this_pass:
            break
    return current, applied


def inline_pure_helpers_in_ir(
    ir_nodes: Sequence[Mapping[str, Any]],
    helpers: Mapping[str, PureHelperDefinition],
) -> list[dict[str, Any]]:
    if not helpers:
        return [dict(node) for node in ir_nodes]
    out: list[dict[str, Any]] = []
    for node in ir_nodes:
        item = dict(node)
        args = dict(item.get("args") or {})
        applied: list[str] = []
        for key in ("row_expression", "predicate", "name_transform"):
            if isinstance(args.get(key), str):
                args[key], used = inline_pure_helper_calls(str(args[key]), helpers)
                applied.extend(used)
        transforms = args.get("transforms")
        if isinstance(transforms, list):
            next_transforms = []
            for transform in transforms:
                if isinstance(transform, Mapping):
                    transform_item = dict(transform)
                    if isinstance(transform_item.get("expression"), str):
                        transform_item["expression"], used = inline_pure_helper_calls(str(transform_item["expression"]), helpers)
                        applied.extend(used)
                    next_transforms.append(transform_item)
                else:
                    next_transforms.append(transform)
            args["transforms"] = next_transforms
        if applied:
            args["inlined_helpers"] = sorted(set(applied))
        item["args"] = args
        out.append(item)
    return out
