import json

import streamlit as st

from dashboard import api
from dashboard.helpers import priority_chip, reason_chips

st.title("Simulate an inbound email")
st.caption(
    "Pick a sample or paste your own, run it live, and watch each node of the graph complete."
)

try:
    samples = api.get("/samples")
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

mode = st.radio("Source", ["Sample email", "Write my own"], horizontal=True)
raw: dict | None = None
if mode == "Sample email":
    opts = {f"{s['id']} · {s['subject'][:60]} · {s['from_email']}": s["id"] for s in samples}
    pick = st.selectbox("Sample", list(opts))
    raw = api.get(f"/samples/{opts[pick]}")
    with st.expander("Preview", expanded=True):
        st.text(raw["body"])
    suffix = st.checkbox("Make unique (so it is not ignored as a duplicate)", value=True)
    if suffix:
        raw["subject"] = f"{raw['subject']} [sim {st.session_state.get('sim_n', 0)}]"
        raw["body"] += f"\n\n(simulation #{st.session_state.get('sim_n', 0)})"
else:
    sender = st.text_input("From", "anna.klein@isar-gruppe.de")
    subject = st.text_input("Subject", "Frage zu Lieferzeiten")
    body = st.text_area(
        "Body",
        "Hello,\n\nWhat is your typical lead time for hydraulic valves?\n\nBest regards\nAnna Klein",
        height=160,
    )
    raw = {"from_email": sender, "subject": subject, "body": body}

if st.button("Run through OpsPilot", type="primary"):
    st.session_state["sim_n"] = st.session_state.get("sim_n", 0) + 1
    done = None
    with st.status("Running pipeline…", expanded=True) as box:
        try:
            for ev in api.stream_simulation(raw):
                if ev["event"] == "node":
                    st.markdown(
                        f"✅ **{ev['node']}** · {ev['latency_ms']} ms · {ev['tokens']} tokens  \n<span class='muted'>{ev['summary']}</span>",
                        unsafe_allow_html=True,
                    )
                elif ev["event"] == "interrupt":
                    st.markdown("⏸️ **paused: waiting for a human decision**")
                elif ev["event"] == "done":
                    done = ev
            box.update(label="Finished" if done else "No result", state="complete", expanded=True)
        except api.ApiError as exc:
            box.update(label="Failed", state="error")
            st.error(str(exc))
    if done:
        run = api.get(f"/runs/{done['run_id']}")
        t = run["task"]
        if t is None:
            st.info(
                "Duplicate content: this email was already processed, so no new task was created."
            )
        else:
            st.markdown(
                f"**Result:** {priority_chip(t['priority'])} {t['category']} → **{t['status']}** ({t['assignee_team']})",
                unsafe_allow_html=True,
            )
            if t["escalation_reasons"]:
                st.markdown(
                    f"Escalated: {reason_chips(t['escalation_reasons'])}. Open **Human Review** to decide.",
                    unsafe_allow_html=True,
                )
            if run["draft"]:
                st.markdown("**Draft reply**")
                st.code(run["draft"]["body"], language=None)
            with st.expander("Extracted fields"):
                st.code(json.dumps(run["fields"], indent=2, ensure_ascii=False), language="json")
