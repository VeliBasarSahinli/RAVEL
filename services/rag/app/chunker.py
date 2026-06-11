"""Hybrid chunking — başlığa göre böl + uzunları kır + overlap ekle.

token sayısı için kaba bir tahmin: 1 token ~= 4 karakter (Türkçe için
biraz farklı ama yeterli). max_tokens=500 → ~2000 karakter.
"""
import re
from typing import List


_CHARS_PER_TOKEN = 4
_HEADING_PATTERNS = [
    r"\n\s*\d+\.\d*\s+",                            # "1.1 Tanım"
    r"\n\s*\d+\.\s",                                # "1. Bölüm"
    r"\n\s*[A-ZÇĞİÖŞÜ][^\n]{2,40}:\s",              # "Tanım:"
    r"\n\s*\b(?:Tanım|Örnek|Kural|Not|Teorem|Aksiyom)\b[\s:]",  # anahtar kelimeler
]
_HEADING_RE = re.compile("|".join(_HEADING_PATTERNS))


_SENTENCE_END_RE = re.compile(r"(?<=[\.!\?])\s+")


class Chunker:
    def split_by_headings(self, text: str) -> List[str]:
        if not text:
            return []
        # Başlangıçta yapay newline ekleyelim ki ilk başlık da yakalansın
        padded = "\n" + text
        positions = [m.start() for m in _HEADING_RE.finditer(padded)]
        if not positions:
            return [text]
        positions.append(len(padded))
        sections = [padded[positions[i]:positions[i + 1]].strip() for i in range(len(positions) - 1)]
        if positions[0] > 1:
            sections.insert(0, padded[1:positions[0]].strip())
        return [s for s in sections if s]

    def split_long_chunk(self, text: str, max_tokens: int = 500) -> List[str]:
        max_chars = max_tokens * _CHARS_PER_TOKEN
        if len(text) <= max_chars:
            return [text]
        # Cümle sınırlarında böl, max_chars'ı aşmayan parçalar oluştur
        sentences = _SENTENCE_END_RE.split(text)
        chunks: List[str] = []
        cur = ""
        for s in sentences:
            if not s:
                continue
            if not cur:
                cur = s
                continue
            if len(cur) + len(s) + 1 <= max_chars:
                cur += " " + s
            else:
                chunks.append(cur)
                cur = s
        if cur:
            chunks.append(cur)
        return chunks

    def add_overlap(self, chunks: List[str], overlap_sentences: int = 1) -> List[str]:
        if overlap_sentences <= 0 or len(chunks) <= 1:
            return chunks
        out: List[str] = [chunks[0]]
        for prev, current in zip(chunks, chunks[1:]):
            tail_sentences = _SENTENCE_END_RE.split(prev)
            tail = " ".join(tail_sentences[-overlap_sentences:]).strip()
            if tail and not current.startswith(tail):
                out.append(f"{tail} {current}".strip())
            else:
                out.append(current)
        return out
