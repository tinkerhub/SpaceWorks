from django import forms
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.procurement import access
from apps.procurement.models import ToBuyItem


class ToBuyItemAdminForm(forms.ModelForm):
    class Meta:
        model = ToBuyItem
        fields = "__all__"

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor

    def clean(self):
        cleaned = super().clean()
        makerspace = cleaned.get("makerspace") if not self.instance.pk else self.instance.makerspace
        kind = cleaned.get("kind") if not self.instance.pk else self.instance.kind
        if makerspace is None or not kind or "machine_type" not in cleaned:
            return cleaned
        machine_type = cleaned["machine_type"]
        try:
            access.validate_machine_type(self.actor, makerspace.pk, kind, machine_type)
            access.validate_machine_type_provenance(self.instance, machine_type)
        except DRFValidationError as exc:
            raise forms.ValidationError(exc.detail) from exc
        return cleaned
