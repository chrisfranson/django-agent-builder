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
    UserOptions,
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
    UserOptionsSerializer,
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

    def perform_destroy(self, instance):
        instance.soft_delete()

    @action(detail=True, methods=["post"])
    def apply(self, request, pk=None):
        """Write this agent to disk."""
        agent = self.get_object()
        try:
            path, mtime = write_agent(agent)
            from django.utils import timezone as tz

            Agent.objects.filter(pk=agent.pk).update(
                file_mtime=mtime,
                last_synced_at=tz.now(),
            )
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

    def perform_destroy(self, instance):
        instance.soft_delete()

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

    def perform_destroy(self, instance):
        instance.soft_delete()

    @action(detail=False, methods=["post"], url_path="delete-file")
    def delete_file(self, request):
        """Delete a config file from the filesystem."""
        from pathlib import Path as _Path

        path = request.data.get("path")
        if not path:
            return Response({"detail": "path required"}, status=400)

        allowed_paths = set(
            ConfigFile.all_objects.filter(user=request.user).values_list("path", flat=True)
        )
        target = _Path(path).resolve()
        if str(target) not in allowed_paths:
            return Response({"detail": "Not authorized to delete this file"}, status=403)

        if target.exists() and target.is_file():
            target.unlink()
            return Response({"status": "ok", "deleted": str(target)})
        return Response({"status": "ok", "detail": "File not found on disk"})


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

    def perform_destroy(self, instance):
        instance.soft_delete()

    @action(detail=True, methods=["get"])
    def files(self, request, pk=None):
        """Read config and memory files from a project directory."""
        from pathlib import Path as _Path

        project = self.get_object()
        project_dir = _Path(project.path)

        if not project_dir.is_dir():
            return Response({"detail": "Project directory not found"}, status=404)

        files = []
        resolved_project_dir = project_dir.resolve()

        coderoo_config = project_dir / ".coderoo" / "coderoo.config.json5"
        if coderoo_config.is_file():
            try:
                resolved = coderoo_config.resolve()
                # Skip symlinks that escape the project directory
                if str(resolved).startswith(str(resolved_project_dir) + "/"):
                    files.append(
                        {
                            "filename": "coderoo.config.json5",
                            "path": str(resolved),
                            "content": coderoo_config.read_text(),
                            "type": "coderoo_config",
                        }
                    )
            except Exception:
                pass

        for name in ("CLAUDE.md", "AGENTS.md"):
            filepath = project_dir / name
            if filepath.is_file():
                try:
                    resolved = filepath.resolve()
                    # Skip symlinks that escape the project directory
                    if not str(resolved).startswith(str(resolved_project_dir) + "/"):
                        continue
                    cf = ConfigFile.objects.filter(user=request.user, path=str(resolved)).first()
                    files.append(
                        {
                            "filename": name,
                            "path": str(resolved),
                            "content": filepath.read_text(),
                            "type": "memory_file",
                            "config_file_id": cf.id if cf else None,
                        }
                    )
                except Exception:
                    pass

        return Response({"project_id": project.id, "files": files})


@api_view(["GET", "PATCH"])
@perm_classes([IsAuthenticated])
def user_options(request):
    """GET or PATCH the authenticated user's UI preferences."""
    opts, _ = UserOptions.objects.get_or_create(user=request.user)
    if request.method == "PATCH":
        serializer = UserOptionsSerializer(opts, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
    return Response(UserOptionsSerializer(opts).data)


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def init_project_with_claude(request, pk):
    """Queue a Celery task to initialize a project with Claude Code /new-project."""
    project = get_object_or_404(Project, pk=pk, user=request.user)
    from .tasks import create_project_with_claude

    create_project_with_claude.delay(project.pk, project.path)
    return Response({"status": "queued"})


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
    from django.utils import timezone as tz

    from .filesystem import render_agent
    from .sync import SyncStatus, detect_import_status

    now = tz.now()
    resolutions = request.data.get("resolutions", {})
    imported = 0
    skipped = 0
    updated = 0
    conflicts = []
    disk_agent_names = set()

    for agent_data in read_claude_agents() + read_coderoo_agents():
        disk_agent_names.add(agent_data["name"])
        existing = Agent.objects.filter(user=request.user, name=agent_data["name"]).first()

        if existing is None:
            # New agent -- import it
            agent = _import_agent(request.user, agent_data)
            Agent.objects.filter(pk=agent.pk).update(
                file_mtime=agent_data.get("mtime"),
                last_synced_at=now,
            )
            imported += 1
            continue

        status = detect_import_status(
            disk_mtime=agent_data.get("mtime"),
            stored_file_mtime=existing.file_mtime,
            db_updated_at=existing.updated_at,
            last_synced_at=existing.last_synced_at,
        )

        if status == SyncStatus.UNCHANGED:
            skipped += 1
        elif status == SyncStatus.DISK_ONLY:
            _update_agent_from_disk(existing, agent_data, now)
            updated += 1
        elif status == SyncStatus.NEW_ON_DISK:
            # Never synced -- update from disk
            _update_agent_from_disk(existing, agent_data, now)
            updated += 1
        elif status == SyncStatus.CONFLICT:
            conflict_key = f"agent:{agent_data['name']}"
            resolution = resolutions.get(conflict_key)
            if resolution == "disk":
                _update_agent_from_disk(existing, agent_data, now)
                updated += 1
            elif resolution == "db":
                # Keep DB version but update sync tracking so conflict clears
                Agent.objects.filter(pk=existing.pk).update(
                    file_mtime=agent_data.get("mtime"),
                    last_synced_at=now,
                )
                skipped += 1
            else:
                # No resolution provided - return conflict with diff data
                db_content = render_agent(existing)
                disk_content = _render_disk_agent_content(agent_data)
                conflicts.append(
                    {
                        "type": "agent",
                        "name": agent_data["name"],
                        "source": agent_data["source"],
                        "conflict_type": "both_modified",
                        "disk_content": disk_content,
                        "db_content": db_content,
                    }
                )
        else:
            skipped += 1

    # Instructions
    instructions_imported = 0
    instructions_skipped = 0
    instructions_updated = 0
    instruction_conflicts = []
    disk_instruction_names = set()

    for instr_data in read_instructions():
        disk_instruction_names.add(instr_data["name"])
        existing = Instruction.objects.filter(user=request.user, name=instr_data["name"]).first()

        if existing is None:
            inst = Instruction.objects.create(
                name=instr_data["name"],
                display_name=instr_data["name"].replace("-", " ").title(),
                content=instr_data["content"],
                user=request.user,
            )
            Instruction.objects.filter(pk=inst.pk).update(
                file_mtime=instr_data.get("mtime"),
                last_synced_at=now,
            )
            instructions_imported += 1
            continue

        status = detect_import_status(
            disk_mtime=instr_data.get("mtime"),
            stored_file_mtime=existing.file_mtime,
            db_updated_at=existing.updated_at,
            last_synced_at=existing.last_synced_at,
        )

        if status == SyncStatus.UNCHANGED:
            instructions_skipped += 1
        elif status in (SyncStatus.DISK_ONLY, SyncStatus.NEW_ON_DISK):
            existing.content = instr_data["content"]
            existing.save()
            Instruction.objects.filter(pk=existing.pk).update(
                file_mtime=instr_data.get("mtime"),
                last_synced_at=now,
            )
            instructions_updated += 1
        elif status == SyncStatus.CONFLICT:
            conflict_key = f"instruction:{instr_data['name']}"
            resolution = resolutions.get(conflict_key)
            if resolution == "disk":
                existing.content = instr_data["content"]
                existing.save()
                Instruction.objects.filter(pk=existing.pk).update(
                    file_mtime=instr_data.get("mtime"),
                    last_synced_at=now,
                )
                instructions_updated += 1
            elif resolution == "db":
                Instruction.objects.filter(pk=existing.pk).update(
                    file_mtime=instr_data.get("mtime"),
                    last_synced_at=now,
                )
                instructions_skipped += 1
            else:
                instruction_conflicts.append(
                    {
                        "type": "instruction",
                        "name": instr_data["name"],
                        "conflict_type": "both_modified",
                        "disk_content": instr_data["content"],
                        "db_content": existing.content,
                    }
                )
        else:
            instructions_skipped += 1

    # Config files -- resolve any symlinked paths in existing records
    from pathlib import Path as _ImportPath

    for cf in ConfigFile.objects.filter(user=request.user):
        resolved = str(_ImportPath(cf.path).resolve())
        if resolved != cf.path:
            if not ConfigFile.objects.filter(user=request.user, path=resolved).exists():
                cf.path = resolved
                cf.save(update_fields=["path"])
            else:
                ConfigFile.all_objects.filter(pk=cf.pk).hard_delete()

    for proj in Project.objects.filter(user=request.user):
        resolved = str(_ImportPath(proj.path).resolve())
        if resolved != proj.path:
            if not Project.objects.filter(user=request.user, path=resolved).exists():
                proj.path = resolved
                proj.save(update_fields=["path"])
            else:
                Project.all_objects.filter(pk=proj.pk).hard_delete()

    config_files_imported = 0
    config_files_skipped = 0
    config_files_updated = 0
    config_file_conflicts = []
    disk_config_paths = set()

    for cf_data in read_config_files():
        disk_config_paths.add(cf_data["path"])
        existing = ConfigFile.objects.filter(user=request.user, path=cf_data["path"]).first()

        if existing is None:
            cf = ConfigFile.objects.create(
                filename=cf_data["filename"],
                path=cf_data["path"],
                content=cf_data["content"],
                user=request.user,
            )
            ConfigFile.objects.filter(pk=cf.pk).update(
                file_mtime=cf_data.get("mtime"),
                last_synced_at=now,
            )
            config_files_imported += 1
            continue

        status = detect_import_status(
            disk_mtime=cf_data.get("mtime"),
            stored_file_mtime=existing.file_mtime,
            db_updated_at=existing.updated_at,
            last_synced_at=existing.last_synced_at,
        )

        if status == SyncStatus.UNCHANGED:
            config_files_skipped += 1
        elif status in (SyncStatus.DISK_ONLY, SyncStatus.NEW_ON_DISK):
            existing.content = cf_data["content"]
            existing.save()
            ConfigFile.objects.filter(pk=existing.pk).update(
                file_mtime=cf_data.get("mtime"),
                last_synced_at=now,
            )
            config_files_updated += 1
        elif status == SyncStatus.CONFLICT:
            conflict_key = f"config_file:{cf_data['path']}"
            resolution = resolutions.get(conflict_key)
            if resolution == "disk":
                existing.content = cf_data["content"]
                existing.save()
                ConfigFile.objects.filter(pk=existing.pk).update(
                    file_mtime=cf_data.get("mtime"),
                    last_synced_at=now,
                )
                config_files_updated += 1
            elif resolution == "db":
                ConfigFile.objects.filter(pk=existing.pk).update(
                    file_mtime=cf_data.get("mtime"),
                    last_synced_at=now,
                )
                config_files_skipped += 1
            else:
                config_file_conflicts.append(
                    {
                        "type": "config_file",
                        "name": cf_data["filename"],
                        "path": cf_data["path"],
                        "conflict_type": "both_modified",
                        "disk_content": cf_data["content"],
                        "db_content": existing.content,
                    }
                )
        else:
            config_files_skipped += 1

    # Import projects (unchanged -- no mtime tracking for projects)
    projects_imported = 0
    projects_updated = 0
    projects_skipped = 0
    for proj_data in scan_projects():
        existing = Project.objects.filter(user=request.user, path=proj_data["path"]).first()
        if existing:
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

    all_conflicts = conflicts + instruction_conflicts + config_file_conflicts

    # Detect DB records whose files are missing from disk
    disk_deletions = []
    disk_deleted_count = 0

    for agent in Agent.objects.filter(user=request.user):
        if agent.name not in disk_agent_names and agent.last_synced_at is not None:
            resolution = resolutions.get(f"agent:{agent.name}")
            if resolution == "soft_delete":
                agent.soft_delete()
                disk_deleted_count += 1
            else:
                disk_deletions.append(
                    {
                        "type": "agent",
                        "name": agent.name,
                        "source": agent.source,
                        "status": "deleted_on_disk",
                    }
                )

    for inst in Instruction.objects.filter(user=request.user):
        if inst.name not in disk_instruction_names and inst.last_synced_at is not None:
            resolution = resolutions.get(f"instruction:{inst.name}")
            if resolution == "soft_delete":
                inst.soft_delete()
                disk_deleted_count += 1
            else:
                disk_deletions.append(
                    {
                        "type": "instruction",
                        "name": inst.name,
                        "status": "deleted_on_disk",
                    }
                )

    for cf in ConfigFile.objects.filter(user=request.user):
        if cf.path not in disk_config_paths and cf.last_synced_at is not None:
            resolution = resolutions.get(f"config_file:{cf.path}")
            if resolution == "soft_delete":
                cf.soft_delete()
                disk_deleted_count += 1
            else:
                disk_deletions.append(
                    {
                        "type": "config_file",
                        "name": cf.filename,
                        "path": cf.path,
                        "status": "deleted_on_disk",
                    }
                )

    return Response(
        {
            "status": "ok",
            "imported": imported,
            "skipped": skipped,
            "updated": updated,
            "instructions_imported": instructions_imported,
            "instructions_skipped": instructions_skipped,
            "instructions_updated": instructions_updated,
            "config_files_imported": config_files_imported,
            "config_files_skipped": config_files_skipped,
            "config_files_updated": config_files_updated,
            "conflicts": all_conflicts,
            "projects_imported": projects_imported,
            "projects_updated": projects_updated,
            "projects_skipped": projects_skipped,
            "disk_deletions": disk_deletions,
            "disk_deleted": disk_deleted_count,
        }
    )


@api_view(["POST"])
@perm_classes([IsAuthenticated])
def apply_all(request):
    """Write all active agents and instructions to disk."""
    from pathlib import Path as _Path

    from django.utils import timezone as tz

    from .filesystem import (
        DEFAULT_CLAUDE_AGENTS_DIR,
        DEFAULT_CODEROO_AGENTS_DIR,
        DEFAULT_INSTRUCTIONS_DIR,
        _get_file_mtime,
    )
    from .sync import SyncStatus, detect_apply_status

    now = tz.now()
    force_paths = set(request.data.get("force_paths", []))
    raw_selected = request.data.get("selected_paths", None)
    selected_paths = set(raw_selected) if raw_selected is not None else None

    # Handle delete-from-db requests
    delete_from_db = request.data.get("delete_from_db", [])
    deleted_from_db_count = 0
    for item in delete_from_db:
        item_type = item.get("type")
        try:
            if item_type == "agent":
                agent = Agent.objects.filter(user=request.user, name=item["name"]).first()
                if agent:
                    agent.soft_delete()
                    deleted_from_db_count += 1
            elif item_type == "instruction":
                inst = Instruction.objects.filter(user=request.user, name=item["name"]).first()
                if inst:
                    inst.soft_delete()
                    deleted_from_db_count += 1
            elif item_type == "config_file":
                cf = ConfigFile.objects.filter(user=request.user, path=item["path"]).first()
                if cf:
                    cf.soft_delete()
                    deleted_from_db_count += 1
        except Exception:
            pass  # Skip items that fail to delete

    agents = Agent.objects.filter(user=request.user, is_active=True)
    results = []
    for agent in agents:
        if agent.source == "claude":
            disk_path = DEFAULT_CLAUDE_AGENTS_DIR / f"{agent.name}.md"
        elif agent.source == "coderoo":
            disk_path = DEFAULT_CODEROO_AGENTS_DIR / agent.name / f"{agent.name}.md"
        else:
            disk_path = None

        # Skip items not in the user's selection (if selection provided)
        if selected_paths is not None and disk_path and str(disk_path) not in selected_paths:
            continue

        disk_mtime = _get_file_mtime(disk_path) if disk_path else None
        force_this = str(disk_path) in force_paths if disk_path else False

        if not force_this:
            # Detect deleted files: disk file missing but was previously synced
            if (
                disk_path
                and disk_mtime is None
                and (agent.last_synced_at is not None or agent.file_mtime is not None)
            ):
                results.append({"name": agent.name, "status": "deleted_on_disk"})
                continue

            status = detect_apply_status(
                disk_mtime=disk_mtime,
                stored_file_mtime=agent.file_mtime,
                db_updated_at=agent.updated_at,
                last_synced_at=agent.last_synced_at,
            )

            if status == SyncStatus.UNCHANGED:
                results.append({"name": agent.name, "status": "unchanged"})
                continue
            elif status == SyncStatus.CONFLICT:
                results.append(
                    {"name": agent.name, "status": "conflict", "conflict_type": "both_modified"}
                )
                continue

        try:
            path, mtime = write_agent(agent)
            Agent.objects.filter(pk=agent.pk).update(
                file_mtime=mtime,
                last_synced_at=now,
            )
            results.append({"name": agent.name, "status": "ok", "path": str(path)})
        except Exception as e:
            results.append({"name": agent.name, "status": "error", "detail": str(e)})

    instruction_results = []
    for instruction in Instruction.objects.filter(user=request.user):
        disk_path = DEFAULT_INSTRUCTIONS_DIR / f"{instruction.name}.md"

        if selected_paths is not None and str(disk_path) not in selected_paths:
            continue

        disk_mtime = _get_file_mtime(disk_path)
        force_this = str(disk_path) in force_paths

        if not force_this:
            # Detect deleted files: disk file missing but was previously synced
            if disk_mtime is None and (
                instruction.last_synced_at is not None or instruction.file_mtime is not None
            ):
                instruction_results.append({"name": instruction.name, "status": "deleted_on_disk"})
                continue

            status = detect_apply_status(
                disk_mtime=disk_mtime,
                stored_file_mtime=instruction.file_mtime,
                db_updated_at=instruction.updated_at,
                last_synced_at=instruction.last_synced_at,
            )

            if status == SyncStatus.UNCHANGED:
                instruction_results.append({"name": instruction.name, "status": "unchanged"})
                continue
            elif status == SyncStatus.CONFLICT:
                instruction_results.append(
                    {
                        "name": instruction.name,
                        "status": "conflict",
                        "conflict_type": "both_modified",
                    }
                )
                continue

        try:
            path, mtime = write_instruction(instruction)
            Instruction.objects.filter(pk=instruction.pk).update(
                file_mtime=mtime,
                last_synced_at=now,
            )
            instruction_results.append(
                {"name": instruction.name, "status": "ok", "path": str(path)}
            )
        except Exception as e:
            instruction_results.append(
                {"name": instruction.name, "status": "error", "detail": str(e)}
            )

    config_file_results = []
    for cf in ConfigFile.objects.filter(user=request.user):
        disk_path = _Path(cf.path)

        if selected_paths is not None and str(disk_path) not in selected_paths:
            continue

        disk_mtime = _get_file_mtime(disk_path)
        force_this = str(disk_path) in force_paths

        if not force_this:
            # Detect deleted files: disk file missing but was previously synced
            if disk_mtime is None and (cf.last_synced_at is not None or cf.file_mtime is not None):
                config_file_results.append(
                    {"name": cf.filename, "path": cf.path, "status": "deleted_on_disk"}
                )
                continue

            status = detect_apply_status(
                disk_mtime=disk_mtime,
                stored_file_mtime=cf.file_mtime,
                db_updated_at=cf.updated_at,
                last_synced_at=cf.last_synced_at,
            )

            if status == SyncStatus.UNCHANGED:
                config_file_results.append(
                    {"name": cf.filename, "path": cf.path, "status": "unchanged"}
                )
                continue
            elif status == SyncStatus.CONFLICT:
                config_file_results.append(
                    {
                        "name": cf.filename,
                        "path": cf.path,
                        "status": "conflict",
                        "conflict_type": "both_modified",
                    }
                )
                continue

        try:
            path, mtime = write_config_file(cf)
            ConfigFile.objects.filter(pk=cf.pk).update(
                file_mtime=mtime,
                last_synced_at=now,
            )
            config_file_results.append({"name": cf.filename, "path": str(path), "status": "ok"})
        except Exception as e:
            config_file_results.append({"name": cf.filename, "status": "error", "detail": str(e)})

    # Handle delete-from-disk requests (soft-deleted items whose files remain)
    delete_from_disk = request.data.get("delete_from_disk", [])
    deleted_from_disk_count = 0
    allowed_dirs = [
        str(DEFAULT_CLAUDE_AGENTS_DIR),
        str(DEFAULT_CODEROO_AGENTS_DIR),
        str(DEFAULT_INSTRUCTIONS_DIR),
    ]
    # Also allow paths of user's config files (active or soft-deleted)
    allowed_config_paths = set(
        ConfigFile.all_objects.filter(user=request.user).values_list("path", flat=True)
    )
    for item in delete_from_disk:
        try:
            target = _Path(item["path"]).resolve()
            target_str = str(target)
            # Validate path is within allowed directories or is a known config file path
            is_allowed = any(target_str.startswith(d) for d in allowed_dirs) or (
                target_str in allowed_config_paths
            )
            if is_allowed and target.exists() and target.is_file():
                target.unlink()
                deleted_from_disk_count += 1
        except Exception:
            pass  # Skip items that fail to delete

    return Response(
        {
            "results": results,
            "instruction_results": instruction_results,
            "config_file_results": config_file_results,
            "deleted_from_db": deleted_from_db_count,
            "deleted_from_disk": deleted_from_disk_count,
        }
    )


@api_view(["GET"])
@perm_classes([IsAuthenticated])
def apply_all_preview(request):
    """Preview what files would be written by apply-all, with change and conflict detection."""
    from pathlib import Path as _Path

    from .filesystem import (
        DEFAULT_CLAUDE_AGENTS_DIR,
        DEFAULT_CODEROO_AGENTS_DIR,
        DEFAULT_INSTRUCTIONS_DIR,
        _get_file_mtime,
        normalize_trailing_newline,
        render_agent,
    )
    from .sync import SyncStatus, detect_apply_status

    def _norm(text: str | None) -> str | None:
        return normalize_trailing_newline(text) if text else text

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
        disk_mtime = _get_file_mtime(path)
        deleted_on_disk = disk_content is None and (
            agent.last_synced_at is not None or agent.file_mtime is not None
        )
        has_changes = (not deleted_on_disk) and (
            disk_content is None or _norm(disk_content) != _norm(db_content)
        )

        status = detect_apply_status(
            disk_mtime=disk_mtime,
            stored_file_mtime=agent.file_mtime,
            db_updated_at=agent.updated_at,
            last_synced_at=agent.last_synced_at,
        )
        has_conflict = status == SyncStatus.CONFLICT

        item = {
            "name": agent.name,
            "source": agent.source,
            "path": str(path),
            "has_changes": has_changes,
            "has_conflict": has_conflict,
            "sync_status": status.value,
            "disk_content": disk_content,
            "db_content": db_content,
        }
        if deleted_on_disk:
            item["deleted_on_disk"] = True
        agent_list.append(item)

    instructions = Instruction.objects.filter(user=request.user)
    instruction_list = []
    for inst in instructions:
        path = DEFAULT_INSTRUCTIONS_DIR / f"{inst.name}.md"
        db_content = inst.content
        disk_content = _read_disk(path)
        disk_mtime = _get_file_mtime(path)
        deleted_on_disk = disk_content is None and (
            inst.last_synced_at is not None or inst.file_mtime is not None
        )
        has_changes = (not deleted_on_disk) and (
            disk_content is None or _norm(disk_content) != _norm(db_content)
        )

        status = detect_apply_status(
            disk_mtime=disk_mtime,
            stored_file_mtime=inst.file_mtime,
            db_updated_at=inst.updated_at,
            last_synced_at=inst.last_synced_at,
        )
        has_conflict = status == SyncStatus.CONFLICT

        item = {
            "name": inst.name,
            "path": str(path),
            "has_changes": has_changes,
            "has_conflict": has_conflict,
            "sync_status": status.value,
            "disk_content": disk_content,
            "db_content": db_content,
        }
        if deleted_on_disk:
            item["deleted_on_disk"] = True
        instruction_list.append(item)

    config_files = ConfigFile.objects.filter(user=request.user)
    config_file_list = []
    for cf in config_files:
        path = _Path(cf.path)
        db_content = cf.content
        disk_content = _read_disk(path)
        disk_mtime = _get_file_mtime(path)
        deleted_on_disk = disk_content is None and (
            cf.last_synced_at is not None or cf.file_mtime is not None
        )
        has_changes = (not deleted_on_disk) and (
            disk_content is None or _norm(disk_content) != _norm(db_content)
        )

        status = detect_apply_status(
            disk_mtime=disk_mtime,
            stored_file_mtime=cf.file_mtime,
            db_updated_at=cf.updated_at,
            last_synced_at=cf.last_synced_at,
        )
        has_conflict = status == SyncStatus.CONFLICT

        item = {
            "filename": cf.filename,
            "path": cf.path,
            "has_changes": has_changes,
            "has_conflict": has_conflict,
            "sync_status": status.value,
            "disk_content": disk_content,
            "db_content": db_content,
        }
        if deleted_on_disk:
            item["deleted_on_disk"] = True
        config_file_list.append(item)

    # Soft-deleted agents that still have files on disk
    deleted_agents = Agent.all_objects.filter(user=request.user, is_deleted=True)
    for agent in deleted_agents:
        if agent.source == "claude":
            path = DEFAULT_CLAUDE_AGENTS_DIR / f"{agent.name}.md"
        elif agent.source == "coderoo":
            path = DEFAULT_CODEROO_AGENTS_DIR / agent.name / f"{agent.name}.md"
        else:
            continue
        if path.exists():
            agent_list.append(
                {
                    "name": agent.name,
                    "source": agent.source,
                    "path": str(path),
                    "label": agent.display_name or agent.name,
                    "deleted_in_db": True,
                    "has_changes": False,
                    "has_conflict": False,
                }
            )

    # Soft-deleted instructions that still have files on disk
    deleted_instructions = Instruction.all_objects.filter(user=request.user, is_deleted=True)
    for inst in deleted_instructions:
        path = DEFAULT_INSTRUCTIONS_DIR / f"{inst.name}.md"
        if path.exists():
            instruction_list.append(
                {
                    "name": inst.name,
                    "path": str(path),
                    "label": inst.display_name or inst.name,
                    "deleted_in_db": True,
                    "has_changes": False,
                    "has_conflict": False,
                }
            )

    # Soft-deleted config files that still exist on disk
    deleted_config_files = ConfigFile.all_objects.filter(user=request.user, is_deleted=True)
    for cf in deleted_config_files:
        path = _Path(cf.path)
        if path.exists():
            config_file_list.append(
                {
                    "filename": cf.filename,
                    "path": cf.path,
                    "label": cf.filename,
                    "deleted_in_db": True,
                    "has_changes": False,
                    "has_conflict": False,
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
    from .simulate import SimulateSessionError, simulate_session

    agent_id = request.data.get("agent_id")
    project_path = request.data.get("project_path", "")
    role = request.data.get("role", "")
    context = request.data.get("context", "")
    task = request.data.get("task", "")
    runtime = request.data.get("runtime", "")

    if not agent_id:
        return Response({"detail": "agent_id is required."}, status=400)

    agent = Agent.objects.filter(pk=agent_id, user=request.user).first()
    if not agent:
        return Response({"detail": "Agent not found."}, status=404)

    try:
        result = simulate_session(
            agent,
            project_path,
            role=role,
            context=context,
            task=task,
            runtime=runtime,
        )
    except SimulateSessionError as exc:
        return Response({"detail": str(exc)}, status=502)

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


def _update_agent_from_disk(agent: Agent, agent_data: dict, sync_time) -> None:
    """Update an existing agent with data from disk."""
    fm_dict = _parse_frontmatter_dict(agent_data["frontmatter"])
    agent.display_name = fm_dict.get("name", agent_data["name"]).replace("-", " ").title()
    agent.description = fm_dict.get("description", "")
    agent.model = fm_dict.get("model", "sonnet")
    agent.frontmatter = agent_data["frontmatter"]
    agent.config = agent_data.get("config", "")
    agent.save()

    # Update the main chunk content
    main_chunk = AgentChunk.objects.filter(agent=agent, position=0).select_related("chunk").first()
    if main_chunk and agent_data.get("content"):
        main_chunk.chunk.content = agent_data["content"]
        main_chunk.chunk.save()
    elif agent_data.get("content") and not main_chunk:
        chunk = Chunk.objects.create(content=agent_data["content"], user=agent.user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

    # Update sync tracking (use update() to avoid touching auto_now)
    Agent.objects.filter(pk=agent.pk).update(
        file_mtime=agent_data.get("mtime"),
        last_synced_at=sync_time,
    )


def _render_disk_agent_content(agent_data: dict) -> str:
    """Render agent content from disk data in the same format as render_agent."""
    body = agent_data.get("content", "")
    frontmatter = agent_data.get("frontmatter", "")
    if frontmatter:
        if body:
            return f"---\n{frontmatter}\n---\n\n{body}"
        return f"---\n{frontmatter}\n---"
    return body


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
