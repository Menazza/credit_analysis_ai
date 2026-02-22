import io
import uuid
from typing import BinaryIO, Optional
import boto3
from botocore.config import Config
from app.config import get_settings


def get_s3_client():
    s = get_settings()
    kwargs = {
        "aws_access_key_id": s.object_storage_access_key,
        "aws_secret_access_key": s.object_storage_secret_key,
        "config": Config(signature_version="s3v4"),
        "region_name": s.storage_region,
    }
    # AWS S3: no endpoint_url (use default). MinIO/R2: set endpoint_url and use_ssl.
    if s.object_storage_url:
        kwargs["endpoint_url"] = s.object_storage_url
        kwargs["use_ssl"] = s.object_storage_use_ssl
    return boto3.client("s3", **kwargs)


def ensure_bucket():
    s = get_settings()
    client = get_s3_client()
    bucket = s.object_storage_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        # Only create for non-AWS (MinIO/R2). For AWS, bucket must exist.
        if s.object_storage_url:
            client.create_bucket(Bucket=bucket)
        else:
            try:
                if s.storage_region and s.storage_region != "us-east-1":
                    client.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": s.storage_region})
                else:
                    client.create_bucket(Bucket=bucket)
            except Exception as e:
                raise RuntimeError(f"Bucket {bucket} not found. Create it in the {s.storage_region} console first. {e}") from e


def upload_file(
    key: str,
    body: BinaryIO,
    content_type: str = "application/octet-stream",
    metadata: Optional[dict] = None,
) -> str:
    ensure_bucket()
    client = get_s3_client()
    bucket = get_settings().object_storage_bucket
    extra = {"ContentType": content_type}
    if metadata:
        extra["Metadata"] = {k: str(v) for k, v in metadata.items()}
    client.upload_fileobj(body, bucket, key, ExtraArgs=extra)
    s = get_settings()
    if s.object_storage_url:
        return f"{s.object_storage_url}/{bucket}/{key}"
    return f"https://{bucket}.s3.{s.storage_region}.amazonaws.com/{key}"


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    return upload_file(key, io.BytesIO(data), content_type=content_type)


def generate_doc_key(tenant_id: str, company_id: str, doc_id: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"tenants/{tenant_id}/companies/{company_id}/docs/{doc_id}.{ext}"


def generate_page_asset_key(tenant_id: str, doc_version_id: str, page_no: int, suffix: str = "png") -> str:
    return f"tenants/{tenant_id}/doc_versions/{doc_version_id}/pages/{page_no}.{suffix}"


def generate_soce_page_key(tenant_id: str, doc_version_id: str, page_no: int) -> str:
    """S3 key for SoCE page image (for LLM layout analysis)."""
    return f"tenants/{tenant_id}/doc_versions/{doc_version_id}/soce_pages/{page_no}.png"


def _parse_storage_url(storage_url: str) -> tuple[str, str]:
    """Return (bucket, key) from a storage URL (AWS virtual-hosted or custom endpoint)."""
    from urllib.parse import urlparse
    parsed = urlparse(storage_url)
    path = (parsed.path or "").strip("/")
    s = get_settings()
    if s.object_storage_url and storage_url.startswith(s.object_storage_url.rstrip("/")):
        # Custom endpoint: {endpoint}/{bucket}/{key}
        parts = path.split("/", 1)
        bucket = parts[0] if len(parts) > 0 else s.object_storage_bucket
        key = parts[1] if len(parts) > 1 else ""
        return bucket, key
    # AWS virtual-hosted: https://bucket.s3.region.amazonaws.com/key
    if ".s3." in parsed.netloc:
        bucket = parsed.netloc.split(".s3.")[0]
        key = path
        return bucket, key
    # Fallback: use config bucket and whole path as key
    return s.object_storage_bucket, path


def download_file_from_url(storage_url: str) -> bytes:
    """Download object from S3 (or compatible) and return bytes."""
    client = get_s3_client()
    bucket, key = _parse_storage_url(storage_url)
    if not key:
        raise ValueError(f"Cannot determine S3 key from URL: {storage_url}")
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read()


def upload_json_to_storage(key: str, json_content: str) -> str:
    """Upload JSON string to S3 and return the URL."""
    return upload_bytes(key, json_content.encode("utf-8"), content_type="application/json")


def download_json_from_storage(key: str) -> str:
    """Download JSON content from S3."""
    ensure_bucket()
    client = get_s3_client()
    bucket = get_settings().object_storage_bucket
    resp = client.get_object(Bucket=bucket, Key=key)
    return resp["Body"].read().decode("utf-8")
