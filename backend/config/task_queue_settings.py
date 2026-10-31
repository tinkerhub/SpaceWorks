"""One target-owned default queue isolates work across destructive restores."""

from uuid import UUID

from django.core.exceptions import ImproperlyConfigured


def default_task_queue(generation):
    if generation == "":
        return "celery"
    try:
        canonical = str(UUID(generation))
    except (TypeError, ValueError, AttributeError):
        raise ImproperlyConfigured(
            "SPACEWORKS_TASK_GENERATION must be a canonical UUID or empty."
        ) from None
    if generation != canonical:
        raise ImproperlyConfigured(
            "SPACEWORKS_TASK_GENERATION must be a canonical UUID or empty."
        )
    return f"spaceworks-{canonical}"
