"""OpsPilot dashboard entrypoint: `streamlit run dashboard/app.py`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make `dashboard.*` importable

import streamlit as st

from dashboard import api, theme

st.set_page_config(page_title="OpsPilot", page_icon=":material/hub:", layout="wide")
theme.apply()

pages = [
    st.Page("views/overview.py", title="Overview", icon=":material/monitoring:", default=True),
    st.Page("views/inbox.py", title="Inbox & Tasks", icon=":material/inbox:"),
    st.Page("views/review.py", title="Human Review", icon=":material/fact_check:"),
    st.Page("views/inspector.py", title="Run Inspector", icon=":material/account_tree:"),
    st.Page("views/evaluation.py", title="Evaluation", icon=":material/science:"),
    st.Page("views/simulate.py", title="Simulate", icon=":material/play_circle:"),
]
with st.sidebar:
    st.markdown("### OpsPilot")
    st.caption("AI operations assistant · Northwind Supply GmbH")
    try:
        h = api.get("/health")
        st.success(f"API online · {h['llm_provider']} provider", icon=":material/check_circle:")
    except api.ApiError as exc:
        st.error(str(exc))
st.navigation(pages).run()
