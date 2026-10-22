from io import BytesIO

from PIL import Image


IMAGE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


def image_mime_from_bytes(data):
    """Return the MIME type of an allowed, decodable image, else None.

    Untrusted bytes can make Pillow raise far more than OSError: DecompressionBombError
    (a plain Exception subclass) for oversized dimensions, SyntaxError from a corrupt PNG
    chunk in verify(), ValueError/struct.error/EOFError from truncated headers. Every
    one of them means "not a valid image" -- none may escape as a 500.
    """
    try:
        image = Image.open(BytesIO(data))
        detected = IMAGE_MIME_BY_FORMAT.get(image.format)
        image.verify()
    except Exception:  # noqa: BLE001 - any decoder failure on untrusted input is invalid
        return None
    return detected
