"""Revision tracking utilities for content snapshots."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.contenttypes.models import ContentType

from .models import Chunk, Instruction, Revision

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser
    from django.db import models as dm


# Fields to snapshot per model
SNAPSHOT_FIELDS: dict[type, list[str]] = {
    Chunk: ["title", "content", "in_library"],
    Instruction: ["name", "display_name", "content", "injection_mode"],
}


def get_snapshot(instance: dm.Model) -> dict:
    """Get a snapshot dict of tracked fields for the given instance."""
    fields = SNAPSHOT_FIELDS.get(type(instance), [])
    return {f: getattr(instance, f) for f in fields}


def create_revision(
    instance: dm.Model,
    user: AbstractUser,
    message: str = "",
) -> Revision | None:
    """Create a revision if the instance's content has changed since the last snapshot.

    Returns the new Revision, or None if nothing changed.
    """
    ct = ContentType.objects.get_for_model(instance)
    snapshot = get_snapshot(instance)

    # Check if content actually changed since last revision
    last = Revision.objects.filter(content_type=ct, object_id=instance.pk).first()
    if last and last.content_snapshot == snapshot:
        return None

    return Revision.objects.create(
        content_type=ct,
        object_id=instance.pk,
        content_snapshot=snapshot,
        message=message,
        user=user,
    )
