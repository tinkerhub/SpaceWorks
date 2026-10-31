import io
import zipfile

from apps.boxes.qr_render import render_qr_label_svg
from tests.qr_batch_projection_safety.helpers import collect


NO_PRINTABLE = "This batch has no printable QR labels available."


def owned_pair(lab):
    # Insertion order differs from print order, and sort_order has gaps.
    later = collect(lab, label="Owned / Drill", order=30)
    earlier = collect(lab, label="Owned_2!", order=10)
    return earlier, later


def assert_owned_zip(response, lab, owned):
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f'attachment; filename="qr-batch-{lab.batch.pk}.zip"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        # Exact members prove foreign labels are omitted and numbering is compact.
        names = ["01-owned_2-.svg", "02-owned---drill.svg"]
        assert archive.namelist() == names
        assert len(archive.infolist()) == len(owned) == 2
        assert archive.testzip() is None
        for name, collected in zip(names, owned, strict=True):
            assert archive.read(name) == render_qr_label_svg(
                collected.code.payload, collected.item.label_text,
            ).encode("utf-8")
