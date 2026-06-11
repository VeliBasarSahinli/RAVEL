"""MinIO async wrapper — Bandit minio_io ile aynı pattern.

Farklar:
  - Video dosyaları (~MB) yüklüyor; weight (~KB) değil → ThreadPoolExecutor
    yine yeterli (file I/O zaten thread-safe).
  - upload_video → presigned GET URL döndürür (Gateway WS'a koyup browser'a
    iletir). 7 gün geçerli (config'den).
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class MinIOClient:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        url_expiration_seconds: int = 7 * 24 * 3600,
        public_url_prefix: Optional[str] = None,
    ):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.url_expiration_seconds = url_expiration_seconds
        # Tarayıcı erişimi için presigned URL'nin host kısmını değiştir.
        # Örn. "http://minio:9000/ravel-videos/..." → "/minio-videos/ravel-videos/..."
        # (frontend nginx Host header'ı koruyarak proxy eder, imza geçerli)
        self.public_url_prefix = public_url_prefix
        self._client = None
        self._executor: Optional[ThreadPoolExecutor] = None

    async def start(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="minio_video")
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            region_name="us-east-1",
        )

    async def stop(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    async def ensure_bucket(self) -> None:
        loop = asyncio.get_running_loop()

        def _ensure():
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    self._client.create_bucket(Bucket=self.bucket)
                    logger.info("MinIO: created bucket %s", self.bucket)
                else:
                    raise

        await loop.run_in_executor(self._executor, _ensure)

    async def upload_video(self, mp4_path: str, task_id: str) -> str:
        """videos/{task_id}.mp4 olarak yükle, presigned GET URL döndür."""
        loop = asyncio.get_running_loop()
        key = f"videos/{task_id}.mp4"

        def _put():
            with open(mp4_path, "rb") as f:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=f,
                    ContentType="video/mp4",
                )
            # ADR-013 dersi: explicit doğrulama — head_object yapıp boyut karşılaştır
            head = self._client.head_object(Bucket=self.bucket, Key=key)
            return int(head["ContentLength"])

        local_size = os.path.getsize(mp4_path)
        remote_size = await loop.run_in_executor(self._executor, _put)
        if remote_size != local_size:
            raise RuntimeError(
                f"MinIO upload size mismatch local={local_size} remote={remote_size}"
            )

        # Presigned URL (gateway/browser'ın direkt erişebilmesi için)
        def _presign():
            return self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=self.url_expiration_seconds,
            )

        url = await loop.run_in_executor(self._executor, _presign)
        # Public rewrite: internal endpoint'i ('http://minio:9000') tarayıcının
        # erişebileceği prefix ile değiştir. SigV4 Host header imzaya dahil;
        # nginx proxy'si Host: minio:9000 header'ı koruyarak imzayı bozmaz.
        if self.public_url_prefix and url.startswith(self.endpoint):
            url = self.public_url_prefix + url[len(self.endpoint):]
        logger.info("MinIO: uploaded %s (%d bytes) → %s/%s", mp4_path, local_size, self.bucket, key)
        return url
