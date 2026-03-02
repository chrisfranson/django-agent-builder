"""API views for agent_builder with OAuth2 authentication and user scoping."""

from __future__ import annotations

import difflib
import json
from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType
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
    read_config_files,
    read_instructions,
    scan_projects,
    write_agent,
    write_config_file,
    write_instruction,
)
from .models import (
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
)
from .profiles import capture_snapshot, restore_snapshot
from .revisions import create_revision, get_snapshot
from .serializers import (
    AgentChunkSerializer,
    AgentInstructionSerializer,
    AgentListSerializer,
    AgentSerializer,
    ChunkSerializer,
    ChunkVariantSerializer,
    ConfigFileSerializer,
    InstructionSerializer,
    ProfileSerializer,
    ProjectListSerializer,
    ProjectSerializer,
    RevisionSerializer,
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

    def perform_update(self, serializer) -> None:
        instance = serializer.save()
        create_revision(instance, self.request.user)


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

    def perform_update(self, serializer) -> None:
        instance = serializer.save()
        create_revision(instance, self.request.user)


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


class RevisionViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to content revisions with diff and restore actions."""

    serializer_class = RevisionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Revision]:
        return Revision.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        ct = request.query_params.get("content_type")
        obj_id = request.query_params.get("object_id")
        if not ct or not obj_id:
            return Response(
                {"detail": "content_type and object_id query params required."},
                status=400,
            )
        queryset = self.get_queryset().filter(content_type_id=ct, object_id=obj_id)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def diff(self, request, pk=None):
        """Compare this revision to another."""
        revision = self.get_object()
        compare_to_id = request.query_params.get("compare_to")
        if not compare_to_id:
            return Response({"detail": "compare_to query param required."}, status=400)
        compare_to = get_object_or_404(self.get_queryset(), pk=compare_to_id)
        diff_result = {}
        for key in set(revision.content_snapshot.keys()) | set(compare_to.content_snapshot.keys()):
            old_val = str(compare_to.content_snapshot.get(key, ""))
            new_val = str(revision.content_snapshot.get(key, ""))
            if old_val != new_val:
                diff_result[key] = list(
                    difflib.unified_diff(
                        old_val.splitlines(keepends=True),
                        new_val.splitlines(keepends=True),
                        fromfile=f"revision {compare_to.pk}",
                        tofile=f"revision {revision.pk}",
                    )
                )
        return Response({"diff": diff_result})

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Restore an object to this revision's snapshot."""
        revision = self.get_object()
        ct = revision.content_type
        model_class = ct.model_class()
        try:
            instance = model_class.objects.get(pk=revision.object_id, user=request.user)
        except model_class.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)

        # Apply snapshot fields
        snapshot = revision.content_snapshot
        for field, value in snapshot.items():
            if hasattr(instance, field):
                setattr(instance, field, value)
        instance.save()

        # Always create a revision for restore (bypass dedup)
        ct = ContentType.objects.get_for_model(instance)
        Revision.objects.create(
            content_type=ct,
            object_id=instance.pk,
            content_snapshot=get_snapshot(instance),
            message=f"Restored from revision {revision.pk}",
            user=request.user,
        )
        return Response({"status": "ok", "restored_from": revision.pk})


class ProfileViewSet(viewsets.ModelViewSet):
    """CRUD for profiles with snapshot capture, apply, and diff."""

    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Profile]:
        return Profile.objects.filter(user=self.request.user)

    def perform_create(self, serializer) -> None:
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"])
    def snapshot(self, request, pk=None):
        """Capture current system state into this profile's snapshot."""
        profile = self.get_object()
        profile.snapshot = capture_snapshot(request.user)
        profile.save()
        return Response({"status": "ok"})

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """Restore system state from this profile's snapshot."""
        profile = self.get_object()
        restore_snapshot(profile.snapshot, request.user)
        return Response({"status": "ok", "profile": profile.name})

    @action(detail=True, methods=["get"])
    def diff(self, request, pk=None):
        """Compare this profile's snapshot to another profile."""
        profile = self.get_object()
        compare_to_id = request.query_params.get("compare_to")
        if not compare_to_id:
            return Response({"detail": "compare_to query param required."}, status=400)
        compare_to = get_object_or_404(self.get_queryset(), pk=compare_to_id)

        diff_result = {}
        all_keys = set(profile.snapshot.keys()) | set(compare_to.snapshot.keys())
        for key in all_keys:
            old_val = json.dumps(compare_to.snapshot.get(key, []), indent=2, sort_keys=True)
            new_val = json.dumps(profile.snapshot.get(key, []), indent=2, sort_keys=True)
            if old_val != new_val:
                diff_result[key] = list(
                    difflib.unified_diff(
                        old_val.splitlines(keepends=True),
                        new_val.splitlines(keepends=True),
                        fromfile=f"profile {compare_to.pk}",
                        tofile=f"profile {profile.pk}",
                    )
                )
        return Response({"diff": diff_result})


class ConfigFileViewSet(viewsets.ModelViewSet):
    """CRUD for config files (CLAUDE.md, AGENTS.md)."""

    serializer_class = ConfigFileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ConfigFile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ProjectViewSet(viewsets.ModelViewSet):
    """CRUD for detected projects."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "list":
            return ProjectListSerializer
        return ProjectSerializer

    def get_queryset(self):
        qs = Project.objects.filter(user=self.request.user)
        has_coderoo = self.request.query_params.get("has_coderoo")
        if has_coderoo is not None:
            qs = qs.filter(has_coderoo=has_coderoo.lower() == "true")
        has_claude_config = self.request.query_params.get("has_claude_config")
        if has_claude_config is not None:
            qs = qs.filter(has_claude_config=has_claude_config.lower() == "true")
        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


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

    # Import config files (CLAUDE.md, AGENTS.md)
    config_files_imported = 0
    config_files_skipped = 0
    for cf_data in read_config_files():
        if ConfigFile.objects.filter(user=request.user, path=cf_data["path"]).exists():
            config_files_skipped += 1
            continue
        ConfigFile.objects.create(
            filename=cf_data["filename"],
            path=cf_data["path"],
            content=cf_data["content"],
            user=request.user,
        )
        config_files_imported += 1

    # Import projects
    projects_imported = 0
    projects_updated = 0
    projects_skipped = 0
    for proj_data in scan_projects():
        existing = Project.objects.filter(user=request.user, path=proj_data["path"]).first()
        if existing:
            # Update detection flags if they changed
            changed = False
            if proj_data["has_coderoo"] and not existing.has_coderoo:
                existing.has_coderoo = True
                changed = True
            if proj_data["has_claude_config"] and not existing.has_claude_config:
                existing.has_claude_config = True
                changed = True
            if changed:
                existing.save()
                projects_updated += 1
            else:
                projects_skipped += 1
            continue
        Project.objects.create(
            name=proj_data["name"],
            path=proj_data["path"],
            has_coderoo=proj_data["has_coderoo"],
            has_claude_config=proj_data["has_claude_config"],
            user=request.user,
        )
        projects_imported += 1

    return Response(
        {
            "status": "ok",
            "imported": imported,
            "skipped": skipped,
            "instructions_imported": instructions_imported,
            "instructions_skipped": instructions_skipped,
            "config_files_imported": config_files_imported,
            "config_files_skipped": config_files_skipped,
            "projects_imported": projects_imported,
            "projects_updated": projects_updated,
            "projects_skipped": projects_skipped,
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

    config_file_results = []
    for cf in ConfigFile.objects.filter(user=request.user):
        try:
            path = write_config_file(cf)
            config_file_results.append({"name": cf.filename, "path": str(path), "status": "ok"})
        except Exception as e:
            config_file_results.append({"name": cf.filename, "status": "error", "detail": str(e)})

    return Response(
        {
            "results": results,
            "instruction_results": instruction_results,
            "config_file_results": config_file_results,
        }
    )


@api_view(["GET"])
@perm_classes([IsAuthenticated])
def apply_all_preview(request):
    """Preview what files would be written by apply-all, with change detection."""
    from pathlib import Path as _Path

    from .filesystem import (
        DEFAULT_CLAUDE_AGENTS_DIR,
        DEFAULT_CODEROO_AGENTS_DIR,
        DEFAULT_INSTRUCTIONS_DIR,
        render_agent,
    )

    def _read_disk(path: _Path) -> str | None:
        """Read file from disk, return None if it doesn't exist."""
        try:
            return path.read_text()
        except (FileNotFoundError, PermissionError):
            return None

    agents = Agent.objects.filter(user=request.user, is_active=True)
    agent_list = []
    for agent in agents:
        if agent.source == "claude":
            path = DEFAULT_CLAUDE_AGENTS_DIR / f"{agent.name}.md"
        elif agent.source == "coderoo":
            path = DEFAULT_CODEROO_AGENTS_DIR / agent.name / f"{agent.name}.md"
        else:
            path = _Path(f"unknown/{agent.name}.md")
        db_content = render_agent(agent)
        disk_content = _read_disk(path)
        has_changes = disk_content is None or disk_content != db_content
        agent_list.append(
            {
                "name": agent.name,
                "source": agent.source,
                "path": str(path),
                "has_changes": has_changes,
                "disk_content": disk_content,
                "db_content": db_content,
            }
        )

    instructions = Instruction.objects.filter(user=request.user)
    instruction_list = []
    for inst in instructions:
        path = DEFAULT_INSTRUCTIONS_DIR / f"{inst.name}.md"
        db_content = inst.content
        disk_content = _read_disk(path)
        has_changes = disk_content is None or disk_content != db_content
        instruction_list.append(
            {
                "name": inst.name,
                "path": str(path),
                "has_changes": has_changes,
                "disk_content": disk_content,
                "db_content": db_content,
            }
        )

    config_files = ConfigFile.objects.filter(user=request.user)
    config_file_list = []
    for cf in config_files:
        path = _Path(cf.path)
        db_content = cf.content
        disk_content = _read_disk(path)
        has_changes = disk_content is None or disk_content != db_content
        config_file_list.append(
            {
                "filename": cf.filename,
                "path": cf.path,
                "has_changes": has_changes,
                "disk_content": disk_content,
                "db_content": db_content,
            }
        )

    return Response(
        {
            "agents": agent_list,
            "instructions": instruction_list,
            "config_files": config_file_list,
        }
    )


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def simulate(request):
    """Simulate a session start and return the assembled context."""
    from .simulate import simulate_session

    agent_id = request.data.get("agent_id")
    project_path = request.data.get("project_path", "")

    if not agent_id:
        return Response({"detail": "agent_id is required."}, status=400)

    agent = Agent.objects.filter(pk=agent_id, user=request.user).first()
    if not agent:
        return Response({"detail": "Agent not found."}, status=404)

    result = simulate_session(agent, project_path)
    return Response(result)


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
        config=agent_data.get("config", ""),
        user=user,
    )
    if agent_data.get("content"):
        chunk = Chunk.objects.create(content=agent_data["content"], user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
    return agent
