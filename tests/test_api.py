import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APIClient

from agent_builder.models import (
    Agent,
    AgentChunk,
    AgentInstruction,
    Chunk,
    ChunkVariant,
    ConfigFile,
    Instruction,
    Profile,
    Project,
    Revision,
    UserOptions,
)

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
        # Soft-deleted: not visible via default manager
        assert Agent.objects.count() == 0
        # But still exists in the database
        deleted = Agent.all_objects.get(pk=agent.pk)
        assert deleted.is_deleted is True
        assert deleted.deleted_at is not None

    def test_deleted_agent_not_in_list(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        agent.soft_delete()
        response = client.get("/agent-builder/api/agents/")
        assert response.status_code == 200
        assert len(response.json()) == 0

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

    def test_apply_all_delete_from_db(self, api_client, tmp_path):
        client, user = api_client

        # Create objects to be deleted
        Agent.objects.create(
            name="doomed-agent",
            display_name="Doomed",
            source="claude",
            is_active=False,
            user=user,
        )
        Instruction.objects.create(
            name="doomed-instruction",
            display_name="Doomed Instruction",
            content="Remove me",
            user=user,
        )
        ConfigFile.objects.create(
            path="/tmp/doomed-config.md",
            content="Remove me too",
            user=user,
        )

        # Create objects belonging to another user (should NOT be deleted)
        other_user = User.objects.create_user(username="other_del", password="pass")
        Agent.objects.create(
            name="doomed-agent",
            display_name="Other Doomed",
            source="claude",
            is_active=False,
            user=other_user,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR",
                tmp_path / ".claude" / "agents",
            )
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR",
                tmp_path / ".coderoo" / "agents",
            )
            mp.setattr(
                "agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR",
                tmp_path / ".claude" / "instructions",
            )
            response = client.post(
                "/agent-builder/api/apply-all/",
                {
                    "delete_from_db": [
                        {"type": "agent", "name": "doomed-agent"},
                        {"type": "instruction", "name": "doomed-instruction"},
                        {"type": "config_file", "path": "/tmp/doomed-config.md"},
                    ]
                },
                format="json",
            )

        assert response.status_code == 200
        data = response.json()
        assert data["deleted_from_db"] == 3

        # Verify objects are soft-deleted (not visible via default manager)
        assert not Agent.objects.filter(user=user, name="doomed-agent").exists()
        assert not Instruction.objects.filter(user=user, name="doomed-instruction").exists()
        assert not ConfigFile.objects.filter(user=user, path="/tmp/doomed-config.md").exists()

        # Verify objects still exist in database as soft-deleted
        agent_sd = Agent.all_objects.get(user=user, name="doomed-agent")
        assert agent_sd.is_deleted is True
        inst_sd = Instruction.all_objects.get(user=user, name="doomed-instruction")
        assert inst_sd.is_deleted is True
        cf_sd = ConfigFile.all_objects.get(user=user, path="/tmp/doomed-config.md")
        assert cf_sd.is_deleted is True

        # Verify the other user's agent was NOT deleted
        assert Agent.objects.filter(user=other_user, name="doomed-agent").exists()


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


@pytest.mark.django_db
class TestChunkSplit:
    def test_split_chunk(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(
            title="Full Instructions",
            content="Part one content.\n\nPart two content.",
            in_library=True,
            user=user,
        )
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        response = client.post(
            f"/agent-builder/api/chunks/{chunk.pk}/split/",
            {"position": len("Part one content.")},
            format="json",
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["chunks"]) == 2
        assert data["chunks"][0]["content"] == "Part one content."
        assert data["chunks"][1]["content"] == "Part two content."

    def test_split_updates_agent_chunks(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(
            title="Instructions", content="First half\n\nSecond half", user=user
        )
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=5)

        response = client.post(
            f"/agent-builder/api/chunks/{chunk.pk}/split/",
            {"position": len("First half")},
            format="json",
        )
        assert response.status_code == 200

        agent_chunks = AgentChunk.objects.filter(agent=agent).order_by("position")
        assert agent_chunks.count() == 2
        assert agent_chunks[0].position == 5
        assert agent_chunks[1].position == 6

    def test_split_at_invalid_position(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Short", content="Hi", user=user)
        response = client.post(
            f"/agent-builder/api/chunks/{chunk.pk}/split/",
            {"position": 999},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestChunkLibrary:
    def test_search_chunks(self, api_client):
        client, user = api_client
        Chunk.objects.create(
            title="Coding Standards", content="Follow PEP 8.", in_library=True, user=user
        )
        Chunk.objects.create(
            title="Git Workflow", content="Use feature branches.", in_library=True, user=user
        )
        response = client.get("/agent-builder/api/chunks/?search=coding")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["title"] == "Coding Standards"

    def test_search_chunks_content(self, api_client):
        client, user = api_client
        Chunk.objects.create(
            title="Standards", content="Always follow PEP 8 guidelines.", in_library=True, user=user
        )
        response = client.get("/agent-builder/api/chunks/?search=PEP")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_promote_to_library(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="My Chunk", content="content", user=user)
        assert chunk.in_library is False
        response = client.patch(
            f"/agent-builder/api/chunks/{chunk.pk}/",
            {"in_library": True},
            format="json",
        )
        assert response.status_code == 200
        chunk.refresh_from_db()
        assert chunk.in_library is True


@pytest.mark.django_db
class TestInstructionImportApply:
    def test_import_all_includes_instructions(self, api_client, tmp_path, monkeypatch):
        client, user = api_client
        instructions_dir = tmp_path / "instructions"
        instructions_dir.mkdir()
        (instructions_dir / "coding-standards.md").write_text("Follow PEP 8.")

        monkeypatch.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", instructions_dir)
        monkeypatch.setattr(
            "agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", tmp_path / "claude"
        )
        monkeypatch.setattr(
            "agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "coderoo"
        )

        response = client.post("/agent-builder/api/import-all/")
        assert response.status_code == 200
        data = response.json()
        assert data.get("instructions_imported", 0) >= 1
        assert Instruction.objects.filter(user=user, name="coding-standards").exists()

    def test_apply_all_writes_instructions(self, api_client, tmp_path, monkeypatch):
        client, user = api_client
        monkeypatch.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path)
        monkeypatch.setattr(
            "agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", tmp_path / "claude"
        )
        monkeypatch.setattr(
            "agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "coderoo"
        )

        Instruction.objects.create(
            name="coding-standards",
            display_name="Coding Standards",
            content="Follow PEP 8.",
            user=user,
        )

        response = client.post("/agent-builder/api/apply-all/")
        assert response.status_code == 200
        assert (tmp_path / "coding-standards.md").exists()


@pytest.mark.django_db
class TestChunkVariantViewSet:
    def test_list_variants(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        ChunkVariant.objects.create(chunk=chunk, label="gentle", content="gentle", position=0)
        ChunkVariant.objects.create(chunk=chunk, label="firm", content="firm", position=1)
        response = client.get(f"/agent-builder/api/chunks/{chunk.pk}/variants/")
        assert response.status_code == 200
        assert len(response.json()) == 2
        assert response.json()[0]["label"] == "gentle"

    def test_create_variant(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        response = client.post(
            f"/agent-builder/api/chunks/{chunk.pk}/variants/",
            {"label": "gentle", "content": "gentle version", "position": 0},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["label"] == "gentle"
        assert ChunkVariant.objects.filter(chunk=chunk).count() == 1

    def test_update_variant(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="old", position=0
        )
        response = client.patch(
            f"/agent-builder/api/chunks/{chunk.pk}/variants/{variant.pk}/",
            {"content": "updated"},
            format="json",
        )
        assert response.status_code == 200
        variant.refresh_from_db()
        assert variant.content == "updated"

    def test_delete_variant(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="content", position=0
        )
        response = client.delete(f"/agent-builder/api/chunks/{chunk.pk}/variants/{variant.pk}/")
        assert response.status_code == 204
        assert ChunkVariant.objects.count() == 0

    def test_user_scoping(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other_variant", password="pass")
        other_chunk = Chunk.objects.create(title="Other", content="content", user=other_user)
        ChunkVariant.objects.create(
            chunk=other_chunk, label="gentle", content="content", position=0
        )
        response = client.get(f"/agent-builder/api/chunks/{other_chunk.pk}/variants/")
        assert response.status_code == 404

    def test_variant_retrieve(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="content", position=0
        )
        response = client.get(f"/agent-builder/api/chunks/{chunk.pk}/variants/{variant.pk}/")
        assert response.status_code == 200
        assert response.json()["label"] == "gentle"


@pytest.mark.django_db
class TestActiveVariantSelection:
    def test_set_active_variant(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="gentle", position=0
        )
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        response = client.patch(
            f"/agent-builder/api/agents/{agent.pk}/chunks/{ac.pk}/",
            {"active_variant_id": variant.pk},
            format="json",
        )
        assert response.status_code == 200
        ac.refresh_from_db()
        assert ac.active_variant == variant

    def test_clear_active_variant(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="gentle", position=0
        )
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk, position=0, active_variant=variant)
        response = client.patch(
            f"/agent-builder/api/agents/{agent.pk}/chunks/{ac.pk}/",
            {"active_variant_id": None},
            format="json",
        )
        assert response.status_code == 200
        ac.refresh_from_db()
        assert ac.active_variant is None

    def test_set_variant_wrong_chunk_rejected(self, api_client):
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        chunk1 = Chunk.objects.create(title="Chunk 1", content="c1", user=user)
        chunk2 = Chunk.objects.create(title="Chunk 2", content="c2", user=user)
        variant_for_chunk2 = ChunkVariant.objects.create(
            chunk=chunk2, label="gentle", content="content", position=0
        )
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk1, position=0)
        response = client.patch(
            f"/agent-builder/api/agents/{agent.pk}/chunks/{ac.pk}/",
            {"active_variant_id": variant_for_chunk2.pk},
            format="json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestRevisionViewSet:
    def test_list_revisions_for_chunk(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "v1"},
            user=user,
        )
        response = client.get(
            f"/agent-builder/api/revisions/?content_type={ct.pk}&object_id={chunk.pk}"
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_list_requires_content_type_and_object_id(self, api_client):
        client, user = api_client
        response = client.get("/agent-builder/api/revisions/")
        assert response.status_code == 400

    def test_user_scoping(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other_rev", password="pass")
        chunk = Chunk.objects.create(title="Test", content="v1", user=other_user)
        ct = ContentType.objects.get_for_model(Chunk)
        Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "v1"},
            user=other_user,
        )
        response = client.get(
            f"/agent-builder/api/revisions/?content_type={ct.pk}&object_id={chunk.pk}"
        )
        assert response.status_code == 200
        assert len(response.json()) == 0  # Not this user's revision

    def test_retrieve_revision(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "v1"},
            user=user,
        )
        response = client.get(f"/agent-builder/api/revisions/{revision.pk}/")
        assert response.status_code == 200
        assert response.json()["content_snapshot"]["content"] == "v1"


@pytest.mark.django_db
class TestRevisionDiff:
    def test_diff_two_revisions(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        r1 = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "line 1\nline 2"},
            user=user,
        )
        r2 = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "line 1\nline 2 modified"},
            user=user,
        )
        response = client.get(f"/agent-builder/api/revisions/{r2.pk}/diff/?compare_to={r1.pk}")
        assert response.status_code == 200
        data = response.json()
        assert "content" in data["diff"]

    def test_diff_missing_compare_to(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        r1 = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "v1"},
            user=user,
        )
        response = client.get(f"/agent-builder/api/revisions/{r1.pk}/diff/")
        assert response.status_code == 400


@pytest.mark.django_db
class TestRevisionRestore:
    def test_restore_chunk_from_revision(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "v1", "in_library": False},
            user=user,
        )
        # Change chunk content
        chunk.content = "v2"
        chunk.save()
        # Restore from revision
        response = client.post(f"/agent-builder/api/revisions/{revision.pk}/restore/")
        assert response.status_code == 200
        chunk.refresh_from_db()
        assert chunk.content == "v1"

    def test_restore_creates_new_revision(self, api_client):
        client, user = api_client
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "v1", "in_library": False},
            user=user,
        )
        chunk.content = "v2"
        chunk.save()
        client.post(f"/agent-builder/api/revisions/{revision.pk}/restore/")
        # Should have 2 revisions: original + restore
        revisions = Revision.objects.filter(content_type=ct, object_id=chunk.pk)
        assert revisions.count() == 2
        assert "Restored" in revisions.first().message

    def test_restore_other_users_revision_denied(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other_restore", password="pass")
        chunk = Chunk.objects.create(title="Test", content="v1", user=other_user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "v1"},
            user=other_user,
        )
        response = client.post(f"/agent-builder/api/revisions/{revision.pk}/restore/")
        assert response.status_code == 404


class TestProfileViewSet:
    @pytest.mark.django_db
    def test_list_profiles(self, api_client):
        client, user = api_client
        Profile.objects.create(
            name="config-1",
            snapshot={"agents": []},
            user=user,
        )
        response = client.get("/agent-builder/api/profiles/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.django_db
    def test_create_profile(self, api_client):
        client, user = api_client
        response = client.post(
            "/agent-builder/api/profiles/",
            {
                "name": "new-config",
                "description": "Test",
                "snapshot": {"agents": [], "chunks": [], "instructions": []},
            },
            format="json",
        )
        assert response.status_code == 201
        assert Profile.objects.filter(user=user).count() == 1

    @pytest.mark.django_db
    def test_user_scoping(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other_profile", password="pass")
        Profile.objects.create(
            name="other-config",
            snapshot={},
            user=other_user,
        )
        response = client.get("/agent-builder/api/profiles/")
        assert response.json() == []

    @pytest.mark.django_db
    def test_delete_profile(self, api_client):
        client, user = api_client
        profile = Profile.objects.create(
            name="config",
            snapshot={},
            user=user,
        )
        response = client.delete(f"/agent-builder/api/profiles/{profile.pk}/")
        assert response.status_code == 204
        assert Profile.objects.count() == 0


class TestProfileSnapshot:
    @pytest.mark.django_db
    def test_snapshot_captures_current_state(self, api_client):
        client, user = api_client
        Agent.objects.create(name="test-agent", display_name="Test", source="coderoo", user=user)
        profile = Profile.objects.create(
            name="config",
            snapshot={},
            user=user,
        )
        response = client.post(f"/agent-builder/api/profiles/{profile.pk}/snapshot/")
        assert response.status_code == 200
        profile.refresh_from_db()
        assert len(profile.snapshot["agents"]) == 1
        assert profile.snapshot["agents"][0]["name"] == "test-agent"


class TestProfileApply:
    @pytest.mark.django_db
    def test_apply_restores_state(self, api_client):
        client, user = api_client
        snapshot = {
            "agents": [
                {
                    "name": "restored-agent",
                    "display_name": "Restored",
                    "source": "claude",
                    "description": "",
                    "model": "sonnet",
                    "frontmatter": "",
                    "is_active": True,
                    "chunks": [],
                    "instructions": [],
                }
            ],
            "chunks": [],
            "instructions": [],
        }
        profile = Profile.objects.create(
            name="config",
            snapshot=snapshot,
            user=user,
        )
        response = client.post(f"/agent-builder/api/profiles/{profile.pk}/apply/")
        assert response.status_code == 200
        assert Agent.objects.filter(user=user, name="restored-agent").exists()


class TestProfileDiff:
    @pytest.mark.django_db
    def test_diff_two_profiles(self, api_client):
        client, user = api_client
        p1 = Profile.objects.create(
            name="v1",
            snapshot={"agents": [{"name": "agent-1"}], "chunks": [], "instructions": []},
            user=user,
        )
        p2 = Profile.objects.create(
            name="v2",
            snapshot={
                "agents": [{"name": "agent-1"}, {"name": "agent-2"}],
                "chunks": [],
                "instructions": [],
            },
            user=user,
        )
        response = client.get(f"/agent-builder/api/profiles/{p2.pk}/diff/?compare_to={p1.pk}")
        assert response.status_code == 200
        assert "diff" in response.json()

    @pytest.mark.django_db
    def test_diff_missing_compare_to(self, api_client):
        client, user = api_client
        profile = Profile.objects.create(
            name="config",
            snapshot={},
            user=user,
        )
        response = client.get(f"/agent-builder/api/profiles/{profile.pk}/diff/")
        assert response.status_code == 400


class TestConfigFileViewSet:
    @pytest.mark.django_db
    def test_list_config_files(self, api_client):
        client, user = api_client
        ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/test/CLAUDE.md",
            content="hi",
            user=user,
        )
        response = client.get("/agent-builder/api/config-files/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.django_db
    def test_create_config_file(self, api_client):
        client, user = api_client
        response = client.post(
            "/agent-builder/api/config-files/",
            {"filename": "CLAUDE.md", "path": "/new/CLAUDE.md", "content": "content"},
            format="json",
        )
        assert response.status_code == 201
        assert ConfigFile.objects.filter(user=user).count() == 1

    @pytest.mark.django_db
    def test_user_scoping(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="other", password="pass")
        ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/other/CLAUDE.md",
            content="",
            user=other_user,
        )
        response = client.get("/agent-builder/api/config-files/")
        assert response.json() == []

    @pytest.mark.django_db
    def test_delete_config_file(self, api_client):
        client, user = api_client
        cf = ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/del/CLAUDE.md",
            content="",
            user=user,
        )
        response = client.delete(f"/agent-builder/api/config-files/{cf.pk}/")
        assert response.status_code == 204


class TestApplyAllPreview:
    @pytest.mark.django_db
    def test_preview_returns_file_lists(self, api_client):
        client, user = api_client
        Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            user=user,
            is_active=True,
        )
        Instruction.objects.create(
            name="test-instr",
            display_name="Test",
            content="content",
            user=user,
        )
        ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/test/CLAUDE.md",
            content="content",
            user=user,
        )
        response = client.get("/agent-builder/api/apply-all/preview/")
        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "test-agent"
        assert len(data["instructions"]) == 1
        assert len(data["config_files"]) == 1

    @pytest.mark.django_db
    def test_preview_empty_state(self, api_client):
        client, user = api_client
        response = client.get("/agent-builder/api/apply-all/preview/")
        assert response.status_code == 200
        data = response.json()
        assert data["agents"] == []
        assert data["instructions"] == []
        assert data["config_files"] == []


class TestImportAllWithConfigFiles:
    @pytest.mark.django_db
    def test_import_includes_config_files_count(self, api_client, monkeypatch):
        client, user = api_client
        monkeypatch.setattr(
            "agent_builder.api_views.read_config_files",
            lambda: [{"filename": "CLAUDE.md", "path": "/tmp/CLAUDE.md", "content": "# Test"}],
        )
        monkeypatch.setattr("agent_builder.api_views.read_claude_agents", lambda: [])
        monkeypatch.setattr("agent_builder.api_views.read_coderoo_agents", lambda: [])
        monkeypatch.setattr("agent_builder.api_views.read_instructions", lambda: [])
        response = client.post("/agent-builder/api/import-all/")
        assert response.status_code == 200
        data = response.json()
        assert "config_files_imported" in data
        assert data["config_files_imported"] == 1


@pytest.mark.django_db
class TestProjectViewSet:
    def test_list_projects_empty(self, api_client):
        client, user = api_client
        response = client.get("/agent-builder/api/projects/")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_project(self, api_client):
        client, user = api_client
        response = client.post(
            "/agent-builder/api/projects/",
            {
                "name": "my-project",
                "path": "/storage/Projects/my-project",
                "has_coderoo": True,
                "has_claude_config": False,
            },
        )
        assert response.status_code == 201
        assert response.json()["name"] == "my-project"
        assert Project.objects.filter(user=user).count() == 1

    def test_retrieve_project(self, api_client):
        client, user = api_client
        project = Project.objects.create(
            name="test",
            path="/test/path",
            user=user,
        )
        response = client.get(f"/agent-builder/api/projects/{project.pk}/")
        assert response.status_code == 200
        assert response.json()["name"] == "test"

    def test_filter_by_has_coderoo(self, api_client):
        client, user = api_client
        Project.objects.create(
            name="coderoo",
            path="/a",
            has_coderoo=True,
            user=user,
        )
        Project.objects.create(
            name="claude",
            path="/b",
            has_claude_config=True,
            user=user,
        )
        response = client.get("/agent-builder/api/projects/?has_coderoo=true")
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "coderoo"

    def test_filter_by_has_claude_config(self, api_client):
        client, user = api_client
        Project.objects.create(
            name="coderoo",
            path="/a",
            has_coderoo=True,
            user=user,
        )
        Project.objects.create(
            name="claude",
            path="/b",
            has_claude_config=True,
            user=user,
        )
        response = client.get("/agent-builder/api/projects/?has_claude_config=true")
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "claude"

    def test_user_scoping(self, api_client):
        client, user = api_client
        other = User.objects.create_user(username="other", password="pass")
        Project.objects.create(name="mine", path="/mine", user=user)
        Project.objects.create(name="theirs", path="/theirs", user=other)
        response = client.get("/agent-builder/api/projects/")
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "mine"


@pytest.mark.django_db
class TestImportAllProjects:
    def test_import_all_includes_projects(self, api_client, tmp_path):
        client, user = api_client
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / ".coderoo").mkdir()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_SCAN_ROOTS", [tmp_path])
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_PROJECTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", tmp_path / "empty2")
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty3")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty4")
            response = client.post("/agent-builder/api/import-all/")

        assert response.status_code == 200
        data = response.json()
        assert data["projects_imported"] >= 1
        assert Project.objects.filter(user=user, name="my-project").exists()

    def test_import_all_updates_project_flags(self, api_client, tmp_path):
        client, user = api_client
        Project.objects.create(
            name="my-project",
            path=str(tmp_path / "my-project"),
            has_coderoo=True,
            has_claude_config=False,
            user=user,
        )
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / ".coderoo").mkdir()
        claude_dir = tmp_path / ".claude" / "projects"
        claude_dir.mkdir(parents=True)
        entry = claude_dir / "-tmp-my-project"
        entry.mkdir()
        (entry / "sessions-index.json").write_text(json.dumps({"originalPath": str(proj)}))

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_SCAN_ROOTS", [tmp_path])
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_PROJECTS_DIR", claude_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", tmp_path / "empty2")
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty3")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty4")
            response = client.post("/agent-builder/api/import-all/")

        data = response.json()
        assert data["projects_updated"] >= 1
        project = Project.objects.get(user=user, path=str(proj))
        assert project.has_coderoo is True
        assert project.has_claude_config is True

    def test_import_all_skips_unchanged_projects(self, api_client, tmp_path):
        client, user = api_client
        proj = tmp_path / "my-project"
        proj.mkdir()
        (proj / ".coderoo").mkdir()
        Project.objects.create(
            name="my-project",
            path=str(proj),
            has_coderoo=True,
            has_claude_config=False,
            user=user,
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_SCAN_ROOTS", [tmp_path])
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_PROJECTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", tmp_path / "empty2")
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty3")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty4")
            response = client.post("/agent-builder/api/import-all/")

        data = response.json()
        assert data["projects_skipped"] >= 1
        assert data["projects_imported"] == 0


@pytest.mark.django_db
class TestUserOptions:
    def test_get_defaults_for_new_user(self, api_client):
        client, user = api_client
        response = client.get("/agent-builder/api/user-options/")
        assert response.status_code == 200
        data = response.json()
        assert data["active_tab"] == "agents"
        assert data["agent_sub_tab"] == "coderoo"
        assert UserOptions.objects.filter(user=user).exists()

    def test_patch_active_tab(self, api_client):
        client, user = api_client
        response = client.patch(
            "/agent-builder/api/user-options/",
            {"active_tab": "projects"},
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["active_tab"] == "projects"
        opts = UserOptions.objects.get(user=user)
        assert opts.active_tab == "projects"

    def test_patch_agent_sub_tab(self, api_client):
        client, user = api_client
        response = client.patch(
            "/agent-builder/api/user-options/",
            {"agent_sub_tab": "claude"},
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["agent_sub_tab"] == "claude"

    def test_patch_invalid_choice_returns_400(self, api_client):
        client, user = api_client
        response = client.patch(
            "/agent-builder/api/user-options/",
            {"active_tab": "invalid"},
            format="json",
        )
        assert response.status_code == 400

    def test_index_view_passes_tab_context(self):
        from django.test import RequestFactory

        from agent_builder.views import IndexView

        user = User.objects.create_user(username="viewuser", password="testpass")
        UserOptions.objects.create(user=user, active_tab="projects", agent_sub_tab="claude")
        factory = RequestFactory()
        request = factory.get("/agent-builder/")
        request.user = user
        view = IndexView()
        view.request = request
        view.kwargs = {}
        context = view.get_context_data()
        assert context["active_tab"] == "projects"
        assert context["agent_sub_tab"] == "claude"

    def test_index_view_creates_defaults_for_new_user(self):
        from django.test import RequestFactory

        from agent_builder.views import IndexView

        user = User.objects.create_user(username="viewuser2", password="testpass")
        factory = RequestFactory()
        request = factory.get("/agent-builder/")
        request.user = user
        view = IndexView()
        view.request = request
        view.kwargs = {}
        context = view.get_context_data()
        assert context["active_tab"] == "agents"
        assert context["agent_sub_tab"] == "coderoo"
        assert UserOptions.objects.filter(user=user).exists()


@pytest.mark.django_db
class TestInitProjectWithClaude:
    def test_init_claude_queues_task(self, api_client):
        from unittest.mock import patch

        client, user = api_client
        project = Project.objects.create(name="test-proj", path="/tmp/test-proj", user=user)
        with patch("agent_builder.tasks.create_project_with_claude") as mock_task:
            mock_task.delay.return_value = None
            response = client.post(f"/agent-builder/api/projects/{project.id}/init-claude/")
        assert response.status_code == 200
        assert response.json() == {"status": "queued"}
        mock_task.delay.assert_called_once_with(project.pk, project.path)

    def test_init_claude_wrong_user_returns_404(self, api_client):
        client, user = api_client
        other_user = User.objects.create_user(username="otheruser", password="testpass")
        project = Project.objects.create(name="other-proj", path="/tmp/other-proj", user=other_user)
        response = client.post(f"/agent-builder/api/projects/{project.id}/init-claude/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestViewSetSoftDeletes:
    """Test that DELETE endpoints soft-delete and soft-deleted items are excluded from lists."""

    def test_delete_instruction_soft_deletes(self, api_client):
        client, user = api_client
        inst = Instruction.objects.create(name="test", display_name="Test", content="c", user=user)
        response = client.delete(f"/agent-builder/api/instructions/{inst.pk}/")
        assert response.status_code == 204
        assert Instruction.objects.filter(pk=inst.pk).count() == 0
        deleted = Instruction.all_objects.get(pk=inst.pk)
        assert deleted.is_deleted is True

    def test_soft_deleted_instruction_not_in_list(self, api_client):
        client, user = api_client
        inst = Instruction.objects.create(name="test", display_name="Test", content="c", user=user)
        inst.soft_delete()
        response = client.get("/agent-builder/api/instructions/")
        assert len(response.json()) == 0

    def test_delete_config_file_soft_deletes(self, api_client):
        client, user = api_client
        cf = ConfigFile.objects.create(
            filename="CLAUDE.md", path="/del/CLAUDE.md", content="", user=user
        )
        response = client.delete(f"/agent-builder/api/config-files/{cf.pk}/")
        assert response.status_code == 204
        assert ConfigFile.objects.filter(pk=cf.pk).count() == 0
        deleted = ConfigFile.all_objects.get(pk=cf.pk)
        assert deleted.is_deleted is True

    def test_soft_deleted_config_file_not_in_list(self, api_client):
        client, user = api_client
        cf = ConfigFile.objects.create(
            filename="CLAUDE.md", path="/del/CLAUDE.md", content="", user=user
        )
        cf.soft_delete()
        response = client.get("/agent-builder/api/config-files/")
        assert len(response.json()) == 0

    def test_delete_project_soft_deletes(self, api_client):
        client, user = api_client
        proj = Project.objects.create(name="test", path="/del/test", user=user)
        response = client.delete(f"/agent-builder/api/projects/{proj.pk}/")
        assert response.status_code == 204
        assert Project.objects.filter(pk=proj.pk).count() == 0
        deleted = Project.all_objects.get(pk=proj.pk)
        assert deleted.is_deleted is True

    def test_soft_deleted_project_not_in_list(self, api_client):
        client, user = api_client
        proj = Project.objects.create(name="test", path="/del/test", user=user)
        proj.soft_delete()
        response = client.get("/agent-builder/api/projects/")
        assert len(response.json()) == 0


@pytest.mark.django_db
class TestApplyPreviewDeletedInDb:
    """Test that apply-all preview includes soft-deleted items when files exist on disk."""

    def test_preview_includes_soft_deleted_agent_when_file_exists(self, api_client, tmp_path):
        client, user = api_client
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "ghost.md").write_text("# Ghost agent")

        agent = Agent.objects.create(name="ghost", display_name="Ghost", source="claude", user=user)
        agent.soft_delete()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", agents_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty2")
            response = client.get("/agent-builder/api/apply-all/preview/")

        assert response.status_code == 200
        agents = response.json()["agents"]
        deleted_in_db = [a for a in agents if a.get("deleted_in_db")]
        assert len(deleted_in_db) == 1
        assert deleted_in_db[0]["name"] == "ghost"

    def test_preview_excludes_soft_deleted_agent_when_no_file(self, api_client, tmp_path):
        client, user = api_client
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        # No file on disk for this agent

        agent = Agent.objects.create(name="gone", display_name="Gone", source="claude", user=user)
        agent.soft_delete()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", agents_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty2")
            response = client.get("/agent-builder/api/apply-all/preview/")

        assert response.status_code == 200
        agents = response.json()["agents"]
        assert len(agents) == 0

    def test_apply_all_delete_from_disk(self, api_client, tmp_path):
        client, user = api_client
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        target_file = agents_dir / "ghost.md"
        target_file.write_text("# Ghost agent")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", agents_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty2")
            response = client.post(
                "/agent-builder/api/apply-all/",
                {"delete_from_disk": [{"path": str(target_file)}]},
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["deleted_from_disk"] == 1
        assert not target_file.exists()

    def test_apply_all_delete_from_disk_rejects_outside_paths(self, api_client, tmp_path):
        client, user = api_client
        # Create a file outside allowed directories
        outside_file = tmp_path / "outside" / "secret.txt"
        outside_file.parent.mkdir(parents=True)
        outside_file.write_text("secret data")

        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", agents_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty2")
            response = client.post(
                "/agent-builder/api/apply-all/",
                {"delete_from_disk": [{"path": str(outside_file)}]},
                format="json",
            )

        assert response.status_code == 200
        assert response.json()["deleted_from_disk"] == 0
        assert outside_file.exists()  # File should NOT have been deleted


@pytest.mark.django_db
class TestImportDiskDeletions:
    """Test that import detects DB records whose disk files are missing."""

    def _mock_import(
        self,
        client,
        agents=None,
        instructions=None,
        config_files=None,
        projects=None,
        resolutions=None,
    ):
        """Helper to call import-all with mocked filesystem readers."""
        body = {}
        if resolutions:
            body["resolutions"] = resolutions
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.api_views.read_claude_agents", lambda: agents or [])
            mp.setattr("agent_builder.api_views.read_coderoo_agents", lambda: [])
            mp.setattr("agent_builder.api_views.read_instructions", lambda: instructions or [])
            mp.setattr("agent_builder.api_views.read_config_files", lambda: config_files or [])
            mp.setattr("agent_builder.api_views.scan_projects", lambda: projects or [])
            return client.post(
                "/agent-builder/api/import-all/",
                body,
                format="json",
            )

    def test_import_detects_missing_disk_agent(self, api_client):
        """Import returns disk_deletions for agents with last_synced_at but no disk file."""
        client, user = api_client
        from django.utils import timezone as tz

        agent = Agent.objects.create(
            name="orphan", display_name="Orphan", source="claude", user=user
        )
        Agent.objects.filter(pk=agent.pk).update(last_synced_at=tz.now())

        response = self._mock_import(client)  # No agents on disk

        assert response.status_code == 200
        data = response.json()
        deletions = data["disk_deletions"]
        assert len(deletions) == 1
        assert deletions[0]["type"] == "agent"
        assert deletions[0]["name"] == "orphan"
        assert deletions[0]["status"] == "deleted_on_disk"
        # Agent should still exist (not auto-deleted)
        assert Agent.objects.filter(pk=agent.pk).exists()

    def test_import_with_soft_delete_resolution(self, api_client):
        """Import with resolution='soft_delete' soft-deletes the record."""
        client, user = api_client
        from django.utils import timezone as tz

        agent = Agent.objects.create(
            name="orphan", display_name="Orphan", source="claude", user=user
        )
        Agent.objects.filter(pk=agent.pk).update(last_synced_at=tz.now())

        response = self._mock_import(client, resolutions={"agent:orphan": "soft_delete"})

        assert response.status_code == 200
        data = response.json()
        assert data["disk_deleted"] == 1
        assert len(data["disk_deletions"]) == 0
        # Agent should be soft-deleted
        assert not Agent.objects.filter(pk=agent.pk).exists()
        assert Agent.all_objects.filter(pk=agent.pk, is_deleted=True).exists()

    def test_import_skips_never_synced_agents(self, api_client):
        """Agents with no last_synced_at should not appear in disk_deletions."""
        client, user = api_client
        Agent.objects.create(name="new-agent", display_name="New", source="claude", user=user)
        # last_synced_at is None by default

        response = self._mock_import(client)

        assert response.status_code == 200
        assert len(response.json()["disk_deletions"]) == 0


@pytest.mark.django_db
class TestApplyAllSelectedPaths:
    """Test that apply_all respects selected_paths filtering."""

    def test_apply_only_selected_paths(self, api_client, tmp_path):
        """Only items in selected_paths should be written to disk."""
        client, user = api_client
        Agent.objects.create(name="included", display_name="Included", source="claude", user=user)
        Agent.objects.create(name="excluded", display_name="Excluded", source="claude", user=user)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        included_path = str(agents_dir / "included.md")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", agents_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty2")
            response = client.post(
                "/agent-builder/api/apply-all/",
                {"selected_paths": [included_path]},
                format="json",
            )

        assert response.status_code == 200
        results = response.json()["results"]
        names = [r["name"] for r in results]
        assert "included" in names
        assert "excluded" not in names

    def test_apply_without_selected_paths_writes_everything(self, api_client, tmp_path):
        """When selected_paths is not sent, all items should be processed."""
        client, user = api_client
        Agent.objects.create(name="agent-a", display_name="A", source="claude", user=user)
        Agent.objects.create(name="agent-b", display_name="B", source="claude", user=user)
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("agent_builder.filesystem.DEFAULT_CLAUDE_AGENTS_DIR", agents_dir)
            mp.setattr("agent_builder.filesystem.DEFAULT_CODEROO_AGENTS_DIR", tmp_path / "empty")
            mp.setattr("agent_builder.filesystem.DEFAULT_INSTRUCTIONS_DIR", tmp_path / "empty2")
            response = client.post(
                "/agent-builder/api/apply-all/",
                {},
                format="json",
            )

        assert response.status_code == 200
        results = response.json()["results"]
        names = [r["name"] for r in results]
        assert "agent-a" in names
        assert "agent-b" in names
