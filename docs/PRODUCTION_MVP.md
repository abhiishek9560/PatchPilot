# Production MVP plan

PatchPilot's public V1 proves the controlled repair workflow. The production MVP
turns that workflow into a multi-user GitHub product without weakening its two
human approval gates.

## Product journey

1. A user registers or signs in and receives an HTTP-only browser session.
2. The user installs the PatchPilot GitHub App on selected repositories.
3. Signed, idempotent webhooks synchronize installations, repositories, and issues.
4. A user explicitly assigns an issue, or enables an allowlisted auto-pick policy.
5. A worker clones a task-specific revision into an isolated, disposable workspace.
6. PatchPilot reproduces the issue and creates a structured plan with evidence.
7. The user approves, rejects, or requests a revised plan. Approval is persisted.
8. A worker produces a bounded patch, runs configured checks, and records evidence.
9. The user reviews the diff and verification results and approves publication.
10. A short-lived GitHub App installation token pushes a branch and creates a draft PR.

PatchPilot never merges the PR or deploys the repository.

## Target architecture

```text
Browser
   |
   v
FastAPI web service ---- PostgreSQL
   |                         |
   | enqueue                 | durable jobs, approvals, audit events
   v                         |
Redis queue -----------------+
   |
   v
Isolated worker job ---- disposable repository workspace
   |
   +---- OpenAI model (structured proposals only)
   +---- GitHub App (short-lived installation token)
```

The API owns identity, authorization, GitHub webhooks, policy, and approval state.
Workers receive a narrow job specification and no long-lived user credential. A
model may propose a plan or diff, but trusted code owns tools and side effects.

## Delivery sequence

### Slice 1 — identity and GitHub intake

- Account registration, login, logout, and workspace membership
- Scrypt password hashes and digest-only session storage
- HTTP-only, `SameSite=Lax`, secure-in-production cookies
- GitHub App installation state tied to an owner workspace
- Webhook HMAC verification and delivery idempotency
- Repository and issue projections

Status: implemented. The local executable uses SQLite until the PostgreSQL adapter
and migrations land in Slice 2.

### Slice 2 — durable orchestration

- PostgreSQL schema and migrations
- Job queue with claim/lease/retry semantics
- User-owned issue assignment and automatic-selection policy
- Plan revisions, comments, approvals, and live progress events
- Per-run authorization on every API operation

### Slice 3 — real patch and PR

- GitHub App JWT and one-hour installation-token exchange
- Task-specific clone pinned to the issue repository and default-branch SHA
- Isolated execution with CPU, memory, time, filesystem, and network limits
- Branch creation, signed audit metadata, push, and draft-PR REST call
- Retry-safe publication so one run cannot create duplicate PRs

### Slice 4 — launch

- Authenticated dashboard for repositories, issues, plans, diffs, and run history
- Rate limits, email verification/reset, encrypted secrets, observability, and backups
- Abuse controls and an allowlisted pilot before arbitrary public repositories
- End-to-end staging tests followed by a limited public beta

## Deployment choice

The fastest coherent first deployment is Render:

- one web service for FastAPI and the dashboard;
- one background worker for queued repair jobs;
- managed PostgreSQL for durable product state;
- managed Key Value for the queue.

Vercel or the existing Site can host a separated marketing/frontend surface later,
but repository cloning and test execution belong in isolated background compute,
not a request-scoped frontend function. The current public Site remains the honest
interactive showcase until the authenticated Render deployment is ready.

## Launch definition

The MVP is ready for real pilot users only when a newly registered user can install
the GitHub App, select an issue, revise and approve a generated plan, observe an
isolated verified patch run, approve publication, and receive exactly one real
draft PR—with tenant authorization and audit events verified by automated tests.
