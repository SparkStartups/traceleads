"""Read-only queries against the published warehouse.

Each query opens its own connection and closes it, so a rebuild can replace the published file
while the app runs: Windows refuses to replace a file another process holds open.
"""

from collections.abc import Sequence

import duckdb
import pandas as pd
import streamlit as st

from leads.config import Settings

ROW_LIMIT = 10_000
# No files or extensions outside the warehouse, and limits a query cannot raise.
SANDBOX = {
    "enable_external_access": False,
    "threads": 2,
    "memory_limit": "1GB",
    "lock_configuration": True,
}


def warehouse_exists() -> bool:
    return Settings().warehouse_path.exists()


def query(sql: str, params: Sequence[object] = ()) -> pd.DataFrame:
    """Run ``sql`` and return at most ``ROW_LIMIT`` rows, cached until the warehouse changes."""
    path = Settings().warehouse_path
    return _cached_query(str(path), path.stat().st_mtime_ns, sql, tuple(params))


@st.cache_data(show_spinner=False, max_entries=256)
def _cached_query(path: str, version: int, sql: str, params: tuple[object, ...]) -> pd.DataFrame:
    # ``version`` is the file's modification time: a rebuild changes it and misses the cache.
    with duckdb.connect(path, read_only=True, config=SANDBOX) as con:
        return con.sql(sql, params=params).limit(ROW_LIMIT).df(date_as_object=True)
