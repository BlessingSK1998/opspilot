"""Deterministic offline provider: keyword/regex based, no network, runs the full eval in seconds.

It is deliberately *not* an oracle. It sees only the (sanitised) email text, like the real
model, so eval numbers in mock mode are honest about what simple rules can and cannot do.
"""

import re
from typing import Any

from opspilot.llm.base import LLMResult
from opspilot.prompts import load_prompt
from opspilot.schemas.enums import Category, DraftKind
from opspilot.schemas.extraction import (
    SCHEMAS,
    AccessOrItRequest,
    BoolField,
    CategoryExtraction,
    Complaint,
    FloatField,
    GeneralInquiry,
    IntListField,
    InvoiceQuery,
    OrderRequest,
    RefundOrReturn,
    StrField,
    StrListField,
    SupplierDocument,
)
from opspilot.schemas.llm import ClassificationResult, DraftResult, RiskAssessment, Usage

MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]

SKU = r"NW-\d{4}"
DOC_NO = r"\b(?:RE-\d{7}|LS-\d{5}|CERT-\d{4}-[A-D])\b"

# (pattern, weight) per category. Weights were tuned by hand on the dev set, not the eval set.
RULES: dict[Category, list[tuple[str, float]]] = {
    Category.SUPPLIER_DOCUMENT: [
        (DOC_NO, 10),
        (r"\[ATTACHMENT[^\]]*\]\s*\n.*\n(?:Document type)", 6),
    ],
    Category.ACCESS_OR_IT_REQUEST: [
        (r"access to|Zugriff auf|Access request|Berechtigungsstufe|Access level", 4),
        (r"line manager|Vorgesetzte", 2),
    ],
    Category.ORDER_REQUEST: [
        (rf"{SKU}", 2),
        (r"place an order|bestellen|Bestellung\b", 3),
        (r"Delivery address|Lieferadresse", 3),
        (r"Requested delivery|Wunschtermin", 3),
        (r"last order|letzten Bestellung", 4),
    ],
    Category.INVOICE_QUERY: [
        (r"INV-\d{4}-\d{5}", 5),
        (r"\b(?:Rechnung|invoice)\b", 2),
        (
            r"doppelt erhalten|twice|nie angekommen|never received|zu viel berechnet|charged too much",
            2,
        ),
    ],
    Category.REFUND_OR_RETURN: [
        (r"return goods|zurückgeben|Retoure|Erstattungsbetrag|Refund amount", 4),
        (r"\bReason:|\bGrund:", 3),
        (r"\bItems: |Artikel: ", 1),
    ],
    Category.COMPLAINT: [
        (r"unacceptable|inakzeptabel|Complaint|Beschwerde", 4),
        (
            r"production line|Produktionslinie|incomplete|unvollständig|\brust|Rost|dented|eingedrückt",
            4,
        ),
        (r"two days late|zu spät|wrong contact|falsche Ansprechpartner|damages|Schadensersatz", 3),
    ],
    Category.GENERAL_INQUIRY: [
        (r"\?", 1.5),
        (
            r"catalogue|Katalog|opening hours|Öffnungszeiten|lead time|Lieferzeit|certificate|Skonto|discount|minimum order|Mindestbestellwert|customer account|Kundenkonto",
            4,
        ),
        (r"Frage|Question", 1),
    ],
    Category.SPAM_OR_IRRELEVANT: [
        (
            r"bit\.ly|https?://|bitcoin|crypto|Rolex|prince|guarantee|ranking|Unsubscribe|CONGRATULATIONS|Verify your password|suspended",
            4,
        ),
    ],
}

INJECTION_NOISE = re.compile(
    r"(?i)ignore (all )?previous instructions|system override|disregard prior rules|forget everything"
)


def _body_only(text: str) -> str:
    """Drop quoted reply lines so a thread is judged on its newest message."""
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith(">"))


def _search(pattern: str, text: str, flags: int = 0) -> tuple[str, str] | None:
    m = re.search(pattern, text, flags)
    if not m:
        return None
    return (m.group(1) if m.groups() else m.group(0)).strip(), m.group(0).strip()


def parse_date(raw: str) -> str | None:
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", raw):
        return m.group(0)
    if m := re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw):
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2}) ([A-Za-z]+) (\d{4})", raw)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}"
    return None


def parse_amount(raw: str) -> float | None:
    m = re.search(r"\d[\d.,]*", raw)
    if not m:
        return None
    s = m.group(0).rstrip(".,")
    if "," in s and "." in s:
        s = (
            s.replace(".", "").replace(",", ".")
            if s.rfind(",") > s.rfind(".")
            else s.replace(",", "")
        )
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def is_german(text: str) -> bool:
    de = len(
        re.findall(
            r"\b(?:bitte|wir|ihr|und|der|die|das|nicht|Rechnung|Grüße|Hallo|Guten Tag|möchten|euch)\b",
            text,
            re.I,
        )
    )
    en = len(re.findall(r"\b(?:please|we|the|and|you|our|regards|hello|would|with)\b", text, re.I))
    return de > en


class MockProvider:
    name = "mock"
    model = "mock-rules-v1"

    # ---- helpers --------------------------------------------------------
    def _usage(self, prompt: str, text: str, out: str) -> Usage:
        return Usage(
            model=self.model,
            prompt_version=prompt,
            tokens_in=len(text) // 4,
            tokens_out=len(out) // 4,
            cost_eur=0.0,
            latency_ms=1,
        )

    # ---- classify -------------------------------------------------------
    def classify(self, email_text: str) -> LLMResult[ClassificationResult]:
        text = _body_only(email_text)
        text = INJECTION_NOISE.sub("", text)
        cutoff = max(1, int(len(text) * 0.45))
        scores: dict[Category, float] = {}
        for cat, rules in RULES.items():
            s = 0.0
            for pat, w in rules:
                for m in re.finditer(
                    pat, text, re.I if cat is not Category.SUPPLIER_DOCUMENT else 0
                ):
                    s += w * (1.5 if m.start() < cutoff else 1.0)
                    break  # one hit per rule: weight signals, not repetition
            scores[cat] = s
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        (best, top), (_, second) = ranked[0], ranked[1]
        if top < 2.5 or (best is Category.GENERAL_INQUIRY and top < 4.5):
            best, conf = Category.GENERAL_INQUIRY, 0.55
            rationale = "No strong signals; treated as a general or unclear inquiry."
        else:
            conf = round(min(0.97, 0.6 + 0.37 * (top - second) / max(top, 1)), 2)
            rationale = f"Matched {best.value} keywords (score {top:.1f} vs {second:.1f})."
        res = ClassificationResult(category=best, confidence=conf, rationale=rationale)
        return LLMResult(res, self._usage(load_prompt("classify").version, email_text, rationale))

    # ---- risk -----------------------------------------------------------
    def assess_risk(self, email_text: str) -> LLMResult[RiskAssessment]:
        t = _body_only(email_text)
        legal = bool(
            re.search(
                r"(?i)Rechtsanwalt|lawyer|legal (?:action|advice|department)|rechtliche Schritte|Rechtsabteilung|Schadensersatz|claim damages|DSGVO|GDPR",
                t,
            )
        )
        high = bool(
            re.search(
                r"(?i)production line|Produktionslinie|unacceptable|inakzeptabel|stopped|steht seit",
                t,
            )
        )
        medium = bool(
            re.search(
                r"(?i)two days late|zu spät|incomplete|unvollständig|\brust|Rost|damaged|beschädigt",
                t,
            )
        )
        severity = "high" if high else "medium" if medium else "low"
        urgency = 1 if (high or legal) else 2 if medium else 3
        rat = f"severity={severity}, legal={legal}"
        return LLMResult(
            RiskAssessment(
                urgency=urgency, severity_signal=severity, legal_language=legal, rationale=rat
            ),
            self._usage(load_prompt("risk").version, email_text, rat),
        )

    # ---- extract --------------------------------------------------------
    def extract(self, category: Category, email_text: str) -> LLMResult[CategoryExtraction]:
        text = _body_only(email_text)
        fn = {
            Category.ORDER_REQUEST: self._order,
            Category.INVOICE_QUERY: self._invoice,
            Category.REFUND_OR_RETURN: self._refund,
            Category.COMPLAINT: self._complaint,
            Category.SUPPLIER_DOCUMENT: self._supplier,
            Category.ACCESS_OR_IT_REQUEST: self._access,
            Category.GENERAL_INQUIRY: self._general,
        }.get(category)
        result = fn(text) if fn else SCHEMAS[category]()
        return LLMResult(
            result,
            self._usage(load_prompt("extract").version, email_text, result.model_dump_json()),
        )

    @staticmethod
    def _sig(text: str) -> tuple[str, str] | None:
        m = re.search(r"\n--\n(.+)\n(.+)\nTel\.", text)
        return (m.group(1).strip(), m.group(2).strip()) if m else None

    def _str(self, found: tuple[str, str] | None, conf: float = 0.9) -> StrField | None:
        return StrField(value=found[0], confidence=conf, source_span=found[1]) if found else None

    def _order(self, text: str) -> OrderRequest:
        skus: list[str] = []
        qtys: list[int] = []
        spans: list[str] = []
        for ln in text.split("\n"):
            for pat, order in (
                (rf"^- (\d+) x ({SKU})", "qs"),
                (rf"^- (\d+) Stk\. ({SKU})", "qs"),
                (rf"^- ({SKU}): (\d+) pcs", "sq"),
                (rf"^({SKU}),(\d+)$", "sq"),
                (rf"^- ({SKU})\b", "s"),
            ):
                m = re.match(pat, ln.strip())
                if m:
                    spans.append(ln.strip())
                    if order == "qs":
                        qtys.append(int(m.group(1)))
                        skus.append(m.group(2))
                    elif order == "sq":
                        skus.append(m.group(1))
                        qtys.append(int(m.group(2)))
                    else:
                        skus.append(m.group(1))
                    break
        sig = self._sig(text)
        date = _search(r"(?:Requested delivery|Wunschtermin): (.+)", text)
        return OrderRequest(
            customer_name=StrField(value=sig[0], confidence=0.85, source_span=sig[0])
            if sig
            else None,
            company=StrField(value=sig[1], confidence=0.85, source_span=sig[1]) if sig else None,
            product_skus=StrListField(value=skus, confidence=0.95, source_span="; ".join(spans))
            if skus
            else None,
            quantities=IntListField(value=qtys, confidence=0.9, source_span="; ".join(spans))
            if skus and len(qtys) == len(skus)
            else None,
            delivery_address=self._str(_search(r"(?:Delivery address|Lieferadresse): (.+)", text)),
            requested_date=(
                StrField(value=d, confidence=0.9, source_span=date[1])
                if date and (d := parse_date(date[0]))
                else None
            ),
            po_number=self._str(_search(r"(PO-\d{6})", text)),
        )

    def _invoice(self, text: str) -> InvoiceQuery:
        sig = self._sig(text)
        amt = _search(r"(?:Amount|Betrag): (.+)", text) or _search(r"Total gross: (.+)", text)
        kind = None
        for k, pat in (
            ("duplicate", r"doppelt|twice"),
            ("missing", r"nie angekommen|never received"),
            ("overcharge", r"zu viel|too much"),
            ("other", r"stimmen so nicht|do not look right"),
        ):
            if m := re.search(pat, text, re.I):
                kind = (k, m.group(0))
                break
        return InvoiceQuery(
            invoice_number=self._str(_search(r"(INV-\d{4}-\d{5})", text), 0.97),
            company=StrField(value=sig[1], confidence=0.85, source_span=sig[1]) if sig else None,
            amount=(
                FloatField(value=a, confidence=0.9, source_span=amt[1])
                if amt and (a := parse_amount(amt[0])) is not None
                else None
            ),
            issue_type=StrField(value=kind[0], confidence=0.75, source_span=kind[1])
            if kind
            else StrField(value="other", confidence=0.4, source_span=None),
        )

    def _refund(self, text: str) -> RefundOrReturn:
        sig = self._sig(text)
        items = _search(r"(?:Items|Artikel): ((?:NW-\d{4}(?:, )?)+)", text)
        amt = _search(r"(?:Refund amount|Erstattungsbetrag): (.+)", text)
        return RefundOrReturn(
            order_number=self._str(_search(r"(SO-\d{4}-\d{5})", text), 0.97),
            company=StrField(value=sig[1], confidence=0.85, source_span=sig[1]) if sig else None,
            reason=self._str(_search(r"(?:Reason|Grund): (.+)", text), 0.85),
            items=StrListField(
                value=re.findall(SKU, items[0]), confidence=0.95, source_span=items[1]
            )
            if items
            else None,
            amount=(
                FloatField(value=a, confidence=0.9, source_span=amt[1])
                if amt and (a := parse_amount(amt[0])) is not None
                else None
            ),
        )

    def _complaint(self, text: str) -> Complaint:
        sig = self._sig(text)
        body = text.split("\n\n", 2)
        desc = body[1].split("\n")[0].strip() if len(body) > 1 else ""
        sev = self.assess_risk(text).parsed.severity_signal
        return Complaint(
            company=StrField(value=sig[1], confidence=0.85, source_span=sig[1]) if sig else None,
            order_number=self._str(_search(r"(SO-\d{4}-\d{5})", text), 0.97),
            severity_signal=StrField(value=sev, confidence=0.7, source_span=desc[:80] or None),
            description=StrField(value=desc, confidence=0.8, source_span=desc) if desc else None,
        )

    def _supplier(self, text: str) -> SupplierDocument:
        head = _search(r"\[ATTACHMENT[^\]]*\]\n(.+)\n", text)
        dtype = _search(r"Document type: (.+)", text)
        amt = _search(r"Total: (.+)", text)
        due = _search(r"Payment due: (.+)", text)
        return SupplierDocument(
            supplier_name=self._str(head, 0.9),
            document_type=(
                StrField(value=dtype[0].replace(" ", "_"), confidence=0.95, source_span=dtype[1])
                if dtype
                else None
            ),
            document_number=self._str(_search(f"({DOC_NO[2:-2]})", text), 0.97),
            amount=(
                FloatField(value=a, confidence=0.9, source_span=amt[1])
                if amt and (a := parse_amount(amt[0])) is not None
                else None
            ),
            due_date=(
                StrField(value=d, confidence=0.9, source_span=due[1])
                if due and (d := parse_date(due[0]))
                else None
            ),
        )

    def _access(self, text: str) -> AccessOrItRequest:
        who = _search(
            r"(?:Please grant|Bitte) ([A-ZÄÖÜ][\w]+ [A-ZÄÖÜ][\w]+)(?: access| Zugriff)", text
        )
        system = _search(r"(?:access to|Zugriff auf) (.+?)\.?$", text, re.M)
        level = _search(r"(?:Access level|Berechtigungsstufe): (read|write|admin)", text)
        approval: BoolField | None = None
        if m := re.search(r"Approved by|zugestimmt", text):
            approval = BoolField(value=True, confidence=0.85, source_span=m.group(0))
        if m := re.search(r"has not been asked|noch nicht gefragt", text):
            approval = BoolField(value=False, confidence=0.85, source_span=m.group(0))
        return AccessOrItRequest(
            employee_name=self._str(who),
            system=self._str(system),
            access_level=self._str(level),
            manager_approval=approval,
        )

    def _general(self, text: str) -> GeneralInquiry:
        parts = text.split("\n\n")
        q = parts[1].split("\n")[0].strip() if len(parts) > 1 else ""
        topic = "unclear"
        for key, pat in (
            ("opening hours", r"opening hours|Öffnungszeiten"),
            ("material certificates", r"certificate|Werkstoffzeugnis"),
            ("lead times", r"lead time|Lieferzeit"),
            ("catalogue", r"catalogue|Katalog"),
            ("payment terms", r"discount|Skonto"),
            ("account opening", r"account|Kundenkonto"),
            ("minimum order", r"minimum order|Mindestbestellwert"),
            ("product advice", r"pump|Pumpen"),
        ):
            if re.search(pat, q, re.I):
                topic = key
                break
        return GeneralInquiry(
            topic=StrField(
                value=topic,
                confidence=0.5 if topic == "unclear" else 0.8,
                source_span=q[:80] or None,
            ),
            question=StrField(value=q, confidence=0.8, source_span=q) if q else None,
        )

    # ---- drafting -------------------------------------------------------
    def draft(self, kind: DraftKind, facts: dict[str, Any]) -> LLMResult[DraftResult]:
        de = bool(facts.get("language") == "de")
        name = facts.get("customer_name")
        hi = (
            (f"Guten Tag {name}," if name else "Guten Tag,")
            if de
            else (f"Hello {name}," if name else "Hello,")
        )
        bye = (
            "Mit freundlichen Grüßen\nNorthwind Supply GmbH, Operations Team"
            if de
            else "Kind regards\nNorthwind Supply GmbH, Operations Team"
        )
        if kind is DraftKind.INFO_REQUEST:
            labels = facts.get("field_labels", {})
            items = "\n".join(f"- {labels.get(f, f)}" for f in facts.get("missing_fields", []))
            issues = "\n".join(f"- {i}" for i in facts.get("issue_messages", []))
            if de:
                body = f"{hi}\n\nvielen Dank für Ihre Nachricht. Damit wir sie bearbeiten können, benötigen wir noch:\n{items}"
                body += f"\n\nZusätzlich bitten wir um Klärung:\n{issues}" if issues else ""
                subject = "Rückfrage zu Ihrer Anfrage"
            else:
                body = f"{hi}\n\nthank you for your message. To process it we still need:\n{items}"
                body += f"\n\nWe also need clarification on:\n{issues}" if issues else ""
                subject = "Information needed for your request"
        else:
            body = self._response_body(facts, de, hi)
            subject = "Ihre Anfrage bei Northwind" if de else "Your request to Northwind"
        body += f"\n\n{bye}"
        d = DraftResult(subject=subject, body=body)
        return LLMResult(
            d,
            self._usage(
                load_prompt(
                    "draft_response" if kind is DraftKind.RESPONSE else "draft_info_request"
                ).version,
                str(facts),
                body,
            ),
        )

    def _response_body(self, facts: dict[str, Any], de: bool, hi: str) -> str:
        f = facts.get("fields", {})
        cat = facts.get("category")
        rec = facts.get("records", {})
        if cat == "order_request":
            n = len(f.get("product_skus", []))
            return (
                f"{hi}\n\nvielen Dank für Ihre Bestellung über {n} Position(en). Wir prüfen Verfügbarkeit und Liefertermin für "
                f"{f.get('delivery_address', 'die angegebene Adresse')}; ein Kollege bestätigt Ihnen beides in Kürze."
                if de
                else f"{hi}\n\nthank you for your order of {n} line item(s). We are checking availability and the delivery date for "
                f"{f.get('delivery_address', 'the given address')}; a colleague will confirm both shortly."
            )
        if cat == "invoice_query":
            inv = rec.get("invoice")
            extra = (
                f" (Betrag laut System: {inv['amount']:.2f} EUR)"
                if inv and de
                else f" (amount on file: EUR {inv['amount']:.2f})"
                if inv
                else ""
            )
            return (
                f"{hi}\n\nwir prüfen Ihre Rechnung {f.get('invoice_number', '')}{extra} und melden uns mit dem Ergebnis."
                if de
                else f"{hi}\n\nwe are reviewing invoice {f.get('invoice_number', '')}{extra} and will come back to you with the result."
            )
        if cat == "refund_or_return":
            return (
                f"{hi}\n\nwir haben Ihre Retoure zu Bestellung {f.get('order_number', '')} erhalten. Wir prüfen sie und senden Ihnen die nächsten Schritte."
                if de
                else f"{hi}\n\nwe have received your return request for order {f.get('order_number', '')}. We are reviewing it and will send you the next steps."
            )
        if cat == "complaint":
            return (
                f"{hi}\n\nes tut uns leid, dass es zu diesem Problem kam. Ihr Anliegen liegt jetzt bei einem Kollegen, der sich zeitnah bei Ihnen meldet."
                if de
                else f"{hi}\n\nwe are sorry about this problem. Your case is now with a colleague who will contact you shortly."
            )
        if cat == "supplier_document":
            return f"{hi}\n\nwe confirm receipt of document {f.get('document_number', '')}; it has been passed to Accounts Payable."
        if cat == "access_or_it_request":
            return f"{hi}\n\nyour access request for {f.get('system', 'the system')} has been logged and sent to IT for processing."
        return (
            f"{hi}\n\nvielen Dank für Ihre Frage. Ein Kollege antwortet Ihnen in Kürze."
            if de
            else f"{hi}\n\nthank you for your question. A colleague will reply shortly."
        )
