# Scope and rule sources

This first-pass migration assistant automates a bounded subset of the earlier reference. Other topics need contextual review. No rule is a universal conversion recipe.

## Target profiles

The implementation baseline is Codex `0.154.0-alpha.1`, commit `042534ec1ab2f79c2997e779347d5383832ecb2e`. This is a reproducible baseline, not a recommendation to install that alpha or a claim about the latest release. Verify different versions before confirming their behavior.

| Profile | Meaning |
| --- | --- |
| `standalone-import` | Standalone Claude settings, skill and command import. Confirm each file is an input. |
| `plugin-install` | Direct installation. Legacy and portable agent-plugin formats differ; this scanner does not fully resolve that distinction. |
| `github-sync` | Repository sync whose backend needs verification. GitHub hosting alone does not identify an importer. |
| `unknown` | Conditional candidates and missing context. |

An import gap means the known path cannot transfer a component as configured. It does not establish that native Codex lacks the feature. Disabled components are intentionally omitted, not automatically incompatible.

## Source-backed facts

| Area | Behavior and treatment | Source |
| --- | --- | --- |
| Tool discovery | Reviewed `tool_search` takes a required string `query` and optional `limit` and searches metadata. Review active instructions before replacing a client-specific selection operator. | [Schema](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/core/src/tools/handlers/tool_search_spec.rs#L16) |
| Callable names | Codex normalizes callable names. Discover actual names; server IDs, labels, URLs and login commands are separate. | [Name handling](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/codex-mcp/src/mcp/mod.rs#L540) |
| Standalone skill copy | Product terms inside SKILL.md can be rewritten. Dual-client conditions may change meaning. Existing target directories may be skipped instead of updated. | [Copy path](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/external-agent-migration/src/utils.rs#L44), [terms](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/external-agent-migration/src/source/cla.rs#L22) |
| Command conversion | Certain placeholders, preprocessing and inclusion tokens in command bodies cause skips. This is not a native-skill rejection rule. Legacy plugin command conversion differs from portable agent-plugin handling. | [Template checks](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/core-plugins/src/command_migration.rs#L418) |
| Legacy command size | Generated command skills over 4,000 UTF-8 bytes are skipped by the reviewed legacy plugin converter. The scanner flags bodies already over this limit; the generated wrapper can also push a shorter body over it. Standalone command import has no such cap in this implementation. | [Plugin limit](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/core-plugins/src/command_migration/plugin.rs#L18), [size check](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/core-plugins/src/command_migration.rs#L168) |
| Standalone MCP import | Unsupported transports, command/argument/URL placeholders and certain environment/header expressions skip servers. Some accepted defaults are lost. | [Importer](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/external-agent-migration/src/mcp.rs#L184) |
| Plugin MCP loading | A separate parser handles plugin settings and transport aliases. Standalone rejection rules do not apply automatically. | [Plugin parser](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/codex-mcp/src/plugin_config.rs#L236) |
| Standalone hook import | Boolean async:true, explicit non-command handlers, extra keys and unknown events can be omitted. | [Importer](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/external-agent-migration/src/hooks_cla.rs#L100) |
| Native hooks | Async command hooks are supported. Background hooks cannot enforce blocking decisions; SessionEnd is synchronous. | [Native schema](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/config/src/hook_config.rs#L162), [hook docs](https://learn.chatgpt.com/docs/hooks#run-hooks-in-the-background) |

## Before confirming a finding

Verify target version, route, active component and the complete condition. Literal text may be an example, a prohibition or a Claude-only branch. Scanner branch detection is heuristic; re-read the Markdown. Authentication and OAuth refresh require separate evidence.

New rules need primary sources, explicit versions/routes and positive and negative tests. Do not generalize alpha behavior to future releases by comparing version numbers.
