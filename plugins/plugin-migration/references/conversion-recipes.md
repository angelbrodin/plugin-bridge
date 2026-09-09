# Conversion recipes

Use these recipes only for components selected by the source manifest and the customer's actual installation route. Preserve shared source by default. Record the source field, target treatment, behavior change, supporting evidence and remaining test for each conversion.

These are reviewed instructions for Codex, not automatic field translations. `REVIEW001` through `REVIEW005` locate candidates and supply finding IDs for the normal selection and patch workflow. A match is not proof of incompatibility. The scanner does not parse YAML, resolve all references or validate native configuration semantics.

## Skill metadata and instructions

Parse the complete YAML frontmatter with a safe parser available in the working environment. A parse failure is a blocker for that file, not permission to discard its metadata. Preserve name, description, supported metadata, body instructions and supporting resources.

| Source feature | Treatment | Validation |
| --- | --- | --- |
| `disable-model-invocation: true` | For targets supporting this policy, set `agents/openai.yaml` -> `policy.allow_implicit_invocation: false`. Merge into any existing file. This preserves explicit invocation while disabling implicit selection. | Verify explicit invocation works and automatic selection remains disabled. |
| `trigger` or custom activation fields | Establish what the source actually does. Do not map an arbitrary trigger string directly to a boolean policy. Preserve intent through verified description/policy settings or leave a decision. | Test the intended triggering and non-triggering prompts. |
| `allowed-tools` | Determine whether the source grants preapproval, restricts tools, or documents dependencies. Tool dependency declarations are not an equivalent permission mechanism. Preserve the intended policy with supported controls before removing the source field from a generated file. | Test a permitted action and any intended prohibited/approval-required action. |
| `model`, `context`, `agent`, `skills` | Treat execution context, model choice and preloaded instructions separately. An ordinary skill is not a separately configured agent. Explicitly invoking another skill can differ from preloading its entire body. Use the agent recipe if necessary. | Verify model/context requirements and that required instructions are present when used. |
| `argument-hint`, structured arguments, `$ARGUMENTS` | Preserve required inputs, defaults, validation and argument handling in a native entry. Do not delete interpolation without translating its behavior. | Test missing, positional and quoted inputs as applicable. |
| `user-invocable`, tags and other metadata | Check target schema and activation behavior. Preserve supported metadata. Remove or relocate a field only after establishing its meaning and recording any lost behavior. | Parse generated files and compare discovery and invocation. |

For MCP dependencies, use the supported `agents/openai.yaml` schema and actual provider identity. Never invent an endpoint or convert a permission restriction into a dependency declaration. Keep common workflow prose shared. For discovery, use the interface present in the session and its returned tool names and input schema. Plain service-and-operation wording avoids hard-coded callable aliases, but still needs real discovery and a clear distinction between test and production connections.

Evidence: [skill metadata and invocation policy](https://learn.chatgpt.com/docs/build-skills#optional-metadata). Verify target-version semantics before claiming equivalence. The source client's frontmatter semantics must also be checked for the fields actually used.

## Agent definitions

1. Confirm each agent is active. Inventory its metadata, instructions, tools, skills and external references.
2. Choose the supported agent distribution route for the target. A standalone Codex role file can carry `name`, `description` and `developer_instructions` in the reviewed implementation. Preserve the body except for explained conversions. A TOML file being generated does not register or install it.
3. Map model and effort only to values supported and available in the customer's target. Do not hard-code a currently available model as an enduring substitute or silently choose one with different behavior.
4. For tool restrictions, approval modes, turn limits and execution context, verify a supported equivalent. Do not strip them to make the file parse. `skills.config` enables or disables skills; it does not promise that their full instructions are preloaded.
5. Record each MCP server's owning plugin and transport definition. Do not fabricate configuration for a server owned by another plugin. Preserve the dependency and report how it must become available. Check whether inherited configuration suffices before duplicating it into an agent.
6. If an agent-local MCP definition is necessary, use a complete supported transport, with command/arguments or URL and appropriate environment/auth fields. Do not treat a server-name-only table as a pointer to another plugin's definition. Verify the target's merge behavior.
7. Resolve agent-relative paths according to the role's loading context. Native plugin-relative `cwd` behavior does not automatically apply to an agent config layer. Avoid committing machine-specific cache paths. If the deployment path is unknown, record the installation-time binding as pending; do not label a package with an unresolved required MCP dependency ready to run.
8. Parse TOML and validate against the target's actual config loader/schema. Check internal references, registration and one representative delegation workflow separately.

Evidence: [role configuration fields](https://learn.chatgpt.com/docs/config-file/config-reference), [role file parser, 0.154.0-alpha.1](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/agent-roles/src/agent_role_config.rs). Reverify for another target version; do not assume this file format is accepted by every agent installation route.

## MCP configuration and credentials

Inspect native plugin configuration separately from standalone import. Preserve command, argument ordering, transport, endpoint, scopes, header names, optionality and enabled state unless a reviewed change requires otherwise.

- **Working directory:** for a local native plugin with relative helper arguments, explicitly set `cwd` to the required plugin-relative directory, such as `.` or `servers`, on targets with verified support. The pinned native loader resolves an explicitly supplied relative `cwd` against the plugin root. Do not assume the launch directory when it is unset. Check packaged helper paths, executability and dependencies without running them during the audit.
- **Path placeholders:** do not assume `${PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_ROOT}` or a shell expression expands in JSON fields. Verify the parser for that field. Where plugin-relative `cwd` is supported, relative helper arguments may be an appropriate replacement. Hook environment behavior is a separate question.
- **Literal values:** preserve nonsecret literal configuration where accepted. Never copy configured credentials into generated packages, plans or reports.
- **Host-supplied environment:** supported stdio `env_vars` entries pass named variables from the execution environment. For example, a source mapping `MCP_TOKEN` from `${user_config.access_token}` can become `env_vars: ["MCP_TOKEN"]` only with an explicit setup step that supplies `MCP_TOKEN` to the process launching the server. This does not create the variable or provide a configuration prompt. A source variable with a different name needs an explicit deployment mapping.
- **Local versus remote:** establish where the MCP process runs. A local environment export does not configure a remote executor. Use the customer's supported secret/configuration delivery mechanism; check support for environment source selection in the target version.
- **User inputs:** inventory `userConfig` fields and all consumers. Verify the chosen installation route's configuration UI before declaring prompts unsupported. If no equivalent prompt exists, record the destination setting, description, required/optional status, default behavior and owner in setup tasks. Omit actual values and secret defaults. Do not make optional inputs mandatory.
- **HTTP and OAuth:** do not put stdio `env_vars` into an HTTP server as a substitute for supported header/token/OAuth configuration. Preserve scopes and provider identity. Successful parsing does not test login or refresh-token rotation.

Evidence: [MCP config fields](https://learn.chatgpt.com/docs/config-file/config-reference), [native plugin loader, 0.154.0-alpha.1](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/codex-mcp/src/plugin_config.rs).

## Hooks

Keep event timing, blocking behavior, matchers, payloads and output semantics explicit. An importer gap is not proof that native hooks lack the feature. A failure hook must not be silently renamed to a success hook. For blocking behavior, first check whether the target already supports an equivalent; ask for a decision only when a real semantic choice remains. Test that a prohibited action is actually prevented. Preserve native asynchronous behavior where supported; test lifecycle exceptions and do not convert to synchronous execution silently.

Read [scope and rules](scope-and-rules.md) and [validation](validation.md) for the existing hook-specific evidence and checks.
