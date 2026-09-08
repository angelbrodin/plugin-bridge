import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import migration_plan as planner


class MigrationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "repo"
        for name in ("github", "slack"):
            p = self.root / "plugins" / name / "skills" / "search" / "SKILL.md"
            p.parent.mkdir(parents=True)
            p.write_text("---\nname: search\ndescription: Search\n---\nUse select:mcp__" + name + "__search.\n")
        self.audit_path = self.base / "audit.json"
        subprocess.run([sys.executable, str(SCRIPTS / "audit_repo.py"), str(self.root), "--target-version", "0.154.0-alpha.1", "--install-path", "plugin-install", "--json-out", str(self.audit_path)], check=True, capture_output=True)
        self.raw = self.audit_path.read_bytes()
        self.audit = json.loads(self.raw)
        self.catalog = {"schema_version": 1, "audit_sha256": hashlib.sha256(self.raw).hexdigest(),
                        "plugins": [{"id": n, "name": n.title(), "path": "plugins/" + n} for n in ("github", "slack")], "items": []}
        inventory = {f["path"]: f["sha256"] for f in self.audit["inventory"]}
        for i, name in enumerate(("github", "slack"), 1):
            f = next(f for f in self.audit["findings"] if "/" + name + "/" in f["path"])
            self.catalog["items"].append({"id": "M00" + str(i), "plugin_id": name, "title": "Adapt discovery",
                "status": "ready", "problem": "The shared instruction prescribes a selection operator.",
                "solution": "Follow the advertised discovery schema.", "claude_impact": "Common workflow retained; runtime tests pending.",
                "next_step": "Review the patch and test both clients.", "changes": [{"path": f["path"],
                "expected_sha256": inventory[f["path"]], "finding_ids": [f["id"]], "rationale": "Use supported discovery.",
                "edits": [{"old": "Use select:mcp__" + name + "__search.", "new": "Find the search tool using the discovery schema exposed in this session."}]}]})

    def select(self, **kwargs):
        return planner.select(self.catalog, self.audit, self.raw, **kwargs)

    def test_plugin_selection_does_not_include_other_plugins(self):
        p = self.select(plugin_names=["GitHub"])
        self.assertEqual(p["selection"]["item_ids"], ["M001"])
        self.assertTrue(all("/github/" in c["path"] for c in p["changes"]))
        self.assertEqual(p["selection"]["omitted"][0]["id"], "M002")

    def test_individual_selection(self):
        self.assertEqual(self.select(item_ids=["M002"])["selection"]["plugin_ids"], ["slack"])

    def test_all_ready_reports_unresolved_items_without_selecting_them(self):
        self.catalog["items"][1].update(status="needs_decision", changes=[])
        p = self.select(all_ready=True)
        self.assertEqual(p["selection"]["item_ids"], ["M001"])
        self.assertEqual(p["selection"]["omitted"][0]["reason"], "not ready")

    def test_explicit_unprepared_item_is_not_silently_skipped(self):
        self.catalog["items"][1].update(status="proposed", changes=[])
        with self.assertRaisesRegex(planner.PlanError, "not ready"):
            self.select(item_ids=["M001", "M002"])

    def test_exclusions_override_all_ready(self):
        self.assertEqual(self.select(all_ready=True, exclude_plugins=["slack"])["selection"]["item_ids"], ["M001"])
        self.assertEqual(self.select(all_ready=True, exclude_items=["M001"])["selection"]["item_ids"], ["M002"])

    def test_unknown_or_ambiguous_plugin_names_are_refused(self):
        with self.assertRaises(planner.PlanError):
            self.select(plugin_names=["githbu"])
        for p in self.catalog["plugins"]:
            p["name"] = "Connector"
        with self.assertRaisesRegex(planner.PlanError, "ambiguous"):
            self.select(plugin_names=["Connector"])
        self.assertEqual(self.select(plugin_names=["github"])["selection"]["item_ids"], ["M001"])

    def test_unknown_item_and_empty_selection_are_refused(self):
        with self.assertRaises(planner.PlanError):
            self.select(item_ids=["M999"])
        with self.assertRaises(planner.PlanError):
            self.select(all_ready=True, exclude_items=["M001", "M002"])

    def test_dependency_does_not_silently_expand_selection(self):
        self.catalog["items"][0]["depends_on"] = ["M002"]
        with self.assertRaisesRegex(planner.PlanError, "dependencies"):
            self.select(item_ids=["M001"])
        self.assertEqual(len(self.select(item_ids=["M001", "M002"])["changes"]), 2)

    def test_excluded_dependency_is_not_reintroduced(self):
        self.catalog["items"][0]["depends_on"] = ["M002"]
        with self.assertRaises(planner.PlanError):
            self.select(all_ready=True, exclude_items=["M002"])

    def test_applied_dependency_can_be_carried_in_fresh_catalog(self):
        self.catalog["items"][0]["depends_on"] = ["M002"]
        self.catalog["items"][1]["status"] = "applied"
        self.assertEqual(self.select(item_ids=["M001"])["selection"]["item_ids"], ["M001"])

    def test_cycles_and_unknown_dependencies_are_refused(self):
        self.catalog["items"][0]["depends_on"] = ["M999"]
        with self.assertRaises(planner.PlanError):
            self.select(all_ready=True)
        self.catalog["items"][0]["depends_on"] = ["M002"]
        self.catalog["items"][1]["depends_on"] = ["M001"]
        with self.assertRaisesRegex(planner.PlanError, "cycle"):
            self.select(all_ready=True)

    def test_shared_impact_needs_explicit_scope(self):
        self.catalog["items"][0]["affected_plugin_ids"] = ["github", "slack"]
        with self.assertRaisesRegex(planner.PlanError, "unselected"):
            self.select(plugin_names=["github"])
        self.assertEqual(self.select(plugin_names=["github"], allow_shared=["slack"])["selection"]["item_ids"], ["M001"])
        with self.assertRaises(planner.PlanError):
            self.select(plugin_names=["github"], allow_shared=["slack"], exclude_plugins=["slack"])

    def test_edit_in_other_plugin_requires_declared_impact(self):
        self.catalog["items"][0]["changes"] = copy.deepcopy(self.catalog["items"][1]["changes"])
        with self.assertRaisesRegex(planner.PlanError, "affected_plugin_ids"):
            self.select(plugin_names=["github"])

    def test_catalog_is_bound_to_exact_audit_bytes(self):
        with self.assertRaisesRegex(planner.PlanError, "does not match"):
            planner.select(self.catalog, self.audit, self.raw + b"\n", all_ready=True)

    def test_identical_file_edits_are_deduplicated(self):
        self.catalog["items"][1].update(plugin_id="github", changes=copy.deepcopy(self.catalog["items"][0]["changes"]))
        p = self.select(all_ready=True)
        self.assertEqual(len(p["changes"]), 1)
        self.assertEqual(len(p["changes"][0]["edits"]), 1)

    def test_conflicting_file_edits_are_refused(self):
        self.catalog["items"][1].update(plugin_id="github", changes=copy.deepcopy(self.catalog["items"][0]["changes"]))
        self.catalog["items"][1]["changes"][0]["edits"][0]["new"] = "Different replacement"
        with self.assertRaisesRegex(planner.PlanError, "Conflicting"):
            self.select(all_ready=True)

    def test_report_contains_action_and_scope_without_patch_contents(self):
        text = planner.render(self.catalog, self.audit, self.raw)
        for item in self.catalog["items"]:
            self.assertIn(item["id"], text)
            self.assertIn(item["solution"], text)
            self.assertIn(item["claude_impact"], text)
        self.assertNotIn(self.catalog["items"][0]["changes"][0]["edits"][0]["new"], text)

    def test_selected_plan_applies_only_selected_plugin_end_to_end(self):
        before = {p: p.read_bytes() for p in self.root.rglob("SKILL.md")}
        out = self.base / "selected.json"
        out.write_text(json.dumps(self.select(plugin_names=["github"])))
        args = [sys.executable, str(SCRIPTS / "apply_plan.py"), str(self.root), "--audit", str(self.audit_path), "--plan", str(out)]
        dry = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))
        applied = subprocess.run(args + ["--write"], capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        for p, data in before.items():
            self.assertEqual(p.read_bytes() == data, "/slack/" in str(p))

    def test_selected_plan_still_refuses_stale_source(self):
        out = self.base / "selected.json"
        out.write_text(json.dumps(self.select(all_ready=True)))
        target = self.root / self.catalog["items"][0]["changes"][0]["path"]
        target.write_text(target.read_text() + "Unrelated user edit.\n")
        before = {p: p.read_bytes() for p in self.root.rglob("SKILL.md")}
        result = subprocess.run([sys.executable, str(SCRIPTS / "apply_plan.py"), str(self.root), "--audit", str(self.audit_path), "--plan", str(out), "--write"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(p.read_bytes() == data for p, data in before.items()))

    def test_cli_output_does_not_overwrite_or_write_into_repository(self):
        catalog = self.base / "catalog.json"
        catalog.write_text(json.dumps(self.catalog))
        for out in (self.root / "plan.md", catalog):
            before = catalog.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPTS / "migration_plan.py"), "render", "--catalog", str(catalog), "--audit", str(self.audit_path), "--out", str(out)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(catalog.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
