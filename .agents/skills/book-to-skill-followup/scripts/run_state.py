#!/usr/bin/env python3
"""Local state checker for a book-to-skill follow-up run; it never invokes a model."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_common import (StateError, claim_host, ensure_relative, load_state,
                            mutate_state, package_snapshot, sha256_file,
                            workflow_snapshot)
from host_smoke import claude_skill_load_paths, digest_tree, final_answer, json_events, normalized_events

STAGES = ["preflight", "inventory", "source-audit", "skill-refinement", "documentation",
          "static-checks", "behavior-tests", "improvement", "language-review", "freeze", "host-smoke", "final-review"]
CHECK_STAGES = {"static-checks", "behavior-tests", "language-review", "freeze", "host-smoke", "final-review"}
REVISION_STAGES = {"skill-refinement", "documentation"}
LANGUAGE_REVIEW_PIPELINE = ("humanizer", "grammar-checker", "style-guide")
KOREAN_SKILLS_COMMIT = "ae12ba27982ebeff03b46dc738365aaa34260d9a"
MEANING_PRESERVATION_FIELDS = ("conditions", "numbers", "citations", "negations", "periods", "attributions")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
AGENT_REVIEW_SURFACES = {"codex": "codex-native", "claude": "claude-native", "antigravity": "antigravity-native"}
EXPECTED_DEPENDENCIES = {
    "preflight": set(), "inventory": {"preflight"}, "source-audit": {"inventory"},
    "skill-refinement": {"source-audit"}, "documentation": {"skill-refinement"},
    "static-checks": {"documentation"}, "behavior-tests": {"static-checks"},
    "improvement": {"behavior-tests"}, "language-review": {"improvement"}, "freeze": {"language-review"},
    "host-smoke": {"freeze"}, "final-review": set(STAGES[:-1]),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error(message: str) -> None:
    raise StateError(message)


def _strict(value: Any, label: str) -> None:
    if value is not True:
        _error(f"{label} must be boolean true")


def _str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        _error(f"{label} must be a non-empty string")
    return value


def _independent_id(value: Any, label: str, producer: Any) -> str:
    identity = _str(value, label)
    if producer is not None and identity == producer:
        _error(f"{label} must differ from producer_id")
    return identity


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _error(f"{label} must be a list")
    return value


def _exact_ids(value: Any, expected: set[str], label: str) -> None:
    values = [x if isinstance(x, str) else x.get("id") if isinstance(x, dict) else None for x in _list(value, label)]
    if any(not isinstance(x, str) or not x for x in values) or len(values) != len(set(values)) or set(values) != expected:
        _error(f"{label} must be the exact unique expected unit-id set")


def _current_digest(state: dict[str, Any]) -> str:
    return package_snapshot(state)["digest"]


def _language_review_vendor() -> dict[str, tuple[str, str]]:
    """Return pinned review skills after proving the complete vendored tree matches provenance."""
    root = Path(__file__).resolve().parent.parent / "assets" / "korean-skills"
    if root.is_symlink() or not root.is_dir(): _error("Korean review vendor root is unavailable")
    provenance_path = root / "provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _error(f"Korean review provenance is unavailable: {exc}")
    if not isinstance(provenance, dict): _error("Korean review provenance must be an object")
    if provenance.get("repository") != "https://github.com/DaleSeo/korean-skills":
        _error("Korean review provenance repository is invalid")
    if provenance.get("commit") != KOREAN_SKILLS_COMMIT:
        _error("Korean review provenance commit is invalid")
    if provenance.get("license") != "MIT": _error("Korean review provenance license is invalid")
    if tuple(provenance.get("included_skills", [])) != LANGUAGE_REVIEW_PIPELINE:
        _error("Korean review provenance skills are invalid")
    entries = provenance.get("files")
    if not isinstance(entries, list): _error("Korean review provenance files are invalid")
    declared: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict): _error("Korean review provenance file entries must be objects")
        relative = _str(entry.get("path"), "Korean review provenance file path")
        if relative == "provenance.json": _error("Korean review provenance must not declare itself")
        path = ensure_relative(root, relative)
        if path.is_symlink() or not path.is_file() or relative in declared:
            _error("Korean review provenance file paths must be unique regular files")
        digest = _str(entry.get("sha256"), "Korean review provenance file hash")
        if not SHA256.fullmatch(digest): _error("Korean review provenance file hash must be SHA-256")
        declared[relative] = digest
    actual: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink(): _error(f"Korean review vendor symlink is not allowed: {relative}")
        if path.is_file() and relative != "provenance.json": actual[relative] = sha256_file(path)
    if declared != actual: _error("Korean review provenance files do not exactly match the vendor tree")
    license_path = root / "LICENSE"
    try:
        if "MIT License" not in license_path.read_text(encoding="utf-8"):
            _error("Korean review vendor LICENSE lacks MIT notice")
    except OSError as exc:
        _error(f"Korean review vendor LICENSE is unavailable: {exc}")
    patches = provenance.get("local_patches")
    if not isinstance(patches, list) or len(patches) != 2:
        _error("Korean review provenance must record the two local patches")
    patched_paths: set[str] = set()
    for patch in patches:
        if not isinstance(patch, dict): _error("Korean review local patch must be an object")
        relative = _str(patch.get("path"), "Korean review local patch.path")
        if relative in patched_paths or relative not in declared: _error("Korean review local patch path is invalid")
        patched_paths.add(relative)
        upstream = _str(patch.get("upstream_sha256"), "Korean review local patch.upstream_sha256")
        bundled = _str(patch.get("bundled_sha256"), "Korean review local patch.bundled_sha256")
        if not SHA256.fullmatch(upstream) or not SHA256.fullmatch(bundled) or bundled != declared[relative]:
            _error("Korean review local patch hashes are invalid")
    result: dict[str, tuple[str, str]] = {}
    for name in LANGUAGE_REVIEW_PIPELINE:
        relative = f"skills/{name}/SKILL.md"
        expected = declared.get(relative)
        path = root / relative
        if not isinstance(expected, str) or len(expected) != 64 or path.is_symlink() or not path.is_file():
            _error(f"Korean review vendor is incomplete: {relative}")
        actual = sha256_file(path)
        if actual != expected: _error(f"Korean review vendor hash mismatch: {relative}")
        result[name] = (f"assets/korean-skills/{relative}", actual)
    return result


def _bound_run_record(run: Path, value: Any, label: str) -> Path:
    if not isinstance(value, dict): _error(f"{label} must be an object")
    path = _run_file(run, value.get("path"), f"{label}.path")
    if sha256_file(path) != _str(value.get("sha256"), f"{label}.sha256"):
        _error(f"{label} hash mismatch")
    return path


def _bound_json_run_record(run: Path, value: Any, label: str) -> dict[str, Any]:
    path = _bound_run_record(run, value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _error(f"{label} must be UTF-8 JSON: {exc}")
    if not isinstance(data, dict): _error(f"{label} JSON must be an object")
    return data


def _regular_tree(root: Path, label: str) -> tuple[str, list[dict]]:
    if root.is_symlink() or not root.is_dir(): _error(f"{label} must be a regular directory")
    for path in root.rglob("*"):
        if path.is_symlink(): _error(f"{label} must not contain symlinks")
    return digest_tree(root)


def _reviewed_language_files(state: dict[str, Any]) -> dict[str, str]:
    snapshot = package_snapshot(state)["files"]
    return {path: digest for path, digest in snapshot.items()
            if Path(path).suffix.lower() in {".md", ".markdown", ".json", ".yaml", ".yml"}}


def _validate_language_review_evidence(state: dict[str, Any], data: dict[str, Any], run: Path) -> None:
    producer = state.get("producer_id")
    reviewer = _independent_id(data.get("reviewer_id"), "language review reviewer_id", producer)
    if tuple(_list(data.get("pipeline"), "language review pipeline")) != LANGUAGE_REVIEW_PIPELINE:
        _error("language review pipeline must be humanizer, grammar-checker, style-guide in order")
    vendor = _language_review_vendor()
    supplied = _list(data.get("upstream_skills"), "language review upstream_skills")
    if len(supplied) != len(LANGUAGE_REVIEW_PIPELINE): _error("language review upstream_skills must list each skill once")
    seen: set[str] = set()
    for item in supplied:
        if not isinstance(item, dict): _error("language review upstream_skills entries must be objects")
        name = _str(item.get("id"), "language review upstream skill id")
        if name in seen or name not in vendor: _error("language review upstream skill ids must be exact and unique")
        seen.add(name)
        path, digest = vendor[name]
        if item.get("path") != path or item.get("sha256") != digest or item.get("commit") != KOREAN_SKILLS_COMMIT:
            _error("language review upstream skill path, hash, or commit differs from the pinned vendor")
    if tuple(item.get("id") for item in supplied) != LANGUAGE_REVIEW_PIPELINE:
        _error("language review upstream_skills must follow the review pipeline order")
    reviewed: dict[str, str] = {}
    for item in _list(data.get("reviewed_files"), "language review reviewed_files"):
        if not isinstance(item, dict): _error("language review reviewed_files entries must be objects")
        path = _str(item.get("path"), "language review reviewed_file.path")
        if path in reviewed: _error("language review reviewed_files paths must be unique")
        reviewed[path] = _str(item.get("sha256"), "language review reviewed_file.sha256")
    if reviewed != _reviewed_language_files(state):
        _error("language review reviewed_files must exactly cover current Markdown, JSON, and YAML subject files")
    stage_records = _list(data.get("pipeline_records"), "language review pipeline_records")
    if len(stage_records) != len(LANGUAGE_REVIEW_PIPELINE): _error("language review needs one record for every pipeline stage")
    if tuple(item.get("id") if isinstance(item, dict) else None for item in stage_records) != LANGUAGE_REVIEW_PIPELINE:
        _error("language review pipeline_records must follow the review pipeline order")
    for item in stage_records:
        if not isinstance(item, dict): _error("language review pipeline record must be an object")
        if _str(item.get("reviewer_id"), "language review pipeline record.reviewer_id") != reviewer:
            _error("language review pipeline record reviewer_id must match the independent reviewer")
        _bound_run_record(run, item, "language review pipeline record")
    manifest = data.get("read_manifest")
    manifest_data = _bound_json_run_record(run, manifest, "language review read_manifest")
    if (not isinstance(manifest, dict) or manifest.get("skills") != supplied or
            manifest.get("subject_files") != data.get("reviewed_files") or
            manifest_data.get("skills") != supplied or manifest_data.get("subject_files") != data.get("reviewed_files")):
        _error("language review read_manifest must bind the reviewed skills and subject files")
    method = data.get("review_method")
    if not isinstance(method, dict): _error("language review review_method must be an object")
    if _str(method.get("reviewer_id"), "language review review_method.reviewer_id") != reviewer:
        _error("language review review_method reviewer_id must match the independent reviewer")
    kind = method.get("kind")
    if kind == "agent":
        _strict(method.get("fresh"), "language review review_method.fresh")
        dispatch = method.get("dispatch")
        expected_surface = AGENT_REVIEW_SURFACES.get(state.get("host"))
        if not isinstance(dispatch, dict) or dispatch.get("surface") != expected_surface:
            _error("language review agent review_method surface must match the run host")
        if state.get("host") == "codex":
            if dispatch.get("fork_turns") != "none":
                _error("language review codex agent requires fork_turns=none")
        elif dispatch.get("fresh_context") is not True or not isinstance(dispatch.get("session_id"), str) or not dispatch["session_id"]:
            _error("language review non-Codex agent requires a fresh context and session ID")
    elif kind == "human":
        _str(method.get("reviewer"), "language review human reviewer")
    else:
        _error("language review review_method kind must be human or agent")
    execution = data.get("execution_record")
    execution_data = _bound_json_run_record(run, execution, "language review execution_record")
    if (not isinstance(execution, dict) or execution.get("reviewer_id") != reviewer or execution.get("method") != kind or
            execution_data.get("reviewer_id") != reviewer or execution_data.get("method") != kind):
        _error("language review execution_record must bind the reviewer and review method")
    if kind == "agent" and (execution_data.get("fresh") is not True or execution_data.get("dispatch") != method.get("dispatch")):
        _error("language review execution_record must bind the fresh native dispatch")
    if kind == "human" and execution_data.get("reviewer") != method.get("reviewer"):
        _error("language review execution_record must identify the human reviewer")
    preservation = data.get("meaning_preservation")
    if not isinstance(preservation, dict) or set(preservation) != set(MEANING_PRESERVATION_FIELDS):
        _error("language review meaning_preservation must contain the six required fields")
    for field in MEANING_PRESERVATION_FIELDS:
        _strict(preservation.get(field), f"language review meaning_preservation.{field}")
    if _list(data.get("blockers"), "language review blockers") != []: _error("language review blockers must be empty")
    if _list(data.get("remaining_findings"), "language review remaining_findings") != []:
        _error("language review remaining_findings must be empty")
    records = _list(data.get("independent_review_evidence"), "language review independent_review_evidence")
    if not records: _error("language review needs a separate human or agent review record")
    for record in records:
        if not isinstance(record, dict) or record.get("kind") not in {"human", "agent"}:
            _error("language review record must identify a human or agent")
        if _str(record.get("reviewer_id"), "language review record.reviewer_id") != reviewer:
            _error("language review record reviewer_id must match the independent reviewer")
        _bound_run_record(run, record, "language review record")


def _validate_supported_spec(path: Path) -> None:
    """Reject a changed DAG that this deliberately sequential helper cannot run."""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        tasks = _list(spec.get("tasks"), "spec.tasks")
        roles = _list(spec.get("roles"), "spec.roles")
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        _error(f"invalid harness specification: {exc}")
    owners = {role.get("name") for role in roles if isinstance(role, dict) and isinstance(role.get("name"), str)}
    by_id: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, dict): _error("spec task must be an object")
        task_id = _str(task.get("id"), "spec task.id")
        if task_id in by_id: _error("spec task ids must be unique")
        by_id[task_id] = task
    if set(by_id) != set(STAGES): _error("spec task ids do not match supported stages")
    for task_id, task in by_id.items():
        if task.get("required") is not True: _error(f"spec stage must be required: {task_id}")
        if task.get("owner") not in owners: _error(f"spec stage owner is missing: {task_id}")
        deps = set(_list(task.get("depends_on"), f"spec {task_id}.depends_on"))
        if any(not isinstance(dep, str) for dep in deps) or deps != EXPECTED_DEPENDENCIES[task_id]:
            _error(f"unsupported dependencies for stage: {task_id}")
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(task_id: str) -> None:
        if task_id in visiting: _error("spec task dependencies contain a cycle")
        if task_id in visited: return
        visiting.add(task_id)
        for dep in by_id[task_id]["depends_on"]: visit(dep)
        visiting.remove(task_id); visited.add(task_id)
    for task_id in STAGES: visit(task_id)


def _source_hashes(state: dict[str, Any]) -> dict[str, str]:
    return {path: sha256_file(Path(path)) for path in state["sources"]}


def _run_file(run: Path, value: Any, label: str) -> Path:
    path = ensure_relative(run, _str(value, label))
    if path.is_symlink() or not path.is_file():
        _error(f"{label} must name an existing non-symlink run file")
    return path


def _artifact_file(state: dict[str, Any], run: Path, entry: Any, label: str) -> tuple[str, str, str]:
    if not isinstance(entry, dict):
        _error(f"{label} entries must be objects")
    name = _str(entry.get("path"), f"{label}.path")
    expected = _str(entry.get("sha256"), f"{label}.sha256")
    scope = entry.get("scope", "project")
    if scope == "run":
        path = ensure_relative(run, name)
    elif scope == "project":
        path = ensure_relative(Path(state["project"]), name)
    elif scope == "source":
        path = Path(name)
        if not path.is_absolute() or str(path.resolve(strict=False)) not in state["sources"]:
            _error(f"{label}.path must name a declared absolute source")
    else:
        _error(f"{label}.scope must be project, run, or source")
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
        _error(f"{label} hash mismatch: {name}")
    return str(scope), name, expected


def _run_artifact(run: Path, value: Any, label: str) -> tuple[str, str, str]:
    path = _run_file(run, value, label)
    return "run", _str(value, label), sha256_file(path)


def _evidence_artifacts(state: dict[str, Any], stage: str, data: dict[str, Any], run: Path) -> list[dict[str, str]]:
    """Bind every referenced child artifact, including nested explicit artifacts."""
    found: dict[tuple[str, str], str] = {}

    def add(item: tuple[str, str, str]) -> None:
        key = item[:2]
        if key in found and found[key] != item[2]:
            _error(f"artifact is declared with conflicting hashes: {item[1]}")
        found[key] = item[2]

    if stage == "behavior-tests":
        for case in data["cases"]:
            for key in ("input_file", "answer_file", "rubric_file"):
                add(_run_artifact(run, case[key], f"case.{key}"))
            for entry in case.get("read_files", []):
                add(_artifact_file(state, run, entry, "case.read_files"))
    if stage == "host-smoke":
        add(_run_artifact(run, data["trace_file"], "host.trace_file"))
        add(_run_artifact(run, data["raw_trace_file"], "host.raw_trace_file"))
        add(_run_artifact(run, data["answer_file"], "host.answer_file"))
        for proof in data["proof_files"]:
            add(_artifact_file(state, run, {**proof, "scope": "run"}, "proof_files"))
    if stage == "language-review":
        for record in data["independent_review_evidence"]:
            add(_run_artifact(run, record["path"], "language review record.path"))
        for record in data["pipeline_records"]:
            add(_run_artifact(run, record["path"], "language review pipeline record.path"))
        add(_run_artifact(run, data["read_manifest"]["path"], "language review read_manifest.path"))
        add(_run_artifact(run, data["execution_record"]["path"], "language review execution_record.path"))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "evidence_artifacts" in value:
                for entry in _list(value["evidence_artifacts"], "evidence_artifacts"):
                    add(_artifact_file(state, run, entry, "evidence_artifacts"))
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(data)
    return [{"scope": scope, "path": path, "sha256": digest}
            for (scope, path), digest in sorted(found.items())]


def _verify_artifacts(state: dict[str, Any], run: Path, record: dict[str, Any]) -> None:
    for artifact in record.get("artifacts", []):
        _artifact_file(state, run, artifact, "bound artifact")


def _archive_evidence(run: Path, stage: str, number: int, evidence_path: Path,
                      artifacts: list[dict[str, str]]) -> dict[str, Any]:
    """Copy run-owned evidence bytes once; source/project reads remain in place."""
    root = run / "evidence-archive" / stage / str(number)
    root.mkdir(parents=True, exist_ok=False)
    archived_evidence = root / "evidence.json"
    shutil.copyfile(evidence_path, archived_evidence)
    archived: list[dict[str, str]] = []
    for artifact in artifacts:
        if artifact["scope"] != "run":
            continue
        source = ensure_relative(run, artifact["path"])
        destination = root / "artifacts" / artifact["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        archived.append({"path": destination.relative_to(run).as_posix(), "sha256": sha256_file(destination)})
    return {"evidence": {"path": archived_evidence.relative_to(run).as_posix(), "sha256": sha256_file(archived_evidence)},
            "artifacts": archived}


def _verify_archive(run: Path, record: dict[str, Any]) -> None:
    archive = record.get("archive")
    if not isinstance(archive, dict): _error("evidence archive is missing")
    evidence = archive.get("evidence")
    if not isinstance(evidence, dict): _error("archived evidence metadata is missing")
    path = _run_file(run, evidence.get("path"), "archive.evidence.path")
    if sha256_file(path) != evidence.get("sha256"): _error("archived evidence hash mismatch")
    for artifact in archive.get("artifacts", []):
        if not isinstance(artifact, dict): _error("archived artifact metadata is invalid")
        path = _run_file(run, artifact.get("path"), "archive.artifact.path")
        if sha256_file(path) != artifact.get("sha256"): _error("archived artifact hash mismatch")


def _inventory_ids(state: dict[str, Any]) -> set[str]:
    record = state["stages"]["inventory"].get("evidence")
    if not record:
        _error("inventory evidence is unavailable")
    data = _read_evidence(Path(state["run_dir"]), record)
    return set(data["expected_unit_ids"])


def _finding_ids(state: dict[str, Any], run: Path) -> set[str]:
    data = _read_evidence(run, state["stages"]["source-audit"]["evidence"])
    return ({f"claim:{x['id']}" for x in data["claims"] if x["verdict"] == "mismatch"} |
            {f"unit:{x['id']}" for x in data["units"] if x["verdict"] == "needs-refinement"})


def _validate_evidence(state: dict[str, Any], stage: str, data: Any, run: Path) -> None:
    if not isinstance(data, dict):
        _error("evidence must be a JSON object")
    if data.get("verdict") != "pass":
        _error("successful evidence verdict must be 'pass'")
    producer = state.get("producer_id")
    if stage == "preflight":
        if (data.get("project") != state["project"] or data.get("skill_rel") != state["skill_rel"] or
                data.get("source_hashes") != state["source_hashes"] or
                data.get("write_paths") != [state["skill_rel"], *state["documents"]]):
            _error("preflight does not match initialized scope")
        _strict(data.get("scope_confirmed"), "preflight.scope_confirmed")
    elif stage == "inventory":
        expected = _list(data.get("expected_unit_ids"), "expected_unit_ids")
        if not expected or any(not isinstance(x, str) or not x for x in expected) or len(expected) != len(set(expected)):
            _error("expected_unit_ids must be non-empty unique strings")
        units = _list(data.get("units"), "units")
        if len(units) != len(expected): _error("units must exactly match expected_unit_ids")
        for unit in units:
            if not isinstance(unit, dict): _error("inventory unit must be an object")
            for field in ("id", "source_path", "source_locator"):
                _str(unit.get(field), f"unit.{field}")
            source_path = Path(unit["source_path"])
            if not source_path.is_absolute() or str(source_path.resolve(strict=False)) not in state["sources"]:
                _error("unit.source_path must be a declared absolute source")
            if sha256_file(source_path) != state["source_hashes"].get(str(source_path.resolve())):
                _error("unit.source_path source hash changed")
            skill_files = _list(unit.get("skill_files"), "unit.skill_files")
            if unit.get("status") not in {"mapped", "missing", "excluded"}: _error("invalid inventory unit status")
            if unit["status"] in {"missing", "excluded"}: _str(unit.get("reason"), "unmapped unit.reason")
            skill_root = ensure_relative(Path(state["project"]), state["skill_rel"])
            for raw in skill_files:
                item = ensure_relative(Path(state["project"]), _str(raw, "unit.skill_files path"))
                if not item.is_relative_to(skill_root): _error("unit.skill_files path is outside target skill")
                if unit["status"] != "missing" and (item.is_symlink() or not item.is_file()):
                    _error("mapped/excluded skill file must exist and be regular")
        _exact_ids(units, set(expected), "units")
    elif stage == "source-audit":
        expected = _inventory_ids(state)
        _exact_ids(data.get("units"), expected, "audit.units")
        for unit in data["units"]:
            if not isinstance(unit, dict) or unit.get("verdict") not in {"pass", "needs-refinement"}:
                _error("audit unit needs a pass or needs-refinement verdict")
        for claim in _list(data.get("claims"), "claims"):
            if not isinstance(claim, dict): _error("claim must be an object")
            for field in ("id", "unit_id", "origin", "source_locator", "verdict"):
                _str(claim.get(field), f"claim.{field}")
            if (claim["unit_id"] not in expected or claim["origin"] not in
                    {"author", "synthesis", "validation-guidance", "proposal"}):
                _error("invalid claim unit_id or origin")
            if claim["verdict"] not in {"pass", "mismatch", "uncertain"}:
                _error("claim verdict must be pass, mismatch, or uncertain")
        claims = data["claims"]
        if not claims or {claim["unit_id"] for claim in claims} != expected:
            _error("source audit needs at least one claim for every inventory unit")
        _list(data.get("visual_candidates"), "visual_candidates")
        _list(data.get("visual_checks"), "visual_checks")
        _independent_id(data.get("reviewer_id"), "source audit reviewer_id", producer)
    elif stage in {"skill-refinement", "improvement"}:
        expected = _inventory_ids(state)
        _exact_ids(data.get("units_covered"), expected, "units_covered")
        changes = _list(data.get("changes"), "changes")
        for change in changes:
            path_text = change if isinstance(change, str) else change.get("path") if isinstance(change, dict) else None
            path = ensure_relative(Path(state["project"]), _str(path_text, "change.path"))
            allowed = [ensure_relative(Path(state["project"]), p) for p in [state["skill_rel"], *state.get("documents", [])]]
            if not any(path == parent or path.is_relative_to(parent) for parent in allowed): _error("change path is outside declared write set")
        if stage == "skill-refinement":
            expected_findings = _finding_ids(state, run); ids = set()
            for resolution in _list(data.get("resolutions"), "resolutions"):
                if not isinstance(resolution, dict): _error("resolution must be an object")
                item_id = _str(resolution.get("id"), "resolution.id"); ids.add(item_id)
                if resolution.get("kind") not in {"fixed", "documented", "false-positive"}: _error("invalid resolution kind")
                _str(resolution.get("reason"), "resolution.reason")
                for raw in _list(resolution.get("paths"), "resolution.paths"):
                    path = ensure_relative(Path(state["project"]), _str(raw, "resolution.path"))
                    if path.is_symlink() or not path.is_file(): _error("resolution path must be a regular project file")
            if ids != expected_findings: _error("resolutions must exactly cover source-audit findings")
        if stage == "improvement" and data.get("revisions") != state.get("revisions"):
            _error("improvement evidence revisions must equal state revisions")
    elif stage == "documentation":
        _exact_ids(data.get("units_covered"), _inventory_ids(state), "units_covered")
        prompts = _list(data.get("reviewed_prompt_ids"), "reviewed_prompt_ids")
        if not prompts or any(not isinstance(item, str) or not item for item in prompts): _error("reviewed_prompt_ids must be non-empty strings")
    elif stage == "static-checks":
        if _list(data.get("errors"), "errors") != []: _error("static checks errors must be empty")
        snapshot = package_snapshot(state); scanned = {}
        for item in _list(data.get("scanned_files"), "scanned_files"):
            if not isinstance(item, dict): _error("scanned file must be an object")
            path = _str(item.get("path"), "scanned_file.path")
            if path in scanned: _error("scanned file paths must be unique")
            scanned[path] = _str(item.get("sha256"), "scanned_file.sha256")
        if (scanned != snapshot["files"] or data.get("files_digest") != snapshot["digest"] or
                data.get("project") != state["project"] or data.get("skill", data.get("skill_rel")) != state["skill_rel"]):
            _error("static check does not match current subject")
    elif stage == "behavior-tests":
        cases = _list(data.get("cases"), "cases")
        kinds: set[str] = set()
        case_ids: set[str] = set()
        for case in cases:
            if not isinstance(case, dict): _error("behavior case must be an object")
            case_id = _str(case.get("id"), "case.id")
            if case_id in case_ids: _error("behavior case ids must be unique")
            case_ids.add(case_id)
            kind = _str(case.get("kind"), "case.kind"); kinds.add(kind)
            if kind not in {"retrieval", "application", "critique", "regression"}: _error("unknown behavior case kind")
            if case.get("verdict") != "pass": _error("behavior case verdict must pass")
            _strict(case.get("fresh"), "case.fresh")
            _independent_id(case.get("evaluator_id"), "case.evaluator_id", producer)
            _run_file(run, case.get("input_file"), "case.input_file")
            _run_file(run, case.get("answer_file"), "case.answer_file")
            _run_file(run, case.get("rubric_file"), "case.rubric_file")
            assertions = _list(case.get("assertions"), "case.assertions")
            if not assertions: _error("case needs assertions")
            for assertion in assertions:
                if not isinstance(assertion, dict): _error("case assertions must be objects")
                _str(assertion.get("id"), "assertion.id")
                _strict(assertion.get("passed"), "assertion.passed")
                _str(assertion.get("reason"), "assertion.reason")
            for item in _list(case.get("read_files"), "case.read_files"):
                _artifact_file(state, run, item, "case.read_files")
        if not {"retrieval", "application", "critique"}.issubset(kinds): _error("behavior cases need retrieval, application, and critique")
        if state.get("revisions", 0):
            prior_ids: set[str] = set()
            behavior = state["stages"]["behavior-tests"]
            for prior in behavior.get("evidence_history", []):
                # A committed result is its own archive entry, not a previous evaluation.
                if behavior["status"] == "succeeded" and prior == behavior.get("evidence"):
                    continue
                archive = prior.get("archive", {}).get("evidence", {})
                try:
                    old = json.loads(_run_file(run, archive.get("path"), "behavior archive").read_text(encoding="utf-8"))
                    prior_ids.update(case["evaluator_id"] for case in old.get("cases", []) if isinstance(case, dict))
                except (StateError, OSError, json.JSONDecodeError, KeyError):
                    _error("prior behavior evidence archive is invalid")
            if prior_ids & {case["evaluator_id"] for case in cases}:
                _error("post-revision behavior tests require a new evaluator_id")
    elif stage == "language-review":
        _validate_language_review_evidence(state, data, run)
    elif stage == "freeze":
        _independent_id(data.get("reviewer_id"), "freeze reviewer_id", producer)
        if _list(data.get("blockers"), "blockers") != []: _error("freeze blockers must be empty")
        _exact_ids(data.get("addressed_findings"), _finding_ids(state, run), "freeze.addressed_findings")
        if not _list(data.get("independent_review_evidence"), "freeze.independent_review_evidence"):
            _error("freeze needs independent review evidence")
    elif stage == "host-smoke":
        if data.get("host") != state["host"]: _error("host evidence host differs from state")
        code = data.get("returncode")
        if isinstance(code, bool) or code != 0: _error("host returncode must be integer 0")
        _strict(data.get("loaded"), "host.loaded"); _strict(data.get("turn_completed"), "host.turn_completed")
        if state.get("host_attempts") != 1: _error("host evidence requires exactly one claimed attempt")
        trace = _run_file(run, data.get("trace_file"), "host.trace_file")
        if sha256_file(trace) != _str(data.get("trace_sha256"), "host.trace_sha256"):
            _error("host trace hash mismatch")
        raw_trace = _run_file(run, data.get("raw_trace_file"), "host.raw_trace_file")
        if sha256_file(raw_trace) != _str(data.get("raw_trace_sha256"), "host.raw_trace_sha256"):
            _error("host raw trace hash mismatch")
        answer = _run_file(run, data.get("answer_file"), "host.answer_file")
        try:
            answer_text = answer.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            _error(f"host answer must be UTF-8: {exc}")
        if not answer_text.strip(): _error("host answer must be non-empty")
        if sha256_file(answer) != _str(data.get("answer_sha256"), "host.answer_sha256"):
            _error("host answer hash mismatch")
        try:
            terminal = final_answer(json_events(raw_trace.read_text(encoding="utf-8")), state["host"])
        except UnicodeDecodeError as exc:
            _error(f"host raw trace must be UTF-8: {exc}")
        if terminal is None:
            _error("host raw trace has no final host answer event")
        expected_answer, expected_event_id = terminal
        if data.get("answer_event_id") != expected_event_id or answer_text != expected_answer:
            _error("host answer does not match the raw trace terminal answer")
        project_root = Path(state["project"]).resolve(strict=True)
        source_skill = ensure_relative(project_root, state["skill_rel"])
        source_digest, source_files = _regular_tree(source_skill, "frozen source skill")
        skill_id = Path(state["skill_rel"]).name
        copied_skill_root = run / "host" / "project" / ".agents" / "skills" / skill_id
        copy_digest, copied_files = _regular_tree(copied_skill_root, "host copied skill")
        source_master = source_skill / "SKILL.md"
        copied_master = copied_skill_root / "SKILL.md"
        if (source_master.is_symlink() or copied_master.is_symlink() or not source_master.is_file() or not copied_master.is_file() or
                sha256_file(source_master) != sha256_file(copied_master)):
            _error("host copied master SKILL.md differs from the frozen source")
        if (data.get("copy_digest") != copy_digest or data.get("copied_files") != copied_files or
                source_digest != copy_digest or source_files != copied_files):
            _error("host copied skill tree does not exactly match the frozen source")
        proofs = _list(data.get("proof_files"), "proof_files")
        if not proofs: _error("host proof_files cannot be empty")
        expected_master = copied_master.relative_to(run).as_posix()
        copied_master_proven = False
        for proof in proofs:
            if not isinstance(proof, dict): _error("proof file must be an object")
            path = _run_file(run, proof.get("path"), "proof.path")
            if sha256_file(path) != _str(proof.get("sha256"), "proof.sha256"): _error("proof file hash mismatch")
            copied_master_proven = copied_master_proven or path.relative_to(run).as_posix() == expected_master
        if not copied_master_proven: _error("host proof must include the exact copied master SKILL.md")
        try:
            trace_data = json.loads(trace.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _error(f"host trace must be JSON: {exc}")
        events = trace_data.get("events", []) if isinstance(trace_data, dict) else trace_data
        copied_project = run / "host" / "project"
        if copied_project.is_symlink() or not copied_project.is_dir(): _error("host copied project is unavailable")
        derived_events = normalized_events(state["host"], json_events(raw_trace.read_text(encoding="utf-8")), copied_project)
        if not isinstance(events, list) or events != derived_events:
            _error("host normalized trace does not exactly match the raw trace")
        if not any(event.get("type") == "turn.completed" for event in derived_events):
            _error("host raw trace lacks turn.completed")
        read_paths = {str(Path(event["path"]).resolve()) for event in derived_events
                      if event.get("type") == "tool.read" and event.get("success") is True}
        if str(copied_master.resolve()) not in read_paths:
            _error("host raw trace lacks a successful read of the exact copied master SKILL.md")
        if state["host"] == "claude" and data.get("native_skill_load") is not (str(copied_master.resolve()) in
                claude_skill_load_paths(json_events(raw_trace.read_text(encoding="utf-8")), copied_project)):
            _error("host native_skill_load does not match the raw trace")
    elif stage == "final-review":
        _independent_id(data.get("reviewer_id"), "final reviewer_id", producer)
        if _list(data.get("blockers"), "blockers") != []: _error("final review blockers must be empty")
        _strict(data.get("post_host"), "final-review.post_host")
    if stage in CHECK_STAGES and data.get("subject_digest") != _current_digest(state):
        _error("evidence subject_digest does not match current subject")


def _read_evidence(run: Path, record: dict[str, Any]) -> dict[str, Any]:
    path = _run_file(run, record.get("path"), "evidence.path")
    if sha256_file(path) != record.get("sha256"):
        _error(f"evidence was modified: {record.get('path')}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"invalid evidence JSON: {path}") from exc
    if not isinstance(value, dict): _error("evidence must be a JSON object")
    return value


def _invalidate(state: dict[str, Any], names: list[str], reason: str) -> None:
    for name in names:
        record = state["stages"][name]
        if record["status"] == "succeeded":
            record["status"] = "stale"
            record.setdefault("history", []).append({"event": "stale", "reason": reason, "at": _now()})


def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    project_raw = Path(args.project)
    if not project_raw.is_absolute() or project_raw.is_symlink() or not project_raw.is_dir(): _error("project must be an absolute non-symlink directory")
    project = project_raw.resolve(strict=True)
    skill = ensure_relative(project, args.skill)
    if skill.is_symlink() or not skill.is_dir(): _error("skill must be an existing non-symlink directory inside project")
    sources = []
    for raw in args.source:
        source = Path(raw)
        if not source.is_absolute() or source.is_symlink() or not source.is_file(): _error("source must be an absolute non-symlink regular file")
        sources.append(str(source.resolve(strict=True)))
    documents: list[str] = []
    for raw in args.documents or []:
        doc = ensure_relative(project, raw)
        if doc.exists() and (doc.is_symlink() or not (doc.is_file() or doc.is_dir())):
            _error("existing document must be a regular file or directory, never a symlink")
        documents.append(doc.relative_to(project).as_posix())
    skill_rel = skill.relative_to(project).as_posix()
    scripts_root = Path(__file__).resolve().parent.parent
    spec = scripts_root / "references" / "harness-spec.json"
    if not spec.is_file(): _error("installed harness specification is missing")
    _validate_supported_spec(spec)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    producer = args.producer_id.strip() if isinstance(args.producer_id, str) else ""
    if args.producer_id is not None and not producer: _error("producer-id must not be blank")
    run = project / "_workspace" / "harness" / "book-to-skill-followup" / run_id
    run.mkdir(parents=True, exist_ok=False)
    state: dict[str, Any] = {"schema": 1, "run_dir": str(run), "project": str(project), "skill_rel": skill_rel,
        "documents": documents, "sources": sources, "source_hashes": {p: sha256_file(Path(p)) for p in sources},
        "spec_path": str(spec), "spec_sha256": sha256_file(spec), "toolchain": workflow_snapshot(scripts_root), "host": args.host,
        "producer_id": producer or f"coordinator:{run_id}", "created_at": _now(), "subject": {}, "freeze_snapshot": None,
        "host_attempts": 0, "revisions": 0, "finalized": False, "events": [{"event": "init", "at": _now()}],
        "stages": {name: {"status": "pending", "restarts": 0, "history": []} for name in STAGES}}
    state["subject"] = package_snapshot(state)
    # Atomic initial creation is enough: the unique run directory has no peers yet.
    (run / "run.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"run_dir": str(run), "subject_digest": state["subject"]["digest"]}


def _require_startable(state: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage not in STAGES: _error("unknown stage")
    record = state["stages"][stage]
    if record["status"] not in {"pending", "failed", "stale"}: _error("stage is not startable")
    index = STAGES.index(stage)
    if any(state["stages"][prior]["status"] != "succeeded" for prior in STAGES[:index]): _error("all prior stages must have succeeded")
    if stage == "host-smoke" and state.get("host_attempts") not in {0, 1}:
        _error("host attempt bookkeeping is invalid")
    if record["status"] == "failed":
        if stage == "host-smoke" or record["restarts"] >= 1: _error("retry limit reached")
        record["restarts"] += 1
    return record


def _fixed_inputs_changed(state: dict[str, Any]) -> bool:
    spec = Path(state["spec_path"])
    return (not spec.is_file() or sha256_file(spec) != state["spec_sha256"] or
            _source_hashes(state) != state["source_hashes"] or
            workflow_snapshot(Path(__file__).resolve().parent.parent) != state["toolchain"])


def cmd_start(args: argparse.Namespace) -> dict[str, Any]:
    def action(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("finalized"): _error("run already finalized")
        if _fixed_inputs_changed(state): _error("source, specification, or toolchain changed; run resume first")
        record = _require_startable(state, args.stage)
        record["status"] = "running"; record["history"].append({"event": "start", "at": _now()})
        return {"stage": args.stage, "status": "running"}
    return mutate_state(Path(args.run_dir), action)


def cmd_finish(args: argparse.Namespace) -> dict[str, Any]:
    run = Path(args.run_dir).resolve(strict=True)
    evidence_path = _run_file(run, args.evidence, "evidence")
    try: data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc: raise StateError("evidence is not valid JSON") from exc
    def action(state: dict[str, Any]) -> dict[str, Any]:
        if args.stage not in STAGES or state["stages"][args.stage]["status"] != "running": _error("only a running stage can finish")
        if _fixed_inputs_changed(state): _error("source, specification, or toolchain changed; evidence cannot finish")
        _validate_evidence(state, args.stage, data, run)
        record = state["stages"][args.stage]
        artifacts = _evidence_artifacts(state, args.stage, data, run)
        prior = state["stages"][args.stage].get("evidence_history", [])
        archive = _archive_evidence(run, args.stage, len(prior) + 1, evidence_path, artifacts)
        evidence = {"path": args.evidence, "sha256": sha256_file(evidence_path), "artifacts": artifacts,
                    "archive": archive, "finished_at": _now()}
        record["evidence"] = evidence; record["status"] = "succeeded"; record["history"].append({"event": "finish", **evidence})
        record.setdefault("evidence_history", []).append(evidence)
        if args.stage == "freeze": state["freeze_snapshot"] = package_snapshot(state)
        state["subject"] = package_snapshot(state)
        return {"stage": args.stage, "status": "succeeded"}
    return mutate_state(run, action)


def cmd_fail(args: argparse.Namespace) -> dict[str, Any]:
    def action(state: dict[str, Any]) -> dict[str, Any]:
        if args.stage not in STAGES or state["stages"][args.stage]["status"] != "running": _error("only a running stage can fail")
        reason = _str(args.reason, "reason")
        record = state["stages"][args.stage]; record["status"] = "failed"; record["history"].append({"event": "fail", "reason": reason, "at": _now()})
        return {"stage": args.stage, "status": "failed"}
    return mutate_state(Path(args.run_dir), action)


def cmd_revise(args: argparse.Namespace) -> dict[str, Any]:
    def action(state: dict[str, Any]) -> dict[str, Any]:
        if args.from_stage not in REVISION_STAGES: _error("revision must start at skill-refinement or documentation")
        if state.get("revisions", 0) >= 2: _error("maximum revisions reached")
        if state["stages"]["freeze"]["status"] == "succeeded": _error("cannot revise after freeze")
        _str(args.reason, "reason")
        state["revisions"] += 1
        start = STAGES.index(args.from_stage)
        for name in STAGES[start:]:
            record = state["stages"][name]
            if record["status"] != "pending":
                record["status"] = "stale"; record["history"].append({"event": "revise", "reason": args.reason, "at": _now()})
        return {"revisions": state["revisions"], "from_stage": args.from_stage}
    return mutate_state(Path(args.run_dir), action)


def _verify(state: dict[str, Any], run: Path, require_complete: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        if _source_hashes(state) != state.get("source_hashes"): errors.append("source hashes changed")
    except Exception as exc: errors.append(str(exc))
    spec = Path(state["spec_path"])
    if not spec.is_file() or sha256_file(spec) != state.get("spec_sha256"):
        errors.append("specification changed")
    skill_root = Path(__file__).resolve().parent.parent
    if workflow_snapshot(skill_root) != state.get("toolchain"): errors.append("toolchain changed")
    try:
        current = package_snapshot(state)
        if current != state.get("subject"): errors.append("subject changed; run resume")
    except Exception as exc: errors.append(str(exc))
    for stage in STAGES:
        record = state["stages"][stage]
        if require_complete and record["status"] != "succeeded": errors.append(f"{stage} is {record['status']}")
        if record["status"] == "succeeded":
            try:
                evidence = _read_evidence(run, record["evidence"])
                _verify_artifacts(state, run, record["evidence"])
                _verify_archive(run, record["evidence"])
                _validate_evidence(state, stage, evidence, run)
            except Exception as exc: errors.append(f"{stage}: {exc}")
        for evidence in record.get("evidence_history", []):
            try: _verify_archive(run, evidence)
            except Exception as exc: errors.append(f"{stage} archive: {exc}")
    return errors


def cmd_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    state = load_state(Path(args.run_dir)); return package_snapshot(state)


def cmd_verify(args: argparse.Namespace) -> dict[str, Any]:
    run = Path(args.run_dir).resolve(strict=True); state = load_state(run); errors = _verify(state, run)
    return {"ok": not errors, "errors": errors}


def cmd_resume(args: argparse.Namespace) -> dict[str, Any]:
    def action(state: dict[str, Any]) -> dict[str, Any]:
        run = Path(state["run_dir"])
        spec = Path(state["spec_path"])
        preflight_stale = (not spec.is_file() or sha256_file(spec) != state.get("spec_sha256") or
                           _source_hashes(state) != state.get("source_hashes") or
                           workflow_snapshot(Path(__file__).resolve().parent.parent) != state.get("toolchain"))
        current = package_snapshot(state)
        if preflight_stale:
            _invalidate(state, STAGES, "source or toolchain changed")
            state["source_hashes"] = _source_hashes(state)
            state["spec_sha256"] = sha256_file(spec)
            state["toolchain"] = workflow_snapshot(Path(__file__).resolve().parent.parent)
        elif current != state.get("subject"):
            _invalidate(state, ["static-checks", "behavior-tests", "improvement", "language-review", "freeze", "host-smoke", "final-review"], "subject changed")
        state["subject"] = current
        return {"preflight_stale": preflight_stale, "subject_digest": current["digest"], "statuses": {x: state["stages"][x]["status"] for x in STAGES}}
    return mutate_state(Path(args.run_dir), action)


def cmd_claim_host(args: argparse.Namespace) -> dict[str, Any]:
    state = claim_host(Path(args.run_dir)); return {"host_attempts": state["host_attempts"], "host": state["host"]}


def cmd_finalize(args: argparse.Namespace) -> dict[str, Any]:
    def action(state: dict[str, Any]) -> dict[str, Any]:
        run = Path(state["run_dir"])
        errors = _verify(state, run, require_complete=True)
        if state.get("freeze_snapshot") != package_snapshot(state): errors.append("frozen subject changed")
        if errors: _error("cannot finalize: " + "; ".join(errors))
        state["finalized"] = True; state["finalized_at"] = _now()
        return {"finalized": True}
    return mutate_state(Path(args.run_dir), action)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); init.add_argument("--project", required=True); init.add_argument("--skill", required=True)
    init.add_argument("--source", action="append", required=True); init.add_argument("--documents", action="append", default=[])
    init.add_argument("--host", choices=("codex", "claude", "antigravity"), required=True); init.add_argument("--producer-id")
    for name in ("start", "fail"):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True); p.add_argument("--stage", required=True)
        if name == "fail": p.add_argument("--reason", required=True)
    finish = sub.add_parser("finish"); finish.add_argument("--run-dir", required=True); finish.add_argument("--stage", required=True); finish.add_argument("--evidence", required=True)
    revise = sub.add_parser("revise"); revise.add_argument("--run-dir", required=True); revise.add_argument("--from-stage", required=True, choices=sorted(REVISION_STAGES)); revise.add_argument("--reason", required=True)
    for name in ("snapshot", "verify", "resume", "finalize", "claim-host"):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = {"init": cmd_init, "start": cmd_start, "finish": cmd_finish, "fail": cmd_fail,
                  "revise": cmd_revise, "snapshot": cmd_snapshot, "verify": cmd_verify, "resume": cmd_resume,
                  "claim-host": cmd_claim_host, "finalize": cmd_finalize}[args.command](args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("ok", True) else 1
    except (StateError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
