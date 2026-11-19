import streamlit as st

from dashboard import api, theme
from dashboard.helpers import priority_chip, reason_chips, sla_label

VERBS = {"approve": "Approved", "edit": "Edited and approved", "reject": "Rejected"}

st.title("Human review queue")
st.caption(
    "Escalated cases wait here. Nothing is sent: approving makes the draft ready for a person to send."
)

try:
    pending = api.get("/reviews/pending")
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if msg := st.session_state.pop("review_flash", None):
    st.success(msg)
if not pending:
    theme.empty("The queue is empty. Nothing needs a decision right now.")
    st.stop()

st.markdown(f"**{len(pending)} case(s) waiting**")
for item in pending:
    t, d = item["task"], item["draft"]
    with st.expander(
        f"{t['priority']} · {t['subject']} · {t['sender']}", expanded=len(pending) == 1
    ):
        st.markdown(
            f"{priority_chip(t['priority'])} <span class='muted'>{t['category']} · {t['assignee_team']} · SLA {sla_label(t['sla_due_at'])}</span>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"**Why it needs a human:** {reason_chips(t['escalation_reasons'])}",
            unsafe_allow_html=True,
        )
        key = t["run_id"]
        subject = st.text_input("Subject", d["subject"] if d else "", key=f"s-{key}")
        body = st.text_area(
            "Draft reply (editable)", d["body"] if d else "", height=200, key=f"b-{key}"
        )
        reviewer = st.text_input(
            "Reviewer", st.session_state.get("reviewer", "ops.reviewer"), key=f"r-{key}"
        )
        reason = st.text_input("Reason (required to reject)", key=f"x-{key}")
        c1, c2, c3 = st.columns(3)

        def decide(
            action: str,
            *,
            run_id: str = key,
            _s: str = subject,
            _b: str = body,
            _r: str = reviewer,
            _x: str = reason,
        ) -> None:
            payload = {"action": action, "reviewer": _r, "reason": _x or None}
            if action == "edit":
                payload |= {"edited_subject": _s, "edited_body": _b}
            try:
                res = api.post(f"/reviews/{run_id}", payload)
                st.session_state["reviewer"] = _r
                st.session_state["review_flash"] = (
                    f"{VERBS[action]}: task is now **{res['task_status']}**."
                )
                st.rerun()
            except api.ApiError as exc:
                st.error(str(exc))

        if c1.button("Approve", key=f"a-{key}", type="primary", use_container_width=True):
            decide("approve")
        if c2.button(
            "Save edit & approve",
            key=f"e-{key}",
            use_container_width=True,
            disabled=not d or (body == d["body"] and subject == d["subject"]),
        ):
            decide("edit")
        if c3.button("Reject", key=f"j-{key}", use_container_width=True):
            decide("reject")
