import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from agent_builder.filesystem import (
    generate_coderoo_config,
    read_claude_agents,
    read_coderoo_agents,
    read_config_files,
    read_instructions,
    render_agent,
    scan_projects,
    write_agent,
    write_config_file,
    write_instruction,
)
from agent_builder.models import Agent, AgentChunk, AgentInstruction, Chunk, Instruction

User = get_user_model()


@pytest.mark.django_db
class TestRenderAgent:
    def test_render_single_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test",
            display_name="Test",
            source="claude",
            frontmatter="name: test\nmodel: sonnet",
            user=user,
        )
        chunk = Chunk.objects.create(content="## Role\nYou are helpful.", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        result = render_agent(agent)
        assert result == "---\nname: test\nmodel: sonnet\n---\n\n## Role\nYou are helpful."

    def test_render_multiple_chunks_ordered(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test",
            display_name="Test",
            source="claude",
            frontmatter="name: test",
            user=user,
        )
        chunk_a = Chunk.objects.create(content="First", user=user)
        chunk_b = Chunk.objects.create(content="Second", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk_b, position=1)
        AgentChunk.objects.create(agent=agent, chunk=chunk_a, position=0)

        result = render_agent(agent)
        assert "First\n\nSecond" in result

    def test_render_skips_disabled_chunks(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test",
            display_name="Test",
            source="claude",
            frontmatter="name: test",
            user=user,
        )
        chunk_a = Chunk.objects.create(content="Included", user=user)
        chunk_b = Chunk.objects.create(content="Excluded", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk_a, position=0)
        AgentChunk.objects.create(agent=agent, chunk=chunk_b, position=1, is_enabled=False)

        result = render_agent(agent)
        assert "Included" in result
        assert "Excluded" not in result

    def test_render_no_chunks(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test",
            display_name="Test",
            source="claude",
            frontmatter="name: test",
            user=user,
        )
        result = render_agent(agent)
        assert result == "---\nname: test\n---"


@pytest.mark.django_db
class TestWriteAgent:
    def test_write_claude_agent(self, tmp_path):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            frontmatter="name: test-agent\nmodel: sonnet",
            user=user,
        )
        chunk = Chunk.objects.create(content="## Instructions", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        agents_dir = tmp_path / ".claude" / "agents"
        result_path, result_mtime = write_agent(agent, claude_agents_dir=agents_dir)

        assert result_path.exists()
        assert result_path.name == "test-agent.md"
        assert result_mtime is not None
        content = result_path.read_text()
        assert "---\nname: test-agent" in content
        assert "## Instructions" in content

    def test_write_coderoo_agent(self, tmp_path):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="my-agent",
            display_name="My Agent",
            source="coderoo",
            frontmatter="name: my-agent\nmodel: sonnet",
            user=user,
        )
        chunk = Chunk.objects.create(content="## Role", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        agents_dir = tmp_path / ".config" / "coderoo" / "agents"
        write_agent(agent, coderoo_agents_dir=agents_dir)

        md_path = agents_dir / "my-agent" / "my-agent.md"
        json5_path = agents_dir / "my-agent" / "my-agent.json5"
        assert md_path.exists()
        assert json5_path.exists()
        assert "## Role" in md_path.read_text()


class TestReadAgents:
    def test_read_claude_agents(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "scout.md").write_text(
            "---\nname: scout\ndescription: Finds things\nmodel: sonnet\n---\n\n"
            "## Role\nYou find things."
        )

        agents = read_claude_agents(agents_dir)
        assert len(agents) == 1
        assert agents[0]["name"] == "scout"
        assert agents[0]["source"] == "claude"
        assert agents[0]["frontmatter"] == "name: scout\ndescription: Finds things\nmodel: sonnet"
        assert agents[0]["content"] == "## Role\nYou find things."

    def test_read_coderoo_agents(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agent_dir = agents_dir / "researcher"
        agent_dir.mkdir(parents=True)
        (agent_dir / "researcher.md").write_text(
            "---\nname: researcher\ndescription: Researches\n---\n\n## Research"
        )
        (agent_dir / "researcher.json5").write_text('{\n  "reminder": [],\n  "docs.include": []\n}')

        agents = read_coderoo_agents(agents_dir)
        assert len(agents) == 1
        assert agents[0]["name"] == "researcher"
        assert agents[0]["source"] == "coderoo"
        assert "config" in agents[0]

    def test_read_empty_dir(self, tmp_path):
        agents_dir = tmp_path / "nonexistent"
        assert read_claude_agents(agents_dir) == []
        assert read_coderoo_agents(agents_dir) == []


@pytest.mark.django_db
class TestWriteInstruction:
    def test_write_instruction(self, user, tmp_path):
        instruction = Instruction.objects.create(
            name="coding-standards",
            display_name="Coding Standards",
            content="## Coding Standards\n\nFollow PEP 8.",
            user=user,
        )
        path, mtime = write_instruction(instruction, instructions_dir=tmp_path)
        assert path.exists()
        assert path.name == "coding-standards.md"
        assert mtime is not None
        content = path.read_text()
        assert "Coding Standards" in content
        assert "Follow PEP 8" in content


class TestReadInstructions:
    def test_read_instructions(self, tmp_path):
        (tmp_path / "coding-standards.md").write_text("## Coding Standards\n\nFollow PEP 8.")
        (tmp_path / "git-workflow.md").write_text("## Git Workflow\n\nUse branches.")
        instructions = read_instructions(instructions_dir=tmp_path)
        assert len(instructions) == 2
        names = [i["name"] for i in instructions]
        assert "coding-standards" in names
        assert "git-workflow" in names

    def test_read_instructions_empty_dir(self, tmp_path):
        instructions = read_instructions(instructions_dir=tmp_path)
        assert instructions == []

    def test_read_instructions_nonexistent_dir(self):
        instructions = read_instructions(instructions_dir=Path("/nonexistent"))
        assert instructions == []


@pytest.mark.django_db
class TestCoderooConfigGeneration:
    def test_generate_coderoo_config(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test Agent", source="coderoo", user=user
        )
        auto_instruction = Instruction.objects.create(
            name="project-context",
            display_name="Project Context",
            content="Context here.",
            injection_mode="auto_inject",
            user=user,
        )
        demand_instruction = Instruction.objects.create(
            name="coding-standards",
            display_name="Coding Standards",
            content="Standards here.",
            injection_mode="on_demand",
            user=user,
        )
        AgentInstruction.objects.create(
            agent=agent, instruction=auto_instruction, injection_mode="auto_inject"
        )
        AgentInstruction.objects.create(
            agent=agent, instruction=demand_instruction, injection_mode="on_demand"
        )

        config = generate_coderoo_config(agent)
        assert "project-context" in config["docs.include"]
        assert "coding-standards" in [r[0] for r in config["reminder"]]

    def test_write_coderoo_agent_with_instructions(self, user, tmp_path):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Standards",
            content="Follow standards.",
            injection_mode="auto_inject",
            user=user,
        )
        AgentInstruction.objects.create(
            agent=agent, instruction=instruction, injection_mode="auto_inject"
        )

        write_agent(agent, coderoo_agents_dir=tmp_path)
        config_path = tmp_path / "test-agent" / "test-agent.json5"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "standards" in config["docs.include"]


class TestReadConfigFiles:
    def test_read_from_empty_dir(self, tmp_path):
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert result == []

    def test_read_claude_md(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Instructions\nBe helpful.")
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert len(result) == 1
        assert result[0]["filename"] == "CLAUDE.md"
        assert result[0]["path"] == str(claude_md)
        assert result[0]["content"] == "# Instructions\nBe helpful."

    def test_read_agents_md(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Agent Instructions")
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert len(result) == 1
        assert result[0]["filename"] == "AGENTS.md"

    def test_read_nested_config_files(self, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        (project / "CLAUDE.md").write_text("project-level")
        (tmp_path / "CLAUDE.md").write_text("root-level")
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert len(result) == 2
        filenames = [r["filename"] for r in result]
        assert filenames.count("CLAUDE.md") == 2

    def test_read_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "CLAUDE.md").write_text("too deep")
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[], max_depth=3)
        assert len(result) == 0

    def test_read_skips_hidden_dirs(self, tmp_path):
        hidden = tmp_path / ".git"
        hidden.mkdir()
        (hidden / "CLAUDE.md").write_text("should skip")
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert len(result) == 0

    def test_read_skips_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "CLAUDE.md").write_text("should skip")
        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert len(result) == 0

    def test_read_home_claude_md(self, tmp_path):
        """Test scanning ~/.claude/CLAUDE.md equivalent."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "CLAUDE.md").write_text("global config")
        result = read_config_files(
            scan_roots=[tmp_path],
            extra_paths=[claude_dir / "CLAUDE.md"],
        )
        assert any(r["path"] == str(claude_dir / "CLAUDE.md") for r in result)


class TestSymlinkDedup:
    def test_symlinked_scan_roots_dedup(self, tmp_path):
        """Symlinked scan roots should not produce duplicate results."""
        real_dir = tmp_path / "real_projects"
        real_dir.mkdir()
        (real_dir / "CLAUDE.md").write_text("# Config")

        link_dir = tmp_path / "linked_projects"
        link_dir.symlink_to(real_dir)

        result = read_config_files(scan_roots=[real_dir, link_dir], extra_paths=[])
        assert len(result) == 1
        assert result[0]["content"] == "# Config"

    def test_symlinked_file_in_extras_and_scan(self, tmp_path):
        """A file found via extra_paths should not duplicate when found via scan."""
        project = tmp_path / "project"
        project.mkdir()
        config = project / "CLAUDE.md"
        config.write_text("# Config")

        result = read_config_files(
            scan_roots=[tmp_path],
            extra_paths=[config],
        )
        assert len(result) == 1

    def test_symlinked_nested_dir_dedup(self, tmp_path):
        """Symlinks within a scan root should not cause duplicates."""
        real_sub = tmp_path / "real_sub"
        real_sub.mkdir()
        (real_sub / "AGENTS.md").write_text("# Agents")

        link_sub = tmp_path / "link_sub"
        link_sub.symlink_to(real_sub)

        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        # real_sub/AGENTS.md and link_sub/AGENTS.md resolve to the same file
        assert len(result) == 1

    def test_non_symlink_paths_still_work(self, tmp_path):
        """Regular paths without symlinks should work as before."""
        (tmp_path / "CLAUDE.md").write_text("root")
        sub = tmp_path / "project"
        sub.mkdir()
        (sub / "AGENTS.md").write_text("nested")

        result = read_config_files(scan_roots=[tmp_path], extra_paths=[])
        assert len(result) == 2


class TestScanProjects:
    def test_scan_coderoo_projects(self, tmp_path):
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / ".coderoo").mkdir()
        results = scan_projects(scan_roots=[tmp_path], claude_projects_dir=tmp_path / "empty")
        assert len(results) == 1
        assert results[0]["name"] == "my-project"
        assert results[0]["has_coderoo"] is True
        assert results[0]["has_claude_config"] is False

    def test_scan_claude_projects(self, tmp_path):
        proj = tmp_path / "my-project"
        proj.mkdir()
        claude_dir = tmp_path / ".claude" / "projects"
        claude_dir.mkdir(parents=True)
        entry = claude_dir / "-tmp-my-project"
        entry.mkdir()
        (entry / "sessions-index.json").write_text(json.dumps({"originalPath": str(proj)}))
        results = scan_projects(
            scan_roots=[tmp_path / "empty"],
            claude_projects_dir=claude_dir,
        )
        assert len(results) == 1
        assert results[0]["name"] == "my-project"
        assert results[0]["has_claude_config"] is True

    def test_scan_merges_both_sources(self, tmp_path):
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / ".coderoo").mkdir()
        claude_dir = tmp_path / ".claude" / "projects"
        claude_dir.mkdir(parents=True)
        entry = claude_dir / "-tmp-my-project"
        entry.mkdir()
        (entry / "sessions-index.json").write_text(json.dumps({"originalPath": str(proj)}))
        results = scan_projects(scan_roots=[tmp_path], claude_projects_dir=claude_dir)
        assert len(results) == 1
        assert results[0]["has_coderoo"] is True
        assert results[0]["has_claude_config"] is True

    def test_scan_skips_nonexistent_claude_paths(self, tmp_path):
        claude_dir = tmp_path / ".claude" / "projects"
        claude_dir.mkdir(parents=True)
        entry = claude_dir / "-nonexistent"
        entry.mkdir()
        (entry / "sessions-index.json").write_text(
            json.dumps({"originalPath": "/nonexistent/path"})
        )
        results = scan_projects(scan_roots=[], claude_projects_dir=claude_dir)
        assert len(results) == 0

    def test_scan_handles_malformed_sessions_index(self, tmp_path):
        claude_dir = tmp_path / ".claude" / "projects"
        claude_dir.mkdir(parents=True)
        entry = claude_dir / "-bad"
        entry.mkdir()
        (entry / "sessions-index.json").write_text("not json")
        results = scan_projects(scan_roots=[], claude_projects_dir=claude_dir)
        assert len(results) == 0

    def test_scan_empty_roots(self, tmp_path):
        results = scan_projects(
            scan_roots=[tmp_path / "empty"],
            claude_projects_dir=tmp_path / "empty2",
        )
        assert results == []

    def test_scan_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d" / "project"
        deep.mkdir(parents=True)
        (deep / ".coderoo").mkdir()
        results = scan_projects(
            scan_roots=[tmp_path],
            claude_projects_dir=tmp_path / "empty",
            max_depth=3,
        )
        assert not any(r["name"] == "project" for r in results)


class TestWriteConfigFile:
    def test_write_config_file(self, tmp_path):
        target = tmp_path / "CLAUDE.md"

        class FakeConfigFile:
            path = str(target)
            content = "# New content"

        result_path, result_mtime = write_config_file(FakeConfigFile())
        assert result_path == target
        assert result_mtime is not None
        assert target.read_text() == "# New content\n"

    def test_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "CLAUDE.md"

        class FakeConfigFile:
            path = str(target)
            content = "nested"

        write_config_file(FakeConfigFile())
        assert target.exists()
        assert target.read_text() == "nested\n"
