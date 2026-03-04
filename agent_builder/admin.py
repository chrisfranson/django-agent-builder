from django.contrib import admin

from .models import (
    Agent,
    AgentChunk,
    AgentInstruction,
    Chunk,
    ChunkVariant,
    ConfigFile,
    Instruction,
    Profile,
    Project,
    Revision,
    UserOptions,
)


class AgentChunkInline(admin.TabularInline):
    model = AgentChunk
    extra = 0
    fields = ["chunk", "position", "is_enabled"]
    ordering = ["position"]


class AgentInstructionInline(admin.TabularInline):
    model = AgentInstruction
    extra = 0
    fields = ["instruction", "injection_mode"]


@admin.action(description="Restore selected items")
def restore_selected(modeladmin, request, queryset):
    queryset.update(is_deleted=False, deleted_at=None)


class SoftDeleteAdminMixin:
    """Mixin for admin classes of SoftDeleteModel subclasses."""

    def get_queryset(self, request):
        return self.model.all_objects.all()


@admin.register(Agent)
class AgentAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "display_name",
        "source",
        "model",
        "is_active",
        "is_deleted",
        "updated_at",
    ]
    list_filter = ["source", "model", "is_active", "is_deleted"]
    search_fields = ["name", "display_name", "description"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AgentChunkInline, AgentInstructionInline]
    actions = [restore_selected]
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
class InstructionAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ["name", "display_name", "injection_mode", "user", "is_deleted", "updated_at"]
    list_filter = ["injection_mode", "is_deleted"]
    search_fields = ["name", "display_name", "content"]
    readonly_fields = ["created_at", "updated_at"]
    actions = [restore_selected]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "description", "user", "created_at"]
    search_fields = ["name", "description"]
    readonly_fields = ["snapshot", "created_at"]


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "content_type", "object_id", "user", "message", "created_at"]
    list_filter = ["content_type"]
    search_fields = ["message"]
    readonly_fields = ["content_type", "object_id", "content_snapshot", "user", "created_at"]


@admin.register(ConfigFile)
class ConfigFileAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ["filename", "path", "user", "is_deleted", "updated_at"]
    list_filter = ["is_deleted"]
    search_fields = ["filename", "path"]
    readonly_fields = ["created_at", "updated_at"]
    actions = [restore_selected]


@admin.register(Project)
class ProjectAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "path",
        "has_coderoo",
        "has_claude_config",
        "user",
        "is_deleted",
        "updated_at",
    ]
    list_filter = ["has_coderoo", "has_claude_config", "is_deleted"]
    search_fields = ["name", "path"]
    readonly_fields = ["discovered_at", "created_at", "updated_at"]
    actions = [restore_selected]


@admin.register(UserOptions)
class UserOptionsAdmin(admin.ModelAdmin):
    list_display = ["user", "active_tab", "agent_sub_tab", "updated_at"]
    list_filter = ["active_tab", "agent_sub_tab"]
    readonly_fields = ["created_at", "updated_at"]
