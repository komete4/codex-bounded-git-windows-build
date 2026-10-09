# WinWork — 2026-10-08/09 Remote/Codex resource exhaustion

**Status:** RECURRENCE OBSERVED; root cause unproven. **Evidence scope:** sanitized, second-hand GitHub auditor receipts and user testimony; this repository does not contain raw Windows traces or privileged access.

## Observation (Europe/Madrid)

- Requested monitoring cutoff: 2026-10-09 07:00; collection did **not** run until that time.
- Auditor-reported collector window: 2026-10-08 20:15:35–23:41:55; approximately 207 one-minute samples, no reported sample gaps *within* this collection window; later hours unobserved.
- Stop reason reported: `DANGEROUS_PRESSURE`. Do not describe the full night as stable.
- End-of-window auditor-reported aggregates: 4,766 `git.exe` processes, 2,820 `conhost.exe` processes, 159,677 counted handles, ~13.83 GiB paged pool (initial ~1.49 GiB), Windows system commit ~53.23/57.90 GiB (~91.94%), ~27 MiB available RAM.
- The auditor reported approximately 3,012 Git descendants of `app-server`. This **does not** identify an individual chat, session, Git invocation, or responsible allocation.
- Historical comparison: Oct 6–7 commit exhaustion around 62.34 GiB and handles/kernel-pool pressure; Oct 8 post-restart 15-minute snapshot (~31.22 GiB RAM, 38.72 GiB commit limit) was **not** a representative stability test.
- Pagefile breakdown, per-PID handle-growth time series, exact workload classification and complete Windows event-2004 coverage **not independently established here**.

These are reported metrics, not measurements this repository or its workflow obtained. Preserve provenance and confirm source receipts when preparing any public engineering submission.

## User-observed behavior

- Android ChatGPT Remote/Codex: some older/large Remote conversations remained loading or incomplete.
- Fresh chats created in the **same Android app and connection** worked.
- Remote was used during the incident evening, reportedly less extensively/cautiously than on previous nights; it was **not** absent.
- Switching models in a long conversation is a **candidate variable only**, with no demonstrated temporal correlation or causal evidence.

A fresh cloud-hosted chat working does not demonstrate that its execution path shares a local Windows app-server, and does not rule out a locally exhausted host for paired Remote sessions.

## Related public issue

- [openai/codex#41982](https://github.com/openai/codex/issues/41982) reports Android Remote chat hydration correlated with automatic Git review/snapshot activity and Windows virtual-memory exhaustion. Compare mechanisms, **do not assume identical root cause**.
- The upstream public discussion linked from this repo's [README](../README.md) describes the bounded-untracked-diff patch context.

## What this patch actually does

- Limits concurrent **untracked-file diff futures** to eight *within one app-server process* by using a shared semaphore.
- Does **not** bound all Git calls, review-summary/snapshot refreshes, remote workers, or multiple app-server processes.
- Tests use simulated futures; they do **not** prove native Windows child-process cleanup or memory stability.
- Builds a `codex.exe` CLI/app-server candidate, **not** the signed desktop application. Never represent successful CI, if any, as an installed or validated WinWork fix.

## Targeted correction and acceptance gates

1. **Identify the actual source path**: instrument synthetic, isolated app-server Remote refresh, review-summary and snapshot/cancellation paths with operation ID, parent/child PID, spawn/exit time, active/max child counts, retries and cancellation results. Do not collect private chats, repository contents or raw secrets.
2. **Red test first**: deterministically exercise overlapping refreshes/cancellation against a synthetic Git repository and confirm whether descendants/handles remain after cancellation and timeouts. An absent repro is **INCONCLUSIVE**, not fixed.
3. **Smallest scoped patch**: ensure process-tree cleanup and bounded/coalesced refresh/review work as supported by the measured source path. No global behavior changes justified by unproven hypotheses.
4. **Green test**: verify children exit and counts return to baseline, bounded concurrency across overlapping requests, preserved legitimate diff/review results and cancellation correctness. Document test platform and limitations.
5. **Compatibility gate**: exact upstream commit, patch checksum, signed/unsigned distinctions, schema checks, reproducible build, and explicit compatibility assessment. No default automatic publication or installation.
6. **Separate host trial**: only with explicit authorization and safe rollback on a recovered system. Compare activity-matched windows and RAM/commit/available margin/paged pool/handles/PIDs; stop under dangerous pressure. Do not intentionally repeat host-wide OOM.

**Current decision:** No claim of fix, no scale-up justification for workers, and no change to Maia #758 or its running factory work. Resource capacity and token quota are separate from local stability.

**Source pointers:** [Maia #758](https://github.com/komete4/Maia/issues/758) (auditor receipts, operational coordination); [Codex #41982](https://github.com/openai/codex/issues/41982). Public summary intentionally omits raw telemetry and private host paths.
