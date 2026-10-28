"""Audit entries for /control/ saves and deletes that no service already records.

Only the model, the object (as the audit target), its makerspace and the NAMES of the
changed fields are recorded -- never field values -- so a credential typed into a form
cannot reach the append-only log.
"""

from apps.audit import services as audit


def record_admin_save(actor, obj, *, created, changed_fields, makerspace=None, detail=None):
    meta = {
        "model": obj._meta.label_lower,
        "changed_fields": sorted(changed_fields),
        "detail": detail or {},
    }
    if created:
        audit.record(actor, "control.object_created", makerspace=makerspace, target=obj, meta=meta)
    else:
        audit.record(actor, "control.object_updated", makerspace=makerspace, target=obj, meta=meta)


class AdminAuditMixin:
    """Audit a ModelAdmin's add/change/delete. List it BEFORE SuperuserOnlyModelAdmin.

    `audit_secret_fields` are write-only inputs where blank means "keep": they count as
    changed only when a value was typed. `audit_exclude_fields` are audited elsewhere.
    """

    audit_secret_fields = ()
    audit_exclude_fields = ()

    def audit_makerspace(self, obj):
        from apps.makerspaces.models import Makerspace

        lookup = self.resolve_hidden_lookup()
        if not lookup:
            return None
        value = obj
        for part in lookup.split("__"):
            value = getattr(value, part, None)
            if value is None:
                return None
        return Makerspace.objects.filter(pk=value).first()

    def audit_changed_fields(self, form):
        cleaned = getattr(form, "cleaned_data", None) or {}
        return [
            name for name in form.changed_data
            if name not in self.audit_exclude_fields
            and (name not in self.audit_secret_fields or cleaned.get(name))
        ]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        changed = self.audit_changed_fields(form)
        if change and not changed:
            return
        record_admin_save(
            request.user, obj, created=not change, changed_fields=changed,
            makerspace=self.audit_makerspace(obj),
        )

    def delete_model(self, request, obj):
        self._audit_delete(request, obj)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self._audit_delete(request, obj)
        super().delete_queryset(request, queryset)

    def _audit_delete(self, request, obj):
        # Recorded first: the target's pk is gone once the row is deleted, and the admin
        # delete runs in one transaction, so a failed delete rolls this back too.
        audit.record(
            request.user,
            "control.object_deleted",
            makerspace=self.audit_makerspace(obj),
            target=obj,
            meta={"model": obj._meta.label_lower},
        )
