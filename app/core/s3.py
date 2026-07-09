import boto3
from app.config import settings
import uuid
import re
from pathlib import Path
from asyncio import to_thread

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    region_name=settings.aws_region
)

def _sanitize_filename(filename: str) -> str:
    base_name = Path(filename or "file").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", base_name)
    return sanitized.strip("._") or "file"

async def upload_to_s3(file_bytes: bytes, filename: str, content_type: str) -> str:
    safe_filename = _sanitize_filename(filename)
    key = f"knowledge-base/{uuid.uuid4()}/{safe_filename}"
    
    await to_thread(
        s3_client.put_object,
        Bucket=settings.aws_bucket_name,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
    )
    
    url = f"https://{settings.aws_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{key}"
    return url