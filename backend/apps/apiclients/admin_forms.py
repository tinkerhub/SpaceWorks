from django import forms
from unfold.widgets import (
    UnfoldAdminEmailInputWidget,
    UnfoldAdminIntegerFieldWidget,
    UnfoldAdminPasswordWidget,
    UnfoldAdminTextInputWidget,
    UnfoldBooleanSwitchWidget,
)

from apps.apiclients.models import ApiClient
from apps.integrations.smtp_validation import validate_smtp_settings


class ApiClientAdminForm(forms.ModelForm):
    telegram_group_chat_id = forms.CharField(
        required=False, widget=UnfoldAdminTextInputWidget
    )
    telegram_bot_token = forms.CharField(
        required=False, widget=UnfoldAdminPasswordWidget(render_value=False)
    )
    smtp_host = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    smtp_port = forms.IntegerField(
        required=False, min_value=1, widget=UnfoldAdminIntegerFieldWidget
    )
    smtp_username = forms.CharField(required=False, widget=UnfoldAdminTextInputWidget)
    smtp_password = forms.CharField(
        required=False, widget=UnfoldAdminPasswordWidget(render_value=False)
    )
    smtp_use_tls = forms.BooleanField(required=False, widget=UnfoldBooleanSwitchWidget)
    smtp_use_ssl = forms.BooleanField(required=False, widget=UnfoldBooleanSwitchWidget)
    smtp_from_email = forms.EmailField(required=False, widget=UnfoldAdminEmailInputWidget)

    class Meta:
        model = ApiClient
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        makerspace = getattr(self.instance, "makerspace", None)
        if makerspace:
            for field in (
                "telegram_group_chat_id",
                "smtp_host",
                "smtp_port",
                "smtp_username",
                "smtp_use_tls",
                "smtp_use_ssl",
                "smtp_from_email",
            ):
                self.fields[field].initial = getattr(makerspace, field)
            self.fields["telegram_bot_token"].help_text = (
                "Token is already set. Leave blank to keep it."
                if makerspace.telegram_bot_token
                else "Enter bot token."
            )
            self.fields["smtp_password"].help_text = (
                "SMTP password is already set. Leave blank to keep it."
                if makerspace.smtp_password
                else "Enter SMTP password."
            )

    def clean(self):
        cleaned = super().clean()
        # Validate what will be stored: only changed settings are written (see
        # save_makerspace_settings), so an untouched host or port is the target space's own.
        # Checking the form's blank host instead let a lone port skip the allowlist.
        attrs = {}
        if "smtp_host" in self.changed_data:
            attrs["smtp_host"] = cleaned.get("smtp_host") or ""
        if "smtp_port" in self.changed_data:
            attrs["smtp_port"] = cleaned.get("smtp_port") or 587
        validate_smtp_settings(attrs, cleaned.get("makerspace"))
        return cleaned


_TEXT_SETTINGS = ("telegram_group_chat_id", "smtp_host", "smtp_username", "smtp_from_email")


def save_makerspace_settings(makerspace, form):
    """Write only the makerspace settings the superadmin actually changed in this form.

    Writing every field used to blank the space's SMTP host, sender and chat id whenever
    a client was ADDED, because the form has no makerspace to prefill from yet.
    """
    if makerspace is None:
        return
    changed = set(form.changed_data)
    updates = []
    for field in _TEXT_SETTINGS:
        if field in changed:
            setattr(makerspace, field, form.cleaned_data.get(field) or "")
            updates.append(field)
    if form.cleaned_data.get("telegram_bot_token"):
        makerspace.set_telegram_bot_token(form.cleaned_data["telegram_bot_token"])
        updates.append("telegram_bot_token")
    if form.cleaned_data.get("smtp_password"):
        makerspace.set_smtp_password(form.cleaned_data["smtp_password"])
        updates.append("smtp_password")
    if "smtp_port" in changed:
        makerspace.smtp_port = form.cleaned_data.get("smtp_port") or 587
        updates.append("smtp_port")
    for field in ("smtp_use_tls", "smtp_use_ssl"):
        if field in changed:
            setattr(makerspace, field, bool(form.cleaned_data.get(field)))
            updates.append(field)
    if updates:
        makerspace.save(update_fields=[*updates, "updated_at"])
