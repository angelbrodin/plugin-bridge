import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_plan.py"
SPEC = importlib.util.spec_from_file_location("migration_apply_under_test", SCRIPT)
apply_plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apply_plan)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ApplyPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.skill = self.repo / "skills" / "github" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.original = (
            "# Shared workflow\n"
            "For Claude: use select:mcp__example-github__search_pull_requests.\n"
            "For Codex: use the old discovery instruction.\n"
            "Keep the rest of the workflow.\n"
        ).encode("utf-8")
        self.skill.write_bytes(self.original)
        os.chmod(self.skill, 0o754)
        self.other = self.repo / "README.md"
        self.other.write_bytes(b"Unrelated documentation.\n")
        self.audit_path = self.base / "audit.json"
        self.plan_path = self.base / "plan.json"
        self.audit = {
            "schema_version": 1,
            "repository": {"root": str(self.repo), "revision": "test-revision"},
            "profile": {"target_version": "0.154.0-alpha.1", "install_path": "standalone-import",
                        "preserve_claude": True, "rules_verified_version": "0.154.0-alpha.1"},
            "inventory": [
                {"path": path.relative_to(self.repo).as_posix(), "sha256": digest(path.read_bytes()),
                 "size": len(path.read_bytes())} for path in (self.skill, self.other)
            ],
            "findings": [{"id": "DISCOVERY-1", "path": "skills/github/SKILL.md"}],
        }
        self.plan = {
            "schema_version": 1, "audit_sha256": "",
            "changes": [{"path": "skills/github/SKILL.md", "expected_sha256": digest(self.original),
                         "edits": [{"old": "For Codex: use the old discovery instruction.",
                                    "new": "For Codex: use tool_search with its advertised schema."}],
                         "finding_ids": ["DISCOVERY-1"],
                         "rationale": "Change only the Codex tool-discovery branch."}],
        }
        self.save()

    def save(self):
        self.audit_path.write_text(json.dumps(self.audit, indent=2), encoding="utf-8")
        self.plan["audit_sha256"] = digest(self.audit_path.read_bytes())
        self.plan_path.write_text(json.dumps(self.plan, indent=2), encoding="utf-8")

    def run_plan(self, write=False, receipt=None):
        return apply_plan.apply_migration(self.repo, self.audit_path, self.plan_path,
                                         write=write, receipt_path=receipt)

    def assert_refused_without_change(self):
        before = self.skill.read_bytes()
        with self.assertRaises(apply_plan.PlanError):
            self.run_plan(write=True)
        self.assertEqual(self.skill.read_bytes(), before)

    def test_dry_run_does_not_mutate_repository_and_hides_content(self):
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}
        result = self.run_plan()
        after = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "dry_run_ready")
        self.assertEqual(result["profile"], self.audit["profile"])
        self.assertNotIn("old discovery", json.dumps(result))
        self.assertNotIn("rationale", json.dumps(result))

    def test_inventory_check_does_not_run_repository_code_or_subprocesses(self):
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("No subprocess is permitted")):
            result = self.run_plan(write=True)
        self.assertEqual(result["status"], "applied_pending_validation")

    def test_apply_changes_only_selected_branch_and_preserves_mode_and_newline(self):
        result = self.run_plan(write=True)
        text = self.skill.read_text(encoding="utf-8")
        self.assertIn("For Claude: use select:mcp__example-github__search_pull_requests.\n", text)
        self.assertIn("For Codex: use tool_search with its advertised schema.\n", text)
        self.assertTrue(text.endswith("Keep the rest of the workflow.\n"))
        self.assertEqual(stat.S_IMODE(self.skill.stat().st_mode), 0o754)
        self.assertEqual(self.other.read_bytes(), b"Unrelated documentation.\n")
        self.assertEqual(result["status"], "applied_pending_validation")
        self.assertEqual(result["runtime_validation"], "not_run")

    def test_crlf_and_absence_of_final_newline_are_preserved(self):
        data = b"line one\r\nreplace this\r\nlast line"
        self.skill.write_bytes(data)
        self.audit["inventory"][0]["sha256"] = digest(data)
        self.audit["inventory"][0]["size"] = len(data)
        self.plan["changes"][0]["expected_sha256"] = digest(data)
        self.plan["changes"][0]["edits"] = [{"old": "replace this", "new": "replaced"}]
        self.save()
        self.run_plan(write=True)
        self.assertEqual(self.skill.read_bytes(), b"line one\r\nreplaced\r\nlast line")

    def test_stale_unedited_inventory_file_blocks_apply(self):
        self.other.write_bytes(b"Changed since audit.\n")
        self.assert_refused_without_change()

    def test_new_file_in_audited_scope_blocks_apply(self):
        (self.repo / "new-instructions.md").write_text("New repository instruction.")
        self.assert_refused_without_change()

    def test_deleted_inventory_file_blocks_apply(self):
        self.other.unlink()
        self.assert_refused_without_change()

    def test_stale_planned_file_blocks_apply(self):
        self.skill.write_bytes(self.original + b"New user edit.\n")
        self.assert_refused_without_change()

    def test_changed_audit_bytes_invalidate_plan(self):
        self.audit_path.write_bytes(self.audit_path.read_bytes() + b"\n")
        self.assert_refused_without_change()

    def test_invalid_later_change_prevents_partial_write(self):
        self.plan["changes"].append({"path": "README.md", "expected_sha256": digest(self.other.read_bytes()),
                                     "edits": [{"old": "Missing text", "new": "Correction"}],
                                     "finding_ids": ["DISCOVERY-1"], "rationale": "Test preflight."})
        self.save()
        self.assert_refused_without_change()

    def test_ambiguous_replacement_is_refused(self):
        self.plan["changes"][0]["edits"] = [{"old": "use", "new": "invoke"}]
        self.save()
        self.assert_refused_without_change()

    def test_overlapping_occurrences_of_one_match_are_refused(self):
        data = b"aaa"
        self.skill.write_bytes(data)
        self.audit["inventory"][0]["sha256"] = digest(data)
        self.audit["inventory"][0]["size"] = len(data)
        self.plan["changes"][0]["expected_sha256"] = digest(data)
        self.plan["changes"][0]["edits"] = [{"old": "aa", "new": "b"}]
        self.save()
        self.assert_refused_without_change()

    def test_overlapping_edits_are_refused(self):
        self.plan["changes"][0]["edits"] = [
            {"old": "For Codex: use the old discovery instruction.", "new": "replacement"},
            {"old": "old discovery", "new": "new discovery"},
        ]
        self.save()
        self.assert_refused_without_change()

    def test_edits_match_original_text_not_previous_replacement(self):
        self.plan["changes"][0]["edits"] = [
            {"old": "old discovery", "new": "new discovery"},
            {"old": "new discovery", "new": "final discovery"},
        ]
        self.save()
        self.assert_refused_without_change()

    def test_path_traversal_absolute_paths_and_git_metadata_are_refused(self):
        for path in ("../outside.md", "/tmp/outside.md", "skills/../README.md", ".git/config", ".GIT/config"):
            with self.subTest(path=path):
                self.plan["changes"][0]["path"] = path
                self.save()
                self.assert_refused_without_change()

    def test_symlink_file_is_refused(self):
        original_file = self.base / "original-skill.md"
        original_file.write_bytes(self.original)
        self.skill.unlink()
        self.skill.symlink_to(original_file)
        self.assert_refused_without_change()
        self.assertEqual(original_file.read_bytes(), self.original)

    def test_symlink_parent_is_refused_for_new_files(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.repo / "linked").symlink_to(outside, target_is_directory=True)
        self.plan["changes"].append({"path": "linked/new.md", "expected_sha256": None,
                                     "content": "Do not write this outside the repository.",
                                     "finding_ids": ["DISCOVERY-1"], "rationale": "Test symlink refusal."})
        self.save()
        self.assert_refused_without_change()
        self.assertFalse((outside / "new.md").exists())

    def test_hard_link_is_refused(self):
        link = self.base / "linked-skill.md"
        os.link(self.skill, link)
        self.assert_refused_without_change()
        self.assertEqual(link.read_bytes(), self.original)

    def test_new_file_is_created_and_receipt_has_hashes_only(self):
        self.plan["changes"].append({"path": "references/codex/tool-discovery.md", "expected_sha256": None,
                                     "content": "Example private instruction.\n",
                                     "finding_ids": ["DISCOVERY-1"], "rationale": "Add the selected reference."})
        self.save()
        destination = self.base / "receipt.json"
        result = self.run_plan(write=True, receipt=destination)
        self.assertEqual((self.repo / "references/codex/tool-discovery.md").read_bytes(),
                         b"Example private instruction.\n")
        self.assertEqual(json.loads(destination.read_text()), result)
        self.assertNotIn("Example private instruction", destination.read_text())

    def test_new_file_cannot_overwrite_existing_file(self):
        self.plan["changes"][0] = {"path": "README.md", "expected_sha256": None, "content": "Replacement",
                                    "finding_ids": ["DISCOVERY-1"], "rationale": "Invalid create."}
        self.save()
        self.assert_refused_without_change()

    def test_unknown_finding_and_missing_profile_are_refused(self):
        self.plan["changes"][0]["finding_ids"] = ["made-up-finding"]
        self.save()
        self.assert_refused_without_change()
        self.plan["changes"][0]["finding_ids"] = ["DISCOVERY-1"]
        self.audit["profile"].pop("install_path")
        self.save()
        self.assert_refused_without_change()

    def test_root_mismatch_is_refused(self):
        self.audit["repository"]["root"] = str(self.base)
        self.save()
        self.assert_refused_without_change()

    def test_input_and_receipt_collisions_are_refused_before_writes(self):
        for path in (self.audit_path, self.plan_path, self.skill, self.repo / "receipt.json"):
            with self.subTest(path=path):
                with self.assertRaises(apply_plan.PlanError):
                    self.run_plan(write=True, receipt=path)
                self.assertEqual(self.skill.read_bytes(), self.original)

    def test_receipt_failure_does_not_misreport_applied_files_as_refused(self):
        with mock.patch.object(apply_plan, "_save_receipt", side_effect=apply_plan.PlanError("Output path changed")):
            result = self.run_plan(write=True, receipt=self.base / "receipt.json")
        self.assertEqual(result["status"], "applied_pending_validation")
        self.assertTrue(result["receipt_write_failed"])
        self.assertNotEqual(self.skill.read_bytes(), self.original)

    def test_excluded_directory_changes_do_not_invalidate_scoped_inventory(self):
        excluded = self.repo / "node_modules"
        excluded.mkdir()
        (excluded / "unrelated.js").write_text("Excluded generated dependency")
        result = self.run_plan()
        self.assertEqual(result["status"], "dry_run_ready")

    def test_audit_input_cannot_be_an_edit_target(self):
        # A forged circular audit cannot easily be hash-stable, but protection is
        # enforced independently of inventory validity during plan preflight.
        change = dict(self.plan["changes"][0], path="audit.json")
        with self.assertRaises(apply_plan.PlanError):
            apply_plan._preflight_changes(self.repo, {"changes": [change]}, {}, {"DISCOVERY-1"},
                                          {str(self.repo / "audit.json")})

    def test_duplicate_paths_and_file_directory_conflicts_are_refused(self):
        self.plan["changes"].append(dict(self.plan["changes"][0]))
        self.save()
        self.assert_refused_without_change()
        self.plan["changes"].pop()
        self.plan["changes"].extend([
            {"path": "new-reference", "expected_sha256": None, "content": "File",
             "finding_ids": ["DISCOVERY-1"], "rationale": "Conflicting file."},
            {"path": "new-reference/child.md", "expected_sha256": None, "content": "Child",
             "finding_ids": ["DISCOVERY-1"], "rationale": "Conflicting directory."},
        ])
        self.save()
        self.assert_refused_without_change()

    def test_write_failure_rolls_back_earlier_file_and_cleans_staging(self):
        self.plan["changes"].append({"path": "README.md", "expected_sha256": digest(self.other.read_bytes()),
                                     "edits": [{"old": "Unrelated", "new": "Updated"}],
                                     "finding_ids": ["DISCOVERY-1"], "rationale": "Test rollback."})
        self.save()
        real_replace = os.replace
        count = [0]

        def fail_second_replace(source, target):
            count[0] += 1
            if count[0] == 2:
                raise OSError("Injected write failure with PRIVATE data that must not enter receipt")
            return real_replace(source, target)

        with mock.patch.object(apply_plan.os, "replace", side_effect=fail_second_replace):
            with self.assertRaises(apply_plan.ApplyError) as captured:
                self.run_plan(write=True)
        self.assertEqual(self.skill.read_bytes(), self.original)
        self.assertEqual(self.other.read_bytes(), b"Unrelated documentation.\n")
        self.assertEqual(captured.exception.receipt["status"], "apply_failed_rolled_back")
        self.assertNotIn("PRIVATE", json.dumps(captured.exception.receipt))
        self.assertFalse(list(self.repo.rglob(".migration-*")))

    def test_rollback_failure_reports_affected_path(self):
        self.plan["changes"].append({"path": "README.md", "expected_sha256": digest(self.other.read_bytes()),
                                     "edits": [{"old": "Unrelated", "new": "Updated"}],
                                     "finding_ids": ["DISCOVERY-1"], "rationale": "Test incomplete rollback."})
        self.save()
        real_replace = os.replace
        count = [0]

        def fail_after_first(source, target):
            count[0] += 1
            if count[0] > 1:
                raise OSError("Injected failure")
            return real_replace(source, target)

        with mock.patch.object(apply_plan.os, "replace", side_effect=fail_after_first):
            with self.assertRaises(apply_plan.ApplyError) as captured:
                self.run_plan(write=True)
        self.assertEqual(captured.exception.receipt["status"], "apply_failed_rollback_incomplete")
        self.assertEqual(captured.exception.receipt["rollback_failed_paths"], ["skills/github/SKILL.md"])
        self.assertFalse(list(self.repo.rglob(".migration-*")))


if __name__ == "__main__":
    unittest.main()
