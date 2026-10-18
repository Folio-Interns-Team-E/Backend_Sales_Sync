import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from app.config import settings
import uuid
import re
import asyncio
from pathlib import Path
from asyncio import to_thread

s3_client = boto3.client(
    "s3",
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    region_name=settings.aws_region,
    config=Config(
        connect_timeout=5,
        read_timeout=20,
        retries={"max_attempts": 2, "mode": "standard"},
    ),
)

def _sanitize_filename(filename: str) -> str:
    base_name = Path(filename or "file").name
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", base_name)
    return sanitized.strip("._") or "file"

async def upload_to_s3(file_bytes: bytes, filename: str, content_type: str, prefix: str = "knowledge-base", user_id: str = "system") -> str:
    if not all(
        [
            settings.aws_access_key_id,
            settings.aws_secret_access_key,
            settings.aws_bucket_name,
            settings.aws_region,
        ]
    ):
        raise RuntimeError("File storage is not configured")

    safe_filename = _sanitize_filename(filename)
    key = f"{prefix}/{user_id}/{uuid.uuid4()}/{safe_filename}"
    
    try:
        await asyncio.wait_for(
            to_thread(
                s3_client.put_object,
                Bucket=settings.aws_bucket_name,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
            ),
            timeout=30,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError("File storage did not respond in time") from exc
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError("File storage rejected the upload") from exc
    
    url = f"https://{settings.aws_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{key}"
    return url


def generate_presigned_url(s3_url: str, expiration: int = 3600) -> str:
    key = s3_url.split(f"{settings.aws_bucket_name}.s3.{settings.aws_region}.amazonaws.com/")[-1]
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.aws_bucket_name, "Key": key},
        ExpiresIn=expiration,
    )
    return url
