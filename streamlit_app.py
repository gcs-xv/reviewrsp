import streamlit as st
from parser_html import parse_simrs_html_to_review, DPJP_MAP

st.set_page_config(page_title="RSPTN Review Generator", page_icon="🩺", layout="centered")
st.title("🩺 RSPTN Patient Review Generator (HTML mode)")

st.markdown(
    """
    Upload the **HTML** file you exported from SIMRS (print → save as HTML).  
    This app will automatically extract the latest CPPT entry and generate the review.
    """
)

uploaded = st.file_uploader("📄 Upload HTML file", type=["html", "htm"])
operator = st.text_input("👨‍⚕️ Operator (manual)", "")
dpjp_override = st.selectbox("🩺 DPJP (optional override)", ["(auto from CPPT)"] + list(DPJP_MAP.values()))

if uploaded:
    html_text = uploaded.read().decode("utf-8", errors="ignore")
    dpjp = None if dpjp_override == "(auto from CPPT)" else dpjp_override
    review = parse_simrs_html_to_review(html_text, dpjp_override=dpjp, operator=operator)
    st.code(review, language="markdown")
    st.download_button("⬇️ Download review.txt", review.encode("utf-8"), "review.txt", "text/plain")
