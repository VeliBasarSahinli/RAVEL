"""Model-agnostic LLM client.

Step 3'te yalnızca mock mode aktif. Step 7'de LangChain/LlamaIndex
soyutlama katmanı üzerinden gerçek modele bağlanacak.
"""
import logging

logger = logging.getLogger(__name__)

MOCK_RESPONSE = (
    "Bu konuyu birlikte inceleyelim. "
    "[MOCK LLM YANITI — Adım 7'de gerçek LLM entegrasyonu yapılacak]"
)

# Mock Manim sahnesi — Adım 6 için. Whitelist'ten geçer (sadece manim
# import'u), syntax doğrudur, render edildiğinde ~3 sn sürer (tek sahne,
# 2 metin + fade).
MOCK_MANIM_CODE = '''\
from manim import *

class RavelLesson(Scene):
    def construct(self):
        title = Text("Konu Anlatimi", font_size=36)
        self.play(Write(title))
        self.wait(0.5)
        body = Text("[MOCK - Adim 7\\'de gercek LLM gelecek]", font_size=24)
        body.next_to(title, DOWN)
        self.play(FadeIn(body))
        self.wait(1)
'''

# Yapay olarak hatalı kod — testlerde QA correction döngüsünü tetiklemek
# için kullanılır. LLM mock'unda 'broken' modu açıldığında döner.
BROKEN_MANIM_CODE = '''\
from manim import *
import os                          # whitelist DIŞI — sandbox AST_VIOLATION verir
class RavelLesson(Scene):
    def construct(self):
        self.add(Text("hello"))
'''


class LLMClient:
    def __init__(self, mock_mode: bool = True):
        self.mock_mode = mock_mode

    async def generate_text_intervention(self, context: dict) -> str:
        """Generate a pedagogical text response.

        context expected to contain at least:
          - student profile (grade_level, learning_style_vector)
          - event payload (topic, taxonomic_level, student_answer, …)
          - rag_chunks: retrieved knowledge OR fallback string
        """
        if self.mock_mode:
            logger.debug("LLM mock mode — returning canned response")
            return MOCK_RESPONSE

        # Step 7: real LLM via LangChain/LlamaIndex abstraction.
        # Provider/model pulled from .env (LLM_PROVIDER, OPENAI_API_KEY, …).
        raise NotImplementedError(
            "Real LLM integration is scheduled for Step 7; "
            "set LLM_MOCK_MODE=true in .env for now."
        )

    async def generate_manim_code(self, context: dict, broken: bool = False) -> str:
        """Manim sahne kodu üret.

        Adım 6 mock: sabit RavelLesson sahnesi döner. Gerçek LLM Adım 7'de.
        `broken=True` ise testler için kasten geçersiz kod döner —
        QA correction döngüsünü kanıtlamak için.
        """
        if self.mock_mode:
            if broken:
                logger.debug("LLM mock — returning broken Manim code (test path)")
                return BROKEN_MANIM_CODE
            logger.debug("LLM mock — returning canned Manim code")
            return MOCK_MANIM_CODE
        raise NotImplementedError(
            "Real LLM Manim generation is scheduled for Step 7; "
            "set LLM_MOCK_MODE=true in .env for now."
        )

    async def correct_manim_code(self, prev_code: str, error_context: dict) -> str:
        """qa_correction_loop'tan gelen hatayı düzeltmeyi dene.

        Adım 6 mock'unda gerçek bir düzeltme yapılamaz — LLM yok.
        Yine de "düzeltme akışı" kanıtı için sabit MOCK_MANIM_CODE
        döndürürüz (önceki kod bozuksa şimdi geçer; aynıysa attempt+1
        ile tekrar denenir).
        """
        if self.mock_mode:
            logger.debug("LLM mock — correction returns canned valid code")
            return MOCK_MANIM_CODE
        raise NotImplementedError(
            "Real LLM Manim correction is scheduled for Step 7; "
            "set LLM_MOCK_MODE=true in .env for now."
        )
