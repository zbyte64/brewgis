from django import forms
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic.edit import CreateView

from brewgis.workspace.models import Layer


class CreateLayerForm(forms.ModelForm):
    class Meta:
        model = Layer
        fields = ["workspace", "key", "name", "db_table", "layer_source", "description"]


@method_decorator(user_passes_test(lambda u: u.is_authenticated), name="dispatch")
class CreateLayerView(CreateView):
    form_class = CreateLayerForm
    template_name = "form.html"

    def form_valid(self, form: CreateLayerForm) -> HttpResponse:
        self.object = form.save()
        redirect_url = reverse(
            "workspace:workspace_map",
            args=[self.object.workspace.pk],
        )
        if self.request.htmx:  # type: ignore[attr-defined]
            response = HttpResponse()
            response["HX-Redirect"] = redirect_url
            return response
        return HttpResponseRedirect(redirect_url)

    def form_invalid(self, form: CreateLayerForm) -> HttpResponse:
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                "workspace/partials/_form_content.html",
                {"form": form, "view": self},
            )
        return super().form_invalid(form)
