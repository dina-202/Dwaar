"""Streamlit UI for the CA Notice Explainer. Zero logic — calls modules only."""

import streamlit as st

from modules.notice_explainer import explain_notice

st.set_page_config(
    page_title="CA Notice Explainer",
    page_icon="📋",
    layout="centered",
)

st.title("📋 CA Notice Explainer")
st.write(
    "Upload a GST or Income Tax notice PDF — get a plain-language "
    "explanation and a ready-to-send draft reply in seconds."
)

uploaded = st.file_uploader("Upload Notice PDF", type="pdf")

if uploaded:
    pdf_bytes = uploaded.read()

    with st.spinner("Analyzing notice..."):
        result = explain_notice(pdf_bytes)

    if result["success"]:
        st.success("Analysis complete")
        st.markdown(result["explanation"])
        with st.expander("View extracted notice text"):
            st.text(result["raw_text"][:2000])
    else:
        st.error(result["error"])

st.caption("Powered by Gemini AI")
