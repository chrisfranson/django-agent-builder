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
