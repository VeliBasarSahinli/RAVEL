"""PDF parser — PyMuPDF (fitz) ile soru ve konu anlatımı dosyalarını okur."""
import logging
import re
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from ..schemas import ParsedChunk
from .excel_parser import ExcelIndex

logger = logging.getLogger(__name__)


_QUESTION_NUMBER_RE = re.compile(r"(?:^|\n)\s*(\d{1,3})[.\)]\s+", re.MULTILINE)
_HEADING_RE = re.compile(r"(?:^|\n)\s*(?:\d+\.\s|[A-ZÇĞİÖŞÜ][^\n]{2,40}:|\b(?:Tanım|Örnek|Kural|Not)\b:)", re.MULTILINE)

MIN_QUESTION_LENGTH = 20  # bu kadar karakterden kısa metin → muhtemelen sadece görsel


class PDFParser:
    # ─── Soru havuzu (Excel index ile birleştirilen) ────────────────

    def parse_question_pdf(
        self,
        file_path: str | Path,
        excel_meta: ExcelIndex,
        grade_level: Optional[int] = None,
        subject: Optional[str] = None,
    ) -> list[ParsedChunk]:
        path = Path(file_path)
        file_name = path.stem  # 6_mat_1.pdf → 6_mat_1

        chunks: list[ParsedChunk] = []
        doc = fitz.open(str(path))
        try:
            full_text = ""
            page_image_pages: dict[int, set] = {}  # sayfa → {soru no'ları (heuristic)}
            for page_idx, page in enumerate(doc):
                page_text = page.get_text()
                full_text += page_text + "\n"
                # Sayfada görsel var mı (her bir image referansı)
                if page.get_images(full=False):
                    page_image_pages[page_idx] = True
                else:
                    page_image_pages[page_idx] = False

            # Soru numaralarını ve konum offset'lerini bul
            matches = list(_QUESTION_NUMBER_RE.finditer(full_text))
            if not matches:
                logger.warning("PDF '%s': no questions detected", file_name)
                return []

            for i, m in enumerate(matches):
                qnum = int(m.group(1))
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
                body = full_text[start:end].strip()

                # Görsel detection — kaba ama etkili: bu soruyu içeren sayfa
                # PyMuPDF görsel saydıysa has_image=True
                # Hangi sayfada bu match? Karakter offset → page belirsiz
                # Pragmatik yaklaşım: tüm dosyada herhangi bir sayfada görsel
                # var mı diye işaretliyoruz; per-question fine-grained görsel
                # detection daha çok iş gerektirir.
                has_image = any(page_image_pages.values())

                # Excel eşleşmesi
                meta = excel_meta.get((file_name, qnum))
                if meta is None:
                    if has_image:
                        # Görsel + meta yok → atla (öğretmen Excel'de işaretlemediyse muhtemelen görsel-zorunlu)
                        continue
                    taxonomic_level = "unknown"
                    answer_key = None
                    test_no = None
                else:
                    taxonomic_level = meta.taxonomic_level
                    answer_key = meta.answer_key
                    test_no = meta.test_no

                # Çok kısa soru → muhtemelen sadece görsel
                if len(body) < MIN_QUESTION_LENGTH:
                    if has_image:
                        continue  # tamamen görsel → embedding yapamayız
                    # Diğer durumda yine atla, çok kısa metin embedding kalitesini düşürür
                    continue

                # Retrieval kalitesi: prefix
                text_content = f"Soru {qnum}: {body}"

                # Admin upload formundan gelen subject/grade_level birinci
                # önceliklidir; verilmediyse file_name'den çıkar.
                final_subject = subject if subject else _infer_subject(file_name)
                final_grade = grade_level if grade_level is not None else _infer_grade(file_name)

                chunks.append(ParsedChunk(
                    chunk_id=f"{file_name}#q{qnum}",
                    text_content=text_content,
                    text_for_embedding=text_content,
                    has_image=has_image,
                    metadata={
                        "content_type": "question",
                        "file_name": file_name,
                        "question_number": qnum,
                        "taxonomic_level": taxonomic_level,
                        "answer_key": answer_key,
                        "test_no": test_no,
                        "subject": final_subject,
                        "grade_level": final_grade,
                    },
                ))
        finally:
            doc.close()

        logger.info("PDF '%s' parsed: %d question chunks", file_name, len(chunks))
        return chunks

    # ─── Konu anlatımı (semantic chunking) ─────────────────────────

    def parse_theory_pdf(
        self,
        file_path: str | Path,
        grade_level: int,
        subject: str,
    ) -> list[ParsedChunk]:
        path = Path(file_path)
        file_name = path.stem
        doc = fitz.open(str(path))
        try:
            text = ""
            for page in doc:
                text += page.get_text() + "\n"
        finally:
            doc.close()

        # Başlıklara göre böl, sonra uzunları kır (chunker import çevrimi
        # önlemek için inline split mantığı)
        from ..chunker import Chunker
        ch = Chunker()
        sections = ch.split_by_headings(text)
        sections = [s for s in (s.strip() for s in sections) if s]
        chunks_text: list[str] = []
        for sec in sections:
            chunks_text.extend(ch.split_long_chunk(sec, max_tokens=500))
        chunks_text = ch.add_overlap(chunks_text, overlap_sentences=1)

        out: list[ParsedChunk] = []
        for i, body in enumerate(chunks_text):
            if len(body) < 30:
                continue
            out.append(ParsedChunk(
                chunk_id=f"{file_name}#t{i}",
                text_content=body,
                text_for_embedding=body,
                has_image=False,
                metadata={
                    "content_type": "theory",
                    "file_name": file_name,
                    "grade_level": grade_level,
                    "subject": subject,
                    "test_no": None,
                    "question_number": None,
                    "taxonomic_level": None,
                    "answer_key": None,
                },
            ))
        logger.info("Theory PDF '%s': %d chunks", file_name, len(out))
        return out


# ─── Helpers (file_name → subject/grade) ────────────────────────────

_GRADE_RE = re.compile(r"(?:^|[^\d])(\d)(?:_|$)")


def _infer_grade(file_name: str) -> Optional[int]:
    m = _GRADE_RE.search(file_name)
    if m:
        try:
            g = int(m.group(1))
            if 5 <= g <= 8:
                return g
        except ValueError:
            pass
    return None


def _infer_subject(file_name: str) -> str:
    # Şimdilik file_name'i bütün döndür; admin katmanı subject metadata'sını
    # upload sırasında üretebilir (Adım 5b iyileştirmesi).
    return file_name
