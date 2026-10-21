"""The sandboxed connection the app reads the warehouse through, and the console's child process.

``python -m leads.app.sandbox <warehouse>`` runs the SQL on stdin and writes its rows as an Arrow
stream to stdout, nothing for a statement without a result set, or its error and exit code 1. It
imports no Streamlit, so it starts quickly.
"""

import os
import sys

import duckdb
import pyarrow as pa

ROW_LIMIT = 10_000
# No files or extensions outside the warehouse, no temporary files when a query outgrows its
# memory, and limits a query cannot raise.
SANDBOX = {
    "enable_external_access": False,
    "threads": 2,
    "memory_limit": "1GB",
    "temp_directory": "",
    "lock_configuration": True,
}


def connect(path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=True, config=SANDBOX)


if __name__ == "__main__":
    with os.fdopen(os.dup(1), "wb") as out:
        os.dup2(2, 1)  # DuckDB can log to stdout itself: the answer goes to the copy alone
        with connect(sys.argv[1]) as con:
            try:
                relation = con.sql(sys.stdin.buffer.read().decode())
                table = None if relation is None else relation.limit(ROW_LIMIT).to_arrow_table()
            except duckdb.Error as exc:
                out.write(str(exc).encode())
                out.flush()  # before closing the connection, which can crash
                sys.exit(1)
        if table is not None:
            with pa.ipc.new_stream(out, table.schema) as stream:
                stream.write_table(table)
