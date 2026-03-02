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
        result_path = write_agent(agent, claude_agents_dir=agents_dir)

        assert result_path.exists()
        assert result_path.name == "test-agent.md"
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
        path = write_instruction(instruction, instructions_dir=tmp_path)
        assert path.exists()
        assert path.name == "coding-standards.md"
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


class TestWriteConfigFile:
    def test_write_config_file(self, tmp_path):
        target = tmp_path / "CLAUDE.md"

        class FakeConfigFile:
            path = str(target)
            content = "# New content"

        result = write_config_file(FakeConfigFile())
        assert result == target
        assert target.read_text() == "# New content"

    def test_write_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "CLAUDE.md"

        class FakeConfigFile:
            path = str(target)
            content = "nested"

        write_config_file(FakeConfigFile())
        assert target.exists()
        assert target.read_text() == "nested"
