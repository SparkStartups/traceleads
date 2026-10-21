"""The app's pages, one function each, reading the published warehouse through ``data``."""

import json
from datetime import date

import duckdb
import pandas as pd
import streamlit as st

from leads.app import data, sandbox
from leads.config import MONTH_FORMAT, Settings

OWN_QUERY = "(your own)"


def leads() -> None:
    st.title("Leads")
    month = month_choice()
    st.caption(
        "Companies whose places look busy on Google but which declare little staff or tax next "
        "to similar businesses: both gaps make a lead, one puts the company on watch. "
        "Leads for a closer look, not accusations: each comes with its numbers, its records and "
        "the innocent explanations to rule out first."
    )
    listed = data.query(
        "SELECT * EXCLUDE (snapshot_month) FROM mart.leads WHERE snapshot_month = ? ORDER BY rank",
        [month],
    )
    if listed.empty:
        st.info("No company is flagged this month.")
        return
    st.dataframe(listed, hide_index=True)

    companies = listed["company"].fillna(listed["ja_kodas"].astype(str))  # an IĮ may have no name
    names = dict(
        zip(listed["ja_kodas"], listed["rank"].astype(str) + ". " + companies, strict=True)
    )
    code = st.selectbox("Company", list(names), format_func=names.get)
    lead = listed.set_index("ja_kodas").loc[code]
    st.subheader(names[code])
    st.write(lead["reason"])
    if lead["explanations"]:
        st.warning(f"Innocent explanations to rule out first: {lead['explanations']}")
    params = [month, int(code)]  # a numpy integer does not bind as a parameter

    st.markdown("**Google places linked to it**")
    st.dataframe(
        data.query(
            "SELECT places.name, places.address, places.review_count AS reviews, places.closed, "
            "links.rule, found.queries AS found_by, mart.maps_url(places.cid) AS maps "
            "FROM int.links AS links "
            "JOIN int.places AS places USING (snapshot_month, cid) "
            "JOIN (SELECT snapshot_month, cid, string_agg(DISTINCT query, '; ' ORDER BY query) "
            "AS queries FROM stg.google_listings GROUP BY snapshot_month, cid) AS found "
            "USING (snapshot_month, cid) "
            "WHERE links.snapshot_month = $1 AND links.ja_kodas = $2 AND links.tier = 'automatic' "
            "ORDER BY places.review_count DESC, places.cid",
            params,
        ),
        hide_index=True,
        column_config={"maps": st.column_config.LinkColumn()},
    )
    st.markdown("**Register record**")
    record = data.query(
        "SELECT jar.legal_name, forms.abbreviation AS legal_form, jar.reg_date, jar.status "
        "FROM stg.jar_entities AS jar JOIN ref.legal_forms AS forms ON forms.code = jar.legal_form "
        "WHERE jar.snapshot_month = $1 AND jar.ja_kodas = $2",
        params,
    )
    st.dataframe(record.assign(address=lead["company_address"]), hide_index=True)
    st.markdown("**Insured people in the months scored** (a month without a row had nobody)")
    st.dataframe(
        data.query(
            "SELECT data_month, insured, evrk FROM stg.sodra_monthly CROSS JOIN ref.scoring "
            "WHERE snapshot_month = $1 AND ja_kodas = $2 AND mart.staff_month(data_month, ("
            "SELECT max(data_month) FROM stg.sodra_monthly WHERE snapshot_month = $1"
            "), staff_months) ORDER BY data_month",
            params,
        ),
        hide_index=True,
    )
    st.markdown("**Taxes paid** (the current year runs to date)")
    st.dataframe(
        data.query(
            "SELECT tax_year, months, amount FROM stg.vmi_taxes "
            "WHERE snapshot_month = $1 AND ja_kodas = $2 ORDER BY tax_year",
            params,
        ),
        hide_index=True,
    )
    st.markdown("**Raw files these records come from**")
    st.dataframe(
        data.query(
            "SELECT source, file, sha256, fetched_at, url FROM stg.source_files "
            "WHERE snapshot_month = $1 AND (source <> 'google_maps' OR file IN ("
            "SELECT listings.file FROM stg.google_listings AS listings "
            "JOIN int.links AS links USING (snapshot_month, cid) "
            "WHERE links.snapshot_month = $1 AND links.ja_kodas = $2 AND links.tier = 'automatic'"
            ")) ORDER BY source, file",
            params,
        ),
        hide_index=True,
    )


def overview() -> None:
    st.title("Overview")
    month = month_choice()
    st.subheader("Categories")
    st.caption(
        "From the places Google showed, through scope and links, to the companies judged. The "
        "flagged share is leads and watch among the judged companies."
    )
    st.dataframe(
        data.query(
            "SELECT * EXCLUDE (snapshot_month) FROM mart.category_summary "
            "WHERE snapshot_month = ? ORDER BY category",
            [month],
        ),
        hide_index=True,
        column_config={"flagged_share": st.column_config.NumberColumn(format="percent")},
    )
    st.subheader("Sensitivity")
    st.caption(
        "The judged companies tiered again under each gap ratio and minimum of reviews, and "
        "how many of the month's leads stay leads; `scoring` marks the limits the list uses."
    )
    st.dataframe(
        data.query(
            "SELECT round(grid.gap_ratio, 2) AS gap_ratio, grid.min_reviews, grid.leads, "
            "grid.watch, grid.leads_kept, grid.gap_ratio = scoring.gap_ratio "
            "AND grid.min_reviews = scoring.min_reviews AS scoring "
            "FROM mart.sensitivity AS grid CROSS JOIN ref.scoring "
            "WHERE grid.snapshot_month = ? ORDER BY grid.gap_ratio DESC, grid.min_reviews",
            [month],
        ),
        hide_index=True,
    )


def month_over_month() -> None:
    st.title("Month over month")
    month = month_choice()
    st.caption(
        "The month's scored companies against the month built before it, with what moved them. "
        "Every build scores all months with the same code, so a change comes from the data."
    )
    changes = data.query(
        "SELECT changes.change, changes.previous_tier, changes.tier, changes.ja_kodas, "
        "coalesce(now.name, before.name) AS company, changes.category, "
        "array_to_string(changes.causes, '; ') AS causes "
        "FROM mart.month_over_month AS changes "
        "LEFT JOIN int.companies AS now "
        "ON now.snapshot_month = changes.snapshot_month AND now.ja_kodas = changes.ja_kodas "
        "LEFT JOIN int.companies AS before "
        "ON before.snapshot_month = changes.previous_month AND before.ja_kodas = changes.ja_kodas "
        "WHERE changes.snapshot_month = ? "
        "ORDER BY changes.change, changes.category, changes.ja_kodas",
        [month],
    )
    if changes.empty:
        st.info("No month was built before this one.")
        return
    st.dataframe(changes.value_counts("change").rename("companies"))
    if not st.toggle("Unchanged companies too"):
        changes = changes[changes["change"] != "unchanged"]
    st.dataframe(changes, hide_index=True)


def matching() -> None:
    st.title("Matching")
    month = month_choice()
    st.subheader("Rules")
    st.caption(
        "Each rule that decided places, in the order the rules are tried: the places it decided, "
        "its links, and its precision on the links labelled at random in "
        "`data/labels/match_labels.csv`, with a 95% interval. Only automatic links are scored."
    )
    st.dataframe(
        data.query(
            "SELECT precision.rule, precision.tier, rules.meaning, precision.places, "
            "precision.linked, precision.labelled, precision.correct, precision.precision, "
            "precision.precision_low, precision.precision_high "
            "FROM mart.match_precision AS precision JOIN int.rules AS rules USING (rule) "
            "WHERE precision.snapshot_month = ? ORDER BY precision.rank",
            [month],
        ),
        hide_index=True,
    )
    st.subheader("Review queue")
    st.caption(
        "Places whose link needs a person: a review rule decided, or a rule found several "
        "companies. One row per candidate of the deciding rule, busiest places first, with the "
        "companies registered in the candidate's building."
    )
    queue = data.query(
        "SELECT * EXCLUDE (snapshot_month) FROM mart.review_queue WHERE snapshot_month = ? "
        "ORDER BY review_count DESC, cid, ja_kodas",
        [month],
    )
    if queue.empty:
        st.info("No place is waiting for a person.")
        return
    st.dataframe(queue, hide_index=True)
    places = dict(zip(queue["cid"], queue["place"], strict=True))  # a place repeats per candidate
    cid = st.selectbox("Place", list(places), format_func=places.get)
    st.markdown("**Its candidates** and the evidence each shares with it")
    every = st.toggle("Companies meeting no rule too")
    st.dataframe(
        data.query(
            "SELECT companies.name AS company, candidates.ja_kodas, companies.activity_code, "
            "candidates.rule, candidates.same_brand, candidates.same_core, "
            "candidates.same_building, candidates.same_street, candidates.shared_words, "
            "candidates.fitting_activity "
            "FROM int.candidates AS candidates JOIN int.companies AS companies "
            "USING (snapshot_month, ja_kodas) "
            "WHERE candidates.snapshot_month = $1 AND candidates.cid = $2 "
            "AND (candidates.rule IS NOT NULL OR $3) "
            "ORDER BY candidates.rule NULLS LAST, candidates.ja_kodas",
            [month, int(cid), every],
        ),
        hide_index=True,
    )


def runs() -> None:
    st.title("Runs and checks")
    month = month_choice()
    st.caption(
        "The published build's run of each snapshot month. Its data-quality checks follow: an "
        "error stops the build, a warning is only recorded, and a failing check keeps its first "
        "rows."
    )
    st.dataframe(
        data.query(
            "SELECT run_id, snapshot_month, git_sha, started_at, "
            "round(epoch(finished_at - started_at), 1) AS seconds "
            "FROM meta.pipeline_runs ORDER BY snapshot_month DESC"
        ),
        hide_index=True,
    )
    st.subheader("Checks")
    checks = data.query(
        "SELECT checks.layer, checks.check_name, checks.severity, checks.failing_rows, "
        "checks.sample FROM meta.dq_results AS checks JOIN meta.pipeline_runs AS runs "
        "USING (run_id) WHERE runs.snapshot_month = ? ORDER BY checks.layer, checks.check_name",
        [month],
    )
    st.dataframe(checks.drop(columns="sample"), hide_index=True)
    failing = checks[checks["failing_rows"] > 0].set_index("check_name")
    if not failing.empty:
        name = st.selectbox("Rows behind a failing check", failing.index)
        st.dataframe(pd.DataFrame(json.loads(failing.loc[name, "sample"])), hide_index=True)
    st.subheader("Snapshot")
    st.caption(
        "Each source of the month: the raw files it came from, the rows it gave the snapshot, "
        "its latest period and its download."
    )
    st.dataframe(
        data.query(
            "SELECT source, count(*) AS files, any_value(snapshot_rows) AS rows, "
            "any_value(period) AS period, max(fetched_at) AS fetched_at "
            "FROM stg.source_files WHERE snapshot_month = ? GROUP BY source ORDER BY source",
            [month],
        ),
        hide_index=True,
    )


def sql_console() -> None:
    st.title("SQL console")
    require_warehouse()
    st.caption(
        "DuckDB SQL over the published warehouse, read-only: no other file, database or setting "
        f"can be reached. Results show at most {sandbox.ROW_LIMIT:,} rows, and a query stops after "
        f"{data.CONSOLE_SECONDS} seconds. Tables read as built: an IĮ's registered address, "
        "which the lead list and the review queue withhold, shows here."
    )
    with st.expander("Tables and views"):
        st.dataframe(
            data.query(
                "SELECT table_schema, table_name, table_type FROM information_schema.tables "
                "ORDER BY table_schema, table_name"
            ),
            hide_index=True,
        )
    saved = data.saved_queries(Settings().sql_dir / "analyst")
    choice = st.selectbox("Saved query", [OWN_QUERY, *saved])
    sql = st.text_area("Query", value=saved.get(choice, ""), height=200, key=f"sql:{choice}")
    if not st.button("Run", type="primary") or not sql.strip():
        return
    try:
        result = data.console(sql)
    except duckdb.Error as exc:
        st.error(str(exc))
        return
    st.dataframe(result, hide_index=True)
    st.caption(f"{len(result):,} rows")


def require_warehouse() -> None:
    """Stop the page with a hint when no warehouse has been published yet."""
    if not data.warehouse_exists():
        st.info("No published warehouse yet: build one with `make build` or `docker compose up`.")
        st.stop()


def month_choice() -> date:
    """Return the snapshot month picked in the sidebar; stop the page without a warehouse."""
    require_warehouse()
    months = data.query("SELECT snapshot_month FROM meta.pipeline_runs ORDER BY 1 DESC")
    return st.sidebar.selectbox(
        "Snapshot month", months["snapshot_month"], format_func=lambda m: f"{m:{MONTH_FORMAT}}"
    )
