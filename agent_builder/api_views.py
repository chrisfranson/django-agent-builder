"""API views for agent_builder with OAuth2 authentication and user scoping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.decorators import permission_classes as perm_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .filesystem import (
    read_claude_agents,
    read_coderoo_agents,
    read_instructions,
    write_agent,
    write_instruction,
)
from .models import Agent, AgentChunk, AgentInstruction, Chunk, ChunkVariant, Instruction
from .serializers import (
    AgentChunkSerializer,
    AgentInstructionSerializer,
    AgentListSerializer,
    AgentSerializer,
    ChunkSerializer,
    ChunkVariantSerializer,
    InstructionSerializer,
)

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
        from django.db.models import Q

        qs = Chunk.objects.filter(user=self.request.user)
        if self.request.query_params.get("library") == "true":
            qs = qs.filter(in_library=True)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(content__icontains=search))
        return qs

    def perform_create(self, serializer) -> None:
        serializer.save(user=self.request.user)


class ChunkVariantViewSet(viewsets.ModelViewSet):
    """CRUD for chunk variants, nested under a chunk."""

    serializer_class = ChunkVariantSerializer
    permission_classes = [IsAuthenticated]

    def _get_chunk(self):
        return get_object_or_404(Chunk, pk=self.kwargs["chunk_pk"], user=self.request.user)

    def get_queryset(self) -> QuerySet[ChunkVariant]:
        chunk = self._get_chunk()
        return ChunkVariant.objects.filter(chunk=chunk)

    def perform_create(self, serializer) -> None:
        chunk = self._get_chunk()
        serializer.save(chunk=chunk)


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


class InstructionViewSet(viewsets.ModelViewSet):
    """CRUD for instructions with automatic user scoping."""

    serializer_class = InstructionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Instruction.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AgentInstructionViewSet(viewsets.ModelViewSet):
    """Manage instructions attached to a specific agent."""

    serializer_class = AgentInstructionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return AgentInstruction.objects.filter(
            agent_id=self.kwargs["agent_pk"],
            agent__user=self.request.user,
        ).select_related("instruction")

    def perform_create(self, serializer):
        from rest_framework import serializers as drf_serializers

        agent = Agent.objects.get(pk=self.kwargs["agent_pk"], user=self.request.user)
        instruction = serializer.validated_data["instruction"]
        if instruction.user != self.request.user:
            raise drf_serializers.ValidationError("Instruction must belong to the same user.")
        serializer.save(agent=agent)


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def split_chunk(request, pk):
    """Split a chunk at the given character position into two new chunks."""
    chunk = Chunk.objects.filter(pk=pk, user=request.user).first()
    if not chunk:
        return Response({"detail": "Not found."}, status=404)

    position = request.data.get("position")
    if position is None:
        return Response({"detail": "position is required."}, status=400)

    position = int(position)
    content = chunk.content
    if position <= 0 or position >= len(content):
        return Response({"detail": "position out of range."}, status=400)

    first_content = content[:position].strip()
    second_content = content[position:].strip()

    with transaction.atomic():
        chunk1 = Chunk.objects.create(
            title=chunk.title,
            content=first_content,
            in_library=chunk.in_library,
            user=chunk.user,
        )
        chunk2 = Chunk.objects.create(
            title="",
            content=second_content,
            in_library=False,
            user=chunk.user,
        )

        agent_chunks = AgentChunk.objects.filter(chunk=chunk).select_related("agent")
        for ac in agent_chunks:
            original_position = ac.position
            AgentChunk.objects.filter(agent=ac.agent, position__gt=original_position).update(
                position=F("position") + 1
            )
            ac.chunk = chunk1
            ac.save()
            AgentChunk.objects.create(
                agent=ac.agent,
                chunk=chunk2,
                position=original_position + 1,
                is_enabled=ac.is_enabled,
            )

        chunk.delete()

    return Response(
        {"chunks": ChunkSerializer([chunk1, chunk2], many=True).data},
        status=200,
    )


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

    instructions_imported = 0
    instructions_skipped = 0
    for instr_data in read_instructions():
        if Instruction.objects.filter(user=request.user, name=instr_data["name"]).exists():
            instructions_skipped += 1
            continue
        Instruction.objects.create(
            name=instr_data["name"],
            display_name=instr_data["name"].replace("-", " ").title(),
            content=instr_data["content"],
            user=request.user,
        )
        instructions_imported += 1

    return Response(
        {
            "status": "ok",
            "imported": imported,
            "skipped": skipped,
            "instructions_imported": instructions_imported,
            "instructions_skipped": instructions_skipped,
        }
    )


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def apply_all(request):
    """Write all active agents and instructions to disk."""
    agents = Agent.objects.filter(user=request.user, is_active=True)
    results = []
    for agent in agents:
        try:
            path = write_agent(agent)
            results.append({"name": agent.name, "status": "ok", "path": str(path)})
        except Exception as e:
            results.append({"name": agent.name, "status": "error", "detail": str(e)})

    instruction_results = []
    for instruction in Instruction.objects.filter(user=request.user):
        try:
            path = write_instruction(instruction)
            instruction_results.append(
                {"name": instruction.name, "status": "ok", "path": str(path)}
            )
        except Exception as e:
            instruction_results.append(
                {"name": instruction.name, "status": "error", "detail": str(e)}
            )

    return Response({"results": results, "instruction_results": instruction_results})


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
