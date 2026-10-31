import io
import zipfile

from rest_framework.exceptions import ValidationError

from apps.boxes.qr_render import render_qr_label_svg


def build_batch_zip(batch) -> bytes:
    """Export current same-makerspace labels; omit moved QRs and reject empty output."""
    items = [
        item for item in batch.items.select_related("qr_code")
        if item.qr_code.makerspace_id == batch.makerspace_id
    ]
    if not items:
        raise ValidationError("This batch has no printable QR labels available.")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(items, start=1):
            label = item.label_text
            svg = render_qr_label_svg(item.qr_code.payload, label)
            archive.writestr(f"{index:02d}-{_sanitize_label(label)}.svg", svg)
    return buffer.getvalue()


def _sanitize_label(label):
    sanitized = "".join(char.lower() if char.isalnum() or char in "-_" else "-" for char in label)
    return sanitized or "qr"
