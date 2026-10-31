#!/usr/bin/env python3
"""Freeze a skill into an isolated project and record one host-smoke attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import tomllib
import re
from pathlib import Path

from runtime_common import claim_host, load_state, package_snapshot, sha256_file


def digest_tree(root: Path) -> tuple[str, list[dict]]:
    rows: list[dict] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rows.append({"path": str(path.relative_to(root)), "sha256": sha256_file(path)})
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), rows


def safe_relative(value: str) -> bool:
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def value(mapping: dict, *keys: str):
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def write_record(run_dir: Path, record: dict) -> Path:
    path = run_dir / "host" / "record.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def codex_mcp_names() -> list[str]:
    """Read only server names, never config values, for per-turn disable overrides."""
    config = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    if not config.is_file():
        return []
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    servers = data.get("mcp_servers", {})
    return sorted(name for name in servers if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)) if isinstance(servers, dict) else []


def host_command(host: str, project: Path, executable: str | None) -> tuple[list[str] | None, dict | None]:
    if executable:
        return [executable], {"mode": "mock", "host": host}
    if host == "codex":
        names = codex_mcp_names()
        command = ["codex", "exec", "--json", "--ephemeral", "--sandbox", "read-only", "--config", "features.hooks=false",
                   "--skip-git-repo-check", "--cd", str(project)]
        for name in names:
            command.extend(["--config", f"mcp_servers.{name}.enabled=false"])
        command.append("-")  # The one user request is stdin; skill content and paths are never injected.
        return command, {"mode": "codex-readonly", "mcp_servers_disabled": names}
    if host == "claude":
        # Skill is how Claude Code loads a named skill; project-only settings keep user skills/plugins out.
        tools = "Skill,Read,Glob,Grep"
        return ["claude", "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                "--setting-sources", "project", "--tools", tools, "--allowedTools", tools, "--permission-mode", "plan",
                "--permission-prompts", "none", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--settings", '{"disableAllHooks":true}'], {"mode": "claude-readonly", "tools": tools.split(","),
                                                             "setting_sources": ["project"]}
    if host in {"agy", "antigravity"}:
        return None, {"code": "capability-blocked", "message": "AGY CLI help exposes sandboxing but no least-tool read-only and MCP-isolation contract"}
    return None, {"code": "unsupported-host", "message": f"no safe adapter for host {host!r}"}


def json_events(stdout: str) -> list[dict]:
    """Accept the mock JSON array and Codex JSONL, retaining only object events."""
    try:
        item = json.loads(stdout)
        return [event for event in item if isinstance(event, dict)] if isinstance(item, list) else [item] if isinstance(item, dict) else []
    except json.JSONDecodeError:
        events: list[dict] = []
        for line in stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events


def persist_trace(run_dir: Path, raw: str, events: list[dict]) -> dict:
    raw_path = run_dir / "host" / "raw-trace.jsonl"
    path = run_dir / "host" / "trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw, encoding="utf-8")
    payload = {"events": events, "raw_trace_file": str(raw_path.relative_to(run_dir)), "raw_trace_sha256": sha256_file(raw_path)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"trace_file": str(path.relative_to(run_dir)), "trace_sha256": sha256_file(path),
            "raw_trace_file": str(raw_path.relative_to(run_dir)), "raw_trace_sha256": sha256_file(raw_path)}


def agy_conversation(events: list[dict]) -> str | None:
    initial = [event for event in events if event.get("event") == "init"]
    if len(initial) != 1:
        return None
    identifier = initial[0].get("conversation_id")
    return identifier if isinstance(identifier, str) and identifier else None


def normalized_events(host: str, raw_events: list[dict], project: Path) -> list[dict]:
    native_agy = host == "antigravity" and any("event" in event for event in raw_events)
    events = [] if native_agy else [event for event in raw_events if event.get("type") in {"read", "tool.read", "turn.completed"}]
    paths = {str(Path(event["path"]).resolve()) for event in events if event.get("type") in {"read", "tool.read"}
             and event.get("success") is True and isinstance(event.get("path"), str)}
    if host == "codex":
        paths.update(codex_read_paths(raw_events, project))
    elif host == "claude":
        paths.update(claude_read_paths(raw_events))
        paths.update(claude_skill_load_paths(raw_events, project))
    elif host == "antigravity":
        paths.update(agy_read_paths(raw_events))
    normalized = [{"type": "tool.read", "path": path, "success": True} for path in sorted(paths)]
    completed = not native_agy and any(event.get("type") == "turn.completed" for event in raw_events)
    if host == "claude" or (host == "antigravity" and not native_agy):
        completed = completed or any(event.get("type") == "result" and event.get("is_error") is False for event in raw_events)
    if native_agy:
        conversation = agy_conversation(raw_events)
        results = [event.get("result") for event in raw_events if event.get("event") == "result"]
        completed = (conversation is not None and len(results) == 1 and isinstance(results[0], dict)
                     and results[0].get("conversation_id") == conversation and results[0].get("status") == "SUCCESS")
    if completed:
        normalized.append({"type": "turn.completed"})
    return normalized


def completed_command_item(event: dict) -> dict | None:
    """Return only a completed, successful Codex command event."""
    if event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if not isinstance(item, dict) or item.get("type") != "command_execution":
        return None
    exit_code = item.get("exit_code")
    if item.get("status") != "completed" or not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0:
        return None
    return item


def command_segments(command: str) -> list[list[str]] | None:
    """Parse the narrow read-only shell subset without evaluating shell syntax."""
    if "\n" in command:
        return None
    try:
        outer = shlex.split(command, posix=True)
    except ValueError:
        return None
    if len(outer) == 3 and Path(outer[0]).name in {"sh", "bash", "zsh"} and outer[1] in {"-c", "-lc"}:
        script = outer[2]
    else:
        script = command
    if "\n" in script or any(token in script for token in ("$", "`")):
        return None
    try:
        lexer = shlex.shlex(script, posix=True, punctuation_chars=";|&<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == ";":
            if not segments[-1]:
                return None
            segments.append([])
        elif token in {"|", "||", "&", "&&", "<", "<<", ">", ">>"}:
            return None
        else:
            segments[-1].append(token)
    return segments if segments[-1] else None


def project_file(path_text: str, project: Path) -> Path | None:
    candidate = Path(path_text)
    candidate = candidate.resolve() if candidate.is_absolute() else (project / candidate).resolve()
    try:
        candidate.relative_to(project)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def cat_paths(segment: list[str], project: Path) -> list[tuple[Path, bool]] | None:
    if not segment or segment[0] != "cat" or len(segment) == 1 or any(arg.startswith("-") for arg in segment[1:]):
        return None
    paths: list[tuple[Path, bool]] = []
    for arg in segment[1:]:
        raw_path = Path(arg)
        if not raw_path.is_absolute() and ".." in raw_path.parts:
            return None
        requested = raw_path if raw_path.is_absolute() else project / raw_path
        resolved = requested.resolve()
        in_project = resolved.is_relative_to(project)
        if not resolved.is_file() or (requested.is_symlink() and not in_project):
            return None
        paths.append((resolved, in_project))
    return paths


def cat_bundle_paths(item: dict, segments: list[list[str]], project: Path) -> set[str]:
    """Credit a cat-only sequence only when its whole output is exact and ordered."""
    per_segment = [cat_paths(segment, project) for segment in segments]
    if any(paths is None for paths in per_segment):
        return set()
    paths = [entry for group in per_segment for entry in group if entry is not None]
    try:
        expected = b"".join(path.read_bytes() for path, _ in paths).decode("utf-8")
    except (OSError, UnicodeError):
        return set()
    if item.get("aggregated_output") != expected:
        return set()
    return {str(path) for path, in_project in paths if in_project}


def simple_read_paths(segment: list[str], project: Path) -> set[str]:
    """Retain the previous narrow sed/head/tail/rg/grep path-recognition contract."""
    paths: set[str] = set()
    if not segment or segment[0] not in {"sed", "head", "tail", "rg", "grep"}:
        return paths
    if segment[0] == "rg" and "--files" in segment:
        return paths
    for part in segment[1:]:
        if part.startswith("-") or part.isdigit():
            continue
        candidate = project_file(part, project)
        if candidate is not None:
            paths.add(str(candidate))
    return paths


def codex_read_paths(events: list[dict], project: Path) -> set[str]:
    """Extract verified read paths from successful Codex command-completion events."""
    project = project.resolve()
    paths: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        item = completed_command_item(event)
        if item is None:
            continue
        command = item.get("command")
        if not isinstance(command, str):
            continue
        segments = command_segments(command)
        if segments is None:
            continue
        if all(segment[0] == "cat" for segment in segments):
            paths.update(cat_bundle_paths(item, segments, project))
        elif len(segments) == 1:
            paths.update(simple_read_paths(segments[0], project))
    return paths


def final_answer(events: list[dict], host: str) -> tuple[str, str] | None:
    """Return the exact terminal host answer and its trace-bound host identity.

    Claude's terminal result ``uuid`` identifies that serialized event.  Older
    CLI result records may omit it; their ``session_id`` identifies the final
    successful result selected from this one raw trace instead.
    """
    if host == "claude":
        results = [event for event in events if isinstance(event, dict) and event.get("type") == "result"
                   and event.get("is_error") is False and isinstance(event.get("result"), str) and event["result"]]
        if not results:
            return None
        result = results[-1]
        identifier = value(result, "uuid", "session_id")
        return (result["result"], identifier) if isinstance(identifier, str) and identifier else None
    if host == "antigravity":
        if any(isinstance(event, dict) and "event" in event for event in events):
            conversation = agy_conversation(events)
            results = [event.get("result") for event in events if isinstance(event, dict) and event.get("event") == "result"]
            if conversation is None or len(results) != 1 or not isinstance(results[0], dict):
                return None
            result = results[0]
            response = result.get("response")
            if result.get("conversation_id") != conversation or result.get("status") != "SUCCESS" or not isinstance(response, str) or not response:
                return None
            return response, conversation
        results = [event for event in events if isinstance(event, dict) and event.get("type") == "result"
                   and event.get("is_error") is False and isinstance(event.get("result"), str) and event["result"]]
        if not results:
            return None
        result = results[-1]
        identifier = value(result, "uuid", "id")
        return (result["result"], identifier) if isinstance(identifier, str) and identifier else None
    completed = [event.get("item") for event in events if isinstance(event, dict) and event.get("type") == "item.completed"
                 and isinstance(event.get("item"), dict)]
    if not completed:
        return None
    item = completed[-1]
    text = item.get("text") if item.get("type") == "agent_message" else None
    identifier = item.get("id")
    return (text, identifier) if isinstance(text, str) and text and isinstance(identifier, str) and identifier else None


def persist_answer(run_dir: Path, answer: str, event_id: str) -> dict:
    path = run_dir / "host" / "answer.txt"
    path.write_text(answer, encoding="utf-8")
    return {"answer_file": str(path.relative_to(run_dir)), "answer_sha256": sha256_file(path), "answer_event_id": event_id}


def claude_read_paths(events: list[dict]) -> set[str]:
    """Match successful Claude Read tool results to their requested paths."""
    requested: dict[str, str] = {}
    paths: set[str] = set()
    for event in events:
        message = event.get("message", {}) if isinstance(event, dict) else {}
        content = message.get("content", []) if isinstance(message, dict) else []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Read":
                path = block.get("input", {}).get("file_path") if isinstance(block.get("input"), dict) else None
                if isinstance(path, str) and isinstance(block.get("id"), str):
                    requested[block["id"]] = path
            elif block.get("type") == "tool_result" and (
                block.get("is_error") is False or
                ("is_error" not in block and isinstance(block.get("content"), (str, list)))
            ):
                tool_id = block.get("tool_use_id")
                if isinstance(tool_id, str) and tool_id in requested:
                    paths.add(str(Path(requested[tool_id]).resolve()))
    return paths


SKILL_BASE_PREFIX = "Base directory for this skill: "
# Claude Code rewrites these in the injected body: $1 becomes an argument word, !`cmd` runs a shell.
CLAUDE_SUBSTITUTION = re.compile(r"\$(?:ARGUMENTS|\d+|\{CLAUDE_[A-Z_]+\})|!`|```!")


def skill_body(text: str) -> str:
    """Return SKILL.md as Claude injects it: no BOM or frontmatter, LF line endings."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    # Mirrors Claude Code 2.1.296's own frontmatter pattern and guard.
    match = re.match(r"---\s*\n[\s\S]*?---\s*\n?", text) if text.find("---", 3) >= 0 else None
    return (text[match.end():] if match else text).strip()


def claude_skill_load_paths(events: list[dict], project: Path) -> set[str]:
    """Bind Claude Code's native Skill load to the copied SKILL.md it injected.

    Claude loads a skill without a Read call: a successful ``Skill`` tool result
    is followed by a synthetic user message holding the base directory and the
    SKILL.md body (plus an optional ``ARGUMENTS:`` tail).  Only that adjacent
    message, a base directory inside ``project`` and the exact body count.
    """
    project = project.resolve()
    skill_calls: set[str] = set()
    launched = False
    paths: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in {"assistant", "user"}:
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        blocks = [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []
        text = blocks[0].get("text") if len(blocks) == 1 and blocks[0].get("type") == "text" else None
        if (launched and event["type"] == "user" and event.get("isSynthetic") is True and isinstance(text, str)
                and text.startswith(SKILL_BASE_PREFIX)):
            base, _, injected = text[len(SKILL_BASE_PREFIX):].partition("\n")
            master = project_file(str(Path(base.strip()) / "SKILL.md"), project)
            try:
                body = skill_body(master.read_text(encoding="utf-8")) if master else ""
            except (OSError, UnicodeDecodeError):
                body = ""
            rest = injected.replace("\r\n", "\n").strip()
            tail = rest[len(body):].strip() if body and rest.startswith(body) else None
            if tail is not None and (not tail or tail.startswith("ARGUMENTS: ")):
                paths.add(str(master))
        launched = False
        for block in blocks:
            if block.get("type") == "tool_use" and block.get("name") == "Skill" and isinstance(block.get("id"), str):
                skill_calls.add(block["id"])
            elif (block.get("type") == "tool_result" and block.get("tool_use_id") in skill_calls
                  and block.get("is_error") is not True):
                launched = True
    return paths


def agy_read_paths(events: list[dict]) -> set[str]:
    """Bind legacy results or native AGY DONE steps to their original requests."""
    if any("event" in event for event in events):
        conversation = agy_conversation(events)
        if conversation is None:
            return set()
        requested: dict[int, str] = {}
        successful: dict[int, str] = {}
        rejected: set[int] = set()
        for event in events:
            if event.get("event") != "step_update" or not isinstance(event.get("step_update"), dict):
                continue
            step = event["step_update"]
            index = step.get("step_index")
            if step.get("conversation_id") != conversation or not isinstance(index, int) or isinstance(index, bool):
                continue
            state = step.get("state")
            if state not in ("ACTIVE", "DONE"):
                rejected.add(index); requested.pop(index, None); successful.pop(index, None)
                continue
            tool = step.get("tool_info")
            if index in rejected or not isinstance(tool, dict) or tool.get("name") != "view_file" or step.get("step_type") != "tool":
                continue
            parameters = tool.get("parameters")
            path = parameters.get("AbsolutePath") if isinstance(parameters, dict) else None
            if not isinstance(path, str) or not Path(path).is_absolute():
                continue
            previous = requested.get(index, successful.get(index))
            error = tool.get("error")
            if previous is not None and previous != path:
                rejected.add(index); requested.pop(index, None); successful.pop(index, None)
            elif state == "ACTIVE":
                if index in successful:
                    rejected.add(index); successful.pop(index, None)
                else:
                    requested[index] = path
            elif (previous == path and isinstance(tool.get("output"), str) and tool["output"]
                  and (error is None or error is False or error == "")):
                successful[index] = path; requested.pop(index, None)
            else:
                rejected.add(index); requested.pop(index, None); successful.pop(index, None)
        return {str(Path(path).resolve()) for path in successful.values()}
    requested: dict[str, str] = {}
    paths: set[str] = set()
    for event in events:
        block = event.get("tool_use", event)
        if isinstance(block, dict) and block.get("name") == "view_file":
            inputs = block.get("input", block.get("arguments", {}))
            path = inputs.get("path") if isinstance(inputs, dict) else None
            identifier = block.get("id")
            if isinstance(path, str) and isinstance(identifier, str):
                requested[identifier] = path
        result = event.get("tool_result", event)
        if isinstance(result, dict) and result.get("is_error") is False:
            identifier = result.get("tool_use_id")
            if isinstance(identifier, str) and identifier in requested:
                paths.add(str(Path(requested[identifier]).resolve()))
    return paths


def source_from_state(state: dict, snapshot: dict) -> tuple[Path, str]:
    project = value(snapshot, "project") or value(state, "project")
    skill = value(snapshot, "skill", "skill_rel") or value(state, "skill", "skill_rel")
    if not isinstance(project, str) or not isinstance(skill, str) or not Path(project).is_absolute() or not safe_relative(skill):
        raise ValueError("frozen state must contain absolute project and project-relative skill")
    root = (Path(project) / skill).resolve()
    if not root.is_dir():
        raise ValueError("frozen skill directory does not exist")
    return root, Path(skill).name


def prepare(run_dir: Path, prompt_rel: str) -> dict:
    """Create the Antigravity-only isolated copy without claiming or invoking a host."""
    record: dict = {"verdict": "blocked", "errors": []}
    if not run_dir.is_absolute() or not run_dir.is_dir() or not safe_relative(prompt_rel) or not (run_dir / prompt_rel).is_file():
        record["errors"].append({"code": "invalid-input", "message": "run dir and prompt are required"})
        return record
    run_dir = run_dir.resolve()
    try:
        state = load_state(run_dir)
        if state.get("host") != "antigravity" or state.get("host_attempts") != 0:
            raise ValueError("prepare is only available before the Antigravity host claim")
        snapshot = package_snapshot(state)
        root, skill_id = source_from_state(state, snapshot)
        host_root = run_dir / "host"
        if host_root.exists():
            raise ValueError("host artifacts already exist")
        target = host_root / "project" / ".agents" / "skills" / skill_id
        target.parent.mkdir(parents=True)
        shutil.copytree(root, target, symlinks=False)
        claude_dir = host_root / "project" / ".claude" / "skills"
        claude_dir.mkdir(parents=True)
        (claude_dir / skill_id).symlink_to(Path("../../.agents/skills") / skill_id)
        source_digest, _ = digest_tree(root)
        copy_digest, copied_files = digest_tree(target)
        if source_digest != copy_digest:
            raise ValueError("isolated skill copy does not match source")
        data = {"subject_digest": snapshot["digest"], "copy_digest": copy_digest, "copied_files": copied_files,
                "skill_path": str(target.relative_to(run_dir)), "prompt_sha256": sha256_file(run_dir / prompt_rel)}
        path = host_root / "prepare.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"verdict": "pass", **data, "prepare_file": str(path.relative_to(run_dir)), "prepare_sha256": sha256_file(path)}
    except Exception as exc:
        record["errors"].append({"code": "prepare-failed", "message": str(exc)})
        return record


def run(run_dir: Path, prompt_rel: str, timeout: int, executable: str | None, import_trace: str | None = None) -> dict:
    started = time.time()
    record: dict = {"verdict": "blocked", "started_at": started, "errors": [], "events": [], "loaded": False}
    if not run_dir.is_absolute() or not run_dir.is_dir() or not safe_relative(prompt_rel):
        record["errors"].append({"code": "invalid-input", "message": "run dir must be absolute and prompt must be run-relative"})
        return record
    run_dir = run_dir.resolve(strict=True)
    prompt_file = run_dir / prompt_rel
    if not prompt_file.is_file():
        record["errors"].append({"code": "missing-prompt", "message": prompt_rel})
        return record
    try:
        prompt = prompt_file.read_text(encoding="utf-8")
        state = load_state(run_dir)
        snapshot = package_snapshot(state)
        root, skill_id = source_from_state(state, snapshot)
        copy_source_digest, _ = digest_tree(root)
    except Exception as exc:
        record["errors"].append({"code": "frozen-snapshot-unavailable", "message": str(exc)})
        return record
    expected = value(snapshot, "subject_digest", "digest")
    host = str(value(state, "host") or "unknown")
    record["host"] = host
    host_root = run_dir / "host"
    prepare_path = host_root / "prepare.json"
    prepared: dict | None = None
    if import_trace is not None and prepare_path.is_file() and host == "antigravity":
        try:
            prepared = json.loads(prepare_path.read_text(encoding="utf-8"))
            if state.get("host_attempts") != 1 or prepared.get("subject_digest") != expected:
                raise ValueError("prepared copy is not bound to the claimed frozen subject")
        except Exception as exc:
            record["errors"].append({"code": "invalid-prepared-copy", "message": str(exc)})
            return record
    elif any((host_root / name).exists() or (host_root / name).is_symlink() for name in ("project", "record.json", "trace.json", "raw-trace.jsonl", "prepare.json")):
        record["errors"].append({"code": "host-artifacts-exist", "message": "existing host evidence is preserved; start a new run"})
        return record
    if import_trace is not None and prepared is None:
        record["errors"].append({"code": "prepare-required", "message": "Antigravity trace import requires --prepare, then an external claim and native run"})
        return record
    project = run_dir / "host" / "project"
    if import_trace is not None:
        if host != "antigravity" or not safe_relative(import_trace) or not (run_dir / import_trace).is_file():
            record["errors"].append({"code": "invalid-import-trace", "message": "only an existing run-relative Antigravity trace may be imported"})
            return record
        command, adapter = None, {"mode": "antigravity-import-trace"}
    else:
        command, adapter = host_command(host, project, executable)
        if command is None:
            record["adapter"] = adapter
            record["errors"].append(adapter)
            record["static_compatibility"] = True
            return record
    if host == "claude":
        try:
            risky = sorted(set(CLAUDE_SUBSTITUTION.findall(skill_body((root / "SKILL.md").read_text(encoding="utf-8")))))
        except (OSError, UnicodeDecodeError) as exc:
            risky = [f"unreadable SKILL.md: {exc}"]
        if risky:
            # Blocked before the one attempt is spent: the injected body could never match the frozen file.
            record["errors"].append({"code": "claude-skill-substitution",
                                     "message": "SKILL.md body has text Claude Code rewrites at load: " + ", ".join(risky)})
            return record
    if prepared is None:
        try:
            claim_host(run_dir)
            record["attempt_claimed"] = True
        except Exception as exc:
            record["errors"].append({"code": "host-quota-refused", "message": str(exc)})
            return record
    else:
        record["attempt_claimed"] = True
    target = project / ".agents" / "skills" / skill_id
    if prepared is None:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, target, symlinks=False)
    profile_rel = {"codex": ".codex/agents", "claude": ".claude/agents", "antigravity": ".agents/agents"}.get(state.get("host"))
    if profile_rel and prepared is None:
        source_profile = Path(state["project"]).resolve() / profile_rel
        target_profile = project / profile_rel
        if source_profile.is_dir():
            target_profile.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_profile, target_profile, symlinks=False)
            record["profile_copy"] = profile_rel
    copied_digest, copied_files = digest_tree(target)
    record.update({"subject_digest": expected, "copy_digest": copied_digest, "copied_files": copied_files,
                   "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "host_project": str(project)})
    if copied_digest != copy_source_digest:
        record["verdict"] = "fail"
        record["errors"].append({"code": "copy-mismatch", "message": "isolated copy differs from frozen source"})
        return record
    if prepared is None:
        claude_dir = project / ".claude" / "skills"
        claude_dir.mkdir(parents=True, exist_ok=True)
        alias = claude_dir / skill_id
        alias.symlink_to(Path("../../.agents/skills") / skill_id)
        record["claude_alias"] = str(alias.relative_to(project))
    if import_trace is not None:
        raw = (run_dir / import_trace).read_text(encoding="utf-8")
        raw_events = json_events(raw)
        events = normalized_events(host, raw_events, project)
        record.update({"adapter": adapter, "import_trace": import_trace,
                       "stdout": raw, "events": events})
        record.update(persist_trace(run_dir, raw, events))
        answer = final_answer(raw_events, host)
        if answer is None:
            record.update({"answer_file": None, "answer_sha256": None, "answer_event_id": None, "returncode": 1})
            record["errors"].append({"code": "answer-unavailable", "message": "imported trace has no final host answer event"})
            return record
        record.update(persist_answer(run_dir, *answer))
        reads = {str(Path(item["path"]).resolve()) for item in events if item.get("type") == "tool.read"}
        copied = {str((target / "SKILL.md").resolve())}
        complete = any(item.get("type") == "turn.completed" for item in events)
        record["turn_completed"] = complete
        record["proof_files"] = [{"path": str(Path(path).relative_to(run_dir)), "sha256": sha256_file(Path(path))}
                                 for path in sorted(copied & reads)]
        if package_snapshot(load_state(run_dir)).get("digest") != expected:
            record.update({"verdict": "fail", "returncode": 1})
            record["errors"].append({"code": "source-changed-during-host-call", "message": "frozen source was modified"})
        elif complete and record["proof_files"]:
            record.update({"verdict": "pass", "loaded": True, "returncode": 0})
        else:
            record.update({"verdict": "fail", "returncode": 1})
            record["errors"].append({"code": "load-proof-unavailable", "message": "imported trace lacks a successful view_file binding or completion"})
        return record
    record["adapter"] = adapter
    record["command"] = command
    stdout_file = host_root / "raw-trace.jsonl"
    stderr_file = host_root / "stderr.log"
    attempt_file = host_root / "attempt.json"
    attempt_file.write_text(json.dumps({"status": "running", "started_at": started,
        "host": host, "command": command, "subject_digest": expected,
        "prompt_sha256": record["prompt_sha256"], "stdout_file": stdout_file.relative_to(run_dir).as_posix(),
        "stderr_file": stderr_file.relative_to(run_dir).as_posix()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        # Persist output during execution; outer tool interruptions must not erase all evidence.
        with stdout_file.open("x", encoding="utf-8") as stdout_handle, stderr_file.open("x", encoding="utf-8") as stderr_handle:
            process = subprocess.run(command, input=prompt, text=True, cwd=project, shell=False,
                                     stdout=stdout_handle, stderr=stderr_handle, timeout=timeout, env=os.environ.copy())
        stdout = stdout_file.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_file.read_text(encoding="utf-8", errors="replace")
        record.update({"returncode": process.returncode, "stdout": stdout, "stderr": stderr})
    except subprocess.TimeoutExpired as exc:
        stdout = stdout_file.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_file.read_text(encoding="utf-8", errors="replace")
        record.update({"verdict": "fail", "timeout": timeout, "stdout": stdout, "stderr": stderr})
        record["errors"].append({"code": "timeout", "message": f"host exceeded {timeout}s"})
        return record
    except OSError as exc:
        record["errors"].append({"code": "host-launch-failed", "message": str(exc)})
        return record
    after_digest = package_snapshot(load_state(run_dir)).get("digest")
    if after_digest != expected:
        record["verdict"] = "fail"
        record["errors"].append({"code": "source-changed-during-host-call", "message": "frozen source was modified"})
        return record
    if process.returncode != 0:
        record["verdict"] = "fail"
        record["errors"].append({"code": "host-failed", "message": f"exit {process.returncode}"})
        return record
    # Exit status and prose never prove discovery/loading; require a host-provided trace with copied-file binding.
    raw_events = json_events(stdout)
    events = normalized_events(host, raw_events, project)
    record["events"] = events
    record.update(persist_trace(run_dir, stdout, events))
    answer = final_answer(raw_events, host)
    if answer is None:
        record.update({"answer_file": None, "answer_sha256": None, "answer_event_id": None, "verdict": "blocked"})
        record["errors"].append({"code": "answer-unavailable", "message": "host trace has no final host answer event"})
        return record
    record.update(persist_answer(run_dir, *answer))
    copied = {str((target / "SKILL.md").resolve())}
    reads = {str(Path(item["path"]).resolve()) for item in events if item.get("type") == "tool.read"}
    complete = any(item.get("type") == "turn.completed" for item in events)
    record["turn_completed"] = complete
    record["proof_files"] = [{"path": str(Path(path).relative_to(run_dir)), "sha256": sha256_file(Path(path))}
                             for path in sorted(copied & reads)]
    if host == "claude":
        # A Read of SKILL.md shows file use; only the Skill-tool injection shows Claude's own skill loading.
        record["native_skill_load"] = bool(copied & claude_skill_load_paths(raw_events, project))
    if complete and record["proof_files"]:
        record.update({"verdict": "pass", "loaded": True})
    else:
        record["errors"].append({"code": "load-proof-unavailable", "message": "missing turn completion or tool-read trace for copied skill files"})
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--executable", help="test-only executable; receives the single user prompt on stdin")
    parser.add_argument("--import-trace", help="run-relative raw Antigravity native-host tool trace")
    parser.add_argument("--prepare", action="store_true", help="prepare an Antigravity isolated copy without claiming or invoking a host")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    record = prepare(Path(args.run_dir), args.prompt) if args.prepare else run(Path(args.run_dir), args.prompt, args.timeout, args.executable, args.import_trace)
    path = write_record(Path(args.run_dir), record) if record.get("attempt_claimed") and Path(args.run_dir).is_absolute() else None
    output = dict(record)
    if path:
        output["evidence_path"] = str(path)
    sys.stdout.write(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0 if output["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
