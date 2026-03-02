"""
Tests for agent_builder models.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from agent_builder.models import Agent, AgentChunk, Chunk

User = get_user_model()


@pytest.mark.django_db
class TestAgentModel:
    def test_create_claude_agent(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test Agent",
            source="claude",
            description="A test agent",
            model="sonnet",
            frontmatter="name: test-agent\ndescription: A test agent\nmodel: sonnet",
            user=user,
        )
        assert agent.name == "test-agent"
        assert agent.source == "claude"
        assert agent.is_active is True
        assert str(agent) == "test-agent (claude)"

    def test_create_coderoo_agent(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="my-coderoo-agent",
            display_name="My Coderoo Agent",
            source="coderoo",
            user=user,
        )
        assert agent.source == "coderoo"

    def test_agent_name_unique_per_user(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        Agent.objects.create(name="dupe", display_name="Dupe", source="claude", user=user)
        with pytest.raises(IntegrityError):
            Agent.objects.create(name="dupe", display_name="Dupe 2", source="claude", user=user)

    def test_agents_ordered_by_name(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        Agent.objects.create(name="zebra", display_name="Zebra", source="claude", user=user)
        Agent.objects.create(name="alpha", display_name="Alpha", source="claude", user=user)
        agents = list(Agent.objects.filter(user=user))
        assert agents[0].name == "alpha"
        assert agents[1].name == "zebra"


@pytest.mark.django_db
class TestChunkModel:
    def test_create_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(
            title="Core Instructions",
            content="## Role\nYou are a helpful assistant.",
            in_library=True,
            user=user,
        )
        assert chunk.title == "Core Instructions"
        assert chunk.in_library is True
        assert str(chunk) == "Core Instructions"

    def test_unnamed_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(content="Some content", user=user)
        assert chunk.title == ""
        assert chunk.in_library is False
        assert str(chunk) == f"Chunk #{chunk.pk}"


@pytest.mark.django_db
class TestAgentChunkModel:
    def test_agent_chunk_ordering(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk_a = Chunk.objects.create(content="First section", user=user)
        chunk_b = Chunk.objects.create(content="Second section", user=user)

        AgentChunk.objects.create(agent=agent, chunk=chunk_b, position=1)
        AgentChunk.objects.create(agent=agent, chunk=chunk_a, position=0)

        agent_chunks = list(AgentChunk.objects.filter(agent=agent))
        assert agent_chunks[0].chunk == chunk_a
        assert agent_chunks[1].chunk == chunk_b

    def test_agent_chunk_enabled_default(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk = Chunk.objects.create(content="Content", user=user)
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        assert ac.is_enabled is True
        assert ac.active_variant is None

    def test_agent_chunks_via_m2m(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk = Chunk.objects.create(content="Content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        assert agent.chunks.count() == 1
        assert agent.chunks.first() == chunk
