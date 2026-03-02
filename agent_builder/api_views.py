"""API views for agent_builder with OAuth2 authentication and user scoping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

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
