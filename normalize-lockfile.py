"""Normalize only frozen tag's stale local package versions, never resolve dependencies."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import tomllib

EXPECTED_VERSION = "0.162.0-alpha.2"
EXPECTED_COUNT = 161


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def prepare(lock_path, manifest_path):
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest["workspace"]["package"]["version"]
    if version != EXPECTED_VERSION:
        raise ValueError(f"Unexpected workspace version: {version}")
    original = lock_path.read_bytes()
    parsed = tomllib.loads(original.decode("utf-8"))
    local = [p for p in parsed["package"] if "source" not in p and p["version"] == "0.0.0"]
    if len(local) != EXPECTED_COUNT:
        raise ValueError(f"Expected {EXPECTED_COUNT} stale local packages, got {len(local)}")
    names = {p["name"] for p in local}
    if len(names) != EXPECTED_COUNT:
        raise ValueError("Duplicate stale local package names")
    proven = set()
    for cargo_manifest in manifest_path.parent.rglob("Cargo.toml"):
        data = tomllib.loads(cargo_manifest.read_text(encoding="utf-8"))
        package = data.get("package", {})
        if package.get("name") not in names:
            continue
        package_version = package.get("version")
        if package_version == {"workspace": True} or package_version == version:
            proven.add(package["name"])
    if proven != names:
        raise ValueError(f"Missing current manifest evidence: {sorted(names - proven)}")
    text = original.decode("utf-8")
    sections = re.split(r"(?=^\[\[package\]\]\r?$)", text, flags=re.MULTILINE)
    changed_blocks = 0
    for index, section in enumerate(sections):
        if not section.startswith("[[package]]"):
            continue
        block = tomllib.loads(section)["package"][0]
        if block.get("name") in names and block.get("version") == "0.0.0" and "source" not in block:
            section, changed = re.subn(r'(?m)^version = "0\.0\.0"(?=\r?$)',
                                      f'version = "{version}"', section, count=1)
            if changed != 1:
                raise ValueError("Unexpected local package version layout")
            sections[index] = section
            changed_blocks += 1
    candidate_text = "".join(sections)
    for name in sorted(names):
        candidate_text = candidate_text.replace(f'"{name} 0.0.0"', f'"{name} {version}"')
    candidate = candidate_text.encode("utf-8")
    actual = tomllib.loads(candidate.decode("utf-8"))
    expected = copy.deepcopy(parsed)
    for package in expected["package"]:
        if package["name"] in names and package.get("version") == "0.0.0" and "source" not in package:
            package["version"] = version
        for field in ("dependencies", "replace"):
            values = package.get(field)
            if not isinstance(values, list):
                continue
            package[field] = [f"{value[:-6]} {version}" if value.endswith(" 0.0.0") and value[:-6] in names else value
                              for value in values]
    if changed_blocks != EXPECTED_COUNT or actual != expected:
        raise ValueError("Normalization changed more than the allowed local versions/references")
    external_before = [p for p in parsed["package"] if "source" in p]
    external_after = [p for p in actual["package"] if "source" in p]
    # External dependency arrays may refer to local packages; compare identity/checksum separately.
    identity = lambda packages: [(p["name"], p["version"], p["source"], p.get("checksum")) for p in packages]
    if identity(external_before) != identity(external_after):
        raise ValueError("External dependency identities changed")
    return original, candidate, {
        "status": "VALIDATED_NOT_APPLIED",
        "workspace_version": version,
        "local_packages_normalized": changed_blocks,
        "external_packages": len(external_before),
        "external_name_version_source_checksum_unchanged": True,
        "only_local_versions_and_local_references_changed": True,
        "before_sha256": sha256(original),
        "after_sha256": sha256(candidate),
        "dependency_resolution_executed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lockfile", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    original, candidate, report = prepare(args.lockfile, args.manifest)
    if args.apply:
        backup = args.lockfile.with_name(args.lockfile.name + ".before-local-version-normalization")
        if backup.exists() and backup.read_bytes() != original:
            raise ValueError("Conflicting normalization backup; refusing overwrite")
        if not backup.exists():
            backup.write_bytes(original)
        if args.lockfile.read_bytes() != original:
            raise ValueError("Lockfile changed during preparation")
        args.lockfile.write_bytes(candidate)
        if args.lockfile.read_bytes() != candidate:
            raise ValueError("Lockfile verification failed")
        report["status"] = "APPLIED_TO_ISOLATED_SOURCE"
        report["backup"] = backup.name
    output = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
