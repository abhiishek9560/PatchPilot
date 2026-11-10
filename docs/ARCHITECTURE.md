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

`store.py` uses SQLite for V1 runs and events. The interface is intentionally small so PostgreSQL can replace it without changing workflow behavior.

### GitHub integration

`github.py` verifies webhook signatures and defines the draft-PR publication boundary. GitHub credentials stay in the trusted service. V1 uses a synthetic publisher; issue normalization and live GitHub publication are V1.1 work.

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
| `GET` | `/api/runs` | List runs |
| `POST` | `/api/runs/demo` | Create the bounded fixture run |
| `GET` | `/api/runs/{id}` | Run state and evidence |
| `POST` | `/api/runs/{id}/advance` | Execute next safe workflow step |
| `POST` | `/api/runs/{id}/approvals` | Approve the plan or draft-PR publication |
| `POST` | `/api/runs/{id}/rejection` | Reject a paused run |

Ordered audit events are included in each run response. A live GitHub webhook endpoint is intentionally deferred to V1.1; V1 unit-tests the signature-verification primitive and publisher interface.

## Production evolution

V2 replaces the in-process runner with a queue and isolated workers, SQLite with PostgreSQL, polling with server-sent events, and the synthetic publisher with a GitHub App installation-token flow.
