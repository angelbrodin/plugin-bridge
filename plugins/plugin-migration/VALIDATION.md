# Verification record

Version: `0.3.0`
Checked: September 9, 2026  
Result: local prototype checks passed. Customer repository and client execution tests remain outstanding.

## Completed checks

| Check | Result |
| --- | --- |
| Scanner tests | 43 passed, covering detection, target applicability, coverage, report output and file handling. |
| Independent scanner regressions | 14 passed, including public-marketplace coverage and command-size cases. |
| Change application tests | 29 passed, covering dry runs, exact changes, stale source, path boundaries and write failure recovery. |
| Migration selection tests | 20 passed, covering whole-plan, plugin and item selection, exclusions, dependencies, shared effects, conflicts, report output and application. |
| Conversion review and package workflow | 8 passed: conditional candidates, secret omission, file accounting, escaped report paths, selected package creation, unchanged source and stale-source refusal. |
| Total automated tests | **114 passed** on Python 3.9.6. |
| Plugin structure | Built-in plugin validator passed. |
| Skill format | Built-in skill validator passed for both skills. |
| Rule verification | Reviewed against the pinned Codex implementation and primary documentation linked in the rule reference. |
| Independent workflow exercise | Audit, contextual review, exact change plan, dry run, application and re-audit completed on an isolated synthetic marketplace. |

Run the automated suite from the plugin root:

```text
python3 -m unittest discover -s tests -v
```

The plugin scripts use only the Python standard library. PyYAML was used in an isolated verification environment for the external format validators; it is not required by the shipped scripts.

## Independent workflow exercise

The exercise used a seven-file source snapshot containing a GitHub review skill, an HTTP MCP connection, an asynchronous command hook and plugin/marketplace manifests. The target was Codex `0.154.0-alpha.1` through direct plugin installation, with Claude support preserved in source. The reviewer received the task and repository without an expected diagnosis.

The initial scan returned five records. Contextual review identified two active discovery assumptions in one shared instruction. Two other records belonged to a conditional Claude reference; the fifth concerned a standalone-import hook limitation that did not apply to the selected route.

The workflow changed one instruction to use the session's advertised discovery interface and returned tool name/schema. It retained the Claude reference, the restriction on posting reviews, the MCP configuration and the asynchronous hook. The other six source files remained byte-for-byte unchanged.

The helper returned `dry_run_ready`, then `applied_pending_validation`. The reviewer checked actual content, receipt hashes, configuration syntax and local manifest references. The final scan retained three `not_applicable` records. No target hook or script ran, and no remote service was contacted.

The exercise exposed two usability gaps: Markdown reports lacked the unique finding IDs needed for plans, and the migration skill omitted a workflow for source snapshots without Git. Both were corrected. A final regression test verifies the Markdown IDs. The revised snapshot guidance matches the exercised approach; the entire skill exercise was not repeated after these documentation and report-display changes.

## Corrections made during review

- Restricted confirmed standalone-import findings to recognized active inputs, instead of nested examples or direct plugin configurations.
- Respected inherited hook-disable settings and same-name MCP overrides.
- Kept unknown versions and GitHub sync behavior conditional.
- Preserved valid Claude-only instructions for applicable routes while requiring review where import behavior is unknown.
- Corrected command-body parsing for CRLF frontmatter and case-insensitive skill filenames.
- Named unsupported custom command paths in coverage instead of silently omitting them.
- Separated runtime tool-interface applicability from installation-route metadata.
- Prevented report output collisions and overwriting existing reports or audited source.

Independent negative application checks also confirmed that stale inventories, invalid later edits, traversal and symlinked parents are refused without changing source.

## Limits

The verified implementation baseline is Codex `0.154.0-alpha.1`, commit `042534ec1ab2f79c2997e779347d5383832ecb2e`. Other versions require verification. Hosting a repository on GitHub does not establish which importer or installer processes it.

The scripted scan covers selected MCP and hook configuration, discovery instructions and command templates. It does not fully evaluate manifests, agents, permission semantics, custom component paths or runtime behavior. See [scope and rules](references/scope-and-rules.md) and [manual review](references/validation.md).

The application helper validates identity, freshness and exact edits. It can mechanically apply an incorrect instruction if the reviewer supplies one. The migration skill therefore requires review of the actual before/after content and preservation of permissions, authentication and required checks. A successful dry run is not evidence of semantic correctness.

## Public marketplace test

Audited the public [Anthropic Claude plugin marketplace](https://github.com/anthropics/claude-plugins-official/tree/85cce0381e7860082641b59d961a2b8c368b8b79) at revision `85cce0381e7860082641b59d961a2b8c368b8b79`. Its manifest has 291 entries: 53 local and 238 pointing to remote sources. The local checkout contained 460 inventoried files. Remote source repositories were not fetched.

The initial audit produced 36 records. Review identified two prototype gaps: unwrapped MCP configurations were not named individually as unchecked, and the legacy plugin converter's generated-skill size limit was missing. Version 0.1.1 names those MCP coverage exclusions and flags command bodies already over the 4,000-byte budget. Five new regression tests passed.

The revised audit produced 53 records: 38 source-verified conversion conditions across 23 selected command files, 14 standalone-import matches that do not apply to the direct-install route, and one unlisted example command. Source review establishes the pinned converter's behavior; the converter and target alpha were not executed. Unknown-version and unknown GitHub-sync behavior remain conditional.

The migration helper created a separate three-file Codex test package for the read-only modernization-status workflow. It retained the exact upstream workflow as a reference and added an argument-mapping skill entry. Every original file, including marketplace and Claude configuration, remained byte-for-byte unchanged. The native package's first format check exposed missing author/interface metadata; a fresh plan corrected it and validation passed. Skill validation, source hashes, receipt chaining and re-audit also passed.

This test did not migrate the whole marketplace. The separate test package is not registered in its marketplace. Other commands and native configuration still need review. Neither Claude nor an installed Codex plugin was executed. There were no select-style discovery matches in this repository, so this exercise did not reproduce that particular migration case.

## Selective migration workflow

Version 0.2.0 adds a migration catalog, a human-readable plan, and a selector that feeds the existing exact-change applier. The skills map follow-up requests to whole-plan, plugin or item selections and prepare selected proposals before application. The helper refuses unknown or ambiguous selections, missing dependencies, undeclared changes under another plugin root, shared effects outside scope, and conflicting edits. Exclusions take precedence.

The new end-to-end tests applied only the GitHub fixture change and verified that Slack remained unchanged. A stale repository test refused the write and preserved the user's intervening edit. These tests exercise the scripts; they do not establish how reliably a model interprets every natural-language selection.

A separate exercise used a fresh source snapshot of the public marketplace revision above. A two-item catalog contained a prepared modernization-status adaptation (`M001`) and a proposed commit-command adaptation (`M002`). Selecting M001 produced a three-file plan, passed dry run, and applied only those files to the isolated copy. All 460 original files remained byte-for-byte unchanged. The commit adaptation was not applied. After checking content against the receipt, a fresh audit and updated catalog retained the IDs and recorded M001 as applied with client tests pending.

This exercised catalog rendering, item selection, application, receipt verification and refreshed reporting against real source. It was a two-item example, not a migration of the complete marketplace. It reused the previously reviewed status adaptation. No target scripts, hooks or Git commit workflow ran. No plugin was installed or registered, and neither client's runtime was tested.

## Local installation check

Plugin Bridge 0.2.0 was installed and enabled in a local Codex environment. Both skills were present, and all 19 installed package files matched the reviewed archive. This verifies installation of the audit tool, not execution of migrated plugins.

## Not run

- Audits or migrations of customer repositories.
- Installation and installed-content comparison for a migrated plugin.
- Live Codex and Claude workflow regression tests.
- Native hook execution or timing tests.
- Authentication or OAuth refresh-token rotation tests.

Before wider distribution, pilot on a small set of real repositories, including plugins already working in both clients. Record incorrect findings and missed issues, verify the exact installation paths, and run representative workflows separately in each client.

## Version 0.3.0 conversion guidance and accounting

Added five conditional review rules for packaging, agent definitions, selected skill frontmatter, user-input declarations and native MCP launch/environment settings. These locate work for contextual review; they do not certify field mappings. The scanner now emits a per-file accounting table and names skipped paths, with explicit limits for excluded directories and scan bounds. Conversion disposition remains unassessed until reviewed.

The skills now include detailed conversion recipes, a generated-package option that preserves the selective workflow, and a conversion report with separate setup tasks. The package option uses the existing exact-change helpers; it is not an unattended converter or binary packager.

Eight new automated tests passed alongside the original 106. A synthetic two-plugin test selected only one generated text package, verified every original file stayed unchanged, and refused a stale-source write. This tests the application workflow, not the target plugin loader or agent interpretation. Both skill validators and the plugin validator passed, and relative documentation links resolved. No customer material or customer-specific names were added.

The new recipes were checked against the linked official skill/configuration documentation and pinned role/native-MCP loaders. The teammate's separate migration reference was unavailable; its unverified mappings were not imported as facts. Runtime validation in Codex and Claude remains outstanding.
