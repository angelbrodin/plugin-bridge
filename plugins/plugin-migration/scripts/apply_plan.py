#!/usr/bin/env python3
"""Apply a reviewed, hash-bound migration plan without executing repository code.

Dry run is the default. This program validates the complete plan before staging
files, and does not claim that the resulting plugin is runtime-compatible.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import unicodedata


HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PlanError(Exception):
    """An invalid or stale plan; repository changes have not started."""


class ApplyError(Exception):
    """A write failed, with rollback outcome included in the receipt."""

    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__("Application failed; inspect rollback status in the receipt.")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanError("JSON input contains a duplicate key.")
        result[key] = value
    return result


def _read_json(path, label):
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError):
        raise PlanError("Cannot read valid UTF-8 JSON from the {} input.".format(label))
    if not isinstance(value, dict):
        raise PlanError("The {} input must be a JSON object.".format(label))
    return data, value


def _safe_relative(value):
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise PlanError("Every repository path must be a nonempty relative POSIX path.")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or Path(value).is_absolute():
        raise PlanError("Absolute paths and path traversal are not allowed.")
    if any(part.casefold() == ".git" for part in parts):
        raise PlanError("Git metadata cannot be changed.")
    return value


def _path_key(value):
    # Portable plans must not depend on case-sensitive or normalization-sensitive
    # file systems to distinguish two intended changes.
    return unicodedata.normalize("NFC", value).casefold()


def _check_components(path, allow_missing=False):
    """Reject symbolic links, including in existing parent directories."""
    current = Path(path.anchor)
    info = current.lstat()
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                return None
            raise PlanError("Required path does not exist: {}".format(path))
        if stat.S_ISLNK(info.st_mode):
            raise PlanError("Symbolic links are not allowed in file paths: {}".format(current))
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise PlanError("A parent path is not a directory: {}".format(current))
    return info


def _regular_bytes(path):
    info = _check_components(path)
    if not stat.S_ISREG(info.st_mode):
        raise PlanError("Expected a regular file: {}".format(path))
    if info.st_nlink != 1:
        raise PlanError("Hard-linked files are not supported: {}".format(path))
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
        with os.fdopen(descriptor, "rb") as stream:
            actual = os.fstat(stream.fileno())
            if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
                raise PlanError("File changed while being checked: {}".format(path))
            if not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1:
                raise PlanError("File is no longer a regular file with one link: {}".format(path))
            data = stream.read()
            after = os.fstat(stream.fileno())
            if (actual.st_mtime_ns, actual.st_size) != (after.st_mtime_ns, after.st_size):
                raise PlanError("File changed while being read: {}".format(path))
        return data, stat.S_IMODE(info.st_mode)
    except OSError:
        raise PlanError("Cannot safely read file: {}".format(path))


def _validate_report(report, root):
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise PlanError("Unsupported audit schema_version; expected 1.")
    repository = report.get("repository")
    if not isinstance(repository, dict) or repository.get("root") != str(root):
        raise PlanError("The audited repository root does not match the target repository.")
    profile = report.get("profile")
    if not isinstance(profile, dict) or any(
        not isinstance(profile.get(key), str) or not profile[key].strip()
        for key in ("target_version", "install_path")
    ):
        raise PlanError("Audit profile must specify target_version and install_path.")
    entries = report.get("inventory")
    if not isinstance(entries, list):
        raise PlanError("Audit inventory must be a list.")
    inventory = {}
    keys = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PlanError("Audit inventory contains an invalid entry.")
        name = _safe_relative(entry.get("path"))
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not HASH_RE.fullmatch(digest):
            raise PlanError("Audit inventory contains an invalid SHA-256 hash.")
        if _path_key(name) in keys:
            raise PlanError("Audit inventory contains colliding paths.")
        keys.add(_path_key(name))
        inventory[name] = digest
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise PlanError("Audit findings must be a list.")
    identifiers = set()
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get("id"), str):
            raise PlanError("Audit findings must have string identifiers.")
        if finding["id"] in identifiers:
            raise PlanError("Audit finding identifiers must be unique.")
        identifiers.add(finding["id"])
    return inventory, identifiers


def _verify_inventory(root, inventory):
    for name, digest in inventory.items():
        data, unused_mode = _regular_bytes(root / name)
        if sha256(data) != digest:
            raise PlanError("Audited file has changed; run the audit again: {}".format(name))


def _verify_inventory_scope(root, inventory):
    """Use the shipped scanner's exact exclusions and bounds, never repo code."""
    scanner_path = Path(__file__).resolve().with_name("audit_repo.py")
    spec = importlib.util.spec_from_file_location("plugin_migration_inventory", scanner_path)
    scanner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = scanner
    try:
        spec.loader.exec_module(scanner)
        current = {entry["path"]: entry["sha256"] for entry in scanner.build_inventory(root)}
    except (OSError, ValueError, RuntimeError):
        raise PlanError("Cannot verify current audit coverage; rerun the audit with this plugin version.")
    if current != inventory:
        raise PlanError("Repository files or audit coverage changed; run the audit again.")


def _render_edits(original, edits, name):
    if not isinstance(edits, list) or not edits:
        raise PlanError("Existing-file changes require a nonempty edits list: {}".format(name))
    try:
        text = original.decode("utf-8")
    except UnicodeError:
        raise PlanError("Planned file is not UTF-8 text: {}".format(name))
    spans = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"old", "new"}:
            raise PlanError("Each edit must contain only old and new text.")
        old, new = edit["old"], edit["new"]
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise PlanError("Edit old text must be nonempty and new text must be a string.")
        start = text.find(old)
        if start < 0 or text.find(old, start + 1) >= 0:
            raise PlanError("Edit must match exactly once in the original file: {}".format(name))
        spans.append((start, start + len(old), new))
    spans.sort(key=lambda span: span[0])
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise PlanError("Edits overlap in the original file: {}".format(name))
    for start, end, new in reversed(spans):
        text = text[:start] + new + text[end:]
    return text.encode("utf-8")


def _preflight_changes(root, plan, inventory, identifiers, protected):
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        raise PlanError("Plan changes must be a nonempty list.")
    prepared = []
    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise PlanError("Each planned change must be an object.")
        name = _safe_relative(change.get("path"))
        key = _path_key(name)
        if key in seen:
            raise PlanError("A plan cannot contain duplicate or colliding paths.")
        seen.add(key)
        path = root / name
        if str(path.resolve(strict=False)) in protected:
            raise PlanError("Audit, plan, and receipt files cannot be migration targets.")
        selected = change.get("finding_ids")
        if not isinstance(selected, list) or not selected or any(
            not isinstance(item, str) or item not in identifiers for item in selected
        ) or len(set(selected)) != len(selected):
            raise PlanError("Each change must reference known, unique audit finding IDs.")
        if not isinstance(change.get("rationale"), str) or not change["rationale"].strip():
            raise PlanError("Each change must include a nonempty rationale.")
        if "expected_sha256" not in change:
            raise PlanError("Each change must specify expected_sha256.")
        expected = change["expected_sha256"]
        if expected is None:
            if "edits" in change or not isinstance(change.get("content"), str):
                raise PlanError("New files require content and cannot specify edits.")
            _check_components(path, allow_missing=True)
            if path.exists() or path.is_symlink() or name in inventory:
                raise PlanError("New-file target already exists: {}".format(name))
            original, mode = None, 0o644
            result = change["content"].encode("utf-8")
        else:
            if not isinstance(expected, str) or not HASH_RE.fullmatch(expected):
                raise PlanError("Existing-file changes require a valid expected_sha256.")
            if inventory.get(name) != expected:
                raise PlanError("Planned file/hash is not in the audited inventory: {}".format(name))
            if "content" in change or "edits" not in change:
                raise PlanError("Existing files require edits and cannot specify content.")
            original, mode = _regular_bytes(path)
            if sha256(original) != expected:
                raise PlanError("Planned file has changed; run the audit again: {}".format(name))
            result = _render_edits(original, change["edits"], name)
        prepared.append({"path": path, "relative_path": name, "original": original,
                         "result": result, "mode": mode, "finding_ids": selected})
    # A planned new directory cannot simultaneously be another planned file.
    for item in prepared:
        parts = item["relative_path"].split("/")
        if any(_path_key("/".join(parts[:count])) in seen for count in range(1, len(parts))):
            raise PlanError("A planned file conflicts with another file's parent directory.")
    return prepared


def _summary(prepared, status, root, profile, audit_digest, plan_digest):
    return {
        "schema_version": 1, "status": status, "repository_root": str(root),
        "profile": {key: profile[key] for key in
                    ("target_version", "install_path", "preserve_claude", "rules_verified_version")
                    if key in profile},
        "audit_sha256": audit_digest, "plan_sha256": plan_digest,
        "runtime_validation": "not_run",
        "changes": [{"path": item["relative_path"],
                     "before_sha256": sha256(item["original"]) if item["original"] is not None else None,
                     "after_sha256": sha256(item["result"]),
                     "finding_ids": item["finding_ids"]} for item in prepared],
    }


def _make_parents(parent, root, created):
    missing = []
    cursor = parent
    while cursor != root and not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    _check_components(cursor)
    for directory in reversed(missing):
        _check_components(directory, allow_missing=True)
        directory.mkdir()
        created.append(directory)


def _stage(path, content, mode):
    _check_components(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=".migration-", dir=str(path.parent))
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(str(staged), mode)
        return staged
    except BaseException:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _verify_target(item):
    path = item["path"]
    _check_components(path, allow_missing=item["original"] is None)
    if item["original"] is None:
        if path.exists() or path.is_symlink():
            raise PlanError("New-file target appeared during application: {}".format(item["relative_path"]))
    else:
        current, mode = _regular_bytes(path)
        if current != item["original"] or mode != item["mode"]:
            raise PlanError("Target changed during application: {}".format(item["relative_path"]))


def _write_changes(root, inventory, prepared, receipt):
    staged = []
    committed = []
    created_dirs = []
    try:
        for item in prepared:
            _make_parents(item["path"].parent, root, created_dirs)
            _verify_target(item)
            staged.append(_stage(item["path"], item["result"], item["mode"]))
        _verify_inventory(root, inventory)
        for item, temporary in zip(prepared, staged):
            _verify_target(item)
            os.replace(str(temporary), str(item["path"]))
            committed.append(item)
    except BaseException as error:
        failures = []
        for item in reversed(committed):
            rollback_temp = None
            try:
                current, unused_mode = _regular_bytes(item["path"])
                if current != item["result"]:
                    raise PlanError("Concurrent edit prevents safe rollback.")
                if item["original"] is None:
                    item["path"].unlink()
                else:
                    rollback_temp = _stage(item["path"], item["original"], item["mode"])
                    os.replace(str(rollback_temp), str(item["path"]))
            except BaseException:
                failures.append(item["relative_path"])
            finally:
                if rollback_temp is not None:
                    try:
                        rollback_temp.unlink(missing_ok=True)
                    except OSError:
                        receipt.setdefault("staging_cleanup_failed_paths", []).append(str(rollback_temp))
        receipt["status"] = "apply_failed_rollback_incomplete" if failures else "apply_failed_rolled_back"
        receipt["rollback_failed_paths"] = failures
        receipt["error_type"] = type(error).__name__
        receipt["next_action"] = (
            "Inspect rollback_failed_paths and restore them from your reviewed baseline before retrying."
            if failures else "Repository file edits were rolled back. Resolve the write failure, rerun the audit, and retry."
        )
        raise ApplyError(receipt)
    finally:
        for temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                receipt.setdefault("staging_cleanup_failed_paths", []).append(str(temporary))
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass


def _receipt_destination(value, root, input_paths):
    if value is None:
        return None
    path = Path(os.path.abspath(str(value)))
    _check_components(path, allow_missing=True)
    if not path.parent.is_dir():
        raise PlanError("Receipt parent directory must already exist.")
    if path.exists() or path.is_symlink():
        raise PlanError("Receipt output already exists; choose a new output path.")
    if root == path or root in path.parents:
        raise PlanError("Write receipts outside the repository to keep source changes limited to the plan.")
    if str(path.resolve(strict=False)) in input_paths:
        raise PlanError("Receipt output must not overwrite the audit or plan input.")
    return path


def _save_receipt(path, receipt):
    if path is None:
        return
    _check_components(path, allow_missing=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def apply_migration(repo, audit_path, plan_path, write=False, receipt_path=None):
    root = Path(os.path.abspath(str(repo)))
    info = _check_components(root)
    if not stat.S_ISDIR(info.st_mode):
        raise PlanError("Repository target must be a directory.")
    root = root.resolve()
    audit_path, plan_path = Path(audit_path), Path(plan_path)
    audit_bytes, report = _read_json(audit_path, "audit")
    plan_bytes, plan = _read_json(plan_path, "plan")
    audit_digest = sha256(audit_bytes)
    if type(plan.get("schema_version")) is not int or plan["schema_version"] != 1 or plan.get("audit_sha256") != audit_digest:
        raise PlanError("Plan must use schema_version 1 and the exact audit file's SHA-256 hash.")
    inventory, identifiers = _validate_report(report, root)
    protected = {str(audit_path.resolve()), str(plan_path.resolve())}
    receipt_path = _receipt_destination(receipt_path, root, protected)
    if receipt_path is not None:
        protected.add(str(receipt_path.resolve(strict=False)))
    _verify_inventory(root, inventory)
    _verify_inventory_scope(root, inventory)
    prepared = _preflight_changes(root, plan, inventory, identifiers, protected)
    receipt = _summary(prepared, "applied_pending_validation" if write else "dry_run_ready",
                       root, report["profile"], audit_digest, sha256(plan_bytes))
    if write:
        # Bind the operation to the exact plan/report read during preflight.
        if audit_path.read_bytes() != audit_bytes or plan_path.read_bytes() != plan_bytes:
            raise PlanError("Audit or plan input changed during preflight; retry with stable inputs.")
        try:
            _write_changes(root, inventory, prepared, receipt)
        except ApplyError as error:
            try:
                _save_receipt(receipt_path, error.receipt)
            except (OSError, PlanError):
                error.receipt["receipt_write_failed"] = True
            raise
    try:
        _save_receipt(receipt_path, receipt)
    except (OSError, PlanError):
        receipt["receipt_write_failed"] = True
        receipt["next_action"] = "Save the JSON printed by this command as the receipt."
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="Repository root recorded in the audit")
    parser.add_argument("--audit", required=True, help="Audit JSON, unchanged since plan preparation")
    parser.add_argument("--plan", required=True, help="Reviewed plan JSON")
    parser.add_argument("--write", action="store_true", help="Apply the selected changes; otherwise dry run")
    parser.add_argument("--receipt", help="New receipt path outside the repository")
    args = parser.parse_args(argv)
    try:
        receipt = apply_migration(args.repo, args.audit, args.plan, args.write, args.receipt)
    except PlanError as error:
        print(json.dumps({"status": "refused", "error": str(error)}), file=sys.stderr)
        return 2
    except ApplyError as error:
        print(json.dumps(error.receipt, indent=2), file=sys.stderr)
        return 3
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__,
                          "next_action": "Inspect file access and rerun the audit before retrying."}), file=sys.stderr)
        return 3
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
    return 0 if not receipt.get("receipt_write_failed") else 4


if __name__ == "__main__":
    sys.exit(main())
