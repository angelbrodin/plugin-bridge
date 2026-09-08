#!/usr/bin/env python3
"""Read-only, source-scoped migration review. Does not load or execute plugins."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

PINNED_VERSION = "0.154.0-alpha.1"
COMMIT = "042534ec1ab2f79c2997e779347d5383832ecb2e"
SOURCE = "https://github.com/openai/codex/blob/" + COMMIT + "/codex-rs/"
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILES = 10000
EXCLUDED = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".cache", ".next", ".pytest_cache"}
EVENTS = {"PreToolUse", "PermissionRequest", "PostToolUse", "PreCompact", "PostCompact", "SessionStart", "SessionEnd", "UserPromptSubmit", "SubagentStart", "SubagentStop", "Stop", "Interrupt"}
HOOK_FIELDS = {"type", "command", "timeout", "timeoutSec", "statusMessage", "async"}
UNCHECKED = [
    "Authentication, token refresh, server startup and tool discovery were not run.",
    "Hook execution, permissions and end-to-end workflows in either client were not tested.",
    "Installed files, importer selection, configuration precedence and remote marketplace dependencies were not resolved.",
    "Frontmatter policy, native TOML/YAML semantics, agent conversion and arbitrary scripts need manual review.",
    "Native plugin MCP/hook rules and custom command paths selected through manifests were not evaluated.",
    "Project-scoped records in .claude.json and user-level external configuration were not resolved.",
    "Skill prose checks are candidates; conditional branches require contextual review.",
    "No finding does not establish compatibility; only listed checks were performed.",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def scalar(value):
    if value is None or isinstance(value, (dict, list)):
        return None
    return value if isinstance(value, str) else json.dumps(value)


def strings(value):
    return [s for s in (scalar(v) for v in (value if isinstance(value, list) else [value])) if s is not None]


def env_name(value):
    if not (value.startswith("${") and value.endswith("}")):
        return None
    name = value[2:-1].split(":-", 1)[0]
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) else None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def parse_json(text):
    """Use the standard JSON parser; separately index token locations, without snippets."""
    value = json.loads(text, object_pairs_hook=unique_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-JSON number")))
    decoder, positions = json.JSONDecoder(), {}

    def ws(i):
        while i < len(text) and text[i].isspace():
            i += 1
        return i

    def visit(i, path):
        i = ws(i)
        positions[path] = text.count("\n", 0, i) + 1
        if text[i] == "{":
            i = ws(i + 1)
            while text[i] != "}":
                key, end = decoder.raw_decode(text, i)
                i = visit(ws(end) + 1, path + (key,))
                i = ws(i)
                if text[i] == ",":
                    i = ws(i + 1)
                else:
                    break
            return i + 1
        if text[i] == "[":
            i, index = ws(i + 1), 0
            while text[i] != "]":
                i = ws(visit(i, path + (index,)))
                index += 1
                if text[i] == ",":
                    i = ws(i + 1)
                else:
                    break
            return i + 1
        return decoder.raw_decode(text, i)[1]

    visit(0, ())
    return value, positions


class Auditor:
    def __init__(self, root, version, route):
        self.root = Path(root).resolve()
        self.version = version.removeprefix("rust-v")
        self.route = route
        self.findings, self.inventory, self.skipped = [], [], []
        self.checked, self.configs = [], {}
        self.raw, self.path, self.sha, self.locations = "", "", "", {}

    def status(self, eligible=True):
        return "confirmed_import_gap" if self.version == PINNED_VERSION and self.route == "standalone-import" and eligible else "review_required"

    def add(self, rule, title, reason, recommendation, source, node=(), line=None,
            status=None, eligible=True):
        line = line or self.locations.get(node, 1)
        scope = {"scope_kind": "standalone-import", "verified_version": PINNED_VERSION,
                 "verified_install_path": "standalone-import",
                 "target_version_verified": self.version == PINNED_VERSION,
                 "install_path_matches": None if self.route in {"unknown", "github-sync"} else self.route == "standalone-import",
                 "recognized_import_file": eligible}
        if rule in {"SKILL001", "SKILL002"}:
            scope.update(scope_kind="runtime-tool-interface", verified_install_path=None,
                         install_path_matches=None, recognized_import_file=None)
        elif rule == "CONFIG001":
            scope.update(scope_kind="json-syntax", verified_version=None,
                         target_version_verified=None, verified_install_path=None,
                         install_path_matches=None, recognized_import_file=None)
        elif rule.startswith("CMD"):
            scope.update(scope_kind="command-conversion-path-dependent", verified_install_path=None,
                         verified_conversion_paths=["standalone-import", "legacy-plugin-command-conversion"],
                         install_path_matches=True if self.route == "standalone-import" and eligible else None)
        status = status or self.status(eligible)
        if self.route == "plugin-install" and rule.startswith(("MCP", "HOOK")) and status != "not_applicable":
            status = "not_applicable"
            recommendation = "This rule describes standalone import. No change is recommended from this match; validate native plugin configuration separately with route-specific checks."
        if status == "review_required" and rule.startswith(("MCP", "HOOK", "CMD")):
            reason += " This is a candidate for the selected profile; confirm the installation path and target implementation before changing it."
        # The locator is hashed: MCP names, header values and commands never enter reports.
        stable = digest(json.dumps([rule, self.path, node, line], sort_keys=True).encode())[:16]
        self.findings.append({"id": rule + "-" + stable, "rule_id": rule, "path": self.path,
            "line": line, "status": status, "title": title, "reason": reason,
            "recommendation": recommendation, "sources": [source], "applicability": scope,
            "fingerprint": digest((rule + self.path + self.sha + stable).encode())})

    def skip(self, path, reason):
        self.skipped.append({"path": str(path), "reason": reason})

    def collect(self):
        total, considered = 0, 0
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            for name in sorted(list(dirs)):
                item = Path(directory) / name
                rel = item.relative_to(self.root).as_posix()
                if name in EXCLUDED or item.is_symlink():
                    dirs.remove(name)
                    self.skip(rel, "excluded directory" if name in EXCLUDED else "symlink not followed")
            dirs.sort()
            for name in sorted(files):
                item = Path(directory) / name
                rel = item.relative_to(self.root).as_posix()
                if considered >= MAX_FILES:
                    self.skip(rel, "file count limit reached; remaining files not enumerated")
                    return
                considered += 1
                if item.is_symlink():
                    self.skip(rel, "symlink not followed")
                    continue
                try:
                    metadata = item.stat()
                    if not stat.S_ISREG(metadata.st_mode):
                        self.skip(rel, "non-regular file not read")
                        continue
                    size = metadata.st_size
                    if size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
                        self.skip(rel, "file or total byte limit exceeded")
                        continue
                    with item.open("rb") as stream:
                        data = stream.read(MAX_FILE_BYTES + 1)
                    if len(data) > MAX_FILE_BYTES:
                        self.skip(rel, "file grew beyond byte limit")
                        continue
                except OSError:
                    self.skip(rel, "unreadable file")
                    continue
                total += len(data)
                self.inventory.append({"path": rel, "sha256": digest(data), "size": len(data)})
                if item.suffix.lower() not in {".json", ".md"}:
                    continue
                try:
                    text = data.decode("utf-8-sig")
                except UnicodeDecodeError:
                    self.skip(rel, "text is not UTF-8")
                    continue
                if "\x00" in text:
                    self.skip(rel, "binary content")
                    continue
                yield rel, text, digest(data)

    def mcp(self, data):
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            return
        source = SOURCE + "external-agent-migration/src/mcp.rs"
        eligible = self.path in {".mcp.json", ".claude.json"}
        settings = self.configs.get(str(Path(self.path).parent / ".claude" / "settings.json"), {})
        # Local settings override the explicit enable/disable list when present.
        settings = dict(settings) if isinstance(settings, dict) else {}
        local = self.configs.get(str(Path(self.path).parent / ".claude" / "settings.local.json"), {})
        if isinstance(local, dict):
            settings.update(local)
        enabled = strings(settings.get("enabledMcpjsonServers"))
        disabled = strings(settings.get("disabledMcpjsonServers"))
        for name, server in servers.items():
            overrides = self.configs.get(".claude.json", {})
            overrides = overrides.get("mcpServers", {}) if isinstance(overrides, dict) else {}
            if (self.route == "standalone-import" and self.path == ".mcp.json"
                    and isinstance(overrides, dict) and name in overrides):
                continue
            node = ("mcpServers", name)
            if not isinstance(server, dict):
                self.add("MCP005", "Invalid MCP server record", "An MCP server record is not an object.", "Correct the record and re-run the audit.", source, node, eligible=eligible)
                continue
            if server.get("enabled") is False or server.get("disabled") is True or name in disabled or (enabled and name not in enabled):
                self.add("MCP004", "MCP connection is disabled or excluded", "The source configuration disables or excludes this connection. This is not a compatibility defect.", "Preserve the setting unless the owner explicitly requests activation.", source, node, status="not_applicable", eligible=eligible)
                continue
            command, url = scalar(server.get("command")), scalar(server.get("url"))
            field = "command" if command is not None else "url"
            endpoint = command if command is not None else url
            if endpoint is None:
                self.add("MCP005", "No convertible MCP command or URL", "The record has neither a scalar command nor a scalar URL accepted by the reviewed importer.", "Obtain the intended command or endpoint; do not invent it.", source, node, eligible=eligible)
                continue
            transport = server.get("type")
            allowed = {"stdio"} if field == "command" else {"http", "streamable_http"}
            if isinstance(transport, str) and transport not in allowed:
                self.add("MCP002", "Transport declaration cannot be converted", "The declared transport does not match the command or URL conversion supported by the reviewed importer.", "Check the provider's supported transport and configure an equivalent endpoint. Renaming the transport alone is insufficient.", source, node + ("type",), eligible=eligible)
            for subfield in [field] + (["args"] if field == "command" else []):
                if any("${" in v for v in strings(server.get(subfield))):
                    self.add("MCP001", "MCP endpoint or arguments contain a placeholder", "The reviewed importer skips a server with an environment placeholder in its " + subfield + " field.", "Prepare supported native configuration with the intended endpoint or command; keep credentials in the approved secret mechanism.", source, node + (subfield,), eligible=eligible)
            map_name = "env" if field == "command" else "headers"
            values = server.get(map_name, {})
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                value = scalar(value) if scalar(value) is not None else json.dumps(value)
                name = env_name(value)
                permitted = name == key if map_name == "env" else name is not None
                if map_name == "headers" and key.lower() == "authorization" and value.startswith("Bearer "):
                    permitted = permitted or env_name(value[7:]) is not None
                if "${" in value and not permitted:
                    self.add("MCP003", "MCP environment or header substitution cannot be converted", "The reviewed importer skips this server because a " + map_name + " value uses unsupported substitution or aliasing.", "Translate the setting into an equivalent native configuration and verify authentication without exposing the value.", source, node + (map_name, key), eligible=eligible)
                elif permitted and ":-" in value:
                    self.add("MCP006", "Environment placeholder fallback is not retained", "The reviewed converter extracts the variable name but does not retain its fallback value.", "Check whether the fallback is required and preserve its intended behavior in deployment settings.", source, node + (map_name, key), status="review_required", eligible=eligible)

    def hooks(self, data):
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return
        source = SOURCE + "external-agent-migration/src/hooks_cla.rs"
        path = Path(self.path)
        settings_name = path.name in {"settings.json", "settings.local.json"}
        eligible = settings_name and (str(path.parent) == ".claude" or
                                     (str(path.parent) == "." and self.root.name == ".claude"))
        disabled = data.get("disableAllHooks")
        if settings_name:
            disabled = None
            for name in ["settings.json", "settings.local.json"]:
                setting = self.configs.get(str(path.parent / name), {})
                value = setting.get("disableAllHooks") if isinstance(setting, dict) else None
                if isinstance(value, bool):
                    disabled = value
        if disabled is True:
            self.add("HOOK005", "Hooks are disabled", "The source settings explicitly disable all hooks. This is not a compatibility defect.", "Preserve the setting unless the owner requests activation.", source, ("hooks",), status="not_applicable", eligible=eligible)
            return
        for event, groups in hooks.items():
            node = ("hooks", event)
            if event not in EVENTS:
                self.add("HOOK004", "Hook event is outside the reviewed import set", "The reviewed importer does not select this event name.", "Map the intended trigger to a supported event only if its timing and behavior are equivalent.", source, node, eligible=eligible)
                continue
            if not isinstance(groups, list):
                self.add("HOOK005", "Hook groups have an invalid structure", "The reviewed importer expects an array of hook groups for this event.", "Review the hook structure before migration.", source, node, eligible=eligible)
                continue
            for gi, group in enumerate(groups):
                group_node = node + (gi,)
                if not isinstance(group, dict):
                    self.add("HOOK005", "Hook group is not an object", "The reviewed importer skips a non-object hook group.", "Review the hook structure.", source, group_node, eligible=eligible)
                    continue
                if set(group) - {"matcher", "hooks"}:
                    self.add("HOOK003", "Hook group contains fields outside the import subset", "The reviewed importer skips this whole group when additional group fields are present.", "Map the original conditions explicitly; do not delete behavior just to pass import.", source, group_node, eligible=eligible)
                handlers = group.get("hooks")
                if not isinstance(handlers, list):
                    self.add("HOOK005", "Hook handlers are missing or malformed", "The reviewed importer expects an array in the group's hooks field.", "Review the hook structure.", source, group_node, eligible=eligible)
                    continue
                for hi, handler in enumerate(handlers):
                    hn = group_node + ("hooks", hi)
                    if not isinstance(handler, dict):
                        self.add("HOOK005", "Hook handler is not an object", "The reviewed importer skips this handler.", "Review the hook structure.", source, hn, eligible=eligible)
                        continue
                    if isinstance(handler.get("type"), str) and handler["type"] != "command":
                        self.add("HOOK002", "Hook handler type is outside the command importer", "This converter imports command handlers only; this is not a statement about every native Codex hook type.", "Check native support and preserve the hook's behavior and permission requirements.", source, hn + ("type",), eligible=eligible)
                    if handler.get("async") is True:
                        recommendation = "Configure and test an equivalent asynchronous command hook in Codex; do not remove async to silence this finding."
                        if event == "SessionEnd":
                            recommendation = "Native Codex SessionEnd hooks run synchronously. Review the trigger and intended lifecycle; do not promise equivalent background behavior."
                        self.add("HOOK001", "Async hook requires a separate import treatment", "Codex supports asynchronous command hooks. The reviewed standalone importer skips handlers with async: true.", recommendation, source, hn + ("async",), eligible=eligible)
                    if set(handler) - HOOK_FIELDS:
                        self.add("HOOK003", "Hook handler contains fields outside the import subset", "The reviewed standalone importer skips a handler with additional fields.", "Review each setting and preserve its effect in native configuration or flag the missing equivalent.", source, hn, eligible=eligible)
                    if not isinstance(handler.get("command"), str) or not handler["command"].strip():
                        if handler.get("type", "command") == "command":
                            self.add("HOOK005", "Command hook has no usable command", "The reviewed importer requires a non-empty command string.", "Provide the intended command; do not execute it during the audit.", source, hn, eligible=eligible)

    def skill(self):
        source = SOURCE + "core/src/tools/handlers/tool_search_spec.rs"
        stack, lines = [], self.raw.splitlines()
        dual = bool(re.search(r"(?im)^#{1,6}\s+.*\bClaude\b", self.raw) and re.search(r"(?im)^#{1,6}\s+.*\bCodex\b", self.raw))
        if dual and (self.route != "plugin-install" or self.version != PINNED_VERSION):
            self.add("SKILL003", "Client labels may change during standalone skill import", "This SKILL.md has headings for both clients. The reviewed standalone importer rewrites whole-word Claude references; check whether the resulting branches become ambiguous.", "Compare source and installed instructions, or use capability-based branches with verified runtime behavior.", SOURCE + "external-agent-migration/src/utils.rs", status="review_required")
        fenced = False
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
            match = re.match(r"^(#{1,6})\s+(.*)", line) if not fenced else None
            if match:
                level, title = len(match[1]), match[2]
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
            headings = next((title for _, title in reversed(stack)
                             if re.search(r"\b(?:Claude|Codex)\b", title, re.I)), "")
            claude_only = bool(re.search(r"\bClaude\b", headings, re.I)) and not re.search(r"\bCodex\b", headings, re.I)
            status = "not_applicable" if claude_only and self.route == "plugin-install" and self.version == PINNED_VERSION else "review_required"
            context = " The occurrence is inside an explicitly Claude-labeled section; this alone is not a Codex incompatibility." if claude_only else " Its meaning and execution context need review; a text match alone does not prove failure."
            if re.search(r"\bselect:", line):
                self.add("SKILL001", "Review select-style discovery syntax", "The reviewed Codex tool_search interface does not implement Claude's select query syntax." + context, "Choose the discovery interface present in the session, follow its schema, and test the same workflow in both clients.", source, line=number, status=status)
            if re.search(r"mcp__[A-Za-z0-9_]*-[A-Za-z0-9_-]*", line):
                self.add("SKILL002", "Review a hard-coded hyphenated MCP callable name", "Codex normalizes exposed callable identifiers, so a source connection label is not a reliable callable name." + context, "Use the name and argument schema actually exposed by tool discovery; do not rename connection IDs globally.", SOURCE + "codex-mcp/src/mcp/mod.rs", line=number, status=status)

    def commands(self):
        normalized = self.raw.replace("\r\n", "\n")
        text = normalized
        # The importer checks the Markdown body after YAML frontmatter.
        offset = 0
        if text.startswith("---\n"):
            end = re.search(r"(?m)^---\s*$", text[4:])
            if end:
                offset = 4 + end.end()
                text = text[offset:]
        match = re.search(r"\$ARGUMENTS|\$[0-9]|! ?`|(?<!\S)@\S+", text)
        if match or ("{{" in text and "}}" in text):
            line = normalized.count("\n", 0, offset + (match.start() if match else text.index("{{"))) + 1
            eligible = self.path.startswith(".claude/commands/") or (self.root.name == ".claude" and self.path.startswith("commands/"))
            self.add("CMD001", "Legacy command template needs conversion review", "The reviewed command converter excludes argument interpolation, shell preprocessing, paired braces and at-sign tokens. Which commands reach this converter depends on the installation path.", "Convert the intended behavior explicitly, preserving argument handling; verify the converter applies before declaring a skipped command.", SOURCE + "core-plugins/src/command_migration.rs", line=line, eligible=eligible)
        if len(text.strip().encode("utf-8")) > 4000:
            self.add("CMD002", "Command body exceeds the legacy plugin conversion size limit",
                     "The command body alone exceeds 4,000 UTF-8 bytes. The reviewed legacy plugin converter skips generated skills over 4,000 bytes, including its added wrapper. This limit does not apply to standalone command import.",
                     "Use a native skill entry with referenced workflow material, or review a deliberate split without dropping required behavior. Confirm this command is selected by the legacy plugin route.",
                     SOURCE + "core-plugins/src/command_migration/plugin.rs",
                     line=normalized.count("\n", 0, offset) + 1,
                     status="not_applicable" if self.route == "standalone-import" else "review_required",
                     eligible=False)
            self.findings[-1]["applicability"].update(
                verified_conversion_paths=["legacy-plugin-command-conversion"],
                install_path_matches=False if self.route == "standalone-import" else None)

    def run(self):
        if not self.root.is_dir():
            raise ValueError("repository path is not a directory")
        files = list(self.collect())
        parsed = {}
        for path, raw, sha in files:
            if path.endswith(".json"):
                try:
                    parsed[path] = parse_json(raw)
                    self.configs[path] = parsed[path][0]
                except (ValueError, RecursionError) as error:
                    self.path, self.raw, self.sha, self.locations = path, raw, sha, {}
                    self.skip(path, "invalid, ambiguous or excessively nested JSON; content not checked")
                    self.add("CONFIG001", "JSON configuration requires review", "This file could not be parsed unambiguously. Other files were still scanned; no invalid content was copied into the report.", "Correct the JSON structure and re-run the audit.", "https://www.rfc-editor.org/rfc/rfc8259", line=getattr(error, "lineno", 1), status="review_required")
        for path, raw, sha in files:
            self.path, self.raw, self.sha, self.locations = path, raw, sha, {}
            if path in parsed and isinstance(parsed[path][0], dict):
                data, self.locations = parsed[path]
                if Path(path).name == ".mcp.json" and "mcpServers" not in data:
                    self.skip(path, "unwrapped MCP configuration was inventoried but not evaluated by standalone MCP rules; native plugin configuration requires review")
                if "mcpServers" in data or "hooks" in data:
                    self.checked.append(path)
                    self.mcp(data)
                    self.hooks(data)
            elif Path(path).name.lower() == "skill.md":
                self.checked.append(path)
                self.skill()
            elif Path(path).suffix == ".md" and Path(path).stem != "README" and "commands" in Path(path).parts:
                self.checked.append(path)
                self.commands()
        for path, (data, _) in parsed.items():
            manifest = Path(path)
            if (manifest.name == "plugin.json" and manifest.parent.name in {".claude-plugin", ".codex-plugin"}
                    and isinstance(data, dict) and "commands" in data):
                declarations = data["commands"] if isinstance(data["commands"], list) else [data["commands"]]
                for declared in declarations:
                    if not isinstance(declared, str):
                        self.skip(path, "non-string command manifest declaration was not resolved")
                        continue
                    named = os.path.normpath(str(manifest.parent.parent / declared))
                    if not any(checked == named or checked.startswith(named.rstrip("/") + "/") for checked in self.checked):
                        self.skip(named, "manifest-selected command path was not inspected; custom command path resolution requires review")
        try:
            result = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--verify", "HEAD"], capture_output=True, text=True, timeout=5, check=False)
            revision = result.stdout.strip() if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", result.stdout.strip()) else None
        except (OSError, subprocess.TimeoutExpired):
            revision = None
        return {"schema_version": 1, "profile": {"target_version": self.version, "install_path": self.route, "preserve_claude": True, "rules_verified_version": PINNED_VERSION},
                "repository": {"root": str(self.root), "revision": revision}, "inventory": self.inventory,
                "findings": sorted(self.findings, key=lambda f: (f["path"], f["line"], f["rule_id"])),
                "coverage": {"checked_files": sorted(set(self.checked)), "skipped": self.skipped,
                             "unchecked_areas": UNCHECKED, "limits": {"file_bytes": MAX_FILE_BYTES, "total_bytes": MAX_TOTAL_BYTES, "files": MAX_FILES}},
                "runtime_validation": "not_run"}


def build_inventory(root):
    """Return the same bounded inventory as an audit, without rule evaluation."""
    auditor = Auditor(root, "unknown", "unknown")
    if not auditor.root.is_dir():
        raise ValueError("repository path is not a directory")
    for _ in auditor.collect():
        pass
    return auditor.inventory


def markdown(report):
    lines = ["# Plugin migration repository review", "", "Target: " + report["profile"]["target_version"] + "; installation: " + report["profile"]["install_path"], "", "Runtime validation: not run. This report does not certify compatibility.", ""]
    for finding in report["findings"]:
        lines += ["## " + finding["rule_id"] + ": " + finding["title"], "", "Finding ID: `" + finding["id"].replace("`", "") + "`", "", "Location: `" + finding["path"].replace("`", "") + ":" + str(finding["line"]) + "`", "", "Status: " + finding["status"], "", finding["reason"], "", finding["recommendation"], "", "Source: " + finding["sources"][0], ""]
    if not report["findings"]:
        lines += ["No matches for the implemented rules. Unchecked areas still require review.", ""]
    lines += ["## Coverage limits", ""] + ["- " + s for s in report["coverage"]["unchecked_areas"]]
    lines += ["", "Skipped paths: " + str(len(report["coverage"]["skipped"])) + ". See JSON for details.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--install-path", choices=["standalone-import", "plugin-install", "github-sync", "unknown"], required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)
    try:
        root = Path(args.repo).resolve()
        destinations = [path for path in [args.json_out, args.markdown_out] if path is not None]
        if len({path.resolve() for path in destinations}) != len(destinations):
            raise ValueError("JSON and Markdown outputs must use different paths")
        for destination in [args.json_out, args.markdown_out]:
            if destination is not None:
                if destination.exists() or destination.is_symlink():
                    raise ValueError("report output already exists; choose a new path")
                resolved = destination.resolve()
                if resolved == root or root in resolved.parents:
                    raise ValueError("report outputs must be outside the scanned repository")
        report = Auditor(root, args.target_version, args.install_path).run()
        encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.json_out:
            with args.json_out.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        else:
            sys.stdout.write(encoded)
        if args.markdown_out:
            with args.markdown_out.open("x", encoding="utf-8") as stream:
                stream.write(markdown(report))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
