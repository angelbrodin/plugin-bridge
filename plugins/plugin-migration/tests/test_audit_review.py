"""Independent review regressions from pinned importer behavior and route boundaries."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("audit_review", Path(__file__).parents[1] / "scripts" / "audit_repo.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class IndependentAuditReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="migration-independent-review-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()

    def put(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not isinstance(content, str):
            content = json.dumps(content, indent=2)
        path.write_bytes(content.encode("utf-8"))

    def run_scan(self, route="standalone-import", version=audit.PINNED_VERSION):
        return audit.Auditor(self.repo, version, route).run()

    def hits(self, report, rule):
        return [f for f in report["findings"] if f["rule_id"] == rule]

    def hook(self):
        return {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python check.py", "async": True}
        ]}]}}

    def test_nested_example_configs_are_not_confirmed_selected_inputs(self):
        self.put("examples/demo/.mcp.json", {"mcpServers": {"demo": {"url": "${ENDPOINT}"}}})
        self.put("examples/old/.claude/settings.json", self.hook())
        self.assertFalse([f for f in self.run_scan()["findings"] if f["status"] == "confirmed_import_gap"])

    def test_unwrapped_mcp_is_explicitly_unchecked_without_false_import_rules(self):
        self.put("plugins/github/.mcp.json", {"github": {"type": "http", "url": "${ENDPOINT}"}})
        report = self.run_scan(route="plugin-install")
        self.assertTrue(any(s["path"] == "plugins/github/.mcp.json" and "unwrapped MCP" in s["reason"] for s in report["coverage"]["skipped"]))
        self.assertFalse([f for f in report["findings"] if f["rule_id"].startswith("MCP")])

    def test_oversize_command_without_template_tokens_is_a_candidate(self):
        self.put("plugins/demo/commands/review.md", "---\ndescription: Review\n---\n" + "x" * 4001)
        hits = self.hits(self.run_scan(route="plugin-install"), "CMD002")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["status"], "review_required")
        self.assertEqual(hits[0]["applicability"]["verified_conversion_paths"], ["legacy-plugin-command-conversion"])

    def test_command_size_uses_utf8_body_not_character_count(self):
        self.put("commands/review.md", "---\ndescription: Review\n---\n" + "é" * 2001)
        self.assertEqual(len(self.hits(self.run_scan(route="unknown", version="unknown"), "CMD002")), 1)

    def test_command_size_lower_bound_excludes_frontmatter_and_boundary(self):
        self.put("commands/review.md", "---\ndescription: " + "x" * 5000 + "\n---\n" + "x" * 4000)
        self.assertFalse(self.hits(self.run_scan(route="plugin-install"), "CMD002"))

    def test_standalone_command_import_has_no_plugin_size_limit(self):
        self.put(".claude/commands/review.md", "---\ndescription: Review\n---\n" + "x" * 4001)
        hit = self.hits(self.run_scan(), "CMD002")[0]
        self.assertEqual(hit["status"], "not_applicable")
        self.assertFalse(hit["applicability"]["install_path_matches"])

    def test_inherited_disabled_hooks_apply_to_local_settings(self):
        self.put(".claude/settings.json", {"disableAllHooks": True})
        self.put(".claude/settings.local.json", self.hook())
        self.assertFalse(self.hits(self.run_scan(), "HOOK001"))

    def test_later_mcp_override_is_not_confirmed_as_stale_import_gap(self):
        self.put(".mcp.json", {"mcpServers": {"github": {"url": "${OLD}"}}})
        self.put(".claude.json", {"mcpServers": {"github": {"url": "https://example.invalid/mcp"}}})
        self.assertFalse([f for f in self.hits(self.run_scan(), "MCP001") if f["status"] == "confirmed_import_gap"])

    def test_unknown_github_sync_does_not_dismiss_claude_branches(self):
        self.put("skills/pr/SKILL.md", "# GitHub\n## For Claude\nUse select:mcp__example-github__search.\n## For Codex\nUse tool_search.\n")
        report = self.run_scan(route="github-sync", version="unknown")
        self.assertTrue(self.hits(report, "SKILL001"))
        self.assertTrue(all(f["status"] == "review_required" for f in self.hits(report, "SKILL001")))
        self.assertTrue(self.hits(report, "SKILL003"))

    def test_case_insensitive_skill_filename_is_reviewed(self):
        self.put(".claude/skills/pr/skill.md", "# For Claude\nUse select:mcp__example-github__search.\n# For Codex\nUse tool_search.\n")
        report = self.run_scan()
        self.assertTrue(self.hits(report, "SKILL003"))

    def test_crlf_frontmatter_is_not_a_command_body(self):
        self.put(".claude/commands/pr.md", '---\r\ndescription: "$ARGUMENTS reference"\r\n---\r\nList recent pull requests.\r\n')
        self.assertFalse(self.hits(self.run_scan(), "CMD001"))

    def test_explicit_legacy_manifest_command_path_is_inspected_or_named_unchecked(self):
        self.put(".claude-plugin/plugin.json", {"name": "commands", "version": "1.0.0", "commands": ["./tasks/pr.md"]})
        self.put("tasks/pr.md", "---\ndescription: Search\n---\nSearch $ARGUMENTS\n")
        report = self.run_scan(route="plugin-install")
        inspected = bool(self.hits(report, "CMD001"))
        named_unchecked = any(item["path"] == "tasks/pr.md" for item in report["coverage"]["skipped"])
        self.assertTrue(inspected or named_unchecked,
                        "A manifest-selected command must be inspected or explicitly identified as unchecked.")

    def test_direct_native_async_does_not_request_importer_correction(self):
        self.put(".codex-plugin/plugin.json", {"name": "native", "version": "1.0.0", "hooks": "./hooks/hooks.json"})
        self.put("hooks/hooks.json", self.hook())
        self.assertFalse([f for f in self.hits(self.run_scan(route="plugin-install"), "HOOK001")
                          if f["status"] in {"review_required", "confirmed_import_gap"}])

    def test_same_name_env_refs_are_accepted_without_dropping_active_gap(self):
        self.put(".mcp.json", {"mcpServers": {
            "safe": {"command": "server", "env": {"TOKEN": "${TOKEN}"}},
            "bad": {"command": "${COMMAND}"}
        }})
        report = self.run_scan()
        self.assertFalse(self.hits(report, "MCP003"))
        self.assertEqual(len(self.hits(report, "MCP001")), 1)
        self.assertEqual(self.hits(report, "MCP001")[0]["status"], "confirmed_import_gap")


if __name__ == "__main__":
    unittest.main()
