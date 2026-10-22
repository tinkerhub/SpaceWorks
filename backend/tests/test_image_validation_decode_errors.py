"""M11: any Pillow decode failure on untrusted bytes means "invalid image", never a 500."""
import struct
import zlib
from io import BytesIO
from unittest.mock import Mock

from PIL import Image

from apps.evidence.image_validation import image_mime_from_bytes
from apps.inventory import public_image_sniff


def _png_bytes(size=(8, 8)):
    stream = BytesIO()
    Image.new("RGB", size, "white").save(stream, format="PNG")
    return stream.getvalue()


def _png_with_dimensions(width, height):
    """A PNG whose IHDR claims huge dimensions (with a valid chunk CRC)."""
    data = bytearray(_png_bytes())
    ihdr = struct.pack(">II", width, height) + bytes(data[24:29])
    data[16:29] = ihdr
    data[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)
    return bytes(data)


def test_valid_png_is_detected():
    assert image_mime_from_bytes(_png_bytes()) == "image/png"


def test_decompression_bomb_is_invalid_not_an_exception():
    assert image_mime_from_bytes(_png_with_dimensions(100_000, 100_000)) is None


def test_corrupt_data_chunk_checksum_is_invalid_not_an_exception():
    data = bytearray(_png_bytes())
    idat = data.index(b"IDAT")
    length = struct.unpack(">I", data[idat - 4:idat])[0]
    data[idat + 4 + length] ^= 0xFF  # break the IDAT CRC -> SyntaxError from verify()
    assert image_mime_from_bytes(bytes(data)) is None


def test_truncated_and_garbage_bytes_are_invalid():
    assert image_mime_from_bytes(_png_bytes()[:20]) is None
    assert image_mime_from_bytes(b"not an image at all") is None


def test_public_image_sniff_reports_a_bomb_as_invalid(monkeypatch, settings):
    body = Mock()
    body.read.return_value = _png_with_dimensions(100_000, 100_000)
    client = Mock()
    client.get_object.return_value = {"Body": body}
    monkeypatch.setattr(public_image_sniff, "_client", lambda: client)

    assert public_image_sniff.sniff_is_valid_image("items/1/bomb.png") is False
