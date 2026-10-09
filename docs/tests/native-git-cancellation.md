# Native Git cancellation smoke — limited baseline

This is a **small prerequisite**, not an integration test or a fix for WinWork.

- Manual Windows GitHub-hosted runner only, 10-minute job ceiling; synthetic repository, 48 Git commands (mix of immediate cancellation and normal completion), maximum eight simultaneous invocations.
- Records whether each *directly spawned* Git child was reaped. No Remote hydration, app-server invocation, review-summary, diff snapshots, parent/descendant-tree analysis, handle time series, kernel pool or system commit measurement.
- Explicitly **does not exercise the experimental Codex executable** from successful [build run 37966319715](https://github.com/komete4/codex-bounded-git-windows-build/actions/runs/37966319715) and cannot validate or invalidate its patch.
- Manual `workflow_dispatch` only; the workflow is not triggered on this PR. No access to WinWork, no private repositories, no secrets or installation.
- A green result establishes only that the harness and native subprocess cancellation baseline work on the hosted runner. A later candidate-linked regression must exercise the actual Codex call site, including cancellation and exit of native descendants.
- Do not infer causal relationship between Android Remote sessions and Windows Git fan-out from this harness.

**Next technical gate:** design a bounded synthetic app-server/review invocation using the pinned candidate and instrument spawn/cancel/exit. Hold installation until that gate passes and an explicit host trial is approved.
