"""DuckDB UDF/macro definitions for DAX-to-SQL compiled expressions.

The compiler maps DAX functions to SQL using ``DAX_<name>`` function names.
This module registers those functions as DuckDB macros or Python UDFs so
that the compiled SQL can execute successfully.

Usage:
    import duckdb
    from dax_engine.duckdb_udfs import register_all_udfs
    con = duckdb.connect(":memory:")
    register_all_udfs(con)
"""
from __future__ import annotations

import datetime
import math
from typing import Any

import duckdb

try:
    from dax_engine import financial as _fin
except ImportError:
    _fin = None  # Enterprise module; financial UDFs unavailable in Community Edition
from dax_engine import distributions as _dist


def register_all_udfs(con: duckdb.DuckDBPyConnection) -> None:
    """Register all DAX_* functions as DuckDB macros/UDFs."""
    _register_math_macros(con)
    _register_bit_macros(con)
    _register_trig_macros(con)
    _register_text_macros(con)
    _register_date_macros(con)
    _register_info_macros(con)
    _register_stat_macros(con)
    if _fin is not None:
        _register_financial_macros(con)
    _register_misc_macros(con)
    _register_python_udfs(con)


def _safe_macro(con: duckdb.DuckDBPyConnection, sql: str) -> None:
    """Execute a CREATE MACRO statement, ignoring errors for already-existing."""
    try:
        con.execute(sql)
    except Exception as exc:
        # Extract macro name for logging
        import re as _re
        m = _re.search(r'CREATE MACRO (\w+)', sql)
        name = m.group(1) if m else '???'
        _FAILED_MACROS.append((name, str(exc)))

    # Also register a raw-name alias (without DAX_ prefix) if applicable,
    # but skip names that would shadow DuckDB built-in functions
    import re as _re
    m = _re.search(r'CREATE MACRO DAX_(\w+)', sql)
    if m:
        raw_name = m.group(1)
        if raw_name.upper() not in _DUCKDB_BUILTINS:
            raw_sql = sql.replace(f'DAX_{raw_name}', raw_name, 1)
            try:
                con.execute(raw_sql)
            except Exception:
                pass  # Raw name may conflict with other definitions


# DuckDB built-in function names — do NOT shadow these with macros
_DUCKDB_BUILTINS = frozenset({
    'ABS', 'ACOS', 'ACOSH', 'ASIN', 'ASINH', 'ATAN', 'ATANH',
    'AVG', 'CEIL', 'CEILING', 'COALESCE', 'CONCAT', 'CONTAINS',
    'COS', 'COSH', 'COUNT', 'DEGREES', 'EXP', 'FLOOR',
    'GREATEST', 'HASH', 'LAST_DAY', 'LEAST', 'LEFT', 'LENGTH',
    'LN', 'LOG', 'LOWER', 'LTRIM', 'MAX', 'MEDIAN', 'MIN',
    'MOD', 'NOT', 'PI', 'POSITION', 'POWER', 'POW',
    'RADIANS', 'RANDOM', 'REPLACE', 'REPEAT', 'ROUND', 'RTRIM',
    'SIGN', 'SIN', 'SINH', 'SQRT', 'STDDEV_POP', 'STDDEV_SAMP',
    'SUBSTR', 'SUBSTRING', 'SUM', 'TAN', 'TANH', 'TRIM',
    'TRUNC', 'UNICODE', 'UPPER', 'VAR_POP', 'VAR_SAMP',
    'DATEDIFF', 'DATE_DIFF',
})


_FAILED_MACROS: list[tuple[str, str]] = []


def get_failed_macros() -> list[tuple[str, str]]:
    """Return list of (macro_name, error_message) for macros that failed to register."""
    return list(_FAILED_MACROS)


# ── Math ─────────────────────────────────────────────────────────────

def _register_math_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        # COMBIN(n, k) = n! / (k! * (n-k)!)
        "CREATE MACRO DAX_COMBIN(n, k) AS "
        "CASE WHEN k < 0 OR k > n THEN NULL "
        "ELSE CAST(factorial(CAST(n AS INTEGER)) / "
        "(factorial(CAST(k AS INTEGER)) * factorial(CAST(n - k AS INTEGER))) AS DOUBLE) END",

        # COMBINA(n, k) = COMBIN(n + k - 1, k)
        "CREATE MACRO DAX_COMBINA(n, k) AS "
        "CAST(factorial(CAST(n + k - 1 AS INTEGER)) / "
        "(factorial(CAST(k AS INTEGER)) * factorial(CAST(n - 1 AS INTEGER))) AS DOUBLE)",

        # FACT(n)
        "CREATE MACRO DAX_FACT(n) AS CAST(factorial(CAST(n AS INTEGER)) AS DOUBLE)",

        # GCD(a, b)
        "CREATE MACRO DAX_GCD(a, b) AS greatest_common_divisor(CAST(a AS BIGINT), CAST(b AS BIGINT))",

        # LCM(a, b) = |a*b| / GCD(a, b)
        "CREATE MACRO DAX_LCM(a, b) AS "
        "CASE WHEN a = 0 OR b = 0 THEN 0 "
        "ELSE ABS(CAST(a AS BIGINT) * CAST(b AS BIGINT)) / "
        "greatest_common_divisor(ABS(CAST(a AS BIGINT)), ABS(CAST(b AS BIGINT))) END",

        # QUOTIENT(num, denom) = integer part of division
        "CREATE MACRO DAX_QUOTIENT(num, denom) AS "
        "CAST(CASE WHEN denom = 0 THEN NULL ELSE TRUNC(CAST(num AS DOUBLE) / denom) END AS BIGINT)",

        # ODD(n) = rounds to nearest odd integer away from zero
        "CREATE MACRO DAX_ODD(n) AS "
        "CASE WHEN n >= 0 THEN "
        "  CASE WHEN CAST(CEIL(n) AS BIGINT) % 2 = 1 THEN CAST(CEIL(n) AS BIGINT) "
        "  ELSE CAST(CEIL(n) AS BIGINT) + 1 END "
        "ELSE "
        "  CASE WHEN CAST(FLOOR(n) AS BIGINT) % 2 = -1 THEN CAST(FLOOR(n) AS BIGINT) "
        "  ELSE CAST(FLOOR(n) AS BIGINT) - 1 END "
        "END",

        # EVEN(n) = rounds to nearest even integer away from zero
        "CREATE MACRO DAX_EVEN(n) AS "
        "CASE WHEN n >= 0 THEN "
        "  CASE WHEN CAST(CEIL(n) AS BIGINT) % 2 = 0 THEN CAST(CEIL(n) AS BIGINT) "
        "  ELSE CAST(CEIL(n) AS BIGINT) + 1 END "
        "ELSE "
        "  CASE WHEN CAST(FLOOR(n) AS BIGINT) % 2 = 0 THEN CAST(FLOOR(n) AS BIGINT) "
        "  ELSE CAST(FLOOR(n) AS BIGINT) - 1 END "
        "END",

        # SQRTPI(n)
        "CREATE MACRO DAX_SQRTPI(n) AS SQRT(CAST(n AS DOUBLE) * PI())",

        # MROUND(n, multiple) = round to nearest multiple
        "CREATE MACRO DAX_MROUND(n, m) AS "
        "CASE WHEN m = 0 THEN 0.0 ELSE ROUND(CAST(n AS DOUBLE) / m) * m END",

        # PERMUT(n, k) = n! / (n-k)!
        "CREATE MACRO DAX_PERMUT(n, k) AS "
        "CAST(factorial(CAST(n AS INTEGER)) / factorial(CAST(n - k AS INTEGER)) AS DOUBLE)",

        # INT(n) = floor toward negative infinity
        "CREATE MACRO DAX_INT(n) AS CAST(FLOOR(CAST(n AS DOUBLE)) AS BIGINT)",

        # CEILING(n, sig) = ceil to significance
        "CREATE MACRO DAX_CEILING(n, sig) AS "
        "CASE WHEN sig = 0 THEN 0.0 ELSE CEIL(CAST(n AS DOUBLE) / sig) * sig END",

        # ISO.CEILING(n, sig)
        "CREATE MACRO DAX_ISO_CEILING(n, sig) AS "
        "CASE WHEN sig = 0 THEN 0.0 ELSE CEIL(CAST(n AS DOUBLE) / ABS(sig)) * ABS(sig) END",

        # FLOOR(n, sig)
        "CREATE MACRO DAX_FLOOR(n, sig) AS "
        "CASE WHEN sig = 0 THEN 0.0 ELSE FLOOR(CAST(n AS DOUBLE) / sig) * sig END",

        # ROUNDUP(n, digits) - round away from zero
        "CREATE MACRO DAX_ROUNDUP(n, d) AS "
        "CASE WHEN n >= 0 THEN CEIL(CAST(n AS DOUBLE) * POWER(10, d)) / POWER(10, d) "
        "ELSE FLOOR(CAST(n AS DOUBLE) * POWER(10, d)) / POWER(10, d) END",

        # ROUNDDOWN(n, digits) - round toward zero
        "CREATE MACRO DAX_ROUNDDOWN(n, d) AS "
        "CASE WHEN n >= 0 THEN FLOOR(CAST(n AS DOUBLE) * POWER(10, d)) / POWER(10, d) "
        "ELSE CEIL(CAST(n AS DOUBLE) * POWER(10, d)) / POWER(10, d) END",

        # TRUNC(n, digits) - same as ROUNDDOWN
        "CREATE MACRO DAX_TRUNC(n, d) AS "
        "CASE WHEN n >= 0 THEN FLOOR(CAST(n AS DOUBLE) * POWER(10, d)) / POWER(10, d) "
        "ELSE CEIL(CAST(n AS DOUBLE) * POWER(10, d)) / POWER(10, d) END",

        # DEGREES(rad)
        "CREATE MACRO DAX_DEGREES(rad) AS DEGREES(CAST(rad AS DOUBLE))",

        # RADIANS(deg)
        "CREATE MACRO DAX_RADIANS(deg) AS RADIANS(CAST(deg AS DOUBLE))",

        # RAND()
        "CREATE MACRO DAX_RAND() AS RANDOM()",

        # RANDBETWEEN(lo, hi)
        "CREATE MACRO DAX_RANDBETWEEN(lo, hi) AS "
        "CAST(lo AS BIGINT) + CAST(FLOOR(RANDOM() * (CAST(hi AS BIGINT) - CAST(lo AS BIGINT) + 1)) AS BIGINT)",

        # CURRENCY(n) - just cast to decimal
        "CREATE MACRO DAX_CURRENCY(n) AS CAST(n AS DECIMAL(19,4))",

        # ISEVEN / ISODD
        "CREATE MACRO DAX_ISEVEN(n) AS (CAST(n AS BIGINT) % 2 = 0)",
        "CREATE MACRO DAX_ISODD(n) AS (CAST(n AS BIGINT) % 2 != 0)",
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Bit operations ──────────────────────────────────────────────────

def _register_bit_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        "CREATE MACRO DAX_BITAND(a, b) AS (CAST(a AS BIGINT) & CAST(b AS BIGINT))",
        "CREATE MACRO DAX_BITOR(a, b) AS (CAST(a AS BIGINT) | CAST(b AS BIGINT))",
        "CREATE MACRO DAX_BITXOR(a, b) AS xor(CAST(a AS BIGINT), CAST(b AS BIGINT))",
        "CREATE MACRO DAX_BITLSHIFT(n, amount) AS (CAST(n AS BIGINT) << CAST(amount AS INTEGER))",
        "CREATE MACRO DAX_BITRSHIFT(n, amount) AS (CAST(n AS BIGINT) >> CAST(amount AS INTEGER))",
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Trig ─────────────────────────────────────────────────────────────

def _register_trig_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        "CREATE MACRO DAX_COT(x) AS (1.0 / TAN(CAST(x AS DOUBLE)))",
        "CREATE MACRO DAX_COTH(x) AS (COSH(CAST(x AS DOUBLE)) / SINH(CAST(x AS DOUBLE)))",
        "CREATE MACRO DAX_ACOT(x) AS (PI() / 2.0 - ATAN(CAST(x AS DOUBLE)))",
        "CREATE MACRO DAX_ACOTH(x) AS (0.5 * LN((CAST(x AS DOUBLE) + 1.0) / (CAST(x AS DOUBLE) - 1.0)))",
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Text ─────────────────────────────────────────────────────────────

def _register_text_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        "CREATE MACRO DAX_LOWER(t) AS LOWER(CAST(t AS VARCHAR))",
        "CREATE MACRO DAX_UPPER(t) AS UPPER(CAST(t AS VARCHAR))",
        "CREATE MACRO DAX_EXACT(a, b) AS (CAST(a AS VARCHAR) = CAST(b AS VARCHAR))",
        "CREATE MACRO DAX_REPT(t, n) AS REPEAT(CAST(t AS VARCHAR), CAST(n AS INTEGER))",
        "CREATE MACRO DAX_UNICHAR(n) AS CHR(CAST(n AS INTEGER))",
        "CREATE MACRO DAX_UNICODE(t) AS UNICODE(CAST(t AS VARCHAR))",
        # FIXED(number, decimals, no_commas) — replaced by Python UDF below,
        # REPLACE(old_text, start, num_chars, new_text)
        "CREATE MACRO DAX_REPLACE(t, s, nc, nt) AS "
        "(SUBSTRING(CAST(t AS VARCHAR), 1, CAST(s AS INTEGER) - 1) || "
        "CAST(nt AS VARCHAR) || "
        "SUBSTRING(CAST(t AS VARCHAR), CAST(s AS INTEGER) + CAST(nc AS INTEGER)))",
        # COMBINEVALUES(delim, val1, val2, ...)
        "CREATE MACRO DAX_COMBINEVALUES(d, a, b) AS "
        "(CAST(a AS VARCHAR) || CAST(d AS VARCHAR) || CAST(b AS VARCHAR))",
        # CONTAINSSTRING
        "CREATE MACRO DAX_CONTAINSSTRING(t, sub) AS "
        "CONTAINS(LOWER(CAST(t AS VARCHAR)), LOWER(CAST(sub AS VARCHAR)))",
        # CONTAINSSTRINGEXACT
        "CREATE MACRO DAX_CONTAINSSTRINGEXACT(t, sub) AS "
        "CONTAINS(CAST(t AS VARCHAR), CAST(sub AS VARCHAR))",
        # RIGHT(text, num_chars)
        "CREATE MACRO DAX_RIGHT(t, n) AS "
        "SUBSTRING(CAST(t AS VARCHAR), LENGTH(CAST(t AS VARCHAR)) - CAST(n AS INTEGER) + 1, CAST(n AS INTEGER))",
        # LEFT is handled natively but add for safety
        "CREATE MACRO DAX_LEFT(t, n) AS LEFT(CAST(t AS VARCHAR), CAST(n AS INTEGER))",
        # MID
        "CREATE MACRO DAX_MID(t, s, n) AS SUBSTRING(CAST(t AS VARCHAR), CAST(s AS INTEGER), CAST(n AS INTEGER))",
        # TRIM
        "CREATE MACRO DAX_TRIM(t) AS TRIM(CAST(t AS VARCHAR))",
        # SUBSTITUTE(text, old, new, instance)
        "CREATE MACRO DAX_SUBSTITUTE(t, old, new) AS "
        "REPLACE(CAST(t AS VARCHAR), CAST(old AS VARCHAR), CAST(new AS VARCHAR))",
        # LEN
        "CREATE MACRO DAX_LEN(t) AS LENGTH(CAST(t AS VARCHAR))",
        # SEARCH(find, within, start_pos)
        "CREATE MACRO DAX_SEARCH(find, within, sp) AS "
        "POSITION(LOWER(CAST(find AS VARCHAR)) IN LOWER(SUBSTRING(CAST(within AS VARCHAR), CAST(sp AS INTEGER)))) + CAST(sp AS INTEGER) - 1",
        # FIND(find, within, start_pos)
        "CREATE MACRO DAX_FIND(find, within, sp) AS "
        "POSITION(CAST(find AS VARCHAR) IN SUBSTRING(CAST(within AS VARCHAR), CAST(sp AS INTEGER))) + CAST(sp AS INTEGER) - 1",
        # VALUE(text) - convert text to number
        "CREATE MACRO DAX_VALUE(t) AS CAST(t AS DOUBLE)",
        # FORMAT(value, format_string) - replaced by Python UDF below,
        # LOOKUPVALUE - simplified 2-arg (will fail for complex calls but covers basics)
        "CREATE MACRO DAX_LOOKUPVALUE(result, search, val) AS NULL",
        # NAMEOF — hard to implement correctly as a macro; needs compiler support
        "CREATE MACRO DAX_NAMEOF(col) AS CAST(col AS VARCHAR)",
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Date/Time ────────────────────────────────────────────────────────

def _register_date_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        "CREATE MACRO DAX_HOUR(d) AS EXTRACT(HOUR FROM d)",
        "CREATE MACRO DAX_MINUTE(d) AS EXTRACT(MINUTE FROM d)",
        "CREATE MACRO DAX_SECOND(d) AS EXTRACT(SECOND FROM d)",
        "CREATE MACRO DAX_WEEKDAY(d) AS "
        "CASE EXTRACT(DOW FROM CAST(d AS DATE)) "
        "WHEN 0 THEN 1 WHEN 1 THEN 2 WHEN 2 THEN 3 WHEN 3 THEN 4 "
        "WHEN 4 THEN 5 WHEN 5 THEN 6 WHEN 6 THEN 7 END",
        "CREATE MACRO DAX_QUARTER(d) AS EXTRACT(QUARTER FROM CAST(d AS DATE))",
        "CREATE MACRO DAX_WEEKNUM(d) AS EXTRACT(WEEK FROM CAST(d AS DATE))",
        # EDATE(start_date, months)
        "CREATE MACRO DAX_EDATE(d, m) AS CAST(CAST(d AS DATE) + INTERVAL (CAST(m AS INTEGER)) MONTH AS DATE)",
        # EOMONTH(start_date, months)
        "CREATE MACRO DAX_EOMONTH(d, m) AS "
        "CAST(LAST_DAY(CAST(CAST(d AS DATE) + INTERVAL (CAST(m AS INTEGER)) MONTH AS DATE)) AS DATE)",
        # DATEDIFF — replaced by Python UDF (handles unit parameter)
        # DATEVALUE
        "CREATE MACRO DAX_DATEVALUE(t) AS CAST(CAST(t AS VARCHAR) AS DATE)",
        # TIMEVALUE
        "CREATE MACRO DAX_TIMEVALUE(t) AS CAST(CAST(t AS VARCHAR) AS TIME)",
        # TIME(h, m, s)
        "CREATE MACRO DAX_TIME(h, m, s) AS MAKE_TIME(CAST(h AS INTEGER), CAST(m AS INTEGER), CAST(s AS INTEGER))",
        # NETWORKDAYS — replaced by Python UDF below,
        # UTCNOW / UTCTODAY
        "CREATE MACRO DAX_UTCNOW() AS CURRENT_TIMESTAMP",
        "CREATE MACRO DAX_UTCTODAY() AS CURRENT_DATE",
        # YEARFRAC (simplified: actual/365)
        "CREATE MACRO DAX_YEARFRAC(d1, d2) AS "
        "CAST(DATEDIFF('day', CAST(d1 AS DATE), CAST(d2 AS DATE)) AS DOUBLE) / 365.0",
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Info / Type-checking ─────────────────────────────────────────────

def _register_info_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        "CREATE MACRO DAX_ISBLANK(v) AS (v IS NULL)",
        "CREATE MACRO DAX_ISERROR(v) AS (TRY_CAST(v AS DOUBLE) IS NULL OR ISNAN(CAST(v AS DOUBLE)) OR ISINF(CAST(v AS DOUBLE)))",
        "CREATE MACRO DAX_ISLOGICAL(v) AS (TYPEOF(v) = 'BOOLEAN')",
        "CREATE MACRO DAX_ISBOOLEAN(v) AS (TYPEOF(v) = 'BOOLEAN')",
        "CREATE MACRO DAX_ISTEXT(v) AS (TYPEOF(v) = 'VARCHAR')",
        "CREATE MACRO DAX_ISSTRING(v) AS (TYPEOF(v) = 'VARCHAR')",
        "CREATE MACRO DAX_ISNONTEXT(v) AS (TYPEOF(v) != 'VARCHAR')",
        "CREATE MACRO DAX_ISNUMBER(v) AS "
        "(TYPEOF(v) IN ('INTEGER', 'BIGINT', 'DOUBLE', 'FLOAT', 'DECIMAL', 'HUGEINT', 'SMALLINT', 'TINYINT'))",
        "CREATE MACRO DAX_ISNUMERIC(v) AS "
        "(TYPEOF(v) IN ('INTEGER', 'BIGINT', 'DOUBLE', 'FLOAT', 'DECIMAL', 'HUGEINT', 'SMALLINT', 'TINYINT'))",
        "CREATE MACRO DAX_ISINTEGER(v) AS "
        "(TYPEOF(v) IN ('INTEGER', 'BIGINT', 'HUGEINT', 'SMALLINT', 'TINYINT'))",
        "CREATE MACRO DAX_ISINT64(v) AS (TYPEOF(v) IN ('INTEGER', 'BIGINT', 'HUGEINT', 'SMALLINT', 'TINYINT'))",
        "CREATE MACRO DAX_ISDOUBLE(v) AS (TYPEOF(v) = 'DOUBLE')",
        "CREATE MACRO DAX_ISDECIMAL(v) AS (TYPEOF(v) LIKE 'DECIMAL%')",
        "CREATE MACRO DAX_ISCURRENCY(v) AS (TYPEOF(v) LIKE 'DECIMAL%')",
        "CREATE MACRO DAX_ISDATETIME(v) AS "
        "(TYPEOF(v) IN ('DATE', 'TIMESTAMP', 'TIMESTAMP WITH TIME ZONE'))",
        # ISINSCOPE - always false in our context
        "CREATE MACRO DAX_ISINSCOPE(col) AS FALSE",
        # CUSTOMDATA - returns empty string
        "CREATE MACRO DAX_CUSTOMDATA() AS ''",
        # USERNAME/USERPRINCIPALNAME/USEROBJECTID/USERCULTURE
        "CREATE MACRO DAX_USERNAME() AS 'anonymous'",
        "CREATE MACRO DAX_USERPRINCIPALNAME() AS 'anonymous@local'",
        "CREATE MACRO DAX_USEROBJECTID() AS 'S-1-5-21-0000000000-0000000000-0000000000-1001'",
        "CREATE MACRO DAX_USERCULTURE() AS 'en-US'",
        # EVALUATEANDLOG
        "CREATE MACRO DAX_EVALUATEANDLOG(v) AS v",
        # COALESCE (DAX version)
        "CREATE MACRO DAX_COALESCE(a, b) AS COALESCE(a, b)",
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Statistics ───────────────────────────────────────────────────────

def _register_stat_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        # STDEV.S / STDEV.P (aggregate versions)
        "CREATE MACRO DAX_STDEV_S(col) AS STDDEV_SAMP(CAST(col AS DOUBLE))",
        "CREATE MACRO DAX_STDEV_P(col) AS STDDEV_POP(CAST(col AS DOUBLE))",
        # VAR.S / VAR.P
        "CREATE MACRO DAX_VAR_S(col) AS VAR_SAMP(CAST(col AS DOUBLE))",
        "CREATE MACRO DAX_VAR_P(col) AS VAR_POP(CAST(col AS DOUBLE))",
        # PERCENTILE.INC / PERCENTILE.EXC — replaced by Python UDFs below,
        # RANK.EQ — replaced by Python UDF below,
        # MEDIAN
        "CREATE MACRO DAX_MEDIAN(col) AS MEDIAN(CAST(col AS DOUBLE))",
        # GEOMEAN
        "CREATE MACRO DAX_GEOMEAN(col) AS EXP(AVG(LN(CAST(col AS DOUBLE))))",
        # COUNTA
        "CREATE MACRO DAX_COUNTA(col) AS COUNT(col)",
        "CREATE MACRO DAX_COUNTAX(col) AS COUNT(col)",
        # COUNTBLANK
        "CREATE MACRO DAX_COUNTBLANK(col) AS SUM(CASE WHEN col IS NULL OR CAST(col AS VARCHAR) = '' THEN 1 ELSE 0 END)",
        # DISTINCTCOUNTNOBLANK
        "CREATE MACRO DAX_DISTINCTCOUNTNOBLANK(col) AS COUNT(DISTINCT col)",
        # APPROXIMATEDISTINCTCOUNT
        "CREATE MACRO DAX_APPROXIMATEDISTINCTCOUNT(col) AS APPROX_COUNT_DISTINCT(col)",
        # MAXA/MINA (treat booleans: TRUE=1, FALSE=0)
        "CREATE MACRO DAX_MAXA(col) AS MAX(col)",
        "CREATE MACRO DAX_MINA(col) AS MIN(col)",
        # MAXX/MINX (iterator versions)
        "CREATE MACRO DAX_MAXX(expr) AS MAX(CAST(expr AS DOUBLE))",
        "CREATE MACRO DAX_MINX(expr) AS MIN(CAST(expr AS DOUBLE))",
        # PRODUCT (aggregate: multiply all values)
        "CREATE MACRO DAX_PRODUCT(col) AS EXP(SUM(LN(ABS(CAST(col AS DOUBLE))))) * "
        "CASE WHEN SUM(CASE WHEN CAST(col AS DOUBLE) < 0 THEN 1 ELSE 0 END) % 2 = 1 THEN -1 ELSE 1 END",
        # Distribution inverse functions — replaced by Python UDFs
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Financial ────────────────────────────────────────────────────────

def _register_financial_macros(con: duckdb.DuckDBPyConnection) -> None:
    """Register financial function macros.

    Many of these are complex; we provide basic implementations for the
    most common functions and stubs for less common ones.
    """
    macros = [
        # PMT(rate, nper, pv, fv, type)
        "CREATE MACRO DAX_PMT(rate, nper, pv) AS "
        "CASE WHEN rate = 0 THEN -CAST(pv AS DOUBLE) / CAST(nper AS DOUBLE) "
        "ELSE CAST(rate AS DOUBLE) * CAST(pv AS DOUBLE) * "
        "POWER(1 + CAST(rate AS DOUBLE), CAST(nper AS DOUBLE)) / "
        "(POWER(1 + CAST(rate AS DOUBLE), CAST(nper AS DOUBLE)) - 1) * -1 "
        "END",

        # FV(rate, nper, pmt, pv, type)
        "CREATE MACRO DAX_FV(rate, nper, pmt) AS "
        "CASE WHEN rate = 0 THEN -(CAST(pmt AS DOUBLE) * CAST(nper AS DOUBLE)) "
        "ELSE -CAST(pmt AS DOUBLE) * (POWER(1 + CAST(rate AS DOUBLE), CAST(nper AS DOUBLE)) - 1) / CAST(rate AS DOUBLE) "
        "END",

        # PV(rate, nper, pmt, fv, type)
        "CREATE MACRO DAX_PV(rate, nper, pmt) AS "
        "CASE WHEN rate = 0 THEN -(CAST(pmt AS DOUBLE) * CAST(nper AS DOUBLE)) "
        "ELSE -CAST(pmt AS DOUBLE) * (1 - POWER(1 + CAST(rate AS DOUBLE), -CAST(nper AS DOUBLE))) / CAST(rate AS DOUBLE) "
        "END",

        # IPMT / PPMT — replaced by Python UDFs

        # NPER — replaced by Python UDF below,

        # RATE — replaced by Python UDF below,

        # SLN(cost, salvage, life)
        "CREATE MACRO DAX_SLN(cost, salvage, life) AS "
        "(CAST(cost AS DOUBLE) - CAST(salvage AS DOUBLE)) / CAST(life AS DOUBLE)",

        # SYD(cost, salvage, life, per)
        "CREATE MACRO DAX_SYD(cost, salvage, life, per) AS "
        "(CAST(cost AS DOUBLE) - CAST(salvage AS DOUBLE)) * "
        "(CAST(life AS DOUBLE) - CAST(per AS DOUBLE) + 1) * 2 / "
        "(CAST(life AS DOUBLE) * (CAST(life AS DOUBLE) + 1))",

        # DDB(cost, salvage, life, period, factor)
        "CREATE MACRO DAX_DDB(cost, salvage, life, period) AS "
        "CAST(cost AS DOUBLE) * 2.0 / CAST(life AS DOUBLE) * "
        "POWER(1 - 2.0 / CAST(life AS DOUBLE), CAST(period AS DOUBLE) - 1)",

        # DB / VDB — replaced by Python UDFs

        # PDURATION(rate, pv, fv)
        "CREATE MACRO DAX_PDURATION(rate, pv, fv) AS "
        "(LN(CAST(fv AS DOUBLE)) - LN(CAST(pv AS DOUBLE))) / LN(1 + CAST(rate AS DOUBLE))",

        # RRI(nper, pv, fv)
        "CREATE MACRO DAX_RRI(nper, pv, fv) AS "
        "POWER(CAST(fv AS DOUBLE) / CAST(pv AS DOUBLE), 1.0 / CAST(nper AS DOUBLE)) - 1",

        # EFFECT(rate, nper)
        "CREATE MACRO DAX_EFFECT(rate, nper) AS "
        "POWER(1 + CAST(rate AS DOUBLE) / CAST(nper AS DOUBLE), CAST(nper AS DOUBLE)) - 1",

        # NOMINAL(effect_rate, nper)
        "CREATE MACRO DAX_NOMINAL(eff, nper) AS "
        "(POWER(1 + CAST(eff AS DOUBLE), 1.0 / CAST(nper AS DOUBLE)) - 1) * CAST(nper AS DOUBLE)",

        # DOLLARDE / DOLLARFR — replaced by Python UDFs below,

        # CUMIPMT / CUMPRINC — replaced by Python UDFs
        "CREATE MACRO DAX_ISPMT(rate, per, nper, pv) AS "
        "-CAST(pv AS DOUBLE) * CAST(rate AS DOUBLE) * (1 - CAST(per AS DOUBLE) / CAST(nper AS DOUBLE))",

        # All bond / securities / coupon / depreciation functions — replaced by Python UDFs
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Misc ─────────────────────────────────────────────────────────────

def _register_misc_macros(con: duckdb.DuckDBPyConnection) -> None:
    macros = [
        # PATHCONTAINS
        "CREATE MACRO DAX_PATHCONTAINS(path, item) AS "
        "CONTAINS('|' || CAST(path AS VARCHAR) || '|', '|' || CAST(item AS VARCHAR) || '|')",
        # PATHITEM
        "CREATE MACRO DAX_PATHITEM(path, pos) AS "
        "SPLIT_PART(CAST(path AS VARCHAR), '|', CAST(pos AS INTEGER))",
        # PATHITEMREVERSE
        "CREATE MACRO DAX_PATHITEMREVERSE(path, pos) AS "
        "SPLIT_PART(CAST(path AS VARCHAR), '|', "
        "LENGTH(CAST(path AS VARCHAR)) - LENGTH(REPLACE(CAST(path AS VARCHAR), '|', '')) + 1 - CAST(pos AS INTEGER) + 1)",
        # PATHLENGTH
        "CREATE MACRO DAX_PATHLENGTH(path) AS "
        "LENGTH(CAST(path AS VARCHAR)) - LENGTH(REPLACE(CAST(path AS VARCHAR), '|', '')) + 1",

        # CONTAINSROW - simplified
        "CREATE MACRO DAX_CONTAINSROW(col, val) AS (val IN (SELECT col))",

        # TOCSV / TOJSON - simplified text representations
        "CREATE MACRO DAX_TOCSV(t) AS CAST(t AS VARCHAR)",
        "CREATE MACRO DAX_TOJSON(t) AS CAST(t AS VARCHAR)",

        # HASH
        "CREATE MACRO DAX_HASH(v) AS HASH(v)",

        # IF.EAGER — same as IF (no short-circuit in SQL)
        "CREATE MACRO DAX_IF_EAGER(cond, t, f) AS CASE WHEN cond THEN t ELSE f END",

        # ERROR
        "CREATE MACRO DAX_ERROR(msg) AS NULL",

        # SELECTEDVALUE (simplified)
        "CREATE MACRO DAX_SELECTEDVALUE(col) AS col",

        # HASONEFILTER / HASONEVALUE
        "CREATE MACRO DAX_HASONEFILTER(col) AS FALSE",
        "CREATE MACRO DAX_HASONEVALUE(col) AS FALSE",

        # USERELATIONSHIP / CROSSFILTER - context modifiers, no-op in SQL
        "CREATE MACRO DAX_USERELATIONSHIP(a, b) AS NULL",

        # MOVINGAVERAGE - stub
        "CREATE MACRO DAX_MOVINGAVERAGE(expr, n, date_col) AS NULL",

        # CLOSINGBALANCE / OPENINGBALANCE - time intelligence stubs
        "CREATE MACRO DAX_CLOSINGBALANCEMONTH(expr, date_col) AS NULL",
        "CREATE MACRO DAX_CLOSINGBALANCEQUARTER(expr, date_col) AS NULL",
        "CREATE MACRO DAX_CLOSINGBALANCEYEAR(expr, date_col) AS NULL",
        "CREATE MACRO DAX_CLOSINGBALANCEWEEK(expr, date_col) AS NULL",
        "CREATE MACRO DAX_OPENINGBALANCEMONTH(expr, date_col) AS NULL",
        "CREATE MACRO DAX_OPENINGBALANCEQUARTER(expr, date_col) AS NULL",
        "CREATE MACRO DAX_OPENINGBALANCEYEAR(expr, date_col) AS NULL",
        "CREATE MACRO DAX_OPENINGBALANCEWEEK(expr, date_col) AS NULL",

        # All distribution functions — replaced by Python UDFs
    ]
    for sql in macros:
        _safe_macro(con, sql)


# ── Python UDFs (financial + statistical distributions) ──────────────

def _py_udf(
    con: duckdb.DuckDBPyConnection,
    name: str,
    func,
    params: list,
    ret: str = "DOUBLE",
    *,
    null_handling: str = "special",
) -> None:
    """Register a Python UDF as DAX_{name} and optionally as raw name."""
    dax_name = f"DAX_{name}"
    try:
        con.create_function(dax_name, func, params, ret,
                            null_handling=null_handling)
    except Exception:
        pass  # already registered
    # Register raw-name alias if not a DuckDB builtin
    if name not in _DUCKDB_BUILTINS:
        try:
            con.create_function(name, func, params, ret,
                                null_handling=null_handling)
        except Exception:
            pass


def _register_python_udfs(con: duckdb.DuckDBPyConnection) -> None:
    """Register real Python UDF implementations (no more NULL stubs)."""
    D = "DOUBLE"
    DT = "DATE"
    V = "VARCHAR"
    I = "BIGINT"

    # ── Financial Python UDFs (require enterprise financial module) ──
    if _fin is not None:
        # ── DATEDIFF ──
        def _datediff(d1, d2, intv):
            if d1 is None or d2 is None or intv is None:
                return None
            return _fin.datediff(d1, d2, intv)
        _py_udf(con, "DATEDIFF", _datediff, [DT, DT, V], I)

        # ── CONVERT ──
        def _convert(expr, type_name):
            if expr is None or type_name is None:
                return None
            return _fin.convert(expr, type_name)
        _py_udf(con, "CONVERT", _convert, [D, V], D)

        # ── Financial: loan/TVM ──
        def _ipmt(rate, per, nper, pv):
            if any(x is None for x in (rate, per, nper, pv)):
                return None
            return _fin.ipmt(rate, per, nper, pv)
        _py_udf(con, "IPMT", _ipmt, [D, D, D, D])

        def _ppmt(rate, per, nper, pv):
            if any(x is None for x in (rate, per, nper, pv)):
                return None
            return _fin.ppmt(rate, per, nper, pv)
        _py_udf(con, "PPMT", _ppmt, [D, D, D, D])

        def _cumipmt(rate, nper, pv, sp, ep, typ):
            if any(x is None for x in (rate, nper, pv, sp, ep, typ)):
                return None
            return _fin.cumipmt(rate, nper, pv, int(sp), int(ep), int(typ))
        _py_udf(con, "CUMIPMT", _cumipmt, [D, D, D, D, D, D])

        def _cumprinc(rate, nper, pv, sp, ep, typ):
            if any(x is None for x in (rate, nper, pv, sp, ep, typ)):
                return None
            return _fin.cumprinc(rate, nper, pv, int(sp), int(ep), int(typ))
        _py_udf(con, "CUMPRINC", _cumprinc, [D, D, D, D, D, D])

        # ── Financial: NPER (Python UDF — more robust than SQL macro) ──
        def _nper(rate, pmt_val, pv):
            if any(x is None for x in (rate, pmt_val, pv)):
                return None
            return _fin.nper_func(rate, pmt_val, pv)
        _py_udf(con, "NPER", _nper, [D, D, D])

        # ── Financial: RATE (Newton-Raphson) ──
        def _rate(nper, pmt_val, pv):
            if any(x is None for x in (nper, pmt_val, pv)):
                return None
            return _fin.rate_func(nper, pmt_val, pv)
        _py_udf(con, "RATE", _rate, [D, D, D])

        # ── Financial: DOLLARDE / DOLLARFR ──
        def _dollarde(frac, denom):
            if any(x is None for x in (frac, denom)):
                return None
            return _fin.dollarde(frac, denom)
        _py_udf(con, "DOLLARDE", _dollarde, [D, D])

        def _dollarfr(dec_val, denom):
            if any(x is None for x in (dec_val, denom)):
                return None
            return _fin.dollarfr(dec_val, denom)
        _py_udf(con, "DOLLARFR", _dollarfr, [D, D])

        # ── Date: NETWORKDAYS (Python UDF) ──
        def _networkdays(d1, d2):
            if d1 is None or d2 is None:
                return None
            return _fin.networkdays(d1, d2)
        _py_udf(con, "NETWORKDAYS", _networkdays, [DT, DT], I)

    # ── Text: FIXED (with thousand separators) ──
    def _fixed(n, d, no_commas):
        if n is None:
            return None
        d = int(d) if d is not None else 2
        no_commas = int(no_commas) if no_commas is not None else 0
        rounded = round(float(n), d)
        if d <= 0:
            formatted = str(int(rounded))
        else:
            formatted = f"{rounded:.{d}f}"
        if not no_commas:
            # Add thousand separators to integer part
            parts = formatted.split(".")
            int_part = parts[0]
            sign = ""
            if int_part.startswith("-"):
                sign = "-"
                int_part = int_part[1:]
            # Insert commas
            groups = []
            while len(int_part) > 3:
                groups.append(int_part[-3:])
                int_part = int_part[:-3]
            groups.append(int_part)
            int_part = ",".join(reversed(groups))
            formatted = sign + int_part
            if len(parts) > 1:
                formatted += "." + parts[1]
        return formatted
    _py_udf(con, "FIXED", _fixed, [D, D, D], V)

    # ── Text: FORMAT (basic number formatting) ──
    def _format(v, fmt_str):
        if v is None:
            return None
        if fmt_str is None:
            return str(v)
        fmt = str(fmt_str).strip()
        # Basic number format patterns
        import re as _re
        # "#,##0.00" style patterns
        m = _re.match(r'^[#0,]+\.?(0*)$', fmt)
        if m:
            has_comma = ',' in fmt
            decimal_part = fmt.split('.')[-1] if '.' in fmt else ''
            decimals = len(decimal_part)
            val = float(v)
            if decimals > 0:
                formatted = f"{val:.{decimals}f}"
            else:
                formatted = str(int(round(val)))
            if has_comma:
                parts = formatted.split(".")
                int_part = parts[0]
                sign = ""
                if int_part.startswith("-"):
                    sign = "-"
                    int_part = int_part[1:]
                groups = []
                while len(int_part) > 3:
                    groups.append(int_part[-3:])
                    int_part = int_part[:-3]
                groups.append(int_part)
                int_part = ",".join(reversed(groups))
                formatted = sign + int_part
                if len(parts) > 1:
                    formatted += "." + parts[1]
            return formatted
        # Percent format
        if '%' in fmt:
            return f"{float(v) * 100:.2f}%"
        # Fallback
        return str(v)
    # Register numeric FORMAT as DAX_FORMAT_NUM (overloading dispatch via macro)
    _py_udf(con, "FORMAT_NUM", _format, [D, V], V)

    # ── Text: FORMAT for DATE/TIMESTAMP values ──
    def _format_date(v, fmt_str):
        """FORMAT(date_value, format_string) — DAX date formatting.

        Supports common DAX date format patterns:
        YYYYMMDD, YYYY, MM, DD, Q, mmm, mmmm, ddd, dddd, etc.
        """
        if v is None:
            return None
        if fmt_str is None:
            return str(v)
        import datetime as _dt
        # Coerce to Python datetime
        if isinstance(v, _dt.date) and not isinstance(v, _dt.datetime):
            d = _dt.datetime(v.year, v.month, v.day)
        elif isinstance(v, _dt.datetime):
            d = v
        else:
            try:
                d = _dt.datetime.fromisoformat(str(v))
            except Exception:
                return str(v)
        fmt = str(fmt_str).strip()
        fu = fmt.upper()
        # Common single-token patterns (fast path)
        if fu == "YYYYMMDD":
            return d.strftime("%Y%m%d")
        if fu == "YYYY":
            return str(d.year)
        if fu == "MM":
            return f"{d.month:02d}"
        if fu == "DD":
            return f"{d.day:02d}"
        if fu == "Q":
            return str((d.month - 1) // 3 + 1)
        # Case-sensitive patterns: mmm/mmmm for month names, ddd/dddd for day names
        if fmt == "mmm":
            return d.strftime("%b")
        if fmt == "mmmm":
            return d.strftime("%B")
        if fmt == "ddd":
            return d.strftime("%a")
        if fmt == "dddd":
            return d.strftime("%A")
        # Composite pattern: replace tokens in the format string
        result = fmt
        result = result.replace("YYYY", str(d.year))
        result = result.replace("yyyy", str(d.year))
        result = result.replace("MM", f"{d.month:02d}")
        result = result.replace("DD", f"{d.day:02d}")
        result = result.replace("dd", f"{d.day:02d}")
        result = result.replace("HH", f"{d.hour:02d}")
        result = result.replace("hh", f"{d.hour:02d}")
        result = result.replace("mm", f"{d.minute:02d}")
        result = result.replace("ss", f"{d.second:02d}")
        # Quarter
        if "Q" in result:
            result = result.replace("Q", str((d.month - 1) // 3 + 1))
        return result
    _py_udf(con, "FORMAT_DATE", _format_date, ["TIMESTAMP", V], V)

    # ── FORMAT / DAX_FORMAT dispatch macros (typeof-based) ──
    # DuckDB Python UDFs don't support overloading by parameter type,
    # so we use SQL macros to dispatch based on typeof().
    for macro_name in ("FORMAT", "DAX_FORMAT"):
        _safe_macro(con, f"""
            CREATE OR REPLACE MACRO {macro_name}(x, fmt) AS (
                CASE
                    WHEN typeof(x) IN ('DATE', 'TIMESTAMP', 'TIMESTAMP WITH TIME ZONE',
                                       'TIMESTAMP_S', 'TIMESTAMP_MS', 'TIMESTAMP_NS')
                    THEN DAX_FORMAT_DATE(CAST(x AS TIMESTAMP), fmt)
                    ELSE DAX_FORMAT_NUM(CAST(x AS DOUBLE), fmt)
                END
            )
        """)

    # ── Financial: depreciation (require enterprise financial module) ──
    if _fin is not None:
        def _db(cost, salvage, life, period):
            if any(x is None for x in (cost, salvage, life, period)):
                return None
            return _fin.db(cost, salvage, int(life), int(period))
        _py_udf(con, "DB", _db, [D, D, D, D])

        def _vdb(cost, salvage, life, sp, ep):
            if any(x is None for x in (cost, salvage, life, sp, ep)):
                return None
            return _fin.vdb(cost, salvage, life, sp, ep)
        _py_udf(con, "VDB", _vdb, [D, D, D, D, D])

        # ── Financial: securities ──
        def _disc(settle, mat, pr, red):
            if any(x is None for x in (settle, mat, pr, red)):
                return None
            return _fin.disc(settle, mat, pr, red)
        _py_udf(con, "DISC", _disc, [DT, DT, D, D])

        def _intrate(settle, mat, inv, red):
            if any(x is None for x in (settle, mat, inv, red)):
                return None
            return _fin.intrate(settle, mat, inv, red)
        _py_udf(con, "INTRATE", _intrate, [DT, DT, D, D])

        def _received(settle, mat, inv, disc_r):
            if any(x is None for x in (settle, mat, inv, disc_r)):
                return None
            return _fin.received(settle, mat, inv, disc_r)
        _py_udf(con, "RECEIVED", _received, [DT, DT, D, D])

        def _tbillprice(settle, mat, disc_r):
            if any(x is None for x in (settle, mat, disc_r)):
                return None
            return _fin.tbillprice(settle, mat, disc_r)
        _py_udf(con, "TBILLPRICE", _tbillprice, [DT, DT, D])

        def _tbilleq(settle, mat, disc_r):
            if any(x is None for x in (settle, mat, disc_r)):
                return None
            return _fin.tbilleq(settle, mat, disc_r)
        _py_udf(con, "TBILLEQ", _tbilleq, [DT, DT, D])

        def _tbillyield(settle, mat, pr):
            if any(x is None for x in (settle, mat, pr)):
                return None
            return _fin.tbillyield(settle, mat, pr)
        _py_udf(con, "TBILLYIELD", _tbillyield, [DT, DT, D])

        def _pricedisc(settle, mat, disc_r, red):
            if any(x is None for x in (settle, mat, disc_r, red)):
                return None
            return _fin.pricedisc(settle, mat, disc_r, red)
        _py_udf(con, "PRICEDISC", _pricedisc, [DT, DT, D, D])

        def _pricemat(settle, mat, issue, rate, yld):
            if any(x is None for x in (settle, mat, issue, rate, yld)):
                return None
            return _fin.pricemat(settle, mat, issue, rate, yld)
        _py_udf(con, "PRICEMAT", _pricemat, [DT, DT, DT, D, D])

        def _price(settle, mat, rate, yld, red, freq):
            if any(x is None for x in (settle, mat, rate, yld, red, freq)):
                return None
            return _fin.price(settle, mat, rate, yld, red, int(freq))
        _py_udf(con, "PRICE", _price, [DT, DT, D, D, D, D])

        def _yield_f(settle, mat, rate, pr, red, freq):
            if any(x is None for x in (settle, mat, rate, pr, red, freq)):
                return None
            return _fin.yield_func(settle, mat, rate, pr, red, int(freq))
        _py_udf(con, "YIELD", _yield_f, [DT, DT, D, D, D, D])

        def _yielddisc(settle, mat, pr, red):
            if any(x is None for x in (settle, mat, pr, red)):
                return None
            return _fin.yielddisc(settle, mat, pr, red)
        _py_udf(con, "YIELDDISC", _yielddisc, [DT, DT, D, D])

        def _yieldmat(settle, mat, issue, rate, pr):
            if any(x is None for x in (settle, mat, issue, rate, pr)):
                return None
            return _fin.yieldmat(settle, mat, issue, rate, pr)
        _py_udf(con, "YIELDMAT", _yieldmat, [DT, DT, DT, D, D])

        def _duration(settle, mat, coup, yld, freq):
            if any(x is None for x in (settle, mat, coup, yld, freq)):
                return None
            return _fin.duration(settle, mat, coup, yld, int(freq))
        _py_udf(con, "DURATION", _duration, [DT, DT, D, D, D])

        def _mduration(settle, mat, coup, yld, freq):
            if any(x is None for x in (settle, mat, coup, yld, freq)):
                return None
            return _fin.mduration(settle, mat, coup, yld, int(freq))
        _py_udf(con, "MDURATION", _mduration, [DT, DT, D, D, D])

        # ── Financial: coupon functions ──
        def _coupdaybs(settle, mat, freq):
            if any(x is None for x in (settle, mat, freq)):
                return None
            return float(_fin.coupdaybs(settle, mat, int(freq)))
        _py_udf(con, "COUPDAYBS", _coupdaybs, [DT, DT, D])

        def _coupdays(settle, mat, freq):
            if any(x is None for x in (settle, mat, freq)):
                return None
            return float(_fin.coupdays(settle, mat, int(freq)))
        _py_udf(con, "COUPDAYS", _coupdays, [DT, DT, D])

        def _coupdaysnc(settle, mat, freq):
            if any(x is None for x in (settle, mat, freq)):
                return None
            return float(_fin.coupdaysnc(settle, mat, int(freq)))
        _py_udf(con, "COUPDAYSNC", _coupdaysnc, [DT, DT, D])

        def _coupncd(settle, mat, freq):
            if any(x is None for x in (settle, mat, freq)):
                return None
            r = _fin.coupncd(settle, mat, int(freq))
            return r
        _py_udf(con, "COUPNCD", _coupncd, [DT, DT, D], DT)

        def _coupnum(settle, mat, freq):
            if any(x is None for x in (settle, mat, freq)):
                return None
            return float(_fin.coupnum(settle, mat, int(freq)))
        _py_udf(con, "COUPNUM", _coupnum, [DT, DT, D])

        def _couppcd(settle, mat, freq):
            if any(x is None for x in (settle, mat, freq)):
                return None
            r = _fin.couppcd(settle, mat, int(freq))
            return r
        _py_udf(con, "COUPPCD", _couppcd, [DT, DT, D], DT)

        # ── Financial: accrued interest ──
        def _accrint(issue, first, settle, rate, par, freq):
            if any(x is None for x in (issue, first, settle, rate, par, freq)):
                return None
            return _fin.accrint(issue, first, settle, rate, par, int(freq))
        _py_udf(con, "ACCRINT", _accrint, [DT, DT, DT, D, D, D])

        def _accrintm(issue, settle, rate, par):
            if any(x is None for x in (issue, settle, rate, par)):
                return None
            return _fin.accrintm(issue, settle, rate, par)
        _py_udf(con, "ACCRINTM", _accrintm, [DT, DT, D, D])

        # ── Financial: French depreciation ──
        def _amordegrc(cost, purchase, first, salvage, per, rate):
            if any(x is None for x in (cost, purchase, first, salvage, per, rate)):
                return None
            return _fin.amordegrc(cost, purchase, first, salvage, int(per), rate)
        _py_udf(con, "AMORDEGRC", _amordegrc, [D, DT, DT, D, D, D])

        def _amorlinc(cost, purchase, first, salvage, per, rate):
            if any(x is None for x in (cost, purchase, first, salvage, per, rate)):
                return None
            return _fin.amorlinc(cost, purchase, first, salvage, int(per), rate)
        _py_udf(con, "AMORLINC", _amorlinc, [D, DT, DT, D, D, D])

        # ── Financial: odd-period bonds ──
        def _oddfprice(s, m, i, fc, r, y, re, f):
            if any(x is None for x in (s, m, i, fc, r, y, re, f)):
                return None
            return _fin.oddfprice(s, m, i, fc, r, y, re, int(f))
        _py_udf(con, "ODDFPRICE", _oddfprice, [DT, DT, DT, DT, D, D, D, D])

        def _oddfyield(s, m, i, fc, r, p, re, f):
            if any(x is None for x in (s, m, i, fc, r, p, re, f)):
                return None
            return _fin.oddfyield(s, m, i, fc, r, p, re, int(f))
        _py_udf(con, "ODDFYIELD", _oddfyield, [DT, DT, DT, DT, D, D, D, D])

        def _oddlprice(s, m, li, r, y, re, f):
            if any(x is None for x in (s, m, li, r, y, re, f)):
                return None
            return _fin.oddlprice(s, m, li, r, y, re, int(f))
        _py_udf(con, "ODDLPRICE", _oddlprice, [DT, DT, DT, D, D, D, D])

        def _oddlyield(s, m, li, r, p, re, f):
            if any(x is None for x in (s, m, li, r, p, re, f)):
                return None
            return _fin.oddlyield(s, m, li, r, p, re, int(f))
        _py_udf(con, "ODDLYIELD", _oddlyield, [DT, DT, DT, D, D, D, D])

    # ── Financial: misc helpers (only register if SQL macro not present) ──
    # PDURATION, RRI, EFFECT, NOMINAL, DOLLARDE, DOLLARFR already have
    # working SQL macros — skip Python UDF registration for these.

    # ── Statistical distributions ──
    def _norm_dist(x, mu, sigma, cum):
        if any(v is None for v in (x, mu, sigma, cum)):
            return None
        return _dist.dax_norm_dist(x, mu, sigma, cum)
    _py_udf(con, "NORM_DIST", _norm_dist, [D, D, D, D])

    def _norm_s_dist(z, cum):
        if any(v is None for v in (z, cum)):
            return None
        return _dist.dax_norm_s_dist(z, cum)
    _py_udf(con, "NORM_S_DIST", _norm_s_dist, [D, D])

    def _norm_inv(p, mu, sigma):
        if any(v is None for v in (p, mu, sigma)):
            return None
        return _dist.dax_norm_inv(p, mu, sigma)
    _py_udf(con, "NORM_INV", _norm_inv, [D, D, D])

    def _norm_s_inv(p):
        if p is None:
            return None
        return _dist.dax_norm_s_inv(p)
    _py_udf(con, "NORM_S_INV", _norm_s_inv, [D])

    def _t_dist(x, df, cum):
        if any(v is None for v in (x, df, cum)):
            return None
        return _dist.dax_t_dist(x, df, cum)
    _py_udf(con, "T_DIST", _t_dist, [D, D, D])

    def _t_dist_2t(x, df):
        if any(v is None for v in (x, df)):
            return None
        return _dist.dax_t_dist_2t(x, df)
    _py_udf(con, "T_DIST_2T", _t_dist_2t, [D, D])

    def _t_dist_rt(x, df):
        if any(v is None for v in (x, df)):
            return None
        return _dist.dax_t_dist_rt(x, df)
    _py_udf(con, "T_DIST_RT", _t_dist_rt, [D, D])

    def _t_inv(p, df):
        if any(v is None for v in (p, df)):
            return None
        return _dist.dax_t_inv(p, df)
    _py_udf(con, "T_INV", _t_inv, [D, D])

    def _t_inv_2t(p, df):
        if any(v is None for v in (p, df)):
            return None
        return _dist.dax_t_inv_2t(p, df)
    _py_udf(con, "T_INV_2T", _t_inv_2t, [D, D])

    def _chisq_dist(x, df, cum):
        if any(v is None for v in (x, df, cum)):
            return None
        return _dist.dax_chisq_dist(x, df, cum)
    _py_udf(con, "CHISQ_DIST", _chisq_dist, [D, D, D])

    def _chisq_dist_rt(x, df):
        if any(v is None for v in (x, df)):
            return None
        return _dist.dax_chisq_dist_rt(x, df)
    _py_udf(con, "CHISQ_DIST_RT", _chisq_dist_rt, [D, D])

    def _chisq_inv(p, df):
        if any(v is None for v in (p, df)):
            return None
        return _dist.dax_chisq_inv(p, df)
    _py_udf(con, "CHISQ_INV", _chisq_inv, [D, D])

    def _chisq_inv_rt(p, df):
        if any(v is None for v in (p, df)):
            return None
        return _dist.dax_chisq_inv_rt(p, df)
    _py_udf(con, "CHISQ_INV_RT", _chisq_inv_rt, [D, D])

    def _beta_dist(x, a, b, cum):
        if any(v is None for v in (x, a, b, cum)):
            return None
        return _dist.dax_beta_dist(x, a, b, cum)
    _py_udf(con, "BETA_DIST", _beta_dist, [D, D, D, D])

    def _beta_inv(p, a, b):
        if any(v is None for v in (p, a, b)):
            return None
        return _dist.dax_beta_inv(p, a, b)
    _py_udf(con, "BETA_INV", _beta_inv, [D, D, D])

    def _poisson_dist(x, mu, cum):
        if any(v is None for v in (x, mu, cum)):
            return None
        return _dist.dax_poisson_dist(x, mu, cum)
    _py_udf(con, "POISSON_DIST", _poisson_dist, [D, D, D])

    def _expon_dist(x, lam, cum):
        if any(v is None for v in (x, lam, cum)):
            return None
        return _dist.dax_expon_dist(x, lam, cum)
    _py_udf(con, "EXPON_DIST", _expon_dist, [D, D, D])

    def _confidence_norm(alpha, stdev, n):
        if any(v is None for v in (alpha, stdev, n)):
            return None
        return _dist.dax_confidence_norm(alpha, stdev, n)
    _py_udf(con, "CONFIDENCE_NORM", _confidence_norm, [D, D, D])

    def _confidence_t(alpha, stdev, n):
        if any(v is None for v in (alpha, stdev, n)):
            return None
        return _dist.dax_confidence_t(alpha, stdev, n)
    _py_udf(con, "CONFIDENCE_T", _confidence_t, [D, D, D])

    # CEILING / FLOOR already have working SQL macros — skip
