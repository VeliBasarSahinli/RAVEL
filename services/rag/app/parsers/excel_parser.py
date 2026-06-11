"""Excel index parser — soru havuzunun metadata'sını okur.

Beklenen kolonlar:
  file_name, test_no, question_number, taxonomic_level, answer_key

Excel dosyalarında file_name'in başında/sonunda boşluk gelmesi yaygın
("6_mat_1 ", " 6_mat_2") — strip ile temizliyoruz.
"""
import logging
from pathlib import Path
from typing import Tuple

import pandas as pd

from ..schemas import QuestionMeta

logger = logging.getLogger(__name__)


# (file_name, question_number) → QuestionMeta
ExcelIndex = dict[Tuple[str, int], QuestionMeta]


REQUIRED_COLUMNS = {"file_name", "question_number", "taxonomic_level"}
OPTIONAL_COLUMNS = {"test_no", "answer_key"}


class ExcelParser:
    @staticmethod
    def parse(file_path: str | Path) -> ExcelIndex:
        df = pd.read_excel(file_path, engine="openpyxl")

        # Kolon adlarını lowercase + strip (Excel'den case insensitive)
        df.columns = [str(c).strip().lower() for c in df.columns]
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            raise ValueError(f"Excel index missing required columns: {missing}")

        index: ExcelIndex = {}
        for _, row in df.iterrows():
            file_name = str(row["file_name"]).strip()
            try:
                qnum = int(row["question_number"])
            except (ValueError, TypeError):
                continue
            taxonomic = str(row["taxonomic_level"]).strip()
            test_no = None
            if "test_no" in df.columns and pd.notna(row.get("test_no")):
                try:
                    test_no = int(row["test_no"])
                except (ValueError, TypeError):
                    test_no = None
            answer_key = None
            if "answer_key" in df.columns and pd.notna(row.get("answer_key")):
                answer_key = str(row["answer_key"]).strip().upper()
                if not answer_key:
                    answer_key = None

            meta = QuestionMeta(
                file_name=file_name,
                test_no=test_no,
                question_number=qnum,
                taxonomic_level=taxonomic,
                answer_key=answer_key,
            )
            index[(file_name, qnum)] = meta

        logger.info("Excel parsed: %d rows, %d unique (file_name, question_number) pairs",
                    len(df), len(index))
        return index
