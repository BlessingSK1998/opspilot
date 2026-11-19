import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard import api, theme
from dashboard.helpers import CATEGORY_COLOURS, PRIORITY_COLOURS, pct

st.title("Operations overview")
try:
    m = api.get("/metrics")
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if m["messages_processed"] == 0:
    theme.empty(
        "No messages processed yet.<br>Run <code>make demo</code> or use the <b>Simulate</b> page to ingest an email."
    )
    st.stop()

cols = st.columns(4)
with cols[0]:
    theme.kpi("Messages processed", f"{m['messages_processed']:,}", "all time")
with cols[1]:
    theme.kpi(
        "Auto-resolved",
        pct(m["auto_resolved_pct"]),
        "draft ready or spam archived, no human needed",
    )
with cols[2]:
    theme.kpi("Needing info", pct(m["needs_info_pct"]), "awaiting customer reply")
with cols[3]:
    theme.kpi("Escalated", pct(m["escalated_pct"]), f"{m['pending_reviews']} waiting for review")
st.write("")
cols = st.columns(3)
with cols[0]:
    secs = m["median_processing_seconds"]
    theme.kpi(
        "Median processing time",
        ("-" if secs is None else f"{secs * 1000:.0f} ms" if secs < 1 else f"{secs:.1f} s"),
        "ingest → task, excl. human wait",
    )
with cols[1]:
    theme.kpi(
        "Estimated hours saved",
        f"{m['estimated_hours_saved']:.1f} h",
        f"vs {m['assumptions']['manual_minutes_per_message']:.0f} min manual triage per message",
    )
with cols[2]:
    theme.kpi("LLM cost per message", f"€{m['llm_cost_per_message_eur']:.4f}", "mock provider = €0")

st.write("")
left, right = st.columns([3, 2])
with left:
    st.subheader("Volume by category (per hour received)")
    df = pd.DataFrame(m["volume_by_category"])
    fig = px.bar(
        df, x="date", y="count", color="category", color_discrete_sequence=CATEGORY_COLOURS
    )
    fig.update_layout(legend_title_text="", height=320, bargap=0.25)
    st.plotly_chart(fig, use_container_width=True)
with right:
    st.subheader("Priority distribution")
    pdf = pd.DataFrame(
        {
            "priority": list(m["priority_distribution"]),
            "tasks": list(m["priority_distribution"].values()),
        }
    )
    fig2 = px.bar(
        pdf, x="priority", y="tasks", color="priority", color_discrete_map=PRIORITY_COLOURS
    )
    fig2.update_layout(showlegend=False, height=320)
    st.plotly_chart(fig2, use_container_width=True)

st.subheader("SLA breach risk")
sla = m["sla"]
c1, c2, c3 = st.columns(3)
with c1:
    theme.kpi("Open tasks", str(sla["open"]), "not closed / archived / rejected")
with c2:
    theme.kpi("First-response SLA breached", str(sla["breached"]), "due time already passed")
with c3:
    theme.kpi("At risk (< 2 h)", str(sla["at_risk"]), "due within two hours")
st.caption(
    "Hours saved = messages × manual minutes − human minutes still spent on escalations and info requests. Assumptions are editable constants in the API (see README)."
)
