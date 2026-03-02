"""Models for agent_builder with OAuth2/user scoping support."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Agent(models.Model):
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
    is_active = models.BooleanField(default=True, help_text="Whether this agent is active")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agents",
        help_text="Owner of this agent",
    )
    chunks = models.ManyToManyField("Chunk", through="AgentChunk", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = [["user", "name"]]
        indexes = [
            models.Index(fields=["user", "source"]),
            models.Index(fields=["user", "name"]),
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

    def __str__(self) -> str:
        return f"{self.agent.name} / {self.chunk} @ {self.position}"
