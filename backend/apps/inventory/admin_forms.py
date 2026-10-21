from django import forms

from apps.inventory.admin_image_uploads import PublicImageAdminForm
from apps.inventory.models import InventoryProduct


class InventoryQuantityAdjustmentForm(forms.Form):
    delta_available = forms.IntegerField(required=True)
    delta_damaged = forms.IntegerField(required=True)
    delta_lost = forms.IntegerField(required=True)
    reason = forms.CharField(required=True, widget=forms.Textarea)


class NeedsFixQuantityForm(forms.Form):
    quantity = forms.IntegerField(required=True, min_value=1)


class InventoryProductAdminForm(PublicImageAdminForm):
    class Meta:
        model = InventoryProduct
        fields = "__all__"
