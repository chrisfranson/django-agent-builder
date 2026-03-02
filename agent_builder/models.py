"""
Models for agent_builder with OAuth2/user scoping support.

All models include a user foreign key for multi-tenant data isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models

if TYPE_CHECKING:
    from django.contrib.auth.models import User  # noqa: F401


class ExampleModel(models.Model):
    """
    Example model with user scoping.

    Customize this model for your app's needs.
    """

    user: models.ForeignKey = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_builder_examples",
        help_text="Owner of this record",
    )
    name: models.CharField = models.CharField(max_length=255)
    description: models.TextField = models.TextField(blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.user.username})"
