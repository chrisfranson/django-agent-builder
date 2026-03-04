"""Models for agent_builder with OAuth2/user scoping support."""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet that overrides delete() to soft-delete."""

    def delete(self):
        """Soft delete all records in the queryset."""
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        """Actually delete records from the database."""
        return super().delete()

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """Default manager that excludes soft-deleted records."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """Unfiltered manager for admin and special queries."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """Abstract base for models with soft delete support."""

    is_deleted = models.BooleanField(default=False, help_text="Soft-deleted flag")
    deleted_at = models.DateTimeField(null=True, blank=True, help_text="When soft-deleted")

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


class Agent(SoftDeleteModel):
    """An AI agent configuration (Claude Code or Coderoo)."""

    SOURCE_CHOICES = [
        ("claude", "Claude Code"),
        ("coderoo", "Coderoo"),
    ]
    MODEL_CHOICES = [
        ("sonnet", "Sonnet"),
        ("opus", "Opus"),
        ("haiku", "Haiku"),
    ]

    name = models.SlugField(max_length=255, help_text="URL-safe agent identifier")
    display_name = models.CharField(max_length=255, help_text="Human-readable name")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, help_text="Agent platform")
    description = models.TextField(blank=True, help_text="Agent description")
    model = models.CharField(
        max_length=20, choices=MODEL_CHOICES, default="sonnet", help_text="AI model"
    )
    frontmatter = models.TextField(blank=True, help_text="Raw YAML frontmatter")
    config = models.TextField(
        blank=True, default="", help_text="Agent config (JSON5 for Coderoo agents)"
    )
    is_active = models.BooleanField(default=True, help_text="Whether this agent is active")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agents",
        help_text="Owner of this agent",
    )
    chunks = models.ManyToManyField("Chunk", through="AgentChunk", blank=True)
    instructions = models.ManyToManyField("Instruction", through="AgentInstruction", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file_mtime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last-seen filesystem modified time at import/apply",
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this item was last imported or applied",
    )

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["user", "source"]),
            models.Index(fields=["user", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(is_deleted=False),
                name="unique_active_agent_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.source})"


class Chunk(models.Model):
    """A composable content block for agent instructions."""

    title = models.CharField(
        max_length=255, blank=True, help_text="Optional title (unnamed chunks hidden from library)"
    )
    content = models.TextField(help_text="Markdown content")
    in_library = models.BooleanField(
        default=False, help_text="Whether this chunk appears in the library"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chunks",
        help_text="Owner of this chunk",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title if self.title else f"Chunk #{self.pk}"


class ChunkVariant(models.Model):
    """A variant of a chunk (stub for Phase 3)."""

    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="variants")
    label = models.CharField(max_length=100, help_text="Variant label (e.g., gentle, firm)")
    content = models.TextField(help_text="Variant content")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]

    def __str__(self) -> str:
        return f"{self.chunk} / {self.label}"


class AgentChunk(models.Model):
    """Through table linking agents to their ordered chunks."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="agent_chunks")
    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="agent_chunks")
    position = models.PositiveIntegerField(help_text="Order position within the agent")
    is_enabled = models.BooleanField(default=True, help_text="Whether this chunk is active")
    active_variant = models.ForeignKey(
        ChunkVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Selected variant (Phase 3, nullable for now)",
    )

    class Meta:
        ordering = ["position"]
        unique_together = [["agent", "chunk"]]

    def clean(self) -> None:
        if self.agent_id and self.chunk_id and self.agent.user_id != self.chunk.user_id:
            raise ValidationError("Agent and chunk must belong to the same user.")
        if self.active_variant_id and self.chunk_id:
            if self.active_variant.chunk_id != self.chunk_id:
                raise ValidationError("Active variant must belong to the same chunk.")

    def __str__(self) -> str:
        return f"{self.agent.name} / {self.chunk} @ {self.position}"


class Instruction(SoftDeleteModel):
    """A reusable instruction block that can be attached to agents."""

    INJECTION_MODE_CHOICES = [
        ("on_demand", "On Demand"),
        ("auto_inject", "Auto Inject"),
    ]

    name = models.SlugField(max_length=255, help_text="URL-safe instruction identifier")
    display_name = models.CharField(max_length=255, help_text="Human-readable name")
    content = models.TextField(help_text="Instruction content (Markdown)")
    injection_mode = models.CharField(
        max_length=20,
        choices=INJECTION_MODE_CHOICES,
        default="on_demand",
        help_text="Default injection mode for this instruction",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructions",
        help_text="Owner of this instruction",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file_mtime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last-seen filesystem modified time at import/apply",
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this item was last imported or applied",
    )

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["user", "name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                condition=models.Q(is_deleted=False),
                name="unique_active_instruction_per_user",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AgentInstruction(models.Model):
    """Through table linking agents to their instructions."""

    INJECTION_MODE_CHOICES = [
        ("", "Use Default"),
        ("on_demand", "On Demand"),
        ("auto_inject", "Auto Inject"),
    ]

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="agent_instructions")
    instruction = models.ForeignKey(
        Instruction, on_delete=models.CASCADE, related_name="agent_instructions"
    )
    injection_mode = models.CharField(
        max_length=20,
        choices=INJECTION_MODE_CHOICES,
        blank=True,
        default="",
        help_text="Override injection mode (blank = use instruction default)",
    )

    class Meta:
        ordering = ["instruction__name"]
        unique_together = [["agent", "instruction"]]

    def get_effective_mode(self) -> str:
        return self.injection_mode if self.injection_mode else self.instruction.injection_mode

    def clean(self) -> None:
        if self.agent_id and self.instruction_id and self.agent.user_id != self.instruction.user_id:
            raise ValidationError("Agent and instruction must belong to the same user.")

    def __str__(self) -> str:
        mode = self.get_effective_mode()
        return f"{self.agent.name} / {self.instruction.name} ({mode})"


class Profile(models.Model):
    """A full system state snapshot for experimentation and rollback."""

    name = models.SlugField(max_length=255, help_text="Profile identifier")
    description = models.TextField(blank=True, help_text="Profile description")
    snapshot = models.JSONField(help_text="Full system state snapshot")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profiles",
        help_text="Owner of this profile",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [["user", "name"]]
        indexes = [models.Index(fields=["user", "name"])]

    def __str__(self) -> str:
        return self.name


class ConfigFile(SoftDeleteModel):
    """A project-level config file tracked from the filesystem (CLAUDE.md, AGENTS.md)."""

    filename = models.CharField(max_length=255, help_text="Filename (e.g., CLAUDE.md)")
    path = models.CharField(max_length=1024, help_text="Absolute filesystem path")
    content = models.TextField(blank=True, help_text="File content")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="config_files",
        help_text="Owner of this config file",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file_mtime = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last-seen filesystem modified time at import/apply",
    )
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this item was last imported or applied",
    )

    class Meta:
        ordering = ["path"]
        indexes = [models.Index(fields=["user", "path"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "path"],
                condition=models.Q(is_deleted=False),
                name="unique_active_configfile_per_user",
            ),
        ]

    def __str__(self) -> str:
        return self.path

    @property
    def scope(self) -> str:
        """Directory this config file affects."""
        from pathlib import Path

        return str(Path(self.path).parent)


class Project(SoftDeleteModel):
    """A detected project directory (has .coderoo/ and/or Claude Code config)."""

    name = models.CharField(max_length=255, help_text="Project name (derived from directory)")
    path = models.CharField(max_length=1024, help_text="Absolute filesystem path")
    has_coderoo = models.BooleanField(default=False, help_text="Has .coderoo/ directory")
    has_claude_config = models.BooleanField(
        default=False, help_text="Has entry in ~/.claude/projects/"
    )
    discovered_at = models.DateTimeField(auto_now_add=True, help_text="When first discovered")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
        help_text="Owner of this project",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["user", "path"]),
            models.Index(fields=["user", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "path"],
                condition=models.Q(is_deleted=False),
                name="unique_active_project_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.path})"


class UserOptions(models.Model):
    """Per-user UI preferences persisted across sessions."""

    TAB_CHOICES = [
        ("agents", "Agents"),
        ("projects", "Projects"),
        ("memory", "Memory"),
    ]
    AGENT_SUB_TAB_CHOICES = [
        ("coderoo", "Coderoo"),
        ("claude", "Claude"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_builder_options",
    )
    active_tab = models.CharField(
        max_length=20,
        choices=TAB_CHOICES,
        default="agents",
        help_text="Last selected top-level sidebar tab",
    )
    agent_sub_tab = models.CharField(
        max_length=20,
        choices=AGENT_SUB_TAB_CHOICES,
        default="coderoo",
        help_text="Last selected agent sub-tab",
    )
    last_simulate_path = models.CharField(
        max_length=1024,
        blank=True,
        default="",
        help_text="Last used project path in simulate modal",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "user options"

    def __str__(self):
        return f"Options for {self.user}"


class Revision(models.Model):
    """A content snapshot for revision tracking (generic across models)."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    content_snapshot = models.JSONField(help_text="Snapshot of content fields at this revision")
    message = models.CharField(max_length=255, blank=True, help_text="Optional revision message")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="revisions",
        help_text="User who created this revision",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"Revision for {self.content_type} #{self.object_id} at {self.created_at}"
