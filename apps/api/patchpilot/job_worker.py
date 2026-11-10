from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event

from .product_store import SQLiteProductStore


JobHandler = Callable[[dict], None]


class DurableJobWorker:
    """Lease-based job dispatcher shared by local and hosted background workers."""

    def __init__(
        self,
        store: SQLiteProductStore,
        worker_id: str,
        handlers: dict[str, JobHandler],
        *,
        lease_seconds: int = 300,
        retry_delay_seconds: int = 30,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id is required")
        self.store = store
        self.worker_id = worker_id
        self.handlers = handlers
        self.lease_seconds = lease_seconds
        self.retry_delay_seconds = retry_delay_seconds

    def run_once(self) -> bool:
        job = self.store.claim_job(self.worker_id, self.lease_seconds)
        if job is None:
            return False
        try:
            handler = self.handlers[job["kind"]]
            handler(job)
        except Exception as exc:
            self.store.fail_job(
                job["id"],
                self.worker_id,
                f"{type(exc).__name__}: {exc}",
                self.retry_delay_seconds,
            )
        else:
            self.store.complete_job(job["id"], self.worker_id)
        return True

    def run_forever(self, stop: Event, idle_seconds: float = 1.0) -> None:
        while not stop.is_set():
            if not self.run_once():
                stop.wait(idle_seconds)
            else:
                time.sleep(0)
