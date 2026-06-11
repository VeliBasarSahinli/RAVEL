"""MinIO async wrapper — boto3 senkron, executor ile sarmalanmış.

aiobotocore'a geçilebilir ama ek dependency; küçük bir bucket için
ThreadPoolExecutor yeterli (ağırlık dosyası ~10-50 KB, dakikada bir kez yazılır).
"""
import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

WEIGHTS_KEY = "weights_latest.json"


class MinIOClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self._client = None
        self._executor: Optional[ThreadPoolExecutor] = None

    async def start(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="minio")
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

    async def save_weights(self, weights: dict) -> None:
        loop = asyncio.get_running_loop()
        body = json.dumps(weights).encode("utf-8")

        def _put():
            self._client.put_object(
                Bucket=self.bucket,
                Key=WEIGHTS_KEY,
                Body=body,
                ContentType="application/json",
            )

        await loop.run_in_executor(self._executor, _put)
        logger.debug("MinIO: saved %d bytes to %s/%s", len(body), self.bucket, WEIGHTS_KEY)

    async def load_weights(self) -> Optional[dict]:
        loop = asyncio.get_running_loop()

        def _get():
            try:
                obj = self._client.get_object(Bucket=self.bucket, Key=WEIGHTS_KEY)
                return json.loads(obj["Body"].read())
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("NoSuchKey", "404"):
                    return None
                raise

        return await loop.run_in_executor(self._executor, _get)
