# Review and validation

Use checks relevant to the changed component. Record passed, failed, not_run or not_applicable with revision, client version, installation method and evidence. Never substitute a scan for an installation or workflow test.

## Manual review beyond the scanner

- Skills: parse YAML metadata, inspect invocation/execution controls, references, paths, variables, templates, client branches and generated files.
- Instructions: identify effective AGENTS/CLAUDE files, nested rules, includes and scope.
- MCP: follow manifest references and inline settings; check precedence, disabled providers, test/production identity, credential references, transport and scopes.
- Hooks: establish event, matcher, handler, arguments, timing, trust and duplicates. Inspect payload/output differences and policy behavior.
- Agents/settings: inspect delegation, model names, permissions, limits, CLI/SDK dependencies and client-specific settings.
- Packaging: resolve plugin and marketplace entries, custom paths, bundled files, symlinks, shared resources and updates. Count local entries separately from remote repositories that were not fetched. Validate generated native plugin manifests and skill files with their format validators.
- Commands: check frontmatter, the selected conversion path and complete generated size. A body below the scanner's size threshold can still exceed the legacy converter's limit after its wrapper is added.

## Test changed behavior

| Layer | Evidence |
| --- | --- |
| Static review | Findings resolved against source, valid relevant configuration, intended diff, limitations recorded. |
| Installation | Intended package installed through the chosen path; expected components present; installed instructions compared to source. |
| Codex workflow | Fresh session, intended provider, representative read-only operation succeeds through the actual tool. |
| Claude regression | Same workflow using the maintained Claude entry and intended provider; result recorded separately. |
| Hook behavior | Positive and negative cases, correct event/timing and required policy. Use isolated test inputs. |
| OAuth refresh | Separate controlled expiry/refresh test when relevant. Tool discovery success does not prove refresh-token rotation correctness. |

If clients or credentials are unavailable, leave results not_run and provide the missing test steps. Matching schemas do not prove a shared instruction works.

## Test this plugin

From the plugin root run:

```text
python3 -m unittest discover -s tests -v
```

Tests should cover import omissions, compatible configurations, unknown targets, different routes, client-only text, malformed JSON, path/symlink handling, stale plans, dry runs and unchanged content. Independent behavioral evaluation should use a realistic task and repository without telling the reviewer the expected diagnosis.

Before broad distribution, pilot on real repositories, including plugins already working in both clients. Measure incorrect findings and missed issues. Do not bundle credentials or customer source without authorization.
