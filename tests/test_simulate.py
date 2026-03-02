"""Tests for simulate mode context assembly."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agent_builder.models import Agent, AgentChunk, AgentInstruction, Chunk, ConfigFile, Instruction
from agent_builder.simulate import simulate_session

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="pass")


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def agent_with_chunks(user):
    agent = Agent.objects.create(
        name="test-agent",
        display_name="Test Agent",
        source="coderoo",
        model="sonnet",
        user=user,
    )
    chunk = Chunk.objects.create(title="Main", content="# Agent Instructions\nDo stuff.", user=user)
    AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
    return agent


@pytest.fixture
def config_files(user):
    """Create config files at different scopes."""
    global_cf = ConfigFile.objects.create(
        filename="CLAUDE.md",
        path="/home/testuser/.claude/CLAUDE.md",
        content="Global instructions",
        user=user,
    )
    project_cf = ConfigFile.objects.create(
        filename="CLAUDE.md",
        path="/storage/Projects/my-project/CLAUDE.md",
        content="Project-specific instructions",
        user=user,
    )
    other_cf = ConfigFile.objects.create(
        filename="AGENTS.md",
        path="/storage/Projects/other-project/AGENTS.md",
        content="Other project agents",
        user=user,
    )
    return global_cf, project_cf, other_cf


@pytest.fixture
def instructions_with_modes(user, agent_with_chunks):
    auto_instr = Instruction.objects.create(
        name="auto-instr",
        display_name="Auto Instruction",
        content="This is auto-injected.",
        injection_mode="auto_inject",
        user=user,
    )
    demand_instr = Instruction.objects.create(
        name="demand-instr",
        display_name="Demand Instruction",
        content="This is on-demand.",
        injection_mode="on_demand",
        user=user,
    )
    AgentInstruction.objects.create(agent=agent_with_chunks, instruction=auto_instr)
    AgentInstruction.objects.create(agent=agent_with_chunks, instruction=demand_instr)
    return auto_instr, demand_instr


# --- Tests ---


@pytest.mark.django_db
class TestSimulateSession:
    def test_basic_simulation_returns_agent_info(self, agent_with_chunks):
        result = simulate_session(agent_with_chunks)
        assert result["agent"]["name"] == "test-agent"
        assert result["agent"]["source"] == "coderoo"

    def test_agent_description_section(self, agent_with_chunks):
        result = simulate_session(agent_with_chunks)
        desc_sections = [s for s in result["sections"] if s["type"] == "agent_description"]
        assert len(desc_sections) == 1
        assert "# Agent Instructions" in desc_sections[0]["content"]

    def test_config_files_scoped_to_project(self, agent_with_chunks, config_files):
        result = simulate_session(agent_with_chunks, project_path="/storage/Projects/my-project")
        cf_sections = [s for s in result["sections"] if s["type"] == "config_file"]
        paths = [s["path"] for s in cf_sections]
        # Should include the project's CLAUDE.md but NOT the other project's
        assert "/storage/Projects/my-project/CLAUDE.md" in paths
        assert "/storage/Projects/other-project/AGENTS.md" not in paths

    def test_config_files_no_project_returns_all(self, agent_with_chunks, config_files):
        result = simulate_session(agent_with_chunks, project_path="")
        cf_sections = [s for s in result["sections"] if s["type"] == "config_file"]
        assert len(cf_sections) == 3  # All config files

    def test_docs_include_section(self, agent_with_chunks, instructions_with_modes):
        result = simulate_session(agent_with_chunks)
        docs_sections = [s for s in result["sections"] if s["type"] == "docs_include"]
        assert len(docs_sections) == 1
        assert docs_sections[0]["title"] == "docs.include: auto-instr"
        assert "auto-injected" in docs_sections[0]["content"]

    def test_reminder_section(self, agent_with_chunks, instructions_with_modes):
        result = simulate_session(agent_with_chunks)
        reminder_sections = [s for s in result["sections"] if s["type"] == "reminder"]
        assert len(reminder_sections) == 1
        assert "demand-instr" in reminder_sections[0]["content"]

    def test_coderoo_agent_config_section(self, agent_with_chunks):
        result = simulate_session(agent_with_chunks)
        config_sections = [s for s in result["sections"] if s["type"] == "agent_config"]
        assert len(config_sections) == 1

    def test_claude_agent_no_config_section(self, user):
        agent = Agent.objects.create(
            name="claude-agent",
            display_name="Claude Agent",
            source="claude",
            model="sonnet",
            user=user,
        )
        result = simulate_session(agent)
        config_sections = [s for s in result["sections"] if s["type"] == "agent_config"]
        assert len(config_sections) == 0

    def test_agent_with_no_chunks(self, user):
        agent = Agent.objects.create(
            name="empty-agent",
            display_name="Empty Agent",
            source="claude",
            model="sonnet",
            user=user,
        )
        result = simulate_session(agent)
        desc_sections = [s for s in result["sections"] if s["type"] == "agent_description"]
        assert len(desc_sections) == 0  # No content = no section


@pytest.mark.django_db
class TestSimulateAPI:
    def test_simulate_endpoint_requires_auth(self, client):
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": 1},
            content_type="application/json",
        )
        assert resp.status_code in (401, 403)

    def test_simulate_endpoint_requires_agent_id(self, api_client):
        client, user = api_client
        resp = client.post(
            "/agent-builder/api/simulate/",
            {},
            format="json",
        )
        assert resp.status_code == 400

    def test_simulate_endpoint_returns_context(self, api_client, agent_with_chunks):
        client, user = api_client
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": agent_with_chunks.pk},
            format="json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert data["agent"]["name"] == "test-agent"

    def test_simulate_endpoint_agent_not_found(self, api_client):
        client, user = api_client
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": 99999},
            format="json",
        )
        assert resp.status_code == 404

    def test_simulate_endpoint_other_users_agent(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other", password="pass")
        other_agent = Agent.objects.create(
            name="other-agent",
            display_name="Other Agent",
            source="claude",
            model="sonnet",
            user=other_user,
        )
        resp = client.post(
            "/agent-builder/api/simulate/",
            {"agent_id": other_agent.pk},
            format="json",
        )
        assert resp.status_code == 404
