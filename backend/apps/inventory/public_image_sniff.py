import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.evidence.image_validation import image_mime_from_bytes
from apps.evidence.storage import StorageUnavailable


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
        config=Config(
            signature_version=settings.AWS_S3_SIGNATURE_VERSION,
            s3={"addressing_style": settings.AWS_S3_ADDRESSING_STYLE},
        ),
    )


def sniff_is_valid_image(object_key):
    from apps.inventory.public_image_publication import InvalidImage, validate_snapshot
    from apps.object_publication import InvalidObjectSize, validate_existing

    try:
        return validate_existing(
            _client(), settings.PUBLIC_IMAGE_BUCKET, object_key,
            settings.PUBLIC_IMAGE_MAX_BYTES, validate_snapshot,
        ) is not None
    except (InvalidObjectSize, InvalidImage):
        return False
