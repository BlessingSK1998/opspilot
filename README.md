# OpsPilot: AI Operations Assistant

**An agentic system that turns a messy shared operations inbox into classified, validated, routed work, drafts the reply, and makes a human approve anything risky. It runs end to end with no API key.**

<details><summary>Screenshot / GIF: how to capture it</summary>

1. `make demo` and open http://localhost:8501.
2. Record with any screen recorder (macOS: `Shift+Cmd+5`) at 1280x800: Overview, then **Human Review** (open the first case, click **Approve**), then **Simulate** (run a sample, watch the nodes complete).
3. Save as `docs/images/demo.gif` and screenshots as `docs/images/overview.png`, `review.png`; then embed with `![demo](docs/images/demo.gif)` here.
</details>

## The business problem

**Northwind Supply GmbH**: a 200-person B2B distributor of industrial parts in Hamburg. A 4-person operations team triages a shared inbox of ~150 messages a day **by hand**:

| Today | |
|---|---|
| Average first response | ~9 hours |
| Requests bounced back for missing information | 18% |
| Urgent issues | buried in the queue |

## The outcome (projected, assumptions stated)

Measured on the 80-email synthetic inbox (`make demo`, mock provider) and scaled to Northwind's volume:

| | Result | How it is derived |
|---|---|---|
| Handled with no human decision | **44%** (35 of 80) | draft ready to send, or spam archived |
| Missing info caught at triage | **17.5%** (14 of 80) | the specific missing fields are asked for in the *first* reply, so the 18% bounce-back round trip disappears |
| Escalated to a human | **39%** (31 of 80) | this set is deliberately escalation-heavy; production would be lower |
| Triage time per message | **seconds** vs ~6 min by hand | pipeline latency |
| Hours saved per week | **~50 h** (about 1.3 of 4 FTE) | 750 msgs/week x 4.1 min saved |
| First response time | **<= 4 h** vs ~9 h | worst case: every message answered at the *end* of its SLA window (P1 1h, P2 4h, P3 8h, P4 24h) |

**Assumptions (editable, in `api/metrics.py`):** manual triage = 6 min/message; a human decision on an escalation still costs 4 min; checking an info-request draft costs 2 min; 150 messages/day, 5 days/week. **These are planning assumptions, not measurements of Northwind.** The response-time figure is a bound, not a measured result: the system produces a draft in seconds, and how fast people send it is an operational choice.

## Architecture

```mermaid
flowchart LR
    Inbox[Shared inbox / n8n] -->|POST /ingest| API[FastAPI]
    API --> Graph[LangGraph pipeline]
    Graph -->|structured output| LLM{{LLMProvider\nOpenAI or Mock}}
    Graph <--> PG[(PostgreSQL 16\nbusiness data + checkpoints)]
    Dash[Streamlit dashboard] -->|REST only| API
    Human([Reviewer]) --> Dash
```

## The agent graph

```mermaid
flowchart TD
    A([email]) --> ingest -->|duplicate| Z([stop])
    ingest --> sanitize --> classify --> extract --> validate --> assess_priority
    assess_priority -->|spam| archive --> audit
    assess_priority -->|missing info / issues| draft_info_request
    assess_priority -->|complete| draft_response
    draft_info_request -->|no escalation| create_task
    draft_response -->|no escalation| create_task
    draft_info_request -->|escalation| queue_review
    draft_response -->|escalation| queue_review
    queue_review --> human_review{{"human_review (interrupt)"}}
    human_review -->|approve / edit / reject| create_task --> audit
```

Every node is a pure function `(OpsState, Deps) -> state update`, individually unit-tested, and writes an audit event (input hash, output summary, model, prompt version, tokens, cost, latency).

## Quickstart

```bash
git clone <this repo> && cd apps/opspilot
make demo        # Docker if present, otherwise an embedded Postgres. No API key needed.
```

Open **http://localhost:8501**. You will see a populated dashboard; open **Human Review**, approve a case, and watch the task become `ready_to_send`. API docs: http://localhost:8000/docs (header `X-API-Key: dev-key`).

`make test` · `make lint` · `make eval` (writes `reports/eval_<timestamp>.md`) · `make eval PROVIDER=openai` (real model, needs `OPENAI_API_KEY`). Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Optional n8n: `COMPOSE_PROFILES=n8n make up`, then import `integrations/n8n/opspilot_workflow.json` (n8n UI > Workflows > Import from file; attach IMAP, Slack and SMTP credentials).

## Personal inbox mode

The same pipeline also triages a **personal** mailbox (job search, finances, accounts, people). Each e-mail carries a `profile` (`ops` by default, or `personal`); the profile selects the categories, the classifier prompt and the routing, so the Northwind behaviour is untouched.

| Category | What happens |
|---|---|
| `job_application_update` | Received / rejected: **closed but kept visible** under team *Job search*. Interview / offer: **P1, human review**, with a reply draft |
| `finance_notice` | Needs action: **P2, human review** with a draft; purely informational: closed |
| `account_or_security` | Closed (informational), visible under *Accounts* |
| `personal_message` | Reply draft, ready for you to edit and send |
| `job_alert`, `newsletter_or_promo`, `spam_or_irrelevant` | Archived, no draft |

Personal mail is never answered with "please send us the missing information", and injection attempts still force a human review. Drafts are signed with `OPSPILOT_OWNER_NAME`. Use it by adding `"profile": "personal"` to the `/ingest` body, or pick **Personal inbox** on the Simulate page.

**Results on a 32-email synthetic personal set** (invented companies and people; `make eval` runs both sets):

| Metric | Mock | OpenAI `gpt-4.1-mini` |
|---|---|---|
| Classification accuracy / macro-F1 | 100.0% / 1.000 | 96.9% / 0.978 |
| Correct outcome (archived / closed / draft / review) | 90.6% | 100.0% |
| Escalation recall / precision | 100.0% / 70.0% | 100.0% / 100.0% |
| Extraction F1, micro | 0.966 | 0.932 |
| Injection resistance | 2 / 2 | 2 / 2 |
| Tokens per message / cost | 206 / €0 | 1162 / €0.00056 |

The mock cannot recognise an ordinary message from a person (it falls back to low confidence and asks for review), and the real model mislabelled one promotion as a job alert; both are in the report's error analysis. A smoke test on 34 real emails from the author's own inbox (not committed) archived 29 junk mails correctly, kept the 3 application replies visible, and sent the one payment reminder to review; one marketing mail from a "personal"-looking sender was wrongly given a reply draft. There is **no live Gmail/IMAP sync**: mail enters through `/ingest` or the n8n workflow.

## Results (evaluation on the 80-email synthetic set)

| Metric | Mock provider | OpenAI `gpt-4.1-mini` |
|---|---|---|
| Classification accuracy / macro-F1 | 100.0% / 1.000 | 100.0% / 1.000 |
| Escalation recall (system) | 100.0%, 0 missed | 100.0%, 0 missed |
| Escalation precision (system) | 87.1% (4 unneeded, all low-confidence safety net) | 100.0% |
| Missing-info precision / recall | 100.0% / 100.0% | 84.2% / 100.0% (3 false "missing": model left a field null) |
| Extraction F1, micro | 0.981 | 0.943 (general-inquiry `topic` free text drags it: 0.55) |
| Injection resistance | 3 / 3 | 3 / 3 |
| PII reaching the model | 0 | 0 |
| Tokens per message | 461 | 1980 |
| Cost per message | €0.00 | €0.0010 |
| End-to-end latency p50 / p95 | under 10 ms | 4.9 s / 6.7 s |

> **Read this honestly.** Both runs use the same *synthetic* data set, which is easy and written by the same hand as the mock's rules, so 100% classification says "the plumbing and prompts work", not "it will be 100% on real mail". The mock's numbers are a regression check only. The OpenAI run is the first real-model measurement (`reports/eval_20261120_*`). Worst remaining errors are in each report's error analysis (e.g. German free-text reasons vs English ground truth; the model sometimes leaves `company` or `severity_signal` empty, which the deterministic validator then flags as missing information). A separate smoke test on 15 real emails from the author's personal inbox (newsletters, promotions, job alerts) went from 14 of 15 wrongly sent to human review with the mock to 14 of 15 archived as irrelevant with the real model; that is anecdotal, not a measurement. Cost uses the built-in price table (EUR per message), which has not been reconciled with an OpenAI invoice.

## Key design decisions

- **Why LangGraph:** the process has real branches and a genuine pause (human approval). A checkpointer (Postgres) lets an interrupted run survive a restart and resume exactly where it stopped, proven in `tests/integration/test_pipeline_postgres.py`.
- **Why deterministic validation:** the LLM extracts; Python decides. Formats, completeness and cross-checks against the invoice/order/customer tables are code, so a hallucinated invoice number cannot pass, and results are explainable.
- **Why these human-in-the-loop thresholds:** hard rules (amount > €5,000, legal language, high-severity complaint, VIP, injection, 3+ unresolved messages) plus a low-confidence safety net. The LLM may *raise* priority, never lower it or suppress an escalation. Recall on escalation matters more than precision: a missed P1 costs more than an unneeded review.
- **Why a mock provider:** a reviewer can clone and see it work in minutes, CI runs the full eval offline, and the same nodes run against both providers.
- **Safety:** email is treated strictly as data (delimited, injection-flagged); PII (IBAN, phone, personal e-mail) is masked reversibly before any model sees it; drafts are never sent, and a guardrail replaces any draft containing identifiers or amounts not in the supplied facts; every human decision is audited.

All 41 decisions with alternatives are in [`docs/DECISIONS.md`](docs/DECISIONS.md). The as-is/to-be process, RACI and KPI definitions are in [`docs/PROCESS_MAP.md`](docs/PROCESS_MAP.md).

## Limitations and roadmap

**Limitations (honest):**
- Data is synthetic. The real-model run measures the system on that set only; real-world accuracy (messy attachments, long threads, other languages) is **unmeasured**. The mock is tuned to the synthetic data and fails on real mail.
- The OpenAI provider has been run against the live API for the 80-email eval and 15 real emails, but only with `gpt-4.1-mini`; the pricing table is unreconciled with billing.
- `docker compose` files and the n8n workflow were written but **not executed** (no Docker on the build machine); the embedded-Postgres path (`make demo-local`) is what was run and verified.
- No auth beyond a shared API key; no multi-tenant isolation; the dashboard has no user login (reviewer name is typed in).
- Replies are never sent: there is no SMTP/Gmail send integration by design.
- Tools are invoked by deterministic nodes, not chosen by a tool-calling loop (schemas are exported for that).

**Roadmap:** prompt iteration for company/severity extraction; held-out and real (anonymised) test data; send-after-approve integration; attachment OCR for scanned PDFs; per-customer SLA overrides; feedback loop turning reviewer edits into few-shot examples; LangSmith dashboards.

## What this demonstrates

| Skill | Where |
|---|---|
| Agents / orchestration | LangGraph graph with conditional routing, interrupt/resume, Postgres checkpointer (`graph/`, `runner.py`) |
| Tool calling | Typed tools with Pydantic schemas exported as OpenAI function specs (`tools/agent_tools.py`) |
| Structured outputs | Per-category schemas with value + confidence + source span (`schemas/extraction.py`), OpenAI Structured Outputs binding |
| Human-in-the-loop | Escalation rules, review queue, approve / edit / reject, audited decisions |
| Backend | FastAPI, typed OpenAPI, API-key auth, SSE streaming, idempotent ingest |
| Data modelling | 14-table Postgres schema, Alembic migrations, enums and indexes |
| Evaluation | Ground-truth harness: P/R/F1, confusion matrix, escalation recall with explicit false negatives, injection and PII checks, CI gate |
| Process design | As-is/to-be swimlane, RACI, KPI definitions, projected ROI with stated assumptions |
