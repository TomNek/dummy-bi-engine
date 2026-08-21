import dax_compiler


def test_load_default_mapping_is_explicit_and_registers_table_rewrites() -> None:
    # Default is explicit: calling it should not error.
    dax_compiler.load_default_mapping(
        prefer_verified_scalar=True,
        register_verified_table_rewrites=True,
        env_var=None,
    )

    # Verified table rewrites should be registered as table functions.
    for fn in [
        "FILTER",
        "VALUES",
        "DISTINCT",
        "TOPN",
        "CROSSJOIN",
        "SELECTCOLUMNS",
        "ADDCOLUMNS",
        "UNION",
        "INTERSECT",
        "EXCEPT",
    ]:
        spec = dax_compiler.registry.get(fn)
        assert spec is not None, f"Expected {fn} to be registered"
        assert spec.kind == "table", f"Expected {fn} to be kind=table"

    # Verified scalar templates should be registered as scalar functions.
    concat = dax_compiler.registry.get("CONCAT")
    assert concat is not None
    assert concat.kind == "scalar"
    assert callable(concat.sql_emit)
