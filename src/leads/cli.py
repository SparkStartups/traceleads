"""Command-line interface."""

import logging
from datetime import date, datetime
from typing import Annotated

import duckdb
import typer

from leads.checks import DataQualityError
from leads.collect import collect_month
from leads.collect.fetch import FetchError
from leads.config import MONTH_FORMAT, Settings, current_month
from leads.tracking import Run
from leads.warehouse import PublishError, Warehouse, publish_on_success

log = logging.getLogger(__name__)

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_show_locals=False)


def parse_month(value: str) -> date:
    """Parse ``YYYY-MM`` into the first day of that month."""
    try:
        return datetime.strptime(value.strip(), MONTH_FORMAT).date()
    except ValueError as exc:
        raise typer.BadParameter(f"expected YYYY-MM, got {value!r}") from exc


Month = Annotated[
    date | None,
    typer.Option(
        "--month",
        "-m",
        parser=parse_month,
        metavar="YYYY-MM",
        help="Snapshot month. Defaults to the current month.",
    ),
]


@app.callback()
def main() -> None:
    """Vilnius businesses that look busy on Google Maps but declare little staff and tax."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


@app.command()
def collect(month: Month = None) -> None:
    """Download the sources for a month and write its snapshot to data/snapshots/."""
    try:
        collect_month(Settings(), month or current_month())
    except (FetchError, duckdb.Error) as exc:  # a source that cannot be read, or has changed
        log.error("%s", exc)
        raise typer.Exit(1) from exc


@app.command()
def build() -> None:
    """Rebuild every snapshot month into a new warehouse, published only if no error check fails."""
    settings = Settings()
    months = settings.snapshot_months()
    if not months:
        log.error("no snapshot in %s; run `leads collect` first", settings.snapshots_dir)
        raise typer.Exit(1)
    try:
        with publish_on_success(settings.warehouse_path) as working_copy:
            for month in months:
                with (
                    Warehouse.open(
                        working_copy,
                        settings.sql_dir,
                        settings.snapshot_dir(month),
                        settings.labels_dir,
                    ) as warehouse,
                    Run.start(warehouse.con, month) as run,
                ):
                    for layer in ("stg", "int", "mart"):
                        warehouse.run_layer(run, layer)
                        warehouse.run_checks(run, layer)
    except (duckdb.Error, DataQualityError, PublishError) as exc:
        log.error("%s; the published warehouse was not changed", exc)
        raise typer.Exit(1) from exc
