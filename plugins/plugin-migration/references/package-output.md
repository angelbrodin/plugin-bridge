# Optional generated Codex packages

Selective migration is the default. Generate a separate Codex package when the user selects this mode or a reviewed layout/configuration difference makes it useful. Explain a necessary mode change before applying it. Do not duplicate every plugin by default.

## One maintained repository

A repository can hold shared source, the existing Claude packages, and generated Codex packages. Each client still needs a supported marketplace manifest and source path. One repository does not guarantee that one marketplace manifest or one package is accepted unchanged by both clients.

Keep business instructions, scripts and resources maintained in one source where possible. Store the conversion recipe and source revision so outputs can be regenerated. Treat generated files as build outputs; changes should feed back into the shared source or recipe rather than become two manually maintained implementations.

Example layout, to adapt to the actual marketplace schemas:

```text
plugins/review/                 existing source and Claude package
codex-packages/review/          generated Codex package
```

This is a suggested layout, not a manifest format. Do not alter marketplace registration, policy or distribution until authorized. Check which manifest each client and the customer's GitHub-sync route selects. Only the appropriate instructions should become active in each client.

## Preserve the selective workflow

1. Use the same migration catalog, plugin IDs, item IDs, dependencies and exclusions. Record the selected output mode per plugin in the conversion report. Generating GitHub alone does not authorize converting Slack or copying its private configuration.
2. Audit an isolated working copy containing the source and intended output parent. Use the same source hashes and freshness checks as selective edits. For output outside that tree, create an isolated workspace containing the source snapshot and a fresh audit; never rewrite an audit's recorded root.
3. Prepare new text files through the existing exact-change plan with `expected_sha256: null`. Link actual reviewed findings, including `REVIEW001` for packaging when applicable. Declare shared effects and every source-to-output mapping. Retain the owning source plugin ID; if an output path overlaps another registered plugin, declare that effect or choose a different path.
4. Preserve source files byte-for-byte in this mode. Convert only selected components and their authorized dependencies. Copy required portable text into the package where necessary to make it self-contained; report the copy and record its source hash. Do not copy `.git`, caches, credentials, personal settings or unrelated plugins.
5. The existing applier supports UTF-8 text writes, not binary copying or executable-mode preservation. For required binaries or executable helpers, use a separate reviewed file-copy step in the isolated output, checking source and destination hashes and modes. Record its result and verify the original source again. Do not encode binary content into text patches or claim the text helper handled it. If that step cannot be completed, mark packaging incomplete.
6. Generate a valid native manifest pointing only to existing intended components. Place separately distributed agents outside the plugin if required by the selected target route, and record their registration/setup tasks. Do not assume putting an `agents` folder inside a plugin installs agents.
7. Run the normal selection, dry run, authorized application and receipt workflow. If required work remains blocked, identify the output as incomplete rather than installable. Compare all source hashes and review the output's files, modes, paths, manifests and references.
8. On regeneration, use a fresh audit and exact edits or a fresh output directory. Never blindly overwrite generated files that someone edited, reuse a stale patch, or delete the prior package to bypass conflicts.

The package option is an agent-guided workflow using the existing selection and application helpers. It is not a universal unattended converter or a new binary packager.

## Handoff

Follow [file accounting and setup](file-accounting.md). Include the output path, source revision, source-preservation check, conversion recipe, remaining setup and tests. Distinguish package creation, marketplace registration, installation, authentication and runtime validation. A package can be generated successfully while still requiring setup or missing required components.
