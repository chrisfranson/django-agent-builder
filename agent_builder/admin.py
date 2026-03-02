from django.contrib import admin

from .models import Agent, AgentChunk, AgentInstruction, Chunk, ChunkVariant, Instruction


class AgentChunkInline(admin.TabularInline):
    model = AgentChunk
    extra = 0
    fields = ["chunk", "position", "is_enabled"]
    ordering = ["position"]


class AgentInstructionInline(admin.TabularInline):
    model = AgentInstruction
    extra = 0
    fields = ["instruction", "injection_mode"]


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ["name", "display_name", "source", "model", "is_active", "updated_at"]
    list_filter = ["source", "model", "is_active"]
    search_fields = ["name", "display_name", "description"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AgentChunkInline, AgentInstructionInline]
    fieldsets = (
        ("Agent", {"fields": ("name", "display_name", "source", "model", "is_active", "user")}),
        ("Content", {"fields": ("description", "frontmatter")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


class ChunkVariantInline(admin.TabularInline):
    model = ChunkVariant
    extra = 0
    fields = ["label", "content", "position"]
    ordering = ["position"]


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ["__str__", "in_library", "user", "updated_at"]
    list_filter = ["in_library"]
    search_fields = ["title", "content"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [ChunkVariantInline]


@admin.register(Instruction)
class InstructionAdmin(admin.ModelAdmin):
    list_display = ["name", "display_name", "injection_mode", "user", "updated_at"]
    list_filter = ["injection_mode"]
    search_fields = ["name", "display_name", "content"]
    readonly_fields = ["created_at", "updated_at"]
