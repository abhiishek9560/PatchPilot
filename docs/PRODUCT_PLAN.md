# PatchPilot V1 Product Plan

## Product promise

PatchPilot converts a well-scoped GitHub bug report into a tested draft pull request while keeping a human in control of every consequential action.

It is not an autonomous employee and does not promise to solve every issue. Its job is to produce evidence: reproduction, a bounded plan, a minimal patch, verification results, and a reviewable draft PR—or a clear, safe failure.

## Target user

The first user is a developer or small engineering team maintaining a Python/FastAPI service with pytest or unittest. The user has GitHub issues that are clear but repetitive: validation bugs, incorrect status codes, missing error handling, pagination defects, and small regressions.

## Primary journey

1. A GitHub issue receives the configured label.
2. PatchPilot validates repository scope and issue content.
3. It creates a run and records an immutable audit event.
4. It inspects the repository and selects relevant files.
5. It executes the configured reproduction command in an isolated workspace.
6. It prepares a structured plan, expected files, risk, and verification commands.
7. A human approves, edits, or rejects the plan.
8. PatchPilot applies a bounded patch in the workspace.
9. It runs focused and full verification commands.
10. A reviewer step checks policy, diff size, unrelated changes, tests, and protected paths.
11. With separate publish approval, it creates a branch and draft PR.
12. It stores the outcome, cost, latency, tool calls, and evaluation labels.

## V1 functional requirements

### Runs

- Create a run manually or from a validated webhook
- Persist issue, repository, branch, state, budget, and timestamps
- Resume from the last safe state
- Cancel, reject, or fail closed
- Provide an ordered event timeline

### Repository investigation

- Work only in a task-specific clone or fixture copy
- List and search files under configured limits
- Read text files with size limits
- Detect test framework and configured commands
- Never read protected files or follow links outside the workspace

### Planning

- Produce structured summary, reproduction, steps, expected files, risks, and tests
- Separate evidence from model inference
- Stop when the issue is too broad or cannot be reproduced
- Require approval before any write

### Patching and verification

- Apply a unified diff to allowed files
- Limit changed-file count and patch bytes
- Execute allowlisted commands with timeouts
- Capture exit code and bounded stdout/stderr
- Require a passing focused test and full configured suite

### Review and publication

- Reject changes to protected paths
- Reject deleted or weakened tests unless explicitly approved
- Reject oversized or unrelated diffs
- Produce a PR summary containing issue, plan, files, and test evidence
- Create a draft PR only; never merge or deploy

### Dashboard

- Portfolio metrics and recent runs
- Run timeline with live state
- Plan approval and rejection
- Changed files and diff summary
- Test evidence, policy decisions, cost, and latency
- Repository policies and evaluation results

## Non-functional requirements

- Every state transition is idempotent
- Every side effect has an idempotency key
- Every command and policy decision is logged
- Secrets never enter model context or workspace files
- User-supplied issue text is treated as untrusted input
- The workflow fails closed on missing approval, timeout, or ambiguous state
- Demo mode runs without network or API credentials

## Explicit V1 exclusions

- Automatic merge or production deployment
- Arbitrary repositories or programming languages
- Large feature requests or architectural rewrites
- Database migrations and infrastructure changes
- Production credentials or customer data
- Autonomous vulnerability exploitation
- Multi-tenant billing and marketplace distribution

## Definition of done

- The fixture issue fails before the patch and passes after it
- A run cannot patch before approval
- Protected paths and disallowed commands are rejected by tests
- An interrupted run can be loaded from persistence
- The dashboard demonstrates request, investigation, approval, verification, and draft-PR states
- Evaluation documentation defines a reproducible benchmark rather than invented metrics

