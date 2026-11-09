from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

from patchpilot.github import DemoPublisher  # noqa: E402
from patchpilot.models import Issue  # noqa: E402
from patchpilot.planner import DeterministicPlanner  # noqa: E402
from patchpilot.store import MemoryRunStore  # noqa: E402
from patchpilot.workflow import PatchPilotWorkflow  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="patchpilot-demo-") as temporary:
        workspace = Path(temporary) / "accounts-api"
        shutil.copytree(PROJECT_ROOT / "fixtures" / "email-validator", workspace)
        store = MemoryRunStore()
        workflow = PatchPilotWorkflow(store, DeterministicPlanner(), DemoPublisher())
        run = workflow.create_run(
            Issue(
                repository="acme/accounts-api",
                number=142,
                title="Email validator accepts incomplete domains",
                body="`user@example` should be rejected.",
            ),
            workspace,
        )

        run = workflow.run_until_pause(run.id)
        assert run.status.value == "awaiting_plan_approval"
        print(f"1. Plan ready and paused for approval: {run.id}")

        workflow.approve(run.id, "plan", "demo-reviewer")
        run = workflow.run_until_pause(run.id)
        assert run.status.value == "awaiting_publish_approval", run.failure
        print("2. Patch applied, verified, reviewed, and paused before publication")

        run = workflow.approve(run.id, "publish", "demo-reviewer")
        assert run.status.value == "completed"
        print("3. Draft PR created after second human approval")
        print(json.dumps({"status": run.status.value, "pr_url": run.pr_url}, indent=2))


if __name__ == "__main__":
    main()
