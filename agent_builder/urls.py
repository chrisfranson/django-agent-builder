"""
URL configuration for agent_builder with OAuth2 and DRF support.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import ExampleModelViewSet, example_api_view

# Create a router and register viewsets
router = DefaultRouter()
router.register(r"examples", ExampleModelViewSet, basename="example")

urlpatterns = [
    # API endpoints via router
    path("api/", include(router.urls)),
    # Custom API endpoints
    path("api/custom-example/", example_api_view, name="custom-example"),
]
