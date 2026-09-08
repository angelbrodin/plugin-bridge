# Plugin Bridge

Audit an existing plugin repository for Codex migration risks, then apply selected changes while keeping shared workflows maintainable.

This is a tested local prototype. It has not been validated against customer repositories or by running migrated plugins in both Codex and Claude. The bundled deterministic baseline is Codex `0.154.0-alpha.1`; other versions and unknown installation paths produce conditional findings.

## Use

Load the plugin through your organization's supported local or repository plugin installation flow, or explicitly ask Codex to use one of the skill files in this checkout. The helper scripts require Python 3.9 or later and use the standard library.

- **Audit plugin repository:** provide a GitHub URL or local checkout, target Codex version, execution environment and installation method. Existing authorized GitHub access is used to obtain a remote repository. Missing access is reported rather than bypassed.
- **Migrate plugin repository:** proceed with the reviewed plan, choose plugins by name, or choose individual change IDs. Codex prepares the selected changes, checks their scope, applies authorized edits and reports remaining work.

Example requests:

> Audit this repository for Codex. We install through GitHub sync and want to preserve Claude support. The Codex version is [our installed version].

The audit returns a migration plan grouped by plugin. Each change has an ID, the issue, the proposed solution, the effect on Claude support, and a status showing whether its patch is prepared or a decision is needed. You can then say:

> Proceed with the migration plan.

> Apply the GitHub and Slack changes only.

> Apply M001 and M003. Leave the other changes for later.

Codex prepares the selected proposals before applying them. It reports anything it cannot complete. Shared-file effects or dependencies outside your selection require an explicit scope decision; exclusions are preserved. After changes, the plan is refreshed so you can select the next items.

If the target version or route is unknown, say so. Do not select the bundled alpha just to obtain confirmed findings.

## What it does

The scripted pass inspects common MCP and hook JSON configuration, skill discovery instructions and legacy command templates. It reports exact locations, source links, target applicability, file hashes and coverage limits. Codex then reviews active components and instructions in context.

The selection helper checks plugin scope, dependencies, shared effects and conflicting edits. The apply helper checks file freshness and exact edit matches, previews by default and records an application receipt. It does not choose fixes automatically or prove they work.

Broader metadata, agents, policies, custom manifest paths and runtime behavior require contextual review. The scanner reports these limits. See [scope and sources](references/scope-and-rules.md), [migration plans and selections](references/migration-plan.md), [exact change plans](references/change-plans.md) and [validation](references/validation.md).

## Maintaining both clients

Preserve shared instructions and scripts when possible. Adapt only client-specific behavior. If separate packages are required, generate them from shared source and include the intended entry in each package. Check the installed result.

Native Codex supports async command hooks. The known standalone-import gap for `async: true` is distinct from native hook support and from direct plugin installation.

## Verification

Run:

```text
python3 -m unittest discover -s tests -v
```

The delivery verification record is in [VALIDATION.md](VALIDATION.md). It distinguishes automated checks from installation and client workflows that have not run.

The plugin does not install the audited plugin, execute its hooks, change live credentials, publish to a marketplace or create a pull request during an audit. An explicit request can authorize later repository changes or a draft pull request.

The display name is Plugin Bridge. The internal plugin ID remains `plugin-migration`.
