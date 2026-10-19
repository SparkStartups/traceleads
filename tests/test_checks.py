import json

import pytest

from leads.checks import Check, DataQualityError, Severity


def results(warehouse) -> list[tuple]:
    return warehouse.con.execute(
        "SELECT check_name, severity, failing_rows, sample FROM meta.dq_results ORDER BY check_name"
    ).fetchall()


@pytest.mark.parametrize(
    ("first_line", "expected"),
    [
        ("-- severity: warn", Severity.WARN),
        ("-- severity: warn  ", Severity.WARN),
        ("--severity:error", Severity.ERROR),
        ("-- rows with a negative amount", Severity.ERROR),
        ("SELECT 1", Severity.ERROR),
        ("SELECT 1 -- severity: warn", Severity.ERROR),
    ],
)
def test_severity_comes_from_first_line_and_defaults_to_error(tmp_path, first_line, expected):
    path = tmp_path / "stg_x.sql"
    path.write_text(f"{first_line}\nSELECT 1 WHERE false", encoding="utf-8")
    assert Check.from_file(path, "stg").severity is expected


def test_unknown_severity_is_rejected(tmp_path):
    path = tmp_path / "stg_x.sql"
    path.write_text("-- severity: info\nSELECT 1", encoding="utf-8")
    with pytest.raises(ValueError, match="info"):
        Check.from_file(path, "stg")


def test_checks_are_loaded_per_layer_in_name_order(warehouse, write_model):
    for name in ["dq/stg_b.sql", "dq/stg_a.sql", "dq/int_c.sql", "dq/stgx_d.sql"]:
        write_model(name, "SELECT 1 WHERE false")
    assert [check.name for check in warehouse.checks("stg")] == ["stg_a", "stg_b"]


def check_log(caplog) -> list[tuple[str, str]]:
    return [
        (record.levelname, record.getMessage())
        for record in caplog.records
        if record.name == "leads.checks"
    ]


def test_passing_and_warning_checks_are_recorded_without_stopping(
    warehouse, run, write_model, caplog
):
    write_model("dq/stg_clean.sql", "SELECT 1 AS x WHERE false;")
    write_model(
        "dq/stg_months.sql",
        "-- severity: warn\nSELECT getvariable('snapshot_month') AS month, 2 AS n -- one row\n",
    )

    warehouse.run_checks(run, "stg")

    clean, months = results(warehouse)
    assert clean == ("stg_clean", Severity.ERROR, 0, None)
    assert months[:3] == ("stg_months", Severity.WARN, 1)
    assert json.loads(months[3]) == [{"month": str(run.snapshot_month), "n": 2}]
    assert check_log(caplog) == [("WARNING", "check stg_months (warn): 1 failing rows")]


def test_error_check_fails_the_step_after_recording_every_check(
    warehouse, run, write_model, caplog
):
    write_model("dq/stg_a_broken.sql", "SELECT * FROM range(7)")
    write_model("dq/stg_b_clean.sql", "SELECT 1 WHERE false")

    with pytest.raises(DataQualityError, match="stg_a_broken"):
        warehouse.run_checks(run, "stg")

    broken, clean = results(warehouse)
    assert (broken[0], broken[2], len(json.loads(broken[3]))) == ("stg_a_broken", 7, 5)
    assert (clean[0], clean[2]) == ("stg_b_clean", 0)
    assert check_log(caplog) == [("ERROR", "check stg_a_broken (error): 7 failing rows")]
    assert "2026-10 dq/stg failed after" in caplog.text
