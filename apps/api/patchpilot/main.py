from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .github import DemoPublisher
from .models import Issue
from .planner import DeterministicPlanner, OpenAIAgentPlanner
from .store import SQLiteRunStore
from .workflow import InvalidTransition, PatchPilotWorkflow


PROJECT_ROOT = Path(__file__).resolve().parents[3]
settings = Settings()
store = SQLiteRunStore(PROJECT_ROOT / settings.database_path)
planner = (
    OpenAIAgentPlanner(settings.openai_model)
    if settings.planner == "openai"
    else DeterministicPlanner()
)
workflow = PatchPilotWorkflow(
    store=store,
    planner=planner,
    publisher=DemoPublisher(),
    allowed_commands=settings.allowed_commands,
    protected_paths=settings.protected_paths,
    max_changed_files=settings.max_changed_files,
    max_patch_bytes=settings.max_patch_bytes,
    timeout_seconds=settings.command_timeout_seconds,
)

app = FastAPI(
    title="PatchPilot API",
    version="0.1.0",
    description="A bounded GitHub issue-to-draft-PR agent with human approval gates.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class DemoRunRequest(BaseModel):
    repository: str = "acme/accounts-api"
    issue_number: int = 142
    title: str = "Email validator accepts incomplete domains"
    body: str = "`user@example` is accepted, but the API contract requires a dotted domain."


class ApprovalRequest(BaseModel):
    approval: Literal["plan", "publish"]
    actor: str = Field(min_length=2, max_length=100)


class RejectionRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=3, max_length=500)


def _run_or_404(run_id: str):
    try:
        return store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "planner": settings.planner}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return [run.to_dict() for run in store.list()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return _run_or_404(run_id).to_dict()


@app.post("/api/runs/demo", status_code=201)
def create_demo_run(request: DemoRunRequest) -> dict:
    fixture = PROJECT_ROOT / "fixtures" / "email-validator"
    workspace_root = (PROJECT_ROOT / settings.workspace_root).resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace = workspace_root / f"issue-{request.issue_number}-{len(store.list()) + 1}"
    if workspace.exists():
        raise HTTPException(status_code=409, detail="Demo workspace already exists")
    shutil.copytree(fixture, workspace)
    issue = Issue(
        repository=request.repository,
        number=request.issue_number,
        title=request.title,
        body=request.body,
    )
    run = workflow.create_run(issue, workspace)
    return workflow.run_until_pause(run.id).to_dict()


@app.post("/api/runs/{run_id}/advance")
def advance_run(run_id: str) -> dict:
    _run_or_404(run_id)
    return workflow.run_until_pause(run_id).to_dict()


@app.post("/api/runs/{run_id}/approvals")
def approve_run(run_id: str, request: ApprovalRequest) -> dict:
    _run_or_404(run_id)
    try:
        workflow.approve(run_id, request.approval, request.actor)
        return workflow.run_until_pause(run_id).to_dict()
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/rejection")
def reject_run(run_id: str, request: RejectionRequest) -> dict:
    _run_or_404(run_id)
    try:
        return workflow.reject(run_id, request.actor, request.reason).to_dict()
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
