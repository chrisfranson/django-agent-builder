"""
Tests for agent_builder models.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from agent_builder.models import (
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

User = get_user_model()


@pytest.mark.django_db
class TestAgentModel:
    def test_create_claude_agent(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent",
            display_name="Test Agent",
            source="claude",
            description="A test agent",
            model="sonnet",
            frontmatter="name: test-agent\ndescription: A test agent\nmodel: sonnet",
            user=user,
        )
        assert agent.name == "test-agent"
        assert agent.source == "claude"
        assert agent.is_active is True
        assert str(agent) == "test-agent (claude)"

    def test_create_coderoo_agent(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="my-coderoo-agent",
            display_name="My Coderoo Agent",
            source="coderoo",
            user=user,
        )
        assert agent.source == "coderoo"

    def test_agent_name_unique_per_user(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        Agent.objects.create(name="dupe", display_name="Dupe", source="claude", user=user)
        with pytest.raises(IntegrityError):
            Agent.objects.create(name="dupe", display_name="Dupe 2", source="claude", user=user)

    def test_agents_ordered_by_name(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        Agent.objects.create(name="zebra", display_name="Zebra", source="claude", user=user)
        Agent.objects.create(name="alpha", display_name="Alpha", source="claude", user=user)
        agents = list(Agent.objects.filter(user=user))
        assert agents[0].name == "alpha"
        assert agents[1].name == "zebra"


@pytest.mark.django_db
class TestChunkModel:
    def test_create_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(
            title="Core Instructions",
            content="## Role\nYou are a helpful assistant.",
            in_library=True,
            user=user,
        )
        assert chunk.title == "Core Instructions"
        assert chunk.in_library is True
        assert str(chunk) == "Core Instructions"

    def test_unnamed_chunk(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(content="Some content", user=user)
        assert chunk.title == ""
        assert chunk.in_library is False
        assert str(chunk) == f"Chunk #{chunk.pk}"


@pytest.mark.django_db
class TestAgentChunkModel:
    def test_agent_chunk_ordering(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk_a = Chunk.objects.create(content="First section", user=user)
        chunk_b = Chunk.objects.create(content="Second section", user=user)

        AgentChunk.objects.create(agent=agent, chunk=chunk_b, position=1)
        AgentChunk.objects.create(agent=agent, chunk=chunk_a, position=0)

        agent_chunks = list(AgentChunk.objects.filter(agent=agent))
        assert agent_chunks[0].chunk == chunk_a
        assert agent_chunks[1].chunk == chunk_b

    def test_agent_chunk_enabled_default(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk = Chunk.objects.create(content="Content", user=user)
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        assert ac.is_enabled is True
        assert ac.active_variant is None

    def test_agent_chunks_via_m2m(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        chunk = Chunk.objects.create(content="Content", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        assert agent.chunks.count() == 1
        assert agent.chunks.first() == chunk


@pytest.mark.django_db
class TestEdgeCases:
    """Edge-case and cascade tests for models."""

    def test_agent_long_name(self):
        """Agent name field accepts max length (255 chars)."""
        user = User.objects.create_user(username="testuser", password="testpass")
        long_name = "a" * 255
        agent = Agent.objects.create(
            name=long_name, display_name="Long", source="claude", user=user
        )
        agent.refresh_from_db()
        assert len(agent.name) == 255

    def test_chunk_empty_title_str(self):
        """Chunk with no title shows 'Chunk #N' in __str__."""
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(content="content", user=user)
        assert str(chunk) == f"Chunk #{chunk.pk}"
        assert chunk.pk is not None

    def test_agent_chunk_position_zero(self):
        """AgentChunk can have position=0."""
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(name="agent", display_name="Agent", source="claude", user=user)
        chunk = Chunk.objects.create(content="c", user=user)
        ac = AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)
        assert ac.position == 0

    def test_chunk_variant_creation(self):
        """ChunkVariant can be created and links to parent chunk."""
        user = User.objects.create_user(username="testuser", password="testpass")
        chunk = Chunk.objects.create(title="Greeting", content="Hello", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="Hi there, friend!", position=0
        )
        assert variant.chunk == chunk
        assert variant.label == "gentle"
        assert str(variant) == "Greeting / gentle"
        assert chunk.variants.count() == 1

    def test_cascade_delete_user(self):
        """Deleting a user cascades to their agents and chunks."""
        user = User.objects.create_user(username="cascade_user", password="testpass")
        agent = Agent.objects.create(name="agent", display_name="Agent", source="claude", user=user)
        chunk = Chunk.objects.create(content="c", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        user_pk = user.pk
        user.delete()

        assert Agent.objects.filter(user_id=user_pk).count() == 0
        assert Chunk.objects.filter(user_id=user_pk).count() == 0
        assert AgentChunk.objects.count() == 0

    def test_cascade_delete_chunk(self):
        """Deleting a chunk cascades to AgentChunk rows."""
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(name="agent", display_name="Agent", source="claude", user=user)
        chunk = Chunk.objects.create(content="c", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk, position=0)

        chunk.delete()
        assert AgentChunk.objects.filter(agent=agent).count() == 0
        # Agent itself still exists
        assert Agent.objects.filter(pk=agent.pk).exists()

    def test_agent_chunks_m2m_access(self):
        """Agent.chunks M2M provides access to related chunks through AgentChunk."""
        user = User.objects.create_user(username="testuser", password="testpass")
        agent = Agent.objects.create(name="agent", display_name="Agent", source="claude", user=user)
        chunk1 = Chunk.objects.create(title="A", content="a", user=user)
        chunk2 = Chunk.objects.create(title="B", content="b", user=user)
        AgentChunk.objects.create(agent=agent, chunk=chunk1, position=0)
        AgentChunk.objects.create(agent=agent, chunk=chunk2, position=1)

        assert agent.chunks.count() == 2
        assert set(agent.chunks.all()) == {chunk1, chunk2}
        # Verify the reverse -- chunk.agent_set not available, but agent_chunks is
        assert chunk1.agent_chunks.count() == 1
        assert chunk1.agent_chunks.first().agent == agent


@pytest.mark.django_db
class TestInstructionModel:
    def test_create_instruction(self, user):
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Coding Standards",
            content="## Standards\nFollow PEP8.",
            injection_mode="on_demand",
            user=user,
        )
        assert instruction.name == "standards"
        assert instruction.display_name == "Coding Standards"
        assert instruction.injection_mode == "on_demand"
        assert str(instruction) == "standards"

    def test_instruction_auto_inject(self, user):
        instruction = Instruction.objects.create(
            name="always-on",
            display_name="Always On",
            content="Always active content.",
            injection_mode="auto_inject",
            user=user,
        )
        assert instruction.injection_mode == "auto_inject"

    def test_instruction_name_unique_per_user(self, user):
        Instruction.objects.create(name="dupe", display_name="Dupe", content="c", user=user)
        with pytest.raises(IntegrityError):
            Instruction.objects.create(name="dupe", display_name="Dupe 2", content="c2", user=user)

    def test_instructions_ordered_by_name(self, user):
        Instruction.objects.create(name="zebra", display_name="Zebra", content="z", user=user)
        Instruction.objects.create(name="alpha", display_name="Alpha", content="a", user=user)
        instructions = list(Instruction.objects.filter(user=user))
        assert instructions[0].name == "alpha"
        assert instructions[1].name == "zebra"


@pytest.mark.django_db
class TestAgentInstructionModel:
    def test_agent_instruction_creation(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Standards",
            content="c",
            injection_mode="on_demand",
            user=user,
        )
        ai = AgentInstruction.objects.create(
            agent=agent, instruction=instruction, injection_mode="auto_inject"
        )
        assert ai.get_effective_mode() == "auto_inject"
        assert str(ai) == "test-agent / standards (auto_inject)"

    def test_agent_instruction_default_mode(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Standards",
            content="c",
            injection_mode="on_demand",
            user=user,
        )
        ai = AgentInstruction.objects.create(
            agent=agent, instruction=instruction, injection_mode=""
        )
        assert ai.get_effective_mode() == "on_demand"
        assert str(ai) == "test-agent / standards (on_demand)"

    def test_agent_instruction_unique_together(self, user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Standards",
            content="c",
            user=user,
        )
        AgentInstruction.objects.create(agent=agent, instruction=instruction)
        with pytest.raises(IntegrityError):
            AgentInstruction.objects.create(agent=agent, instruction=instruction)

    def test_cross_user_validation(self, user, admin_user):
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="claude", user=user
        )
        instruction = Instruction.objects.create(
            name="standards",
            display_name="Standards",
            content="c",
            user=admin_user,
        )
        ai = AgentInstruction(agent=agent, instruction=instruction)
        with pytest.raises(ValidationError):
            ai.clean()


@pytest.mark.django_db
class TestActiveVariantValidation:
    def test_active_variant_must_belong_to_same_chunk(self, user):
        chunk1 = Chunk.objects.create(title="Chunk 1", content="c1", user=user)
        chunk2 = Chunk.objects.create(title="Chunk 2", content="c2", user=user)
        variant_for_chunk2 = ChunkVariant.objects.create(
            chunk=chunk2, label="gentle", content="content", position=0
        )
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        ac = AgentChunk(agent=agent, chunk=chunk1, position=0, active_variant=variant_for_chunk2)
        with pytest.raises(ValidationError):
            ac.clean()

    def test_active_variant_same_chunk_passes(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        variant = ChunkVariant.objects.create(
            chunk=chunk, label="gentle", content="content", position=0
        )
        agent = Agent.objects.create(
            name="test-agent", display_name="Test", source="coderoo", user=user
        )
        ac = AgentChunk(agent=agent, chunk=chunk, position=0, active_variant=variant)
        ac.clean()  # Should not raise


@pytest.mark.django_db
class TestRevisionModel:
    def test_create_revision_for_chunk(self, user):
        chunk = Chunk.objects.create(title="Test", content="original", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"title": "Test", "content": "original"},
            user=user,
        )
        assert revision.content_object == chunk
        assert revision.content_snapshot["content"] == "original"

    def test_create_revision_for_instruction(self, user):
        instruction = Instruction.objects.create(
            name="test", display_name="Test", content="v1", user=user
        )
        ct = ContentType.objects.get_for_model(Instruction)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=instruction.pk,
            content_snapshot={"name": "test", "content": "v1"},
            user=user,
        )
        assert revision.content_object == instruction

    def test_revision_ordering(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        r1 = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "v1"},
            user=user,
        )
        r2 = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "v2"},
            user=user,
        )
        revisions = list(Revision.objects.filter(content_type=ct, object_id=chunk.pk))
        # Most recent first
        assert revisions[0].pk == r2.pk
        assert revisions[1].pk == r1.pk

    def test_revision_with_message(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "content"},
            message="Initial version",
            user=user,
        )
        assert revision.message == "Initial version"

    def test_revision_str(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        revision = Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "content"},
            user=user,
        )
        assert str(chunk.pk) in str(revision)

    def test_revision_cascade_on_user_delete(self, user):
        chunk = Chunk.objects.create(title="Test", content="content", user=user)
        ct = ContentType.objects.get_for_model(Chunk)
        Revision.objects.create(
            content_type=ct,
            object_id=chunk.pk,
            content_snapshot={"content": "content"},
            user=user,
        )
        user.delete()
        assert Revision.objects.count() == 0


class TestProfileModel:
    @pytest.mark.django_db
    def test_create_profile(self, user):
        profile = Profile.objects.create(
            name="production-config",
            description="Production agent configuration",
            snapshot={"agents": [], "chunks": [], "instructions": []},
            user=user,
        )
        assert profile.name == "production-config"
        assert profile.snapshot["agents"] == []
        assert str(profile) == "production-config"

    @pytest.mark.django_db
    def test_profile_name_unique_per_user(self, user):
        Profile.objects.create(
            name="config-v1",
            snapshot={},
            user=user,
        )
        with pytest.raises(IntegrityError):
            Profile.objects.create(
                name="config-v1",
                snapshot={},
                user=user,
            )

    @pytest.mark.django_db
    def test_profiles_ordered_by_name(self, user):
        Profile.objects.create(name="zebra", snapshot={}, user=user)
        Profile.objects.create(name="alpha", snapshot={}, user=user)
        names = list(Profile.objects.filter(user=user).values_list("name", flat=True))
        assert names == ["alpha", "zebra"]

    @pytest.mark.django_db
    def test_profile_cascade_on_user_delete(self, user):
        Profile.objects.create(name="config", snapshot={}, user=user)
        user.delete()
        assert Profile.objects.count() == 0


@pytest.mark.django_db
class TestProjectModel:
    def test_create_project(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        project = Project.objects.create(
            name="my-project",
            path="/storage/Projects/my-project",
            has_coderoo=True,
            has_claude_config=False,
            user=user,
        )
        assert project.name == "my-project"
        assert project.has_coderoo is True
        assert project.has_claude_config is False
        assert str(project) == "my-project (/storage/Projects/my-project)"

    def test_project_path_unique_per_user(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        Project.objects.create(
            name="proj",
            path="/some/path",
            user=user,
        )
        with pytest.raises(IntegrityError):
            Project.objects.create(
                name="proj2",
                path="/some/path",
                user=user,
            )

    def test_different_users_same_path(self):
        user1 = User.objects.create_user(username="user1", password="testpass")
        user2 = User.objects.create_user(username="user2", password="testpass")
        Project.objects.create(name="proj", path="/same/path", user=user1)
        Project.objects.create(name="proj", path="/same/path", user=user2)
        assert Project.objects.count() == 2

    def test_project_both_flags(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        project = Project.objects.create(
            name="both",
            path="/storage/Projects/both",
            has_coderoo=True,
            has_claude_config=True,
            user=user,
        )
        assert project.has_coderoo is True
        assert project.has_claude_config is True

    def test_projects_ordered_by_name(self):
        user = User.objects.create_user(username="testuser", password="testpass")
        Project.objects.create(name="zebra", path="/z", user=user)
        Project.objects.create(name="alpha", path="/a", user=user)
        names = list(Project.objects.filter(user=user).values_list("name", flat=True))
        assert names == ["alpha", "zebra"]


class TestConfigFileModel:
    @pytest.mark.django_db
    def test_create_config_file(self, user):
        cf = ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/home/testuser/.claude/CLAUDE.md",
            content="# Instructions\nBe helpful.",
            user=user,
        )
        assert cf.filename == "CLAUDE.md"
        assert cf.content == "# Instructions\nBe helpful."
        assert str(cf) == "/home/testuser/.claude/CLAUDE.md"

    @pytest.mark.django_db
    def test_config_file_path_unique_per_user(self, user):
        ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/home/testuser/.claude/CLAUDE.md",
            content="v1",
            user=user,
        )
        with pytest.raises(IntegrityError):
            ConfigFile.objects.create(
                filename="CLAUDE.md",
                path="/home/testuser/.claude/CLAUDE.md",
                content="v2",
                user=user,
            )

    @pytest.mark.django_db
    def test_config_files_ordered_by_path(self, user):
        ConfigFile.objects.create(filename="CLAUDE.md", path="/z/CLAUDE.md", content="", user=user)
        ConfigFile.objects.create(filename="AGENTS.md", path="/a/AGENTS.md", content="", user=user)
        paths = list(ConfigFile.objects.filter(user=user).values_list("path", flat=True))
        assert paths == ["/a/AGENTS.md", "/z/CLAUDE.md"]

    @pytest.mark.django_db
    def test_config_file_scope(self, user):
        cf = ConfigFile.objects.create(
            filename="AGENTS.md",
            path="/storage/Projects/AGENTS.md",
            content="",
            user=user,
        )
        assert cf.scope == "/storage/Projects"

    @pytest.mark.django_db
    def test_config_file_cascade_on_user_delete(self, user):
        ConfigFile.objects.create(
            filename="CLAUDE.md",
            path="/test/CLAUDE.md",
            content="",
            user=user,
        )
        user.delete()
        assert ConfigFile.objects.count() == 0


@pytest.mark.django_db
class TestSoftDeleteBehavior:
    """Tests for SoftDeleteModel infrastructure across Agent, Instruction, ConfigFile, Project."""

    def test_queryset_delete_sets_flags(self, user):
        """SoftDeleteQuerySet.delete() sets is_deleted=True and deleted_at."""
        Agent.objects.create(name="a1", display_name="A1", source="claude", user=user)
        Agent.objects.create(name="a2", display_name="A2", source="claude", user=user)
        Agent.objects.filter(user=user).delete()
        # Default manager excludes soft-deleted, so use all_objects
        agents = Agent.all_objects.filter(user=user)
        assert agents.count() == 2
        for agent in agents:
            assert agent.is_deleted is True
            assert agent.deleted_at is not None

    def test_queryset_hard_delete_removes_rows(self, user):
        """SoftDeleteQuerySet.hard_delete() actually removes from the database."""
        Agent.objects.create(name="gone", display_name="Gone", source="claude", user=user)
        Agent.all_objects.filter(user=user).hard_delete()
        assert Agent.all_objects.filter(user=user).count() == 0

    def test_default_manager_excludes_soft_deleted(self, user):
        """objects (default manager) excludes soft-deleted records."""
        a = Agent.objects.create(name="visible", display_name="V", source="claude", user=user)
        a.soft_delete()
        assert Agent.objects.filter(user=user).count() == 0
        assert Agent.all_objects.filter(user=user).count() == 1

    def test_all_objects_includes_everything(self, user):
        """all_objects manager returns both active and soft-deleted records."""
        Agent.objects.create(name="active", display_name="Active", source="claude", user=user)
        a2 = Agent.objects.create(
            name="deleted", display_name="Deleted", source="claude", user=user
        )
        a2.soft_delete()
        assert Agent.all_objects.filter(user=user).count() == 2
        assert Agent.objects.filter(user=user).count() == 1

    def test_soft_delete_instance_method(self, user):
        """soft_delete() sets is_deleted and deleted_at on the instance."""
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        agent.soft_delete()
        agent.refresh_from_db()
        assert agent.is_deleted is True
        assert agent.deleted_at is not None

    def test_restore_instance_method(self, user):
        """restore() clears is_deleted and deleted_at."""
        agent = Agent.objects.create(name="test", display_name="Test", source="claude", user=user)
        agent.soft_delete()
        agent.restore()
        agent.refresh_from_db()
        assert agent.is_deleted is False
        assert agent.deleted_at is None
        # Should be visible via default manager again
        assert Agent.objects.filter(pk=agent.pk).exists()

    def test_alive_and_dead_querysets(self, user):
        """alive() and dead() filter correctly."""
        Agent.objects.create(name="alive", display_name="Alive", source="claude", user=user)
        a2 = Agent.objects.create(name="dead", display_name="Dead", source="claude", user=user)
        a2.soft_delete()
        assert Agent.all_objects.filter(user=user).alive().count() == 1
        assert Agent.all_objects.filter(user=user).dead().count() == 1

    def test_conditional_unique_allows_recreate_after_soft_delete(self, user):
        """Soft-deleting a record allows creating a new one with the same unique fields."""
        agent = Agent.objects.create(name="reuse", display_name="Reuse", source="claude", user=user)
        agent.soft_delete()
        # Should not raise IntegrityError
        new_agent = Agent.objects.create(
            name="reuse", display_name="Reuse V2", source="claude", user=user
        )
        assert new_agent.pk != agent.pk
        assert Agent.objects.filter(user=user, name="reuse").count() == 1
        assert Agent.all_objects.filter(user=user, name="reuse").count() == 2

    def test_instruction_soft_delete(self, user):
        """Instruction model supports soft delete."""
        inst = Instruction.objects.create(name="test", display_name="Test", content="c", user=user)
        inst.soft_delete()
        assert Instruction.objects.filter(user=user).count() == 0
        assert Instruction.all_objects.filter(user=user).count() == 1

    def test_configfile_soft_delete(self, user):
        """ConfigFile model supports soft delete."""
        cf = ConfigFile.objects.create(
            filename="CLAUDE.md", path="/test/CLAUDE.md", content="", user=user
        )
        cf.soft_delete()
        assert ConfigFile.objects.filter(user=user).count() == 0
        assert ConfigFile.all_objects.filter(user=user).count() == 1

    def test_project_soft_delete(self, user):
        """Project model supports soft delete."""
        proj = Project.objects.create(name="proj", path="/test/proj", user=user)
        proj.soft_delete()
        assert Project.objects.filter(user=user).count() == 0
        assert Project.all_objects.filter(user=user).count() == 1

    def test_project_conditional_unique_after_soft_delete(self, user):
        """Project path uniqueness allows re-creation after soft delete."""
        proj = Project.objects.create(name="proj", path="/test/proj", user=user)
        proj.soft_delete()
        new_proj = Project.objects.create(name="proj-v2", path="/test/proj", user=user)
        assert new_proj.pk != proj.pk

    def test_instruction_conditional_unique_after_soft_delete(self, user):
        """Instruction name uniqueness allows re-creation after soft delete."""
        inst = Instruction.objects.create(
            name="reuse", display_name="Reuse", content="c", user=user
        )
        inst.soft_delete()
        new_inst = Instruction.objects.create(
            name="reuse", display_name="Reuse V2", content="c2", user=user
        )
        assert new_inst.pk != inst.pk

    def test_configfile_conditional_unique_after_soft_delete(self, user):
        """ConfigFile path uniqueness allows re-creation after soft delete."""
        cf = ConfigFile.objects.create(
            filename="CLAUDE.md", path="/test/CLAUDE.md", content="v1", user=user
        )
        cf.soft_delete()
        new_cf = ConfigFile.objects.create(
            filename="CLAUDE.md", path="/test/CLAUDE.md", content="v2", user=user
        )
        assert new_cf.pk != cf.pk
