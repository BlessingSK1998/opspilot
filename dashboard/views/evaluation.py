import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import api, theme

st.title("Evaluation")
dataset = st.radio(
    "Data set",
    ["ops", "personal"],
    horizontal=True,
    format_func=lambda d: {
        "ops": "Operations inbox (80 emails)",
        "personal": "Personal inbox (32 emails)",
    }[d],
)
try:
    data = api.get("/eval/latest", dataset=dataset)
except api.ApiError as exc:
    theme.empty(
        f"No evaluation report available yet.<br>Run <code>make eval</code>. <span class='muted'>({exc})</span>"
    )
    st.stop()

r = data["report"]
st.caption(f"Report: {data['name']} · provider: {r['provider']} · {r['n_messages']} messages")
if r["provider"] == "mock":
    st.info(
        "Mock provider: its rules were written against the same synthetic templates, so near-perfect scores are a regression check, not a generalisation claim. Run `make eval` with an API key for real-model numbers.",
        icon=":material/info:",
    )

c = st.columns(4)
with c[0]:
    theme.kpi(
        "Classification accuracy",
        f"{r['classification']['accuracy']:.1%}",
        f"macro-F1 {r['classification']['macro_f1']:.3f}",
    )
with c[1]:
    theme.kpi(
        "Escalation recall",
        f"{r['escalation']['recall']:.1%}",
        f"{len(r['escalation']['false_negatives'])} missed",
    )
with c[2]:
    theme.kpi(
        "Missing-info recall",
        f"{r['missing_info']['recall']:.1%}",
        f"precision {r['missing_info']['precision']:.1%}",
    )
with c[3]:
    theme.kpi(
        "Injection resistance",
        f"{r['injection']['resisted']}/{r['injection']['attempts']}",
        "behaviour unchanged",
    )

st.subheader("Confusion matrix")
labels = r["classification"]["labels"]
fig = px.imshow(
    r["classification"]["confusion"],
    x=labels,
    y=labels,
    text_auto=True,
    color_continuous_scale=["#FFFFFF", "#0F766E"],
    labels={"x": "predicted", "y": "actual"},
)
fig.update_layout(height=480, coloraxis_showscale=False)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Field extraction (per category)")
st.dataframe(
    pd.DataFrame(r["extraction"]).T.rename_axis("category").reset_index(),
    hide_index=True,
    use_container_width=True,
)

st.subheader("Latency, tokens and cost")
st.dataframe(
    pd.DataFrame(r["latency_ms"]).T.rename_axis("node").reset_index(),
    hide_index=True,
    use_container_width=True,
)
st.caption(
    f"Tokens per message: {r['tokens_per_message']:.0f} · cost per message: €{r['cost_per_message_eur']:.5f}"
)

st.subheader("Error analysis: worst cases")
for case in r["error_analysis"]:
    st.markdown(f"- **{case['id']}** ({case['category']}): {case['reason']}")
if not r["error_analysis"]:
    st.caption("No errors in this run.")
with st.expander("Full report (Markdown)"):
    st.markdown(data["markdown"])
