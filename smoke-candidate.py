#!/usr/bin/env python3
"""Finite Windows-only CLI/schema smoke; never starts a Codex session.

Use on a disposable Windows build runner, not against the installed desktop client.
Only Python's standard library is required. See smoke-scope.txt for limits.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time


MAX_SCHEMA_FILES = 2000
MAX_SCHEMA_FILE_BYTES = 8 * 1024 * 1024
MAX_SCHEMA_TREE_BYTES = 64 * 1024 * 1024
MAX_RECORDED_OUTPUT_BYTES = 16 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_pe(path: Path) -> dict:
    """Check DOS/PE signatures, AMD64 machine and PE32+ optional header."""
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("Not a DOS/PE executable")
        pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
        if pe_offset < 64 or pe_offset > 16 * 1024 * 1024 or pe_offset + 26 > size:
            raise ValueError("PE header offset is invalid or exceeds the inspection bound")
        handle.seek(pe_offset)
        pe = handle.read(26)
        if pe[:4] != b"PE\0\0":
            raise ValueError("Missing PE signature")
        machine, sections = struct.unpack_from("<HH", pe, 4)
        optional_size, characteristics = struct.unpack_from("<HH", pe, 20)
        optional_magic = struct.unpack_from("<H", pe, 24)[0]
        if machine != 0x8664 or optional_magic != 0x20B:
            raise ValueError("Executable is not AMD64 PE32+")
        if not sections or optional_size < 112 or not characteristics & 0x0002:
            raise ValueError("PE headers do not describe an executable image")
        if characteristics & 0x2000:
            raise ValueError("PE image is a DLL, not an executable")
    return {
        "status": "PASS",
        "machine": "AMD64",
        "machine_hex": "0x8664",
        "optional_header": "PE32+",
        "sections": sections,
        "size_bytes": size,
    }


def isolated_environment(root: Path) -> dict[str, str]:
    """Do not inherit credentials, CODEX_HOME, proxy settings or a user profile."""
    env = {}
    for name in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
                 "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER"):
        if name in os.environ:
            env[name] = os.environ[name]
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    env["PATH"] = str(Path(system_root) / "System32")
    for name in ("TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA",
                 "CODEX_HOME"):
        folder = root / name.lower()
        folder.mkdir()
        env[name] = str(folder)
    env["DO_NOT_TRACK"] = "1"
    return env


def read_recorded_output(path: Path) -> dict:
    size = path.stat().st_size
    with path.open("rb") as handle:
        data = handle.read(MAX_RECORDED_OUTPUT_BYTES)
    return {
        "text": data.decode("utf-8", errors="replace"),
        "size_bytes": size,
        "recorded_bytes": len(data),
        "truncated_in_report": size > len(data),
    }


def run_command(binary: Path, arguments: list[str], work: Path,
                env: dict[str, str], timeout: int, label: str) -> dict:
    stdout_path = work / (label + ".stdout")
    stderr_path = work / (label + ".stderr")
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            [str(binary), *arguments], stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, cwd=work, env=env,
            shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Terminate only this exact process via Popen's held process handle.
            # No process-name lookup, taskkill, daemon stop or existing-process action.
            process.kill()
            process.wait(timeout=10)
    return {
        "label": label,
        "arguments": arguments,
        "status": "PASS" if process.returncode == 0 and not timed_out else "FAILED",
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": read_recorded_output(stdout_path),
        "stderr": read_recorded_output(stderr_path),
    }


def schema_tree(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Schema root must be an existing non-symlink directory")
    files = {}
    total = 0
    # This traverses only the caller-selected schema subtree or our own output.
    for directory, child_dirs, child_files in os.walk(root, followlinks=False):
        base = Path(directory)
        if any((base / name).is_symlink() for name in child_dirs + child_files):
            raise ValueError("Schema tree contains symlinks")
        for name in sorted(child_files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if not name.endswith(".json"):
                raise ValueError("Unexpected non-JSON schema file: " + relative)
            size = path.stat().st_size
            total += size
            if (len(files) >= MAX_SCHEMA_FILES or size > MAX_SCHEMA_FILE_BYTES
                    or total > MAX_SCHEMA_TREE_BYTES):
                raise ValueError("Schema tree exceeds the inspection bounds")
            data = path.read_bytes()
            json.loads(data.decode("utf-8"))
            files[relative] = data
    if not files or "codex_app_server_protocol.schemas.json" not in files:
        raise ValueError("Stable schema tree is empty or missing its protocol bundle")
    return files


def tree_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def reference_schema(source: Path) -> tuple[dict[str, bytes], dict]:
    cli = source / "codex-rs/cli/src/main.rs"
    fixtures = source / "codex-rs/app-server-protocol/src/schema_fixtures_tests.rs"
    for path in (cli, fixtures):
        if not path.is_file() or path.is_symlink():
            raise ValueError("Source reference sentinel is missing or is a symlink")
    cli_text = cli.read_text(encoding="utf-8")
    fixture_text = fixtures.read_text(encoding="utf-8")
    if ("struct GenerateJsonSchemaCommand" not in cli_text
            or 'long = "out"' not in cli_text
            or "gen_cli.experimental" not in cli_text
            or "fn json_schema_fixtures_match_generated" not in fixture_text
            or "/*experimental_api*/ false" not in fixture_text):
        raise ValueError("Source does not establish this stable-schema CLI/reference contract")
    root = source / "codex-rs/app-server-protocol/schema/json"
    files = schema_tree(root)
    return files, {
        "status": "VALID_REFERENCE",
        "path": str(root),
        "mode": "stable; no --experimental flag",
        "file_count": len(files),
        "total_bytes": sum(map(len, files.values())),
        "tree_sha256": tree_digest(files),
        "sentinel_sha256": {
            str(cli.relative_to(source)): sha256_file(cli),
            str(fixtures.relative_to(source)): sha256_file(fixtures),
        },
        "provenance": "Caller must independently establish source/tag/patch provenance",
    }


def compare_schemas(expected: dict[str, bytes], actual: dict[str, bytes]) -> dict:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    shared = set(expected) & set(actual)
    byte_mismatch = sorted(name for name in shared if expected[name] != actual[name])
    json_mismatch = sorted(
        name for name in shared
        if json.loads(expected[name]) != json.loads(actual[name])
    )
    return {
        "status": "PASS" if not missing and not extra and not byte_mismatch else "FAILED",
        "expected_files": len(expected),
        "generated_files": len(actual),
        "generated_bytes": sum(map(len, actual.values())),
        "expected_tree_sha256": tree_digest(expected),
        "generated_tree_sha256": tree_digest(actual),
        "file_sets_equal": not missing and not extra,
        "bytes_equal": not missing and not extra and not byte_mismatch,
        "json_values_equal": not missing and not extra and not json_mismatch,
        "missing": missing,
        "extra": extra,
        "byte_mismatches": byte_mismatch,
        "json_mismatches": json_mismatch,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-version", default="codex-cli 0.162.0-alpha.2")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.timeout_seconds <= 120:
        parser.error("--timeout-seconds must be between 1 and 120")
    binary = args.binary.resolve()
    source = args.source.resolve()
    report_path = args.report.absolute()
    if report_path.exists():
        parser.error("Refusing to overwrite an existing report; choose a fresh report path")
    report = {
        "format_version": 1,
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "INCOMPLETE",
        "binary": str(binary),
        "source": str(source),
        "expected_version": args.expected_version,
        "commands": [],
        "limits": [
            "Finite CLI and stable-schema smoke only; memory stability is not tested",
            "No authentication, model calls, session resume/start, remote control or agent task execution",
            "No review/snapshot load, Git fanout, cancellation, process-tree or memory-retention test",
            "Source-to-binary provenance and Authenticode signature are not independently verified",
            "Timeout kills only the exact command process; descendant cleanup is not tested",
            "Not a desktop installation/override compatibility test; no installed client is modified",
        ],
    }
    exit_code = 2
    try:
        if sys.platform != "win32":
            raise RuntimeError("This smoke must run on a disposable Windows runner")
        if not binary.is_file() or args.binary.is_symlink():
            raise ValueError("Candidate binary is missing or is a symlink")
        report["binary_sha256_before"] = sha256_file(binary)
        report["pe"] = inspect_pe(binary)
        expected = None
        try:
            expected, report["schema_reference"] = reference_schema(source)
        except (OSError, ValueError, UnicodeError) as error:
            report["schema_reference"] = {"status": "UNAVAILABLE", "reason": str(error)}
        with tempfile.TemporaryDirectory(prefix="codex-candidate-smoke-") as temporary:
            work = Path(temporary)
            env = isolated_environment(work)
            sequence = [
                ("version", ["--version"]),
                ("app_server_help", ["app-server", "--help"]),
                ("stable_json_schema", ["app-server", "generate-json-schema", "--out",
                                        str(work / "generated-schema")]),
            ]
            for label, arguments in sequence:
                result = run_command(binary, arguments, work, env, args.timeout_seconds, label)
                report["commands"].append(result)
                if result["status"] != "PASS":
                    raise RuntimeError("Command failed: " + label)
                if label == "version":
                    actual_version = result["stdout"]["text"].strip()
                    report["version_matches"] = actual_version == args.expected_version
                    if not report["version_matches"]:
                        raise RuntimeError("Candidate version differs from --expected-version")
                if label == "app_server_help":
                    help_text = result["stdout"]["text"] + result["stderr"]["text"]
                    if "generate-json-schema" not in help_text:
                        raise RuntimeError("App-server help lacks generate-json-schema")
            actual = schema_tree(work / "generated-schema")
            if expected is not None:
                report["schema_comparison"] = compare_schemas(expected, actual)
            else:
                report["schema_comparison"] = {
                    "status": "NOT_COMPARED", "generated_files": len(actual),
                    "generated_tree_sha256": tree_digest(actual),
                }
        report["binary_sha256_after"] = sha256_file(binary)
        if report["binary_sha256_before"] != report["binary_sha256_after"]:
            raise RuntimeError("Candidate binary changed during smoke")
        if report["schema_comparison"]["status"] == "FAILED":
            raise RuntimeError("Generated stable schemas differ from source reference")
        if expected is not None:
            report["status"] = "PASS"
            exit_code = 0
        else:
            report["reason"] = "CLI smoke passed, but no valid stable-schema reference was available"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        exit_code = 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": report["status"], "report": str(report_path)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
