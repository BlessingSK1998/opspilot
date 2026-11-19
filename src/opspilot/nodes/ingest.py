"""Node 1: normalise the e-mail, extract attachment text, deduplicate."""

import base64
import hashlib
import re
import time
from typing import Any

from opspilot.emailio import attachment_text
from opspilot.nodes.common import Deps, finish
from opspilot.schemas.state import NormalizedMessage, OpsState


def content_hash(sender: str, subject: str, body: str, attachment_texts: list[str]) -> str:
    norm = re.sub(
        r"\s+", " ", f"{sender.lower()}|{subject}|{body}|{'|'.join(attachment_texts)}"
    ).strip()
    return hashlib.sha256(norm.encode()).hexdigest()


def assemble_text(subject: str, body: str, attachments: list[dict[str, Any]]) -> str:
    parts = [f"Subject: {subject}", "", body]
    for a in attachments:
        if a["text"]:
            parts += ["", f"[ATTACHMENT {a['filename']}]", a["text"]]
    return "\n".join(parts)


def ingest(state: OpsState, deps: Deps) -> dict[str, Any]:
    t0 = time.perf_counter()
    assert state.raw is not None, "ingest needs a raw email"
    raw = state.raw
    atts = []
    for a in raw.attachments:
        data = base64.b64decode(a.content_b64)
        atts.append(
            {
                "filename": a.filename,
                "content_type": a.content_type,
                "size_bytes": len(data),
                "text": attachment_text(a.filename, a.content_type, data),
            }
        )
    chash = content_hash(raw.from_email, raw.subject, raw.body, [str(a["text"]) for a in atts])
    msg = NormalizedMessage(
        external_id=raw.message_id, thread_id=raw.thread_id or f"T-{chash[:12]}", sender=raw.from_email.lower(),
        sender_name=raw.from_name, subject=raw.subject.strip(), body=raw.body.strip(), received_at=raw.received_at,
        thread_message_count=raw.thread_message_count, content_hash=chash, attachments=atts,
    )  # fmt: skip
    message_id = deps.backend.sink.register_message(msg, state.run_id)
    if message_id is None:
        return finish(
            "ingest",
            state,
            t0,
            "duplicate content: skipped",
            {"message": msg, "duplicate": True, "route": "duplicate"},
        )
    text = assemble_text(msg.subject, msg.body, atts)
    return finish(
        "ingest",
        state,
        t0,
        f"{len(atts)} attachment(s), {len(text)} chars",
        {"message": msg, "message_id": message_id, "email_text": text},
    )
