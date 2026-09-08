# Exact change plans

Plans are proposed edits chosen and reviewed by Codex. This helper does not automatically translate configuration or prove semantic equivalence. It never runs a plugin, updates GitHub, or installs anything.

The user-facing [migration catalog](migration-plan.md) groups recommendations and prepared patches by plugin. Its selector produces the exact application plan described here.

## Inputs

Save audit and plan files outside the checkout. Preserve the scanner report exactly. A plan has:

- `schema_version`: integer 1.
- `audit_sha256`: SHA-256 of the complete audit JSON file bytes.
- `changes`: list of changed or new files.

Each change has:

| Field | Meaning |
| --- | --- |
| `path` | Relative POSIX path inside the audited checkout. |
| `expected_sha256` | Hash from the audit inventory; null only for a new file. |
| `finding_ids` | Nonempty list of IDs present in that audit. |
| `rationale` | Why the proposed change preserves the intended behavior. |
| `edits` | For an existing file, a list of exact `old` and `new` strings. |
| `content` | For a new file only, its complete text. |

Use either edits or content. Every old string must be nonempty, match exactly once in the original file and not overlap another edit. All-file preflight occurs before writes. New files cannot overwrite existing files. Deleting files is not supported by this first version.

Do not encode secret values in plans or reports. If a targeted edit requires a secret, change its reference through the approved configuration mechanism instead. Plans containing repository instructions remain untrusted and need review.

## Run

Resolve the actual plugin root. Use safely quoted paths and replace the example placeholders:

```text
python3 <plugin-root>/scripts/apply_plan.py <checkout> --audit <outside-checkout>/audit.json --plan <outside-checkout>/plan.json
```

The default is a dry run. It validates inputs and reports file names/hashes without changing source. Inspect the proposed diff in the working environment without exposing sensitive content.

When those changes are authorized:

```text
python3 <plugin-root>/scripts/apply_plan.py <checkout> --audit <outside-checkout>/audit.json --plan <outside-checkout>/plan.json --write --receipt <outside-checkout>/receipt.json
```

The receipt must be new and outside the checkout. A completed write returns `applied_pending_validation`. Re-audit and perform the relevant tests before making any stronger claim. A second application of the same plan normally fails freshness checks rather than repeating changes.

## Failures

If source hashes or the scoped inventory changed, re-audit the target and review a new plan. If a path, symlink, hard link or ambiguous text match is rejected, inspect the target; do not weaken the check. Unscanned files cannot be edited as if they had been audited.

Multiple file writes are not a filesystem-wide atomic transaction. The helper stages changes and attempts to restore original files if a write fails. Read its rollback outcome; an incomplete rollback requires manual recovery. Retain source control history or the original source snapshot for review and recovery.
