"""
API views for agent_builder with OAuth2 authentication and user scoping.

All views require authentication and automatically scope data to the requesting user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from .models import ExampleModel
from .serializers import ExampleModelSerializer

if TYPE_CHECKING:
    from django.db.models import QuerySet


class ExampleModelViewSet(viewsets.ModelViewSet):
    """
    ViewSet for ExampleModel with automatic user scoping.

    Only returns objects owned by the authenticated user.
    Automatically assigns the current user when creating new objects.
    """

    serializer_class = ExampleModelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[ExampleModel]:
        """Filter queryset to only include objects owned by the current user."""
        return ExampleModel.objects.filter(user=self.request.user)

    def perform_create(self, serializer: ExampleModelSerializer) -> None:
        """Automatically assign the current user when creating objects."""
        serializer.save(user=self.request.user)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def example_api_view(request: Request) -> Response:
    """
    Example function-based API view with authentication.

    Returns user-scoped data for the authenticated user.
    """
    examples = ExampleModel.objects.filter(user=request.user)
    serializer = ExampleModelSerializer(examples, many=True)
    return Response({"count": examples.count(), "results": serializer.data})
