"""
Tests for agent_builder models.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from agent_builder.models import Agent

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
