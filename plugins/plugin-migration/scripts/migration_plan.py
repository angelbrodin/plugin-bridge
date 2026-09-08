#!/usr/bin/env python3
"""Render a reviewed migration catalog and select exact changes without applying them."""
import argparse
import copy
import json
from pathlib import Path
import re
import sys

from apply_plan import PlanError, _read_json, _safe_relative, _validate_report, sha256

STATES = {"proposed", "ready", "needs_decision", "applied", "verified", "not_inspected"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def require(condition, message):
    if not condition:
        raise PlanError(message)


def validate(catalog, report, audit_bytes):
    require(catalog.get("schema_version") == 1, "Unsupported migration catalog schema.")
    require(catalog.get("audit_sha256") == sha256(audit_bytes), "Catalog does not match the audit; refresh the plan.")
    _, findings = _validate_report(report, Path(report.get("repository", {}).get("root", "")))
    plugins, items = {}, {}
    require(isinstance(catalog.get("plugins"), list), "Catalog must list plugins.")
    for plugin in catalog["plugins"]:
        require(isinstance(plugin, dict), "Invalid plugin entry.")
        key = plugin.get("id")
        require(isinstance(key, str) and ID.fullmatch(key) and key not in plugins, "Plugin IDs must be unique and stable.")
        require(isinstance(plugin.get("name"), str) and plugin["name"].strip(), "Every plugin needs a display name.")
        if plugin.get("path") not in {None, "."}:
            _safe_relative(plugin["path"])
        plugins[key] = plugin
    require(isinstance(catalog.get("items"), list), "Catalog must list migration items.")
    for item in catalog["items"]:
        require(isinstance(item, dict), "Invalid migration item.")
        key = item.get("id")
        require(isinstance(key, str) and ID.fullmatch(key) and key not in items, "Migration item IDs must be unique.")
        require(item.get("plugin_id") in plugins, "Item has an unknown owning plugin.")
        require(item.get("status") in STATES, "Unknown migration item status.")
        for field in ("title", "problem", "solution", "claude_impact", "next_step"):
            require(isinstance(item.get(field), str) and item[field].strip(), "Each item needs " + field + ".")
        if item.get("diff_path"):
            _safe_relative(item["diff_path"])
        affected = item.get("affected_plugin_ids", [item["plugin_id"]])
        require(isinstance(affected, list) and affected and all(isinstance(x, str) and x in plugins for x in affected)
                and item["plugin_id"] in affected, "Affected plugins must include the owner and reference known IDs.")
        dependencies = item.get("depends_on", [])
        require(isinstance(dependencies, list) and all(isinstance(x, str) for x in dependencies), "Dependencies must be item IDs.")
        changes = item.get("changes", [])
        require(isinstance(changes, list), "Item changes must be a list.")
        if item["status"] == "ready":
            require(bool(changes), "A ready item must contain exact prepared changes.")
        for change in changes:
            require(isinstance(change, dict), "Invalid file change.")
            _safe_relative(change.get("path"))
            owners = [(len(p["path"]), pid) for pid, p in plugins.items() if p.get("path") is not None
                      and (p["path"] == "." or change["path"] == p["path"] or change["path"].startswith(p["path"] + "/"))]
            if owners:
                depth = max(size for size, _ in owners)
                require(all(pid in affected for size, pid in owners if size == depth), "File change affects a plugin missing from affected_plugin_ids.")
            refs = change.get("finding_ids")
            require(isinstance(refs, list) and refs and all(isinstance(x, str) and x in findings for x in refs), "Changes must reference actual audit findings.")
        items[key] = item
    for item in items.values():
        require(all(x in items and x != item["id"] for x in item.get("depends_on", [])), "Unknown or self-referencing dependency.")
    visited, active = set(), set()
    def visit(key):
        require(key not in active, "Migration dependencies contain a cycle.")
        if key in visited:
            return
        active.add(key)
        for dep in items[key].get("depends_on", []):
            visit(dep)
        active.remove(key)
        visited.add(key)
    for key in items:
        visit(key)
    return plugins, items


def resolve_plugins(values, plugins):
    resolved = set()
    for value in values:
        matches = [value] if value in plugins else [key for key, p in plugins.items() if p["name"].casefold() == value.casefold()]
        require(len(matches) == 1, "Plugin name is unknown or ambiguous; use its catalog ID: " + value)
        resolved.add(matches[0])
    return resolved


def select(catalog, report, audit_bytes, *, all_ready=False, plugin_names=(), item_ids=(), exclude_plugins=(), exclude_items=(), allow_shared=()):
    plugins, items = validate(catalog, report, audit_bytes)
    require(sum(bool(x) for x in (all_ready, plugin_names, item_ids)) == 1, "Choose all-ready, plugins, or item IDs.")
    require(all(x in items for x in list(item_ids) + list(exclude_items)), "Unknown migration item ID.")
    excluded_plugins = resolve_plugins(exclude_plugins, plugins)
    excluded_items = set(exclude_items)
    if all_ready:
        candidates = set(items)
        scope = set(plugins)
    elif plugin_names:
        scope = resolve_plugins(plugin_names, plugins)
        candidates = {key for key, item in items.items() if item["plugin_id"] in scope}
    else:
        candidates = set(item_ids)
        scope = {items[key]["plugin_id"] for key in candidates}
    candidates = {key for key in candidates if key not in excluded_items and items[key]["plugin_id"] not in excluded_plugins}
    # Explicitly selecting an unprepared change is an error, not a silent partial application.
    if item_ids:
        require(all(items[key]["status"] == "ready" for key in candidates), "A selected item is not ready; prepare or resolve it before applying.")
    selected = {key for key in candidates if items[key]["status"] == "ready"}
    require(bool(selected), "No ready items match this selection; no changes prepared.")
    allowed = (scope | resolve_plugins(allow_shared, plugins)) - excluded_plugins
    for key in selected:
        item = items[key]
        missing = set(item.get("depends_on", [])) - selected
        # Previously applied dependencies must be carried forward by contextual review in a fresh audit.
        missing = {dep for dep in missing if items[dep]["status"] not in {"applied", "verified"}}
        require(not missing, "Selection omits dependencies for " + key + ": " + ", ".join(sorted(missing)))
        outside = set(item.get("affected_plugin_ids", [item["plugin_id"]])) - allowed
        require(not outside, "Shared change " + key + " affects unselected plugins: " + ", ".join(sorted(outside)))
    merged = {}
    for key in sorted(selected):
        for raw in items[key]["changes"]:
            change = copy.deepcopy(raw)
            path = change["path"]
            if path not in merged:
                merged[path] = change
                continue
            existing = merged[path]
            require(existing.get("expected_sha256") == change.get("expected_sha256"), "Conflicting source hashes: " + path)
            if "content" in existing or "content" in change:
                require("content" in existing and "content" in change and existing["content"] == change["content"], "Conflicting file creation: " + path)
            else:
                require(isinstance(existing.get("edits"), list) and isinstance(change.get("edits"), list), "Missing exact edits: " + path)
                for edit in change["edits"]:
                    same = [e for e in existing["edits"] if e.get("old") == edit.get("old")]
                    require(not same or same[0] == edit, "Conflicting edits: " + path)
                    if not same:
                        existing["edits"].append(edit)
            existing["finding_ids"] = sorted(set(existing["finding_ids"] + change["finding_ids"]))
            existing["rationale"] = existing.get("rationale", "") + "\n" + change.get("rationale", "")
    return {"schema_version": 1, "audit_sha256": catalog["audit_sha256"],
            "selection": {"item_ids": sorted(selected), "plugin_ids": sorted({items[k]["plugin_id"] for k in selected}),
                          "omitted": [{"id": key, "status": item["status"], "reason": "not selected or excluded" if key not in candidates else "not ready"}
                                      for key, item in items.items() if key not in selected]},
            "changes": list(merged.values())}


def render(catalog, report, audit_bytes):
    plugins, items = validate(catalog, report, audit_bytes)
    profile = report["profile"]
    lines = ["# Migration plan", "", "Target: " + profile["target_version"] + "; installation: " + profile["install_path"] + ".", "",
             "Choose the whole ready plan, a plugin, or individual change IDs. Ready means an exact patch is prepared; it does not mean tested in either client.", ""]
    for plugin_id, plugin in plugins.items():
        lines += ["## " + plugin["name"], "", "Plugin ID: `" + plugin_id + "`", ""]
        owned = [item for item in items.values() if item["plugin_id"] == plugin_id]
        if not owned:
            lines += ["No migration items recorded. Review coverage before concluding that no changes are needed.", ""]
        for item in owned:
            lines += ["### " + item["id"] + ": " + item["title"], "", "Status: **" + item["status"] + "**", ""]
            for label, field in (("What needs attention", "problem"), ("Proposed change", "solution"), ("Claude impact", "claude_impact"), ("Next step", "next_step")):
                lines += ["**" + label + ":** " + item[field], ""]
            if item.get("changes"):
                lines += ["Files in the prepared patch:", ""]
                lines += ["- `" + c["path"] + "`" for c in item["changes"]]
                lines += [""]
            if item.get("diff_path"):
                lines += ["[Review the exact changes](" + item["diff_path"] + ")", ""]
            if item.get("depends_on"):
                lines += ["Required changes: " + ", ".join(item["depends_on"]), ""]
            affected = item.get("affected_plugin_ids", [plugin_id])
            if set(affected) != {plugin_id}:
                lines += ["Also affects: " + ", ".join(x for x in affected if x != plugin_id), ""]
    lines += ["## Continue", "", '- "Proceed with the migration plan."', '- "Apply changes for [plugin name] only."',
              '- "Apply M001 and M003; leave the other changes for later."', "",
              "Unprepared changes need review and exact patches before application. Unresolved decisions stay open. Installation and tests in each client are recorded separately.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["render", "select"])
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all-ready", action="store_true")
    group.add_argument("--plugin", action="append", default=[])
    group.add_argument("--item", action="append", default=[])
    parser.add_argument("--exclude-plugin", action="append", default=[])
    parser.add_argument("--exclude-item", action="append", default=[])
    parser.add_argument("--allow-shared", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        _, catalog = _read_json(args.catalog, "catalog")
        audit_bytes, report = _read_json(args.audit, "audit")
        root = Path(report.get("repository", {}).get("root", "")).resolve()
        output = args.out.resolve()
        require(output != root and root not in output.parents, "Write plan outputs outside the audited repository.")
        require(not args.out.is_symlink() and not args.out.exists(), "Output must be a new file.")
        value = render(catalog, report, audit_bytes) if args.action == "render" else json.dumps(select(
            catalog, report, audit_bytes, all_ready=args.all_ready, plugin_names=args.plugin, item_ids=args.item,
            exclude_plugins=args.exclude_plugin, exclude_items=args.exclude_item, allow_shared=args.allow_shared), indent=2) + "\n"
        with args.out.open("x", encoding="utf-8") as stream:
            stream.write(value)
        print("Created " + str(args.out) + "; repository unchanged.")
        return 0
    except (PlanError, OSError, ValueError, TypeError, KeyError) as error:
        print("Plan refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
