# File accounting and remaining setup

The scanner emits `file_accounting` in audit JSON and a file-coverage table in Markdown. It lists each inventoried file plus skipped paths. Excluded directory contents and files beyond scan limits are not enumerated. Expand relevant coverage before claiming every source file was reviewed. An inaccessible linked repository remains outside coverage.

The automatic scan status is `needs_review`, `no_matches` or `not_checked`. It never means the file works unchanged. `disposition` and `setup_status` start as `not_assessed`. A listed hash proves inventory, not review.

## Complete the conversion report

Keep the original audit immutable. Write `CONVERSION-SUMMARY.md` outside the audited tree, under a new per-run report directory. Update that report as the selected migration progresses. Retain older run reports without appending repeated full tables into one growing document.

Include:

- Source repository/revision, target version, installation route and output mode for each plugin.
- Counts by artifact type and disposition, reconciled with the source inventory. Show excluded paths and linked repositories separately.
- A row for every inventoried source file, including unchanged supporting files, with plugin, source path/hash, target path(s), disposition, related migration IDs, rationale and validation.
- A separate list of newly generated files with their source inputs and purpose.
- Dependency references: consumer, owning plugin, source reference, target reference/configuration, resolution and setup task. Do not expose credentials, sensitive URLs or secret defaults.
- User decisions with the plugin/item scope to which each applies.

Use these dispositions only with corresponding evidence:

| Disposition | Meaning |
| --- | --- |
| `unchanged` | Reviewed; no source edit needed for the stated target. Runtime status is separate. |
| `copied` | Copied to generated output and content hash checked. |
| `modified` | Reviewed change applied and checked against the receipt. |
| `proposed` | Intended change is known but not applied. |
| `not_selected` | Outside the user's migration selection. |
| `not_applicable` | Confirmed inactive or outside the selected target. Explain why. |
| `blocked` | Required conversion cannot safely proceed; state the missing decision or information. |
| `not_checked` | Meaning or behavior has not been reviewed. |

A blocked component can coexist with converted independent files. Do not describe an incomplete plugin as ready to install. Unsupported behavior stays visible as a blocker or decision; it must not disappear from the report.

## Setup and validation

Keep setup separate from source disposition. Mark it `not_required`, `pending`, `complete` or `not_assessed`, with evidence. Derive `SETUP.md` from pending tasks only when tasks exist. For each task include plugin, affected component, action, destination environment, owner if known, and verification step. List variable names and required/optional status, never values.

Examples include supplying a required environment variable, binding a deployment-relative path, registering a separately distributed agent, or selecting a marketplace source. Inspecting readiness is separate from conversion and can proceed when authorized; conversion must not activate credentials or production hooks just to complete the report.

Report these results independently: structural checks, source preservation, package completeness, marketplace registration, installation, authentication, Codex workflow, Claude workflow. Use `not_run` when a check did not run. A dependency declaration is not proof of installed access, and unchanged Claude files are not a Claude runtime test.
