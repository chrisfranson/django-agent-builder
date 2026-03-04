"""Sync conflict detection for import and apply operations."""

from __future__ import annotations

from datetime import datetime
from enum import Enum


class SyncStatus(str, Enum):
    """Result of comparing DB vs disk state for an item."""

    UNCHANGED = "unchanged"  # Neither side changed
    DISK_ONLY = "disk_only"  # Only disk changed -> safe to import
    DB_ONLY = "db_only"  # Only DB changed -> safe to apply
    CONFLICT = "conflict"  # Both changed -> needs resolution
    NEW_ON_DISK = "new_on_disk"  # Item doesn't exist in DB
    NEW_IN_DB = "new_in_db"  # Item doesn't exist on disk
    DELETED_ON_DISK = "deleted_on_disk"  # File was synced but now missing from disk


def detect_import_status(
    disk_mtime: datetime | None,
    stored_file_mtime: datetime | None,
    db_updated_at: datetime | None,
    last_synced_at: datetime | None,
) -> SyncStatus:
    """Determine sync status for an import (disk -> DB) operation.

    Args:
        disk_mtime: Current file modified time on disk.
        stored_file_mtime: The file_mtime stored in DB from last sync.
        db_updated_at: The model's updated_at timestamp.
        last_synced_at: When the last sync happened.
    """
    if stored_file_mtime is None:
        # Never synced before -- treat as new
        return SyncStatus.NEW_ON_DISK

    if disk_mtime is None:
        # File deleted from disk
        return SyncStatus.DELETED_ON_DISK

    # Use a small tolerance (1 second) for mtime comparison
    disk_changed = disk_mtime > stored_file_mtime

    if not disk_changed:
        return SyncStatus.UNCHANGED

    # Disk changed -- check if DB also changed since last sync
    if last_synced_at and db_updated_at and db_updated_at > last_synced_at:
        return SyncStatus.CONFLICT

    return SyncStatus.DISK_ONLY


def detect_apply_status(
    disk_mtime: datetime | None,
    stored_file_mtime: datetime | None,
    db_updated_at: datetime | None,
    last_synced_at: datetime | None,
) -> SyncStatus:
    """Determine sync status for an apply (DB -> disk) operation.

    Args:
        disk_mtime: Current file modified time on disk.
        stored_file_mtime: The file_mtime stored in DB from last sync.
        db_updated_at: The model's updated_at timestamp.
        last_synced_at: When the last sync happened.
    """
    if last_synced_at is None:
        # Never synced before
        return SyncStatus.NEW_IN_DB

    db_changed = db_updated_at and db_updated_at > last_synced_at

    if not db_changed:
        return SyncStatus.UNCHANGED

    # DB changed -- check if disk also changed
    if stored_file_mtime and disk_mtime and disk_mtime > stored_file_mtime:
        return SyncStatus.CONFLICT

    return SyncStatus.DB_ONLY
