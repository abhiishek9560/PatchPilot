# Evaluation Plan

PatchPilot is evaluated on outcomes and traces, not screenshots or subjective demonstrations.

## Benchmark composition

Start with 20 seeded issues across two small FastAPI repositories:

- 4 validation defects
- 3 HTTP/status-code defects
- 3 authorization defects
- 3 pagination/query defects
- 3 error-handling defects
- 2 caching/idempotency defects
- 2 dependency or configuration regressions

Every issue includes a hidden acceptance test and a clear expected behavior. Repository secrets and external network access are unnecessary.

## Primary metrics

- Scope acceptance accuracy
- Reproduction rate
- Plan approval rate
- Patch application rate
- Focused-test pass rate
- Full-suite pass rate
- Hidden-test pass rate
- Human patch acceptance rate
- Unrelated-change rate
- Unsafe-action block rate
- Median latency and model cost

## Trace labels

Each step is graded for evidence use, correct tool choice, policy compliance, minimality, recovery behavior, and stop/escalate judgment.

## Baselines

Compare the workflow against:

1. One-shot issue-to-patch prompting
2. Planning without reproduction
3. Full PatchPilot workflow

This isolates the value of reproduction, approval, verification, and review.

## No invented metrics

README and resume numbers remain blank until a reproducible benchmark run produces them. Every published metric links to a dataset version, configuration, commit, and result artifact.

