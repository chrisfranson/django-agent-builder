"""Simulate mode: assemble the full context an agent receives at session start."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .filesystem import generate_coderoo_config, render_agent
from .models import Agent, AgentInstruction, ConfigFile


def simulate_session(
    agent: Agent,
    project_path: str = "",
) -> dict[str, Any]:
    """Assemble the full context an agent would receive at session start.

    Args:
        agent: The Agent instance to simulate.
        project_path: Optional project path for scope-matching ConfigFiles.

    Returns:
        Dictionary with sections:
        - agent_description: The rendered agent markdown (frontmatter + chunks)
        - config_files: List of CLAUDE.md/AGENTS.md that apply to the project
        - docs_include: List of auto-injected instruction contents
        - reminder: List of on-demand instruction references
        - agent_config: The generated Coderoo config (if coderoo agent)
    """
    result: dict[str, Any] = {
        "agent": {
            "name": agent.name,
            "display_name": agent.display_name,
            "source": agent.source,
            "model": agent.model,
        },
        "sections": [],
    }

    # Section 1: Agent description (rendered markdown from chunks)
    rendered = render_agent(agent)
    if rendered:
        result["sections"].append(
            {
                "title": f"Agent Description: {agent.display_name}",
                "type": "agent_description",
                "content": rendered,
            }
        )

    # Section 2: Config files (CLAUDE.md / AGENTS.md) scoped to project_path
    config_files = _get_scoped_config_files(agent.user, project_path)
    for cf in config_files:
        result["sections"].append(
            {
                "title": f"{cf.filename} ({cf.scope})",
                "type": "config_file",
                "path": cf.path,
                "content": cf.content,
            }
        )

    # Section 3: docs.include (auto-injected instructions)
    docs_include = _get_docs_include_instructions(agent)
    for instr_name, instr_content in docs_include:
        result["sections"].append(
            {
                "title": f"docs.include: {instr_name}",
                "type": "docs_include",
                "content": instr_content,
            }
        )

    # Section 4: Reminder (on-demand instructions)
    reminders = _get_reminder_instructions(agent)
    if reminders:
        reminder_lines = [f"- [{name}] {display_name}" for name, display_name in reminders]
        result["sections"].append(
            {
                "title": "Reminder (On-Demand Instructions)",
                "type": "reminder",
                "content": "\n".join(reminder_lines),
            }
        )

    # Section 5: Agent config (Coderoo agents only)
    if agent.source == "coderoo":
        if agent.config:
            result["sections"].append(
                {
                    "title": "Agent Config (JSON5)",
                    "type": "agent_config",
                    "content": agent.config,
                }
            )
        else:
            generated = generate_coderoo_config(agent)
            result["sections"].append(
                {
                    "title": "Agent Config (Generated)",
                    "type": "agent_config",
                    "content": json.dumps(generated, indent=2),
                }
            )

    return result


def _get_scoped_config_files(user, project_path: str) -> list[ConfigFile]:
    """Return ConfigFiles whose scope is a parent of (or equal to) the project path.

    If no project_path is provided, return all config files for the user.
    Config files are returned in order from broadest scope to narrowest.
    """
    config_files = ConfigFile.objects.filter(user=user).order_by("path")
    if not project_path:
        return list(config_files)

    # Normalize the project path
    normalized_project = str(Path(project_path).resolve())

    matching = []
    for cf in config_files:
        scope = cf.scope
        # A config file applies if:
        # 1. The project path is within the config file's scope, OR
        # 2. The config file is a global config (lives under ~/.claude/)
        is_global = "/.claude/" in cf.path
        if normalized_project.startswith(scope) or is_global:
            matching.append(cf)

    # Sort by scope length (broadest first = shortest path)
    matching.sort(key=lambda cf: len(cf.scope))
    return matching


def _get_docs_include_instructions(agent: Agent) -> list[tuple[str, str]]:
    """Get instructions configured as auto_inject (docs.include) for this agent."""
    agent_instructions = AgentInstruction.objects.filter(agent=agent).select_related("instruction")
    results = []
    for ai in agent_instructions:
        if ai.get_effective_mode() == "auto_inject":
            results.append((ai.instruction.name, ai.instruction.content))
    return results


def _get_reminder_instructions(agent: Agent) -> list[tuple[str, str]]:
    """Get instructions configured as on_demand (reminder) for this agent."""
    agent_instructions = AgentInstruction.objects.filter(agent=agent).select_related("instruction")
    results = []
    for ai in agent_instructions:
        if ai.get_effective_mode() == "on_demand":
            results.append((ai.instruction.name, ai.instruction.display_name))
    return results
