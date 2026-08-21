from __future__ import annotations

from pathlib import Path

import duckdb


def main() -> int:
    root = Path(__file__).resolve().parent
    db_path = root / "sample.duckdb"

    product_csv = root / "data" / "product.csv"
    sales_csv = root / "data" / "sales.csv"
    dim_date_csv = root / "data" / "dim_date.csv"

    if not product_csv.exists():
        raise FileNotFoundError(str(product_csv))
    if not sales_csv.exists():
        raise FileNotFoundError(str(sales_csv))
    if not dim_date_csv.exists():
        raise FileNotFoundError(str(dim_date_csv))

    con = duckdb.connect(str(db_path))
    con.execute("DROP TABLE IF EXISTS Product")
    con.execute("DROP TABLE IF EXISTS Sales")
    con.execute("DROP TABLE IF EXISTS DimDate")

    con.execute(
        "CREATE TABLE Product AS SELECT * FROM read_csv_auto(?, header=True)",
        [str(product_csv)],
    )
    con.execute(
        "CREATE TABLE Sales AS SELECT SaleId, ProductKey, Quantity, Amount, CAST(OrderDate AS DATE) AS OrderDate, Region, TRY_CAST(Discount AS DOUBLE) AS Discount FROM read_csv_auto(?, header=True)",
        [str(sales_csv)],
    )

    con.execute(
        "CREATE TABLE DimDate AS SELECT CAST(Date AS DATE) AS Date, Year, Month, MonthName, Quarter, DayOfWeek FROM read_csv_auto(?, header=True)",
        [str(dim_date_csv)],
    )

    con.close()
    print(f"Wrote DuckDB database: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
