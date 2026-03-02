import pytest

from agent_builder.models import (
    Agent,
    AgentChunk,
    AgentInstruction,
    Chunk,
    ChunkVariant,
    Instruction,
)
from agent_builder.profiles import capture_snapshot, restore_snapshot


class TestCaptureSnapshot:
    @pytest.mark.django_db
    def test_capture_empty_state(self, user):
        snapshot = capture_snapshot(user)
        assert snapshot == {"agents": [], "chunks": [], "instructions": []}

    @pytest.mark.django_db
    def test_capture_agents_with_chunks(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        chunk = Chunk.objects.create(title="Intro", content="Hello", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        snapshot = capture_snapshot(user)
        assert len(snapshot["agents"]) == 1
        assert snapshot["agents"][0]["name"] == "test-agent"
        assert len(snapshot["agents"][0]["chunks"]) == 1
        assert snapshot["agents"][0]["chunks"][0]["title"] == "Intro"

    @pytest.mark.django_db
    def test_capture_agents_with_instructions(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Standards",
            content="rules",
            user=user,
        )
        AgentInstruction.objects.create(agent=agent, instruction=instruction)
        snapshot = capture_snapshot(user)
        assert len(snapshot["agents"][0]["instructions"]) == 1

    @pytest.mark.django_db
    def test_capture_includes_variants(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        ChunkVariant.objects.create(chunk=chunk, label="gentle", content="gentle", position=0)
        snapshot = capture_snapshot(user)
        assert len(snapshot["chunks"][0]["variants"]) == 1

    @pytest.mark.django_db
    def test_capture_standalone_chunks(self, user):
        Chunk.objects.create(title="Library Chunk", content="shared", in_library=True, user=user)
        snapshot = capture_snapshot(user)
        assert len(snapshot["chunks"]) == 1
        assert snapshot["chunks"][0]["title"] == "Library Chunk"

    @pytest.mark.django_db
    def test_capture_standalone_instructions(self, user):
        Instruction.objects.create(name="test", display_name="Test", content="content", user=user)
        snapshot = capture_snapshot(user)
        assert len(snapshot["instructions"]) == 1


class TestRestoreSnapshot:
    @pytest.mark.django_db
    def test_restore_creates_agents(self, user):
        snapshot = {
            "agents": [
                {
                    "name": "restored-agent",
                    "display_name": "Restored",
                    "source": "coderoo",
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
        restore_snapshot(snapshot, user)
        assert Agent.objects.filter(user=user, name="restored-agent").exists()

    @pytest.mark.django_db
    def test_restore_creates_chunks_and_links(self, user):
        snapshot = {
            "agents": [
                {
                    "name": "agent-1",
                    "display_name": "Agent 1",
                    "source": "claude",
                    "description": "",
                    "model": "sonnet",
                    "frontmatter": "",
                    "is_active": True,
                    "chunks": [
                        {
                            "title": "Intro",
                            "content": "Hello world",
                            "in_library": False,
                            "position": 0,
                            "is_enabled": True,
                            "active_variant": None,
                            "variants": [],
                        }
                    ],
                    "instructions": [],
                }
            ],
            "chunks": [],
            "instructions": [],
        }
        restore_snapshot(snapshot, user)
        agent = Agent.objects.get(user=user, name="agent-1")
        assert agent.agent_chunks.count() == 1
        assert agent.agent_chunks.first().chunk.title == "Intro"

    @pytest.mark.django_db
    def test_restore_overwrites_existing(self, user):
        Agent.objects.create(name="existing", display_name="Old", source="coderoo", user=user)
        snapshot = {
            "agents": [
                {
                    "name": "existing",
                    "display_name": "New Display",
                    "source": "coderoo",
                    "description": "updated",
                    "model": "opus",
                    "frontmatter": "",
                    "is_active": True,
                    "chunks": [],
                    "instructions": [],
                }
            ],
            "chunks": [],
            "instructions": [],
        }
        restore_snapshot(snapshot, user)
        agent = Agent.objects.get(user=user, name="existing")
        assert agent.display_name == "New Display"
        assert agent.model == "opus"

    @pytest.mark.django_db
    def test_restore_roundtrip(self, user):
        """Capture, modify, restore should return to original state."""
        agent = Agent.objects.create(
            name="roundtrip", display_name="RT", source="claude", user=user
        )
        chunk = Chunk.objects.create(title="Test", content="original", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        snapshot = capture_snapshot(user)
        # Modify
        chunk.content = "modified"
        chunk.save()
        # Restore
        restore_snapshot(snapshot, user)
        chunk.refresh_from_db()
        assert chunk.content == "original"
