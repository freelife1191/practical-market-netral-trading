"""Small, local-only state primitives for the book-to-skill follow-up harness."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

try:  # macOS and Linux, which are the supported harness hosts.
    import fcntl
except ImportError:  # pragma: no cover - documented unsupported locking platform
    fcntl = None


class StateError(ValueError):
    """Raised when a run state or its requested transition is invalid."""


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 for a regular file."""
    if not path.is_file():
        raise StateError(f"regular file required: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(files: dict[str, str]) -> str:
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def ensure_relative(root: Path, path: str | Path) -> Path:
    """Resolve *path* under *root*, rejecting escapes and every selected symlink."""
    root = root.resolve(strict=True)
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise StateError(f"relative path required: {path}")
    selected = root
    # `Path.resolve()` erases a symlink from the spelling, so inspect each supplied
    # component before resolving.  The canonical root itself is intentionally allowed.
    for part in candidate.parts:
        if part in {"", "."}:
            continue
        selected = selected / part
        if selected.is_symlink():
            raise StateError(f"symlink is not allowed in selected path: {path}")
    resolved = selected.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StateError(f"path escapes root: {path}") from exc
    return resolved


def _regular_files(root: Path, excludes: set[str] | None = None) -> dict[str, str]:
    """Snapshot regular files below root. Symlinks are never followed."""
    excludes = excludes or set()
    files: dict[str, str] = {}
    for item in sorted(root.rglob("*")):
        rel = _relative(root, item)
        if any(part in excludes for part in Path(rel).parts):
            if item.is_symlink():
                raise StateError(f"excluded cache path must not be a symlink: {item}")
            continue
        if item.is_symlink():
            raise StateError(f"symlink is not allowed in snapshot: {item}")
        if item.is_file():
            files[rel] = sha256_file(item)
    return files


def workflow_snapshot(skill_root: Path) -> dict[str, Any]:
    """Fingerprint the installed follow-up skill, excluding mutable caches/runs."""
    skill_root = skill_root.resolve(strict=True)
    files = _regular_files(skill_root, {"cache", "__pycache__", ".pytest_cache", "_workspace"})
    return {"files": files, "digest": _digest(files)}


def package_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Snapshot the declared target skill, documents, and local host profiles."""
    project = Path(state["project"]).resolve(strict=True)
    selected = [state["skill_rel"], *state.get("documents", [])]
    files: dict[str, str] = {}
    for declared in selected:
        item = ensure_relative(project, declared)
        # Documentation can be an approved future output.  Its absence is therefore
        # represented by no files and becomes a digest change when it is created.
        if not item.exists() and declared == state["skill_rel"]:
            raise StateError(f"target skill disappeared: {declared}")
        if not item.exists():
            continue
        if item.is_symlink():
            raise StateError(f"declared subject is a symlink: {declared}")
        if item.is_file():
            files[_relative(project, item)] = sha256_file(item)
        else:
            for relative, digest in _regular_files(item, {"__pycache__", ".pytest_cache"}).items():
                files[_relative(project, item / relative)] = digest
    # Static compatibility checks cover every shipped host profile.
    for profile_rel in (".codex/agents", ".claude/agents", ".agents/agents"):
        profile = ensure_relative(project, profile_rel)
        if not profile.exists():
            continue
        if profile.is_symlink() or not profile.is_dir():
            raise StateError(f"selected host profile is invalid: {profile}")
        for relative, digest in _regular_files(profile, {"__pycache__", ".pytest_cache"}).items():
            files[_relative(project, profile / relative)] = digest
    return {"files": dict(sorted(files.items())), "digest": _digest(dict(sorted(files.items())))}


def load_state(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir).resolve(strict=True) / "run.json"
    if not path.is_file():
        raise StateError(f"missing run state: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"invalid run state JSON: {path}") from exc


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, name = tempfile.mkstemp(prefix=".run-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def mutate_state(run_dir: Path, action: Callable[[dict[str, Any]], Any]) -> Any:
    """Run one read-modify-write transition under a per-run advisory file lock.

    `fcntl.flock` is available on the supported macOS/Linux hosts. Other platforms
    fail closed instead of pretending a host claim is exclusive.
    """
    if fcntl is None:
        raise StateError("file locking requires fcntl (macOS/Linux)")
    run_dir = Path(run_dir).resolve(strict=True)
    lock_path = run_dir / "run.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            state = load_state(run_dir)
            result = action(state)
            _atomic_json(run_dir / "run.json", state)
            return result
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def claim_host(run_dir: Path) -> dict[str, Any]:
    """Atomically consume the one permitted host attempt after a valid freeze."""
    def claim(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("stages", {}).get("freeze", {}).get("status") != "succeeded":
            raise StateError("host can be claimed only after freeze succeeds")
        frozen = state.get("freeze_snapshot")
        if not frozen or frozen.get("digest") != package_snapshot(state)["digest"]:
            raise StateError("frozen subject no longer matches current subject")
        if state.get("host_attempts") != 0:
            raise StateError("host attempt was already claimed")
        state["host_attempts"] = 1  # Consume before the external host starts.
        state.setdefault("events", []).append({"event": "host-claimed"})
        return state
    return mutate_state(run_dir, claim)
