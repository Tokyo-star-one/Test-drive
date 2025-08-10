# app.py
import os
import streamlit as st

# Prefer Streamlit secrets in the cloud, fall back to env for local dev
def _get(k, default=""):
    if "secrets" in st.runtime.scriptrunner.get_script_run_ctx().session_data:  # st.secrets available
        return st.secrets.get(k, os.getenv(k, default))
    return os.getenv(k, default)

# Import your scraper
from suumo_scraper import get_suumo_data, upload_to_airtable

st.set_page_config(page_title="Suumo → Airtable", page_icon="🏠", layout="centered")

st.title("Suumo → Airtable uploader")
st.caption("Paste a Suumo property URL, preview parsed data, then upload to Airtable.")

with st.form("scrape"):
    url = st.text_input("Suumo URL", placeholder="https://suumo.jp/chintai/…")
    do_upload = st.checkbox("Upload to Airtable after preview", value=False)
    submitted = st.form_submit_button("Run")

if submitted:
    if not url.strip():
        st.error("Please paste a URL.")
        st.stop()

    try:
        data = get_suumo_data(url)
    except Exception as e:
        st.exception(e)
        st.stop()

    st.subheader("Preview")
    st.json(data, expanded=False)

    if do_upload:
        try:
            res = upload_to_airtable(data)  # returns created record or prints success
            st.success("Uploaded to Airtable ✅")
            if isinstance(res, dict):
                st.json(res)
        except Exception as e:
            st.error("Upload failed.")
            st.exception(e)

st.divider()
st.caption("Env keys used: AIRTABLE_API_KEY, BASE_ID, TABLE_ID, STATIONS_TABLE_ID, "
           "LAYOUTS_TABLE_ID, PROP_TYPES_TABLE_ID, AREAS_TABLE_ID, PRICE_RANGE_TABLE_ID, PROPERTY_KIND_TABLE_ID")
