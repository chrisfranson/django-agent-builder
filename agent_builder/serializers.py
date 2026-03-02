"""Serializers for agent_builder."""

from rest_framework import serializers

from .models import Agent, AgentChunk, Chunk


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chunk
        fields = ["id", "title", "content", "in_library", "user", "created_at", "updated_at"]
        read_only_fields = ["user", "created_at", "updated_at"]


class AgentChunkSerializer(serializers.ModelSerializer):
    chunk = ChunkSerializer(read_only=True)
    chunk_id = serializers.PrimaryKeyRelatedField(
        queryset=Chunk.objects.all(), source="chunk", write_only=True
    )

    class Meta:
        model = AgentChunk
        fields = ["id", "chunk", "chunk_id", "position", "is_enabled", "active_variant"]
        read_only_fields = ["active_variant"]


class AgentSerializer(serializers.ModelSerializer):
    agent_chunks = AgentChunkSerializer(many=True, read_only=True)

    class Meta:
        model = Agent
        fields = [
            "id",
            "name",
            "display_name",
            "source",
            "description",
            "model",
            "frontmatter",
            "is_active",
            "user",
            "agent_chunks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user", "created_at", "updated_at"]


class AgentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "name", "display_name", "source", "description", "model", "is_active"]
