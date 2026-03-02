"""URL configuration for agent_builder."""

from django.urls import include, path
from drf_spectacular.views import SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from .api_views import (
    AgentChunkViewSet,
    AgentInstructionViewSet,
    AgentViewSet,
    ChunkViewSet,
    InstructionViewSet,
    apply_all,
    import_all,
)
from .views import CustomSpectacularAPIView, IndexView

app_name = "agent_builder"

router = DefaultRouter()
router.register(r"agents", AgentViewSet, basename="agent")
router.register(r"chunks", ChunkViewSet, basename="chunk")
router.register(r"instructions", InstructionViewSet, basename="instruction")

urlpatterns = [
    path("api/import-all/", import_all, name="import-all"),
    path("api/apply-all/", apply_all, name="apply-all"),
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
    path(
        "api/agents/<int:agent_pk>/instructions/",
        AgentInstructionViewSet.as_view({"get": "list", "post": "create"}),
        name="agent-instructions-list",
    ),
    path(
        "api/agents/<int:agent_pk>/instructions/<int:pk>/",
        AgentInstructionViewSet.as_view(
            {
                "get": "retrieve",
                "put": "update",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="agent-instructions-detail",
    ),
    path("api/schema/", CustomSpectacularAPIView.as_view(), name="agent-builder-schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="agent_builder:agent-builder-schema"),
        name="agent-builder-swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="agent_builder:agent-builder-schema"),
        name="agent-builder-redoc",
    ),
    path("", IndexView.as_view(), name="agent-builder-index"),
]
