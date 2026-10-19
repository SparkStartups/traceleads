"""Command-line interface."""

import logging

import typer

from leads.checks import DataQualityError
from leads.config import Settings
from leads.tracking import Run
from leads.warehouse import PublishError, Warehouse, publish_on_success

log = logging.getLogger(__name__)

app = typer.Typer(no_args_is_help=True, add_completion=False, pretty_exceptions_show_locals=False)


@app.callback()
def main() -> None:
    """Vilnius businesses that look busy on Google Maps but declare little staff and tax."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


@app.command()
def build() -> None:
    """Rebuild every snapshot month into a new warehouse, published only if no error check fails."""
    settings = Settings()
    months = settings.snapshot_months()
    if not months:
        log.error("no snapshot in %s", settings.snapshots_dir)
        raise typer.Exit(1)
    try:
        with publish_on_success(settings.warehouse_path) as working_copy:
            for month in months:
                with (
                    Warehouse.open(
                        working_copy, settings.sql_dir, settings.snapshot_dir(month)
                    ) as warehouse,
                    Run.start(warehouse.con, month) as run,
                ):
                    for layer in ("stg", "int", "mart"):
                        warehouse.run_layer(run, layer)
                        warehouse.run_checks(run, layer)
    except (DataQualityError, PublishError) as exc:
        log.error("%s; the published warehouse was not changed", exc)
        raise typer.Exit(1) from exc
