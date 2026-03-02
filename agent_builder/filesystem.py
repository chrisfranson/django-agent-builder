"""Filesystem operations for applying and importing agents."""

from __future__ import annotations

import re
from pathlib import Path

from .models import Agent, AgentChunk

# Default paths
DEFAULT_CLAUDE_AGENTS_DIR = Path.home() / ".claude" / "agents"
DEFAULT_CODEROO_AGENTS_DIR = Path.home() / ".config" / "coderoo" / "agents"


def parse_frontmatter(text: str) -> tuple[str, str]:
    """Extract raw frontmatter and content from markdown file."""
    match = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    if match:
        return match.group(1), match.group(2).strip()
    return "", text.strip()


def render_agent(agent: Agent) -> str:
    """Assemble an agent's final markdown from its chunks."""
    agent_chunks = (
        AgentChunk.objects.filter(agent=agent, is_enabled=True)
        .select_related("chunk", "active_variant")
        .order_by("position")
    )

    parts = []
    for ac in agent_chunks:
        if ac.active_variant:
            parts.append(ac.active_variant.content)
        else:
            parts.append(ac.chunk.content)

    body = "\n\n".join(parts)

    if agent.frontmatter:
        if body:
            return f"---\n{agent.frontmatter}\n---\n\n{body}"
        return f"---\n{agent.frontmatter}\n---"

    return body


def write_agent(
    agent: Agent,
    claude_agents_dir: Path | None = None,
    coderoo_agents_dir: Path | None = None,
) -> Path:
    """Write an agent to the appropriate filesystem location.

    Returns the path of the primary file written.
    """
    content = render_agent(agent)

    if agent.source == "claude":
        target_dir = claude_agents_dir or DEFAULT_CLAUDE_AGENTS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{agent.name}.md"
        file_path.write_text(content)
        return file_path

    elif agent.source == "coderoo":
        target_dir = coderoo_agents_dir or DEFAULT_CODEROO_AGENTS_DIR
        agent_dir = target_dir / agent.name
        agent_dir.mkdir(parents=True, exist_ok=True)
        md_path = agent_dir / f"{agent.name}.md"
        json5_path = agent_dir / f"{agent.name}.json5"
        md_path.write_text(content)
        # Write basic config (Phase 2 populates docs.include/reminder from instructions)
        if not json5_path.exists():
            json5_path.write_text('{\n  "reminder": [],\n  "docs.include": []\n}')
        return md_path

    raise ValueError(f"Unknown agent source: {agent.source}")


def read_claude_agents(agents_dir: Path | None = None) -> list[dict]:
    """Read all Claude agents from disk."""
    target_dir = agents_dir or DEFAULT_CLAUDE_AGENTS_DIR
    if not target_dir.exists():
        return []

    agents = []
    for file_path in target_dir.glob("*.md"):
        try:
            text = file_path.read_text()
            frontmatter, content = parse_frontmatter(text)
            agents.append(
                {
                    "name": file_path.stem,
                    "source": "claude",
                    "frontmatter": frontmatter,
                    "content": content,
                }
            )
        except Exception:
            continue
    return agents


def read_coderoo_agents(agents_dir: Path | None = None) -> list[dict]:
    """Read all Coderoo agents from disk."""
    target_dir = agents_dir or DEFAULT_CODEROO_AGENTS_DIR
    if not target_dir.exists():
        return []

    agents = []
    for agent_dir in target_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name.startswith("."):
            continue
        md_file = agent_dir / f"{agent_dir.name}.md"
        if not md_file.exists():
            continue
        try:
            text = md_file.read_text()
            frontmatter, content = parse_frontmatter(text)
            config = ""
            config_file = agent_dir / f"{agent_dir.name}.json5"
            if config_file.exists():
                config = config_file.read_text()
            agents.append(
                {
                    "name": agent_dir.name,
                    "source": "coderoo",
                    "frontmatter": frontmatter,
                    "content": content,
                    "config": config,
                }
            )
        except Exception:
            continue
    return agents
