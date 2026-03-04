"""Tests for mtime tracking and conflict detection."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone as tz
from rest_framework.test import APIClient

from agent_builder.models import Agent, AgentChunk, Chunk, Instruction
from agent_builder.sync import SyncStatus, detect_apply_status, detect_import_status

User = get_user_model()


@pytest.fixture
def api_client():
    user = User.objects.create_user(username="testuser", password="testpass")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


class TestSyncStatusDetection:
    """Unit tests for sync status detection logic."""

    def test_import_new_item(self):
        """First-time import (no stored mtime) should return NEW_ON_DISK."""
        status = detect_import_status(
            disk_mtime=datetime(2026, 1, 1, tzinfo=timezone.utc),
            stored_file_mtime=None,
            db_updated_at=None,
            last_synced_at=None,
        )
        assert status == SyncStatus.NEW_ON_DISK

    def test_import_unchanged(self):
        """File unchanged on disk should return UNCHANGED."""
        mtime = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_import_status(
            disk_mtime=mtime,
            stored_file_mtime=mtime,
            db_updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            last_synced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert status == SyncStatus.UNCHANGED

    def test_import_disk_only_change(self):
        """Only disk changed should return DISK_ONLY."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_import_status(
            disk_mtime=base + timedelta(hours=1),
            stored_file_mtime=base,
            db_updated_at=base,
            last_synced_at=base,
        )
        assert status == SyncStatus.DISK_ONLY

    def test_import_conflict(self):
        """Both disk and DB changed should return CONFLICT."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_import_status(
            disk_mtime=base + timedelta(hours=1),
            stored_file_mtime=base,
            db_updated_at=base + timedelta(hours=2),
            last_synced_at=base,
        )
        assert status == SyncStatus.CONFLICT

    def test_import_db_only_change(self):
        """Only DB changed (disk unchanged) should return UNCHANGED (nothing to import)."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_import_status(
            disk_mtime=base,
            stored_file_mtime=base,
            db_updated_at=base + timedelta(hours=1),
            last_synced_at=base,
        )
        assert status == SyncStatus.UNCHANGED

    def test_import_deleted_from_disk(self):
        """File deleted from disk should return DELETED_ON_DISK."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_import_status(
            disk_mtime=None,
            stored_file_mtime=base,
            db_updated_at=base,
            last_synced_at=base,
        )
        assert status == SyncStatus.DELETED_ON_DISK

    def test_apply_new_item(self):
        """Never synced should return NEW_IN_DB."""
        status = detect_apply_status(
            disk_mtime=None,
            stored_file_mtime=None,
            db_updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            last_synced_at=None,
        )
        assert status == SyncStatus.NEW_IN_DB

    def test_apply_unchanged(self):
        """DB unchanged since sync should return UNCHANGED."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_apply_status(
            disk_mtime=base,
            stored_file_mtime=base,
            db_updated_at=base,
            last_synced_at=base + timedelta(hours=1),
        )
        assert status == SyncStatus.UNCHANGED

    def test_apply_db_only_change(self):
        """Only DB changed should return DB_ONLY."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_apply_status(
            disk_mtime=base,
            stored_file_mtime=base,
            db_updated_at=base + timedelta(hours=1),
            last_synced_at=base,
        )
        assert status == SyncStatus.DB_ONLY

    def test_apply_conflict(self):
        """Both DB and disk changed should return CONFLICT."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_apply_status(
            disk_mtime=base + timedelta(hours=1),
            stored_file_mtime=base,
            db_updated_at=base + timedelta(hours=2),
            last_synced_at=base,
        )
        assert status == SyncStatus.CONFLICT

    def test_apply_disk_only_change(self):
        """Only disk changed (DB unchanged) should return UNCHANGED (nothing to apply)."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        status = detect_apply_status(
            disk_mtime=base + timedelta(hours=1),
            stored_file_mtime=base,
            db_updated_at=base,
            last_synced_at=base + timedelta(hours=1),
        )
        assert status == SyncStatus.UNCHANGED


@pytest.mark.django_db
class TestImportConflictIntegration:
    """Integration tests for import with conflict detection."""

    def test_import_skips_unchanged_files(self, api_client):
        """Import should skip files whose mtime hasn't changed."""
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            user=user,
        )
        base = tz.now() - timedelta(hours=1)
        Agent.objects.filter(pk=agent.pk).update(
            file_mtime=base,
            last_synced_at=base,
        )

        with patch("agent_builder.api_views.read_claude_agents") as mock_read:
            mock_read.return_value = [
                {
                    "name": "test-agent",
                    "source": "claude",
                    "frontmatter": "",
                    "content": "hello",
                    "mtime": base,
                }
            ]
            with patch("agent_builder.api_views.read_coderoo_agents", return_value=[]):
                with patch("agent_builder.api_views.read_instructions", return_value=[]):
                    with patch("agent_builder.api_views.read_config_files", return_value=[]):
                        with patch("agent_builder.api_views.scan_projects", return_value=[]):
                            res = client.post("/agent-builder/api/import-all/")

        assert res.status_code == 200
        assert res.data["skipped"] == 1
        assert res.data["updated"] == 0

    def test_import_detects_conflict(self, api_client):
        """Import should detect conflict when both DB and disk changed."""
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            user=user,
        )
        base = tz.now() - timedelta(hours=2)
        Agent.objects.filter(pk=agent.pk).update(
            file_mtime=base,
            last_synced_at=base,
            updated_at=base + timedelta(hours=1),
        )

        with patch("agent_builder.api_views.read_claude_agents") as mock_read:
            mock_read.return_value = [
                {
                    "name": "test-agent",
                    "source": "claude",
                    "frontmatter": "",
                    "content": "new content",
                    "mtime": base + timedelta(hours=1),
                }
            ]
            with patch("agent_builder.api_views.read_coderoo_agents", return_value=[]):
                with patch("agent_builder.api_views.read_instructions", return_value=[]):
                    with patch("agent_builder.api_views.read_config_files", return_value=[]):
                        with patch("agent_builder.api_views.scan_projects", return_value=[]):
                            res = client.post("/agent-builder/api/import-all/")

        assert res.status_code == 200
        assert len(res.data["conflicts"]) == 1
        assert res.data["conflicts"][0]["conflict_type"] == "both_modified"

    def test_import_updates_disk_only_change(self, api_client):
        """Import should update when only disk changed."""
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            frontmatter="",
            user=user,
        )
        chunk = Chunk.objects.create(content="old content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        base = tz.now() - timedelta(hours=2)
        Agent.objects.filter(pk=agent.pk).update(
            file_mtime=base,
            last_synced_at=base,
            updated_at=base,
        )

        with patch("agent_builder.api_views.read_claude_agents") as mock_read:
            mock_read.return_value = [
                {
                    "name": "test-agent",
                    "source": "claude",
                    "frontmatter": "",
                    "content": "updated content",
                    "mtime": base + timedelta(hours=1),
                }
            ]
            with patch("agent_builder.api_views.read_coderoo_agents", return_value=[]):
                with patch("agent_builder.api_views.read_instructions", return_value=[]):
                    with patch("agent_builder.api_views.read_config_files", return_value=[]):
                        with patch("agent_builder.api_views.scan_projects", return_value=[]):
                            res = client.post("/agent-builder/api/import-all/")

        assert res.status_code == 200
        assert res.data["updated"] == 1
        # Verify chunk content was updated
        chunk.refresh_from_db()
        assert chunk.content == "updated content"

    def test_import_new_agent_sets_sync_fields(self, api_client):
        """Newly imported agent should have file_mtime and last_synced_at set."""
        client, user = api_client
        mtime = tz.now() - timedelta(hours=1)

        with patch("agent_builder.api_views.read_claude_agents") as mock_read:
            mock_read.return_value = [
                {
                    "name": "new-agent",
                    "source": "claude",
                    "frontmatter": "name: New Agent",
                    "content": "hello",
                    "mtime": mtime,
                }
            ]
            with patch("agent_builder.api_views.read_coderoo_agents", return_value=[]):
                with patch("agent_builder.api_views.read_instructions", return_value=[]):
                    with patch("agent_builder.api_views.read_config_files", return_value=[]):
                        with patch("agent_builder.api_views.scan_projects", return_value=[]):
                            res = client.post("/agent-builder/api/import-all/")

        assert res.status_code == 200
        assert res.data["imported"] == 1
        agent = Agent.objects.get(name="new-agent", user=user)
        assert agent.file_mtime == mtime
        assert agent.last_synced_at is not None

    def test_import_instruction_conflict(self, api_client):
        """Import should detect instruction conflicts."""
        client, user = api_client
        inst = Instruction.objects.create(
            name="test-inst",
            display_name="Test",
            content="old",
            user=user,
        )
        base = tz.now() - timedelta(hours=2)
        Instruction.objects.filter(pk=inst.pk).update(
            file_mtime=base,
            last_synced_at=base,
            updated_at=base + timedelta(hours=1),
        )

        with patch("agent_builder.api_views.read_claude_agents", return_value=[]):
            with patch("agent_builder.api_views.read_coderoo_agents", return_value=[]):
                with patch("agent_builder.api_views.read_instructions") as mock_read:
                    mock_read.return_value = [
                        {
                            "name": "test-inst",
                            "content": "new content",
                            "mtime": base + timedelta(hours=1),
                        }
                    ]
                    with patch("agent_builder.api_views.read_config_files", return_value=[]):
                        with patch("agent_builder.api_views.scan_projects", return_value=[]):
                            res = client.post("/agent-builder/api/import-all/")

        assert res.status_code == 200
        assert len(res.data["conflicts"]) == 1
        assert res.data["conflicts"][0]["type"] == "instruction"


@pytest.mark.django_db
class TestApplyConflictIntegration:
    """Integration tests for apply with conflict detection."""

    def test_apply_preview_shows_conflict(self, api_client):
        """Apply preview should show conflict flag when both sides changed."""
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            frontmatter="",
            user=user,
        )
        chunk = Chunk.objects.create(content="db content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        base = tz.now() - timedelta(hours=2)
        Agent.objects.filter(pk=agent.pk).update(
            file_mtime=base,
            last_synced_at=base,
            updated_at=base + timedelta(hours=1),
        )

        new_mtime = base + timedelta(hours=1)

        with patch("agent_builder.filesystem._get_file_mtime", return_value=new_mtime):
            with patch("agent_builder.filesystem.render_agent", return_value="db content"):
                with patch("pathlib.Path.read_text", return_value="old disk content"):
                    res = client.get("/agent-builder/api/apply-all/preview/")

        assert res.status_code == 200
        agents = res.data["agents"]
        assert len(agents) == 1
        assert agents[0]["has_conflict"] is True
        assert agents[0]["sync_status"] == "conflict"

    def test_apply_skips_conflicts_by_default(self, api_client):
        """Apply should skip conflicted items by default."""
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            frontmatter="",
            user=user,
        )
        chunk = Chunk.objects.create(content="db content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        base = tz.now() - timedelta(hours=2)
        Agent.objects.filter(pk=agent.pk).update(
            file_mtime=base,
            last_synced_at=base,
            updated_at=base + timedelta(hours=1),
        )

        new_mtime = base + timedelta(hours=1)
        with patch("agent_builder.filesystem._get_file_mtime", return_value=new_mtime):
            with patch("agent_builder.api_views.write_agent") as mock_write:
                res = client.post("/agent-builder/api/apply-all/")

        assert res.status_code == 200
        assert res.data["results"][0]["status"] == "conflict"
        mock_write.assert_not_called()

    def test_apply_forces_conflict_with_force_paths(self, api_client):
        """Apply should write conflicted items when force_paths includes them."""
        client, user = api_client
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test",
            source="claude",
            frontmatter="",
            user=user,
        )
        chunk = Chunk.objects.create(content="db content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        base = tz.now() - timedelta(hours=2)
        Agent.objects.filter(pk=agent.pk).update(
            file_mtime=base,
            last_synced_at=base,
            updated_at=base + timedelta(hours=1),
        )

        from agent_builder.filesystem import DEFAULT_CLAUDE_AGENTS_DIR

        disk_path = str(DEFAULT_CLAUDE_AGENTS_DIR / "test-agent.md")
        new_mtime = base + timedelta(hours=1)
        written_mtime = tz.now()

        with patch("agent_builder.filesystem._get_file_mtime", return_value=new_mtime):
            with patch("agent_builder.api_views.write_agent") as mock_write:
                from pathlib import Path

                mock_write.return_value = (Path(disk_path), written_mtime)
                res = client.post(
                    "/agent-builder/api/apply-all/",
                    {"force_paths": [disk_path]},
                    format="json",
                )

        assert res.status_code == 200
        assert res.data["results"][0]["status"] == "ok"
        mock_write.assert_called_once()
