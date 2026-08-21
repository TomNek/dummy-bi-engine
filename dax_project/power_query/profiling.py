from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _is_error(value: Any) -> bool:
    return (isinstance(value, Mapping) and bool(value.get("error"))) or value.__class__.__name__ == "MErrorValue"


def build_data_profile(
    *,
    columns: Sequence[Mapping[str, Any]],
    rows: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    """Build a lightweight Power Query-style data profile from preview rows."""

    names = [str(c.get("name") or "").strip() for c in columns if str(c.get("name") or "").strip()]
    profiles: list[dict[str, Any]] = []
    row_count = len(rows)

    for idx, name in enumerate(names):
        values = [row[idx] if idx < len(row) else None for row in rows]
        empty_count = sum(1 for value in values if _is_empty(value))
        error_count = sum(1 for value in values if _is_error(value))
        valid_values = [value for value in values if not _is_empty(value) and not _is_error(value)]
        valid_count = len(valid_values)
        counts = Counter(str(value) for value in valid_values)
        unique_count = sum(1 for count in counts.values() if count == 1)

        numeric_values = [value for value in valid_values if isinstance(value, (int, float)) and not isinstance(value, bool)]
        profile: dict[str, Any] = {
            "name": name,
            "type": str(columns[idx].get("type") or "UNKNOWN") if idx < len(columns) else "UNKNOWN",
            "row_count": row_count,
            "quality": {
                "valid": valid_count,
                "empty": empty_count,
                "error": error_count,
                "unknown": 0,
            },
            "distribution": {
                "distinct_count": len(counts),
                "unique_count": unique_count,
                "top_values": [
                    {"value": value, "count": count}
                    for value, count in counts.most_common(10)
                ],
            },
        }
        if numeric_values:
            profile["statistics"] = {
                "min": min(numeric_values),
                "max": max(numeric_values),
                "average": sum(numeric_values) / len(numeric_values),
            }
        profiles.append(profile)

    return {
        "row_count": row_count,
        "profile_scope": "preview",
        "columns": profiles,
    }
