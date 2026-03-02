import pytest
from django.contrib.contenttypes.models import ContentType

from agent_builder.models import Chunk, Instruction, Revision
from agent_builder.revisions import create_revision, get_snapshot


class TestGetSnapshot:
    @pytest.mark.django_db
    def test_chunk_snapshot(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        snapshot = get_snapshot(chunk)
        assert snapshot == {"title": "Test", "content": "content", "in_library": False}

    @pytest.mark.django_db
    def test_instruction_snapshot(self, user):
        instruction = Instruction.objects.create(
            name="test",
            display_name="Test",
            content="v1",
            injection_mode="on_demand",
            user=user,
        )
        snapshot = get_snapshot(instruction)
        assert snapshot == {
            "name": "test",
            "display_name": "Test",
            "content": "v1",
            "injection_mode": "on_demand",
        }


class TestCreateRevision:
    @pytest.mark.django_db
    def test_create_revision_for_chunk(self, user):
        chunk = Chunk.objects.create(title="Test", content="original", user=user)
        revision = create_revision(chunk, user)
        assert revision is not None
        assert revision.content_snapshot["content"] == "original"
        assert revision.user == user

    @pytest.mark.django_db
    def test_create_revision_with_message(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        revision = create_revision(chunk, user, message="Updated content")
        assert revision.message == "Updated content"

    @pytest.mark.django_db
    def test_no_duplicate_revision_if_unchanged(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        create_revision(chunk, user)
        revision2 = create_revision(chunk, user)
        assert revision2 is None  # No change, no new revision
        assert Revision.objects.count() == 1

    @pytest.mark.django_db
    def test_new_revision_on_content_change(self, user):
        chunk = Chunk.objects.create(title="Test", content="v1", user=user)
        create_revision(chunk, user)
        chunk.content = "v2"
        chunk.save()
        revision2 = create_revision(chunk, user)
        assert revision2 is not None
        assert Revision.objects.count() == 2


class TestRevisionViaAPI:
    @pytest.mark.django_db
    def test_chunk_update_creates_revision(self, authenticated_client, user):
        chunk = Chunk.objects.create(title="Test", content="original", user=user)
        authenticated_client.patch(
            f"/agent-builder/api/chunks/{chunk.pk}/",
            {"content": "updated"},
            format="json",
        )
        ct = ContentType.objects.get_for_model(Chunk)
        assert Revision.objects.filter(content_type=ct, object_id=chunk.pk).count() == 1

    @pytest.mark.django_db
    def test_instruction_update_creates_revision(self, authenticated_client, user):
        instruction = Instruction.objects.create(
            name="test",
            display_name="Test",
            content="v1",
            user=user,
        )
        authenticated_client.patch(
            f"/agent-builder/api/instructions/{instruction.pk}/",
            {"content": "v2"},
            format="json",
        )
        ct = ContentType.objects.get_for_model(Instruction)
        assert Revision.objects.filter(content_type=ct, object_id=instruction.pk).count() == 1

    @pytest.mark.django_db
    def test_no_revision_on_create(self, authenticated_client, user):
        authenticated_client.post(
            "/agent-builder/api/chunks/",
            {"title": "New", "content": "content"},
            format="json",
        )
        assert Revision.objects.count() == 0
