from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.plumbing import normalize_result_object, sanitize_result_object
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView


class IndexView(LoginRequiredMixin, TemplateView):
    template_name = "agent_builder/index.html"


class FilteredSchemaGenerator(SchemaGenerator):
    def get_schema(self, request=None, public=False):
        """Generate an OpenAPI schema for just the agent_builder app."""
        import json
        import re as re_mod

        result = super().get_schema(request, public)

        filtered_paths = {}
        for path, path_data in result["paths"].items():
            if "/agent-builder/" in path:
                filtered_paths[path] = path_data
        result["paths"] = filtered_paths

        if "components" in result and "schemas" in result["components"]:
            paths_json = json.dumps(filtered_paths)
            schema_refs = set(re_mod.findall(r"#/components/schemas/(\w+)", paths_json))
            filtered_schemas = {}
            for schema_name in schema_refs:
                if schema_name in result["components"]["schemas"]:
                    filtered_schemas[schema_name] = result["components"]["schemas"][schema_name]
                    schema_json = json.dumps(result["components"]["schemas"][schema_name])
                    nested_refs = set(re_mod.findall(r"#/components/schemas/(\w+)", schema_json))
                    for nested_ref in nested_refs:
                        if nested_ref in result["components"]["schemas"]:
                            filtered_schemas[nested_ref] = result["components"]["schemas"][
                                nested_ref
                            ]
            result["components"]["schemas"] = filtered_schemas

        return sanitize_result_object(normalize_result_object(result))


@extend_schema(exclude=True)
class CustomSpectacularAPIView(SpectacularAPIView):
    generator_class = FilteredSchemaGenerator
