from __future__ import annotations

import re


def quote_duckdb_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_duckdb_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text.lower() == "null":
        return "NULL"
    if text.lower() in {"true", "false"}:
        return text.upper()
    return "'" + text.replace("'", "''") + "'"


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


def _m_string_to_sql(text: str) -> str | None:
    value = text.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return quote_duckdb_literal(value[1:-1].replace('""', '"'))
    return None


def _replace_m_string_literals(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] != '"':
            out.append(text[i])
            i += 1
            continue
        i += 1
        chars: list[str] = []
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if ch == '"' and nxt == '"':
                chars.append('"')
                i += 2
                continue
            if ch == '"':
                i += 1
                break
            chars.append(ch)
            i += 1
        out.append(quote_duckdb_literal("".join(chars)))
    return "".join(out)


def _find_matching_keyword(text: str, keyword: str, start: int = 0) -> int:
    pattern = re.compile(rf"\b{re.escape(keyword)}\b", flags=re.IGNORECASE)
    in_string = False
    i = start
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
        match = pattern.match(text, i)
        if match:
            return i
        i += 1
    return -1


def _translate_if_expression(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.lower().startswith("if "):
        return None
    then_idx = _find_matching_keyword(stripped, "then", 3)
    if then_idx < 0:
        return None
    else_idx = _find_matching_keyword(stripped, "else", then_idx + 4)
    if else_idx < 0:
        return None
    condition = stripped[3:then_idx].strip()
    truthy = stripped[then_idx + 4 : else_idx].strip()
    falsy = stripped[else_idx + 4 :].strip()
    return (
        "CASE WHEN "
        + m_row_expression_to_duckdb_sql(condition)
        + " THEN "
        + m_row_expression_to_duckdb_sql(truthy)
        + " ELSE "
        + m_row_expression_to_duckdb_sql(falsy)
        + " END"
    )


def _replace_function_call(text: str, name: str, renderer) -> str:
    pattern = re.compile(rf"\b{re.escape(name)}\s*\(", flags=re.IGNORECASE)
    pos = 0
    out = []
    while True:
        match = pattern.search(text, pos)
        if not match:
            out.append(text[pos:])
            break
        out.append(text[pos : match.start()])
        depth = 1
        in_string = False
        i = match.end()
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
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            out.append(text[match.start() :])
            return "".join(out)
        args = _split_top_level_args(text[match.end() : i])
        out.append(renderer(args))
        pos = i + 1
    return "".join(out)


def _arg_sql(args: list[str], index: int) -> str:
    if index >= len(args):
        return "NULL"
    value = args[index].strip()
    if (
        not re.search(r"\b(?:Text|Number|Date|DateTime|Logical|List|Record|Table)\.", value)
        and "[" not in value
        and re.search(r"\b(?:CAST|contains|starts_with|ends_with|length|left|right|substr|lpad|rpad|split_part|strpos|upper|lower|trim|ltrim|rtrim|regexp_replace|replace|round|abs|sign|ceil|floor|pow|date_part|date_trunc|last_day|strptime)\s*\(", value)
    ):
        return value
    return m_row_expression_to_duckdb_sql(value)


def _arg_literal_text(args: list[str], index: int) -> str | None:
    if index >= len(args):
        return None
    value = args[index].strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('""', '"')
    return None


def _literal_list_sql_values(text: str) -> list[str] | None:
    value = text.strip()
    if len(value) < 2 or value[0] != "{" or value[-1] != "}":
        return None
    out: list[str] = []
    for item in _split_top_level_args(value[1:-1]):
        raw = item.strip()
        if not raw:
            return None
        if len(raw) >= 2 and raw[0] == "'" and raw[-1] == "'":
            out.append(raw)
        elif len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            out.append(quote_duckdb_literal(raw[1:-1].replace('""', '"')))
        elif re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
            out.append(raw)
        elif raw.lower() in {"null", "true", "false"}:
            out.append(quote_duckdb_literal(raw))
        else:
            return None
    return out


def _culture_key(args: list[str], index: int = 1) -> str:
    return (_arg_literal_text(args, index) or "").strip().lower().replace("_", "-")


def _day_first_offset_sql(args: list[str], index: int = 1) -> int:
    if index >= len(args):
        return 0
    text = args[index].strip().strip('"').strip("'").lower()
    mapping = {
        "day.sunday": 0,
        "sunday": 0,
        "0": 0,
        "day.monday": 1,
        "monday": 1,
        "1": 1,
        "day.tuesday": 2,
        "tuesday": 2,
        "2": 2,
        "day.wednesday": 3,
        "wednesday": 3,
        "3": 3,
        "day.thursday": 4,
        "thursday": 4,
        "4": 4,
        "day.friday": 5,
        "friday": 5,
        "5": 5,
        "day.saturday": 6,
        "saturday": 6,
        "6": 6,
    }
    return mapping.get(text, 0)


def _render_text_from(args: list[str]) -> str:
    return f"CAST({_arg_sql(args, 0)} AS VARCHAR)"


def _render_number_from(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    culture = _culture_key(args)
    if culture.startswith(("de", "fr", "it", "es", "pt")):
        return f"CAST(replace(replace(replace({value}, ' ', ''), '.', ''), ',', '.') AS DOUBLE)"
    if culture.startswith("en"):
        return f"CAST(replace({value}, ',', '') AS DOUBLE)"
    return f"CAST({_arg_sql(args, 0)} AS DOUBLE)"


def _render_date_from(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    culture = _culture_key(args)
    if culture.startswith(("de", "fr", "it", "es", "pt")):
        return f"CAST(strptime({value}, '%d.%m.%Y') AS DATE)"
    if culture.startswith("en"):
        return f"CAST(strptime({value}, '%m/%d/%Y') AS DATE)"
    return f"CAST({_arg_sql(args, 0)} AS DATE)"


def _render_datetime_from(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    culture = _culture_key(args)
    if culture.startswith(("de", "fr", "it", "es", "pt")):
        return f"strptime({value}, '%d.%m.%Y %H:%M:%S')"
    if culture.startswith("en"):
        return f"strptime({value}, '%m/%d/%Y %H:%M:%S')"
    return f"CAST({_arg_sql(args, 0)} AS TIMESTAMP)"


def _render_datetime_date(args: list[str]) -> str:
    return f"CAST({_arg_sql(args, 0)} AS DATE)"


def _render_datetime_time(args: list[str]) -> str:
    return f"CAST({_arg_sql(args, 0)} AS TIME)"


def _render_time_from(args: list[str]) -> str:
    return f"CAST({_arg_sql(args, 0)} AS TIME)"


def _render_logical_from(args: list[str]) -> str:
    return f"CAST({_arg_sql(args, 0)} AS BOOLEAN)"


def _render_list_contains(args: list[str]) -> str:
    values = _literal_list_sql_values(args[0]) if args else None
    if values is None or len(args) > 2:
        return f"List.Contains({', '.join(args)})"
    if not values:
        return "(FALSE)"
    value_sql = _arg_sql(args, 1)
    non_null_values = [item for item in values if item.upper() != "NULL"]
    has_null = len(non_null_values) != len(values)
    checks: list[str] = []
    if non_null_values:
        checks.append(f"{value_sql} IN ({', '.join(non_null_values)})")
    if has_null:
        checks.append(f"{value_sql} IS NULL")
    return "(" + (" OR ".join(checks) if checks else "FALSE") + ")"


def _render_text_contains(args: list[str]) -> str:
    return f"contains(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)})"


def _render_text_startswith(args: list[str]) -> str:
    return f"starts_with(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)})"


def _render_text_endswith(args: list[str]) -> str:
    return f"ends_with(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)})"


def _render_text_length(args: list[str]) -> str:
    return f"length(CAST({_arg_sql(args, 0)} AS VARCHAR))"


def _render_text_start(args: list[str]) -> str:
    return f"left(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)})"


def _render_text_end(args: list[str]) -> str:
    return f"right(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)})"


def _render_text_range(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    start = f"({_arg_sql(args, 1)} + 1)"
    if len(args) > 2:
        return f"substr({value}, {start}, {_arg_sql(args, 2)})"
    return f"substr({value}, {start})"


def _render_text_pad_start(args: list[str]) -> str:
    pad = _arg_sql(args, 2) if len(args) > 2 else "' '"
    return f"lpad(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)}, {pad})"


def _render_text_pad_end(args: list[str]) -> str:
    pad = _arg_sql(args, 2) if len(args) > 2 else "' '"
    return f"rpad(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)}, {pad})"


def _render_text_before_delimiter(args: list[str]) -> str:
    return f"split_part(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)}, 1)"


def _render_text_after_delimiter(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    delimiter = _arg_sql(args, 1)
    return f"CASE WHEN strpos({value}, {delimiter}) = 0 THEN '' ELSE substr({value}, strpos({value}, {delimiter}) + length({delimiter})) END"


def _render_text_between_delimiters(args: list[str]) -> str:
    return f"split_part(split_part(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)}, 2), {_arg_sql(args, 2)}, 1)"


def _render_text_upper(args: list[str]) -> str:
    return f"upper(CAST({_arg_sql(args, 0)} AS VARCHAR))"


def _render_text_lower(args: list[str]) -> str:
    return f"lower(CAST({_arg_sql(args, 0)} AS VARCHAR))"


def _render_text_trim(args: list[str]) -> str:
    return f"trim(CAST({_arg_sql(args, 0)} AS VARCHAR))"


def _render_text_trim_start(args: list[str]) -> str:
    if len(args) > 1:
        return f"Text.TrimStart({', '.join(args)})"
    return f"ltrim(CAST({_arg_sql(args, 0)} AS VARCHAR))"


def _render_text_trim_end(args: list[str]) -> str:
    if len(args) > 1:
        return f"Text.TrimEnd({', '.join(args)})"
    return f"rtrim(CAST({_arg_sql(args, 0)} AS VARCHAR))"


def _render_text_clean(args: list[str]) -> str:
    return f"regexp_replace(CAST({_arg_sql(args, 0)} AS VARCHAR), '\\p{{Cc}}', '', 'g')"


def _render_text_replace(args: list[str]) -> str:
    return f"replace(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)}, {_arg_sql(args, 2)})"


def _render_text_position_of(args: list[str]) -> str:
    if len(args) > 2:
        return f"Text.PositionOf({', '.join(args)})"
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    needle = _arg_sql(args, 1)
    return f"CASE WHEN strpos({value}, {needle}) = 0 THEN -1 ELSE strpos({value}, {needle}) - 1 END"


def _render_text_repeat(args: list[str]) -> str:
    return f"repeat(CAST({_arg_sql(args, 0)} AS VARCHAR), {_arg_sql(args, 1)})"


def _render_text_insert(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    offset = _arg_sql(args, 1)
    inserted = _arg_sql(args, 2)
    return f"left({value}, {offset}) || {inserted} || substr({value}, ({offset} + 1))"


def _render_text_remove_range(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS VARCHAR)"
    offset = _arg_sql(args, 1)
    if len(args) > 2:
        count = _arg_sql(args, 2)
        return f"left({value}, {offset}) || substr({value}, ({offset} + {count} + 1))"
    return f"left({value}, {offset})"


def _render_number_round(args: list[str]) -> str:
    if len(args) > 1:
        return f"round({_arg_sql(args, 0)}, {_arg_sql(args, 1)})"
    return f"round({_arg_sql(args, 0)})"


def _render_number_abs(args: list[str]) -> str:
    return f"abs({_arg_sql(args, 0)})"


def _render_number_sign(args: list[str]) -> str:
    return f"sign({_arg_sql(args, 0)})"


def _render_number_round_up(args: list[str]) -> str:
    if len(args) > 1:
        factor = f"pow(10, {_arg_sql(args, 1)})"
        return f"(ceil({_arg_sql(args, 0)} * {factor}) / {factor})"
    return f"ceil({_arg_sql(args, 0)})"


def _render_number_round_down(args: list[str]) -> str:
    if len(args) > 1:
        factor = f"pow(10, {_arg_sql(args, 1)})"
        return f"(floor({_arg_sql(args, 0)} * {factor}) / {factor})"
    return f"floor({_arg_sql(args, 0)})"


def _render_number_mod(args: list[str]) -> str:
    return f"({_arg_sql(args, 0)} % {_arg_sql(args, 1)})"


def _render_number_power(args: list[str]) -> str:
    return f"pow({_arg_sql(args, 0)}, {_arg_sql(args, 1)})"


def _render_number_sqrt(args: list[str]) -> str:
    return f"sqrt({_arg_sql(args, 0)})"


def _render_date_part(part: str):
    def renderer(args: list[str]) -> str:
        return f"date_part('{part}', CAST({_arg_sql(args, 0)} AS DATE))"

    return renderer


def _render_date_day_of_week(args: list[str]) -> str:
    offset = _day_first_offset_sql(args)
    dow = f"date_part('dow', CAST({_arg_sql(args, 0)} AS DATE))"
    if offset == 0:
        return dow
    return f"(({dow} - {offset} + 7) % 7)"


def _render_time_part(part: str):
    def renderer(args: list[str]) -> str:
        return f"date_part('{part}', CAST({_arg_sql(args, 0)} AS TIME))"

    return renderer


def _render_date_trunc(part: str):
    def renderer(args: list[str]) -> str:
        return f"CAST(date_trunc('{part}', CAST({_arg_sql(args, 0)} AS DATE)) AS DATE)"

    return renderer


def _render_date_end_of_month(args: list[str]) -> str:
    return f"last_day(CAST({_arg_sql(args, 0)} AS DATE))"


def _render_date_end_of_quarter(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS DATE)"
    return f"CAST(date_trunc('quarter', {value}) + INTERVAL '3 months' - INTERVAL '1 day' AS DATE)"


def _render_date_end_of_year(args: list[str]) -> str:
    value = f"CAST({_arg_sql(args, 0)} AS DATE)"
    return f"CAST(date_trunc('year', {value}) + INTERVAL '1 year' - INTERVAL '1 day' AS DATE)"


def _render_date_add_days(args: list[str]) -> str:
    return f"CAST(CAST({_arg_sql(args, 0)} AS DATE) + CAST({_arg_sql(args, 1)} AS INTEGER) * INTERVAL '1 day' AS DATE)"


def _render_date_add_months(args: list[str]) -> str:
    return f"CAST(CAST({_arg_sql(args, 0)} AS DATE) + CAST({_arg_sql(args, 1)} AS INTEGER) * INTERVAL '1 month' AS DATE)"


def _render_date_add_years(args: list[str]) -> str:
    return f"CAST(CAST({_arg_sql(args, 0)} AS DATE) + CAST({_arg_sql(args, 1)} AS INTEGER) * INTERVAL '1 year' AS DATE)"


_FUNCTION_RENDERERS = {
    "List.Contains": _render_list_contains,
    "Text.From": _render_text_from,
    "Text.Contains": _render_text_contains,
    "Text.StartsWith": _render_text_startswith,
    "Text.EndsWith": _render_text_endswith,
    "Text.Length": _render_text_length,
    "Text.Start": _render_text_start,
    "Text.End": _render_text_end,
    "Text.Range": _render_text_range,
    "Text.PadStart": _render_text_pad_start,
    "Text.PadEnd": _render_text_pad_end,
    "Text.BeforeDelimiter": _render_text_before_delimiter,
    "Text.AfterDelimiter": _render_text_after_delimiter,
    "Text.BetweenDelimiters": _render_text_between_delimiters,
    "Text.Upper": _render_text_upper,
    "Text.Lower": _render_text_lower,
    "Text.Trim": _render_text_trim,
    "Text.TrimStart": _render_text_trim_start,
    "Text.TrimEnd": _render_text_trim_end,
    "Text.Clean": _render_text_clean,
    "Text.Replace": _render_text_replace,
    "Text.PositionOf": _render_text_position_of,
    "Text.Repeat": _render_text_repeat,
    "Text.Insert": _render_text_insert,
    "Text.RemoveRange": _render_text_remove_range,
    "Number.From": _render_number_from,
    "Number.FromText": _render_number_from,
    "Number.Round": _render_number_round,
    "Number.Abs": _render_number_abs,
    "Number.Sign": _render_number_sign,
    "Number.RoundUp": _render_number_round_up,
    "Number.RoundDown": _render_number_round_down,
    "Number.Mod": _render_number_mod,
    "Number.Power": _render_number_power,
    "Number.Sqrt": _render_number_sqrt,
    "Date.From": _render_date_from,
    "Date.FromText": _render_date_from,
    "DateTime.From": _render_datetime_from,
    "DateTime.FromText": _render_datetime_from,
    "DateTime.Date": _render_datetime_date,
    "DateTime.Time": _render_datetime_time,
    "Logical.From": _render_logical_from,
    "Logical.FromText": _render_logical_from,
    "Time.Hour": _render_time_part("hour"),
    "Time.Minute": _render_time_part("minute"),
    "Time.Second": _render_time_part("second"),
    "Time.From": _render_time_from,
    "Time.FromText": _render_time_from,
    "Date.Year": _render_date_part("year"),
    "Date.Month": _render_date_part("month"),
    "Date.Day": _render_date_part("day"),
    "Date.DayOfWeek": _render_date_day_of_week,
    "Date.QuarterOfYear": _render_date_part("quarter"),
    "Date.DayOfYear": _render_date_part("doy"),
    "Date.StartOfMonth": _render_date_trunc("month"),
    "Date.EndOfMonth": _render_date_end_of_month,
    "Date.StartOfQuarter": _render_date_trunc("quarter"),
    "Date.EndOfQuarter": _render_date_end_of_quarter,
    "Date.StartOfYear": _render_date_trunc("year"),
    "Date.EndOfYear": _render_date_end_of_year,
    "Date.AddDays": _render_date_add_days,
    "Date.AddMonths": _render_date_add_months,
    "Date.AddYears": _render_date_add_years,
}


def m_row_expression_to_duckdb_sql(expression: str, *, current_column: str | None = None) -> str:
    text = expression.strip()
    if text.lower().startswith("each "):
        text = text[5:].strip()
    if current_column:
        text = re.sub(r"(?<![A-Za-z0-9_])_(?![A-Za-z0-9_])", f"[{current_column}]", text)
    if not text:
        return "NULL"

    conditional = _translate_if_expression(text)
    if conditional is not None:
        return conditional

    string_literal = _m_string_to_sql(text)
    if string_literal is not None:
        return string_literal

    text = _replace_m_string_literals(text)

    for name, renderer in _FUNCTION_RENDERERS.items():
        text = _replace_function_call(text, name, renderer)

    text = re.sub(r"\[([^\]]+)\]", lambda m: quote_duckdb_identifier(m.group(1)), text)
    text = re.sub(r"<>", "!=", text)
    text = re.sub(r"(?<![<>=!])=(?!=)", "=", text)
    text = re.sub(r"\s&\s", " || ", text)
    text = re.sub(r"\band\b", "AND", text, flags=re.IGNORECASE)
    text = re.sub(r"\bor\b", "OR", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnot\b", "NOT", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnull\b", "NULL", text, flags=re.IGNORECASE)
    text = re.sub(r"\btrue\b", "TRUE", text, flags=re.IGNORECASE)
    text = re.sub(r"\bfalse\b", "FALSE", text, flags=re.IGNORECASE)
    return text


def can_lower_m_row_expression_to_duckdb(expression: str, *, current_column: str | None = None) -> bool:
    text = expression.strip()
    if not text:
        return False
    if re.search(r"\btry\b|\botherwise\b", text, flags=re.IGNORECASE):
        return False
    if "?[" in text or "]?" in text:
        return False
    if re.search(r"(^|[^A-Za-z0-9_])[\{\[]\s*(?:\[|[A-Za-z_][A-Za-z0-9_]*\s*=)", text):
        return False
    lowered = m_row_expression_to_duckdb_sql(text, current_column=current_column)
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\s*\(", lowered):
        return False
    if re.search(r"\b[A-Za-z_][A-Za-z0-9_]*\s*\(", lowered):
        allowed = {
            "CASE",
            "IN",
            "NOT",
            "CAST",
            "contains",
            "starts_with",
            "ends_with",
            "length",
            "repeat",
            "left",
            "right",
            "substr",
            "lpad",
            "rpad",
            "split_part",
            "strpos",
            "upper",
            "lower",
            "trim",
            "ltrim",
            "rtrim",
            "regexp_replace",
            "replace",
            "round",
            "abs",
            "sign",
            "ceil",
            "floor",
            "pow",
            "sqrt",
            "date_part",
            "date_trunc",
            "last_day",
            "strptime",
        }
        for name in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", lowered):
            if name not in allowed:
                return False
    return True
