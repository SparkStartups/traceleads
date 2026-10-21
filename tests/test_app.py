from datetime import date
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from leads.app import data
from leads.cli import app as cli
from leads.config import Settings

OCTOBER = date(2026, 10, 1)
CODE = 304100001  # a company made to run the fixture place Cozy
MONTH = f"DATE '{OCTOBER}'"


@pytest.fixture
def built(project_root: Path, collected) -> Path:
    """Return the project root with the fixture month's warehouse published."""
    collected(OCTOBER)
    result = CliRunner().invoke(cli, ["build"])
    assert result.exit_code == 0, result.output
    return project_root


@pytest.fixture
def flagged(built: Path) -> Path:
    """Publish a lead: a company running Cozy and Užupio kavinė, with its register, Sodra and
    VMI rows, and a link to it labelled wrong."""
    with duckdb.connect(Settings(built).warehouse_path) as con:
        con.execute(
            f"INSERT INTO stg.jar_entities VALUES ({MONTH}, {CODE}, 'UAB \"Cozy\"', "
            f"'Vilnius, Dominikonų g. 10-3, LT-01120', DATE '2018-01-01', 310, 0);"
            f"INSERT INTO stg.sodra_monthly SELECT {MONTH}, {CODE}, month, 2, '561100' "
            "FROM range(DATE '2026-05-01', DATE '2026-09-01', INTERVAL 1 MONTH) AS t(month);"
            f"INSERT INTO stg.vmi_taxes VALUES ({MONTH}, {CODE}, NULL, 2025, 12, 5000), "
            f"({MONTH}, {CODE}, NULL, 2026, 9, 3000);"
            "INSERT INTO int.companies (snapshot_month, ja_kodas, name, address, legal_form, "
            f"reg_date) SELECT snapshot_month, ja_kodas, legal_name, address, legal_form, "
            f"reg_date FROM stg.jar_entities WHERE ja_kodas = {CODE};"
            f"UPDATE int.links SET ja_kodas = {CODE}, tier = 'automatic', "
            "rule = 'brand_and_building', candidates = 1 "
            "WHERE cid IN (SELECT cid FROM int.places WHERE name IN ('Cozy', 'Užupio kavinė'));"
            f"INSERT INTO int.links SELECT {MONTH}, cid, {CODE}, 'rejected', 'brand_and_building', "
            "1 FROM int.places WHERE name = 'Grey';"
            f"INSERT INTO mart.company_facts VALUES ({MONTH}, {CODE}, 'cafes_bakeries', 1, 1815, "
            "false, false, DATE '2018-01-01', 2.0, 2025, 5000);"
            f"INSERT INTO mart.scores BY NAME SELECT {MONTH} AS snapshot_month, "
            f"{CODE} AS ja_kodas, 'lead' AS tier, 1 AS rank, 'category' AS peer_group, 5 AS peers, "
            "172.0 AS category_median_reviews, true AS busy, 2.0 AS staff, "
            "6.0 AS peer_median_staff, 0.33 AS staff_ratio, true AS staff_gap, "
            "30000.0 AS peer_median_tax, 0.17 AS tax_ratio, true AS tax_gap, "
            "25000.0 AS tax_gap_eur, ['dentists often bill through their own companies'] "
            "AS explanations;"
        )
    return built


def run_page(name: str) -> AppTest:
    """Run one page function of ``leads.app.views`` on its own."""

    def page(name: str) -> None:
        from leads.app import views  # AppTest runs this function's source on its own

        getattr(views, name)()

    return AppTest.from_function(page, args=(name,), default_timeout=30).run()


def test_the_leads_page_lists_the_month_s_leads_and_shows_one_with_its_records(flagged):
    page = run_page("leads")
    listed, places, record, sodra, taxes, files = (frame.value for frame in page.dataframe)
    assert listed[["rank", "status", "ja_kodas", "company"]].values.tolist() == [
        [1, "lead", CODE, 'UAB "Cozy"']
    ]
    assert page.subheader[0].value == '1. UAB "Cozy"'
    assert "staff gap: 2.0 against the peers' 6.0" in page.markdown[0].value
    assert "dentists often bill" in page.warning[0].value
    assert places["name"].tolist() == ["Užupio kavinė", "Cozy"]  # busiest first
    assert places["maps"][0].startswith("https://www.google.com/maps?cid=")
    assert places["found_by"].tolist() == ["kavinė Antakalnis Vilnius"] * 2
    assert record[["legal_form", "address"]].values.tolist() == [
        ["UAB", "Vilnius, Dominikonų g. 10-3, LT-01120"]
    ]
    assert sodra["data_month"].tolist() == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]
    assert taxes["tax_year"].tolist() == [2025, 2026]
    google = files[files["source"] == "google_maps"]["file"].tolist()
    assert len(google) == 1  # the page that found its places, not the month's other 83
    assert set(files["source"]) == {"jar", "sodra", "vmi_taxes", "google_maps"}


def test_the_leads_page_lists_the_companies_in_rank_order(flagged):
    second = CODE + 1
    with duckdb.connect(Settings(flagged).warehouse_path) as con:
        con.execute(
            f"UPDATE mart.scores SET rank = 2, tier = 'watch' WHERE ja_kodas = {CODE};"
            f"INSERT INTO mart.scores SELECT * REPLACE ({second} AS ja_kodas, 1 AS rank, "
            f"'lead' AS tier) FROM mart.scores WHERE ja_kodas = {CODE};"
            f"INSERT INTO mart.company_facts SELECT * REPLACE ({second} AS ja_kodas) "
            f"FROM mart.company_facts WHERE ja_kodas = {CODE};"
            f"INSERT INTO int.companies SELECT * REPLACE ({second} AS ja_kodas, 'UAB \"Kavinė\"' "
            f"AS name) FROM int.companies WHERE ja_kodas = {CODE};"
            f"UPDATE int.links SET ja_kodas = {second} "
            "WHERE cid = (SELECT cid FROM int.places WHERE name = 'Užupio kavinė')"
        )
    page = run_page("leads")
    assert page.dataframe[0].value[["rank", "ja_kodas"]].values.tolist() == [
        [1, second],
        [2, CODE],
    ]


def test_a_nameless_ii_shows_by_its_code_without_its_registered_address(flagged):
    with duckdb.connect(Settings(flagged).warehouse_path) as con:
        con.execute(
            f"UPDATE int.companies SET legal_form = 810, name = NULL WHERE ja_kodas = {CODE};"
            "UPDATE mart.scores SET explanations = []"
        )
    page = run_page("leads")
    assert page.subheader[0].value == f"1. {CODE}"
    assert page.dataframe[2].value["address"].tolist() == [None]
    assert not page.warning  # no explanation to rule out


def test_the_leads_page_says_when_no_company_is_flagged(built):
    page = run_page("leads")
    assert page.info[0].value == "No company is flagged this month."


def test_a_page_says_how_to_build_a_missing_warehouse(project_root):
    page = run_page("leads")
    assert "No published warehouse yet" in page.info[0].value
    assert not page.exception


def test_queries_see_a_rebuild_at_the_same_path(built):
    sql = "SELECT run_id FROM meta.pipeline_runs"
    first = data.query(sql)["run_id"].tolist()
    assert CliRunner().invoke(cli, ["build"]).exit_code == 0
    assert data.query(sql)["run_id"].tolist() != first


def test_queries_return_at_most_row_limit_rows(built, monkeypatch):
    monkeypatch.setattr(data, "ROW_LIMIT", 1)
    assert len(data.query("SELECT * FROM range(2)")) == 1


def test_queries_run_on_two_threads_and_1_gb(built):
    limits = data.query(
        "SELECT current_setting('threads') AS threads, current_setting('memory_limit') AS memory"
    )
    assert limits.values.tolist() == [[2, "953.6 MiB"]]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE mart.mine AS SELECT 1",
        "SELECT * FROM read_csv('data/labels/match_labels.csv')",
        "SET threads = 8",
        "ATTACH 'other.duckdb'",
    ],
    ids=["write", "read-a-file", "raise-a-limit", "attach"],
)
def test_queries_cannot_write_read_files_or_change_settings(built, sql):
    with pytest.raises(duckdb.Error):
        data.query(sql)


@pytest.fixture
def two_months(flagged: Path) -> Path:
    """Score the lead a month earlier as watched and named otherwise, beside a company unchanged
    in both months and one scored in the earlier month only."""
    september = "DATE '2026-09-01'"
    with duckdb.connect(Settings(flagged).warehouse_path) as con:
        con.execute(
            "INSERT INTO mart.company_facts SELECT * REPLACE (304100002 AS ja_kodas) "
            "FROM mart.company_facts;"
            "INSERT INTO mart.scores SELECT * REPLACE (304100002 AS ja_kodas, "
            "'not_flagged' AS tier, NULL AS rank, 1.0 AS staff_ratio, false AS staff_gap, "
            "1.0 AS tax_ratio, false AS tax_gap) FROM mart.scores;"
            f"INSERT INTO int.companies SELECT * REPLACE ({september} AS snapshot_month, "
            f"CASE WHEN ja_kodas = {CODE} THEN 'UAB \"Cosy\"' ELSE name END AS name) "
            "FROM int.companies;"
            f"INSERT INTO mart.company_facts SELECT * REPLACE ({september} AS snapshot_month) "
            "FROM mart.company_facts;"
            f"INSERT INTO mart.scores SELECT * REPLACE ({september} AS snapshot_month, "
            f"CASE WHEN ja_kodas = {CODE} THEN 'watch' ELSE tier END AS tier) FROM mart.scores;"
            f"INSERT INTO int.companies (snapshot_month, ja_kodas, name, address, legal_form, "
            f"reg_date) VALUES ({september}, 304100003, 'UAB \"Gone\"', 'Vilnius', 310, "
            "DATE '2018-01-01');"
            "INSERT INTO mart.company_facts SELECT * REPLACE (304100003 AS ja_kodas) "
            f"FROM mart.company_facts WHERE snapshot_month = {september} AND ja_kodas = {CODE};"
            "INSERT INTO mart.scores SELECT * REPLACE (304100003 AS ja_kodas) "
            f"FROM mart.scores WHERE snapshot_month = {september} AND ja_kodas = 304100002;"
        )
    return flagged


def test_the_overview_shows_the_month_s_categories_and_sensitivity_grid(two_months):
    page = run_page("overview")
    categories, grid = (frame.value for frame in page.dataframe)
    shown = categories[["category", "places", "judged", "leads", "flagged_share"]]
    assert shown.values.tolist() == [["cafes_bakeries", 20, 2, 1, 0.5]]  # October's only
    assert '"format": "percent"' in page.dataframe[0].proto.columns
    assert len(grid) == 9
    scoring = grid[grid["scoring"]]
    assert scoring[["gap_ratio", "min_reviews", "leads"]].values.tolist() == [[0.33, 50, 1]]


def test_the_month_over_month_page_counts_the_changes_and_lists_them(two_months):
    page = run_page("month_over_month")
    counts, listed = (frame.value for frame in page.dataframe)
    assert counts["companies"].to_dict() == {"gone": 1, "tier changed": 1, "unchanged": 1}
    columns = ["change", "previous_tier", "tier", "ja_kodas", "company"]
    assert listed[columns].fillna("-").values.tolist() == [
        ["gone", "not_flagged", "-", 304100003, 'UAB "Gone"'],  # named as it was
        ["tier changed", "watch", "lead", CODE, 'UAB "Cozy"'],  # named as it is now
    ]
    page.toggle[0].set_value(True).run()
    assert page.dataframe[1].value["ja_kodas"].tolist() == [304100003, CODE, 304100002]


def test_the_month_over_month_page_says_when_no_month_came_before(flagged):
    page = run_page("month_over_month")
    assert page.info[0].value == "No month was built before this one."
