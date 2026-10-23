from django.apps import AppConfig


def _seed_categories(sender, instance, created, **kwargs):
    # A tenant import brings the source's own categories (with their codes and letter
    # counters); seeding here first would collide with them on code.
    if created and instance.lifecycle_state == instance.LifecycleState.ACTIVE:
        from apps.inventory.categories import ensure_default_categories

        ensure_default_categories(instance)


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"

    def ready(self):
        from django.db.models.signals import post_save

        from apps.makerspaces.models import Makerspace

        post_save.connect(
            _seed_categories,
            sender=Makerspace,
            dispatch_uid="inventory.seed_categories_for_new_makerspace",
        )
