# PatchPilot

PatchPilot is a verified GitHub issue-to-draft-PR agent. It investigates a small bug, reproduces it, proposes a repair plan, pauses for human approval, applies a constrained patch, runs verification, reviews its own diff, and prepares a draft pull request with evidence.

Version 1 deliberately supports a narrow, safe workflow: one Python repository, deterministic test commands, a bounded file-change policy, and mandatory approval before any write or publication step.

## What is included

- A stateful agent workflow with explicit transitions and resumable approval
- A deterministic demo planner and an optional OpenAI Agents SDK planner
- Repository inspection, command-policy, patch-policy, and verification boundaries
- SQLite-backed run/event persistence
- FastAPI endpoints for runs, approvals, rejection, and audit history
- GitHub webhook and draft-PR adapter boundaries
- A deliberately broken fixture repository and executable end-to-end demo
- Unit tests for state transitions and security policies
- A responsive dashboard that works in demo mode without credentials
- Product, security, architecture, evaluation, and roadmap documentation

## Repository layout

```text
apps/api/                 FastAPI control plane and agent workflow
dist/                     Published dashboard prototype
fixtures/                 Safe repository used by the demo and evals
docs/                     Product and engineering documentation
scripts/run_demo.py       Local end-to-end agent demonstration
```

## Quick start

The deterministic workflow requires only Python 3.11+:

```bash
python3 scripts/run_demo.py
python3 -m unittest discover -s apps/api/tests -v
```

To run the API after installing the optional application dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn patchpilot.main:app --app-dir apps/api --reload
```

The OpenAI-backed planner is disabled by default. Set `PATCHPILOT_PLANNER=openai` and provide `OPENAI_API_KEY` only in a local secret manager or deployment environment. Never commit credentials.

## V1 safety contract

PatchPilot does not merge, deploy, access production, read secrets, execute arbitrary commands, or modify protected paths. A run must reproduce the issue and receive explicit human approval before patching. Publication creates a draft PR only.

## Documentation

- [Product plan](docs/PRODUCT_PLAN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Threat model and security](docs/SECURITY.md)
- [Evaluation plan](docs/EVALUATION.md)
- [Roadmap](docs/ROADMAP.md)

