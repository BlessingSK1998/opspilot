# Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|--------------|-----------|
| 1 | Project lives in `apps/opspilot/` of the existing monorepo | New repo | Matches repo conventions; CI uses `working-directory`. Can be split out with `git subtree`. |
| 2 | Default model `gpt-4o-mini`, overridable via `OPENAI_MODEL` | gpt-4.1-mini, newer | Cheap, supports Structured Outputs; verify name against docs in M3. |
| 3 | Dependencies added per milestone, not up front | Install everything now | Keeps each milestone's lockfile honest and installs fast. |
| 4 | Compose has only postgres + api in M1; dashboard/n8n added in M7/M9 | Stub services | No placeholder services that cannot start. |
| 5 | Mock provider is selected automatically when `OPENAI_API_KEY` is empty | Explicit flag | Zero-config demo for reviewers. |
| 6 | Order lines stored as JSONB on `orders` (no `order_lines` table) | Normalised table | Spec lists a fixed table set; lines are always read with the order and never queried across orders. |
| 7 | Integration tests use embedded Postgres (`pgserver`) unless `TEST_DATABASE_URL` is set | Docker-only (testcontainers) | Real Postgres (enums, JSONB, checkpointer) with zero setup on any laptop or CI runner; compose Postgres still used for `make up`. |
| 8 | Inbound emails are not inserted by `make seed`; they go through `POST /ingest` | Pre-populate messages/tasks | Dashboard data then comes from the real pipeline, so what a reviewer sees is what the system produces. Seed loads reference data only. |
| 9 | Seed data is generated deterministically (fixed RNG seed, reportlab `invariant=1`) and committed | Generate on demand only | Reviewers see the data without running anything; a test proves regeneration is byte-identical. Ground truth is written by the same code as the emails so they cannot drift. |
| 10 | Eval set is deliberately escalation-heavy (~1/3 of emails) | Realistic base rate (~10%) | A realistic base rate would leave too few positives to measure escalation recall. README states production rates would be lower. |
| 11 | Supplier delivery notes/certificates do not require `amount`/`due_date`; supplier invoices do | Require for all | A certificate has no amount. Required-field list is per document type. |
| 12 | `access_or_it_request` with `manager_approval=false` is a *validation issue* (awaiting approval), not an escalation | Escalate | Hard escalation rules in the brief are an explicit list; stay within it. |
| 13 | Low-confidence escalation (<0.7) is not labelled in ground truth | Label vague emails | It is a runtime model signal. Vague emails are flagged `ambiguous` and reported separately in eval. |
| 14 | Order value for the €5,000 rule = SKU unit price x quantity from the product table (net); invoices/refunds use the stated gross amount | Always gross | Orders carry no stated amount, so it must be computed. |
| 15 | Default `OPENAI_MODEL=gpt-4.1-mini` (supports Structured Outputs + temperature 0). Web search could not confirm the single newest cheap model; GPT-5.x reasoning models reject `temperature`, so the provider omits it for `gpt-5*`/`o*` | Newest GPT-5.x mini | Predictable determinism for classify/extract. Override with `OPENAI_MODEL`; pricing table in `llm/pricing.py` is approximate and unverified against the live pricing page. |
| 16 | `LLMProvider` is task-oriented (`classify/extract/assess_risk/draft`), not a raw `complete()` | Generic completion interface | The mock can implement tasks directly; prompts and schemas stay behind the provider. |
| 17 | Mock provider sees only sanitised text, like the real model, and is not an oracle | Mock reads ground truth | Offline eval numbers are honest about what simple rules achieve. |
| 18 | Nodes are `(OpsState, Deps) -> partial state update` functions; `Deps` = provider + backend (reference reader + sink) | Classes with hidden state | Pure and individually testable; the same nodes run against Postgres or in-memory backends. |
| 19 | Read/write ports (`Reference`, `Sink`) with SQL and in-memory implementations | Eval talks to Postgres | Offline eval of 80 emails runs in seconds without a database; the production path uses identical node code. |
| 20 | Agent "tools" are typed functions with Pydantic arg schemas, exported as OpenAI function specs (`tool_specs()`), invoked deterministically by nodes | Free-form LLM tool loop | Predictable, auditable and cheap; schemas allow a tool-calling model to be dropped in later. |
| 21 | PII masking covers IBANs, phones and *personal-provider* e-mails; business e-mails stay | Mask all e-mails | Business addresses/domains are needed to match customers. Reversible via `pii_map`. |
| 22 | SLA clock starts at message `received_at`; "requested date in the past" is judged against `received_at`, not wall clock | Wall clock | Deterministic, and correct for backlogs and for the fixed-date synthetic data. Demo ingestion rebases timestamps to "now". |
| 23 | Any validation issue routes to an info request (awaiting_customer) | Only missing fields | A wrong invoice number or mismatched amount needs customer clarification before anyone acts on it. |
| 24 | Priority = most urgent of (rules, LLM urgency); LLM may raise priority but never lower or suppress an escalation | LLM decides | Keeps escalation recall deterministic and explainable. |
| 25 | Mock rules were written against the same templates as the synthetic emails | Hold out a separate set | Mock-mode eval is therefore a regression test, **not** a generalisation claim. README and eval report say so; real-model numbers are the meaningful ones. |
