from __future__ import annotations

import contextlib
import functools
import http.server
import sqlite3
import threading
from pathlib import Path
from typing import Iterator

import duckdb
import pytest
from fastapi.testclient import TestClient

from dax_ui.server import create_app


EXPECTED_CONNECTOR_TYPES = {
    "csv",
    "parquet",
    "json",
    "excel",
    "text",
    "blob",
    "duckdb",
    "sqlite",
    "postgres",
    "mysql",
    "http",
    "s3",
    "azure_blob",
    "cloudflare_r2",
    "delta",
    "iceberg",
}


def _write_csv(path: Path) -> None:
    path.write_text("Name,Amount\nA,10\nB,20\n", encoding="utf-8")


def _write_parquet(path: Path) -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (Name VARCHAR, Amount INTEGER)")
    con.execute("INSERT INTO t VALUES ('A', 10), ('B', 20)")
    con.execute("COPY t TO ? (FORMAT 'parquet')", [str(path)])
    con.close()


def _write_json(path: Path) -> None:
    content = "\n".join([
        '{"Name": "A", "Amount": 10}',
        '{"Name": "B", "Amount": 20}',
    ])
    path.write_text(content + "\n", encoding="utf-8")


def _write_text(path: Path) -> None:
    path.write_text("Alpha\nBeta\n", encoding="utf-8")


def _write_blob(path: Path) -> None:
    path.write_bytes(b"blob-data")


def _write_excel(path: Path) -> bool:
    try:
        import openpyxl  # type: ignore
    except Exception:
        return False
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Name", "Amount"])
    ws.append(["A", 10])
    ws.append(["B", 20])
    wb.save(path)
    return True


def _write_duckdb(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE items (Name VARCHAR, Amount INTEGER)")
    con.execute("INSERT INTO items VALUES ('A', 10), ('B', 20)")
    con.close()


def _write_sqlite(path: Path) -> None:
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    cur.execute("CREATE TABLE items (Name TEXT, Amount INTEGER)")
    cur.execute("INSERT INTO items VALUES ('A', 10)")
    cur.execute("INSERT INTO items VALUES ('B', 20)")
    con.commit()
    con.close()


def _extension_available(name: str) -> bool:
    con = duckdb.connect()
    try:
        con.execute(f"INSTALL {name}")
    except Exception:
        pass
    try:
        con.execute(f"LOAD {name}")
        return True
    except Exception:
        return False
    finally:
        con.close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@contextlib.contextmanager
def _http_server(root: Path) -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def _preview(client: TestClient, project_path: Path, source: dict) -> tuple[int, dict]:
    response = client.post(
        f"/runtime/data_sources/preview?project={project_path}",
        json={"source": source, "limit": 5},
    )
    return response.status_code, response.json()


def test_import_connector_coverage(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    data_dir = project_path / "data"
    data_dir.mkdir(parents=True)

    csv_path = data_dir / "data.csv"
    parquet_path = data_dir / "data.parquet"
    json_path = data_dir / "data.json"
    text_path = data_dir / "data.txt"
    blob_path = data_dir / "data.bin"
    excel_path = data_dir / "data.xlsx"
    duckdb_path = data_dir / "data.duckdb"
    sqlite_path = data_dir / "data.sqlite"
    delta_path = data_dir / "delta"
    iceberg_path = data_dir / "iceberg"

    _write_csv(csv_path)
    _write_parquet(parquet_path)
    _write_json(json_path)
    _write_text(text_path)
    _write_blob(blob_path)
    excel_written = _write_excel(excel_path)
    _write_duckdb(duckdb_path)
    _write_sqlite(sqlite_path)
    delta_path.mkdir()
    iceberg_path.mkdir()

    client = TestClient(create_app())

    resp = client.get("/runtime/data_sources/connectors")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("ok") is True
    connectors = payload.get("connectors") or []
    connector_map = {str(c.get("type")): c for c in connectors if isinstance(c, dict)}

    for ctype in EXPECTED_CONNECTOR_TYPES:
        assert ctype in connector_map
        assert (connector_map[ctype].get("status") or "active") == "active"

    # Local file previews
    status, data = _preview(client, project_path, {"type": "csv", "path": "data/data.csv"})
    assert status == 200
    assert data.get("row_count") == 2

    status, data = _preview(client, project_path, {"type": "parquet", "path": "data/data.parquet"})
    assert status == 200
    assert data.get("row_count") == 2

    status, data = _preview(client, project_path, {"type": "json", "path": "data/data.json"})
    assert status == 200
    assert data.get("row_count") == 2

    status, data = _preview(client, project_path, {"type": "text", "path": "data/data.txt"})
    assert status == 200, data
    assert data.get("row_count") == 1

    status, data = _preview(client, project_path, {"type": "blob", "path": "data/data.bin"})
    if status == 200:
        assert data.get("row_count") == 1
        assert data.get("rows", [[None, None]])[0][1].get("kind") == "binary_ref"
    else:
        detail = str(data.get("detail") or data.get("error") or "").lower()
        if data.get("error_code") == "E_CONNECTOR_EXTENSION_UNAVAILABLE":
            assert status == 400
        elif "read_blob" in detail:
            assert status == 400
        elif "non-json" in detail and "bytes" in detail:
            assert status == 400
        else:
            assert status == 200, data

    if excel_written:
        status, data = _preview(client, project_path, {"type": "excel", "path": "data/data.xlsx"})
        if status == 200:
            assert (data.get("row_count") or 0) >= 2
        else:
            detail = str(data.get("detail") or data.get("error") or "").lower()
            if data.get("error_code") == "E_CONNECTOR_EXTENSION_UNAVAILABLE":
                assert status == 400
            elif "read_excel" in detail:
                assert status == 400
            else:
                assert status == 200

    # Database sources
    status, data = _preview(
        client,
        project_path,
        {"type": "duckdb", "path": "data/data.duckdb", "schema": "main", "table": "items"},
    )
    assert status == 200
    assert data.get("row_count") == 2

    if _extension_available("sqlite_scanner"):
        status, data = _preview(
            client,
            project_path,
            {"type": "sqlite", "path": "data/data.sqlite", "table": "items"},
        )
        assert status == 200
        assert data.get("row_count") == 2

    # Cloud/lakehouse connectors (normalization only via connectors list)
    assert "http" in connector_map
    assert "s3" in connector_map
    assert "azure_blob" in connector_map
    assert "cloudflare_r2" in connector_map
    assert "delta" in connector_map
    assert "iceberg" in connector_map

    # Optional HTTP preview if httpfs is available
    if _extension_available("httpfs"):
        with _http_server(data_dir) as base_url:
            status, data = _preview(
                client,
                project_path,
                {"type": "http", "path": f"{base_url}/data.csv", "format": "csv"},
            )
            assert status == 200
            assert data.get("row_count") == 2
