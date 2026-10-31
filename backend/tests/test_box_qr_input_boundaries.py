import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode
from apps.boxes.serializers import CreateBoxQrSerializer
from tests.return_helpers import authenticated_client, make_box, make_member, make_space

pytestmark = pytest.mark.django_db


@pytest.fixture
def box_qr_context(settings):
    # Legitimate self-host infrastructure; keep all middleware enabled.
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    settings.PLATFORM_ORIGIN_HOST = ""
    settings.INFRA_HOSTS = {"localhost"}
    settings.ALLOWED_HOSTS = ["localhost"]
    makerspace = make_space("box-input-boundary")
    actor = make_member("box-input-manager", makerspace)
    foreign_space = make_space("box-input-foreign")
    foreign_box = make_box(foreign_space, label="Existing foreign box")
    QrCode.objects.create(
        makerspace=foreign_space,
        payload=foreign_box.code,
        target_type=QrCode.TargetType.BOX,
        target_id=foreign_box.id,
    )
    return makerspace, actor, authenticated_client(actor)


@pytest.mark.parametrize("field", ["label", "location"])
def test_box_qr_rejects_201_characters_without_writes(box_qr_context, field):
    makerspace, _, client = box_qr_context
    body = {"makerspace_id": makerspace.id, "label": "Valid box", "location": "Shelf"}
    body[field] = "x" * 201
    models = (Box, QrCode, AuditLog)
    before = [list(model.objects.order_by("pk").values()) for model in models]

    response = client.post(
        "/api/v1/admin/qr/boxes", body, format="json", HTTP_HOST="localhost"
    )

    assert response.status_code == 400
    assert set(response.data) == {field}
    assert len(response.data[field]) == 1
    assert response.data[field][0].code == "max_length"
    assert [list(model.objects.order_by("pk").values()) for model in models] == before


def test_box_qr_accepts_exactly_200_characters_with_scoped_qr_and_audit(box_qr_context):
    makerspace, actor, client = box_qr_context
    # Distinct non-whitespace strings expose swapping or silent truncation.
    label = "L" + "a" * 198 + "Z"
    location = "S" + "b" * 198 + "Y"
    serializer = CreateBoxQrSerializer()
    for field in ("label", "location"):
        assert serializer.fields[field].max_length == 200
        assert Box._meta.get_field(field).max_length == 200
    models = (Box, QrCode, AuditLog)
    before = [model.objects.count() for model in models]

    response = client.post(
        "/api/v1/admin/qr/boxes",
        {"makerspace_id": makerspace.id, "label": label, "location": location},
        format="json",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 201
    assert [model.objects.count() for model in models] == [count + 1 for count in before]
    box = Box.objects.get(pk=response.data["id"])
    assert box.makerspace_id == response.data["makerspace"] == makerspace.id
    assert box.label == response.data["label"] == label
    assert box.location == response.data["location"] == location
    assert box.parent_id is None
    qr = QrCode.objects.get(pk=response.data["qr_code_id"])
    assert qr.makerspace_id == makerspace.id
    assert qr.target_type == QrCode.TargetType.BOX
    assert qr.target_id == box.id
    assert qr.payload == box.code == response.data["code"]
    assert qr.status == QrCode.Status.ACTIVE
    assert qr.created_by_id == actor.id
    assert QrCode.objects.filter(
        makerspace=makerspace, target_type=QrCode.TargetType.BOX, target_id=box.id
    ).count() == 1
    event = AuditLog.objects.get(action="qr.box_created", target_id=str(box.id))
    assert event.target_type == "boxes.box"
    assert event.makerspace_id == makerspace.id
    assert event.actor_id == actor.id
