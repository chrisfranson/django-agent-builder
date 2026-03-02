"""
Tests for agent_builder serializers.
"""

import pytest
from django.contrib.auth import get_user_model

from agent_builder.models import (
    Agent,
    AgentChunk,
    AgentInstruction,
    Chunk,
    ChunkVariant,
    Instruction,
)
from agent_builder.serializers import (
    AgentChunkSerializer,
    AgentInstructionSerializer,
    AgentListSerializer,
    AgentSerializer,
    ChunkSerializer,
    ChunkVariantSerializer,
    InstructionSerializer,
)

User = get_user_model()


@pytest.mark.django_db
class TestAgentSerializer:
    def test_serialize_agent(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test Agent",
            source="claude",
            description="Desc",
            model="sonnet",
            frontmatter="name: test-agent",
            user=user,
        )
        serializer = AgentSerializer(agent)
        data = serializer.data
        assert data["name"] == "test-agent"
        assert data["source"] == "claude"
        assert "agent_chunks" in data
        assert "user" in data
        assert "created_at" in data

    def test_agent_with_chunks(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk = Chunk.objects.create(title="Instructions", content="Do things", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        serializer = AgentSerializer(agent)
        data = serializer.data
        assert len(data["agent_chunks"]) == 1
        assert data["agent_chunks"][0]["chunk"]["title"] == "Instructions"
        assert data["agent_chunks"][0]["position"] == 0

    def test_agent_list_serializer_excludes_chunks(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        serializer = AgentListSerializer(agent)
        data = serializer.data
        assert "agent_chunks" not in data
        assert data["name"] == "test-agent"


@pytest.mark.django_db
class TestChunkSerializer:
    def test_serialize_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(title="Test", content="Content", user=user)
        serializer = ChunkSerializer(chunk)
        data = serializer.data
        assert data["title"] == "Test"
        assert data["content"] == "Content"
        assert "user" in data


@pytest.mark.django_db
class TestAgentChunkSerializer:
    def test_serialize_agent_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk = Chunk.objects.create(title="Test Chunk", content="Content", user=user)
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        serializer = AgentChunkSerializer(ac)
        data = serializer.data
        assert data["position"] == 0
        assert data["is_enabled"] is True
        assert data["chunk"]["title"] == "Test Chunk"


@pytest.mark.django_db
class TestChunkVariantSerializer:
    def test_serialize_chunk_variant(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="gentle version", position=0
        )
        serializer = ChunkVariantSerializer(variant)
        data = serializer.data
        assert data["id"] == variant.pk
        assert data["label"] == "gentle"
        assert data["content"] == "gentle version"
        assert data["position"] == 0

    def test_deserialize_chunk_variant(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        data = {"label": "firm", "content": "firm version", "position": 1}
        serializer = ChunkVariantSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        variant = serializer.save(chunk=chunk)
        assert variant.label == "firm"
        assert variant.chunk == chunk

    def test_chunk_variant_read_only_fields(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="content", position=0
        )
        serializer = ChunkVariantSerializer(variant)
        assert "chunk" not in serializer.data  # chunk set via URL nesting, not serializer


@pytest.mark.django_db
class TestInstructionSerializer:
    def test_serialize_instruction(self, user):
        instruction = Instruction.objects.create(
            name="coding-standards",
            display_name="Coding Standards",
            content="Follow PEP 8.",
            injection_mode="on_demand",
            user=user,
        )
        data = InstructionSerializer(instruction).data
        assert data["name"] == "coding-standards"
        assert data["injection_mode"] == "on_demand"
        assert "user" in data
        assert "created_at" in data


@pytest.mark.django_db
class TestAgentInstructionSerializer:
    def test_serialize_agent_instruction(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        instruction = Instruction.objects.create(
            name="standards", display_name="Standards", content="content", user=user
        )
        ai = AgentInstruction.objects.create(
            agent=agent, instruction=instruction, injection_mode="auto_inject"
        )
        data = AgentInstructionSerializer(ai).data
        assert data["instruction"]["name"] == "standards"
        assert data["injection_mode"] == "auto_inject"
        assert "instruction_id" not in data  # write-only
