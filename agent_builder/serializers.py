"""Serializers for agent_builder."""

from rest_framework import serializers

from .models import Agent, AgentChunk, AgentInstruction, Chunk, ChunkVariant, Instruction


class ChunkVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChunkVariant
        fields = ["id", "label", "content", "position"]


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


class InstructionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instruction
        fields = [
            "id",
            "name",
            "display_name",
            "content",
            "injection_mode",
            "user",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user", "created_at", "updated_at"]


class AgentInstructionSerializer(serializers.ModelSerializer):
    instruction = InstructionSerializer(read_only=True)
    instruction_id = serializers.PrimaryKeyRelatedField(
        queryset=Instruction.objects.all(), source="instruction", write_only=True
    )

    class Meta:
        model = AgentInstruction
        fields = ["id", "instruction", "instruction_id", "injection_mode"]


class AgentSerializer(serializers.ModelSerializer):
    agent_chunks = AgentChunkSerializer(many=True, read_only=True)
    agent_instructions = AgentInstructionSerializer(many=True, read_only=True)

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
            "agent_instructions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["user", "created_at", "updated_at"]


class AgentListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ["id", "name", "display_name", "source", "description", "model", "is_active"]
