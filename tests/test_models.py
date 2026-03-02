"""
Tests for agent_builder models.
"""

import pytest
from django.contrib.auth import get_user_model

from agent_builder.models import ExampleModel

User = get_user_model()


@pytest.mark.django_db
class TestExampleModel:
    """Tests for ExampleModel."""

    def test_create_example(self, user):
        """Test creating an ExampleModel instance."""
        example = ExampleModel.objects.create(
            user=user, name="Test Example", description="This is a test"
        )
        assert example.id is not None
        assert example.name == "Test Example"
        assert example.user == user
        assert str(example) == f"Test Example ({user.username})"

    def test_example_ordering(self, user):
        """Test that examples are ordered by created_at (newest first)."""
        example1 = ExampleModel.objects.create(user=user, name="First")
        example2 = ExampleModel.objects.create(user=user, name="Second")

        examples = list(ExampleModel.objects.all())
        assert examples[0] == example2  # Newest first
        assert examples[1] == example1

    def test_user_deletion_cascades(self, user):
        """Test that deleting a user deletes their examples."""
        ExampleModel.objects.create(user=user, name="Test Example")
        assert ExampleModel.objects.count() == 1

        user.delete()
        assert ExampleModel.objects.count() == 0
