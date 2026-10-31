"""Clear-first raw cascades and explicit guard-owned profile deletion."""
from threading import Event
from unittest.mock import Mock

import pytest
from django.contrib import admin
from django.db import connection, transaction
from django.db.models.deletion import Collector, ProtectedError
from django.test import RequestFactory

from apps.accounts.models import User
from apps.inventory import public_image_storage as storage
from apps.makerspaces import profile_images
from apps.makerspaces.models import MakerspaceMembership, MemberProfile, MemberProject
from apps.makerspaces.profile_delete_guards import ProfileImageDeleteProtected, CLEAR_IMAGES_FIRST
from apps.makerspaces.module_purge_collectors import membership_delete
from apps.makerspaces.purge_cleanup import synchronous_cleanup
from apps.makerspaces.purge_locks import purge_boundary
from tests.makerspaces.module_cleanup_support import module_store
from apps.makerspaces.purge_storage import bucket_name
from apps.object_storage_lifecycle import storage_lifecycle
from tests.atomic_publication.domain import bind_store, setup_machine
from tests.atomic_publication.store import png
from tests.atomic_publication.threading import workers

pytestmark = pytest.mark.django_db(transaction=True)


def case(monkeypatch):
    space, actor, _machine = setup_machine("atomic-profile-cascade", monkeypatch)
    membership = MakerspaceMembership.objects.get(user=actor, makerspace=space)
    profile = MemberProfile.objects.create(membership=membership)
    project = MemberProject.objects.create(profile=profile, title="A project")
    return space, actor, membership, profile, project


@pytest.mark.parametrize("target", ["user", "membership", "profile", "project"])
@pytest.mark.parametrize("image", ["avatar", "project"])
def test_raw_image_bearing_cascade_refused_without_guard_acquire_or_s3(target, image, monkeypatch):
    space, actor, membership, profile, project = case(monkeypatch)
    if image == "avatar":
        MemberProfile.objects.filter(pk=profile.pk).update(avatar_key=f"member/{space.pk}/avatar.png")
        if target == "project":
            MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/project.png")
    else:
        MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/project.png")
    acquire = Mock(side_effect=AssertionError("pre_delete must never acquire a storage guard"))
    monkeypatch.setattr("apps.object_storage_lifecycle._new_lock_connection", acquire)
    store = bind_store(monkeypatch, storage)
    instance = {"user": actor, "membership": membership, "profile": profile, "project": project}[target]
    with pytest.raises(ProfileImageDeleteProtected, match="Clear member profile"):
        instance.delete()
    assert MemberProfile.objects.filter(pk=profile.pk).exists()
    assert MemberProject.objects.filter(pk=project.pk).exists()
    assert User.objects.filter(pk=actor.pk).exists()
    assert store.calls == []
    acquire.assert_not_called()


@pytest.mark.parametrize("target", ["user", "membership", "profile", "project"])
def test_empty_image_cascades_need_no_storage_guard_or_io(target, monkeypatch):
    _space, actor, membership, profile, project = case(monkeypatch)
    store = bind_store(monkeypatch, storage)
    monkeypatch.setattr("apps.object_storage_lifecycle._new_lock_connection", Mock(side_effect=AssertionError("empty cascade needs no storage")))
    instance = {"user": actor, "membership": membership, "profile": profile, "project": project}[target]
    model, pk = type(instance), instance.pk
    instance.delete()
    assert not model.objects.filter(pk=pk).exists() and store.calls == []


@pytest.mark.parametrize("guard_kind", ["wrong-tenant", "released", "impostor"])
def test_image_cascade_rejects_invalid_explicit_guard_origin(guard_kind, monkeypatch):
    space, _actor, _membership, profile, project = case(monkeypatch)
    MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/project.png")
    from tests.return_helpers import make_space
    tenant = make_space("atomic-foreign-guard").pk if guard_kind == "wrong-tenant" else space.pk
    with storage_lifecycle(tenant) as owned:
        if guard_kind == "released":
            owned.close()
        origin = MemberProfile.objects.filter(pk=profile.pk)
        origin._storage_guard = Mock() if guard_kind == "impostor" else owned
        with pytest.raises(ProfileImageDeleteProtected):
            origin.delete()
    assert MemberProject.objects.filter(pk=project.pk).exists()


def test_user_admin_preflight_clear_first_preserves_other_protect_results(monkeypatch):
    space, actor, _membership, profile, project = case(monkeypatch)
    MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/project.png")
    request = RequestFactory().get("/control/accounts/user/")
    request.user = User.objects.create_superuser(username="atomic-global-admin", email="admin@example.test", password="unused")
    model_admin = admin.site._registry[User]
    _deleted, _counts, _perms, protected = model_admin.get_deleted_objects([actor], request)
    assert CLEAR_IMAGES_FIRST in protected
    # Add a genuine PROTECT relationship, then verify the existing FK protection
    # is still surfaced along with the image-specific refusal.
    from apps.evidence.models import EvidencePhoto
    EvidencePhoto.objects.create(makerspace=space, uploaded_by=actor,
                                 evidence_type="issue", object_key="private/protected")
    with pytest.raises(ProtectedError):
        actor.delete()
    _deleted, _counts, _perms, protected = model_admin.get_deleted_objects([actor], request)
    assert CLEAR_IMAGES_FIRST in protected and len(protected) > 1


def test_collector_stale_empty_snapshot_rechecks_locked_rows_after_raced_attachment(monkeypatch):
    space, actor, _membership, profile, project = case(monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"member/{space.pk}/raced.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    collected, proceed = Event(), Event()
    original_delete = Collector.delete
    def pause_collected(collector):
        if isinstance(collector.origin, User) and collector.origin.pk == actor.pk:
            collected.set()
            assert proceed.wait(4)
        return original_delete(collector)
    monkeypatch.setattr(Collector, "delete", pause_collected)
    with workers() as spawn:
        def raw_delete():
            with pytest.raises(ProfileImageDeleteProtected):
                User.objects.get(pk=actor.pk).delete()
        deleted = spawn(raw_delete)
        assert collected.wait(4)
        try:
            profile_images.set_project_image(profile, project, key)
        finally:
            proceed.set()
        deleted.result(timeout=8)
    project.refresh_from_db()
    assert User.objects.filter(pk=actor.pk).exists() and project.image_key == key
    assert store.objects[key][0] == data


@pytest.mark.parametrize("model_name", ["profile", "project"])
def test_guard_owned_admin_bulk_delete_releases_after_commit_with_profile_project_order(model_name, monkeypatch):
    space, actor, _membership, profile, project = case(monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"member/{space.pk}/admin-delete.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    profile_images.set_project_image(profile, project, key)
    request = RequestFactory().post("/control/")
    request.user = actor
    target = profile if model_name == "profile" else project
    model, pk = type(target), target.pk
    locked_tables = []
    def capture(execute, sql, params, many, context):
        if "FOR UPDATE" in sql:
            if 'FROM "makerspaces_memberprofile"' in sql:
                locked_tables.append("profile")
            elif 'FROM "makerspaces_memberproject"' in sql:
                locked_tables.append("project")
        return execute(sql, params, many, context)
    with connection.execute_wrapper(capture):
        admin.site._registry[model].delete_queryset(request, model.objects.filter(pk=pk))
    assert not model.objects.filter(pk=pk).exists() and key not in store.objects
    space.refresh_from_db()
    assert space.storage_bytes_used == 0
    assert locked_tables.index("profile") < locked_tables.index("project")


def test_membership_module_collector_marks_queryset_origin_with_verified_guard(monkeypatch):
    space, _actor, _membership, profile, project = case(monkeypatch)
    MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/module.png")
    store = bind_store(monkeypatch, storage)
    with storage_lifecycle(space.pk) as guard, transaction.atomic(), connection.cursor() as cursor:
        membership_delete(space, cursor, guard=guard)
    assert not MemberProfile.objects.filter(pk=profile.pk).exists()
    assert not MemberProject.objects.filter(pk=project.pk).exists()
    assert store.calls == [], "collector hooks must not do S3 inside deletion atomic"


def test_full_tenant_cleanup_exemption_precedes_stale_guard_verification(monkeypatch, module_store):
    space, _actor, _membership, profile, project = case(monkeypatch)
    MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/purge.png")
    with storage_lifecycle(space.pk) as released:
        pass
    origin = MemberProfile.objects.filter(pk=profile.pk)
    origin._storage_guard = released
    with purge_boundary(space.pk, all_tenants=True) as verify, synchronous_cleanup(space.pk, verify=verify):
        origin.delete()
    assert not MemberProject.objects.filter(pk=project.pk).exists()


def test_actual_membership_module_purge_deletes_profile_images_and_releases_quota(monkeypatch, settings, module_store):
    from apps.makerspaces.module_purge import purge_module
    settings.MANAGED_POSTGRES = True
    space, actor, _membership, profile, project = case(monkeypatch)
    store = bind_store(monkeypatch, storage)
    key, data = f"member/{space.pk}/{'a' * 32}.png", png()
    store.seed(storage.staging_key(key), data, "image/png")
    profile_images.set_project_image(profile, project, key)
    module_store.put(bucket_name("public_image"), key, data)
    module_store.put(bucket_name("public_image"), f"staging/{key}", data)
    actor.is_superuser = True
    actor.is_staff = True
    actor.save(update_fields=["is_superuser", "is_staff"])
    space.enabled_modules = [key for key in space.enabled_modules if key != "membership"]
    space.save(update_fields=["enabled_modules"])
    receipt, counts = purge_module(space, "membership", actor)
    assert receipt.graph_purged_at and counts
    assert not MemberProfile.objects.filter(pk=profile.pk).exists()
    assert not MemberProject.objects.filter(pk=project.pk).exists()
    assert not module_store.has_key(bucket_name("public_image"), key)
    assert not module_store.has_key(bucket_name("public_image"), f"staging/{key}")
    space.refresh_from_db()
    assert space.storage_bytes_used == 0


def test_verified_guard_owned_profile_instance_delete_uses_explicit_origin_without_hook_io(monkeypatch):
    space, _actor, _membership, profile, project = case(monkeypatch)
    MemberProject.objects.filter(pk=project.pk).update(image_key=f"member/{space.pk}/owned.png")
    store = bind_store(monkeypatch, storage)
    with storage_lifecycle(space.pk) as guard:
        profile._storage_guard = guard
        profile.delete()
    assert not MemberProject.objects.filter(pk=project.pk).exists()
    assert store.calls == [], "pre_delete owns validation, not object cleanup"
