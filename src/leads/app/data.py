"""Read-only queries against the published warehouse.

Each query opens its own connection and closes it, so a rebuild can replace the published file
while the app runs: Windows refuses to replace a file another process holds open. The console's
queries run in a child process, so neither a crash in DuckDB nor a query that never ends takes the
app down.
"""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import streamlit as st

from leads.app import sandbox
from leads.config import Settings

CONSOLE_SECONDS = 60


def warehouse_exists() -> bool:
    return Settings().warehouse_path.exists()


def query(sql: str, params: Sequence[object] = ()) -> pd.DataFrame:
    """Run ``sql`` and return at most ``ROW_LIMIT`` rows, cached until the warehouse changes."""
    path = Settings().warehouse_path
    return _cached_query(str(path), path.stat().st_mtime_ns, sql, tuple(params))


@st.cache_data(show_spinner=False, max_entries=256)
def _cached_query(path: str, version: int, sql: str, params: tuple[object, ...]) -> pd.DataFrame:
    # ``version`` is the file's modification time: a rebuild changes it and misses the cache.
    with sandbox.connect(path) as con:
        return con.sql(sql, params=params).limit(sandbox.ROW_LIMIT).df(date_as_object=True)


def console(sql: str) -> pd.DataFrame:
    """Run an analyst's ``sql`` in a child process and return at most ``ROW_LIMIT`` rows; raise
    ``duckdb.Error`` with its error, or when it crashes or runs past ``CONSOLE_SECONDS``."""
    command = [sys.executable, "-m", sandbox.__name__, str(Settings().warehouse_path)]
    try:
        child = subprocess.run(
            command, input=sql.encode(), capture_output=True, timeout=CONSOLE_SECONDS
        )
    except subprocess.TimeoutExpired:
        raise duckdb.Error(f"The query was stopped after {CONSOLE_SECONDS} seconds.") from None
    if child.returncode:
        raise duckdb.Error(
            child.stdout.decode() or f"DuckDB stopped (exit code {child.returncode})."
        )
    if not child.stdout:  # a statement without a result set
        return pd.DataFrame()
    rows = pa.ipc.open_stream(child.stdout).read_all()
    return duckdb.from_arrow(rows).df(date_as_object=True)  # typed as the pages' queries are


def saved_queries(directory: Path) -> dict[str, str]:
    """Return the queries saved in ``directory`` by title: each file's first line, a comment."""
    queries = {}
    for path in sorted(directory.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        queries[sql.partition("\n")[0].removeprefix("--").strip()] = sql
    return queries
