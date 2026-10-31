"""Refuse image-bearing profile cascades without explicit cleanup ownership."""
from django.db.models.deletion import ProtectedError

from apps.evidence.storage import StorageUnavailable
from apps.makerspaces.models import MemberProfile, MemberProject
from apps.makerspaces.purge_cleanup import owns_cleanup
from apps.object_storage_lifecycle import StorageGuard

CLEAR_IMAGES_FIRST = (
    "Clear member profile avatars and project images before deleting this user, "
    "membership, profile or project."
)


class ProfileImageDeleteProtected(ProtectedError):
    """A focused refusal that admin can display without hiding other PROTECT errors."""


def _refuse(instance):
    raise ProfileImageDeleteProtected(CLEAR_IMAGES_FIRST, [instance])


def _check_owner(instance, origin, makerspace_id, has_images):
    # Full-tenant cleanup has exclusive graph ownership and must be checked before
    # consulting a possibly stale ordinary storage guard.
    if owns_cleanup(makerspace_id) or not has_images:
        return
    for owner in (origin, instance):
        guard = getattr(owner, "_storage_guard", None)
        if isinstance(guard, StorageGuard):
            try:
                guard.verify(makerspace_id)
            except StorageUnavailable:
                _refuse(instance)
            return
    _refuse(instance)


def protect_profile_images(sender, instance, using, origin=None, **kwargs):
    profiles = MemberProfile.objects.using(using)
    tenant = profiles.filter(pk=instance.pk).values_list(
        "membership__makerspace_id", flat=True,
    ).first()
    if tenant is None or owns_cleanup(tenant):
        return
    profile = profiles.select_for_update().filter(pk=instance.pk).first()
    if profile is None:
        return
    # Attachment locks the profile before its project. Follow that same order,
    # re-reading keys instead of trusting the collector's earlier model snapshots.
    projects = list(MemberProject.objects.using(using).select_for_update().filter(
        profile_id=profile.pk,
    ).order_by("pk"))
    tenant = profile.membership.makerspace_id
    _check_owner(instance, origin, tenant, bool(
        profile.avatar_key or any(project.image_key for project in projects)
    ))


def protect_project_image(sender, instance, using, origin=None, **kwargs):
    projects = MemberProject.objects.using(using)
    # Read the CURRENT parent before locking anything. A moved project must not
    # make us take a second parent lock while already holding the project lock.
    parent_id = projects.filter(pk=instance.pk).values_list("profile_id", flat=True).first()
    if parent_id is None:
        return
    profiles = MemberProfile.objects.using(using)
    tenant = profiles.filter(pk=parent_id).values_list(
        "membership__makerspace_id", flat=True,
    ).first()
    if tenant is not None and owns_cleanup(tenant):
        return
    profile = profiles.select_for_update().filter(pk=parent_id).first()
    project = projects.select_for_update().filter(pk=instance.pk).first()
    if project is None:
        return
    if profile is None or project.profile_id != parent_id:
        _refuse(instance)
    _check_owner(instance, origin, profile.membership.makerspace_id, bool(project.image_key))
