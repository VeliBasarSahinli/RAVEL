"""RAG chunk → soru (gövde + şıklar) ayrıştırıcı (Adım 8j).

Türk ortaokul müfredatında sorular genellikle 5 şıklı (a-e). Chunk
formatı (RAG'da gözlemlenen):

    "1. Üslü ifadelerde 2 üzeri 3 işleminin sonucu kaçtır? a) 6 b) 8 c) 9 d) 12 e) 16"

Soru numarasını atla, gövdeyi al; a)/b)/c)/d)/e) ile başlayan parçalardan
şıkları çıkar. answer_key chunk metadata'sında zaten geliyor (Excel
index'ten). Eğer parse başarısızsa: tek option ("A" = chunk text) +
metadata answer_key olduğu gibi geçer; frontend yine soru göstereblir.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# Şık ayırıcı: a)/A)/a./A. desenleri; ilk şık ile soru gövdesi arası whitespace zorunlu.
_OPT_RE = re.compile(r"\s+([a-eA-E])[\)\.]\s*", re.UNICODE)
# Soru numarası prefix: "1. " veya "12) " gibi
_QNUM_RE = re.compile(r"^\s*\d+[\)\.]\s*")


def parse_question_chunk(text: str, metadata: dict) -> dict:
    """Chunk text + metadata → {question_text, options, answer_key, metadata}.

    Hata toleranslı: parse edemediği soru olduğu gibi tek option ile döner.
    """
    raw = (text or "").strip()
    body = _QNUM_RE.sub("", raw, count=1).strip()

    # Şıkları bul: split'le ama anchor'ları koru.
    # Yöntem: matchall ile başlangıç indekslerini al, parçaları kes.
    matches = list(_OPT_RE.finditer(body))
    if not matches:
        # Şık formatı yok; tüm metni question_text yap.
        return {
            "question_text": body,
            "options": [],
            "answer_key": _normalize_answer_key(metadata.get("answer_key")),
            "metadata": _safe_metadata(metadata),
        }

    question_text = body[: matches[0].start()].strip()
    options: list[dict] = []
    for i, m in enumerate(matches):
        key = m.group(1).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        option_text = body[start:end].strip().rstrip(",;.")
        if option_text:
            options.append({"key": key, "text": option_text})

    return {
        "question_text": question_text or body,
        "options": options,
        "answer_key": _normalize_answer_key(metadata.get("answer_key")),
        "metadata": _safe_metadata(metadata),
    }


def _normalize_answer_key(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().upper()
    if s and s[0] in "ABCDE":
        return s[0]
    return None


def _safe_metadata(md: dict) -> dict:
    """Front'a göndereceğimiz metadata — answer_key burada da var ama
    JSON top-level'da da var; tutarlılık için ikisini de tut."""
    if not isinstance(md, dict):
        return {}
    keys = (
        "question_number",
        "test_no",
        "file_name",
        "taxonomic_level",
        "subject",
        "grade_level",
        "content_type",
        "answer_key",
    )
    return {k: md.get(k) for k in keys if md.get(k) is not None}
