"""PromptEngine — yaml prompt dosyalarını yükle, Jinja2 ile render et.

Yaml dosyaları services/orchestrator/app/prompts/ altında. Her dosya
{ system_prompt: str, user_prompt_template: str } şemasında.

Render davranışı:
- Bilinmeyen placeholder Jinja2 default'ında boş string olarak çıkar
  (DebugUndefined yerine ChainableUndefined kullanmıyoruz; boş string
  pedagojik olarak "bilinmiyor" demektir, hata değil).
- Yine de runtime'da bir placeholder eksik kalırsa **uyarı log'la** —
  test'te yakalanması gerek.
- Sürekli yeniden açma maliyeti yok: dosyaları process boyunca cache'le
  (development'ta bile yeniden başlatınca yenilenir).

Modlar:
  error_explanation, topic_teaching, step_by_step, qa_dialog,
  manim_code, manim_correction
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from jinja2 import ChoiceLoader, DictLoader, Environment, meta

logger = logging.getLogger(__name__)


SUPPORTED_MODES = (
    "error_explanation",
    "topic_teaching",
    "step_by_step",
    "qa_dialog",
    "manim_code",
    "manim_correction",
)


@dataclass(frozen=True)
class PromptPair:
    system_prompt: str
    user_prompt: str


class PromptEngineError(Exception):
    pass


class PromptEngine:
    def __init__(self, prompts_dir: str | None = None):
        # Default: this file's neighbor 'prompts/' directory
        default_dir = str(Path(__file__).parent / "prompts")
        self.dir = Path(prompts_dir or default_dir)
        if not self.dir.is_dir():
            raise PromptEngineError(f"prompts directory not found: {self.dir}")
        self._cache: dict[str, dict[str, str]] = {}     # mode → {system_prompt, user_prompt_template}
        self._env = Environment(
            loader=ChoiceLoader([DictLoader({})]),
            autoescape=False,
            keep_trailing_newline=True,
        )
        self._load_all()

    def _load_all(self) -> None:
        for mode in SUPPORTED_MODES:
            path = self.dir / f"{mode}.yaml"
            if not path.is_file():
                raise PromptEngineError(f"missing prompt file: {path}")
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise PromptEngineError(f"{path}: top-level must be a mapping")
            sp = data.get("system_prompt", "")
            up = data.get("user_prompt_template", "")
            if not isinstance(sp, str) or not isinstance(up, str):
                raise PromptEngineError(f"{path}: system_prompt/user_prompt_template must be strings")
            if not up.strip():
                raise PromptEngineError(f"{path}: user_prompt_template cannot be empty")
            self._cache[mode] = {"system_prompt": sp, "user_prompt_template": up}
            logger.debug("loaded prompt mode=%s sys=%dB user=%dB", mode, len(sp), len(up))

    def modes(self) -> tuple[str, ...]:
        return SUPPORTED_MODES

    def has(self, mode: str) -> bool:
        return mode in self._cache

    def required_vars(self, mode: str) -> set[str]:
        """Template içindeki {{ placeholder }} isimleri (test/audit için)."""
        if mode not in self._cache:
            raise PromptEngineError(f"unknown mode: {mode}")
        ast = self._env.parse(self._cache[mode]["user_prompt_template"])
        return meta.find_undeclared_variables(ast)

    def render(self, mode: str, context: dict) -> PromptPair:
        if mode not in self._cache:
            raise PromptEngineError(f"unknown mode: {mode}")
        templ = self._cache[mode]["user_prompt_template"]
        # Eksik placeholder'ları context'e boş string olarak ekleyelim
        # (production'da sessiz çalışsın). Eksiklikleri logla.
        required = self.required_vars(mode)
        missing = [v for v in required if v not in context]
        if missing:
            logger.warning("prompt mode=%s missing context keys: %s", mode, sorted(missing))
        ctx = {**{k: "" for k in required}, **context}
        rendered_user = self._env.from_string(templ).render(**ctx)
        return PromptPair(
            system_prompt=self._cache[mode]["system_prompt"],
            user_prompt=rendered_user,
        )
