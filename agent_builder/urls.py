"""URL configuration for agent_builder."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .api_views import AgentChunkViewSet, AgentViewSet, ChunkViewSet

app_name = "agent_builder"

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"chunks", ChunkViewSet, basename="chunk")

urlpatterns = [
    path("api/", include(router.urls)),
    path(
        "api/agents/<int:agent_pk>/chunks/",
        AgentChunkViewSet.as_view({"get": "list", "post": "create"}),
        name="agent-chunks-list",
    ),
    path(
        "api/agents/<int:agent_pk>/chunks/<int:pk>/",
        AgentChunkViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="agent-chunks-detail",
    ),
]
