"""Explicit storage ownership for warranty/receipt admin delete entry points."""
from contextlib import ExitStack

from django.db import transaction

from apps.object_storage_lifecycle import storage_lifecycle


class StorageDocumentDeleteAdminMixin:
    storage_makerspace_path = "makerspace_id"

    def _storage_tenant(self, obj):
        for part in self.storage_makerspace_path.split("__"):
            obj = getattr(obj, part)
        return int(obj)

    def delete_view(self, request, object_id, extra_context=None):
        # Django's inherited delete_view opens atomic before invoking delete_model.
        # Enter outside it, and retain ownership until its on_commit cleanup ends.
        obj = self.get_object(request, object_id)
        if request.method != "POST" or obj is None or not self.has_delete_permission(request, obj):
            return super().delete_view(request, object_id, extra_context)
        with storage_lifecycle(self._storage_tenant(obj)) as guard:
            request._storage_guard = guard
            return super().delete_view(request, object_id, extra_context)

    def storage_deleted_keys(self, obj):
        return ()

    def _release_images(self, tenant, keys, guard):
        from apps.inventory import public_image_storage
        from apps.makerspaces.models import Makerspace

        if not keys:
            return
        space = Makerspace.objects.get(pk=tenant)
        for key in dict.fromkeys(keys):
            if key:
                public_image_storage.release_public_image_on_commit(space, key, guard=guard)

    def delete_model(self, request, obj):
        guard = request._storage_guard
        guard.verify(self._storage_tenant(obj))
        tenant, keys = self._storage_tenant(obj), self.storage_deleted_keys(obj)
        obj._storage_guard = guard
        super().delete_model(request, obj)
        self._release_images(tenant, keys, guard)

    def delete_queryset(self, request, queryset):
        # Admin's delete-selected action has no outer transaction. Acquire all
        # distinct tenant guards before the single cascading queryset transaction.
        tenants = sorted({self._storage_tenant(obj) for obj in queryset})
        with ExitStack() as stack:
            guards = {tenant: stack.enter_context(storage_lifecycle(tenant)) for tenant in tenants}
            with transaction.atomic():
                for tenant, guard in guards.items():
                    subset = queryset.filter(**{self.storage_makerspace_path: tenant})
                    keys = [key for obj in subset for key in self.storage_deleted_keys(obj)]
                    subset._storage_guard = guard
                    guard.verify(tenant)
                    super().delete_queryset(request, subset)
                    self._release_images(tenant, keys, guard)
