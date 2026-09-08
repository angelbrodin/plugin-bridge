# Plugin Bridge

An early prototype built with Codex to review plugin repositories for potential Codex compatibility issues and prepare selected migration changes.

## Try it

Download or clone this repository, then open the folder in Codex. Ask:

> Use the audit-plugin-repo skill in plugins/plugin-migration/skills to audit [repository URL or local path]. Preserve Claude support and prepare a migration plan. My Codex version is [version] and I install plugins through [installation method]. Do not change the source files yet.

The audit produces a plan grouped by plugin, including proposed fixes, prepared changes and decisions that need review. After reviewing it, you can ask:

- Proceed with the migration plan.
- Apply the GitHub changes only.
- Apply M001 and M003; leave the other changes for later.

Codex prepares the selected changes, checks dependencies and file freshness, and reports what it applied and what still needs testing. The plugin's two skill files are under [plugins/plugin-migration/skills](plugins/plugin-migration/skills). Its helper scripts require Python 3.9 or later.

## Prototype status

This is a first-pass prototype for review and testing. Automated checks and a limited migration exercise on a copy of a public plugin marketplace have passed. It has not been tested against customer repositories or by running migrated workflows in both Codex and Claude.

The scanner covers selected differences, not every possible compatibility issue. Findings depend on the target Codex version and installation method. Its source-verified baseline is 0.154.0-alpha.1; that is a reference point, not a recommendation to install that version.

Start with a small set of plugins. Review proposed changes and test the affected workflows in each client before distributing them. The goal is to preserve shared workflows and Claude support where possible, but that still requires validation.

See the [plugin guide](plugins/plugin-migration/README.md), [checks performed](plugins/plugin-migration/VALIDATION.md), and [rule sources and coverage](plugins/plugin-migration/references/scope-and-rules.md).
