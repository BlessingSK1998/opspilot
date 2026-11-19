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
