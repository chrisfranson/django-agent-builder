import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agent_builder.models import Agent, AgentChunk, AgentInstruction, Chunk, Instruction

User = get_user_model()


@pytest.fixture
def api_client():
    user = User.objects.create_user(username="testuser", password="testpass")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestAgentViewSet:
    def test_list_agents_empty(self, api_client):
        client, user = api_client
        response = client.get("/agent-builder/api/agents/")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_agent(self, api_client):
        client, user = api_client
        response = client.post(
            "/agent-builder/api/agents/",
            {
                "name": "my-agent",
                "display_name": "My Agent",
                "source": "claude",
                "description": "Test agent",
            },
        )
        assert response.status_code == 201
        assert response.json()["name"] == "my-agent"
        assert response.json()["user"] == user.pk
        assert Agent.objects.filter(user=user).count() == 1

    def test_retrieve_agent(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        response = client.get(f"/agent-builder/api/agents/{agent.pk}/")
        assert response.status_code == 200
        assert response.json()["name"] == "test"
        assert "agent_chunks" in response.json()

    def test_update_agent(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        response = client.patch(
            f"/agent-builder/api/agents/{agent.pk}/",
            {
                "display_name": "Updated Name",
            },
        )
        assert response.status_code == 200
        agent.refresh_from_db()
        assert agent.display_name == "Updated Name"

    def test_delete_agent(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        response = client.delete(f"/agent-builder/api/agents/{agent.pk}/")
        assert response.status_code == 204
        assert Agent.objects.count() == 0

    def test_user_scoping(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other", password="pass")
        Agent.objects.create(name="mine", display_name="Mine", source="claude", user=user)
        Agent.objects.create(name="theirs", display_name="Theirs", source="claude", user=other_user)
        response = client.get("/agent-builder/api/agents/")
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "mine"

    def test_filter_by_source(self, api_client):
        client, user = api_client
        Agent.objects.create(name="claude-a", display_name="C", source="claude", user=user)
        Agent.objects.create(name="coderoo-a", display_name="R", source="coderoo", user=user)
        response = client.get("/agent-builder/api/agents/?source=claude")
        assert len(response.json()) == 1
        assert response.json()[0]["source"] == "claude"


@pytest.mark.django_db
class TestChunkViewSet:
    def test_list_chunks(self, api_client):
        client, user = api_client
        Chunk.objects.create(title="Test", content="Content", user=user)
        response = client.get("/agent-builder/api/chunks/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_create_chunk(self, api_client):
        client, user = api_client
        response = client.post(
            "/agent-builder/api/chunks/",
            {
                "title": "New Chunk",
                "content": "## Instructions",
                "in_library": True,
            },
        )
        assert response.status_code == 201
        assert response.json()["title"] == "New Chunk"

    def test_filter_library_chunks(self, api_client):
        client, user = api_client
        Chunk.objects.create(title="In Lib", content="A", in_library=True, user=user)
        Chunk.objects.create(content="Not in lib", user=user)
        response = client.get("/agent-builder/api/chunks/?library=true")
        assert len(response.json()) == 1
        assert response.json()[0]["title"] == "In Lib"

    def test_unauthenticated_rejected(self):
        client = APIClient()
        response = client.get("/agent-builder/api/agents/")
        assert response.status_code in [401, 403]


@pytest.mark.django_db
class TestAgentChunkViewSet:
    def test_create_agent_chunk(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        chunk = Chunk.objects.create(title="Chunk", content="Content", user=user)
        response = client.post(
            f"/agent-builder/api/agents/{agent.pk}/chunks/",
            {"chunk_id": chunk.pk, "position": 0},
            format="json",
        )
        assert response.status_code == 201
        assert AgentChunk.objects.filter(agent=agent, chunk=chunk).exists()

    def test_list_agent_chunks(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        chunk = Chunk.objects.create(title="Chunk", content="Content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        response = client.get(f"/agent-builder/api/agents/{agent.pk}/chunks/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_cross_user_chunk_rejected(self, api_client):
        """Reject linking a chunk owned by another user to an agent."""
        client, user = api_client
        other_user = User.objects.create_user(username="other", password="pass")
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        other_chunk = Chunk.objects.create(title="Other", content="Nope", user=other_user)
        response = client.post(
            f"/agent-builder/api/agents/{agent.pk}/chunks/",
            {"chunk_id": other_chunk.pk, "position": 0},
            format="json",
        )
        assert response.status_code == 403
        assert AgentChunk.objects.count() == 0


@pytest.mark.django_db
class TestApplyEndpoint:
    def test_apply_claude_agent(self, api_client, tmp_path):
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            frontmatter="name: test-agent",
            user=user,
        )
        chunk = Chunk.objects.create(content="## Instructions", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR",
                tmp_path / ".claude" / "agents",
            )
            response = client.post(f"/agent-builder/api/agents/{agent.pk}/apply/")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        written = (tmp_path / ".claude" / "agents" / "test-agent.md").read_text()
        assert "## Instructions" in written


@pytest.mark.django_db
class TestImportAllEndpoint:
    def test_import_all(self, api_client, tmp_path):
        client, user = api_client
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "imported-agent.md").write_text(
            "---\nname: imported-agent\ndescription: Imported\nmodel: sonnet\n---\n\n## Content"
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR",
                agents_dir,
            )
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR",
                tmp_path / "empty",
            )
            response = client.post("/agent-builder/api/import-all/")

        assert response.status_code == 200
        data = response.json()
        assert data["imported"] >= 1
        assert Agent.objects.filter(user=user, name="imported-agent").exists()
        agent = Agent.objects.get(user=user, name="imported-agent")
        assert agent.chunks.count() == 1


@pytest.mark.django_db
class TestApplyAllEndpoint:
    def test_apply_all_writes_active_agents(self, api_client, tmp_path):
        client, user = api_client
        agent = Agent.objects.create(
            name="active-agent",
            display_name="Active",
            source="claude",
            frontmatter="name: active-agent",
            is_active=True,
            user=user,
        )
        chunk = Chunk.objects.create(content="## Active Content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        Agent.objects.create(
            name="inactive-agent",
            display_name="Inactive",
            source="claude",
            is_active=False,
            user=user,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR",
                tmp_path / ".claude" / "agents",
            )
            response = client.post("/agent-builder/api/apply-all/")

        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "active-agent"
        written = (tmp_path / ".claude" / "agents" / "active-agent.md").read_text()
        assert "## Active Content" in written


@pytest.mark.django_db
class TestInstructionViewSet:
    def test_list_instructions_empty(self, api_client):
        client, user = api_client
        response = client.get("/agent-builder/api/instructions/")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_instruction(self, api_client):
        client, user = api_client
        response = client.post(
            "/agent-builder/api/instructions/",
            {
                "name": "coding-standards",
                "display_name": "Coding Standards",
                "content": "Follow PEP 8.",
                "injection_mode": "on_demand",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["name"] == "coding-standards"

    def test_retrieve_instruction(self, api_client):
        client, user = api_client
        instruction = Instruction.objects.create(
            name="standards", display_name="Standards", content="content", user=user
        )
        response = client.get(f"/agent-builder/api/instructions/{instruction.pk}/")
        assert response.status_code == 200
        assert response.json()["name"] == "standards"

    def test_user_scoping(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other_instr", password="pass")
        Instruction.objects.create(
            name="other-user", display_name="Other", content="content", user=other_user
        )
        response = client.get("/agent-builder/api/instructions/")
        assert response.json() == []


@pytest.mark.django_db
class TestAgentInstructionViewSet:
    def test_create_agent_instruction(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        instruction = Instruction.objects.create(
            name="standards", display_name="Standards", content="content", user=user
        )
        response = client.post(
            f"/agent-builder/api/agents/{agent.pk}/instructions/",
            {"instruction_id": instruction.pk, "injection_mode": "auto_inject"},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["injection_mode"] == "auto_inject"

    def test_list_agent_instructions(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        instruction = Instruction.objects.create(
            name="standards", display_name="Standards", content="content", user=user
        )
        AgentInstruction.objects.create(agent=agent, instruction=instruction)
        response = client.get(f"/agent-builder/api/agents/{agent.pk}/instructions/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_cross_user_instruction_rejected(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other_instr2", password="pass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        instruction = Instruction.objects.create(
            name="other", display_name="Other", content="content", user=other_user
        )
        response = client.post(
            f"/agent-builder/api/agents/{agent.pk}/instructions/",
            {"instruction_id": instruction.pk},
            format="json",
        )
        assert response.status_code == 400
