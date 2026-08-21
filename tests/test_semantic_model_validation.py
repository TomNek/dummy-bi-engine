import pytest

from semantic_model_loader import validate_semantic_model


def test_validation_requires_relationship_fields():
    model = {
        "relationships": [
            {"from": {"table": "", "column": "ProductKey"}, "to": {"table": "Product", "column": "ProductKey"}},
            {"from": {"table": "Sales", "column": ""}, "to": {"table": "Product", "column": "ProductKey"}},
            {"from": {"table": "Sales", "column": "ProductKey"}, "to": {"table": "", "column": "ProductKey"}},
            {"from": {"table": "Sales", "column": "ProductKey"}, "to": {"table": "Product", "column": ""}},
        ]
    }
    with pytest.raises(ValueError) as exc:
        validate_semantic_model(model)
    msg = str(exc.value)
    assert "from.table is required" in msg
    assert "from.column is required" in msg
    assert "to.table is required" in msg
    assert "to.column is required" in msg


def test_validation_duplicate_relationships_and_rel_id():
    model = {
        "relationships": [
            {
                "from": {"table": "Sales", "column": "ProductKey"},
                "to": {"table": "Product", "column": "ProductKey"},
                "rel_id": "r1",
            },
            {
                "from": {"table": "Sales", "column": "ProductKey"},
                "to": {"table": "Product", "column": "ProductKey"},
                "rel_id": "r1",
            },
        ]
    }
    with pytest.raises(ValueError) as exc:
        validate_semantic_model(model)
    msg = str(exc.value)
    assert "Duplicate relationship pair" in msg
    assert "Duplicate relationship rel_id" in msg


def test_validation_requires_measure_fields_and_uniqueness():
    model = {
        "measures": [
            {"name": "", "dax": "SUM(Sales[Amount])"},
            {"name": "Total", "dax": ""},
            {"name": "Total", "dax": "SUM(Sales[Amount])"},
            {"name": "total", "dax": "SUM(Sales[Amount])"},
        ]
    }
    with pytest.raises(ValueError) as exc:
        validate_semantic_model(model)
    msg = str(exc.value)
    assert "measures[0].name is required" in msg
    assert "measures[1].dax is required" in msg
    # duplicates are case-insensitive
    assert "Duplicate measure name: Total" in msg


def test_validation_metadata_types():
    model = {
        "measures": [
            {"name": "Total", "dax": "SUM(Sales[Amount])", "description": 123, "folder": [], "format": {}},
        ]
    }
    with pytest.raises(ValueError) as exc:
        validate_semantic_model(model)
    msg = str(exc.value)
    assert "measures[0].description must be a string" in msg
    assert "measures[0].folder must be a string" in msg
    assert "measures[0].format must be a string" in msg
