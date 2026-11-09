from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Protocol

from .models import AgentRun


class RunStore(Protocol):
    def save(self, run: AgentRun) -> None: ...

    def get(self, run_id: str) -> AgentRun: ...

    def list(self) -> list[AgentRun]: ...


class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}

    def save(self, run: AgentRun) -> None:
        self._runs[run.id] = run.to_dict()

    def get(self, run_id: str) -> AgentRun:
        try:
            return AgentRun.from_dict(self._runs[run_id])
        except KeyError as exc:
            raise KeyError(f"Unknown run: {run_id}") from exc

    def list(self) -> list[AgentRun]:
        return [AgentRun.from_dict(payload) for payload in self._runs.values()]


class SQLiteRunStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def save(self, run: AgentRun) -> None:
        payload = json.dumps(run.to_dict(), separators=(",", ":"))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs(id, status, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (run.id, run.status.value, run.updated_at, payload),
            )

    def get(self, run_id: str) -> AgentRun:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown run: {run_id}")
        return AgentRun.from_dict(json.loads(row[0]))

    def list(self) -> list[AgentRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM agent_runs ORDER BY updated_at DESC"
            ).fetchall()
        return [AgentRun.from_dict(json.loads(row[0])) for row in rows]

