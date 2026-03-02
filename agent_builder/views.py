from django.shortcuts import render
from django.views import View


class IndexView(View):
    template_name = "agent_builder/index.html"

    def get(self, request):
        context = {"content": "agent_builder Index"}
        return render(request, self.template_name, context)
