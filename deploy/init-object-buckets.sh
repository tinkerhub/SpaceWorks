#!/bin/sh
# Shared by development and production createbuckets services.
set -eu

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
: "${AWS_STORAGE_BUCKET_NAME:?AWS_STORAGE_BUCKET_NAME is required}"
: "${PUBLIC_IMAGE_BUCKET:?PUBLIC_IMAGE_BUCKET is required}"

if [ "$AWS_STORAGE_BUCKET_NAME" = "$PUBLIC_IMAGE_BUCKET" ]; then
    echo "Private and public storage bucket names must be different." >&2
    exit 1
fi
# Restrict the interpolated ARN to bucket-name characters; no JSON escaping needed.
case "$PUBLIC_IMAGE_BUCKET" in
    *[!a-z0-9.-]*)
        echo "Public storage bucket name contains invalid characters." >&2
        exit 1
        ;;
esac
if [ "${#PUBLIC_IMAGE_BUCKET}" -lt 3 ] || [ "${#PUBLIC_IMAGE_BUCKET}" -gt 63 ]; then
    echo "Public storage bucket name must contain 3 to 63 characters." >&2
    exit 1
fi

until mc alias set -- local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
    sleep 1
done
mc mb --ignore-existing "local/$AWS_STORAGE_BUCKET_NAME"
mc version enable "local/$AWS_STORAGE_BUCKET_NAME"
mc anonymous set none "local/$AWS_STORAGE_BUCKET_NAME"
mc mb --ignore-existing "local/$PUBLIC_IMAGE_BUCKET"
mc version enable "local/$PUBLIC_IMAGE_BUCKET"

policy_file=$(mktemp)
trap 'rm -f "$policy_file"' 0
trap 'exit 1' HUP INT TERM
cat > "$policy_file" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::$PUBLIC_IMAGE_BUCKET/*"]
    },
    {
      "Effect": "Deny",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject", "s3:GetObjectVersion"],
      "Resource": ["arn:aws:s3:::$PUBLIC_IMAGE_BUCKET/staging/*"],
      "Condition": {"StringEquals": {"aws:principaltype": ["Anonymous"]}}
    }
  ]
}
EOF
mc anonymous set-json "$policy_file" "local/$PUBLIC_IMAGE_BUCKET"
