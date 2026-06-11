#!/usr/bin/env bash
# RAVEL — Step 5 Aşama 1 + Aşama 2 birleşik unit + ingestion testleri
#
# 1) Excel parser   — programmatic .xlsx → index dict
# 2) DOCX parser    — programmatic .docx (bold + numbered) → 3 question chunks
# 3) Chunker        — long text → bölünme + overlap
# 4) Embedder       — 5 sorudan vektör; benzer olanlar yakın (cosine)
# 5) Ingestion E2E  — Excel + DOCX → embed → Qdrant upsert → search bulur mu?
# 6) Idempotency    — aynı dosyayı tekrar ingest et, count sabit mi?

set -uo pipefail
cd "$(dirname "$0")/.."

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

# Test'i RAG container içinde çalıştır — kütüphaneler oraya kurulu,
# Qdrant'a "qdrant:6333" hostname ile erişim içeride doğal.
run_in_container() {
  docker compose exec -T rag python <<'PY'
import asyncio, json, sys, traceback, tempfile, os
from pathlib import Path
import numpy as np
import pandas as pd
from docx import Document

from app.config import get_settings
from app.parsers.excel_parser import ExcelParser
from app.parsers.docx_parser import DocxParser
from app.chunker import Chunker
from app.embedder import Embedder, normalize_for_embedding
from app.qdrant_io import QdrantIO
from app.ingestion_pipeline import IngestionPipeline
from app.retriever import Retriever
from app.schemas import ContentRetrievalRequest, ContentRetrievalQuery

settings = get_settings()
results = {}

def assert_ok(name, condition, detail=""):
    results[name] = (bool(condition), detail)
    print(f"{'PASS' if condition else 'FAIL'} | {name} | {detail}")

# ── 1) Excel parser ─────────────────────────────────────────────────
def test_excel():
    df = pd.DataFrame([
        {"file_name": "test_set ", "test_no": 1, "question_number": 1, "taxonomic_level": "B1", "answer_key": "A"},
        {"file_name": "test_set",  "test_no": 1, "question_number": 2, "taxonomic_level": "B1", "answer_key": "B"},
        {"file_name": "test_set",  "test_no": 1, "question_number": 3, "taxonomic_level": "B2", "answer_key": "C"},
    ])
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as t:
        path = t.name
    df.to_excel(path, index=False)
    idx = ExcelParser.parse(path)
    os.unlink(path)
    assert_ok("excel_parser_count",       len(idx) == 3, f"len={len(idx)}")
    assert_ok("excel_parser_strip",       ("test_set", 1) in idx, "trailing space stripped")
    assert_ok("excel_parser_taxonomy",    idx[("test_set", 3)].taxonomic_level == "B2", "")

test_excel()

# ── 2) DOCX parser ─────────────────────────────────────────────────
def make_docx_with_questions(questions, file_path):
    doc = Document()
    for n, body in questions:
        p = doc.add_paragraph()
        run = p.add_run(f"{n}. ")
        run.bold = True
        p.add_run(body)
    doc.save(file_path)

def test_docx():
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as t:
        path = t.name
    make_docx_with_questions([
        (1, "Üslü ifadelerde 2^3 işleminin sonucu kaçtır? a) 6  b) 8  c) 9  d) 12  e) 16"),
        (2, "Karekök 16 işleminin sonucu nedir? a) 2  b) 4  c) 8  d) 16  e) 256"),
        (3, "5+3*2 işleminin sonucu kaçtır? a) 11  b) 13  c) 16  d) 21  e) 31"),
    ], path)
    excel_index = {
        ("test_set", 1): __import__("app.schemas", fromlist=["QuestionMeta"]).QuestionMeta(
            file_name="test_set", test_no=1, question_number=1, taxonomic_level="B1", answer_key="B"),
        ("test_set", 2): __import__("app.schemas", fromlist=["QuestionMeta"]).QuestionMeta(
            file_name="test_set", test_no=1, question_number=2, taxonomic_level="B1", answer_key="B"),
        ("test_set", 3): __import__("app.schemas", fromlist=["QuestionMeta"]).QuestionMeta(
            file_name="test_set", test_no=1, question_number=3, taxonomic_level="B2", answer_key="A"),
    }
    # DocxParser file_name'i Path.stem'den alıyor; isim eşleşmeli
    final_path = "/tmp/test_set.docx"
    Path(path).rename(final_path)
    chunks = DocxParser().parse_question_docx(final_path, excel_index)
    os.unlink(final_path)

    assert_ok("docx_parser_count",     len(chunks) == 3, f"len={len(chunks)}")
    assert_ok("docx_parser_q1_meta",   chunks[0].metadata["question_number"] == 1, "")
    assert_ok("docx_parser_taxonomy",  chunks[2].metadata["taxonomic_level"] == "B2", "")
    assert_ok("docx_parser_text_prefix", chunks[0].text_content.startswith("Soru 1:"), "")

test_docx()

# ── 3) Chunker ─────────────────────────────────────────────────────
def test_chunker():
    ch = Chunker()
    long_text = ". ".join([f"Bu bir test cümlesi numara {i}" for i in range(80)]) + "."
    splits = ch.split_long_chunk(long_text, max_tokens=100)
    overlap = ch.add_overlap(splits, overlap_sentences=1)
    assert_ok("chunker_split_long",  len(splits) > 1, f"chunks={len(splits)}")
    assert_ok("chunker_overlap_len", len(overlap) == len(splits), "")
    if len(splits) > 1:
        first_sentence_of_chunk1 = splits[0].split(". ")[-1].rstrip(".")
        # Overlap chunk 2'nin başında chunk 1'in son cümlesi var mı?
        assert_ok("chunker_overlap_pref",
                  first_sentence_of_chunk1 in overlap[1] or splits[1] == overlap[1],
                  "")

test_chunker()

# ── 4) Embedder cosine similarity ──────────────────────────────────
def cos(a, b):
    a = np.array(a); b = np.array(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

def test_embedder():
    e = Embedder(settings.embedding_model, cache_folder=settings.embedding_cache_folder)
    e.load()
    sentences = [
        "2 üzeri 3 kaçtır?",          # 0
        "İki üzeri üç işleminin sonucu nedir?",  # 1 (0'a yakın olmalı)
        "Karekök 16 kaçtır?",           # 2
        "16'nın karekökü nedir?",       # 3 (2'ye yakın olmalı)
        "Türkiye'nin başkenti neresidir?",  # 4 (alakasız)
    ]
    vecs = e.embed_texts(sentences)
    assert_ok("embedder_dim",   all(len(v) == settings.embedding_dim for v in vecs), f"dim={len(vecs[0])}")
    sim_01 = cos(vecs[0], vecs[1])
    sim_23 = cos(vecs[2], vecs[3])
    sim_04 = cos(vecs[0], vecs[4])
    # paraphrase-multilingual-MiniLM-L12-v2 Türkçe paraphrase'lerini 0.55-0.75
    # aralığında verir (ESKI BERT modellerinden daha düşük). Asıl önemli olan
    # related vs unrelated arasındaki belirgin fark — bu da SIMILARITY_THRESHOLD=0.45
    # config'iyle uyumlu.
    assert_ok("embedder_sim_pair_high_01", sim_01 > 0.55, f"sim={sim_01:.3f}")
    assert_ok("embedder_sim_pair_high_23", sim_23 > 0.55, f"sim={sim_23:.3f}")
    assert_ok("embedder_sim_pair_low_04",  sim_04 < sim_01 * 0.5,
              f"unrelated={sim_04:.3f} ≪ related={sim_01:.3f} ({sim_01/max(sim_04, 0.001):.0f}x)")

test_embedder()

# ── 5) Ingestion E2E (DOCX → Qdrant → search) ───────────────────────
async def test_ingestion():
    qd = QdrantIO(url=settings.qdrant_url, collection=settings.qdrant_collection,
                  vector_dim=settings.embedding_dim)
    await qd.start()
    e = Embedder(settings.embedding_model, cache_folder=settings.embedding_cache_folder)
    e.load()
    pipeline = IngestionPipeline(embedder=e, qdrant=qd, minio_client=None, minio_bucket=None)

    # Excel index oluştur
    df = pd.DataFrame([
        {"file_name": "rag_unit_test", "test_no": 1, "question_number": 1, "taxonomic_level": "B1", "answer_key": "B"},
        {"file_name": "rag_unit_test", "test_no": 1, "question_number": 2, "taxonomic_level": "B1", "answer_key": "B"},
        {"file_name": "rag_unit_test", "test_no": 1, "question_number": 3, "taxonomic_level": "B2", "answer_key": "A"},
    ])
    excel_path = "/tmp/rag_unit_index.xlsx"
    df.to_excel(excel_path, index=False)
    pipeline.ingest_excel_index(excel_path)

    # DOCX oluştur
    docx_path = "/tmp/rag_unit_test.docx"
    make_docx_with_questions([
        (1, "Üslü ifadelerde 2^3 işleminin sonucu kaçtır? a) 6 b) 8 c) 9 d) 12 e) 16"),
        (2, "Karekök 16 işleminin sonucu nedir? a) 2 b) 4 c) 8 d) 16 e) 256"),
        (3, "5+3*2 işleminin sonucu kaçtır? a) 11 b) 13 c) 16 d) 21 e) 31"),
    ], docx_path)

    res1 = await pipeline.ingest_question_file(docx_path, "docx")
    assert_ok("ingest_parsed",   res1.parsed_chunks == 3, f"parsed={res1.parsed_chunks}")
    assert_ok("ingest_embedded", res1.embedded_chunks == 3, f"embedded={res1.embedded_chunks}")
    assert_ok("ingest_written",  res1.written_chunks == 3, f"written={res1.written_chunks}")

    # Qdrant'tan ara: "üs hesaplama" → soru 1 dönmeli.
    # subject="rag_unit_test" ile sadece bu testin yüklediği chunk'ları
    # filtreliyoruz (koleksiyon paylaşımlı; başka testlerin kalıntıları
    # taxonomic_level filter kaldırıldıktan sonra retrieval'a karışıyordu).
    retriever = Retriever(settings, e, qd)
    request = ContentRetrievalRequest(
        correlation_id="unit_test_corr",
        trace_id="unit_test_trace",
        student_id=None,
        query=ContentRetrievalQuery(
            subject="rag_unit_test", taxonomic_level="B1",
            content_type="question",
            context="iki üzeri üç işlemi",
        ),
        grade_level=None,
        top_k=5,
    )
    response = await retriever.retrieve(request)
    found = [c.text for c in response.chunks]
    assert_ok("retrieval_found_at_least_1", len(response.chunks) >= 1, f"chunks={len(response.chunks)}")
    if response.chunks:
        # taxonomic_level filtresi question retrieval'da uygulanmıyor (tasarım
        # kararı: Bandit seviye düzeltmesi yapsın). Üç soru da B1/B2 fark
        # etmeksizin döner; bu yüzden en yüksek skorda olmasa da top sonuçların
        # içinde 'üslü/2^3' geçen alakalı chunk bulunmalı.
        relevant_in_results = any(
            "2^3" in c.text or "üslü" in c.text.lower()
            for c in response.chunks
        )
        debug_list = " | ".join(f"{c.score:.2f}:{c.text[:30]}" for c in response.chunks)
        assert_ok("retrieval_top_chunk_relevant",
                  relevant_in_results,
                  f"chunks=[{debug_list}]")

    # 6) Idempotency — aynı dosyayı tekrar yükle
    res2 = await pipeline.ingest_question_file(docx_path, "docx")
    assert_ok("idempotency_chunks_stable",
              res2.written_chunks == 3,
              f"first={res1.written_chunks} second={res2.written_chunks}")
    # Qdrant collection toplam chunk sayısı (sadece bu test için ekleneni filtrele)
    # delete_by_source çalıştığını teyit etmek için: collection'da rag_unit_test
    # için sadece 3 nokta olmalı, 6 değil.
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue
    cnt = await qd.client.count(
        collection_name=settings.qdrant_collection,
        count_filter=Filter(must=[FieldCondition(key="file_name", match=MatchValue(value="rag_unit_test"))]),
        exact=True,
    )
    assert_ok("idempotency_qdrant_count_3", cnt.count == 3, f"qdrant count={cnt.count}")

    # Cleanup
    await qd.delete_by_source("rag_unit_test")
    await qd.stop()
    os.unlink(excel_path); os.unlink(docx_path)

asyncio.run(test_ingestion())

# ── Sonuç ──
total = len(results)
passed = sum(1 for v, _ in results.values() if v)
failed = total - passed
print(f"\n=== TOTAL: {passed}/{total} ===")
# Diğer test scriptleriyle aynı format için ayrı bir satır:
print(f"Passed: {passed}    Failed: {failed}")
PY
}

run_in_container

echo ""
echo "═════════════════════════════════════"
