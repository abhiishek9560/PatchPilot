from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patchpilot.models import AgentRun, Issue, RunStatus  # noqa: E402
from patchpilot.store import SQLiteRunStore  # noqa: E402


class SQLiteRunStoreTests(unittest.TestCase):
    def test_round_trip_preserves_run_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = SQLiteRunStore(Path(temporary) / "runs.db")
            run = AgentRun(Issue("acme/api", 7, "Small defect", "Reproduce it"), temporary)
            run.set_status(RunStatus.INSPECTING, "Inspection started")
            store.save(run)

            restored = store.get(run.id)
            self.assertEqual(restored.status, RunStatus.INSPECTING)
            self.assertEqual(restored.issue.number, 7)
            self.assertEqual(restored.events[-1].kind, "state_changed")


if __name__ == "__main__":
    unittest.main()
