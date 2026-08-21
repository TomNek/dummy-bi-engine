from __future__ import annotations

from typing import Any, Mapping


_MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
_MONTHS_DE = ["Januar", "Februar", "M\u00e4rz", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
_MONTHS_FR = ["janvier", "f\u00e9vrier", "mars", "avril", "mai", "juin", "juillet", "ao\u00fbt", "septembre", "octobre", "novembre", "d\u00e9cembre"]
_MONTHS_JA = ["1\u6708", "2\u6708", "3\u6708", "4\u6708", "5\u6708", "6\u6708", "7\u6708", "8\u6708", "9\u6708", "10\u6708", "11\u6708", "12\u6708"]

_WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_WEEKDAYS_JA = ["\u6708\u66dc\u65e5", "\u706b\u66dc\u65e5", "\u6c34\u66dc\u65e5", "\u6728\u66dc\u65e5", "\u91d1\u66dc\u65e5", "\u571f\u66dc\u65e5", "\u65e5\u66dc\u65e5"]


def normalize_culture(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        value = value.get("Culture") or value.get("culture") or ""
    return str(value).strip().lower().replace("_", "-")


def number_separators(culture: Any) -> tuple[str, tuple[str, ...]]:
    key = normalize_culture(culture)
    if key.startswith(("de", "fr", "it", "es", "pt", "nl")):
        return ",", (".", " ", "\u00a0", "\u202f")
    return ".", (",", " ", "\u00a0", "\u202f") if key.startswith(("en", "ja", "zh", "ko")) else (".", ",", " ", "\u00a0", "\u202f")


def date_parse_formats(culture: Any) -> tuple[str, ...]:
    key = normalize_culture(culture)
    if key.startswith(("de", "fr", "it", "es", "pt", "nl")):
        return ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y")
    if key.startswith(("ja", "zh", "ko")):
        return ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y年%m月%d日")
    if key.startswith("en"):
        return ("%m/%d/%Y", "%m-%d-%Y")
    return ()


def datetime_parse_formats(culture: Any) -> tuple[str, ...]:
    values: list[str] = []
    for fmt in date_parse_formats(culture):
        values.extend((f"{fmt} %H:%M:%S", f"{fmt} %H:%M"))
    return tuple(values)


def month_names(culture: Any) -> list[str]:
    key = normalize_culture(culture)
    if key.startswith("de"):
        return _MONTHS_DE
    if key.startswith("fr"):
        return _MONTHS_FR
    if key.startswith(("ja", "zh", "ko")):
        return _MONTHS_JA
    return _MONTHS_EN


def weekday_names(culture: Any) -> list[str]:
    key = normalize_culture(culture)
    if key.startswith("de"):
        return _WEEKDAYS_DE
    if key.startswith("fr"):
        return _WEEKDAYS_FR
    if key.startswith(("ja", "zh", "ko")):
        return _WEEKDAYS_JA
    return _WEEKDAYS_EN
