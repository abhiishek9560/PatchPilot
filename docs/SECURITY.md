# Threat Model and Security Contract

## Protected assets

- GitHub App private key and installation tokens
- Model API keys
- Source repositories and intellectual property
- CI/CD and production credentials
- Developer identity and approval decisions
- Integrity of branches, tests, and pull requests

## Primary threats

### Prompt injection in issues or repository files

An issue, README, comment, or source file may instruct the model to expose secrets or run dangerous commands. PatchPilot treats repository content as evidence, never as trusted instructions. The model can propose only typed actions; application policy decides whether they execute.

### Command execution

Generated shell text is never passed to `shell=True`. Commands are arrays, the executable must be allowlisted, arguments are checked, execution has a timeout, and output is bounded.

### Workspace escape

All resolved paths must remain below the task workspace. Symlinks that leave the workspace, absolute paths, parent traversal, device files, and protected paths are rejected.

### Credential exposure

Credentials exist only in the trusted control plane. They are never mounted into the execution environment or included in model messages, command output, logs, or PR content.

### Destructive or excessive change

V1 limits changed files and patch bytes. Workflow, infrastructure, secret, and Git metadata paths are protected. Automatic merge and deploy do not exist.

### Approval bypass

State transitions enforce approval in code. A model message saying “approved” is not approval. Approval requires an authenticated user action recorded with actor and timestamp.

### Duplicate events

Webhook and publication actions require idempotency keys. Replayed events return the existing result rather than repeating a side effect.

## V1 command policy

Allowed executables are configured, with a conservative default:

- `python`
- `pytest`
- `ruff`
- `mypy`
- `git`
- `rg`

Disallowed patterns include command separators, shell interpreters, privilege escalation, network clients, process control, device access, and filesystem operations outside the workspace.

## Production worker requirements

- Separate kernel boundary or hardened container runtime
- Non-root identity and no privilege escalation
- Read-only base filesystem
- Private task workspace with cleanup
- Deny-by-default outbound network
- CPU, memory, process, disk, and wall-clock limits
- No Docker socket or host home-directory mount
- Signed worker jobs and authenticated artifact upload
- Central audit logging and emergency worker revocation

## Human review points

V1 requires human review before patching and before publishing. Later versions may allow low-risk auto-patching, but publication remains governed by repository policy.

