"""
Serializers for agent_builder with OAuth2 support.
"""

from rest_framework import serializers

from .models import ExampleModel


class ExampleModelSerializer(serializers.ModelSerializer):
    """
    Serializer for ExampleModel.

    The 'user' field is read-only since it's automatically assigned from request.user.
    """

    class Meta:
        model = ExampleModel
        fields = ["id", "user", "name", "description", "created_at", "updated_at"]
        read_only_fields = ["user", "created_at", "updated_at"]
