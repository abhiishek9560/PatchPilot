from __future__ import annotations

import shutil
from urllib.parse import urlencode
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .github import DemoPublisher, process_webhook_event, verify_webhook_signature
from .models import Issue
from .planner import DeterministicPlanner, OpenAIAgentPlanner
from .product_store import PostgresProductStore, SQLiteProductStore, User
from .security import hash_password, normalize_email, verify_password
from .store import PostgresRunStore, SQLiteRunStore
from .workflow import InvalidTransition, PatchPilotWorkflow


PROJECT_ROOT = Path(__file__).resolve().parents[3]
settings = Settings()
if settings.database_url:
    store = PostgresRunStore(settings.database_url)
    product_store = PostgresProductStore(settings.database_url)
else:
    store = SQLiteRunStore(PROJECT_ROOT / settings.database_path)
    product_store = SQLiteProductStore(PROJECT_ROOT / settings.database_path)
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
    version="1.0.0",
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


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=10, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class IssueAssignmentRequest(BaseModel):
    selection_mode: Literal["manual", "automatic"] = "manual"


class PlanFeedbackRequest(BaseModel):
    message: str = Field(min_length=3, max_length=2000)


class ProductApprovalRequest(BaseModel):
    stage: Literal["plan", "publish"]


def _run_or_404(run_id: str):
    try:
        return store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_lifetime_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def current_user(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> User:
    user = product_store.user_for_session(session_token) if session_token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _account_payload(user: User) -> dict:
    return {
        "user": user.to_dict(),
        "organizations": [item.to_dict() for item in product_store.organizations_for_user(user.id)],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "planner": settings.planner,
        "database": "postgresql" if settings.database_url else "sqlite",
    }


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return health()


@app.post("/api/auth/register", status_code=201)
def register(request: RegisterRequest, response: Response) -> dict:
    try:
        email = normalize_email(request.email)
        display_name = " ".join(request.display_name.strip().split())
        if len(display_name) < 2:
            raise ValueError("Display name must contain at least 2 characters")
        user, _ = product_store.register_user(
            email, display_name, hash_password(request.password)
        )
    except ValueError as exc:
        status_code = 409 if "already exists" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    token = product_store.create_session(user.id, settings.session_lifetime_days)
    _set_session_cookie(response, token)
    return _account_payload(user)


@app.post("/api/auth/login")
def login(request: LoginRequest, response: Response) -> dict:
    try:
        email = normalize_email(request.email)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid email or password") from exc
    record = product_store.authenticate(email)
    if record is None or not verify_password(request.password, record[1]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user = record[0]
    token = product_store.create_session(user.id, settings.session_lifetime_days)
    _set_session_cookie(response, token)
    return _account_payload(user)


@app.post("/api/auth/logout", status_code=204)
def logout(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> None:
    if session_token:
        product_store.delete_session(session_token)
    response.delete_cookie(settings.session_cookie_name, path="/")


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return _account_payload(user)


@app.post("/api/github/connect")
def connect_github(
    organization_id: str = Query(min_length=1), user: User = Depends(current_user)
) -> dict[str, str]:
    if not settings.github_app_slug:
        raise HTTPException(status_code=503, detail="GitHub App is not configured")
    try:
        state = product_store.begin_github_setup(user.id, organization_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    query = urlencode({"state": state})
    return {
        "install_url": f"https://github.com/apps/{settings.github_app_slug}/installations/new?{query}"
    }


@app.get("/api/github/setup")
def finish_github_setup(
    installation_id: int,
    state: str = Query(min_length=20),
    user: User = Depends(current_user),
) -> RedirectResponse:
    try:
        claimed_id = product_store.claim_github_installation(state, installation_id, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(url=f"/?github=connected&installation_id={claimed_id}#product", status_code=303)


@app.post("/api/github/webhooks", status_code=202)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
    x_github_event: str = Header(default=""),
) -> dict[str, str]:
    body = await request.body()
    if not verify_webhook_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature")
    if not x_github_delivery or not x_github_event:
        raise HTTPException(status_code=400, detail="Missing GitHub delivery headers")
    if not product_store.record_webhook_delivery(x_github_delivery, x_github_event):
        return {"status": "duplicate"}
    try:
        payload = await request.json()
        process_webhook_event(product_store, x_github_event, payload)
    except Exception as exc:
        product_store.finish_webhook_delivery(x_github_delivery, str(exc)[:500])
        raise HTTPException(status_code=422, detail="Webhook could not be processed") from exc
    product_store.finish_webhook_delivery(x_github_delivery)
    return {"status": "accepted"}


@app.get("/api/repositories")
def repositories(user: User = Depends(current_user)) -> list[dict]:
    return product_store.list_repositories(user.id)


@app.get("/api/issues")
def issues(
    repository_id: int | None = None, user: User = Depends(current_user)
) -> list[dict]:
    return product_store.list_issues(user.id, repository_id)


@app.post("/api/issues/{repository_id}/{issue_number}/assign", status_code=201)
def assign_issue(
    repository_id: int,
    issue_number: int,
    request: IssueAssignmentRequest,
    user: User = Depends(current_user),
) -> dict:
    try:
        return product_store.assign_issue(
            user.id, repository_id, issue_number, request.selection_mode
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/issues/auto-assign", status_code=201)
def auto_assign_issue(
    organization_id: str = Query(min_length=1), user: User = Depends(current_user)
) -> dict:
    try:
        return product_store.auto_assign_next_issue(user.id, organization_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/work-items")
def work_items(user: User = Depends(current_user)) -> list[dict]:
    return product_store.list_work_items(user.id)


@app.get("/api/work-items/{work_item_id}")
def get_work_item(work_item_id: str, user: User = Depends(current_user)) -> dict:
    try:
        return product_store.get_work_item(user.id, work_item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/work-items/{work_item_id}/plan-feedback", status_code=201)
def submit_plan_feedback(
    work_item_id: str,
    request: PlanFeedbackRequest,
    user: User = Depends(current_user),
) -> dict:
    try:
        return product_store.submit_plan_feedback(user.id, work_item_id, request.message)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/work-items/{work_item_id}/approvals", status_code=201)
def approve_work_item(
    work_item_id: str,
    request: ProductApprovalRequest,
    user: User = Depends(current_user),
) -> dict:
    try:
        return product_store.approve_work_item(user.id, work_item_id, request.stage)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


# Keep this mount last so API routes win before the single-page dashboard fallback.
app.mount("/", StaticFiles(directory=PROJECT_ROOT / "dist", html=True), name="dashboard")
