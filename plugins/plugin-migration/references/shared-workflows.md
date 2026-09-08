# Shared workflows

Choose the smallest change that preserves the intended workflow.

- Keep ordinary instructions, scripts and resources shared when portable.
- Use capability-based instructions when the difference is the available discovery interface.
- Use separate client references when schemas or behavior differ substantially.
- Generate one entry per client when packaging or import transformations require it. Distribute only the intended entry in each package. Two generated outputs can share one maintained source.

## Candidate discovery instructions

This pattern needs testing in the target clients:

1. If the required tool is already exposed, use its exact name and arguments.
2. Otherwise, use the discovery interface advertised in the session and follow its schema. Search for the required service and operation. Distinguish test and production providers using their actual connection identity.
3. Use exact selection only when the interface supports it and the exact identifier is already advertised. Otherwise use supported discovery without guessing names.
4. Use the matching tool returned. Refine an empty query using available metadata. Report an unresolved discovery or connection problem if it remains unavailable; an empty result alone does not establish an authentication failure.

The reviewed Codex interface accepts a query string. Provider-specific queries depend on the observed namespace and should not be copied into another organization's skills without checking its actual tools. Claude Code exposes its own ToolSearch when deferred discovery is enabled. Check the actual interface before prescribing syntax. [Codex schema](https://github.com/openai/codex/blob/042534ec1ab2f79c2997e779347d5383832ecb2e/codex-rs/core/src/tools/handlers/tool_search_spec.rs), [Claude tools](https://code.claude.com/docs/en/tools-reference).

Capability-based branching avoids dependence on product headings. It cannot restore a connection or hook omitted during installation. Compare installed content and test the same workflow in each client.
