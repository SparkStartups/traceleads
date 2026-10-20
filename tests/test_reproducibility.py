import shutil
from pathlib import Path

from typer.testing import CliRunner

from leads.cli import app
from leads.config import Settings

REPOSITORY = Settings(Path(__file__).resolve().parents[1])


def test_the_committed_inputs_rebuild_the_committed_lead_lists(project_root):
    """A clean clone builds, offline, exactly the lead lists that are committed."""
    project = Settings(project_root)
    months = REPOSITORY.snapshot_months()
    assert months
    shutil.copytree(REPOSITORY.snapshots_dir, project.snapshots_dir)
    shutil.copytree(REPOSITORY.labels_dir, project.labels_dir, dirs_exist_ok=True)

    result = CliRunner().invoke(app, ["build"])

    assert result.exit_code == 0, result.output
    for month in months:
        assert project.leads_csv(month).read_bytes() == REPOSITORY.leads_csv(month).read_bytes()
