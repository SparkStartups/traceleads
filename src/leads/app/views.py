"""The app's pages, one function each, reading the published warehouse through ``data``."""

from datetime import date

import streamlit as st

from leads.app import data
from leads.config import MONTH_FORMAT


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


def month_choice() -> date:
    """Return the snapshot month picked in the sidebar; stop the page without a warehouse."""
    if not data.warehouse_exists():
        st.info("No published warehouse yet: build one with `make build` or `docker compose up`.")
        st.stop()
    months = data.query("SELECT snapshot_month FROM meta.pipeline_runs ORDER BY 1 DESC")
    return st.sidebar.selectbox(
        "Snapshot month", months["snapshot_month"], format_func=lambda m: f"{m:{MONTH_FORMAT}}"
    )
