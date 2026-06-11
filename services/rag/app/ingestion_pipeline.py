"""IngestionPipeline — admin upload akışını orkestre eder.

Akış:
  1. Excel index'i parse et (in-memory tut + MinIO'ya persist)
  2. PDF/DOCX'i ilgili parser ile parse et
  3. Chunk'ları batch'ler halinde embed et
  4. Qdrant'a upsert et (idempotency: önce delete_by_source)
  5. Orijinal dosyayı MinIO'ya yükle
  6. Sonuçları IngestionResult olarak döndür

Excel index persist: process-memory dict'i container restart'ında kaybolur.
Yeni soru havuzu upload'ı `_excel_index` boş olduğu için reddedilir, admin
manuel reupload zorunda. Çözüm: ingest_excel_index başarılı parse sonrası
pickle ile MinIO'ya yazıyoruz; main.py startup'ta restore_excel_index
çağırıp önceki state'i döndürüyor.
"""
import asyncio
import io
import logging
import pickle
import time
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError

from .embedder import Embedder
from .parsers.docx_parser import DocxParser
from .parsers.excel_parser import ExcelIndex, ExcelParser
from .parsers.pdf_parser import PDFParser
from .qdrant_io import QdrantIO
from .schemas import IngestionResult, ParsedChunk

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        embedder: Embedder,
        qdrant: QdrantIO,
        minio_client=None,
        minio_bucket: Optional[str] = None,
        minio_meta_bucket: Optional[str] = None,
        excel_index_object_key: str = "excel_index/latest.pkl",
    ):
        self.embedder = embedder
        self.qdrant = qdrant
        self.minio_client = minio_client
        self.minio_bucket = minio_bucket
        self.minio_meta_bucket = minio_meta_bucket
        self.excel_index_object_key = excel_index_object_key
        self._excel_index: ExcelIndex = {}

    # ─── Excel index (admin tarafında bir kez) ──────────────────────

    def ingest_excel_index(self, file_path: str) -> dict:
        idx = ExcelParser.parse(file_path)
        self._excel_index = idx
        files = sorted({k[0] for k in idx.keys()})
        # Best-effort persist: MinIO'ya yazma başarısız olursa bile
        # in-memory state çalışmaya devam etsin.
        try:
            self._persist_excel_index_sync()
        except Exception:
            logger.exception("Excel index MinIO persist failed (continuing in-memory)")
        return {
            "rows": len(idx),
            "file_names": files,
        }

    @property
    def excel_index_size(self) -> int:
        return len(self._excel_index)

    # ─── MinIO persist/restore ──────────────────────────────────────

    def _persist_excel_index_sync(self) -> None:
        if not (self.minio_client and self.minio_meta_bucket):
            logger.debug("Excel index persist skipped — MinIO meta bucket not configured")
            return
        data = pickle.dumps(self._excel_index)
        self.minio_client.put_object(
            Bucket=self.minio_meta_bucket,
            Key=self.excel_index_object_key,
            Body=data,
            ContentType="application/octet-stream",
        )
        logger.info(
            "Excel index persisted to MinIO bucket=%s key=%s size=%dB",
            self.minio_meta_bucket, self.excel_index_object_key, len(data),
        )

    async def restore_excel_index(self) -> bool:
        """MinIO'dan önceki Excel index'i yükle. Bulamazsa False döner."""
        if not (self.minio_client and self.minio_meta_bucket):
            return False
        loop = asyncio.get_running_loop()

        def _get():
            return self.minio_client.get_object(
                Bucket=self.minio_meta_bucket,
                Key=self.excel_index_object_key,
            )

        try:
            obj = await loop.run_in_executor(None, _get)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404", "NoSuchBucket"):
                return False
            raise
        body = obj["Body"].read()
        idx = pickle.loads(body)
        if not isinstance(idx, dict):
            logger.warning("Excel index restore: invalid payload type %s", type(idx))
            return False
        self._excel_index = idx
        logger.info("Excel index restored from MinIO: %d rows", len(idx))
        return True

    # ─── Question file ingest ───────────────────────────────────────

    async def ingest_question_file(
        self,
        file_path: str,
        file_type: str,
        grade_level: Optional[int] = None,
        subject: Optional[str] = None,
    ) -> IngestionResult:
        question_metadata = None
        if grade_level is not None or subject is not None:
            question_metadata = {"grade_level": grade_level, "subject": subject}
        return await self._ingest_file(
            file_path,
            file_type,
            theory_metadata=None,
            question_metadata=question_metadata,
        )

    # ─── Theory file ingest ─────────────────────────────────────────

    async def ingest_theory_file(
        self,
        file_path: str,
        file_type: str,
        grade_level: int,
        subject: str,
    ) -> IngestionResult:
        return await self._ingest_file(
            file_path,
            file_type,
            theory_metadata={"grade_level": grade_level, "subject": subject},
        )

    # ─── Internal ───────────────────────────────────────────────────

    async def _ingest_file(
        self,
        file_path: str,
        file_type: str,
        theory_metadata: Optional[dict] = None,
        question_metadata: Optional[dict] = None,
    ) -> IngestionResult:
        start = time.perf_counter()
        path = Path(file_path)
        file_name = path.stem
        ft = file_type.lower()

        # ── 1. Parse ────────────────────────────────────────────────
        chunks: list[ParsedChunk] = []
        if theory_metadata is None:
            # Soru havuzu — Excel index gerek
            if not self._excel_index:
                raise ValueError("Excel index empty — POST /admin/upload/excel önce çağrılmalı")
            q_grade = question_metadata.get("grade_level") if question_metadata else None
            q_subject = question_metadata.get("subject") if question_metadata else None
            if ft == "pdf":
                chunks = PDFParser().parse_question_pdf(
                    path, self._excel_index, grade_level=q_grade, subject=q_subject,
                )
            elif ft == "docx":
                chunks = DocxParser().parse_question_docx(
                    path, self._excel_index, grade_level=q_grade, subject=q_subject,
                )
            else:
                raise ValueError(f"unsupported file_type: {file_type}")
        else:
            grade = int(theory_metadata["grade_level"])
            subject = str(theory_metadata["subject"])
            if ft == "pdf":
                chunks = PDFParser().parse_theory_pdf(path, grade, subject)
            elif ft == "docx":
                chunks = DocxParser().parse_theory_docx(path, grade, subject)
            else:
                raise ValueError(f"unsupported file_type: {file_type}")

        parsed_count = len(chunks)
        skipped_image_only = 0  # parser zaten atlıyor; metric için ek sayım yapmak isterseniz buraya
        embedded_count = 0
        written_count = 0
        failed_count = 0

        if not chunks:
            logger.warning("ingestion '%s': no chunks parsed", file_name)
        else:
            # ── 2. Idempotency ──────────────────────────────────────
            await self.qdrant.delete_by_source(file_name)

            # ── 3. Embed (batch'ler halinde) ────────────────────────
            try:
                texts = [c.text_for_embedding for c in chunks]
                # Embedder kendi içinde batch yapıyor
                vectors = await asyncio.to_thread(self.embedder.embed_texts, texts)
                embedded_count = len(vectors)
            except Exception:
                logger.exception("ingestion '%s': embedding failed", file_name)
                failed_count = len(chunks)
                vectors = []

            # ── 4. Qdrant upsert ────────────────────────────────────
            if vectors:
                try:
                    written_count = await self.qdrant.upsert_chunks(chunks, vectors)
                except Exception:
                    logger.exception("ingestion '%s': qdrant upsert failed", file_name)
                    failed_count = len(chunks)

        # ── 5. MinIO upload (best-effort, hatada warning) ──────────
        if self.minio_client and self.minio_bucket:
            try:
                self.minio_client.upload_file(str(path), self.minio_bucket, path.name)
            except Exception:
                logger.exception("ingestion '%s': MinIO upload failed (non-fatal)", file_name)

        elapsed = time.perf_counter() - start
        result = IngestionResult(
            file_name=file_name,
            file_type=ft,
            parsed_chunks=parsed_count,
            embedded_chunks=embedded_count,
            written_chunks=written_count,
            skipped_chunks=skipped_image_only,
            failed_chunks=failed_count,
            processing_time_seconds=round(elapsed, 3),
        )
        logger.info("ingestion '%s' complete: %s", file_name, result.model_dump())
        return result
