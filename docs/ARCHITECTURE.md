# Architecture

## Trust boundaries

```text
GitHub / dashboard
        |
        | authenticated events and commands
        v
Trusted control plane (FastAPI)
  - run state and policy
  - approval decisions
  - model adapter
  - audit log
        |
        | narrow typed job specification
        v
Restricted execution workspace
  - task-specific repository copy
  - allowlisted commands
  - time / CPU / memory / network limits
  - no production credentials
        |
        | bounded artifacts and test evidence
        v
Trusted publisher
  - validates approval and review result
  - creates branch and draft PR
```

The language model never receives GitHub credentials and never talks directly to GitHub. It proposes structured plans and patches. Trusted application code validates and executes those proposals.

## Core modules

### Workflow engine

`workflow.py` owns legal state transitions. The workflow is deliberately explicit rather than an unbounded chat loop. Model output cannot skip reproduction, approval, verification, or review.

### Planner

`planner.py` defines a protocol with two implementations:

- `DeterministicPlanner` makes the repository executable and testable without credentials.
- `OpenAIAgentPlanner` uses the OpenAI Agents SDK for structured investigation and planning when configured.

The planner does not execute commands or publish changes. It receives bounded evidence and returns typed proposals.

### Execution policy

`policy.py` validates command binaries, paths, changed-file count, patch size, and protected locations. Enforcement occurs immediately before the side effect—not only in the prompt.

### Workspace

`repository.py` provides scoped file inspection, safe subprocess execution, patch application, and output truncation. The local implementation is suitable only for fixtures and dedicated clones. Production uses a container or microVM worker with a deny-by-default network policy.

### Persistence

`store.py` uses SQLite for V1 runs and events. `product_store.py` adds users,
digest-only sessions, organizations, GitHub installations, repositories, issues,
and idempotent webhook deliveries. SQLite remains the local adapter; the production
MVP moves these tables to PostgreSQL before multi-instance deployment.

### GitHub integration

`github.py` verifies webhook signatures, projects installation/repository/issue
events, and defines the draft-PR publication boundary. The API correlates installs
with short-lived setup state and claims them only after a matching signed webhook.
GitHub credentials stay in the trusted service. Live installation-token exchange
and draft-PR publication remain production-MVP work.

### API and dashboard

`main.py` exposes run lifecycle endpoints. The hosted dashboard is static and uses a realistic local demo store. When the FastAPI service is available, the same screen contract can call the API.

## State machine

```text
received
  -> inspecting
  -> reproduced
  -> plan_ready
  -> awaiting_approval
       -> rejected
       -> patching
  -> verifying
  -> reviewing
  -> ready_to_publish
  -> completed

Any active state -> failed or cancelled
```

Each transition records an event containing actor, timestamp, summary, and safe structured metadata.

## API outline

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service and configuration health |
| `POST` | `/api/auth/register` | Create an account and workspace |
| `POST` | `/api/auth/login` | Start an HTTP-only browser session |
| `GET` | `/api/auth/me` | Restore the signed-in account |
| `POST` | `/api/github/connect` | Begin a state-bound GitHub App install |
| `POST` | `/api/github/webhooks` | Receive signed, idempotent GitHub events |
| `GET` | `/api/repositories` | List authorized synchronized repositories |
| `GET` | `/api/issues` | List authorized synchronized issues |
| `POST` | `/api/issues/{repo}/{number}/assign` | Queue a user-selected issue |
| `POST` | `/api/issues/auto-assign` | Select and queue the next open issue |
| `GET` | `/api/work-items` | List authorized product work |
| `POST` | `/api/work-items/{id}/plan-feedback` | Request a versioned plan revision |
| `POST` | `/api/work-items/{id}/approvals` | Queue patch or publication after approval |
| `GET` | `/api/runs` | List demo runs |
| `POST` | `/api/runs/demo` | Create the bounded fixture run |
| `GET` | `/api/runs/{id}` | Run state and evidence |
| `POST` | `/api/runs/{id}/advance` | Execute next safe workflow step |
| `POST` | `/api/runs/{id}/approvals` | Approve the plan or draft-PR publication |
| `POST` | `/api/runs/{id}/rejection` | Reject a paused run |

Ordered audit events are included in each run response. Demo-run routes remain
separate from the authenticated production-product routes while ownership and the
durable worker queue are implemented.

## Production evolution

The production deployment replaces the local SQLite queue adapter with PostgreSQL,
runs the implemented lease-based dispatcher in isolated workers, adds server-sent
progress events, and connects the implemented GitHub App client to verified branch
pushes and draft-PR publication.
