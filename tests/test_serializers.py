"""
Tests for agent_builder serializers.
"""

import pytest
from django.contrib.auth import get_user_model

from agent_builder.models import Agent, AgentChunk, Chunk
from agent_builder.serializers import (
    AgentChunkSerializer,
    AgentListSerializer,
    AgentSerializer,
    ChunkSerializer,
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
