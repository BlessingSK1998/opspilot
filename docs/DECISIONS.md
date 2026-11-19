# Decisions

| # | Decision | Alternatives | Rationale |
|---|----------|--------------|-----------|
| 1 | Project lives in `apps/opspilot/` of the existing monorepo | New repo | Matches repo conventions; CI uses `working-directory`. Can be split out with `git subtree`. |
| 2 | Default model `gpt-4o-mini`, overridable via `OPENAI_MODEL` | gpt-4.1-mini, newer | Cheap, supports Structured Outputs; verify name against docs in M3. |
| 3 | Dependencies added per milestone, not up front | Install everything now | Keeps each milestone's lockfile honest and installs fast. |
| 4 | Compose has only postgres + api in M1; dashboard/n8n added in M7/M9 | Stub services | No placeholder services that cannot start. |
| 5 | Mock provider is selected automatically when `OPENAI_API_KEY` is empty | Explicit flag | Zero-config demo for reviewers. |
