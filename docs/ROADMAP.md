# Roadmap

## Version 1 — verified Python repair agent

- Manual and webhook-triggered runs
- Python/FastAPI repositories
- Stateful workflow and audit events
- Deterministic and OpenAI-backed planning adapters
- Human approval before patching and publishing
- Restricted commands and bounded patches
- Test evidence and draft-PR contract
- Dashboard and initial benchmark fixture

## Version 1.1 — real GitHub pilot

- GitHub App installation flow
- Installation tokens and encrypted secret storage
- Repository onboarding and policy discovery
- Branch creation, commit, and draft PR publication
- Webhook idempotency and delivery diagnostics
- Server-sent progress events

## Version 2 — isolated worker platform

- PostgreSQL and durable job queue
- Container or microVM workers
- Network and resource policy per repository
- Worker snapshots and artifact retention
- Node.js/TypeScript repository adapter
- CI failure ingestion and focused retry

## Version 3 — team product

- Multi-tenant organizations and RBAC
- SSO, audit export, quotas, and cost controls
- Jira/Linear/Slack integrations
- Repository-specific memory and coding standards
- Policy templates and approval routing
- Evaluation regression gates before rollout

## Version 4 — bounded automation

- Risk-based automatic approval for test-only or documentation changes
- Multi-repository dependency repairs
- Scheduled backlog triage
- Patch ranking from multiple candidate attempts
- Organization-level analytics and model routing

Automatic merge and production deployment remain separate, explicitly governed capabilities rather than default behavior.

