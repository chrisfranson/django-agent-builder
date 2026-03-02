import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from agent_builder.models import Agent, AgentChunk, Chunk

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
