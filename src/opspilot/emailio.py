"""Turning files into `RawEmail`, and attachments into text."""

import base64
import io
import json
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from pypdf import PdfReader

from opspilot.schemas.enums import Profile
from opspilot.schemas.state import AttachmentIn, RawEmail

MAX_ATTACHMENT_TEXT = 20_000


def attachment_text(filename: str, content_type: str, data: bytes) -> str:
    """Text from a PDF (pypdf), .txt or .csv attachment; empty string for unsupported types."""
    name = filename.lower()
    try:
        if name.endswith(".pdf") or content_type == "application/pdf":
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages).strip()[
                :MAX_ATTACHMENT_TEXT
            ]
        if name.endswith((".txt", ".csv")) or content_type.startswith("text/"):
            return data.decode("utf-8", errors="replace").strip()[:MAX_ATTACHMENT_TEXT]
    except Exception:  # corrupt attachment must not kill the run
        return ""
    return ""


def raw_from_seed_json(path: Path, attachments_dir: Path) -> RawEmail:
    d = json.loads(path.read_text())
    atts = [
        AttachmentIn(
            filename=a["filename"],
            content_type=a["content_type"],
            content_b64=base64.b64encode((attachments_dir / a["filename"]).read_bytes()).decode(),
        )
        for a in d.get("attachments", [])
    ]
    return RawEmail(
        message_id=d["message_id"], thread_id=d["thread_id"], from_name=d["from_name"], from_email=d["from_email"],
        to=d["to"], subject=d["subject"], body=d["body"], received_at=datetime.fromisoformat(d["received_at"]),
        thread_message_count=d.get("thread_message_count", 1),
        profile=Profile(d.get("profile", "ops")), attachments=atts,
    )  # fmt: skip


def _payload(part: EmailMessage) -> bytes:
    data = part.get_payload(decode=True)
    return data if isinstance(data, bytes) else b""


def raw_from_eml(data: bytes) -> RawEmail:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    name, addr = parseaddr(str(msg["From"] or ""))
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    atts = [
        AttachmentIn(
            filename=part.get_filename() or "attachment",
            content_type=part.get_content_type(),
            content_b64=base64.b64encode(_payload(part)).decode(),
        )
        for part in msg.iter_attachments()
    ]
    try:
        received = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else datetime.now(UTC)
    except (TypeError, ValueError):
        received = datetime.now(UTC)
    refs = str(msg["References"] or msg["In-Reply-To"] or "").split()
    return RawEmail(
        message_id=str(msg["Message-ID"]) if msg["Message-ID"] else None,
        thread_id=refs[0] if refs else None,
        from_name=name or None, from_email=addr, to=str(msg["To"] or "ops@northwind-supply.de"),
        subject=str(msg["Subject"] or "(no subject)"), body=str(body), received_at=received,
        thread_message_count=max(1, len(refs) + 1), attachments=atts,
    )  # fmt: skip
