"""API views for agent_builder with OAuth2 authentication and user scoping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.decorators import permission_classes as perm_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .filesystem import read_claude_agents, read_coderoo_agents, write_agent
from .models import Agent, AgentChunk, Chunk
from .serializers import AgentChunkSerializer, AgentListSerializer, AgentSerializer, ChunkSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet


class AgentViewSet(viewsets.ModelViewSet):
    """CRUD for agents with automatic user scoping."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "list":
            return AgentListSerializer
        return AgentSerializer

    def get_queryset(self) -> QuerySet[Agent]:
        qs = Agent.objects.filter(user=self.request.user)
        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)
        return qs

    def perform_create(self, serializer) -> None:
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """Write this agent to disk."""
        agent = self.get_object()
        try:
            path = write_agent(agent)
            return Response({"status": "ok", "path": str(path)})
        except Exception as e:
            return Response({"status": "error", "detail": str(e)}, status=500)


class ChunkViewSet(viewsets.ModelViewSet):
    """CRUD for chunks with optional library filtering."""

    serializer_class = ChunkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Chunk]:
        qs = Chunk.objects.filter(user=self.request.user)
        if self.request.query_params.get("library") == "true":
            qs = qs.filter(in_library=True)
        return qs

    def perform_create(self, serializer) -> None:
        serializer.save(user=self.request.user)


class AgentChunkViewSet(viewsets.ModelViewSet):
    """Manage chunks attached to a specific agent."""

    serializer_class = AgentChunkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[AgentChunk]:
        return AgentChunk.objects.filter(
            agent_id=self.kwargs["agent_pk"],
            agent__user=self.request.user,
        )

    def perform_create(self, serializer) -> None:
        chunk = serializer.validated_data["chunk"]
        if chunk.user != self.request.user:
            raise PermissionDenied("Cannot link a chunk owned by another user.")
        serializer.save(agent_id=self.kwargs["agent_pk"])


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def import_all(request):
    """Bulk import agents from disk into the database."""
    imported = 0
    skipped = 0

    for agent_data in read_claude_agents():
        if Agent.objects.filter(user=request.user, name=agent_data["name"]).exists():
            skipped += 1
            continue
        _import_agent(request.user, agent_data)
        imported += 1

    for agent_data in read_coderoo_agents():
        if Agent.objects.filter(user=request.user, name=agent_data["name"]).exists():
            skipped += 1
            continue
        _import_agent(request.user, agent_data)
        imported += 1

    return Response({"status": "ok", "imported": imported, "skipped": skipped})


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def apply_all(request):
    """Write all active agents to disk."""
    agents = Agent.objects.filter(user=request.user, is_active=True)
    results = []
    for agent in agents:
        try:
            path = write_agent(agent)
            results.append({"name": agent.name, "status": "ok", "path": str(path)})
        except Exception as e:
            results.append({"name": agent.name, "status": "error", "detail": str(e)})
    return Response({"results": results})


def _parse_frontmatter_dict(fm_text: str) -> dict:
    """Parse frontmatter text to dict."""
    result = {}
    current_key = None
    current_value = []

    for line in fm_text.split("\n"):
        if not line.startswith(" ") and not line.startswith("\t"):
            if current_key:
                result[current_key] = "\n".join(current_value).strip()
            if ":" in line:
                key, _, value = line.partition(":")
                current_key = key.strip()
                current_value = [value.strip()]
            else:
                current_key = None
                current_value = []
        else:
            if current_key:
                current_value.append(line)

    if current_key:
        result[current_key] = "\n".join(current_value).strip()
    return result


def _import_agent(user, agent_data: dict) -> Agent:
    """Import a single agent from parsed disk data."""
    fm_dict = _parse_frontmatter_dict(agent_data["frontmatter"])
    agent = Agent.objects.create(
        name=agent_data["name"],
        display_name=fm_dict.get("name", agent_data["name"]).replace("-", " ").title(),
        source=agent_data["source"],
        description=fm_dict.get("description", ""),
        model=fm_dict.get("model", "sonnet"),
        frontmatter=agent_data["frontmatter"],
        user=user,
    )
    if agent_data.get("content"):
        chunk = Chunk.objects.create(content=agent_data["content"], user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
    return agent
