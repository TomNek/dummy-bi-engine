from pathlib import Path

import duckdb

import dax_compiler
from semantic_model_loader import load_semantic_model
from dax_parser.compile import compile_dax_expression_to_sql


def test_load_model_and_execute_measures_in_duckdb() -> None:
    # Load the semantic model (relationships + measures)
    root = Path(__file__).resolve().parents[1]
    model_path = root / "semantic_model.yaml"
    load_semantic_model(model_path)

    # Prepare DuckDB in-memory tables
    con = duckdb.connect(database=":memory:")
    con.execute(
        """
        CREATE TABLE Sales(
            ProductKey INTEGER,
            Amount DOUBLE,
            Region VARCHAR
        )
        """
    )
    con.execute(
        """
        INSERT INTO Sales VALUES
            (1, 10.0, 'EU'),
            (2, 20.0, 'US'),
            (1, 15.0, 'EU')
        """
    )

    # Compile measures to SQL and execute
    sql_total = compile_dax_expression_to_sql("[Total]")
    rows_total = con.execute(sql_total).fetchall()
    assert rows_total and isinstance(rows_total[0][0], (int, float))
    assert abs(rows_total[0][0] - 45.0) < 1e-9

    sql_eu_total = compile_dax_expression_to_sql("[EU Total]")
    rows_eu = con.execute(sql_eu_total).fetchall()
    assert rows_eu and isinstance(rows_eu[0][0], (int, float))
    assert abs(rows_eu[0][0] - 25.0) < 1e-9
