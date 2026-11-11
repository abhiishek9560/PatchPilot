# PatchPilot

PatchPilot is a human-approved code-repair agent that turns a small, reproducible
Python bug into a tested draft pull-request proposal.

It demonstrates the engineering around an agent, not just an LLM call: explicit
workflow state, bounded repository tools, policy enforcement, two approval gates,
SQLite persistence, test evidence, and an auditable event timeline.

**Live dashboard:** https://patchpilot-agent.dotingtulip8.chatgpt.site

> The hosted static dashboard is an interactive product demonstration. The
> executable workflow runs through FastAPI or the included CLI demo. Account and
> GitHub-intake foundations are now implemented locally; V1 still uses a synthetic
> publisher while isolated execution and live publication are completed.

## V1 workflow

~~~text
Issue received
    -> inspect repository
    -> reproduce defect
    -> create repair plan
    -> HUMAN APPROVAL
    -> generate and policy-check patch
    -> run verification
    -> review scope and evidence
    -> HUMAN APPROVAL
    -> create draft-PR record
~~~

The workflow fails closed if the defect cannot be reproduced, a command or path
is disallowed, the patch exceeds its budget, tests fail, or approval is missing.
V1 cannot merge code or deploy an application.

## What is implemented

- Resumable issue-to-draft-PR state machine
- Deterministic credential-free demo planner
- Optional OpenAI Agents SDK plan and patch adapter
- Bounded file inspection, subprocess execution, and unified-diff application
- Command, path, file-count, patch-size, and timeout policies
- Mandatory approval before patching and before publication
- SQLite-backed run and event persistence
- FastAPI endpoints for runs, approvals, rejection, and audit state
- GitHub webhook HMAC verification and a publisher interface
- Responsive dashboard with real local-API mode and public demo mode
- Docker runtime and GitHub Actions CI
- Account registration, secure browser sessions, and personal workspaces
- Signed/idempotent GitHub webhook intake with repository and issue projections
- Manual and automatic issue assignment with tenant authorization
- Durable lease/retry jobs, versioned plan feedback, and approval-driven queuing
- Short-lived GitHub App token exchange and real draft-PR API boundary
- 26 automated tests plus an executable end-to-end demo

## Quick demo

The deterministic demo has no external dependencies or API key:

~~~bash
python3 scripts/run_demo.py
python3 -m unittest discover -s apps/api/tests -v
~~~

Expected result: the bug is reproduced, the workflow pauses twice for approval,
the patch passes verification, and all 26 tests pass.

## Run the connected dashboard

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn patchpilot.main:app --app-dir apps/api --reload
~~~

Open http://127.0.0.1:8000. On localhost the dashboard calls the real FastAPI
workflow and stores runs in .patchpilot/patchpilot.db.

Docker is also supported:

~~~bash
docker compose up --build
~~~

## Deploy the web application

The FastAPI container serves both the dashboard and the API, so the deployed
product uses one origin for browser sessions, GitHub setup redirects, and
webhooks. A Render Blueprint is provided in `render.yaml`; see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the deployment and GitHub App
configuration.

## Optional LLM planner

Credential-free deterministic mode is the default. To use the real structured
model adapter:

~~~env
PATCHPILOT_PLANNER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=your_available_coding_model
~~~

The model proposes typed plans and diffs. Trusted PatchPilot code still owns
tools, policies, approvals, execution, and publication. Keep API keys only on
the backend and never commit .env.

## Repository layout

~~~text
apps/api/patchpilot/   FastAPI control plane and workflow
apps/api/tests/        Policy, workflow, persistence, and webhook tests
dist/                  Dashboard served by FastAPI and the public Site
fixtures/              Deliberately broken repository used by V1
docs/                  Product, architecture, security, evaluation, roadmap
scripts/run_demo.py    Credential-free end-to-end demonstration
~~~

## Honest V1 boundary

V1 supports one deliberately narrow Python fixture and a configured unit-test
command. The deterministic planner's patch is known in advance so CI remains
reproducible. The optional model adapter can propose a plan and patch, but V1
does not yet clone arbitrary private repositories or publish to the real GitHub
API.

The current production-MVP milestone adds PostgreSQL-backed orchestration,
task-specific isolated clones, plan feedback, real branch/commit/draft-PR
publication, and live progress events. See the [production MVP plan](docs/PRODUCTION_MVP.md).

## Documentation

- [Product plan](docs/PRODUCT_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security model](docs/SECURITY.md)
- [Evaluation plan](docs/EVALUATION.md)
- [Roadmap](docs/ROADMAP.md)
- [Production MVP plan](docs/PRODUCTION_MVP.md)

## License

MIT
