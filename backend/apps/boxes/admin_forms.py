from django import forms
from django.http import Http404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.boxes.models import Box
from apps.boxes.services import box_write_makerspace


class BoxAdminForm(forms.ModelForm):
    class Meta:
        model = Box
        fields = "__all__"

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor

    def clean(self):
        cleaned = super().clean()
        adding = self.instance._state.adding
        makerspace_id = (
            getattr(cleaned.get("makerspace"), "pk", None)
            if adding else self.instance.makerspace_id
        )
        if makerspace_id is None:
            return cleaned
        try:
            makerspace = box_write_makerspace(
                self.actor, makerspace_id, native=True, creation=adding,
            )
        except (PermissionDenied, Http404) as exc:
            raise forms.ValidationError("You cannot write a box in this makerspace.") from exc
        except ValidationError as exc:
            raise forms.ValidationError(str(exc.detail)) from exc
        if not adding:
            fresh = Box.objects.filter(pk=self.instance.pk, makerspace=makerspace).first()
            if fresh is None:
                raise forms.ValidationError("This box no longer exists.")
            # _post_clean constructs/saves this fresh instance, preserving excluded
            # fields and preventing Model.save's UPDATE-to-INSERT resurrection.
            self.instance = fresh
            if "parent" in self.fields and self.add_prefix("parent") not in self.data:
                cleaned["parent"] = fresh.parent
        self.instance.makerspace = makerspace
        if "makerspace" in self.fields:
            cleaned["makerspace"] = makerspace
        parent = cleaned.get("parent")
        if parent is not None:
            parent = Box.objects.filter(pk=parent.pk, makerspace=makerspace).first()
            if parent is None:
                self.add_error("parent", "Select an existing parent in this makerspace.")
            else:
                cleaned["parent"] = parent
        # Django's _post_clean still checks cycles, field bounds and duplicates.
        return cleaned
