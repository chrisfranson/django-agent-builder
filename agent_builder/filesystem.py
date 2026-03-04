"""Filesystem operations for applying and importing agents."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .models import Agent, AgentChunk


def normalize_trailing_newline(text: str) -> str:
    """Ensure text ends with exactly one newline (POSIX convention)."""
    return text.rstrip("\n") + "\n" if text else text


def _get_file_mtime(path: Path) -> datetime | None:
    """Get a file's modified time as a timezone-aware datetime."""
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (FileNotFoundError, PermissionError):
        return None


# Config file scanning
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".tox", ".venv", "venv"}
CONFIG_FILENAMES = {"CLAUDE.md", "AGENTS.md"}
DEFAULT_SCAN_ROOTS = [
    Path("/storage/Projects").resolve(),
    (Path.home() / "Projects").resolve(),
]
DEFAULT_EXTRA_PATHS = [
    (Path.home() / ".claude" / "CLAUDE.md").resolve(),
    (Path.home() / "CLAUDE.md").resolve(),
    (Path.home() / "AGENTS.md").resolve(),
]

# Default paths
DEFAULT_CLAUDE_AGENTS_DIR = Path.home() / ".claude" / "agents"
DEFAULT_CODEROO_AGENTS_DIR = Path.home() / ".config" / "coderoo" / "agents"
DEFAULT_INSTRUCTIONS_DIR = Path.home() / ".config" / "coderoo" / "instructions"
DEFAULT_INSTRUCTIONS_MODULES_DIR = Path.home() / ".config" / "coderoo" / "instructions-modules"
DEFAULT_CLAUDE_SKILLS_DIR = Path.home() / ".claude" / "skills"
DEFAULT_CLAUDE_COMMANDS_DIR = Path.home() / ".claude" / "commands"


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
) -> tuple[Path, datetime | None]:
    """Write an agent to the appropriate filesystem location.

    Returns (path, mtime) -- the path of the primary file written and its new mtime.
    """
    content = normalize_trailing_newline(render_agent(agent))

    if agent.source == "claude":
        target_dir = claude_agents_dir or DEFAULT_CLAUDE_AGENTS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{agent.name}.md"
        file_path.write_text(content)
        return file_path, _get_file_mtime(file_path)

    elif agent.source == "coderoo":
        target_dir = coderoo_agents_dir or DEFAULT_CODEROO_AGENTS_DIR
        agent_dir = target_dir / agent.name
        agent_dir.mkdir(parents=True, exist_ok=True)
        md_path = agent_dir / f"{agent.name}.md"
        json5_path = agent_dir / f"{agent.name}.json5"
        md_path.write_text(content)
        if agent.config:
            json5_path.write_text(agent.config)
        else:
            config = generate_coderoo_config(agent)
            json5_path.write_text(json.dumps(config, indent=2))
        return md_path, _get_file_mtime(md_path)

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
                    "mtime": _get_file_mtime(file_path),
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
                    "mtime": _get_file_mtime(md_file),
                }
            )
        except Exception:
            continue
    return agents


def write_instruction(
    instruction, instructions_dir: Path | None = None
) -> tuple[Path, datetime | None]:
    """Write an instruction to the Coderoo instructions directory.

    Each instruction is a directory containing SKILL.md.
    """
    target_dir = instructions_dir or DEFAULT_INSTRUCTIONS_DIR
    skill_dir = target_dir / instruction.name
    skill_dir.mkdir(parents=True, exist_ok=True)
    target_path = skill_dir / "SKILL.md"
    target_path.write_text(normalize_trailing_newline(instruction.content))
    return target_path, _get_file_mtime(target_path)


def read_instructions(
    instructions_dirs: list[Path] | None = None,
) -> list[dict]:
    """Read all instruction files from Coderoo instructions directories.

    Each instruction is a directory containing SKILL.md.
    Scans both instructions/ and instructions-modules/ by default.
    """
    dirs = instructions_dirs or [DEFAULT_INSTRUCTIONS_DIR, DEFAULT_INSTRUCTIONS_MODULES_DIR]
    results = []
    seen_names: set[str] = set()
    for target_dir in dirs:
        if not target_dir.exists():
            continue
        for skill_dir in sorted(target_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            if skill_dir.name in seen_names:
                continue
            try:
                content = skill_file.read_text()
                results.append(
                    {
                        "name": skill_dir.name,
                        "content": content,
                        "mtime": _get_file_mtime(skill_file),
                        "path": str(skill_file),
                    }
                )
                seen_names.add(skill_dir.name)
            except Exception:
                continue
    return results


def read_claude_skills(skills_dir: Path | None = None) -> list[dict]:
    """Read all Claude Code skills from ~/.claude/skills/*/SKILL.md."""
    target_dir = skills_dir or DEFAULT_CLAUDE_SKILLS_DIR
    if not target_dir.exists():
        return []
    results = []
    for skill_dir in sorted(target_dir.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        try:
            content = skill_file.read_text()
            results.append(
                {
                    "name": skill_dir.name,
                    "content": content,
                    "mtime": _get_file_mtime(skill_file),
                    "path": str(skill_file),
                }
            )
        except Exception:
            continue
    return results


def read_claude_commands(commands_dir: Path | None = None) -> list[dict]:
    """Read all Claude Code slash commands from ~/.claude/commands/*.md."""
    target_dir = commands_dir or DEFAULT_CLAUDE_COMMANDS_DIR
    if not target_dir.exists():
        return []
    results = []
    for md_file in sorted(target_dir.glob("*.md")):
        try:
            content = md_file.read_text()
            results.append(
                {
                    "name": md_file.stem,
                    "content": content,
                    "mtime": _get_file_mtime(md_file),
                    "path": str(md_file),
                }
            )
        except Exception:
            continue
    # Also scan subdirectories for flat .md files (e.g., commands/new/*.md)
    for sub_dir in sorted(target_dir.iterdir()):
        if not sub_dir.is_dir() or sub_dir.name.startswith("."):
            continue
        for md_file in sorted(sub_dir.glob("*.md")):
            try:
                content = md_file.read_text()
                results.append(
                    {
                        "name": f"{sub_dir.name}/{md_file.stem}",
                        "content": content,
                        "mtime": _get_file_mtime(md_file),
                        "path": str(md_file),
                    }
                )
            except Exception:
                continue
    return results


def generate_coderoo_config(agent: Agent) -> dict:
    """Generate Coderoo .json5 config from agent's instruction mappings."""
    from .models import AgentInstruction

    config: dict = {"docs.include": [], "reminder": []}
    agent_instructions = AgentInstruction.objects.filter(agent=agent).select_related("instruction")

    for ai in agent_instructions:
        mode = ai.get_effective_mode()
        if mode == "auto_inject":
            config["docs.include"].append(ai.instruction.name)
        elif mode == "on_demand":
            config["reminder"].append([ai.instruction.name, ai.instruction.display_name])

    return config


def read_config_files(
    scan_roots: list[Path] | None = None,
    extra_paths: list[Path] | None = None,
    max_depth: int = 3,
) -> list[dict]:
    """Scan for CLAUDE.md and AGENTS.md files.

    Args:
        scan_roots: Directories to recursively scan (up to max_depth).
        extra_paths: Specific file paths to check directly.
        max_depth: Maximum directory depth to scan.

    Returns:
        List of dicts with keys: filename, path, content.
    """
    roots = scan_roots if scan_roots is not None else DEFAULT_SCAN_ROOTS
    extras = extra_paths if extra_paths is not None else DEFAULT_EXTRA_PATHS
    seen_paths: set[str] = set()
    results: list[dict] = []

    # Check explicit extra paths first
    for file_path in extras:
        if file_path.is_file():
            resolved = str(file_path.resolve())
            if resolved not in seen_paths:
                try:
                    results.append(
                        {
                            "filename": file_path.name,
                            "path": resolved,
                            "content": file_path.read_text(),
                            "mtime": _get_file_mtime(file_path),
                        }
                    )
                    seen_paths.add(resolved)
                except Exception:
                    continue

    # Recursively scan roots -- resolve each root to dedup symlinked trees
    resolved_roots: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        resolved_root = str(root.resolve())
        if resolved_root in resolved_roots:
            continue
        resolved_roots.add(resolved_root)
        _scan_dir(root, 0, max_depth, seen_paths, results)

    return results


def _scan_dir(
    directory: Path,
    depth: int,
    max_depth: int,
    seen_paths: set[str],
    results: list[dict],
) -> None:
    """Recursively scan a directory for config files."""
    if depth >= max_depth:
        return
    try:
        entries = sorted(directory.iterdir())
    except PermissionError:
        return
    for entry in entries:
        if entry.is_file() and entry.name in CONFIG_FILENAMES:
            resolved = str(entry.resolve())
            if resolved not in seen_paths:
                try:
                    results.append(
                        {
                            "filename": entry.name,
                            "path": resolved,
                            "content": entry.read_text(),
                            "mtime": _get_file_mtime(entry),
                        }
                    )
                    seen_paths.add(resolved)
                except Exception:
                    continue
        elif entry.is_dir() and entry.name not in SKIP_DIRS and not entry.name.startswith("."):
            _scan_dir(entry, depth + 1, max_depth, seen_paths, results)


# Project scanning
DEFAULT_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def scan_projects(
    scan_roots: list[Path] | None = None,
    claude_projects_dir: Path | None = None,
    max_depth: int = 3,
) -> list[dict]:
    """Scan for project directories.

    Discovers projects by:
    1. Finding directories with .coderoo/ subdirectory under scan_roots
    2. Reading Claude Code project entries from ~/.claude/projects/

    Returns:
        List of dicts with keys: name, path, has_coderoo, has_claude_config.
    """
    roots = scan_roots if scan_roots is not None else DEFAULT_SCAN_ROOTS
    claude_dir = (
        claude_projects_dir if claude_projects_dir is not None else DEFAULT_CLAUDE_PROJECTS_DIR
    )

    # Use path as key to merge discoveries
    projects: dict[str, dict] = {}

    # 1. Scan for .coderoo directories
    for root in roots:
        if not root.is_dir():
            continue
        _scan_for_coderoo_projects(root, 0, max_depth, projects)

    # 2. Read Claude Code project entries
    _scan_claude_projects(claude_dir, projects)

    return list(projects.values())


def _scan_for_coderoo_projects(
    directory: Path,
    depth: int,
    max_depth: int,
    projects: dict[str, dict],
) -> None:
    """Recursively scan for directories containing .coderoo/."""
    if depth >= max_depth:
        return
    try:
        entries = sorted(directory.iterdir())
    except PermissionError:
        return
    for entry in entries:
        if not entry.is_dir() or entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        coderoo_dir = entry / ".coderoo"
        if coderoo_dir.is_dir():
            path_str = str(entry.resolve())
            if path_str in projects:
                projects[path_str]["has_coderoo"] = True
            else:
                projects[path_str] = {
                    "name": entry.name,
                    "path": path_str,
                    "has_coderoo": True,
                    "has_claude_config": False,
                }
        # Continue scanning subdirectories (projects can be nested)
        _scan_for_coderoo_projects(entry, depth + 1, max_depth, projects)


def _scan_claude_projects(
    claude_projects_dir: Path,
    projects: dict[str, dict],
) -> None:
    """Read Claude Code project entries from ~/.claude/projects/."""
    if not claude_projects_dir.is_dir():
        return
    try:
        entries = sorted(claude_projects_dir.iterdir())
    except PermissionError:
        return
    for entry in entries:
        if not entry.is_dir():
            continue
        sessions_index = entry / "sessions-index.json"
        if not sessions_index.is_file():
            continue
        try:
            data = json.loads(sessions_index.read_text())
            original_path = data.get("originalPath")
            if not original_path:
                continue
            # Verify the path actually exists on disk
            if not Path(original_path).is_dir():
                continue
            path_str = str(Path(original_path).resolve())
            if path_str in projects:
                projects[path_str]["has_claude_config"] = True
            else:
                projects[path_str] = {
                    "name": Path(original_path).name,
                    "path": path_str,
                    "has_coderoo": False,
                    "has_claude_config": True,
                }
        except (json.JSONDecodeError, OSError):
            continue


def write_config_file(config_file) -> tuple[Path, datetime | None]:
    """Write a ConfigFile's content back to disk."""
    target = Path(config_file.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(normalize_trailing_newline(config_file.content))
    return target, _get_file_mtime(target)
