# DAX → DuckDB SQL mapping

This repo is a **compiler**: every DAX function must compile. `sql_template` is the **authoritative** lowering target; `example_sql` is **parse-safe** for sqlglot syntax validation.

Functions covered: **481**

## Legend

- **direct_sql_fn**: emitted as a DuckDB SQL call/operator
- **case_rewrite**: emitted as `CASE WHEN ...`
- **subquery_rewrite**: emitted as `SELECT ...` / derived table
- **window_rewrite**: emitted as `... OVER (...)`
- **context_rewrite**: rewrites filter/join context; disappears from final SQL
- **generic_fallback**: emitted as `DAX_<NAME>(args...)` to guarantee syntactic validity

## Full mapping

| DAX function | Kind | Strategy | Verified DuckDB | SQL template (authoritative) | Example DAX | Example SQL (parse-safe) |
|---|---|---|:---:|---|---|---|
| ABS | scalar | direct_sql_fn | true | `ABS({args})` | `ABS(1)` | `ABS(1)` |
| ACCRINT | scalar | generic_fallback | false | `DAX_ACCRINT({args})` | `ACCRINT(1)` | `DAX_ACCRINT(1)` |
| ACCRINTM | scalar | generic_fallback | false | `DAX_ACCRINTM({args})` | `ACCRINTM(1)` | `DAX_ACCRINTM(1)` |
| ACOS | scalar | direct_sql_fn | true | `ACOS({args})` | `ACOS(1)` | `ACOS(1)` |
| ACOSH | scalar | direct_sql_fn | true | `ACOSH({args})` | `ACOSH(1)` | `ACOSH(1)` |
| ACOT | scalar | generic_fallback | false | `DAX_ACOT({args})` | `ACOT(1)` | `DAX_ACOT(1)` |
| ACOTH | scalar | generic_fallback | false | `DAX_ACOTH({args})` | `ACOTH(1)` | `DAX_ACOTH(1)` |
| ADDCOLUMNS | table | subquery_rewrite | true | `(SELECT t.*, {{expr}} AS {{name}} FROM {{table}} AS t)` | `ADDCOLUMNS(Sales, "Amount2", Sales[Amount] * 2)` | `SELECT t.*, (t.Amount * 2) AS Amount2 FROM Sales AS t` |
| ADDMISSINGITEMS | table | subquery_rewrite | false | `(SELECT * FROM DAX_ADDMISSINGITEMS({args}) AS t)` | `ADDMISSINGITEMS(1)` | `(SELECT * FROM DAX_ADDMISSINGITEMS(1) AS t)` |
| ALL | context | context_rewrite | false | `<context_rewrite>` | `ALL(SUM(Sales[Amount]))` | `SELECT 1` |
| ALLCROSSFILTERED | context | context_rewrite | false | `<context_rewrite>` | `ALLCROSSFILTERED(SUM(Sales[Amount]))` | `SELECT 1` |
| ALLEXCEPT | context | context_rewrite | false | `<context_rewrite>` | `ALLEXCEPT(SUM(Sales[Amount]))` | `SELECT 1` |
| ALLNOBLANKROW | context | context_rewrite | false | `<context_rewrite>` | `ALLNOBLANKROW(SUM(Sales[Amount]))` | `SELECT 1` |
| ALLSELECTED | context | context_rewrite | false | `<context_rewrite>` | `ALLSELECTED(SUM(Sales[Amount]))` | `SELECT 1` |
| ALLSELECTEDAPPLY | context | context_rewrite | false | `<context_rewrite>` | `ALLSELECTEDAPPLY(SUM(Sales[Amount]))` | `SELECT 1` |
| ALLSELECTEDREMOVE | context | context_rewrite | false | `<context_rewrite>` | `ALLSELECTEDREMOVE(SUM(Sales[Amount]))` | `SELECT 1` |
| ALWAYSAPPLY | context | context_rewrite | false | `<context_rewrite>` | `ALWAYSAPPLY(SUM(Sales[Amount]))` | `SELECT 1` |
| AMORDEGRC | scalar | generic_fallback | false | `DAX_AMORDEGRC({args})` | `AMORDEGRC(1)` | `DAX_AMORDEGRC(1)` |
| AMORLINC | scalar | generic_fallback | false | `DAX_AMORLINC({args})` | `AMORLINC(1)` | `DAX_AMORLINC(1)` |
| AND | scalar | direct_sql_fn | true | `({{a}} AND {{b}})` | `AND(TRUE(), FALSE())` | `(TRUE AND FALSE)` |
| APPROXIMATEDISTINCTCOUNT | scalar | generic_fallback | false | `DAX_APPROXIMATEDISTINCTCOUNT({args})` | `APPROXIMATEDISTINCTCOUNT(1)` | `DAX_APPROXIMATEDISTINCTCOUNT(1)` |
| ASIN | scalar | direct_sql_fn | true | `ASIN({args})` | `ASIN(1)` | `ASIN(1)` |
| ASINH | scalar | direct_sql_fn | true | `ASINH({args})` | `ASINH(1)` | `ASINH(1)` |
| ATAN | scalar | direct_sql_fn | true | `ATAN({args})` | `ATAN(1)` | `ATAN(1)` |
| ATANH | scalar | direct_sql_fn | true | `ATANH({args})` | `ATANH(1)` | `ATANH(1)` |
| AVERAGE | agg | direct_sql_fn | true | `AVG({{x}})` | `AVERAGE(Sales[Amount])` | `AVG(Sales.Amount)` |
| AVERAGEA | agg | direct_sql_fn | true | `AVG({x})` | `AVERAGEA(Sales[Amount])` | `AVG(Sales.Amount)` |
| AVERAGEX | iterator | subquery_rewrite | true | `(SELECT AVG({expr}) FROM {table})` | `AVERAGEX(Sales, Sales[Amount])` | `(SELECT AVG(Sales.Amount) FROM Sales)` |
| BETA.DIST | scalar | generic_fallback | false | `DAX_BETA_DIST({args})` | `BETA.DIST(1)` | `DAX_BETA_DIST(1)` |
| BETA.INV | scalar | generic_fallback | false | `DAX_BETA_INV({args})` | `BETA.INV(1)` | `DAX_BETA_INV(1)` |
| BITAND | scalar | generic_fallback | false | `DAX_BITAND({args})` | `BITAND(1)` | `DAX_BITAND(1)` |
| BITLSHIFT | scalar | generic_fallback | false | `DAX_BITLSHIFT({args})` | `BITLSHIFT(1)` | `DAX_BITLSHIFT(1)` |
| BITOR | scalar | generic_fallback | false | `DAX_BITOR({args})` | `BITOR(1)` | `DAX_BITOR(1)` |
| BITRSHIFT | scalar | generic_fallback | false | `DAX_BITRSHIFT({args})` | `BITRSHIFT(1)` | `DAX_BITRSHIFT(1)` |
| BITXOR | scalar | generic_fallback | false | `DAX_BITXOR({args})` | `BITXOR(1)` | `DAX_BITXOR(1)` |
| BLANK | scalar | direct_sql_fn | true | `NULL` | `BLANK()` | `NULL` |
| CALCULATE | context | context_rewrite | false | `<context_rewrite>` | `CALCULATE(SUM(Sales[Amount]))` | `SELECT 1` |
| CALCULATETABLE | context | context_rewrite | false | `<context_rewrite>` | `CALCULATETABLE(SUM(Sales[Amount]))` | `SELECT 1` |
| CALENDAR | table | subquery_rewrite | false | `(SELECT * FROM DAX_CALENDAR({args}) AS t)` | `CALENDAR(1)` | `(SELECT * FROM DAX_CALENDAR(1) AS t)` |
| CALENDARAUTO | table | subquery_rewrite | false | `(SELECT * FROM DAX_CALENDARAUTO({args}) AS t)` | `CALENDARAUTO(1)` | `(SELECT * FROM DAX_CALENDARAUTO(1) AS t)` |
| CEILING | scalar | direct_sql_fn | true | `CEIL({args})` | `CEILING(1)` | `CEIL(1)` |
| CHISQ.DIST | scalar | generic_fallback | false | `DAX_CHISQ_DIST({args})` | `CHISQ.DIST(1)` | `DAX_CHISQ_DIST(1)` |
| CHISQ.DIST.RT | scalar | generic_fallback | false | `DAX_CHISQ_DIST_RT({args})` | `CHISQ.DIST.RT(1)` | `DAX_CHISQ_DIST_RT(1)` |
| CHISQ.INV | scalar | generic_fallback | false | `DAX_CHISQ_INV({args})` | `CHISQ.INV(1)` | `DAX_CHISQ_INV(1)` |
| CHISQ.INV.RT | scalar | generic_fallback | false | `DAX_CHISQ_INV_RT({args})` | `CHISQ.INV.RT(1)` | `DAX_CHISQ_INV_RT(1)` |
| CLOSINGBALANCEMONTH | scalar | generic_fallback | false | `DAX_CLOSINGBALANCEMONTH({args})` | `CLOSINGBALANCEMONTH(1)` | `DAX_CLOSINGBALANCEMONTH(1)` |
| CLOSINGBALANCEQUARTER | scalar | generic_fallback | false | `DAX_CLOSINGBALANCEQUARTER({args})` | `CLOSINGBALANCEQUARTER(1)` | `DAX_CLOSINGBALANCEQUARTER(1)` |
| CLOSINGBALANCEWEEK | scalar | generic_fallback | false | `DAX_CLOSINGBALANCEWEEK({args})` | `CLOSINGBALANCEWEEK(1)` | `DAX_CLOSINGBALANCEWEEK(1)` |
| CLOSINGBALANCEYEAR | scalar | generic_fallback | false | `DAX_CLOSINGBALANCEYEAR({args})` | `CLOSINGBALANCEYEAR(1)` | `DAX_CLOSINGBALANCEYEAR(1)` |
| COALESCE | scalar | generic_fallback | false | `DAX_COALESCE({args})` | `COALESCE(1)` | `DAX_COALESCE(1)` |
| COLLAPSE | scalar | generic_fallback | false | `DAX_COLLAPSE({args})` | `COLLAPSE(1)` | `DAX_COLLAPSE(1)` |
| COLLAPSEALL | scalar | generic_fallback | false | `DAX_COLLAPSEALL({args})` | `COLLAPSEALL(1)` | `DAX_COLLAPSEALL(1)` |
| COLUMNSTATISTICS | scalar | generic_fallback | false | `DAX_COLUMNSTATISTICS({args})` | `COLUMNSTATISTICS(1)` | `DAX_COLUMNSTATISTICS(1)` |
| COMBIN | scalar | generic_fallback | false | `DAX_COMBIN({args})` | `COMBIN(1)` | `DAX_COMBIN(1)` |
| COMBINA | scalar | generic_fallback | false | `DAX_COMBINA({args})` | `COMBINA(1)` | `DAX_COMBINA(1)` |
| COMBINEVALUES | scalar | generic_fallback | false | `DAX_COMBINEVALUES({args})` | `COMBINEVALUES(1)` | `DAX_COMBINEVALUES(1)` |
| CONCAT | scalar | direct_sql_fn | true | `({{a}} \|\| {{b}})` | `CONCAT("a", "b")` | `('a' \|\| 'b')` |
| CONCATENATE | scalar | direct_sql_fn | true | `({{text1}} \|\| {{text2}})` | `CONCATENATE("a", "b")` | `('a' \|\| 'b')` |
| CONCATENATEX | iterator | subquery_rewrite | true | `(SELECT STRING_AGG({{expr}}, {{delim}} ORDER BY {{order_by}}) FROM {{table}})` | `CONCATENATEX(Sales, Sales[Category], ",", Sales[SortKey], ASC)` | `(SELECT STRING_AGG(v, ',' ORDER BY ord) FROM (SELECT 'b' AS v, 2 AS ord UNION ALL SELECT 'a' AS v, 1 AS ord) AS t)` |
| CONFIDENCE.NORM | scalar | generic_fallback | false | `DAX_CONFIDENCE_NORM({args})` | `CONFIDENCE.NORM(1)` | `DAX_CONFIDENCE_NORM(1)` |
| CONFIDENCE.T | scalar | generic_fallback | false | `DAX_CONFIDENCE_T({args})` | `CONFIDENCE.T(1)` | `DAX_CONFIDENCE_T(1)` |
| CONTAINS | scalar | generic_fallback | false | `DAX_CONTAINS({args})` | `CONTAINS(1)` | `DAX_CONTAINS(1)` |
| CONTAINSROW | scalar | generic_fallback | false | `DAX_CONTAINSROW({args})` | `CONTAINSROW(1)` | `DAX_CONTAINSROW(1)` |
| CONTAINSSTRING | scalar | generic_fallback | false | `DAX_CONTAINSSTRING({args})` | `CONTAINSSTRING(1)` | `DAX_CONTAINSSTRING(1)` |
| CONTAINSSTRINGEXACT | scalar | generic_fallback | false | `DAX_CONTAINSSTRINGEXACT({args})` | `CONTAINSSTRINGEXACT(1)` | `DAX_CONTAINSSTRINGEXACT(1)` |
| CONVERT | scalar | direct_sql_fn | true | `CAST({{expr}} AS {{type}})` | `CONVERT(1, STRING)` | `CAST(1 AS VARCHAR)` |
| COS | scalar | direct_sql_fn | true | `COS({args})` | `COS(1)` | `COS(1)` |
| COSH | scalar | direct_sql_fn | true | `COSH({args})` | `COSH(1)` | `COSH(1)` |
| COT | scalar | generic_fallback | false | `DAX_COT({args})` | `COT(1)` | `DAX_COT(1)` |
| COTH | scalar | generic_fallback | false | `DAX_COTH({args})` | `COTH(1)` | `DAX_COTH(1)` |
| COUNT | agg | direct_sql_fn | true | `COUNT({x})` | `COUNT(Sales[Amount])` | `COUNT(Sales.Amount)` |
| COUNTA | agg | generic_fallback | false | `DAX_COUNTA({args})` | `COUNTA(Sales[Amount])` | `DAX_COUNTA(Sales.Amount)` |
| COUNTAX | iterator | subquery_rewrite | true | `(SELECT COUNT({expr}) FROM {table})` | `COUNTAX(Sales, Sales[Amount])` | `(SELECT COUNT(Sales.Amount) FROM Sales)` |
| COUNTBLANK | agg | generic_fallback | false | `DAX_COUNTBLANK({args})` | `COUNTBLANK(Sales[Amount])` | `DAX_COUNTBLANK(Sales.Amount)` |
| COUNTROWS | agg | subquery_rewrite | true | `(SELECT COUNT(*) FROM {{table}})` | `COUNTROWS(Sales)` | `SELECT COUNT(*) FROM Sales` |
| COUNTX | iterator | subquery_rewrite | true | `(SELECT COUNT({expr}) FROM {table})` | `COUNTX(Sales, Sales[Amount])` | `(SELECT COUNT(Sales.Amount) FROM Sales)` |
| COUPDAYBS | scalar | generic_fallback | false | `DAX_COUPDAYBS({args})` | `COUPDAYBS(1)` | `DAX_COUPDAYBS(1)` |
| COUPDAYS | scalar | generic_fallback | false | `DAX_COUPDAYS({args})` | `COUPDAYS(1)` | `DAX_COUPDAYS(1)` |
| COUPDAYSNC | scalar | generic_fallback | false | `DAX_COUPDAYSNC({args})` | `COUPDAYSNC(1)` | `DAX_COUPDAYSNC(1)` |
| COUPNCD | scalar | generic_fallback | false | `DAX_COUPNCD({args})` | `COUPNCD(1)` | `DAX_COUPNCD(1)` |
| COUPNUM | scalar | generic_fallback | false | `DAX_COUPNUM({args})` | `COUPNUM(1)` | `DAX_COUPNUM(1)` |
| COUPPCD | scalar | generic_fallback | false | `DAX_COUPPCD({args})` | `COUPPCD(1)` | `DAX_COUPPCD(1)` |
| CROSSFILTER | context | context_rewrite | false | `<context_rewrite>` | `CROSSFILTER(SUM(Sales[Amount]))` | `SELECT 1` |
| CROSSJOIN | table | subquery_rewrite | true | `(SELECT * FROM ({{t1}}) AS t1 CROSS JOIN ({{t2}}) AS t2)` | `CROSSJOIN(VALUES(Sales[CustomerKey]), VALUES(Returns[CustomerKey]))` | `SELECT * FROM (SELECT DISTINCT Sales.CustomerKey FROM Sales) AS t1 CROSS JOIN (SELECT DISTINCT Returns.CustomerKey FROM Returns) AS t2` |
| CUMIPMT | scalar | generic_fallback | false | `DAX_CUMIPMT({args})` | `CUMIPMT(1)` | `DAX_CUMIPMT(1)` |
| CUMPRINC | scalar | generic_fallback | false | `DAX_CUMPRINC({args})` | `CUMPRINC(1)` | `DAX_CUMPRINC(1)` |
| CURRENCY | scalar | generic_fallback | false | `DAX_CURRENCY({args})` | `CURRENCY(1)` | `DAX_CURRENCY(1)` |
| CURRENTGROUP | scalar | generic_fallback | false | `DAX_CURRENTGROUP({args})` | `CURRENTGROUP(1)` | `DAX_CURRENTGROUP(1)` |
| CUSTOMDATA | scalar | generic_fallback | false | `DAX_CUSTOMDATA({args})` | `CUSTOMDATA(1)` | `DAX_CUSTOMDATA(1)` |
| DATATABLE | table | subquery_rewrite | false | `(SELECT * FROM DAX_DATATABLE({args}) AS t)` | `DATATABLE(1)` | `(SELECT * FROM DAX_DATATABLE(1) AS t)` |
| DATE | scalar | direct_sql_fn | true | `MAKE_DATE({{year}}, {{month}}, {{day}})` | `DATE(2025, 1, 2)` | `MAKE_DATE(2025, 1, 2)` |
| DATEADD | scalar | generic_fallback | false | `DAX_DATEADD({args})` | `DATEADD(1)` | `DAX_DATEADD(1)` |
| DATEDIFF | scalar | direct_sql_fn | true | `DATE_DIFF({{unit}}, {{start_date}}, {{end_date}})` | `DATEDIFF(DATE(2025,1,1), DATE(2025,1,2), DAY)` | `DATE_DIFF('day', DATE '2025-01-01', DATE '2025-01-02')` |
| DATESBETWEEN | scalar | generic_fallback | false | `DAX_DATESBETWEEN({args})` | `DATESBETWEEN(1)` | `DAX_DATESBETWEEN(1)` |
| DATESINPERIOD | scalar | generic_fallback | false | `DAX_DATESINPERIOD({args})` | `DATESINPERIOD(1)` | `DAX_DATESINPERIOD(1)` |
| DATESMTD | scalar | generic_fallback | false | `DAX_DATESMTD({args})` | `DATESMTD(1)` | `DAX_DATESMTD(1)` |
| DATESQTD | scalar | generic_fallback | false | `DAX_DATESQTD({args})` | `DATESQTD(1)` | `DAX_DATESQTD(1)` |
| DATESWTD | scalar | generic_fallback | false | `DAX_DATESWTD({args})` | `DATESWTD(1)` | `DAX_DATESWTD(1)` |
| DATESYTD | scalar | generic_fallback | false | `DAX_DATESYTD({args})` | `DATESYTD(1)` | `DAX_DATESYTD(1)` |
| DATEVALUE | scalar | generic_fallback | false | `DAX_DATEVALUE({args})` | `DATEVALUE(1)` | `DAX_DATEVALUE(1)` |
| DAY | scalar | direct_sql_fn | true | `EXTRACT(DAY FROM {{date}})` | `DAY(DATE(2025, 1, 2))` | `EXTRACT(DAY FROM MAKE_DATE(2025, 1, 2))` |
| DB | scalar | generic_fallback | false | `DAX_DB({args})` | `DB(1)` | `DAX_DB(1)` |
| DDB | scalar | generic_fallback | false | `DAX_DDB({args})` | `DDB(1)` | `DAX_DDB(1)` |
| DEGREES | scalar | generic_fallback | false | `DAX_DEGREES({args})` | `DEGREES(1)` | `DAX_DEGREES(1)` |
| DETAILROWS | scalar | generic_fallback | false | `DAX_DETAILROWS({args})` | `DETAILROWS(1)` | `DAX_DETAILROWS(1)` |
| DISC | scalar | generic_fallback | false | `DAX_DISC({args})` | `DISC(1)` | `DAX_DISC(1)` |
| DISTINCT | table | subquery_rewrite | true | `(SELECT DISTINCT {{col}} FROM {{table}})` | `DISTINCT(Sales[CustomerKey])` | `SELECT DISTINCT Sales.CustomerKey FROM Sales` |
| DISTINCTCOUNT | agg | direct_sql_fn | true | `COUNT(DISTINCT {{x}})` | `DISTINCTCOUNT(Sales[CustomerKey])` | `COUNT(DISTINCT Sales.CustomerKey)` |
| DISTINCTCOUNTNOBLANK | scalar | generic_fallback | false | `DAX_DISTINCTCOUNTNOBLANK({args})` | `DISTINCTCOUNTNOBLANK(1)` | `DAX_DISTINCTCOUNTNOBLANK(1)` |
| DIVIDE | scalar | case_rewrite | true | `CASE WHEN {{denominator}} IS NULL OR {{denominator}} = 0 THEN {{alternate_result}} ELSE ({{numerator}} / {{denominator}}) END` | `DIVIDE(10, 2)` | `CASE WHEN 2 IS NULL OR 2 = 0 THEN NULL ELSE (10 / 2) END` |
| DOLLARDE | scalar | generic_fallback | false | `DAX_DOLLARDE({args})` | `DOLLARDE(1)` | `DAX_DOLLARDE(1)` |
| DOLLARFR | scalar | generic_fallback | false | `DAX_DOLLARFR({args})` | `DOLLARFR(1)` | `DAX_DOLLARFR(1)` |
| DT"..." | scalar | generic_fallback | false | `DAX_DT({args})` | `DT"..."(1)` | `DAX_DT(1)` |
| DURATION | scalar | generic_fallback | false | `DAX_DURATION({args})` | `DURATION(1)` | `DAX_DURATION(1)` |
| EARLIER | scalar | generic_fallback | false | `DAX_EARLIER({args})` | `EARLIER(1)` | `DAX_EARLIER(1)` |
| EARLIEST | scalar | generic_fallback | false | `DAX_EARLIEST({args})` | `EARLIEST(1)` | `DAX_EARLIEST(1)` |
| EDATE | scalar | generic_fallback | false | `DAX_EDATE({args})` | `EDATE(1)` | `DAX_EDATE(1)` |
| EFFECT | scalar | generic_fallback | false | `DAX_EFFECT({args})` | `EFFECT(1)` | `DAX_EFFECT(1)` |
| ENDOFMONTH | scalar | generic_fallback | false | `DAX_ENDOFMONTH({args})` | `ENDOFMONTH(1)` | `DAX_ENDOFMONTH(1)` |
| ENDOFQUARTER | scalar | generic_fallback | false | `DAX_ENDOFQUARTER({args})` | `ENDOFQUARTER(1)` | `DAX_ENDOFQUARTER(1)` |
| ENDOFWEEK | scalar | generic_fallback | false | `DAX_ENDOFWEEK({args})` | `ENDOFWEEK(1)` | `DAX_ENDOFWEEK(1)` |
| ENDOFYEAR | scalar | generic_fallback | false | `DAX_ENDOFYEAR({args})` | `ENDOFYEAR(1)` | `DAX_ENDOFYEAR(1)` |
| EOMONTH | scalar | direct_sql_fn | true | `LAST_DAY({{start_date}} + ({{months}} \|\| ' months')::INTERVAL)` | `EOMONTH(DATE(2025, 1, 15), 1)` | `LAST_DAY(MAKE_DATE(2025, 1, 15) + INTERVAL '1 month')` |
| ERROR | scalar | generic_fallback | false | `DAX_ERROR({args})` | `ERROR(1)` | `DAX_ERROR(1)` |
| EVALUATEANDLOG | scalar | generic_fallback | false | `DAX_EVALUATEANDLOG({args})` | `EVALUATEANDLOG(1)` | `DAX_EVALUATEANDLOG(1)` |
| EVEN | scalar | generic_fallback | false | `DAX_EVEN({args})` | `EVEN(1)` | `DAX_EVEN(1)` |
| EXACT | scalar | generic_fallback | false | `DAX_EXACT({args})` | `EXACT(1)` | `DAX_EXACT(1)` |
| EXCEPT | table | subquery_rewrite | true | `({{t1}}) EXCEPT ({{t2}})` | `EXCEPT(VALUES(Sales[CustomerKey]), VALUES(Returns[CustomerKey]))` | `(SELECT DISTINCT Sales.CustomerKey FROM Sales) EXCEPT (SELECT DISTINCT Returns.CustomerKey FROM Returns)` |
| EXP | scalar | direct_sql_fn | true | `EXP({args})` | `EXP(1)` | `EXP(1)` |
| EXPAND | scalar | generic_fallback | false | `DAX_EXPAND({args})` | `EXPAND(1)` | `DAX_EXPAND(1)` |
| EXPANDALL | scalar | generic_fallback | false | `DAX_EXPANDALL({args})` | `EXPANDALL(1)` | `DAX_EXPANDALL(1)` |
| EXPON.DIST | scalar | generic_fallback | false | `DAX_EXPON_DIST({args})` | `EXPON.DIST(1)` | `DAX_EXPON_DIST(1)` |
| EXTERNALMEASURE | scalar | generic_fallback | false | `DAX_EXTERNALMEASURE({args})` | `EXTERNALMEASURE(1)` | `DAX_EXTERNALMEASURE(1)` |
| FACT | scalar | generic_fallback | false | `DAX_FACT({args})` | `FACT(1)` | `DAX_FACT(1)` |
| FALSE | scalar | direct_sql_fn | true | `FALSE` | `FALSE()` | `FALSE` |
| FILTER | table | subquery_rewrite | true | `(SELECT * FROM {{table}} WHERE {{predicate}})` | `FILTER(Sales, Sales[Amount] > 0)` | `SELECT * FROM Sales WHERE Sales.Amount > 0` |
| FILTERCLUSTER | scalar | generic_fallback | false | `DAX_FILTERCLUSTER({args})` | `FILTERCLUSTER(1)` | `DAX_FILTERCLUSTER(1)` |
| FILTERS | scalar | generic_fallback | false | `DAX_FILTERS({args})` | `FILTERS(1)` | `DAX_FILTERS(1)` |
| FIND | scalar | direct_sql_fn | true | `STRPOS({{within_text}}, {{find_text}})` | `FIND("ell", "hello")` | `STRPOS('hello', 'ell')` |
| FIRST | scalar | generic_fallback | false | `DAX_FIRST({args})` | `FIRST(1)` | `DAX_FIRST(1)` |
| FIRSTDATE | scalar | generic_fallback | false | `DAX_FIRSTDATE({args})` | `FIRSTDATE(1)` | `DAX_FIRSTDATE(1)` |
| FIRSTNONBLANK | scalar | generic_fallback | false | `DAX_FIRSTNONBLANK({args})` | `FIRSTNONBLANK(1)` | `DAX_FIRSTNONBLANK(1)` |
| FIRSTNONBLANKVALUE | scalar | generic_fallback | false | `DAX_FIRSTNONBLANKVALUE({args})` | `FIRSTNONBLANKVALUE(1)` | `DAX_FIRSTNONBLANKVALUE(1)` |
| FIXED | scalar | generic_fallback | false | `DAX_FIXED({args})` | `FIXED(1)` | `DAX_FIXED(1)` |
| FLOOR | scalar | direct_sql_fn | true | `FLOOR({args})` | `FLOOR(1)` | `FLOOR(1)` |
| FORMAT | scalar | generic_fallback | false | `DAX_FORMAT({args})` | `FORMAT(1)` | `DAX_FORMAT(1)` |
| FV | scalar | generic_fallback | false | `DAX_FV({args})` | `FV(1)` | `DAX_FV(1)` |
| GCD | scalar | generic_fallback | false | `DAX_GCD({args})` | `GCD(1)` | `DAX_GCD(1)` |
| GENERATE | table | subquery_rewrite | false | `(SELECT * FROM DAX_GENERATE({args}) AS t)` | `GENERATE(1)` | `(SELECT * FROM DAX_GENERATE(1) AS t)` |
| GENERATEALL | table | subquery_rewrite | false | `(SELECT * FROM DAX_GENERATEALL({args}) AS t)` | `GENERATEALL(1)` | `(SELECT * FROM DAX_GENERATEALL(1) AS t)` |
| GENERATESERIES | scalar | generic_fallback | false | `DAX_GENERATESERIES({args})` | `GENERATESERIES(1)` | `DAX_GENERATESERIES(1)` |
| GEOMEAN | scalar | generic_fallback | false | `DAX_GEOMEAN({args})` | `GEOMEAN(1)` | `DAX_GEOMEAN(1)` |
| GEOMEANX | scalar | generic_fallback | false | `DAX_GEOMEANX({args})` | `GEOMEANX(1)` | `DAX_GEOMEANX(1)` |
| GROUPBY | table | subquery_rewrite | false | `(SELECT * FROM DAX_GROUPBY({args}) AS t)` | `GROUPBY(1)` | `(SELECT * FROM DAX_GROUPBY(1) AS t)` |
| GROUPCROSSAPPLY | scalar | generic_fallback | false | `DAX_GROUPCROSSAPPLY({args})` | `GROUPCROSSAPPLY(1)` | `DAX_GROUPCROSSAPPLY(1)` |
| GROUPCROSSAPPLYTABLE | scalar | generic_fallback | false | `DAX_GROUPCROSSAPPLYTABLE({args})` | `GROUPCROSSAPPLYTABLE(1)` | `DAX_GROUPCROSSAPPLYTABLE(1)` |
| HASH | scalar | generic_fallback | false | `DAX_HASH({args})` | `HASH(1)` | `DAX_HASH(1)` |
| HASONEFILTER | scalar | generic_fallback | false | `DAX_HASONEFILTER({args})` | `HASONEFILTER(1)` | `DAX_HASONEFILTER(1)` |
| HASONEVALUE | scalar | generic_fallback | false | `DAX_HASONEVALUE({args})` | `HASONEVALUE(1)` | `DAX_HASONEVALUE(1)` |
| HOUR | scalar | generic_fallback | false | `DAX_HOUR({args})` | `HOUR(1)` | `DAX_HOUR(1)` |
| IF | scalar | case_rewrite | true | `CASE WHEN {{condition}} THEN {{value_if_true}} ELSE {{value_if_false}} END` | `IF(1=1, 10, 20)` | `CASE WHEN 1 = 1 THEN 10 ELSE 20 END` |
| IF.EAGER | scalar | generic_fallback | false | `DAX_IF_EAGER({args})` | `IF.EAGER(1)` | `DAX_IF_EAGER(1)` |
| IFERROR | scalar | generic_fallback | false | `DAX_IFERROR({args})` | `IFERROR(1)` | `DAX_IFERROR(1)` |
| IGNORE | scalar | generic_fallback | false | `DAX_IGNORE({args})` | `IGNORE(1)` | `DAX_IGNORE(1)` |
| INDEX | window | window_rewrite | true | `ROW_NUMBER() OVER (PARTITION BY {{partition_by}} ORDER BY {{order_by}})` | `INDEX(Sales)` | `SELECT ROW_NUMBER() OVER (ORDER BY Amount) AS idx FROM Sales` |
| INFO.ALTERNATEOFDEFINITIONS | scalar | generic_fallback | false | `DAX_INFO_ALTERNATEOFDEFINITIONS({args})` | `INFO.ALTERNATEOFDEFINITIONS(1)` | `DAX_INFO_ALTERNATEOFDEFINITIONS(1)` |
| INFO.ANNOTATIONS | scalar | generic_fallback | false | `DAX_INFO_ANNOTATIONS({args})` | `INFO.ANNOTATIONS(1)` | `DAX_INFO_ANNOTATIONS(1)` |
| INFO.ATTRIBUTEHIERARCHIES | scalar | generic_fallback | false | `DAX_INFO_ATTRIBUTEHIERARCHIES({args})` | `INFO.ATTRIBUTEHIERARCHIES(1)` | `DAX_INFO_ATTRIBUTEHIERARCHIES(1)` |
| INFO.ATTRIBUTEHIERARCHYSTORAGES | scalar | generic_fallback | false | `DAX_INFO_ATTRIBUTEHIERARCHYSTORAGES({args})` | `INFO.ATTRIBUTEHIERARCHYSTORAGES(1)` | `DAX_INFO_ATTRIBUTEHIERARCHYSTORAGES(1)` |
| INFO.CALCDEPENDENCY | scalar | generic_fallback | false | `DAX_INFO_CALCDEPENDENCY({args})` | `INFO.CALCDEPENDENCY(1)` | `DAX_INFO_CALCDEPENDENCY(1)` |
| INFO.CALCULATIONGROUPS | scalar | generic_fallback | false | `DAX_INFO_CALCULATIONGROUPS({args})` | `INFO.CALCULATIONGROUPS(1)` | `DAX_INFO_CALCULATIONGROUPS(1)` |
| INFO.CALCULATIONITEMS | scalar | generic_fallback | false | `DAX_INFO_CALCULATIONITEMS({args})` | `INFO.CALCULATIONITEMS(1)` | `DAX_INFO_CALCULATIONITEMS(1)` |
| INFO.CATALOGS | scalar | generic_fallback | false | `DAX_INFO_CATALOGS({args})` | `INFO.CATALOGS(1)` | `DAX_INFO_CATALOGS(1)` |
| INFO.CHANGEDPROPERTIES | scalar | generic_fallback | false | `DAX_INFO_CHANGEDPROPERTIES({args})` | `INFO.CHANGEDPROPERTIES(1)` | `DAX_INFO_CHANGEDPROPERTIES(1)` |
| INFO.COLUMNPARTITIONSTORAGES | scalar | generic_fallback | false | `DAX_INFO_COLUMNPARTITIONSTORAGES({args})` | `INFO.COLUMNPARTITIONSTORAGES(1)` | `DAX_INFO_COLUMNPARTITIONSTORAGES(1)` |
| INFO.COLUMNPERMISSIONS | scalar | generic_fallback | false | `DAX_INFO_COLUMNPERMISSIONS({args})` | `INFO.COLUMNPERMISSIONS(1)` | `DAX_INFO_COLUMNPERMISSIONS(1)` |
| INFO.COLUMNS | scalar | generic_fallback | false | `DAX_INFO_COLUMNS({args})` | `INFO.COLUMNS(1)` | `DAX_INFO_COLUMNS(1)` |
| INFO.COLUMNSTORAGES | scalar | generic_fallback | false | `DAX_INFO_COLUMNSTORAGES({args})` | `INFO.COLUMNSTORAGES(1)` | `DAX_INFO_COLUMNSTORAGES(1)` |
| INFO.CSDLMETADATA | scalar | generic_fallback | false | `DAX_INFO_CSDLMETADATA({args})` | `INFO.CSDLMETADATA(1)` | `DAX_INFO_CSDLMETADATA(1)` |
| INFO.CULTURES | scalar | generic_fallback | false | `DAX_INFO_CULTURES({args})` | `INFO.CULTURES(1)` | `DAX_INFO_CULTURES(1)` |
| INFO.DATACOVERAGEDEFINITIONS | scalar | generic_fallback | false | `DAX_INFO_DATACOVERAGEDEFINITIONS({args})` | `INFO.DATACOVERAGEDEFINITIONS(1)` | `DAX_INFO_DATACOVERAGEDEFINITIONS(1)` |
| INFO.DATASOURCES | scalar | generic_fallback | false | `DAX_INFO_DATASOURCES({args})` | `INFO.DATASOURCES(1)` | `DAX_INFO_DATASOURCES(1)` |
| INFO.DELTATABLEMETADATASTORAGES | scalar | generic_fallback | false | `DAX_INFO_DELTATABLEMETADATASTORAGES({args})` | `INFO.DELTATABLEMETADATASTORAGES(1)` | `DAX_INFO_DELTATABLEMETADATASTORAGES(1)` |
| INFO.DEPENDENCIES | scalar | generic_fallback | false | `DAX_INFO_DEPENDENCIES({args})` | `INFO.DEPENDENCIES(1)` | `DAX_INFO_DEPENDENCIES(1)` |
| INFO.DETAILROWSDEFINITIONS | scalar | generic_fallback | false | `DAX_INFO_DETAILROWSDEFINITIONS({args})` | `INFO.DETAILROWSDEFINITIONS(1)` | `DAX_INFO_DETAILROWSDEFINITIONS(1)` |
| INFO.DICTIONARYSTORAGES | scalar | generic_fallback | false | `DAX_INFO_DICTIONARYSTORAGES({args})` | `INFO.DICTIONARYSTORAGES(1)` | `DAX_INFO_DICTIONARYSTORAGES(1)` |
| INFO.EXCLUDEDARTIFACTS | scalar | generic_fallback | false | `DAX_INFO_EXCLUDEDARTIFACTS({args})` | `INFO.EXCLUDEDARTIFACTS(1)` | `DAX_INFO_EXCLUDEDARTIFACTS(1)` |
| INFO.EXPRESSIONS | scalar | generic_fallback | false | `DAX_INFO_EXPRESSIONS({args})` | `INFO.EXPRESSIONS(1)` | `DAX_INFO_EXPRESSIONS(1)` |
| INFO.EXTENDEDPROPERTIES | scalar | generic_fallback | false | `DAX_INFO_EXTENDEDPROPERTIES({args})` | `INFO.EXTENDEDPROPERTIES(1)` | `DAX_INFO_EXTENDEDPROPERTIES(1)` |
| INFO.FORMATSTRINGDEFINITIONS | scalar | generic_fallback | false | `DAX_INFO_FORMATSTRINGDEFINITIONS({args})` | `INFO.FORMATSTRINGDEFINITIONS(1)` | `DAX_INFO_FORMATSTRINGDEFINITIONS(1)` |
| INFO.FUNCTIONS | scalar | generic_fallback | false | `DAX_INFO_FUNCTIONS({args})` | `INFO.FUNCTIONS(1)` | `DAX_INFO_FUNCTIONS(1)` |
| INFO.GENERALSEGMENTMAPSEGMENTMETADATASTORAGES | scalar | generic_fallback | false | `DAX_INFO_GENERALSEGMENTMAPSEGMENTMETADATASTORAGES({args})` | `INFO.GENERALSEGMENTMAPSEGMENTMETADATASTORAGES(1)` | `DAX_INFO_GENERALSEGMENTMAPSEGMENTMETADATASTORAGES(1)` |
| INFO.GROUPBYCOLUMNS | scalar | generic_fallback | false | `DAX_INFO_GROUPBYCOLUMNS({args})` | `INFO.GROUPBYCOLUMNS(1)` | `DAX_INFO_GROUPBYCOLUMNS(1)` |
| INFO.HIERARCHIES | scalar | generic_fallback | false | `DAX_INFO_HIERARCHIES({args})` | `INFO.HIERARCHIES(1)` | `DAX_INFO_HIERARCHIES(1)` |
| INFO.HIERARCHYSTORAGES | scalar | generic_fallback | false | `DAX_INFO_HIERARCHYSTORAGES({args})` | `INFO.HIERARCHYSTORAGES(1)` | `DAX_INFO_HIERARCHYSTORAGES(1)` |
| INFO.KPIS | scalar | generic_fallback | false | `DAX_INFO_KPIS({args})` | `INFO.KPIS(1)` | `DAX_INFO_KPIS(1)` |
| INFO.LEVELS | scalar | generic_fallback | false | `DAX_INFO_LEVELS({args})` | `INFO.LEVELS(1)` | `DAX_INFO_LEVELS(1)` |
| INFO.LINGUISTICMETADATA | scalar | generic_fallback | false | `DAX_INFO_LINGUISTICMETADATA({args})` | `INFO.LINGUISTICMETADATA(1)` | `DAX_INFO_LINGUISTICMETADATA(1)` |
| INFO.MEASURES | scalar | generic_fallback | false | `DAX_INFO_MEASURES({args})` | `INFO.MEASURES(1)` | `DAX_INFO_MEASURES(1)` |
| INFO.MODEL | scalar | generic_fallback | false | `DAX_INFO_MODEL({args})` | `INFO.MODEL(1)` | `DAX_INFO_MODEL(1)` |
| INFO.OBJECTTRANSLATIONS | scalar | generic_fallback | false | `DAX_INFO_OBJECTTRANSLATIONS({args})` | `INFO.OBJECTTRANSLATIONS(1)` | `DAX_INFO_OBJECTTRANSLATIONS(1)` |
| INFO.PARQUETFILESTORAGES | scalar | generic_fallback | false | `DAX_INFO_PARQUETFILESTORAGES({args})` | `INFO.PARQUETFILESTORAGES(1)` | `DAX_INFO_PARQUETFILESTORAGES(1)` |
| INFO.PARTITIONS | scalar | generic_fallback | false | `DAX_INFO_PARTITIONS({args})` | `INFO.PARTITIONS(1)` | `DAX_INFO_PARTITIONS(1)` |
| INFO.PARTITIONSTORAGES | scalar | generic_fallback | false | `DAX_INFO_PARTITIONSTORAGES({args})` | `INFO.PARTITIONSTORAGES(1)` | `DAX_INFO_PARTITIONSTORAGES(1)` |
| INFO.PERSPECTIVECOLUMNS | scalar | generic_fallback | false | `DAX_INFO_PERSPECTIVECOLUMNS({args})` | `INFO.PERSPECTIVECOLUMNS(1)` | `DAX_INFO_PERSPECTIVECOLUMNS(1)` |
| INFO.PERSPECTIVEHIERARCHIES | scalar | generic_fallback | false | `DAX_INFO_PERSPECTIVEHIERARCHIES({args})` | `INFO.PERSPECTIVEHIERARCHIES(1)` | `DAX_INFO_PERSPECTIVEHIERARCHIES(1)` |
| INFO.PERSPECTIVEMEASURES | scalar | generic_fallback | false | `DAX_INFO_PERSPECTIVEMEASURES({args})` | `INFO.PERSPECTIVEMEASURES(1)` | `DAX_INFO_PERSPECTIVEMEASURES(1)` |
| INFO.PERSPECTIVES | scalar | generic_fallback | false | `DAX_INFO_PERSPECTIVES({args})` | `INFO.PERSPECTIVES(1)` | `DAX_INFO_PERSPECTIVES(1)` |
| INFO.PERSPECTIVETABLES | scalar | generic_fallback | false | `DAX_INFO_PERSPECTIVETABLES({args})` | `INFO.PERSPECTIVETABLES(1)` | `DAX_INFO_PERSPECTIVETABLES(1)` |
| INFO.PROPERTIES | scalar | generic_fallback | false | `DAX_INFO_PROPERTIES({args})` | `INFO.PROPERTIES(1)` | `DAX_INFO_PROPERTIES(1)` |
| INFO.QUERYGROUPS | scalar | generic_fallback | false | `DAX_INFO_QUERYGROUPS({args})` | `INFO.QUERYGROUPS(1)` | `DAX_INFO_QUERYGROUPS(1)` |
| INFO.REFRESHPOLICIES | scalar | generic_fallback | false | `DAX_INFO_REFRESHPOLICIES({args})` | `INFO.REFRESHPOLICIES(1)` | `DAX_INFO_REFRESHPOLICIES(1)` |
| INFO.RELATEDCOLUMNDETAILS | scalar | generic_fallback | false | `DAX_INFO_RELATEDCOLUMNDETAILS({args})` | `INFO.RELATEDCOLUMNDETAILS(1)` | `DAX_INFO_RELATEDCOLUMNDETAILS(1)` |
| INFO.RELATIONSHIPINDEXSTORAGES | scalar | generic_fallback | false | `DAX_INFO_RELATIONSHIPINDEXSTORAGES({args})` | `INFO.RELATIONSHIPINDEXSTORAGES(1)` | `DAX_INFO_RELATIONSHIPINDEXSTORAGES(1)` |
| INFO.RELATIONSHIPS | scalar | generic_fallback | false | `DAX_INFO_RELATIONSHIPS({args})` | `INFO.RELATIONSHIPS(1)` | `DAX_INFO_RELATIONSHIPS(1)` |
| INFO.RELATIONSHIPSTORAGES | scalar | generic_fallback | false | `DAX_INFO_RELATIONSHIPSTORAGES({args})` | `INFO.RELATIONSHIPSTORAGES(1)` | `DAX_INFO_RELATIONSHIPSTORAGES(1)` |
| INFO.ROLEMEMBERSHIPS | scalar | generic_fallback | false | `DAX_INFO_ROLEMEMBERSHIPS({args})` | `INFO.ROLEMEMBERSHIPS(1)` | `DAX_INFO_ROLEMEMBERSHIPS(1)` |
| INFO.ROLES | scalar | generic_fallback | false | `DAX_INFO_ROLES({args})` | `INFO.ROLES(1)` | `DAX_INFO_ROLES(1)` |
| INFO.SEGMENTMAPSTORAGES | scalar | generic_fallback | false | `DAX_INFO_SEGMENTMAPSTORAGES({args})` | `INFO.SEGMENTMAPSTORAGES(1)` | `DAX_INFO_SEGMENTMAPSTORAGES(1)` |
| INFO.SEGMENTSTORAGES | scalar | generic_fallback | false | `DAX_INFO_SEGMENTSTORAGES({args})` | `INFO.SEGMENTSTORAGES(1)` | `DAX_INFO_SEGMENTSTORAGES(1)` |
| INFO.STORAGEFILES | scalar | generic_fallback | false | `DAX_INFO_STORAGEFILES({args})` | `INFO.STORAGEFILES(1)` | `DAX_INFO_STORAGEFILES(1)` |
| INFO.STORAGEFOLDERS | scalar | generic_fallback | false | `DAX_INFO_STORAGEFOLDERS({args})` | `INFO.STORAGEFOLDERS(1)` | `DAX_INFO_STORAGEFOLDERS(1)` |
| INFO.STORAGETABLECOLUMNS | scalar | generic_fallback | false | `DAX_INFO_STORAGETABLECOLUMNS({args})` | `INFO.STORAGETABLECOLUMNS(1)` | `DAX_INFO_STORAGETABLECOLUMNS(1)` |
| INFO.STORAGETABLECOLUMNSEGMENTS | scalar | generic_fallback | false | `DAX_INFO_STORAGETABLECOLUMNSEGMENTS({args})` | `INFO.STORAGETABLECOLUMNSEGMENTS(1)` | `DAX_INFO_STORAGETABLECOLUMNSEGMENTS(1)` |
| INFO.STORAGETABLES | scalar | generic_fallback | false | `DAX_INFO_STORAGETABLES({args})` | `INFO.STORAGETABLES(1)` | `DAX_INFO_STORAGETABLES(1)` |
| INFO.TABLEPERMISSIONS | scalar | generic_fallback | false | `DAX_INFO_TABLEPERMISSIONS({args})` | `INFO.TABLEPERMISSIONS(1)` | `DAX_INFO_TABLEPERMISSIONS(1)` |
| INFO.TABLES | scalar | generic_fallback | false | `DAX_INFO_TABLES({args})` | `INFO.TABLES(1)` | `DAX_INFO_TABLES(1)` |
| INFO.TABLESTORAGES | scalar | generic_fallback | false | `DAX_INFO_TABLESTORAGES({args})` | `INFO.TABLESTORAGES(1)` | `DAX_INFO_TABLESTORAGES(1)` |
| INFO.VARIATIONS | scalar | generic_fallback | false | `DAX_INFO_VARIATIONS({args})` | `INFO.VARIATIONS(1)` | `DAX_INFO_VARIATIONS(1)` |
| INFO.VIEW.COLUMNS | scalar | generic_fallback | false | `DAX_INFO_VIEW_COLUMNS({args})` | `INFO.VIEW.COLUMNS(1)` | `DAX_INFO_VIEW_COLUMNS(1)` |
| INFO.VIEW.MEASURES | scalar | generic_fallback | false | `DAX_INFO_VIEW_MEASURES({args})` | `INFO.VIEW.MEASURES(1)` | `DAX_INFO_VIEW_MEASURES(1)` |
| INFO.VIEW.RELATIONSHIPS | scalar | generic_fallback | false | `DAX_INFO_VIEW_RELATIONSHIPS({args})` | `INFO.VIEW.RELATIONSHIPS(1)` | `DAX_INFO_VIEW_RELATIONSHIPS(1)` |
| INFO.VIEW.TABLES | scalar | generic_fallback | false | `DAX_INFO_VIEW_TABLES({args})` | `INFO.VIEW.TABLES(1)` | `DAX_INFO_VIEW_TABLES(1)` |
| INT | scalar | generic_fallback | false | `DAX_INT({args})` | `INT(1)` | `DAX_INT(1)` |
| INTERSECT | table | subquery_rewrite | true | `({{t1}}) INTERSECT ({{t2}})` | `INTERSECT(VALUES(Sales[CustomerKey]), VALUES(Returns[CustomerKey]))` | `(SELECT DISTINCT Sales.CustomerKey FROM Sales) INTERSECT (SELECT DISTINCT Returns.CustomerKey FROM Returns)` |
| INTRATE | scalar | generic_fallback | false | `DAX_INTRATE({args})` | `INTRATE(1)` | `DAX_INTRATE(1)` |
| IPMT | scalar | generic_fallback | false | `DAX_IPMT({args})` | `IPMT(1)` | `DAX_IPMT(1)` |
| ISAFTER | scalar | generic_fallback | false | `DAX_ISAFTER({args})` | `ISAFTER(1)` | `DAX_ISAFTER(1)` |
| ISATLEVEL | scalar | generic_fallback | false | `DAX_ISATLEVEL({args})` | `ISATLEVEL(1)` | `DAX_ISATLEVEL(1)` |
| ISBLANK | scalar | generic_fallback | false | `DAX_ISBLANK({args})` | `ISBLANK(1)` | `DAX_ISBLANK(1)` |
| ISBOOLEAN | scalar | generic_fallback | false | `DAX_ISBOOLEAN({args})` | `ISBOOLEAN(1)` | `DAX_ISBOOLEAN(1)` |
| ISCROSSFILTERED | scalar | generic_fallback | false | `DAX_ISCROSSFILTERED({args})` | `ISCROSSFILTERED(1)` | `DAX_ISCROSSFILTERED(1)` |
| ISCURRENCY | scalar | generic_fallback | false | `DAX_ISCURRENCY({args})` | `ISCURRENCY(1)` | `DAX_ISCURRENCY(1)` |
| ISDATETIME | scalar | generic_fallback | false | `DAX_ISDATETIME({args})` | `ISDATETIME(1)` | `DAX_ISDATETIME(1)` |
| ISDECIMAL | scalar | generic_fallback | false | `DAX_ISDECIMAL({args})` | `ISDECIMAL(1)` | `DAX_ISDECIMAL(1)` |
| ISDOUBLE | scalar | generic_fallback | false | `DAX_ISDOUBLE({args})` | `ISDOUBLE(1)` | `DAX_ISDOUBLE(1)` |
| ISEMPTY | scalar | generic_fallback | false | `DAX_ISEMPTY({args})` | `ISEMPTY(1)` | `DAX_ISEMPTY(1)` |
| ISERROR | scalar | generic_fallback | false | `DAX_ISERROR({args})` | `ISERROR(1)` | `DAX_ISERROR(1)` |
| ISEVEN | scalar | generic_fallback | false | `DAX_ISEVEN({args})` | `ISEVEN(1)` | `DAX_ISEVEN(1)` |
| ISFILTERED | scalar | generic_fallback | false | `DAX_ISFILTERED({args})` | `ISFILTERED(1)` | `DAX_ISFILTERED(1)` |
| ISINSCOPE | scalar | generic_fallback | false | `DAX_ISINSCOPE({args})` | `ISINSCOPE(1)` | `DAX_ISINSCOPE(1)` |
| ISINT64 | scalar | generic_fallback | false | `DAX_ISINT64({args})` | `ISINT64(1)` | `DAX_ISINT64(1)` |
| ISINTEGER | scalar | generic_fallback | false | `DAX_ISINTEGER({args})` | `ISINTEGER(1)` | `DAX_ISINTEGER(1)` |
| ISLOGICAL | scalar | generic_fallback | false | `DAX_ISLOGICAL({args})` | `ISLOGICAL(1)` | `DAX_ISLOGICAL(1)` |
| ISNONTEXT | scalar | generic_fallback | false | `DAX_ISNONTEXT({args})` | `ISNONTEXT(1)` | `DAX_ISNONTEXT(1)` |
| ISNUMBER | scalar | generic_fallback | false | `DAX_ISNUMBER({args})` | `ISNUMBER(1)` | `DAX_ISNUMBER(1)` |
| ISNUMERIC | scalar | generic_fallback | false | `DAX_ISNUMERIC({args})` | `ISNUMERIC(1)` | `DAX_ISNUMERIC(1)` |
| ISO.CEILING | scalar | generic_fallback | false | `DAX_ISO_CEILING({args})` | `ISO.CEILING(1)` | `DAX_ISO_CEILING(1)` |
| ISODD | scalar | generic_fallback | false | `DAX_ISODD({args})` | `ISODD(1)` | `DAX_ISODD(1)` |
| ISONORAFTER | scalar | generic_fallback | false | `DAX_ISONORAFTER({args})` | `ISONORAFTER(1)` | `DAX_ISONORAFTER(1)` |
| ISPMT | scalar | generic_fallback | false | `DAX_ISPMT({args})` | `ISPMT(1)` | `DAX_ISPMT(1)` |
| ISSELECTEDMEASURE | scalar | generic_fallback | false | `DAX_ISSELECTEDMEASURE({args})` | `ISSELECTEDMEASURE(1)` | `DAX_ISSELECTEDMEASURE(1)` |
| ISSTRING | scalar | generic_fallback | false | `DAX_ISSTRING({args})` | `ISSTRING(1)` | `DAX_ISSTRING(1)` |
| ISSUBTOTAL | scalar | generic_fallback | false | `DAX_ISSUBTOTAL({args})` | `ISSUBTOTAL(1)` | `DAX_ISSUBTOTAL(1)` |
| ISTEXT | scalar | generic_fallback | false | `DAX_ISTEXT({args})` | `ISTEXT(1)` | `DAX_ISTEXT(1)` |
| KEEPFILTERS | context | context_rewrite | false | `<context_rewrite>` | `KEEPFILTERS(SUM(Sales[Amount]))` | `SELECT 1` |
| KEYWORDMATCH | scalar | generic_fallback | false | `DAX_KEYWORDMATCH({args})` | `KEYWORDMATCH(1)` | `DAX_KEYWORDMATCH(1)` |
| LAST | scalar | generic_fallback | false | `DAX_LAST({args})` | `LAST(1)` | `DAX_LAST(1)` |
| LASTDATE | scalar | generic_fallback | false | `DAX_LASTDATE({args})` | `LASTDATE(1)` | `DAX_LASTDATE(1)` |
| LASTNONBLANK | scalar | generic_fallback | false | `DAX_LASTNONBLANK({args})` | `LASTNONBLANK(1)` | `DAX_LASTNONBLANK(1)` |
| LASTNONBLANKVALUE | scalar | generic_fallback | false | `DAX_LASTNONBLANKVALUE({args})` | `LASTNONBLANKVALUE(1)` | `DAX_LASTNONBLANKVALUE(1)` |
| LCM | scalar | generic_fallback | false | `DAX_LCM({args})` | `LCM(1)` | `DAX_LCM(1)` |
| LEFT | scalar | direct_sql_fn | true | `SUBSTR({{text}}, 1, {{num_chars}})` | `LEFT("abcdef", 2)` | `SUBSTR('abcdef', 1, 2)` |
| LEN | scalar | direct_sql_fn | true | `LENGTH({{text}})` | `LEN("abc")` | `LENGTH('abc')` |
| LINEST | scalar | generic_fallback | false | `DAX_LINEST({args})` | `LINEST(1)` | `DAX_LINEST(1)` |
| LINESTX | scalar | generic_fallback | false | `DAX_LINESTX({args})` | `LINESTX(1)` | `DAX_LINESTX(1)` |
| LN | scalar | direct_sql_fn | true | `LN({args})` | `LN(1)` | `LN(1)` |
| LOG | scalar | direct_sql_fn | true | `LOG({args})` | `LOG(1)` | `LOG(1)` |
| LOG10 | scalar | direct_sql_fn | true | `LOG10({args})` | `LOG10(1)` | `LOG10(1)` |
| LOOKUP | scalar | generic_fallback | false | `DAX_LOOKUP({args})` | `LOOKUP(1)` | `DAX_LOOKUP(1)` |
| LOOKUPVALUE | scalar | generic_fallback | false | `DAX_LOOKUPVALUE({args})` | `LOOKUPVALUE(1)` | `DAX_LOOKUPVALUE(1)` |
| LOOKUPWITHTOTALS | scalar | generic_fallback | false | `DAX_LOOKUPWITHTOTALS({args})` | `LOOKUPWITHTOTALS(1)` | `DAX_LOOKUPWITHTOTALS(1)` |
| LOWER | scalar | generic_fallback | false | `DAX_LOWER({args})` | `LOWER(1)` | `DAX_LOWER(1)` |
| LTRIM | scalar | direct_sql_fn | true | `LTRIM({{text}})` | `LTRIM("  abc")` | `LTRIM('  abc')` |
| MATCHBY | scalar | generic_fallback | false | `DAX_MATCHBY({args})` | `MATCHBY(1)` | `DAX_MATCHBY(1)` |
| MAX | agg | direct_sql_fn | true | `MAX({x})` | `MAX(Sales[Amount])` | `MAX(Sales.Amount)` |
| MAXA | scalar | generic_fallback | false | `DAX_MAXA({args})` | `MAXA(1)` | `DAX_MAXA(1)` |
| MAXX | iterator | subquery_rewrite | true | `(SELECT MAX({expr}) FROM {table})` | `MAXX(Sales, Sales[Amount])` | `(SELECT MAX(Sales.Amount) FROM Sales)` |
| MDURATION | scalar | generic_fallback | false | `DAX_MDURATION({args})` | `MDURATION(1)` | `DAX_MDURATION(1)` |
| MEDIAN | agg | generic_fallback | false | `DAX_MEDIAN({args})` | `MEDIAN(Sales[Amount])` | `DAX_MEDIAN(Sales.Amount)` |
| MEDIANX | agg | generic_fallback | false | `DAX_MEDIANX({args})` | `MEDIANX(Sales[Amount])` | `DAX_MEDIANX(Sales.Amount)` |
| MID | scalar | direct_sql_fn | true | `SUBSTR({{text}}, {{start_num}}, {{num_chars}})` | `MID("abcdef", 2, 3)` | `SUBSTR('abcdef', 2, 3)` |
| MIN | agg | direct_sql_fn | true | `MIN({x})` | `MIN(Sales[Amount])` | `MIN(Sales.Amount)` |
| MINA | scalar | generic_fallback | false | `DAX_MINA({args})` | `MINA(1)` | `DAX_MINA(1)` |
| MINUTE | scalar | generic_fallback | false | `DAX_MINUTE({args})` | `MINUTE(1)` | `DAX_MINUTE(1)` |
| MINX | iterator | subquery_rewrite | true | `(SELECT MIN({expr}) FROM {table})` | `MINX(Sales, Sales[Amount])` | `(SELECT MIN(Sales.Amount) FROM Sales)` |
| MOD | scalar | direct_sql_fn | true | `({{a}} % {{b}})` | `MOD(10, 3)` | `(10 % 3)` |
| MONTH | scalar | direct_sql_fn | true | `EXTRACT(MONTH FROM {{date}})` | `MONTH(DATE(2025, 1, 2))` | `EXTRACT(MONTH FROM MAKE_DATE(2025, 1, 2))` |
| MOVINGAVERAGE | scalar | generic_fallback | false | `DAX_MOVINGAVERAGE({args})` | `MOVINGAVERAGE(1)` | `DAX_MOVINGAVERAGE(1)` |
| MROUND | scalar | generic_fallback | false | `DAX_MROUND({args})` | `MROUND(1)` | `DAX_MROUND(1)` |
| NAMEOF | scalar | generic_fallback | false | `DAX_NAMEOF({args})` | `NAMEOF(1)` | `DAX_NAMEOF(1)` |
| NATURALINNERJOIN | table | subquery_rewrite | false | `(SELECT * FROM DAX_NATURALINNERJOIN({args}) AS t)` | `NATURALINNERJOIN(1)` | `(SELECT * FROM DAX_NATURALINNERJOIN(1) AS t)` |
| NATURALJOINUSAGE | scalar | generic_fallback | false | `DAX_NATURALJOINUSAGE({args})` | `NATURALJOINUSAGE(1)` | `DAX_NATURALJOINUSAGE(1)` |
| NATURALLEFTOUTERJOIN | table | subquery_rewrite | false | `(SELECT * FROM DAX_NATURALLEFTOUTERJOIN({args}) AS t)` | `NATURALLEFTOUTERJOIN(1)` | `(SELECT * FROM DAX_NATURALLEFTOUTERJOIN(1) AS t)` |
| NETWORKDAYS | scalar | generic_fallback | false | `DAX_NETWORKDAYS({args})` | `NETWORKDAYS(1)` | `DAX_NETWORKDAYS(1)` |
| NEXT | scalar | generic_fallback | false | `DAX_NEXT({args})` | `NEXT(1)` | `DAX_NEXT(1)` |
| NEXTDAY | scalar | generic_fallback | false | `DAX_NEXTDAY({args})` | `NEXTDAY(1)` | `DAX_NEXTDAY(1)` |
| NEXTMONTH | scalar | generic_fallback | false | `DAX_NEXTMONTH({args})` | `NEXTMONTH(1)` | `DAX_NEXTMONTH(1)` |
| NEXTQUARTER | scalar | generic_fallback | false | `DAX_NEXTQUARTER({args})` | `NEXTQUARTER(1)` | `DAX_NEXTQUARTER(1)` |
| NEXTWEEK | scalar | generic_fallback | false | `DAX_NEXTWEEK({args})` | `NEXTWEEK(1)` | `DAX_NEXTWEEK(1)` |
| NEXTYEAR | scalar | generic_fallback | false | `DAX_NEXTYEAR({args})` | `NEXTYEAR(1)` | `DAX_NEXTYEAR(1)` |
| NOMINAL | scalar | generic_fallback | false | `DAX_NOMINAL({args})` | `NOMINAL(1)` | `DAX_NOMINAL(1)` |
| NONFILTER | scalar | generic_fallback | false | `DAX_NONFILTER({args})` | `NONFILTER(1)` | `DAX_NONFILTER(1)` |
| NONVISUAL | scalar | generic_fallback | false | `DAX_NONVISUAL({args})` | `NONVISUAL(1)` | `DAX_NONVISUAL(1)` |
| NORM.DIST | scalar | generic_fallback | false | `DAX_NORM_DIST({args})` | `NORM.DIST(1)` | `DAX_NORM_DIST(1)` |
| NORM.INV | scalar | generic_fallback | false | `DAX_NORM_INV({args})` | `NORM.INV(1)` | `DAX_NORM_INV(1)` |
| NORM.S.DIST | scalar | generic_fallback | false | `DAX_NORM_S_DIST({args})` | `NORM.S.DIST(1)` | `DAX_NORM_S_DIST(1)` |
| NORM.S.INV | scalar | generic_fallback | false | `DAX_NORM_S_INV({args})` | `NORM.S.INV(1)` | `DAX_NORM_S_INV(1)` |
| NOT | scalar | direct_sql_fn | true | `(NOT {{x}})` | `NOT(TRUE())` | `(NOT TRUE)` |
| NOW | scalar | direct_sql_fn | true | `CURRENT_TIMESTAMP` | `NOW()` | `CURRENT_TIMESTAMP` |
| NPER | scalar | generic_fallback | false | `DAX_NPER({args})` | `NPER(1)` | `DAX_NPER(1)` |
| ODD | scalar | generic_fallback | false | `DAX_ODD({args})` | `ODD(1)` | `DAX_ODD(1)` |
| ODDFPRICE | scalar | generic_fallback | false | `DAX_ODDFPRICE({args})` | `ODDFPRICE(1)` | `DAX_ODDFPRICE(1)` |
| ODDFYIELD | scalar | generic_fallback | false | `DAX_ODDFYIELD({args})` | `ODDFYIELD(1)` | `DAX_ODDFYIELD(1)` |
| ODDLPRICE | scalar | generic_fallback | false | `DAX_ODDLPRICE({args})` | `ODDLPRICE(1)` | `DAX_ODDLPRICE(1)` |
| ODDLYIELD | scalar | generic_fallback | false | `DAX_ODDLYIELD({args})` | `ODDLYIELD(1)` | `DAX_ODDLYIELD(1)` |
| OFFSET | window | window_rewrite | true | `LAG({{expr}}, {{offset}}) OVER (PARTITION BY {{partition_by}} ORDER BY {{order_by}})` | `OFFSET(Sales[Amount], 1)` | `SELECT LAG(Amount, 1) OVER (ORDER BY Amount) AS prev FROM Sales` |
| OPENINGBALANCEMONTH | scalar | generic_fallback | false | `DAX_OPENINGBALANCEMONTH({args})` | `OPENINGBALANCEMONTH(1)` | `DAX_OPENINGBALANCEMONTH(1)` |
| OPENINGBALANCEQUARTER | scalar | generic_fallback | false | `DAX_OPENINGBALANCEQUARTER({args})` | `OPENINGBALANCEQUARTER(1)` | `DAX_OPENINGBALANCEQUARTER(1)` |
| OPENINGBALANCEWEEK | scalar | generic_fallback | false | `DAX_OPENINGBALANCEWEEK({args})` | `OPENINGBALANCEWEEK(1)` | `DAX_OPENINGBALANCEWEEK(1)` |
| OPENINGBALANCEYEAR | scalar | generic_fallback | false | `DAX_OPENINGBALANCEYEAR({args})` | `OPENINGBALANCEYEAR(1)` | `DAX_OPENINGBALANCEYEAR(1)` |
| OR | scalar | direct_sql_fn | true | `({{a}} OR {{b}})` | `OR(TRUE(), FALSE())` | `(TRUE OR FALSE)` |
| ORDERBY | scalar | generic_fallback | false | `DAX_ORDERBY({args})` | `ORDERBY(1)` | `DAX_ORDERBY(1)` |
| PARALLELPERIOD | scalar | generic_fallback | false | `DAX_PARALLELPERIOD({args})` | `PARALLELPERIOD(1)` | `DAX_PARALLELPERIOD(1)` |
| PARTITIONBY | scalar | generic_fallback | false | `DAX_PARTITIONBY({args})` | `PARTITIONBY(1)` | `DAX_PARTITIONBY(1)` |
| PATH | scalar | generic_fallback | false | `DAX_PATH({args})` | `PATH(1)` | `DAX_PATH(1)` |
| PATHCONTAINS | scalar | generic_fallback | false | `DAX_PATHCONTAINS({args})` | `PATHCONTAINS(1)` | `DAX_PATHCONTAINS(1)` |
| PATHITEM | scalar | generic_fallback | false | `DAX_PATHITEM({args})` | `PATHITEM(1)` | `DAX_PATHITEM(1)` |
| PATHITEMREVERSE | scalar | generic_fallback | false | `DAX_PATHITEMREVERSE({args})` | `PATHITEMREVERSE(1)` | `DAX_PATHITEMREVERSE(1)` |
| PATHLENGTH | scalar | generic_fallback | false | `DAX_PATHLENGTH({args})` | `PATHLENGTH(1)` | `DAX_PATHLENGTH(1)` |
| PDURATION | scalar | generic_fallback | false | `DAX_PDURATION({args})` | `PDURATION(1)` | `DAX_PDURATION(1)` |
| PERCENTILE.EXC | scalar | generic_fallback | false | `DAX_PERCENTILE_EXC({args})` | `PERCENTILE.EXC(1)` | `DAX_PERCENTILE_EXC(1)` |
| PERCENTILE.INC | scalar | generic_fallback | false | `DAX_PERCENTILE_INC({args})` | `PERCENTILE.INC(1)` | `DAX_PERCENTILE_INC(1)` |
| PERCENTILEX.EXC | scalar | generic_fallback | false | `DAX_PERCENTILEX_EXC({args})` | `PERCENTILEX.EXC(1)` | `DAX_PERCENTILEX_EXC(1)` |
| PERCENTILEX.INC | scalar | generic_fallback | false | `DAX_PERCENTILEX_INC({args})` | `PERCENTILEX.INC(1)` | `DAX_PERCENTILEX_INC(1)` |
| PERMUT | scalar | generic_fallback | false | `DAX_PERMUT({args})` | `PERMUT(1)` | `DAX_PERMUT(1)` |
| PI | scalar | direct_sql_fn | true | `PI()` | `PI()` | `PI()` |
| PMT | scalar | generic_fallback | false | `DAX_PMT({args})` | `PMT(1)` | `DAX_PMT(1)` |
| POISSON.DIST | scalar | generic_fallback | false | `DAX_POISSON_DIST({args})` | `POISSON.DIST(1)` | `DAX_POISSON_DIST(1)` |
| POWER | scalar | direct_sql_fn | true | `POW({{number}}, {{power}})` | `POWER(2, 3)` | `POW(2, 3)` |
| PPMT | scalar | generic_fallback | false | `DAX_PPMT({args})` | `PPMT(1)` | `DAX_PPMT(1)` |
| PREVIOUS | scalar | generic_fallback | false | `DAX_PREVIOUS({args})` | `PREVIOUS(1)` | `DAX_PREVIOUS(1)` |
| PREVIOUSDAY | scalar | generic_fallback | false | `DAX_PREVIOUSDAY({args})` | `PREVIOUSDAY(1)` | `DAX_PREVIOUSDAY(1)` |
| PREVIOUSMONTH | scalar | generic_fallback | false | `DAX_PREVIOUSMONTH({args})` | `PREVIOUSMONTH(1)` | `DAX_PREVIOUSMONTH(1)` |
| PREVIOUSQUARTER | scalar | generic_fallback | false | `DAX_PREVIOUSQUARTER({args})` | `PREVIOUSQUARTER(1)` | `DAX_PREVIOUSQUARTER(1)` |
| PREVIOUSWEEK | scalar | generic_fallback | false | `DAX_PREVIOUSWEEK({args})` | `PREVIOUSWEEK(1)` | `DAX_PREVIOUSWEEK(1)` |
| PREVIOUSYEAR | scalar | generic_fallback | false | `DAX_PREVIOUSYEAR({args})` | `PREVIOUSYEAR(1)` | `DAX_PREVIOUSYEAR(1)` |
| PRICE | scalar | generic_fallback | false | `DAX_PRICE({args})` | `PRICE(1)` | `DAX_PRICE(1)` |
| PRICEDISC | scalar | generic_fallback | false | `DAX_PRICEDISC({args})` | `PRICEDISC(1)` | `DAX_PRICEDISC(1)` |
| PRICEMAT | scalar | generic_fallback | false | `DAX_PRICEMAT({args})` | `PRICEMAT(1)` | `DAX_PRICEMAT(1)` |
| PRODUCT | scalar | generic_fallback | false | `DAX_PRODUCT({args})` | `PRODUCT(1)` | `DAX_PRODUCT(1)` |
| PRODUCTX | iterator | subquery_rewrite | false | `(SELECT DAX_PRODUCTX({expr}) FROM {table})` | `PRODUCTX(Sales, Sales[Amount])` | `(SELECT DAX_PRODUCTX(Sales.Amount) FROM Sales)` |
| PV | scalar | generic_fallback | false | `DAX_PV({args})` | `PV(1)` | `DAX_PV(1)` |
| QUARTER | scalar | generic_fallback | false | `DAX_QUARTER({args})` | `QUARTER(1)` | `DAX_QUARTER(1)` |
| QUOTIENT | scalar | generic_fallback | false | `DAX_QUOTIENT({args})` | `QUOTIENT(1)` | `DAX_QUOTIENT(1)` |
| RADIANS | scalar | generic_fallback | false | `DAX_RADIANS({args})` | `RADIANS(1)` | `DAX_RADIANS(1)` |
| RAND | scalar | generic_fallback | false | `DAX_RAND({args})` | `RAND(1)` | `DAX_RAND(1)` |
| RANDBETWEEN | scalar | generic_fallback | false | `DAX_RANDBETWEEN({args})` | `RANDBETWEEN(1)` | `DAX_RANDBETWEEN(1)` |
| RANGE | scalar | generic_fallback | false | `DAX_RANGE({args})` | `RANGE(1)` | `DAX_RANGE(1)` |
| RANK | scalar | generic_fallback | false | `DAX_RANK({args})` | `RANK(1)` | `DAX_RANK(1)` |
| RANK.EQ | scalar | generic_fallback | false | `DAX_RANK_EQ({args})` | `RANK.EQ(1)` | `DAX_RANK_EQ(1)` |
| RANKX | window | window_rewrite | true | `RANK() OVER (PARTITION BY {{partition_by}} ORDER BY {{order_by}})` | `RANKX(Sales, Sales[Amount])` | `SELECT RANK() OVER (ORDER BY Amount) AS r FROM Sales` |
| RATE | scalar | generic_fallback | false | `DAX_RATE({args})` | `RATE(1)` | `DAX_RATE(1)` |
| RECEIVED | scalar | generic_fallback | false | `DAX_RECEIVED({args})` | `RECEIVED(1)` | `DAX_RECEIVED(1)` |
| RELATED | scalar | generic_fallback | false | `DAX_RELATED({args})` | `RELATED(1)` | `DAX_RELATED(1)` |
| RELATEDTABLE | table | subquery_rewrite | false | `(SELECT * FROM DAX_RELATEDTABLE({args}) AS t)` | `RELATEDTABLE(1)` | `(SELECT * FROM DAX_RELATEDTABLE(1) AS t)` |
| REMOVEFILTERS | context | context_rewrite | false | `<context_rewrite>` | `REMOVEFILTERS(SUM(Sales[Amount]))` | `SELECT 1` |
| REPLACE | scalar | generic_fallback | false | `DAX_REPLACE({args})` | `REPLACE(1)` | `DAX_REPLACE(1)` |
| REPT | scalar | generic_fallback | false | `DAX_REPT({args})` | `REPT(1)` | `DAX_REPT(1)` |
| RIGHT | scalar | direct_sql_fn | true | `SUBSTR({{text}}, LENGTH({{text}}) - {{num_chars}} + 1, {{num_chars}})` | `RIGHT("abcdef", 2)` | `SUBSTR('abcdef', LENGTH('abcdef') - 2 + 1, 2)` |
| ROLLUP | scalar | generic_fallback | false | `DAX_ROLLUP({args})` | `ROLLUP(1)` | `DAX_ROLLUP(1)` |
| ROLLUPADDISSUBTOTAL | scalar | generic_fallback | false | `DAX_ROLLUPADDISSUBTOTAL({args})` | `ROLLUPADDISSUBTOTAL(1)` | `DAX_ROLLUPADDISSUBTOTAL(1)` |
| ROLLUPGROUP | scalar | generic_fallback | false | `DAX_ROLLUPGROUP({args})` | `ROLLUPGROUP(1)` | `DAX_ROLLUPGROUP(1)` |
| ROLLUPISSUBTOTAL | scalar | generic_fallback | false | `DAX_ROLLUPISSUBTOTAL({args})` | `ROLLUPISSUBTOTAL(1)` | `DAX_ROLLUPISSUBTOTAL(1)` |
| ROUND | scalar | direct_sql_fn | true | `ROUND({args})` | `ROUND(1)` | `ROUND(1)` |
| ROUNDDOWN | scalar | direct_sql_fn | true | `(CASE WHEN {{number}} >= 0 THEN FLOOR({{number}} * POW(10, {{num_digits}})) / POW(10, {{num_digits}}) ELSE CEIL({{number}} * POW(10, {{num_digits}})) / POW(10, {{num_digits}}) END)` | `ROUNDDOWN(12.34, 1)` | `(CASE WHEN 12.34 >= 0 THEN FLOOR(12.34 * POW(10, 1)) / POW(10, 1) ELSE CEIL(12.34 * POW(10, 1)) / POW(10, 1) END)` |
| ROUNDUP | scalar | direct_sql_fn | true | `(CASE WHEN {{number}} >= 0 THEN CEIL({{number}} * POW(10, {{num_digits}})) / POW(10, {{num_digits}}) ELSE FLOOR({{number}} * POW(10, {{num_digits}})) / POW(10, {{num_digits}}) END)` | `ROUNDUP(12.34, 1)` | `(CASE WHEN 12.34 >= 0 THEN CEIL(12.34 * POW(10, 1)) / POW(10, 1) ELSE FLOOR(12.34 * POW(10, 1)) / POW(10, 1) END)` |
| ROW | scalar | generic_fallback | false | `DAX_ROW({args})` | `ROW(1)` | `DAX_ROW(1)` |
| ROWNUMBER | scalar | generic_fallback | false | `DAX_ROWNUMBER({args})` | `ROWNUMBER(1)` | `DAX_ROWNUMBER(1)` |
| RRI | scalar | generic_fallback | false | `DAX_RRI({args})` | `RRI(1)` | `DAX_RRI(1)` |
| RTRIM | scalar | direct_sql_fn | true | `RTRIM({{text}})` | `RTRIM("abc  ")` | `RTRIM('abc  ')` |
| RUNNINGSUM | scalar | generic_fallback | false | `DAX_RUNNINGSUM({args})` | `RUNNINGSUM(1)` | `DAX_RUNNINGSUM(1)` |
| SAMEPERIODLASTYEAR | scalar | generic_fallback | false | `DAX_SAMEPERIODLASTYEAR({args})` | `SAMEPERIODLASTYEAR(1)` | `DAX_SAMEPERIODLASTYEAR(1)` |
| SAMPLE | scalar | generic_fallback | false | `DAX_SAMPLE({args})` | `SAMPLE(1)` | `DAX_SAMPLE(1)` |
| SAMPLEAXISWITHLOCALMINMAX | scalar | generic_fallback | false | `DAX_SAMPLEAXISWITHLOCALMINMAX({args})` | `SAMPLEAXISWITHLOCALMINMAX(1)` | `DAX_SAMPLEAXISWITHLOCALMINMAX(1)` |
| SAMPLECARTESIANPOINTSBYCOVER | scalar | generic_fallback | false | `DAX_SAMPLECARTESIANPOINTSBYCOVER({args})` | `SAMPLECARTESIANPOINTSBYCOVER(1)` | `DAX_SAMPLECARTESIANPOINTSBYCOVER(1)` |
| SEARCH | scalar | direct_sql_fn | true | `STRPOS(LOWER({{within_text}}), LOWER({{find_text}}))` | `SEARCH("ELL", "hello")` | `STRPOS(LOWER('hello'), LOWER('ELL'))` |
| SECOND | scalar | generic_fallback | false | `DAX_SECOND({args})` | `SECOND(1)` | `DAX_SECOND(1)` |
| SELECTCOLUMNS | table | subquery_rewrite | true | `(SELECT {{expr}} AS {{name}} FROM {{table}})` | `SELECTCOLUMNS(Sales, "Amount", Sales[Amount])` | `SELECT Sales.Amount AS Amount FROM Sales` |
| SELECTEDMEASURE | scalar | generic_fallback | false | `DAX_SELECTEDMEASURE({args})` | `SELECTEDMEASURE(1)` | `DAX_SELECTEDMEASURE(1)` |
| SELECTEDMEASUREFORMATSTRING | scalar | generic_fallback | false | `DAX_SELECTEDMEASUREFORMATSTRING({args})` | `SELECTEDMEASUREFORMATSTRING(1)` | `DAX_SELECTEDMEASUREFORMATSTRING(1)` |
| SELECTEDMEASURENAME | scalar | generic_fallback | false | `DAX_SELECTEDMEASURENAME({args})` | `SELECTEDMEASURENAME(1)` | `DAX_SELECTEDMEASURENAME(1)` |
| SELECTEDVALUE | scalar | generic_fallback | false | `DAX_SELECTEDVALUE({args})` | `SELECTEDVALUE(1)` | `DAX_SELECTEDVALUE(1)` |
| SHADOWCLUSTER | scalar | generic_fallback | false | `DAX_SHADOWCLUSTER({args})` | `SHADOWCLUSTER(1)` | `DAX_SHADOWCLUSTER(1)` |
| SIGN | scalar | direct_sql_fn | true | `SIGN({args})` | `SIGN(1)` | `SIGN(1)` |
| SIN | scalar | direct_sql_fn | true | `SIN({args})` | `SIN(1)` | `SIN(1)` |
| SINH | scalar | direct_sql_fn | true | `SINH({args})` | `SINH(1)` | `SINH(1)` |
| SLN | scalar | generic_fallback | false | `DAX_SLN({args})` | `SLN(1)` | `DAX_SLN(1)` |
| SQRT | scalar | direct_sql_fn | true | `SQRT({args})` | `SQRT(1)` | `SQRT(1)` |
| SQRTPI | scalar | generic_fallback | false | `DAX_SQRTPI({args})` | `SQRTPI(1)` | `DAX_SQRTPI(1)` |
| STARTOFMONTH | scalar | generic_fallback | false | `DAX_STARTOFMONTH({args})` | `STARTOFMONTH(1)` | `DAX_STARTOFMONTH(1)` |
| STARTOFQUARTER | scalar | generic_fallback | false | `DAX_STARTOFQUARTER({args})` | `STARTOFQUARTER(1)` | `DAX_STARTOFQUARTER(1)` |
| STARTOFWEEK | scalar | generic_fallback | false | `DAX_STARTOFWEEK({args})` | `STARTOFWEEK(1)` | `DAX_STARTOFWEEK(1)` |
| STARTOFYEAR | scalar | generic_fallback | false | `DAX_STARTOFYEAR({args})` | `STARTOFYEAR(1)` | `DAX_STARTOFYEAR(1)` |
| STDEV.P | scalar | generic_fallback | false | `DAX_STDEV_P({args})` | `STDEV.P(1)` | `DAX_STDEV_P(1)` |
| STDEV.S | scalar | generic_fallback | false | `DAX_STDEV_S({args})` | `STDEV.S(1)` | `DAX_STDEV_S(1)` |
| STDEVX.P | scalar | generic_fallback | false | `DAX_STDEVX_P({args})` | `STDEVX.P(1)` | `DAX_STDEVX_P(1)` |
| STDEVX.S | scalar | generic_fallback | false | `DAX_STDEVX_S({args})` | `STDEVX.S(1)` | `DAX_STDEVX_S(1)` |
| SUBSTITUTE | scalar | direct_sql_fn | true | `REPLACE({{text}}, {{old_text}}, {{new_text}})` | `SUBSTITUTE("a-b", "-", "_")` | `REPLACE('a-b', '-', '_')` |
| SUBSTITUTEWITHINDEX | scalar | generic_fallback | false | `DAX_SUBSTITUTEWITHINDEX({args})` | `SUBSTITUTEWITHINDEX(1)` | `DAX_SUBSTITUTEWITHINDEX(1)` |
| SUM | agg | direct_sql_fn | true | `SUM({x})` | `SUM(Sales[Amount])` | `SUM(Sales.Amount)` |
| SUMMARIZE | table | subquery_rewrite | false | `(SELECT * FROM DAX_SUMMARIZE({args}) AS t)` | `SUMMARIZE(1)` | `(SELECT * FROM DAX_SUMMARIZE(1) AS t)` |
| SUMMARIZECOLUMNS | table | subquery_rewrite | true | `(SELECT {{dim_cols}}, {{measure_expr}} AS {{measure_name}} FROM {{table}} GROUP BY {{dim_cols}})` | `SUMMARIZECOLUMNS(Sales[Category], "TotalAmount", SUM(Sales[Amount]))` | `SELECT Category, SUM(Amount) AS TotalAmount FROM Sales GROUP BY Category` |
| SUMX | iterator | subquery_rewrite | true | `(SELECT SUM({expr}) FROM {table})` | `SUMX(Sales, Sales[Amount])` | `(SELECT SUM(Sales.Amount) FROM Sales)` |
| SWITCH | scalar | generic_fallback | false | `DAX_SWITCH({args})` | `SWITCH(1)` | `DAX_SWITCH(1)` |
| SYD | scalar | generic_fallback | false | `DAX_SYD({args})` | `SYD(1)` | `DAX_SYD(1)` |
| T.DIST | scalar | generic_fallback | false | `DAX_T_DIST({args})` | `T.DIST(1)` | `DAX_T_DIST(1)` |
| T.DIST.2T | scalar | generic_fallback | false | `DAX_T_DIST_2T({args})` | `T.DIST.2T(1)` | `DAX_T_DIST_2T(1)` |
| T.DIST.RT | scalar | generic_fallback | false | `DAX_T_DIST_RT({args})` | `T.DIST.RT(1)` | `DAX_T_DIST_RT(1)` |
| T.INV | scalar | generic_fallback | false | `DAX_T_INV({args})` | `T.INV(1)` | `DAX_T_INV(1)` |
| T.INV.2T | scalar | generic_fallback | false | `DAX_T_INV_2T({args})` | `T.INV.2T(1)` | `DAX_T_INV_2T(1)` |
| TABLE CONSTRUCTOR | scalar | generic_fallback | false | `DAX_TABLE_CONSTRUCTOR({args})` | `TABLE CONSTRUCTOR(1)` | `DAX_TABLE_CONSTRUCTOR(1)` |
| TAN | scalar | direct_sql_fn | true | `TAN({args})` | `TAN(1)` | `TAN(1)` |
| TANH | scalar | direct_sql_fn | true | `TANH({args})` | `TANH(1)` | `TANH(1)` |
| TBILLEQ | scalar | generic_fallback | false | `DAX_TBILLEQ({args})` | `TBILLEQ(1)` | `DAX_TBILLEQ(1)` |
| TBILLPRICE | scalar | generic_fallback | false | `DAX_TBILLPRICE({args})` | `TBILLPRICE(1)` | `DAX_TBILLPRICE(1)` |
| TBILLYIELD | scalar | generic_fallback | false | `DAX_TBILLYIELD({args})` | `TBILLYIELD(1)` | `DAX_TBILLYIELD(1)` |
| TIME | scalar | generic_fallback | false | `DAX_TIME({args})` | `TIME(1)` | `DAX_TIME(1)` |
| TIMEVALUE | scalar | generic_fallback | false | `DAX_TIMEVALUE({args})` | `TIMEVALUE(1)` | `DAX_TIMEVALUE(1)` |
| TOCSV | scalar | generic_fallback | false | `DAX_TOCSV({args})` | `TOCSV(1)` | `DAX_TOCSV(1)` |
| TODAY | scalar | direct_sql_fn | true | `CURRENT_DATE` | `TODAY()` | `CURRENT_DATE` |
| TOJSON | scalar | generic_fallback | false | `DAX_TOJSON({args})` | `TOJSON(1)` | `DAX_TOJSON(1)` |
| TOPN | table | subquery_rewrite | true | `(SELECT * FROM {{table}} ORDER BY {{order_by}} {{order_dir}} LIMIT {{n}})` | `TOPN(5, Sales, Sales[Amount], DESC)` | `SELECT * FROM Sales ORDER BY Sales.Amount DESC LIMIT 5` |
| TOPNPERLEVEL | scalar | generic_fallback | false | `DAX_TOPNPERLEVEL({args})` | `TOPNPERLEVEL(1)` | `DAX_TOPNPERLEVEL(1)` |
| TOPNSKIP | scalar | generic_fallback | false | `DAX_TOPNSKIP({args})` | `TOPNSKIP(1)` | `DAX_TOPNSKIP(1)` |
| TOTALMTD | scalar | generic_fallback | false | `DAX_TOTALMTD({args})` | `TOTALMTD(1)` | `DAX_TOTALMTD(1)` |
| TOTALQTD | scalar | generic_fallback | false | `DAX_TOTALQTD({args})` | `TOTALQTD(1)` | `DAX_TOTALQTD(1)` |
| TOTALWTD | scalar | generic_fallback | false | `DAX_TOTALWTD({args})` | `TOTALWTD(1)` | `DAX_TOTALWTD(1)` |
| TOTALYTD | scalar | generic_fallback | false | `DAX_TOTALYTD({args})` | `TOTALYTD(1)` | `DAX_TOTALYTD(1)` |
| TREATAS | context | context_rewrite | false | `<context_rewrite>` | `TREATAS(SUM(Sales[Amount]))` | `SELECT 1` |
| TRIM | scalar | direct_sql_fn | true | `TRIM({{text}})` | `TRIM("  abc  ")` | `TRIM('  abc  ')` |
| TRUE | scalar | direct_sql_fn | true | `TRUE` | `TRUE()` | `TRUE` |
| TRUNC | scalar | generic_fallback | false | `DAX_TRUNC({args})` | `TRUNC(1)` | `DAX_TRUNC(1)` |
| UNICHAR | scalar | generic_fallback | false | `DAX_UNICHAR({args})` | `UNICHAR(1)` | `DAX_UNICHAR(1)` |
| UNICODE | scalar | generic_fallback | false | `DAX_UNICODE({args})` | `UNICODE(1)` | `DAX_UNICODE(1)` |
| UNION | table | subquery_rewrite | true | `({{t1}}) UNION ALL ({{t2}})` | `UNION(VALUES(Sales[CustomerKey]), VALUES(Returns[CustomerKey]))` | `(SELECT DISTINCT Sales.CustomerKey FROM Sales) UNION ALL (SELECT DISTINCT Returns.CustomerKey FROM Returns)` |
| UPPER | scalar | generic_fallback | false | `DAX_UPPER({args})` | `UPPER(1)` | `DAX_UPPER(1)` |
| USERCULTURE | scalar | generic_fallback | false | `DAX_USERCULTURE({args})` | `USERCULTURE(1)` | `DAX_USERCULTURE(1)` |
| USERELATIONSHIP | context | context_rewrite | false | `<context_rewrite>` | `USERELATIONSHIP(SUM(Sales[Amount]))` | `SELECT 1` |
| USERNAME | scalar | generic_fallback | false | `DAX_USERNAME({args})` | `USERNAME(1)` | `DAX_USERNAME(1)` |
| USEROBJECTID | scalar | generic_fallback | false | `DAX_USEROBJECTID({args})` | `USEROBJECTID(1)` | `DAX_USEROBJECTID(1)` |
| USERPRINCIPALNAME | scalar | generic_fallback | false | `DAX_USERPRINCIPALNAME({args})` | `USERPRINCIPALNAME(1)` | `DAX_USERPRINCIPALNAME(1)` |
| UTCNOW | scalar | generic_fallback | false | `DAX_UTCNOW({args})` | `UTCNOW(1)` | `DAX_UTCNOW(1)` |
| UTCTODAY | scalar | generic_fallback | false | `DAX_UTCTODAY({args})` | `UTCTODAY(1)` | `DAX_UTCTODAY(1)` |
| VALUE | scalar | generic_fallback | false | `DAX_VALUE({args})` | `VALUE(1)` | `DAX_VALUE(1)` |
| VALUES | table | subquery_rewrite | true | `(SELECT DISTINCT {{col}} FROM {{table}})` | `VALUES(Sales[CustomerKey])` | `SELECT DISTINCT Sales.CustomerKey FROM Sales` |
| VAR.P | scalar | generic_fallback | false | `DAX_VAR_P({args})` | `VAR.P(1)` | `DAX_VAR_P(1)` |
| VAR.S | scalar | generic_fallback | false | `DAX_VAR_S({args})` | `VAR.S(1)` | `DAX_VAR_S(1)` |
| VARX.P | scalar | generic_fallback | false | `DAX_VARX_P({args})` | `VARX.P(1)` | `DAX_VARX_P(1)` |
| VARX.S | scalar | generic_fallback | false | `DAX_VARX_S({args})` | `VARX.S(1)` | `DAX_VARX_S(1)` |
| VDB | scalar | generic_fallback | false | `DAX_VDB({args})` | `VDB(1)` | `DAX_VDB(1)` |
| WEEKDAY | scalar | generic_fallback | false | `DAX_WEEKDAY({args})` | `WEEKDAY(1)` | `DAX_WEEKDAY(1)` |
| WEEKNUM | scalar | generic_fallback | false | `DAX_WEEKNUM({args})` | `WEEKNUM(1)` | `DAX_WEEKNUM(1)` |
| WINDOW | window | window_rewrite | false | `<window_rewrite>` | `WINDOW(1)` | `SELECT DAX_WINDOW(1) OVER (PARTITION BY 1 ORDER BY 1)` |
| XIRR | scalar | generic_fallback | false | `DAX_XIRR({args})` | `XIRR(1)` | `DAX_XIRR(1)` |
| XNPV | scalar | generic_fallback | false | `DAX_XNPV({args})` | `XNPV(1)` | `DAX_XNPV(1)` |
| YEAR | scalar | direct_sql_fn | true | `EXTRACT(YEAR FROM {{date}})` | `YEAR(DATE(2025, 1, 2))` | `EXTRACT(YEAR FROM MAKE_DATE(2025, 1, 2))` |
| YEARFRAC | scalar | generic_fallback | false | `DAX_YEARFRAC({args})` | `YEARFRAC(1)` | `DAX_YEARFRAC(1)` |
| YIELD | scalar | generic_fallback | false | `DAX_YIELD({args})` | `YIELD(1)` | `DAX_YIELD(1)` |
| YIELDDISC | scalar | generic_fallback | false | `DAX_YIELDDISC({args})` | `YIELDDISC(1)` | `DAX_YIELDDISC(1)` |
| YIELDMAT | scalar | generic_fallback | false | `DAX_YIELDMAT({args})` | `YIELDMAT(1)` | `DAX_YIELDMAT(1)` |
