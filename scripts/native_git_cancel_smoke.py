#!/usr/bin/env python3
"""Bounded Windows Git subprocess cancellation smoke. NOT a Codex regression test."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, timeout=10, check=True,
                          capture_output=True, text=True)

def run_one(repo, cancel):
    p = subprocess.Popen(["git", "-C", str(repo), "status", "--porcelain"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pid = p.pid
    if cancel and p.poll() is None:
        p.terminate()
    try:
        out, err = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate(timeout=5)
        raise AssertionError(f"Git subprocess {pid} exceeded 10s")
    if p.poll() is None:
        raise AssertionError(f"Git subprocess {pid} did not exit")
    if not cancel and p.returncode != 0:
        raise AssertionError(f"Git status failed (pid={pid}, code={p.returncode}): {err[:300]!r}")
    return {"pid": pid, "exit_code": p.returncode, "cancel_requested": cancel,
            "stdout_bytes": len(out), "stderr_bytes": len(err)}

def main():
    if os.name != "nt":
        raise SystemExit("Windows runner only")
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="codex-git-smoke-") as d:
        root = Path(d)
        git("init", "--quiet", cwd=root)
        (root / "sample.txt").write_text("synthetic only\n", encoding="utf-8")
        git("add", "--", "sample.txt", cwd=root)
        reports = []
        for workers in (1, 4, 8):
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                jobs = [pool.submit(run_one, root, i % 2 == 0) for i in range(16)]
                reports += [j.result(timeout=20) for j in jobs]
        pids = [r["pid"] for r in reports]
        assert len(pids) == len(set(pids)), "reused PID within rapid synthetic test; cannot validate PID identity alone"
        result = {"status": "PASS", "scope": "native Git subprocess smoke only; no Codex/app-server/Remote",
                  "operating_system": os.name, "operations": len(reports),
                  "worker_bounds": [1, 4, 8], "all_spawned_children_reaped": True,
                  "elapsed_seconds": round(time.monotonic() - start, 3)}
        Path(os.environ.get("GITHUB_WORKSPACE", "."), "native-git-cancel-receipt.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))

if __name__ == "__main__":
    main()
