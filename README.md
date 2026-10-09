# Codex Windows build: bounded untracked-file diffs

Experimental build recipe for the public `openai/codex` source with a community patch that bounds concurrent untracked-file diff operations. This repository is an independent reproduction kit, not an official OpenAI release or a demonstration that a particular stability problem is resolved.

## Pinned inputs

| Input | Value |
| --- | --- |
| Upstream repository | https://github.com/openai/codex |
| Upstream tag | `rust-v0.162.0-alpha.2` |
| Upstream commit | `74e804deeb1241d5fe699b31fb319f7d46454c42` |
| Patch SHA-256 | `5ecb0a71aa3ce2fb0d2259661d1c804198d9ffebf80d2317812ce332666f377d` |
| Rust toolchain | `1.95.0` |
| Target | `x86_64-pc-windows-msvc` |
| Runner | GitHub-hosted `windows-2022` |

Patch context: [upstream issue #41982](https://github.com/openai/codex/issues/41982) and [community patch discussion](https://github.com/openai/codex/issues/41982#issuecomment-6043672693). Those references describe the public hypothesis; they do not establish the outcome of this build recipe.

## Patch scope

The patch replaces an unbounded collection of untracked-file diff futures with ordered buffering and a shared semaphore of eight. The semaphore covers that code path within one process, including overlapping requests. It is not a global limit on Git processes, app-server instances, remote workers, or other Git operations. Accumulated diff output can still grow with the input.

Three added tests check the request future's `Send` property, shared concurrency and ordered results using simulated futures, and permit release on cancellation. They do not verify termination of native Git process trees on Windows.

## Reproduce

1. Open **Actions**, select **Build reviewed Codex Windows candidate**, and choose **Run workflow**.
2. Inspect the workflow conclusion, `build-receipt.json`, test/build logs, and `smoke-candidate.json` in the uploaded artifact.
3. Check `manifest.sha256` before evaluating the candidate executable.

The workflow runs only on manual dispatch, with a 120-minute job limit, two Cargo build jobs, read-only repository permissions, and actions pinned to commits. It checks out the exact upstream commit, verifies patch and V8 hashes, normalizes the frozen lockfile, runs `codex-git-utils` library tests, and builds `codex.exe` with `--locked`. Lockfile normalization changes only stale internal package versions and references; external dependency identities and checksums must remain unchanged.

No custom secrets are required. `build-windows.ps1` accepts only the GitHub-hosted Windows runner environment. The workflow uploads a candidate and evidence; it does not publish releases or install the executable. An uploaded artifact can contain a failed build: check the receipt status rather than assuming artifact existence means success.

## Validation and limits

The finite smoke checks AMD64 PE headers, executable hashes, version output, `app-server --help`, and generated stable schemas against the pinned source fixtures byte for byte. Experimental schemas are also generated, but are not compared with an installed desktop client's output. See [smoke-scope.txt](smoke-scope.txt) for the precise checks and exit codes.

Successful compilation and smoke results do not establish memory stability, cancellation cleanup of native descendants, behavior under review/snapshot load, Remote session resource retention, or desktop replacement compatibility. This recipe builds the CLI executable containing `app-server`, not the complete desktop application. The resulting binary does not carry OpenAI's official Authenticode signature.

This repository contains the build recipe, patch, and upstream license notices. It includes no private workload data or machine-specific incident logs. Any future bug report should separate observed measurements, reproduction steps, hypotheses, and validation limits, using synthetic or explicitly publishable inputs.

## Licensing

Upstream licensing and attribution are preserved in [LICENSE.upstream](LICENSE.upstream) and [NOTICE.upstream](NOTICE.upstream).

## WinWork incident evidence

The [8–9 October 2026 Remote/Codex incident note](docs/incidents/2026-10-08-winwork-remote.md) preserves sanitized auditor-reported resource pressure, Android Remote observations and a narrowly scoped correction/acceptance plan. It is **not** proof that this patch fixes the incident. No host deployment is authorized by this documentation.
