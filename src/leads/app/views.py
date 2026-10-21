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


def month_choice() -> date:
    """Return the snapshot month picked in the sidebar; stop the page without a warehouse."""
    if not data.warehouse_exists():
        st.info("No published warehouse yet: build one with `make build` or `docker compose up`.")
        st.stop()
    months = data.query("SELECT snapshot_month FROM meta.pipeline_runs ORDER BY 1 DESC")
    return st.sidebar.selectbox(
        "Snapshot month", months["snapshot_month"], format_func=lambda m: f"{m:{MONTH_FORMAT}}"
    )
