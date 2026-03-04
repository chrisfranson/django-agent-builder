"""Celery tasks for agent_builder."""

import subprocess
from pathlib import Path

from celery import shared_task


@shared_task(queue="iolabs")
def create_project_with_claude(project_id, project_path):
    """Invoke Claude Code with /new-project skill to initialize a project directory."""
    Path(project_path).mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        ["claude", "-p", f"/new-project {project_path}"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=project_path,
    )

    from .models import Project

    project = Project.objects.filter(pk=project_id).first()
    if project:
        project.has_claude_config = True
        project.save(update_fields=["has_claude_config"])

    return {
        "status": "ok" if result.returncode == 0 else "error",
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:] if result.stdout else "",
        "stderr": result.stderr[-2000:] if result.stderr else "",
    }
