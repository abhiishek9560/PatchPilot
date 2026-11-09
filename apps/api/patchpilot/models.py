from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStatus(StrEnum):
    RECEIVED = "received"
    INSPECTING = "inspecting"
    REPRODUCED = "reproduced"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    PATCHING = "patching"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    AWAITING_PUBLISH_APPROVAL = "awaiting_publish_approval"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.REJECTED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
}


@dataclass(slots=True)
class Issue:
    repository: str
    number: int
    title: str
    body: str
    default_branch: str = "main"


@dataclass(slots=True)
class RepairPlan:
    summary: str
    reproduction: str
    steps: list[str]
    expected_files: list[str]
    verification_commands: list[list[str]]
    risk: str = "low"
    assumptions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PatchProposal:
    unified_diff: str
    rationale: str
    changed_files: list[str]


@dataclass(slots=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass(slots=True)
class RunEvent:
    kind: str
    summary: str
    actor: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(slots=True)
class AgentRun:
    issue: Issue
    workspace: str
    status: RunStatus = RunStatus.RECEIVED
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    inspected_files: list[str] = field(default_factory=list)
    plan: RepairPlan | None = None
    patch: PatchProposal | None = None
    reproduction: CommandResult | None = None
    verification: list[CommandResult] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)
    plan_approved_by: str | None = None
    publish_approved_by: str | None = None
    pr_url: str | None = None
    failure: str | None = None

    def add_event(
        self,
        kind: str,
        summary: str,
        actor: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(RunEvent(kind, summary, actor, metadata or {}))
        self.updated_at = utc_now()

    def set_status(self, status: RunStatus, summary: str) -> None:
        previous = self.status
        self.status = status
        self.add_event(
            "state_changed",
            summary,
            metadata={"from": previous.value, "to": status.value},
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentRun":
        data = dict(payload)
        data["issue"] = Issue(**data["issue"])
        data["status"] = RunStatus(data["status"])
        if data.get("plan"):
            data["plan"] = RepairPlan(**data["plan"])
        if data.get("patch"):
            data["patch"] = PatchProposal(**data["patch"])
        if data.get("reproduction"):
            data["reproduction"] = CommandResult(**data["reproduction"])
        data["verification"] = [CommandResult(**item) for item in data.get("verification", [])]
        data["events"] = [RunEvent(**item) for item in data.get("events", [])]
        return cls(**data)

