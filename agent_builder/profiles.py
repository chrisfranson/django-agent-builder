"""Profile snapshot capture and restore utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import Agent, AgentChunk, AgentInstruction, Chunk, ChunkVariant, Instruction

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser


def capture_snapshot(user: AbstractUser) -> dict:
    """Capture the full system state for a user as a JSON-serializable dict."""
    agents_data = []
    for agent in Agent.objects.filter(user=user).prefetch_related(
        "agent_chunks__chunk__variants",
        "agent_instructions__instruction",
    ):
        agent_chunks = []
        for ac in agent.agent_chunks.all():
            chunk_data = {
                "title": ac.chunk.title,
                "content": ac.chunk.content,
                "in_library": ac.chunk.in_library,
                "position": ac.position,
                "is_enabled": ac.is_enabled,
                "active_variant": ac.active_variant.label if ac.active_variant else None,
                "variants": [
                    {"label": v.label, "content": v.content, "position": v.position}
                    for v in ac.chunk.variants.all()
                ],
            }
            agent_chunks.append(chunk_data)

        agent_instructions = []
        for ai in agent.agent_instructions.all():
            agent_instructions.append(
                {
                    "name": ai.instruction.name,
                    "display_name": ai.instruction.display_name,
                    "content": ai.instruction.content,
                    "injection_mode": ai.injection_mode or ai.instruction.injection_mode,
                }
            )

        agents_data.append(
            {
                "name": agent.name,
                "display_name": agent.display_name,
                "source": agent.source,
                "description": agent.description,
                "model": agent.model,
                "frontmatter": agent.frontmatter,
                "is_active": agent.is_active,
                "chunks": agent_chunks,
                "instructions": agent_instructions,
            }
        )

    # Standalone chunks (all user chunks, including those not attached to agents)
    chunks_data = []
    for chunk in Chunk.objects.filter(user=user):
        chunks_data.append(
            {
                "title": chunk.title,
                "content": chunk.content,
                "in_library": chunk.in_library,
                "variants": [
                    {"label": v.label, "content": v.content, "position": v.position}
                    for v in chunk.variants.all()
                ],
            }
        )

    # Standalone instructions
    instructions_data = []
    for inst in Instruction.objects.filter(user=user):
        instructions_data.append(
            {
                "name": inst.name,
                "display_name": inst.display_name,
                "content": inst.content,
                "injection_mode": inst.injection_mode,
            }
        )

    return {
        "agents": agents_data,
        "chunks": chunks_data,
        "instructions": instructions_data,
    }


def restore_snapshot(snapshot: dict, user: AbstractUser) -> None:
    """Restore a user's system state from a snapshot.

    Updates existing objects by name/title, creates missing ones.
    Does NOT delete objects not in the snapshot.
    """
    # Restore standalone instructions
    for inst_data in snapshot.get("instructions", []):
        Instruction.objects.update_or_create(
            user=user,
            name=inst_data["name"],
            defaults={
                "display_name": inst_data["display_name"],
                "content": inst_data["content"],
                "injection_mode": inst_data.get("injection_mode", "on_demand"),
            },
        )

    # Restore standalone chunks
    chunk_map = {}  # title -> Chunk for linking
    for chunk_data in snapshot.get("chunks", []):
        chunk, _ = Chunk.objects.update_or_create(
            user=user,
            title=chunk_data["title"],
            defaults={
                "content": chunk_data["content"],
                "in_library": chunk_data.get("in_library", False),
            },
        )
        chunk_map[chunk.title] = chunk
        # Restore variants
        for v_data in chunk_data.get("variants", []):
            ChunkVariant.objects.update_or_create(
                chunk=chunk,
                label=v_data["label"],
                defaults={
                    "content": v_data["content"],
                    "position": v_data.get("position", 0),
                },
            )

    # Restore agents
    for agent_data in snapshot.get("agents", []):
        agent, _ = Agent.objects.update_or_create(
            user=user,
            name=agent_data["name"],
            defaults={
                "display_name": agent_data["display_name"],
                "source": agent_data["source"],
                "description": agent_data.get("description", ""),
                "model": agent_data.get("model", "sonnet"),
                "frontmatter": agent_data.get("frontmatter", ""),
                "is_active": agent_data.get("is_active", True),
            },
        )

        # Restore agent-chunk links
        agent.agent_chunks.all().delete()
        for chunk_data in agent_data.get("chunks", []):
            chunk, _ = Chunk.objects.update_or_create(
                user=user,
                title=chunk_data["title"],
                defaults={
                    "content": chunk_data["content"],
                    "in_library": chunk_data.get("in_library", False),
                },
            )
            # Restore variants
            for v_data in chunk_data.get("variants", []):
                ChunkVariant.objects.update_or_create(
                    chunk=chunk,
                    label=v_data["label"],
                    defaults={
                        "content": v_data["content"],
                        "position": v_data.get("position", 0),
                    },
                )
            # Find active variant
            active_variant = None
            if chunk_data.get("active_variant"):
                active_variant = ChunkVariant.objects.filter(
                    chunk=chunk, label=chunk_data["active_variant"]
                ).first()

            AgentChunk.objects.create(
                agent=agent,
                chunk=chunk,
                position=chunk_data.get("position", 0),
                is_enabled=chunk_data.get("is_enabled", True),
                active_variant=active_variant,
            )

        # Restore agent-instruction links
        agent.agent_instructions.all().delete()
        for inst_data in agent_data.get("instructions", []):
            instruction, _ = Instruction.objects.update_or_create(
                user=user,
                name=inst_data["name"],
                defaults={
                    "display_name": inst_data["display_name"],
                    "content": inst_data["content"],
                    "injection_mode": inst_data.get("injection_mode", "on_demand"),
                },
            )
            AgentInstruction.objects.create(
                agent=agent,
                instruction=instruction,
            )
