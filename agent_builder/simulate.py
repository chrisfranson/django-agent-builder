"""Simulate mode: preview assembled context via `coderoo preview-context`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import Agent


class SimulateSessionError(RuntimeError):
    """Raised when simulate context preview cannot be generated."""


def simulate_session(
    agent: Agent,
    project_path: str = "",
    *,
    role: str = "",
    context: str = "",
    task: str = "",
    runtime: str = "",
) -> dict[str, Any]:
    """Get the raw context preview payload from `coderoo preview-context`.

    Args:
        agent: The Agent instance to simulate.
        project_path: Optional project path passed to preview command.
        role: Optional role override.
        context: Optional context override.
        task: Optional task name to include.
        runtime: Optional runtime identifier.

    Returns:
        Raw JSON object emitted by `coderoo preview-context --json`.
    """
    payload = _run_preview_context(
        agent=agent,
        project_path=project_path,
        role=role,
        context=context,
        task=task,
        runtime=runtime,
    )
    return _prioritize_md_files(payload)


def _run_preview_context(
    *,
    agent: Agent,
    project_path: str,
    role: str,
    context: str,
    task: str,
    runtime: str,
) -> dict[str, Any]:
    coderoo_executable = _resolve_coderoo_executable()
    command = [coderoo_executable, "preview-context", "--json", "--agent", agent.name]
    if role:
        command.extend(["--role", role])
    if context:
        command.extend(["--context", context])
    if task:
        command.extend(["--task", task])
    if runtime:
        command.extend(["--runtime", runtime])
    command.append("--include-md-files")
    if project_path:
        command.extend(["--path", project_path])

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SimulateSessionError(
            "coderoo executable became unavailable during invocation."
        ) from exc
    except OSError as exc:
        raise SimulateSessionError(f"Failed to run coderoo preview-context: {exc}") from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or "unknown error"
        raise SimulateSessionError(f"coderoo preview-context failed: {detail}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SimulateSessionError("coderoo preview-context returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise SimulateSessionError("coderoo preview-context returned an unexpected response.")

    return payload


def _resolve_coderoo_executable() -> str:
    """Resolve a runnable Coderoo CLI path for shell and service environments."""
    env_override = os.environ.get("CODEROO_BIN", "").strip()
    if env_override:
        return env_override

    resolved = shutil.which("coderoo")
    if resolved:
        return resolved

    fallback = Path.home() / ".local" / "bin" / "coderoo"
    if fallback.exists() and os.access(fallback, os.X_OK):
        return str(fallback)

    path_value = os.environ.get("PATH", "")
    raise SimulateSessionError(
        "coderoo command not found. Ensure Coderoo CLI is installed and available in PATH "
        f"(current PATH: {path_value})."
    )


def _prioritize_md_files(payload: dict[str, Any]) -> dict[str, Any]:
    """Return payload with `md_files` first to improve simulate output readability."""
    if "md_files" not in payload:
        return payload

    reordered: dict[str, Any] = {"md_files": payload["md_files"]}
    for key, value in payload.items():
        if key == "md_files":
            continue
        reordered[key] = value
    return reordered
