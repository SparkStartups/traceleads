"""Collection: download a month's sources into ``data/raw`` and write its snapshot."""

import logging
import shutil
from datetime import date
from pathlib import Path

import duckdb

from leads.collect.fetch import Fetcher
from leads.collect.jar import Jar
from leads.collect.sodra import Sodra
from leads.collect.source import Source
from leads.collect.vmi_taxes import VmiTaxes
from leads.config import MONTH_FORMAT, Settings, current_month

log = logging.getLogger(__name__)

SOURCES: tuple[Source, ...] = (Jar(), Sodra(), VmiTaxes())


def collect_month(settings: Settings, month: date) -> None:
    """Fetch every source for ``month`` and write ``data/snapshots/<month>/``.

    Files already in the month's raw folder are reused, so a rerun downloads only what is missing.
    Only the current month can be fetched; an earlier month is rebuilt from its saved raw files.
    The snapshot is written to ``<month>.building/`` and replaces the month's folder only when
    every source succeeded, so a failed source leaves the earlier snapshot, or none, in place.
    """
    out_dir = settings.snapshot_dir(month)
    working = out_dir.with_name(f"{out_dir.name}.building")
    working.mkdir(parents=True, exist_ok=True)  # a killed run leaves it; every file is rewritten
    try:
        with Fetcher(offline=month != current_month()) as fetcher, duckdb.connect() as con:
            for source in SOURCES:
                files = source.fetch(fetcher, settings.raw_dir(source.name, month), month)
                rows = source.snapshot(con, files, working)
                log.info(
                    "%s %s: %d rows from %d files",
                    source.name,
                    f"{month:{MONTH_FORMAT}}",
                    rows,
                    len(files),
                )
        _swap(working, out_dir)
    finally:
        shutil.rmtree(working, ignore_errors=True)


def _swap(new: Path, target: Path) -> None:
    """Put ``new`` in the place of ``target``; if that fails, ``target`` stays as it was.

    The old folder is moved aside first and deleted only once ``new`` is in place: Windows refuses
    to rename a folder while a file in it is open. A run killed between the two renames leaves only
    the aside copy, which this run puts back if its own rename fails.
    """
    replaced = target.with_name(f"{target.name}.replaced")
    if target.exists():
        shutil.rmtree(replaced, ignore_errors=True)  # left by a run killed after its swap
        target.rename(replaced)
    try:
        new.rename(target)
    except OSError:
        if replaced.exists():
            replaced.rename(target)
        raise
    shutil.rmtree(replaced, ignore_errors=True)
