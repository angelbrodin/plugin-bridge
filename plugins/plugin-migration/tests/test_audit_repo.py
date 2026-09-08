"""Behavior and false-positive checks for the bounded repository audit."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("audit_repo", Path(__file__).parents[1] / "scripts" / "audit_repo.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repository"
        self.root.mkdir()
        self.addCleanup(self.temp.cleanup)

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) if not isinstance(value, str) else value, encoding="utf-8")
        return path

    def run_audit(self, route="standalone-import", version=audit.PINNED_VERSION):
        return audit.Auditor(self.root, version, route).run()

    def findings(self, report, rule):
        return [f for f in report["findings"] if f["rule_id"] == rule]

    def hook(self, **changes):
        handler = {"type": "command", "command": "python check.py"}
        handler.update(changes)
        return {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [handler]}]}}

    def test_async_is_import_gap_and_not_native_incompatibility(self):
        self.put(".claude/settings.json", self.hook(**{"async": True}))
        finding = self.findings(self.run_audit(), "HOOK001")[0]
        self.assertEqual(finding["status"], "confirmed_import_gap")
        self.assertIn("Codex supports asynchronous command hooks", finding["reason"])
        self.assertIn("do not remove async", finding["recommendation"])
        self.assertEqual(finding["line"], 10)

    def test_wrong_route_and_unknown_version_never_confirmed(self):
        self.put(".claude/settings.json", self.hook(**{"async": True}))
        for route in ["plugin-install", "github-sync", "unknown"]:
            report = self.run_audit(route=route)
            self.assertTrue(all(f["status"] != "confirmed_import_gap" for f in report["findings"]))
        for version in ["0.154.0", "0.154.0-alpha.2", "unknown", "0.155.0"]:
            self.assertEqual(self.findings(self.run_audit(version=version), "HOOK001")[0]["status"], "review_required")
        self.assertEqual(self.findings(self.run_audit(version="rust-v0.154.0-alpha.1"), "HOOK001")[0]["status"], "confirmed_import_gap")

    def test_applicability_distinguishes_runtime_syntax_and_conversion_rules(self):
        self.put("skills/github/SKILL.md", "Use select:mcp__example-github__tool")
        self.put(".claude/commands/pr.md", "$ARGUMENTS")
        self.put("invalid.json", "{")
        self.put(".claude/settings.json", self.hook(**{"async": True}))
        report = self.run_audit(route="plugin-install")
        for rule in ["SKILL001", "SKILL002"]:
            scope = self.findings(report, rule)[0]["applicability"]
            self.assertEqual(scope["scope_kind"], "runtime-tool-interface")
            self.assertIsNone(scope["verified_install_path"])
            self.assertIsNone(scope["install_path_matches"])
        syntax = self.findings(report, "CONFIG001")[0]["applicability"]
        self.assertEqual(syntax["scope_kind"], "json-syntax")
        self.assertIsNone(syntax["verified_version"])
        self.assertIsNone(syntax["verified_install_path"])
        command = self.findings(report, "CMD001")[0]["applicability"]
        self.assertEqual(command["scope_kind"], "command-conversion-path-dependent")
        self.assertIn("legacy-plugin-command-conversion", command["verified_conversion_paths"])
        self.assertIsNone(command["install_path_matches"])
        hook = self.findings(report, "HOOK001")[0]["applicability"]
        self.assertEqual(hook["verified_install_path"], "standalone-import")
        self.assertFalse(hook["install_path_matches"])

    def test_plugin_install_does_not_recommend_standalone_repairs(self):
        self.put(".claude/settings.json", self.hook(**{"async": True}))
        self.put(".mcp.json", {"mcpServers": {"test": {"url": "${URL}"}}})
        for finding in self.run_audit(route="plugin-install")["findings"]:
            self.assertEqual(finding["status"], "not_applicable")
            self.assertIn("No change is recommended", finding["recommendation"])

    def test_plugin_hook_file_is_not_standalone_settings(self):
        self.put("plugins/one/hooks/hooks.json", self.hook(**{"async": True}))
        finding = self.findings(self.run_audit(), "HOOK001")[0]
        self.assertEqual(finding["status"], "review_required")
        self.assertFalse(finding["applicability"]["recognized_import_file"])

    def test_only_root_standalone_hook_settings_are_confirmed(self):
        for name in ["settings.json", "examples/.claude/settings.json", "plugins/p/.claude/settings.json"]:
            self.put(name, self.hook(**{"async": True}))
        self.assertTrue(all(f["status"] == "review_required" for f in self.findings(self.run_audit(), "HOOK001")))
        direct_root = self.root / ".claude"
        self.put(".claude/settings.json", self.hook(**{"async": True}))
        direct = audit.Auditor(direct_root, audit.PINNED_VERSION, "standalone-import").run()
        self.assertEqual(self.findings(direct, "HOOK001")[0]["status"], "confirmed_import_gap")

    def test_async_string_is_not_boolean_true(self):
        self.put(".claude/settings.json", self.hook(**{"async": "true"}))
        self.assertFalse(self.findings(self.run_audit(), "HOOK001"))

    def test_hook_fields_types_events_and_missing_commands(self):
        data = self.hook(**{"type": "prompt", "prompt": "private prompt"})
        data["hooks"]["PostToolUse"].append({"if": "conditional", "hooks": [{"command": "safe"}]})
        data["hooks"]["PostToolUse"].append({"hooks": [{"type": "command", "command": ""}]})
        data["hooks"]["PostToolUseFailure"] = []
        self.put(".claude/settings.json", data)
        rules = {f["rule_id"] for f in self.run_audit()["findings"]}
        self.assertTrue({"HOOK002", "HOOK003", "HOOK004", "HOOK005"}.issubset(rules))

    def test_missing_or_nonstring_hook_type_defaults_command(self):
        data = self.hook(type=42)
        self.put(".claude/settings.json", data)
        self.assertFalse(self.findings(self.run_audit(), "HOOK002"))

    def test_disabled_hooks_do_not_report_import_gap(self):
        data = self.hook(**{"async": True})
        data["disableAllHooks"] = True
        self.put(".claude/settings.json", data)
        report = self.run_audit()
        self.assertFalse(self.findings(report, "HOOK001"))
        self.assertEqual(self.findings(report, "HOOK005")[0]["status"], "not_applicable")

    def test_local_hook_disable_override_is_honored(self):
        self.put(".claude/settings.json", self.hook(**{"async": True}))
        self.put(".claude/settings.local.json", {"disableAllHooks": True})
        self.assertFalse(self.findings(self.run_audit(), "HOOK001"))

    def test_disable_hooks_uses_last_boolean_across_both_files(self):
        base = self.hook(**{"async": True})
        base["disableAllHooks"] = True
        self.put(".claude/settings.json", base)
        for value in [None, "false", 0, {}]:
            local = self.hook(**{"async": True})
            if value is not None:
                local["disableAllHooks"] = value
            self.put(".claude/settings.local.json", local)
            report = self.run_audit()
            self.assertFalse(self.findings(report, "HOOK001"), value)
            self.assertEqual(len(self.findings(report, "HOOK005")), 2)
        self.put(".claude/settings.local.json", {"disableAllHooks": False})
        self.assertEqual(len(self.findings(self.run_audit(), "HOOK001")), 1)

    def test_session_end_does_not_promise_async_runtime(self):
        data = self.hook(**{"async": True})
        data["hooks"]["SessionEnd"] = data["hooks"].pop("PostToolUse")
        self.put(".claude/settings.json", data)
        self.assertIn("run synchronously", self.findings(self.run_audit(), "HOOK001")[0]["recommendation"])

    def test_mcp_placeholders_and_exact_transport_rules(self):
        self.put(".mcp.json", {"mcpServers": {
            "one": {"command": "${BIN}", "args": ["--token", "${TOKEN}"]},
            "two": {"url": "${ENDPOINT}", "type": "sse"},
            "three": {"url": "https://example.invalid", "type": "streamable-http"},
        }})
        report = self.run_audit()
        self.assertEqual(len(self.findings(report, "MCP001")), 3)
        self.assertEqual(len(self.findings(report, "MCP002")), 2)
        self.assertTrue(all(f["status"] == "confirmed_import_gap" for f in report["findings"]))

    def test_accepted_mcp_header_and_env_cases(self):
        self.put(".mcp.json", {"mcpServers": {
            "stdio": {"command": "server", "type": "stdio", "env": {"TOKEN": "${TOKEN}", "STATIC": "literal"}},
            "http": {"url": "https://example.invalid", "type": "streamable_http", "headers": {"aUtHoRiZaTiOn": "Bearer ${TOKEN}", "X-Key": "${KEY}"}},
            "nonstring": {"url": "https://example.invalid", "type": 1},
        }})
        self.assertFalse(self.run_audit()["findings"])

    def test_nested_mcp_files_are_candidates_not_root_import_inputs(self):
        for name in ["examples/.mcp.json", "plugins/p/.mcp.json", "fixtures/.claude.json"]:
            self.put(name, {"mcpServers": {"test": {"url": "${URL}"}}})
        findings = self.findings(self.run_audit(), "MCP001")
        self.assertEqual(len(findings), 3)
        self.assertTrue(all(f["status"] == "review_required" for f in findings))

    def test_project_scoped_claude_records_are_not_assumed_active(self):
        self.put(".claude.json", {"projects": {"/some/other/repo": {"mcpServers": {"test": {"url": "${URL}"}}}}})
        self.assertFalse(self.findings(self.run_audit(), "MCP001"))

    def test_root_claude_json_overrides_same_name_mcp_record(self):
        self.put(".mcp.json", {"mcpServers": {"same": {"url": "${URL}"}, "other": {"url": "${OTHER}"}}})
        self.put(".claude.json", {"mcpServers": {"same": {"url": "https://example.invalid"}}})
        findings = self.findings(self.run_audit(), "MCP001")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["path"], ".mcp.json")

    def test_command_takes_precedence_over_url(self):
        self.put(".mcp.json", {"mcpServers": {"both": {"command": "safe", "url": "${IGNORED}", "type": "http"}}})
        report = self.run_audit()
        self.assertFalse(self.findings(report, "MCP001"))
        self.assertEqual(len(self.findings(report, "MCP002")), 1)

    def test_alias_composite_and_case_sensitive_bearer_fail(self):
        self.put(".mcp.json", {"mcpServers": {
            "stdio": {"command": "server", "env": {"TOKEN": "${OTHER}"}},
            "http": {"url": "https://example.invalid", "headers": {"Authorization": "bearer ${TOKEN}", "X-Key": "prefix-${KEY}"}},
        }})
        self.assertEqual(len(self.findings(self.run_audit(), "MCP003")), 3)

    def test_fallback_is_review_and_not_skip(self):
        self.put(".mcp.json", {"mcpServers": {"stdio": {"command": "server", "env": {"TOKEN": "${TOKEN:-default}"}}}})
        report = self.run_audit()
        self.assertFalse(self.findings(report, "MCP003"))
        self.assertEqual(self.findings(report, "MCP006")[0]["status"], "review_required")

    def test_disabled_mcp_and_lists_do_not_create_defects(self):
        self.put(".mcp.json", {"mcpServers": {"disabled": {"disabled": True, "url": "${URL}"}, "listed": {"url": "${URL}"}, "allowed": {"url": "https://example.invalid"}}})
        self.put(".claude/settings.json", {"disabledMcpjsonServers": ["listed"]})
        report = self.run_audit()
        self.assertFalse(self.findings(report, "MCP001"))
        self.assertEqual(len(self.findings(report, "MCP004")), 2)
        self.assertTrue(all(f["status"] == "not_applicable" for f in report["findings"]))

    def test_skill_candidates_and_claude_only_sections(self):
        self.put("skills/github/SKILL.md", "# Find tools\nUse select:mcp__example-github__search.\n## For Claude\nUse select:mcp__example-github__search.\n## For Codex\nUse tool_search.\n")
        report = self.run_audit(route="plugin-install")
        first, second = self.findings(report, "SKILL001")
        self.assertEqual(first["status"], "review_required")
        self.assertEqual(second["status"], "not_applicable")
        self.assertFalse(self.findings(report, "SKILL003"))
        standalone = self.run_audit()
        self.assertEqual(len(self.findings(standalone, "SKILL003")), 1)
        self.assertEqual(self.findings(standalone, "SKILL001")[1]["status"], "review_required")

    def test_examples_in_readme_are_not_active_skills(self):
        self.put("README.md", "# Example\nUse select:mcp__example-github__tool $ARGUMENTS.\n")
        self.assertFalse(self.run_audit()["findings"])

    def test_nearest_client_section_overrides_shared_parent_title(self):
        self.put("skills/github/SKILL.md", "# GitHub for Claude and Codex\n## For Claude\nUse select:tool.\n## For Codex\nUse tool_search.\n")
        finding = self.findings(self.run_audit(route="plugin-install"), "SKILL001")[0]
        self.assertEqual(finding["status"], "not_applicable")

    def test_unknown_route_and_version_keep_claude_branch_under_review(self):
        self.put("skills/github/skill.md", "# GitHub\n## For Claude\nUse select:tool.\n## For Codex\nUse tool_search.\n")
        for route, version in [("github-sync", audit.PINNED_VERSION), ("plugin-install", "unknown")]:
            report = self.run_audit(route=route, version=version)
            self.assertEqual(self.findings(report, "SKILL001")[0]["status"], "review_required")
            self.assertEqual(len(self.findings(report, "SKILL003")), 1)

    def test_commands_body_only_and_route_scope(self):
        self.put(".claude/commands/pr.md", "---\ndescription: Search\n---\nSearch $ARGUMENTS\n")
        self.put(".claude/commands/ok.md", "---\ndescription: '$ARGUMENTS'\n---\nSearch recent pull requests.\n")
        self.put("plugins/p/commands/task.md", "Use @file.md\n")
        findings = self.findings(self.run_audit(), "CMD001")
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["status"], "confirmed_import_gap")
        self.assertEqual(findings[1]["status"], "review_required")
        for f in self.findings(self.run_audit(route="plugin-install"), "CMD001"):
            self.assertEqual(f["status"], "review_required")

    def test_crlf_frontmatter_is_not_treated_as_command_body(self):
        self.put(".claude/commands/ok.md", "---\r\ndescription: '$ARGUMENTS'\r\n---\r\nSearch recent pull requests.\r\n")
        self.assertFalse(self.findings(self.run_audit(), "CMD001"))
        self.put(".claude/commands/bad.md", "---\r\ndescription: 'Search'\r\n---\r\nSearch $ARGUMENTS\r\n")
        self.assertEqual(self.findings(self.run_audit(), "CMD001")[0]["line"], 4)

    def test_readme_under_commands_is_excluded(self):
        self.put(".claude/commands/README.md", "---\ndescription: Examples\n---\n$ARGUMENTS and @file")
        self.assertFalse(self.findings(self.run_audit(), "CMD001"))

    def test_nested_claude_commands_are_candidates(self):
        self.put("examples/.claude/commands/pr.md", "$ARGUMENTS")
        self.assertEqual(self.findings(self.run_audit(), "CMD001")[0]["status"], "review_required")

    def test_command_patterns_are_detected(self):
        for index, body in enumerate(["$1", "before {{ value }}", "!`date`", "! `date`", "run @path"]):
            self.put(".claude/commands/%s.md" % index, body)
        self.assertEqual(len(self.findings(self.run_audit(), "CMD001")), 5)

    def test_malformed_json_does_not_abort_other_files(self):
        self.put("plugins/a/.mcp.json", '{"mcpServers": {"secret": "do not disclose"')
        self.put("plugins/b/.mcp.json", {"mcpServers": {"tool": {"url": "${URL}"}}})
        report = self.run_audit()
        self.assertEqual(len(self.findings(report, "CONFIG001")), 1)
        self.assertEqual(len(self.findings(report, "MCP001")), 1)
        self.assertIn("plugins/a/.mcp.json", [s["path"] for s in report["coverage"]["skipped"]])

    def test_duplicate_json_keys_are_not_silently_resolved(self):
        self.put(".mcp.json", '{"mcpServers": {}, "mcpServers": {}}')
        self.assertEqual(len(self.findings(self.run_audit(), "CONFIG001")), 1)

    def test_secrets_commands_and_identifiers_are_not_in_report(self):
        secret = "DO_NOT_LEAK_THIS_TOKEN_123"
        self.put(".mcp.json", {"mcpServers": {secret: {"url": "https://example.invalid", "headers": {"Authorization": "Bearer " + secret + "-${TOKEN}"}}}})
        self.put(".claude/settings.json", self.hook(command="curl --token " + secret, **{"async": True}))
        report = self.run_audit()
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn(secret, audit.markdown(report))

    def test_symlinks_and_excluded_directories_not_followed(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "SKILL.md").write_text("select:mcp__secret-x__tool", encoding="utf-8")
        (self.root / "linked").symlink_to(outside, target_is_directory=True)
        (self.root / "SKILL.md").symlink_to(outside / "SKILL.md")
        self.put("node_modules/pkg/SKILL.md", "select:mcp__ignored-x__tool")
        report = self.run_audit()
        self.assertFalse(report["findings"])
        self.assertEqual(len(report["coverage"]["skipped"]), 3)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX")
    def test_fifo_is_not_opened(self):
        os.mkfifo(self.root / "wait.json")
        report = self.run_audit()
        self.assertEqual(report["coverage"]["skipped"][0]["reason"], "non-regular file not read")

    def test_large_file_is_skipped_with_coverage_notice(self):
        self.put("skills/large/SKILL.md", "x" * (audit.MAX_FILE_BYTES + 1))
        report = self.run_audit()
        self.assertFalse(report["findings"])
        self.assertEqual(len(report["coverage"]["skipped"]), 1)

    def test_multi_plugin_inventory_stability_and_freshness(self):
        self.put("plugins/a/skills/github/SKILL.md", "Use select:mcp__a-b__tool\n")
        path = self.put("plugins/b/skills/github/SKILL.md", "Use select:mcp__c-d__tool\n")
        first, second = self.run_audit(), self.run_audit()
        self.assertEqual(first, second)
        self.assertEqual(len(first["inventory"]), 2)
        self.assertEqual(len(first["findings"]), 4)
        path.write_text("Use select:mcp__e-f__tool\n", encoding="utf-8")
        third = self.run_audit()
        self.assertEqual(second["findings"][2]["id"], third["findings"][2]["id"])
        self.assertNotEqual(second["findings"][2]["fingerprint"], third["findings"][2]["fingerprint"])
        self.assertEqual(third["runtime_validation"], "not_run")

    def test_cli_does_not_write_into_scanned_repository(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main([str(self.root), "--target-version", audit.PINNED_VERSION, "--install-path", "unknown", "--json-out", str(self.root / "report.json")])
        self.assertFalse((self.root / "report.json").exists())

    def test_public_inventory_matches_report_and_detects_additions(self):
        self.put("skills/a/SKILL.md", "A workflow")
        before = self.run_audit()["inventory"]
        self.assertEqual(audit.build_inventory(self.root), before)
        self.put("skills/b/SKILL.md", "Another workflow")
        self.assertNotEqual(audit.build_inventory(self.root), before)

    def test_cli_emits_json_and_markdown(self):
        self.put("skills/x/SKILL.md", "Use select:tool")
        json_out, md_out = Path(self.temp.name) / "report.json", Path(self.temp.name) / "report.md"
        result = audit.main([str(self.root), "--target-version", "unknown", "--install-path", "unknown", "--json-out", str(json_out), "--markdown-out", str(md_out)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(json_out.read_text())["runtime_validation"], "not_run")
        self.assertIn("does not certify compatibility", md_out.read_text())

    def test_markdown_includes_each_unique_finding_id_for_change_plans(self):
        self.put("skills/one/SKILL.md", "Use select:mcp__one-tool__search")
        self.put("skills/two/SKILL.md", "Use select:mcp__two-tool__search")
        report = self.run_audit()
        rendered = audit.markdown(report)
        ids = {finding["id"] for finding in report["findings"]}
        self.assertEqual(len(ids), 4)
        for finding_id in ids:
            self.assertEqual(rendered.count("Finding ID: `" + finding_id + "`"), 1)

    def test_cli_rejects_same_outputs_existing_outputs_and_symlinks(self):
        output = Path(self.temp.name) / "report.json"
        base = [str(self.root), "--target-version", "unknown", "--install-path", "unknown"]
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main(base + ["--json-out", str(output), "--markdown-out", str(output)])
        self.assertFalse(output.exists())
        output.write_text("immutable audit", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main(base + ["--json-out", str(output)])
        self.assertEqual(output.read_text(), "immutable audit")
        link = Path(self.temp.name) / "link.json"
        link.symlink_to(Path(self.temp.name) / "does-not-exist")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main(base + ["--json-out", str(link)])


if __name__ == "__main__":
    unittest.main()
