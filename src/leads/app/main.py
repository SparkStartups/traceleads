"""The app's navigation: one page per view."""

import streamlit as st

from leads.app import views

st.set_page_config(page_title="Leads", layout="wide")
st.navigation(
    [
        st.Page(views.leads, title="Leads"),
        st.Page(views.overview, title="Overview"),
        st.Page(views.month_over_month, title="Month over month"),
    ]
).run()
