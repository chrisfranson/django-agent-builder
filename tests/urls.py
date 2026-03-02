from django.urls import include, path

urlpatterns = [
    path("agent-builder/", include("agent_builder.urls")),
]
