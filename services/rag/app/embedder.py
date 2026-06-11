"""Embedder — sentence-transformers wrapper with LaTeX/symbol normalization.

Embedding kalitesi için critical: LaTeX işaretleri "üzeri", "bölü"
gibi Türkçe okunuşa çevrilir; orijinal metin gösterim için saklanır,
sadece embedding girdisi normalize edilir.

Hardware:
  - Container (Linux/ARM64) : torch CPU
  - Host venv (Apple Silicon): torch MPS otomatik algılanır
"""
import logging
import re
from typing import Iterable, Optional

import torch
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


# ─── LaTeX / sembol → Türkçe normalizasyon kuralları ────────────────

_FRAC_RE = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
_SQRT_RE = re.compile(r"\\sqrt\s*\{([^{}]+)\}")
_SUPERSCRIPT_LITERAL = re.compile(r"\^(\d+)")
_INLINE_DOLLAR = re.compile(r"\$([^$]+)\$")
_LATEX_CMD = re.compile(r"\\[a-zA-Z]+")

_SYMBOL_TABLE = {
    "²": " kare ",
    "³": " küp ",
    "⁴": " üzeri 4 ",
    "⁵": " üzeri 5 ",
    "√": " karekök ",
    "÷": " bölü ",
    "×": " çarpı ",
    "≤": " küçük eşit ",
    "≥": " büyük eşit ",
    "≠": " eşit değil ",
    "≈": " yaklaşık ",
    "π": " pi ",
    "∞": " sonsuz ",
    "α": " alfa ",
    "β": " beta ",
}


def normalize_for_embedding(text: str) -> str:
    """LaTeX + Unicode matematik sembollerini sözel hale çevir.

    Örnekler:
      x^2          → x kare
      \\frac{a}{b}  → a bölü b
      \\sqrt{x+1}   → karekök ( x+1 )
      x²           → x kare
    """
    s = text

    # LaTeX inline ($...$) sarmalayıcılarını kaldır
    s = _INLINE_DOLLAR.sub(r"\1", s)

    # \frac{a}{b} → "a bölü b"
    s = _FRAC_RE.sub(r"\1 bölü \2", s)
    # \sqrt{x} → "karekök ( x )"
    s = _SQRT_RE.sub(r"karekök ( \1 )", s)

    # ^N → "üzeri N"  (önce çoklu rakam)
    def _sup(m):
        n = m.group(1)
        if n == "2":
            return " kare "
        if n == "3":
            return " küp "
        return f" üzeri {n} "

    s = _SUPERSCRIPT_LITERAL.sub(_sup, s)

    # Unicode tek karakter semboller
    for k, v in _SYMBOL_TABLE.items():
        s = s.replace(k, v)

    # Kalan LaTeX komutları (\alpha, \cdot vb.) — kaldır
    s = _LATEX_CMD.sub(" ", s)

    # Tek karakter ASCII süslü parantezleri kaldır (artık karşılığı bırakıldı)
    s = s.replace("{", " ").replace("}", " ")

    # Çoklu boşluk → tek
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ─── Embedder ────────────────────────────────────────────────────────

class Embedder:
    def __init__(
        self,
        model_name: str,
        cache_folder: Optional[str] = None,
        batch_size: int = 64,
    ):
        self.model_name = model_name
        self.cache_folder = cache_folder
        self.batch_size = batch_size
        self._model: Optional[SentenceTransformer] = None
        self._device: Optional[str] = None

    def _detect_device(self) -> str:
        if torch.cuda.is_available():
            return "cuda"
        # Apple Silicon (host venv'de mevcut, container'da mevcut değil)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def load(self) -> None:
        if self._model is not None:
            return
        self._device = self._detect_device()
        logger.info("Embedder: loading '%s' on device=%s (cache=%s)",
                    self.model_name, self._device, self.cache_folder)
        kwargs = {"device": self._device}
        if self.cache_folder:
            kwargs["cache_folder"] = self.cache_folder
        self._model = SentenceTransformer(self.model_name, **kwargs)
        logger.info("Embedder: loaded (dim=%d)", self._model.get_sentence_embedding_dimension())

    @property
    def device(self) -> str:
        return self._device or "cpu"

    def embed_texts(self, texts: Iterable[str]) -> list[list[float]]:
        if self._model is None:
            self.load()
        text_list = list(texts)
        if not text_list:
            return []
        # encode batch'leri sentence-transformers iç olarak yönetir
        # ama büyük listeler için biz de güvenli batch boyutu veriyoruz
        normalized = [normalize_for_embedding(t) for t in text_list]
        vectors = self._model.encode(
            normalized,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]

    def embed_one(self, text: str) -> list[list[float]]:
        return self.embed_texts([text])[0] if False else self.embed_texts([text])[0:1][0]
