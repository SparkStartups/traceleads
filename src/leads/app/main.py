"""The app's navigation: one page per view."""

import streamlit as st

from leads.app import views

st.set_page_config(page_title="Leads", layout="wide")
st.navigation([st.Page(views.leads, title="Leads")]).run()
