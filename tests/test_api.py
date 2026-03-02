"""
Tests for agent_builder API views.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from agent_builder.models import ExampleModel


@pytest.mark.django_db
class TestExampleModelViewSet:
    """Tests for ExampleModel ViewSet."""

    def test_list_requires_authentication(self, api_client):
        """Test that listing examples requires authentication."""
        url = reverse("example-list")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_examples(self, authenticated_client, user):
        """Test listing examples for authenticated user."""
        # Create some examples
        ExampleModel.objects.create(user=user, name="Example 1")
        ExampleModel.objects.create(user=user, name="Example 2")

        url = reverse("example-list")
        response = authenticated_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2

    def test_create_example(self, authenticated_client, user):
        """Test creating an example via API."""
        url = reverse("example-list")
        data = {"name": "New Example", "description": "Created via API"}
        response = authenticated_client.post(url, data)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "New Example"
        assert response.data["user"] == user.id

        # Verify it was created in the database
        assert ExampleModel.objects.filter(name="New Example").exists()

    def test_user_scoping(self, api_client, user):
        """Test that users can only see their own examples."""
        # Create another user
        from django.contrib.auth import get_user_model

        User = get_user_model()
        other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password="otherpass123"
        )

        # Create examples for both users
        ExampleModel.objects.create(user=user, name="User 1 Example")
        ExampleModel.objects.create(user=other_user, name="User 2 Example")

        # Authenticate as first user
        api_client.force_authenticate(user=user)
        url = reverse("example-list")
        response = api_client.get(url)

        # Should only see own example
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "User 1 Example"

    def test_update_example(self, authenticated_client, user):
        """Test updating an example."""
        example = ExampleModel.objects.create(user=user, name="Original Name")

        url = reverse("example-detail", kwargs={"pk": example.pk})
        data = {"name": "Updated Name"}
        response = authenticated_client.patch(url, data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Name"

        example.refresh_from_db()
        assert example.name == "Updated Name"

    def test_delete_example(self, authenticated_client, user):
        """Test deleting an example."""
        example = ExampleModel.objects.create(user=user, name="To Delete")

        url = reverse("example-detail", kwargs={"pk": example.pk})
        response = authenticated_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ExampleModel.objects.filter(pk=example.pk).exists()
