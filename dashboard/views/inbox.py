import pandas as pd
import streamlit as st

from dashboard import api, theme
from dashboard.helpers import (
    STATUS_COLOURS,
    chip,
    fields_table,
    fmt_dt,
    highlight,
    priority_chip,
    reason_chips,
    sla_label,
)

st.title("Inbox & tasks")

f1, f2, f3, f4, f5 = st.columns(5)
status = f1.selectbox(
    "Status",
    [
        "All",
        "pending_review",
        "ready_to_send",
        "awaiting_customer",
        "rejected",
        "archived",
        "closed",
    ],
)
priority = f2.selectbox("Priority", ["All", "P1", "P2", "P3", "P4"])
category = f3.selectbox(
    "Category",
    [
        "All",
        "order_request",
        "invoice_query",
        "refund_or_return",
        "complaint",
        "supplier_document",
        "access_or_it_request",
        "general_inquiry",
        "spam_or_irrelevant",
    ],
)
team = f4.selectbox(
    "Team",
    [
        "All",
        "Sales Operations",
        "Finance",
        "Customer Service",
        "Accounts Payable",
        "IT Service Desk",
        "Archive",
    ],
)
esc = f5.selectbox("Escalated", ["All", "Yes", "No"])

try:
    tasks = api.get(
        "/tasks",
        status=status,
        priority=priority,
        category=category,
        assignee=team,
        escalated={"Yes": True, "No": False}.get(esc),
    )
except api.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not tasks:
    theme.empty("No tasks match these filters.")
    st.stop()

df = pd.DataFrame(
    [
        {
            "Received": fmt_dt(t["received_at"]),
            "Priority": t["priority"],
            "Category": t["category"],
            "Subject": t["subject"][:70],
            "From": t["sender"],
            "Status": t["status"],
            "Team": t["assignee_team"],
            "SLA": sla_label(t["sla_due_at"]),
            "Escalated": "yes" if t["escalation_reasons"] else "",
            "Conf.": t["confidence"],
        }
        for t in tasks
    ]
)


@st.dialog("Task detail", width="large")
def show(task: dict) -> None:
    run = api.get(f"/runs/{task['run_id']}")
    st.markdown(f"### {run['message']['subject']}")
    st.markdown(
        f"{priority_chip(task['priority'])} {chip(task['status'], STATUS_COLOURS.get(task['status'], '#5B6B7F'))} {chip(task['category'], '#0F766E')} "
        f"<span class='muted'>{task['assignee_team']} · SLA {sla_label(task['sla_due_at'])}</span>",
        unsafe_allow_html=True,
    )
    if task["escalation_reasons"]:
        st.markdown(
            f"**Escalation reasons:** {reason_chips(task['escalation_reasons'])}",
            unsafe_allow_html=True,
        )

    left, right = st.columns(2)
    with left:
        st.markdown("**Original email**")
        spans = [v.get("source_span") or "" for v in run["fields"].values()]
        st.markdown(
            f"<div class='email'><b>From:</b> {run['message']['sender']}<br><br>{highlight(run['message']['body'], spans)}</div>",
            unsafe_allow_html=True,
        )
        for a in run["message"]["attachments"]:
            with st.expander(f"Attachment: {a['filename']}"):
                st.text(a["text"] or "(no text extracted)")
        st.caption("Yellow = text the extracted fields were taken from.")
    with right:
        st.markdown("**Extracted fields**")
        if run["fields"]:
            st.dataframe(
                pd.DataFrame(fields_table(run["fields"])),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Confidence": st.column_config.ProgressColumn(
                        min_value=0, max_value=1, format="%.2f"
                    )
                },
            )
        else:
            st.caption("No fields (spam or nothing extractable).")
        if run["missing_fields"]:
            st.warning("Missing: " + ", ".join(run["missing_fields"]))
        if run["validation_issues"]:
            st.error("Validation issues: " + ", ".join(run["validation_issues"]))
        for w in run["warnings"]:
            st.info(w)
        if run["injection_flags"]:
            st.error("Prompt-injection signals: " + ", ".join(run["injection_flags"]))

    st.markdown("**Draft** (never sent automatically)")
    if run["draft"]:
        st.markdown(
            f"<div class='card'><b>{run['draft']['subject']}</b> <span class='muted'>({run['draft']['kind']})</span><br><br>{run['draft']['body'].replace(chr(10), '<br>')}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No draft for this task.")
    if run["reviews"]:
        r = run["reviews"][0]
        st.markdown(
            f"**Human decision:** {r['action']} by {r['reviewer']}"
            + (f" - {r['reason']}" if r["reason"] else "")
        )

    with st.expander("Node trace"):
        st.dataframe(
            pd.DataFrame(run["audit"])[
                [
                    "node",
                    "latency_ms",
                    "tokens_in",
                    "tokens_out",
                    "model",
                    "prompt_version",
                    "output_summary",
                ]
            ],
            hide_index=True,
            use_container_width=True,
        )


st.caption(
    f"{len(tasks)} task(s). Tick the box at the left of a row to open it, or use the dropdown below."
)
sel = st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    height=330,
)
rows = sel.selection.rows if sel else []

labels = {f"{t['priority']} · {t['subject'][:55]} · {t['sender']}": i for i, t in enumerate(tasks)}
choice = st.selectbox("Open a task", ["Select a task…", *labels], key="open_task")
if rows:
    show(tasks[rows[0]])
elif choice != "Select a task…":
    show(tasks[labels[choice]])
