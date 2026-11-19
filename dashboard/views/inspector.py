import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

from dashboard import api, theme

st.title("Run inspector")
try:
    tasks = api.get("/tasks", limit=200)
    mermaid = api.get("/graph")["mermaid"]
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not tasks:
    theme.empty("No runs yet.")
    st.stop()

labels = {
    f"{t['received_at'][5:16].replace('T', ' ')} · {t['subject'][:50]} · {t['run_id'][:8]}": t[
        "run_id"
    ]
    for t in tasks
}
choice = st.selectbox("Run", list(labels))
run = api.get(f"/runs/{labels[choice]}")

c1, c2, c3, c4 = st.columns(4)
audit = run["audit"]
with c1:
    theme.kpi("Status", run["status"], f"provider: {run['provider']}")
with c2:
    theme.kpi("Nodes executed", str(len(audit)))
with c3:
    theme.kpi("Tokens", f"{sum(a['tokens_in'] + a['tokens_out'] for a in audit):,}")
with c4:
    theme.kpi("Cost", f"€{sum(a['cost_eur'] for a in audit):.5f}")

st.subheader("Trace")
df = pd.DataFrame(audit)
st.dataframe(
    df[
        [
            "node",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "model",
            "prompt_version",
            "input_hash",
            "output_summary",
        ]
    ],
    hide_index=True,
    use_container_width=True,
)
fig = px.bar(df, x="latency_ms", y="node", orientation="h", color_discrete_sequence=["#0F766E"])
fig.update_layout(
    height=max(220, 28 * len(df)),
    yaxis={"autorange": "reversed"},
    xaxis_title="latency (ms)",
    yaxis_title="",
)
st.plotly_chart(fig, use_container_width=True)

with st.expander("Raw state: classification, fields, validation"):
    st.json(
        {
            k: run[k]
            for k in (
                "classification",
                "fields",
                "missing_fields",
                "validation_issues",
                "warnings",
                "injection_flags",
            )
        }
    )

st.subheader("Graph")
executed = [a["node"] for a in audit]
st.caption("Executed in this run: " + " → ".join(executed))
components.html(
    f"""<pre class="mermaid">{mermaid}</pre>
    <script type="module">import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs';
    mermaid.initialize({{startOnLoad: true, theme: 'neutral'}});</script>""",
    height=560,
    scrolling=True,
)
