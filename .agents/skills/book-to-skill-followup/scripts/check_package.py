#!/usr/bin/env python3
"""Static, side-effect-free validation for a generated skill package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import yaml
except ImportError:  # Report a truthful blocked result; never install parsers here.
    yaml = None

try:
    from markdown_it import MarkdownIt
except ImportError:
    MarkdownIt = None


FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
HTML_ID = re.compile(r"\bid\s*=\s*(['\"])(.*?)\1", re.IGNORECASE)
INSTRUCTION = re.compile(r"\b(?:run|execute|install|delete|remove|curl|wget|npm\s+install|pip\s+install)\b|(?:실행|설치|삭제)\b", re.IGNORECASE)
# Same pattern as host_smoke: Claude Code substitutes or executes these when it loads a SKILL.md body.
CLAUDE_SUBSTITUTION = re.compile(r"\$(?:ARGUMENTS|\d+|\{CLAUDE_[A-Z_]+\})|!`|```!")
ADVISORY = re.compile(r"\b(?:example|quoted?|citation|book|do not run)\b|(?:예시|인용|책|실행하지)\b", re.IGNORECASE)
FOLLOWUP_SKILL_PATHS = tuple(Path(host) / "skills" / "book-to-skill-followup"
                            for host in (".agents", ".claude", ".codex", ".agent"))
FOLLOWUP_PROFILE_PATHS = tuple(
    Path(host) / "agents" / f"book-followup-{role}.{extension}"
    for host in (".agents", ".claude", ".codex")
    for role in ("source-reviewer", "forward-tester", "release-reviewer")
    for extension in ("md", "toml")
)
FOLLOWUP_DELIVERY_PATHS = FOLLOWUP_SKILL_PATHS + FOLLOWUP_PROFILE_PATHS


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(path: Path) -> Path:
    return path.resolve(strict=False)


def contained(path: Path, root: Path) -> bool:
    try:
        canonical(path).relative_to(canonical(root))
        return True
    except ValueError:
        return False


def visible_markdown(text: str) -> str:
    """Drop fenced code; commands quoted by a book are advisory, never executable."""
    lines, inside, marker, length = [], False, "", 0
    for line in text.splitlines():
        match = FENCE.match(line)
        if match:
            token = match.group(1)
            if not inside:
                inside, marker, length = True, token[0], len(token)
            elif token[0] == marker and len(token) >= length:
                inside = False
            continue
        if not inside:
            lines.append(line)
    return "\n".join(lines)


def slug(value: str) -> str:
    value = unquote(value).strip().lower()
    value = "".join(char for char in value if char.isalnum() or char in "-_" or char.isspace())
    return re.sub(r"[\s-]+", "-", value).strip("-")


def markdown_anchors(text: str) -> set[str]:
    visible = visible_markdown(text)
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    if MarkdownIt is not None:
        tokens = MarkdownIt().parse(visible)
        for index, token in enumerate(tokens):
            if token.type == "heading_open" and index + 1 < len(tokens):
                inline = tokens[index + 1]
                content = "".join(child.content for child in (inline.children or [])
                                  if child.type in {"text", "code_inline", "image"})
                base = slug(content)
                if base:
                    suffix = counts.get(base, 0)
                    anchors.add(base if suffix == 0 else f"{base}-{suffix}")
                    counts[base] = suffix + 1
    else:
        for line in visible.splitlines():
            match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
            if match:
                base = slug(match.group(1))
                suffix = counts.get(base, 0)
                anchors.add(base if suffix == 0 else f"{base}-{suffix}")
                counts[base] = suffix + 1
    for _quote, identifier in HTML_ID.findall(visible):
        anchors.add(unquote(identifier).strip())
        anchors.add(slug(identifier))
    return anchors


def markdown_links(text: str) -> list[str]:
    if MarkdownIt is None:
        return []
    result: list[str] = []
    for token in MarkdownIt().parse(visible_markdown(text)):
        tokens = token.children or [token]
        for child in tokens:
            if child.type == "link_open":
                href = child.attrGet("href")
                if href:
                    result.append(href)
            elif child.type == "image":
                source = child.attrGet("src")
                if source:
                    result.append(source)
            elif child.type in {"html_inline", "html_block"}:
                result.extend(re.findall(r"\bhref\s*=\s*['\"]([^'\"]+)", child.content, re.IGNORECASE))
    return result


def parse_file(path: Path, errors: list[dict], relative: str) -> None:
    try:
        if path.suffix.lower() == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() == ".toml":
            tomllib.loads(path.read_text(encoding="utf-8"))
        elif path.suffix.lower() in {".yaml", ".yml"}:
            if yaml is None:
                raise RuntimeError("PyYAML is unavailable")
            yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append({"file": relative, "code": "invalid-structured-file", "message": str(exc)})


def read_front_matter(path: Path, errors: list[dict], root: Path) -> None:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    if not match:
        errors.append({"file": "SKILL.md", "code": "missing-front-matter", "message": "YAML front matter is required"})
        return
    if yaml is None:
        errors.append({"file": "SKILL.md", "code": "yaml-parser-unavailable", "message": "PyYAML is required"})
        return
    try:
        data = yaml.safe_load(match.group(1))
    except Exception as exc:
        errors.append({"file": "SKILL.md", "code": "invalid-front-matter", "message": str(exc)})
        return
    if not isinstance(data, dict):
        errors.append({"file": "SKILL.md", "code": "invalid-front-matter", "message": "front matter must be a mapping"})
        return
    for field in ("name", "description"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            errors.append({"file": "SKILL.md", "code": f"missing-{field}", "message": f"{field} is required"})
    if data.get("name") != root.name:
        errors.append({"file": "SKILL.md", "code": "name-folder-mismatch", "message": "front matter name must match skill folder"})


def read_role_front_matter(path: Path, errors: list[dict], project: Path) -> None:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    relative = str(path.relative_to(project))
    if not match or yaml is None:
        errors.append({"file": relative, "code": "missing-role-front-matter", "message": "role Markdown requires YAML name and description"})
        return
    try:
        data = yaml.safe_load(match.group(1))
    except Exception as exc:
        errors.append({"file": relative, "code": "invalid-role-front-matter", "message": str(exc)})
        return
    if not isinstance(data, dict) or not all(isinstance(data.get(key), str) and data[key].strip() for key in ("name", "description")):
        errors.append({"file": relative, "code": "missing-role-metadata", "message": "role Markdown requires name and description"})


def check_link(source: Path, href: str, project: Path, anchors_cache: dict[Path, set[str]], errors: list[dict]) -> None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or href.startswith("//") or href.startswith("mailto:"):
        return
    raw_path, fragment = unquote(parsed.path), unquote(parsed.fragment)
    target = source if not raw_path else canonical(source.parent / raw_path)
    if not contained(target, project):
        errors.append({"file": str(source.relative_to(project)), "code": "link-escapes-project", "message": href})
        return
    if target.is_dir() and not fragment:
        return
    if not target.is_file():
        errors.append({"file": str(source.relative_to(project)), "code": "missing-local-link", "message": href})
        return
    if fragment:
        if target.suffix.lower() not in {".md", ".markdown"}:
            errors.append({"file": str(source.relative_to(project)), "code": "invalid-link-anchor", "message": href})
            return
        anchors = anchors_cache.setdefault(target, markdown_anchors(target.read_text(encoding="utf-8")))
        if fragment not in anchors and slug(fragment) not in anchors:
            errors.append({"file": str(source.relative_to(project)), "code": "missing-link-anchor", "message": href})


def allowed_claude_alias(project: Path, supplied: Path, resolved: Path) -> bool:
    """A .claude/skills/<id> link may point at the paired in-project .agents skill."""
    try:
        rel = supplied.relative_to(project)
    except ValueError:
        return False
    return (len(rel.parts) == 3 and rel.parts[:2] == (".claude", "skills")
            and resolved == canonical(project / ".agents" / "skills" / rel.name))


def git_root(project: Path) -> tuple[Path | None, str | None]:
    try:
        result = subprocess.run(["git", "-C", str(project), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
    except OSError as exc:
        return None, str(exc)
    if result.returncode:
        if "not a git repository" in result.stderr.lower():
            return None, None
        return None, result.stderr.strip() or f"git rev-parse exited {result.returncode}"
    if not result.stdout.strip():
        return None, "git did not report a repository root"
    return canonical(Path(result.stdout.strip())), None


def git_tracks(repository: Path, path: Path) -> bool | None:
    try:
        relative = path.relative_to(repository)
    except ValueError:
        return None
    try:
        result = subprocess.run(["git", "-C", str(repository), "ls-files", "--error-unmatch", "--", str(relative)],
                                capture_output=True, text=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(result.returncode)


def git_ignores(repository: Path, path: Path) -> bool | None:
    try:
        relative = path.relative_to(repository)
    except ValueError:
        return None
    try:
        result = subprocess.run(["git", "-C", str(repository), "check-ignore", "-q", "--", str(relative)],
                                capture_output=True, text=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(result.returncode)


def is_followup_skill_file(path: Path) -> bool:
    if path.name != "SKILL.md" or not path.is_file() or yaml is None:
        return False
    try:
        text = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
        data = yaml.safe_load(match.group(1)) if match else None
    except (OSError, UnicodeError, yaml.YAMLError):
        return False
    return isinstance(data, dict) and data.get("name") == "book-to-skill-followup"


def is_followup_self_validation(root: Path) -> bool:
    return (canonical(root) == canonical(Path(__file__).parents[1])
            and is_followup_skill_file(root / "SKILL.md"))


def nested_followup_paths(root: Path) -> list[Path]:
    paths = [path for path in root.rglob("SKILL.md")
             if path != root / "SKILL.md" and is_followup_skill_file(path)]
    paths.extend(path for path in root.rglob("book-to-skill-followup") if path.is_symlink())
    return sorted(set(paths))


def check_followup_tool_leakage(project: Path, root: Path, errors: list[dict]) -> None:
    """Reject a copied production helper without treating text mentions as installations."""
    for path in nested_followup_paths(root):
        reported = path.parent if path.name == "SKILL.md" else path
        errors.append({"file": str(reported.relative_to(project)), "code": "nested-followup-tool",
                       "message": "generated skills may not contain the follow-up production tool"})
    if is_followup_self_validation(root):
        return
    install_paths = tuple(project / path for path in FOLLOWUP_DELIVERY_PATHS)
    installed = tuple(path for path in install_paths if path.exists() or path.is_symlink())
    if not installed:
        return
    repository, git_error = git_root(project)
    for path in installed:
        relative = str(path.relative_to(project))
        if git_error:
            errors.append({"file": relative, "code": "git-status-unavailable",
                           "message": "cannot determine whether follow-up tooling is tracked or ignored"})
            continue
        elif repository is None:
            errors.append({"file": relative, "code": "unmanaged-followup-tool",
                           "message": "a non-Git project may not contain the follow-up production tool"})
            continue
        tracked = git_tracks(repository, path)
        if tracked is True:
            errors.append({"file": relative, "code": "tracked-followup-tool",
                           "message": "the follow-up production tool is tracked for delivery"})
            continue
        ignored = git_ignores(repository, path) if tracked is False else None
        if tracked is None or ignored is None:
            errors.append({"file": relative, "code": "git-status-unavailable",
                           "message": "cannot determine whether follow-up tooling is tracked or ignored"})
        elif ignored is False:
            errors.append({"file": relative, "code": "unexcluded-followup-tool",
                           "message": "untracked follow-up tooling must be explicitly ignored"})


def package_files(root: Path, project: Path, errors: list[dict]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts):
            if path.is_symlink():
                errors.append({"file": str(relative), "code": "symlinked-cache", "message": "cache directories may not be symlinks"})
            continue
        if path.is_symlink():
            if not contained(path, project):
                errors.append({"file": str(relative), "code": "symlink-escapes-project", "message": str(path.resolve())})
            continue
        if path.is_dir():
            continue
        if path.is_file():
            files.append(path)
    return files


def run(project: Path, skill: str, documents: list[str], run_dir: Path | None) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    advisories: list[dict] = []
    if not project.is_absolute() or not project.is_dir():
        return {"verdict": "fail", "errors": [{"code": "invalid-project", "message": "--project must be an existing absolute directory"}]}
    project = canonical(project)
    requested = project / skill
    if Path(skill).is_absolute() or ".." in Path(skill).parts:
        return {"verdict": "fail", "errors": [{"code": "invalid-skill-path", "message": "--skill must be project-relative"}]}
    root = canonical(requested)
    if not requested.exists() or not root.is_dir() or not contained(root, project):
        return {"verdict": "fail", "errors": [{"code": "invalid-skill", "message": "skill must be an in-project directory"}]}
    aliases: list[dict] = []
    if requested.is_symlink():
        if not allowed_claude_alias(project, requested, root):
            return {"verdict": "fail", "errors": [{"code": "invalid-skill-alias", "message": "only paired in-project Claude skill aliases are allowed"}]}
        aliases.append({"path": str(requested.relative_to(project)), "target": str(root.relative_to(project))})
    check_followup_tool_leakage(project, root, errors)
    if yaml is None or MarkdownIt is None:
        missing = [name for name, present in (("PyYAML", yaml), ("markdown-it-py", MarkdownIt)) if present is None]
        return {"verdict": "blocked", "errors": [{"code": "parser-unavailable", "message": ", ".join(missing)}], "warnings": [], "advisories": []}
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        errors.append({"file": "SKILL.md", "code": "missing-skill", "message": "SKILL.md is required"})
    else:
        read_front_matter(skill_file, errors, root)
        body = re.sub(r"^﻿?---\s*\n[\s\S]*?---\s*\n?", "", skill_file.read_text(encoding="utf-8"), count=1)
        tokens = sorted(set(CLAUDE_SUBSTITUTION.findall(body)))
        if tokens:
            warnings.append({"file": "SKILL.md", "code": "claude-load-substitution",
                             "message": "Claude Code rewrites these in the SKILL.md body at load: " + ", ".join(tokens)})
    files = package_files(root, project, errors)
    document_paths: list[Path] = []
    for supplied in documents:
        candidate = project / supplied
        if Path(supplied).is_absolute() or ".." in Path(supplied).parts or candidate.is_symlink() or not candidate.exists() or not contained(candidate, project):
            errors.append({"file": supplied, "code": "invalid-document", "message": "document must be an in-project file"})
        elif candidate.is_file():
            document_paths.append(canonical(candidate))
        elif candidate.is_dir():
            document_paths.extend(package_files(candidate, project, errors))
        else:
            warnings.append({"file": supplied, "code": "non-markdown-document", "message": "only Markdown documents are link-checked"})
    profile_files: list[Path] = []
    for profile_root in (project / ".codex" / "agents", project / ".claude" / "agents", project / ".agents" / "agents"):
        if not profile_root.exists():
            continue
        if profile_root.is_symlink() or not profile_root.is_dir() or not contained(profile_root, project):
            errors.append({"file": str(profile_root.relative_to(project)), "code": "invalid-host-profile-root", "message": "profile root must be an in-project directory"})
            continue
        profile_files.extend(package_files(profile_root, project, errors))
    all_files = sorted({*files, *document_paths, *profile_files})
    anchors_cache: dict[Path, set[str]] = {}
    entries: list[dict] = []
    for path in all_files:
        relative = str(path.relative_to(project))
        entries.append({"path": relative, "sha256": sha256_file(path)})
        parse_file(path, errors, relative)
        if "agents" in path.relative_to(project).parts and path.suffix.lower() in {".md", ".markdown"}:
            read_role_front_matter(path, errors, project)
        if path.suffix.lower() not in {".md", ".markdown"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            errors.append({"file": relative, "code": "invalid-utf8-markdown", "message": str(exc)})
            continue
        for href in markdown_links(text):
            check_link(path, href, project, anchors_cache, errors)
        for line_number, line in enumerate(visible_markdown(text).splitlines(), 1):
            if INSTRUCTION.search(line):
                item = {"file": relative, "line": line_number, "code": "instruction-like-text", "message": line.strip()[:240]}
                (advisories if ADVISORY.search(line) else warnings).append(item)
    files_digest = hashlib.sha256(json.dumps({entry["path"]: entry["sha256"] for entry in entries},
                                             sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report = {"verdict": "fail" if errors else "pass", "errors": errors, "warnings": warnings,
              "advisories": advisories, "scanned_files": entries, "files_digest": files_digest,
              "project": str(project), "skill": str(root.relative_to(project)), "claude_aliases": aliases,
              "note": "static PASS does not establish the factual correctness of skill content."}
    if run_dir is not None:
        try:
            from runtime_common import load_state, package_snapshot
            state = load_state(run_dir)
            declared_docs = list(state.get("documents", []))
            supplied_docs = list(documents)
            if canonical(Path(state["project"])) != project or state.get("skill_rel") != str(root.relative_to(project)) or supplied_docs != declared_docs:
                raise ValueError("CLI project, skill, or documents do not match run state")
            snapshot = package_snapshot(state)
            expected = snapshot.get("subject_digest") or snapshot.get("digest")
            report["subject_digest"] = expected
            if (state.get("freeze_snapshot") or {}).get("digest") and state["freeze_snapshot"]["digest"] != expected:
                report["verdict"] = "fail"
                report["errors"].append({"code": "subject-digest-mismatch", "message": "package differs from frozen snapshot"})
        except Exception as exc:
            report["verdict"] = "blocked"
            report["errors"].append({"code": "runtime-snapshot-unavailable", "message": str(exc)})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--documents", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument("--run-dir")
    args = parser.parse_args(argv)
    report = run(Path(args.project), args.skill, args.documents, Path(args.run_dir) if args.run_dir else None)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            parser.error("--output must be absolute")
        output = canonical(output)
        run_root = canonical(Path(args.run_dir)) if args.run_dir else None
        if output.exists() or (run_root is not None and not contained(output, run_root)):
            report["verdict"] = "fail"
            report.setdefault("errors", []).append({"code": "unsafe-output-path", "message": "output must be a new file inside --run-dir" if run_root else "output file already exists"})
            encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
